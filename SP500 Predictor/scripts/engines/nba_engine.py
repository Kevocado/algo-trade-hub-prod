"""
NBA Player Props Engine — BallDontLie + LightGBM + Injury Monitor

Strategy:
  1. Fetch recent player game logs from BallDontLie API (free, no key)
  2. Engineer features: rolling pts/reb/ast, usage rate proxy, opponent DRTG,
     pace, home/away, back-to-back flag
  3. Compare model P(over) against Kalshi NBA prop market prices
  4. Flag edges >12% as actionable signals
  5. Monitor ESPN injury API; if new scratch → re-price immediately

Usage:
  engine = NBAEngine()
  signals = engine.get_signals()

Paper trading only. All signals are logged to Supabase paper_trades table.
"""

import re
import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from shared.config import BALLDONTLIE_API_KEY
except ImportError:
    BALLDONTLIE_API_KEY = ""

# BallDontLie repriced/restructured its API in 2025: the free, keyless
# www.balldontlie.io/api/v1 path is deprecated. Current API requires a key
# (free tier still covers basic games/players/stats) at api.balldontlie.io/v1
# with an Authorization header. Fall back to the legacy base if no key is
# configured — it may 404/degrade rather than serve stale data silently.
if BALLDONTLIE_API_KEY:
    BDL_BASE = "https://api.balldontlie.io/v1"
    BDL_HEADERS = {"Authorization": BALLDONTLIE_API_KEY}
else:
    BDL_BASE = "https://www.balldontlie.io/api/v1"
    BDL_HEADERS = {}
    print("⚠️ No BALLDONTLIE_API_KEY configured — falling back to the legacy free "
          "endpoint, which BallDontLie may no longer serve. Set BALLDONTLIE_API_KEY "
          "in .env once a tier is chosen (see KALSHI_SPORTS_CORE_BRIEF.md).")

# ESPN public injury feed (no auth required)
ESPN_INJURY_URL = "https://site.api.espn.com/apis/v2/injuries?sport=basketball&league=nba"

# Kalshi NBA prop integration — Sports-category fetch (see kalshi_feed.py;
# the generic get_all_active_markets() deliberately excludes Sports).
try:
    from src.kalshi_feed import get_active_sports_markets
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False
    print("⚠️ Kalshi feed unavailable — NBA signals will not cross-reference market prices")

try:
    from shared.kalshi_fees import net_edge_pct
except ImportError:
    def net_edge_pct(model_prob_pct, kalshi_price_cents, **_kwargs):
        return model_prob_pct - kalshi_price_cents

# Signal ledger logger (see supabase_client.log_signal_event)
try:
    from src.supabase_client import log_signal_event
except ImportError:
    log_signal_event = None


# ─── Team defensive rating lookup ────────────────────────────────────────────
# These are approximate 2024-25 season defensive ratings (pts allowed per 100 pos).
# Update at season start or pull dynamically from a stats API.
TEAM_DRTG = {
    "BOS": 109.6, "MIL": 110.2, "OKC": 110.8, "MIN": 111.0, "IND": 112.1,
    "NYK": 112.3, "MIA": 112.7, "PHI": 113.5, "CLE": 113.8, "DEN": 114.2,
    "LAL": 114.5, "PHX": 115.0, "SAS": 115.2, "MEM": 115.6, "CHA": 116.0,
    "DET": 116.3, "WAS": 117.2, "POR": 117.5, "GSW": 114.1, "DAL": 114.8,
    "NOP": 115.9, "SAC": 116.7, "UTA": 117.1, "ORL": 113.3, "ATL": 116.2,
    "HOU": 113.9, "BKN": 118.2, "TOR": 116.8, "CHI": 115.4, "LAC": 114.9,
}


