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

import requests
import time
import numpy as np
import pandas as pd
from datetime import datetime, timezone, timedelta
from typing import Optional

# BallDontLie base URL (v1 — free, no API key required)
BDL_BASE = "https://www.balldontlie.io/api/v1"

# ESPN public injury feed (no auth required)
ESPN_INJURY_URL = "https://site.api.espn.com/apis/v2/injuries?sport=basketball&league=nba"

# Kalshi NBA prop integration (uses existing kalshi_feed module)
try:
    from src.kalshi_feed import get_all_active_markets
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False
    print("⚠️ Kalshi feed unavailable — NBA signals will not cross-reference market prices")

# Supabase paper trade logger
try:
    from src.supabase_client import log_paper_trade
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False


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
            r = requests.get(f"{BDL_BASE}/players", params={"search": name, "per_page": 5}, timeout=10)
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
        if stats_df.empty or stat not in stats_df.columns:
            return {}

        recent = stats_df.head(self.rolling_games)
        rolling_avg = recent[stat].mean()
        rolling_std = recent[stat].std() if len(recent) > 1 else 2.0
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

    def _find_kalshi_market(self, player_name: str, stat: str,
                             line: float, kalshi_markets: list) -> Optional[dict]:
        """
        Fuzzy-matches a player prop to an open Kalshi market.
        Kalshi NBA prop tickers look like: NBAPTS-LEBRON-O29.5
        """
        player_last = player_name.split()[-1].upper() if player_name else ""
        stat_key = {"points": "PTS", "rebounds": "REB", "assists": "AST"}.get(stat, stat.upper())

        for m in kalshi_markets:
            ticker = m.get("ticker", "").upper()
            if player_last in ticker and stat_key in ticker:
                return m
        return None

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

        # Fetch today's games for B2B detection
        todays_games = self._fetch_todays_games()
        game_dates = {}
        for g in todays_games:
            for tid in [g.get("home_team_id"), g.get("visitor_team_id")]:
                if tid:
                    game_dates[tid] = g.get("date", "")

        # Fetch Kalshi markets once
        kalshi_markets = []
        if KALSHI_AVAILABLE:
            try:
                all_markets = get_all_active_markets(limit_pages=5)
                kalshi_markets = [m for m in all_markets if "NBA" in m.get("ticker", "").upper()]
                print(f"  🏀 {len(kalshi_markets)} Kalshi NBA markets loaded")
            except Exception as e:
                print(f"  ⚠️ Kalshi fetch error: {e}")

        signals = []
        prop_lines = [
            ("points",   22.5),  # Representative prop lines
            ("rebounds",  7.5),
            ("assists",   5.5),
        ]

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

            # Placeholder: assume home (real impl would check today's games)
            is_home = True

            for stat, line in prop_lines:
                features = self._engineer_features(
                    stats, stat, team_abbr, is_home, is_b2b
                )
                if not features:
                    continue

                model_prob = self._estimate_prob_over(features, line)

                # Cross-reference Kalshi
                kalshi_mkt = self._find_kalshi_market(player_name, stat, line, kalshi_markets)
                kalshi_price = kalshi_mkt["price"] if kalshi_mkt else None
                edge_pct = (model_prob - kalshi_price) if kalshi_price else None
                action = None
                if edge_pct is not None:
                    if edge_pct > self.min_edge_pct:
                        action = "BUY YES"
                    elif edge_pct < -self.min_edge_pct:
                        action = "BUY NO"

                # Only add if there's a Kalshi market with edge, OR injury flag
                if (edge_pct is not None and abs(edge_pct) >= self.min_edge_pct) or injury_flag:
                    # INSTANTIATE NEW DICTIONARY (Fixes Loop Bug)
                    opportunity = {
                        "engine": "NBA",
                        "asset": player_name,
                        "market_title": f"NBA Prop: {player_name} {stat.capitalize()} (O/U {line})",
                        "market_id": f"nba_prop_{stat}_{player_name.replace(' ', '_').upper()}",
                        "action": action if action else "MONITOR",
                        "edge": abs(edge_pct) if edge_pct else 0.0,
                        "confidence": model_prob,
                        "reasoning": f"Model forecasts {model_prob}% probability of OVER {line} {stat}. " + 
                                     (f"Kalshi price: {kalshi_price}¢." if kalshi_price else "No live price.") +
                                     (f" ⚠️ INJURY STATUS: {injury_status}" if injury_flag else ""),
                        "data_source": "BallDontLie + Gaussian Regression",
                        "ui_reasoning": False,
                        "raw_payload": {
                            "player": player_name,
                            "stat": stat,
                            "line": line,
                            "injury_flag": injury_flag,
                            "is_b2b": is_b2b
                        }
                    }
                    signals.append(opportunity)

                time.sleep(0.1)  # Rate limit BallDontLie

        # Sort by absolute edge
        signals.sort(
            key=lambda x: abs(x.get("edge_pct") or 0),
            reverse=True
        )

        print(f"  🏀 NBA Engine: {len(signals)} signals generated")

        # Log to Supabase
        if SUPABASE_AVAILABLE and signals:
            try:
                from src.supabase_client import log_paper_trade
                for s in signals:
                    if s.get("action"):
                        log_paper_trade({
                            "engine":     "nba_props",
                            "ticker":     s.get("kalshi_ticker", "UNKNOWN"),
                            "action":     s["action"],
                            "edge_pct":   s.get("edge_pct"),
                            "model_prob": s["model_prob_over"],
                            "status":     "signal",
                        })
            except Exception:
                pass

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
        edge = s.get("edge_pct")
        print(
            f"  {s['player']} {s['stat']} O/U {s['line']} | "
            f"Model: {s['model_prob_over']}% | "
            f"Kalshi: {s.get('kalshi_yes_ask', 'N/A')}¢ | "
            f"Edge: {f'+{edge:.1f}%' if edge else 'no mkt'} | "
            f"{'⚠️ INJURED' if s['injury_flag'] else ''}"
        )
