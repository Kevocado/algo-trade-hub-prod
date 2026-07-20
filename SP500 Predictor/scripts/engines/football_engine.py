"""
football_engine.py — Football Dixon-Coles Engine
Detects +EV opportunities in Kalshi Premier League and La Liga markets.
"""

import re
import time
import logging
import requests
from datetime import datetime, timedelta, timezone
from scipy.stats import poisson
from understatapi import UnderstatClient

import sys
import os
from pathlib import Path
# Add project root to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.append(os.getcwd())

from shared import config
from shared.kalshi_fees import net_edge_pct
from src.kalshi_feed import get_active_sports_markets
from scripts.engines.dixon_coles import fit_dixon_coles, DixonColesModel

try:
    from src.supabase_client import log_signal_event
except ImportError:
    log_signal_event = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FOOTBALL-ENGINE] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

class FootballKalshiEngine:
    def __init__(self):
        self.football_api_key = config.FOOTBALL_DATA_API_KEY
        self.headers = {"X-Auth-Token": self.football_api_key} if self.football_api_key else {}
        self.understat = UnderstatClient()
        self.edge_threshold = 8.0  # 8% net-of-fees edge required

        # Mapping football-data.org competition codes to Understat league names
        self.league_map = {
            "PL": "EPL",
            "PD": "La_liga"
        }

        # Per-run caches so a single find_opportunities() call fits one
        # league's season data and Dixon-Coles model once, not once per match.
        self._season_match_cache: dict[str, list[dict]] = {}
        self._dc_model_cache: dict[str, DixonColesModel] = {}

    def fetch_fixtures(self):
        """Fetch upcoming La Liga (PD) and Premier League (PL) matches for the next 48 hours."""
        if not self.football_api_key:
            log.warning("No FOOTBALL_DATA_API_KEY. Cannot fetch fixtures.")
            return []
            
        now = datetime.now(timezone.utc)
        date_from = now.strftime("%Y-%m-%d")
        date_to = (now + timedelta(days=7)).strftime("%Y-%m-%d")
        
        url = f"https://api.football-data.org/v4/matches?competitions=PL,PD,CL&dateFrom={date_from}&dateTo={date_to}"
        log.info(f"Fetching football fixtures from {date_from} to {date_to}...")
        
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                matches = resp.json().get("matches", [])
                log.info(f"Found {len(matches)} upcoming PL/La Liga matches.")
                return matches
            else:
                log.error(f"Failed to fetch fixtures: {resp.status_code} - {resp.text}")
                return []
        except Exception as e:
            log.error(f"Error fetching football fixtures: {e}")
            return []

    def _normalize_team_name(self, name):
        """Basic normalizer to match API team names with Understat."""
        name = name.replace(" FC", "").replace(" AFC", "").replace(" Hotspur", "")
        name = name.replace("Real Madrid", "Real Madrid").replace("Atletico", "Atletico Madrid")
        name = name.replace("Manchester United", "Manchester United").replace("Manchester City", "Manchester City")
        return name.strip()

    def _fetch_season_matches(self, league_code):
        """
        Fetches every finished match in the current season for a league,
        once per engine run (cached on self), for Dixon-Coles fitting.
        Replaces the old per-team last-5-games xG fetch, which re-pulled the
        entire league table once per team per match.
        """
        if league_code in self._season_match_cache:
            return self._season_match_cache[league_code]

        understat_league = self.league_map.get(league_code, "EPL")
        current_year = datetime.now().year
        season_year = current_year if datetime.now().month > 7 else current_year - 1

        time.sleep(3)  # CRITICAL: Prevent IP Ban — one call per league per run now, not per team
        try:
            raw = self.understat.league(league=understat_league).get_match_data(season=str(season_year))
            finished = [m for m in raw if m.get("isResult") is True]
        except Exception as e:
            log.error(f"Failed to fetch season match data for {league_code}: {e}")
            finished = []

        self._season_match_cache[league_code] = finished
        return finished

    def _get_dixon_coles_model(self, league_code):
        """Fits (or returns the cached) Dixon-Coles model for a league's current season."""
        if league_code in self._dc_model_cache:
            return self._dc_model_cache[league_code]

        raw_matches = self._fetch_season_matches(league_code)
        parsed = []
        for m in raw_matches:
            try:
                match_date = None
                if m.get("datetime"):
                    match_date = datetime.strptime(m["datetime"], "%Y-%m-%d %H:%M:%S")
                parsed.append({
                    "home": self._normalize_team_name(m["h"]["title"]),
                    "away": self._normalize_team_name(m["a"]["title"]),
                    "home_goals": int(float(m["goals"]["h"])),
                    "away_goals": int(float(m["goals"]["a"])),
                    "date": match_date,
                })
            except (KeyError, TypeError, ValueError):
                continue

        if len(parsed) < 30:
            log.warning(f"Only {len(parsed)} finished matches for {league_code}; not enough to fit Dixon-Coles.")
            return None

        try:
            model = fit_dixon_coles(parsed)
        except Exception as e:
            log.error(f"Dixon-Coles fit failed for {league_code}: {e}")
            return None

        self._dc_model_cache[league_code] = model
        return model

    def _match_fixture_markets(self, home_team, away_team, sports_markets):
        """
        Best-effort match of a fixture to its live Kalshi HOME_WIN/DRAW/AWAY_WIN
        markets. Returns {"HOME_WIN": market|None, "DRAW": market|None, "AWAY_WIN": market|None}.
        Kalshi's exact soccer market naming should be spot-checked against a live
        response before trusting this blindly — see KALSHI_SPORTS_CORE_BRIEF.md.
        """
        home_key = self._normalize_team_name(home_team).lower()
        away_key = self._normalize_team_name(away_team).lower()
        home_token = home_key.split()[0] if home_key else ""
        away_token = away_key.split()[0] if away_key else ""

        # Group by event_ticker first, unfiltered — a "Draw" market's own
        # title never mentions either team, so filtering by team-name match
        # before grouping would silently drop it from its own fixture.
        by_event = {}
        for m in sports_markets:
            event_ticker = m.get("event_ticker") or ""
            by_event.setdefault(event_ticker, []).append(m)

        matched = {"HOME_WIN": None, "DRAW": None, "AWAY_WIN": None}
        for event_ticker, markets in by_event.items():
            combined_titles = " | ".join((m.get("title") or "").lower() for m in markets)
            has_home = home_token in combined_titles
            has_away = away_token in combined_titles
            if event_ticker:
                # Trust Kalshi's own event grouping; just confirm it's not a
                # completely unrelated fixture.
                if not (has_home or has_away):
                    continue
            elif not (has_home and has_away):
                # No event grouping to lean on — require both team names as
                # a safety net against merging unrelated ungrouped markets.
                continue

            for m in markets:
                title = (m.get("title") or "").lower()
                if "draw" in title or "tie" in title:
                    matched["DRAW"] = m
                elif home_token in title:
                    matched["HOME_WIN"] = m
                elif away_token in title:
                    matched["AWAY_WIN"] = m
            break  # first event that looks like our fixture is the one we want
        return matched

    def calculate_poisson_edge(self, home_xg, away_xg):
        """Simulate match result probabilities using Poisson distribution."""
        home_win_prob = 0.0
        draw_prob = 0.0
        away_win_prob = 0.0
        
        # Simulate grid of goals from 0 to 7
        for home_goals in range(8):
            for away_goals in range(8):
                prob = poisson.pmf(home_goals, home_xg) * poisson.pmf(away_goals, away_xg)
                
                if home_goals > away_goals:
                    home_win_prob += prob
                elif home_goals == away_goals:
                    draw_prob += prob
                else:
                    away_win_prob += prob
                    
        return {
            "HOME_WIN": home_win_prob * 100,
            "DRAW": draw_prob * 100,
            "AWAY_WIN": away_win_prob * 100
        }

    def evaluate_market(self, match_title, prediction_type, model_prob, kalshi_price):
        """Compare model probability to a real Kalshi market price. Returns a
        payload only if the gap clears self.edge_threshold; otherwise None."""
        diff = model_prob - kalshi_price

        if abs(diff) < self.edge_threshold:
            return None

        return {
            "market_id": f"FOOTBALL_{match_title.replace(' ', '_').upper()}_{prediction_type}",
            "title": f"Kalshi Football: {match_title} ({prediction_type})",
            "edge_type": "SPORTS",
            "our_prob": round(model_prob / 100, 4),
            "market_prob": round(kalshi_price / 100, 4),
            "edge_pct": round(diff / 100, 4),
            "raw_payload": {
                "subsystem": "SOCCER",
                "match": match_title,
                "prediction": prediction_type,
                "model_probability": round(model_prob, 2),
                "kalshi_price": round(kalshi_price, 2)
            }
        }

    def find_opportunities(self):
        """Master method to run the football engine evaluation loop."""
        opportunities = []
        fixtures = self.fetch_fixtures()
        if not fixtures:
            return opportunities

        try:
            sports_markets = get_active_sports_markets(leagues=["EPL", "LALIGA"])
            log.info(f"Loaded {len(sports_markets)} live Kalshi soccer markets.")
        except Exception as e:
            log.error(f"Failed to load Kalshi soccer markets: {e}")
            sports_markets = []

        # Limit to 10 matches per run
        for match in fixtures[:10]:
            try:
                home_team = match["homeTeam"]["name"]
                away_team = match["awayTeam"]["name"]
                league = match["competition"]["code"]
                match_title = f"{home_team} vs {away_team}"

                dc_model = self._get_dixon_coles_model(league)
                if dc_model is None:
                    log.warning(f"No fitted Dixon-Coles model for {league}; skipping {match_title}.")
                    continue

                home_key = self._normalize_team_name(home_team)
                away_key = self._normalize_team_name(away_team)
                if home_key not in dc_model.teams or away_key not in dc_model.teams:
                    log.warning(f"{home_key} or {away_key} not in fitted {league} model; skipping {match_title}.")
                    continue

                probs = dc_model.match_probabilities(home_key, away_key)
                fixture_markets = self._match_fixture_markets(home_team, away_team, sports_markets)

                for outcome in ("HOME_WIN", "DRAW", "AWAY_WIN"):
                    market = fixture_markets.get(outcome)
                    if market is None:
                        # No live Kalshi market for this outcome — do not fabricate a price.
                        continue

                    kalshi_price = float(market.get("price") or 0)
                    if kalshi_price <= 0:
                        continue
                    model_prob = probs[outcome]

                    net_edge = net_edge_pct(model_prob, kalshi_price)
                    payload = self.evaluate_market(match_title, outcome, model_prob, kalshi_price)
                    if payload is None or abs(net_edge) < self.edge_threshold:
                        continue

                    gross_edge = model_prob - kalshi_price
                    opportunity = {
                        "engine": "Soccer",
                        "asset": match_title,
                        "market_title": f"Soccer: {match_title} ({outcome})",
                        "market_id": market.get("ticker") or payload["market_id"],
                        "edge_type": "SPORTS",
                        "action": "BUY YES" if gross_edge > 0 else "BUY NO",
                        "edge": abs(net_edge),
                        "confidence": model_prob,
                        "reasoning": (
                            f"Dixon-Coles model: Pr({outcome}) = {model_prob:.1f}%. "
                            f"Kalshi price: {kalshi_price:.0f}c. Gross edge {gross_edge:+.1f}pp, "
                            f"net of Kalshi fees {net_edge:+.1f}pp."
                        ),
                        "data_source": "Understat season data + Dixon-Coles",
                        "ui_reasoning": False,  # Default to False, updated by background_scanner for top 3
                        "raw_payload": {
                            "league": league,
                            "outcome": outcome,
                            "kalshi_ticker": market.get("ticker"),
                            "gross_edge_pct": gross_edge,
                            "net_edge_pct": net_edge,
                        },
                    }
                    opportunities.append(opportunity)
                    log.info(f"🚨 FOUND EDGE: {opportunity['market_title']} (net {net_edge:.1f}pp)")

                    if log_signal_event is not None:
                        try:
                            log_signal_event(
                                domain="football",
                                asset=match_title,
                                source_market_ticker=market.get("ticker") or "",
                                desired_side="YES" if gross_edge > 0 else "NO",
                                model_probability_yes=round(model_prob / 100, 4),
                                kalshi_price_dollars=round(kalshi_price / 100, 4),
                                edge=round(net_edge / 100, 4),
                                payload=opportunity["raw_payload"],
                            )
                        except Exception as e:
                            log.warning(f"Failed to log signal event: {e}")

            except Exception as e:
                log.error(f"Error processing match loop: {e}")
                continue

        return opportunities

if __name__ == "__main__":
    engine = FootballKalshiEngine()
    ops = engine.find_opportunities()
    print(f"Found {len(ops)} edges.")