class NBAEngine:
    """Scores NBA player props by comparing LightGBM model probabilities to Kalshi prices."""

    def __init__(self, min_edge_pct: float = 12.0, rolling_games: int = 5):
        self.min_edge_pct   = min_edge_pct
        self.rolling_games  = rolling_games
        self._injury_cache: dict = {}
        self._last_injury_fetch: Optional[datetime] = None

    # ─── BallDontLie API helpers ─────────────────────────────────────────────

    def _fetch_players(self, name: str) -> list:
        """Search for a player by name."""
        try:
            r = requests.get(
                f"{BDL_BASE}/players",
                params={"search": name, "per_page": 5},
                headers=BDL_HEADERS,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception as e:
            print(f"  ⚠️ BDL players fetch error: {e}")
        return []

    def _fetch_recent_stats(self, player_id: int, n_games: int = 10) -> pd.DataFrame:
        """
        Fetches the last N games for a player.
        BDL stats endpoint paginates by 25; we take the most recent.
        """
        try:
            r = requests.get(
                f"{BDL_BASE}/stats",
                params={
                    "player_ids[]": player_id,
                    "per_page": n_games,
                    "sort": "game.date:desc",
                    "seasons[]": 2024,  # Current season
                },
                headers=BDL_HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json().get("data", [])
                if not data:
                    return pd.DataFrame()
                rows = []
                for s in data:
                    game = s.get("game", {})
                    home_team_id = game.get("home_team_id")
                    rows.append({
                        "date":       game.get("date", ""),
                        "pts":        s.get("pts") or 0,
                        "reb":        s.get("reb") or 0,
                        "ast":        s.get("ast") or 0,
                        "min":        self._parse_minutes(s.get("min", "0")),
                        "fg_pct":     s.get("fg_pct") or 0,
                        "home":       s.get("team", {}).get("id") == home_team_id,
                        "opp_team_id": (
                            game.get("visitor_team_id")
                            if s.get("team", {}).get("id") == home_team_id
                            else home_team_id
                        ),
                    })
                return pd.DataFrame(rows)
        except Exception as e:
            print(f"  ⚠️ BDL stats fetch error for player {player_id}: {e}")
        return pd.DataFrame()

    def _fetch_todays_games(self) -> list:
        """Returns today's NBA games from BallDontLie."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            r = requests.get(
                f"{BDL_BASE}/games",
                params={"dates[]": today, "per_page": 30},
                headers=BDL_HEADERS,
                timeout=10,
            )
            if r.status_code == 200:
                return r.json().get("data", [])
        except Exception as e:
            print(f"  ⚠️ BDL games fetch error: {e}")
        return []

    @staticmethod
    def _parse_minutes(min_str: str) -> float:
        """Converts '32:14' → 32.23 minutes."""
        try:
            if ":" in str(min_str):
                parts = str(min_str).split(":")
                return int(parts[0]) + int(parts[1]) / 60
            return float(min_str)
        except Exception:
            return 0.0

    def fetch_upcoming_games(self) -> list:
        """Fetches NBA games for the next 7 days using nba_api."""
        try:
            from nba_api.stats.endpoints import scoreboardv2
        except ImportError:
            print("  ⚠️ nba_api not installed.")
            return []
            
        upcoming = []
        now = datetime.now(timezone.utc)
        
        for i in range(1, 8):
            target_date = now + timedelta(days=i)
            date_str = target_date.strftime("%Y-%m-%d")
            try:
                board = scoreboardv2.ScoreboardV2(game_date=date_str)
                line_scores = board.line_score.get_data_frame()
                
                if line_scores.empty:
                    continue
                    
                for game_id, group in line_scores.groupby('GAME_ID'):
                    if len(group) >= 2:
                        away = group.iloc[0]['TEAM_ABBREVIATION']
                        home = group.iloc[1]['TEAM_ABBREVIATION']
                        
                        upcoming.append({
                            "title": f"NBA: {away} @ {home}",
                            "edge_type": "SPORTS",
                            "market_id": f"nba_{game_id}",
                            "our_prob": 0,
                            "market_prob": 0,
                            "raw_payload": {"date": date_str, "away": away, "home": home}
                        })
                time.sleep(0.5)
            except Exception as e:
                print(f"  ⚠️ nba_api error on {date_str}: {e}")
                
        return upcoming

    # ─── Feature Engineering ─────────────────────────────────────────────────

    # _fetch_recent_stats() builds columns from the BDL response using its
    # abbreviated field names (pts/reb/ast); the rest of the engine uses the
    # full stat name ("points"/"rebounds"/"assists") for tickers and prop
    # lines. This mapping is the one place that gap needs to be bridged —
    # previously stat ("points") was looked up directly as a DataFrame
    # column that never existed, so this always silently returned {}.
    STAT_COLUMN = {"points": "pts", "rebounds": "reb", "assists": "ast"}

    def _engineer_features(self, stats_df: pd.DataFrame, stat: str,
                             opp_abbr: str, is_home: bool, is_b2b: bool) -> dict:
        """
        Builds the feature vector for a single prop prediction.

        Features:
        - rolling_avg: rolling N-game average of the target stat
        - rolling_std: rolling standard deviation (volatility)
        - min_avg: average minutes (usage proxy)
        - opp_drtg: opponent defensive rating (lower = harder to score against)
        - home_flag: 1 if home game
        - b2b_flag: 1 if back-to-back (fatigue)
        """
        column = self.STAT_COLUMN.get(stat, stat)
        if stats_df.empty or column not in stats_df.columns:
            return {}

        recent = stats_df.head(self.rolling_games)
        rolling_avg = recent[column].mean()
        rolling_std = recent[column].std() if len(recent) > 1 else 2.0
        min_avg     = recent["min"].mean() if "min" in recent.columns else 28.0
        opp_drtg    = TEAM_DRTG.get(opp_abbr, 114.5)

        return {
            "rolling_avg": rolling_avg,
            "rolling_std": max(rolling_std, 0.5),
            "min_avg":     min_avg,
            "opp_drtg":    opp_drtg,
            "home_flag":   int(is_home),
            "b2b_flag":    int(is_b2b),
        }

    # ─── Probability Model ───────────────────────────────────────────────────

    def _estimate_prob_over(self, features: dict, line: float) -> float:
        """
        Estimates P(player goes OVER the prop line) using a Gaussian model.

        We model performance as Normal(μ=rolling_avg, σ=rolling_std) adjusted
        for opponent quality, home/away, and B2B fatigue.

        - Each point of opponent DRTG above league average (114.5) reduces μ by 0.15 pts
        - Home bonus: +1.0 pt to μ
        - B2B penalty: -2.5 pts to μ

        Uses scipy.stats.norm for the CDF calculation.
        """
        if not features:
            return 0.5  # No data → neutral

        from scipy.stats import norm

        mu  = features["rolling_avg"]
        sigma = features["rolling_std"]
        opp_drtg = features["opp_drtg"]
        league_avg_drtg = 114.5

        # Adjustments
        mu += (league_avg_drtg - opp_drtg) * 0.15  # Tough defense → lower mu
        mu += features["home_flag"] * 1.0            # Home court advantage
        mu -= features["b2b_flag"] * 2.5             # B2B fatigue penalty

        # P(X > line) where X ~ Normal(mu, sigma)
        prob = 1 - norm.cdf(line, loc=mu, scale=max(sigma, 1.0))
        return round(min(max(prob * 100, 2.0), 98.0), 1)  # Clip 2-98%

    # ─── Injury Monitor ──────────────────────────────────────────────────────

    def _fetch_injuries(self) -> dict:
        """
        Fetches current NBA injury report from ESPN.
        Returns {player_name_lower: status_string}.
        Caches for 5 minutes.
        """
        now = datetime.now(timezone.utc)
        if (
            self._last_injury_fetch
            and (now - self._last_injury_fetch).total_seconds() < 300
        ):
            return self._injury_cache

        try:
            r = requests.get(ESPN_INJURY_URL, timeout=10)
            if r.status_code == 200:
                data = r.json()
                injuries = {}
                # ESPN response structure: {teams: [{injuries: [{athlete: {displayName}, status}]}]}
                for team in data.get("injuries", []):
                    for inj in team.get("injuries", []):
                        name   = inj.get("athlete", {}).get("displayName", "").lower()
                        status = inj.get("status", "").lower()
                        if name:
                            injuries[name] = status
                self._injury_cache = injuries
                self._last_injury_fetch = now
                return injuries
        except Exception as e:
            print(f"  ⚠️ ESPN injury fetch error: {e}")
        return self._injury_cache

    def _is_injured(self, player_name: str) -> tuple[bool, str]:
        """Returns (is_out, status_str) for a player."""
        injuries = self._fetch_injuries()
        status = injuries.get(player_name.lower(), "")
        is_out = any(kw in status for kw in ["out", "doubtful", "scratch"])
        return is_out, status

    # ─── Kalshi Cross-Reference ──────────────────────────────────────────────

    STAT_TICKER_PREFIX = {"points": "PTS", "rebounds": "REB", "assists": "AST"}

    def _find_kalshi_props(self, player_name: str, kalshi_markets: list) -> list[dict]:
        """
        Finds every live Kalshi prop market for a player and parses the
        actual line Kalshi is offering out of the ticker (the "O29.5" in
        NBAPTS-LEBRON-O29.5), instead of guessing a fixed line and hoping
        Kalshi happens to be offering a market at exactly that number.

        NOTE: this ticker convention is a starting assumption, not a
        verified Kalshi contract — confirm against a live response before
        trusting it in production. See KALSHI_SPORTS_CORE_BRIEF.md.

        Returns: [{"stat": "points", "line": 29.5, "market": {...}}, ...]
        """
        player_last = player_name.split()[-1].upper() if player_name else ""
        found = []
        for m in kalshi_markets:
            ticker = (m.get("ticker") or "").upper()
            if player_last not in ticker:
                continue
            for stat, prefix in self.STAT_TICKER_PREFIX.items():
                if prefix not in ticker:
                    continue
                line_match = re.search(r"O(\d+(?:\.\d+)?)", ticker)
                if not line_match:
                    continue
                found.append({"stat": stat, "line": float(line_match.group(1)), "market": m})
        return found

    @staticmethod
    def _todays_matchups(todays_games: list) -> dict:
        """
        Maps team abbreviation -> {"is_home": bool, "opponent": abbr} for
        today's games. Also fixes a real bug in the original code: features
        were built by passing a player's own team abbreviation in as the
        *opponent* DRTG lookup key, so "opponent defensive rating" was
        silently scoring a team against its own defense.
        """
        matchups = {}
        for g in todays_games:
            home = g.get("home_team") or {}
            away = g.get("visitor_team") or {}
            home_abbr = home.get("abbreviation")
            away_abbr = away.get("abbreviation")
            if home_abbr and away_abbr:
                matchups[home_abbr] = {"is_home": True, "opponent": away_abbr}
                matchups[away_abbr] = {"is_home": False, "opponent": home_abbr}
        return matchups

    # ─── Main Signal Generator ───────────────────────────────────────────────

    def get_signals(self, player_names: list = None) -> list:
        """
        Main entry point: returns list of NBA prop signal dicts sorted by edge.

        If player_names is None, uses a curated watchlist of high-volume prop players.
        """
        if player_names is None:
            # High-volume NBA prop watchlist — players with consistent Kalshi markets
            player_names = [
                "LeBron James", "Stephen Curry", "Luka Doncic",
                "Giannis Antetokounmpo", "Kevin Durant", "Jayson Tatum",
                "Anthony Davis", "Joel Embiid", "Nikola Jokic",
                "Shai Gilgeous-Alexander", "Damian Lillard", "Tyrese Haliburton",
            ]

        # Fetch today's games for B2B detection and real home/away/opponent resolution
        todays_games = self._fetch_todays_games()
        matchups = self._todays_matchups(todays_games)

        # Fetch Kalshi Sports markets once (Sports category, NBA keyword-filtered)
        kalshi_markets = []
        if KALSHI_AVAILABLE:
            try:
                kalshi_markets = get_active_sports_markets(leagues=["NBA"], limit_pages=5)
                print(f"  🏀 {len(kalshi_markets)} Kalshi NBA markets loaded")
            except Exception as e:
                print(f"  ⚠️ Kalshi fetch error: {e}")

        signals = []

        for player_name in player_names:
            # Fetch player ID
            players = self._fetch_players(player_name)
            if not players:
                print(f"  ⚠️ Player not found: {player_name}")
                continue

            player = players[0]
            player_id = player["id"]
            team_abbr = player.get("team", {}).get("abbreviation", "UNK") if "team" in player else "UNK"

            # Fetch stats
            stats = self._fetch_recent_stats(player_id, n_games=15)
            if stats.empty:
                continue

            # Injury check
            is_out, injury_status = self._is_injured(player_name)
            injury_flag = is_out or bool(injury_status)

            # Simple back-to-back detection (yesterday's game in the dataset)
            yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
            is_b2b = not stats.empty and any(
                str(d)[:10] == yesterday for d in stats.get("date", [])
            )

            matchup = matchups.get(team_abbr)
            if matchup is None:
                print(f"  ⚠️ No game today found for {team_abbr}; skipping {player_name}")
                continue
            is_home = matchup["is_home"]
            opponent_abbr = matchup["opponent"]

            # Only price props Kalshi is actually offering right now — the
            # line itself comes from the market ticker, not a guessed constant.
            live_props = self._find_kalshi_props(player_name, kalshi_markets)
            if not live_props:
                time.sleep(0.1)
                continue

            for prop in live_props:
                stat, line, kalshi_mkt = prop["stat"], prop["line"], prop["market"]
                features = self._engineer_features(stats, stat, opponent_abbr, is_home, is_b2b)
                if not features:
                    continue

                model_prob = self._estimate_prob_over(features, line)
                kalshi_price = float(kalshi_mkt.get("price") or 0)
                if kalshi_price <= 0:
                    continue

                net_edge = net_edge_pct(model_prob, kalshi_price)
                action = None
                if net_edge > self.min_edge_pct:
                    action = "BUY YES"
                elif net_edge < -self.min_edge_pct:
                    action = "BUY NO"

                if abs(net_edge) >= self.min_edge_pct or injury_flag:
                    opportunity = {
                        "engine": "NBA",
                        "asset": player_name,
                        "market_title": f"NBA Prop: {player_name} {stat.capitalize()} (O/U {line})",
                        "market_id": kalshi_mkt.get("ticker") or f"nba_prop_{stat}_{player_name.replace(' ', '_').upper()}",
                        "edge_type": "SPORTS",
                        "action": action if action else "MONITOR",
                        "edge": abs(net_edge),
                        "confidence": model_prob,
                        "reasoning": (
                            f"Model forecasts {model_prob}% probability of OVER {line} {stat}. "
                            f"Kalshi price: {kalshi_price:.0f}c, net-of-fees edge {net_edge:+.1f}pp."
                            + (f" ⚠️ INJURY STATUS: {injury_status}" if injury_flag else "")
                        ),
                        "data_source": "BallDontLie + Gaussian Regression",
                        "ui_reasoning": False,
                        "raw_payload": {
                            "player": player_name,
                            "stat": stat,
                            "line": line,
                            "kalshi_ticker": kalshi_mkt.get("ticker"),
                            "kalshi_price": kalshi_price,
                            "net_edge_pct": net_edge,
                            "injury_flag": injury_flag,
                            "is_b2b": is_b2b,
                            "is_home": is_home,
                            "opponent": opponent_abbr,
                        }
                    }
                    signals.append(opportunity)

                    if log_signal_event is not None:
                        try:
                            log_signal_event(
                                domain="nba",
                                asset=player_name,
                                source_market_ticker=kalshi_mkt.get("ticker") or "",
                                desired_side="YES" if (action == "BUY YES") else ("NO" if action == "BUY NO" else ""),
                                model_probability_yes=round(model_prob / 100, 4),
                                kalshi_price_dollars=round(kalshi_price / 100, 4),
                                edge=round(net_edge / 100, 4),
                                payload=opportunity["raw_payload"],
                            )
                        except Exception as e:
                            print(f"  ⚠️ Failed to log signal event: {e}")

                time.sleep(0.1)  # Rate limit BallDontLie

        # Sort by absolute edge
        signals.sort(key=lambda x: abs(x.get("edge", 0)), reverse=True)

        print(f"  🏀 NBA Engine: {len(signals)} signals generated")
        return signals


# ── Dev entrypoint ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🏀 NBA Engine — Running signal scan...\n")
    engine = NBAEngine(min_edge_pct=10.0)
    signals = engine.get_signals(player_names=[
        "LeBron James", "Stephen Curry", "Luka Doncic"
    ])
    print(f"\n✅ Signals found: {len(signals)}")
    for s in signals[:5]:
        rp = s["raw_payload"]
        print(
            f"  {rp['player']} {rp['stat']} O/U {rp['line']} | "
            f"Model: {s['confidence']}% | "
            f"Kalshi: {rp.get('kalshi_price', 'N/A')}c | "
            f"Edge: +{s['edge']:.1f}% | "
            f"{'⚠️ INJURED' if rp['injury_flag'] else ''}"
        )
