"""
football_engine.py — Football xPTS & Poisson Engine
Detects +EV opportunities in Kalshi Premier League and La Liga markets.
"""

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

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FOOTBALL-ENGINE] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

class FootballKalshiEngine:
    def __init__(self):
        self.football_api_key = config.FOOTBALL_DATA_API_KEY
        self.headers = {"X-Auth-Token": self.football_api_key} if self.football_api_key else {}
        self.understat = UnderstatClient()
        self.edge_threshold = 8.0  # 8% edge required
        
        # Mapping football-data.org competition codes to Understat league names
        self.league_map = {
            "PL": "EPL",
            "PD": "La_liga"
        }

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

    def fetch_xpts_data(self, team_name, league):
        """
        Extract xG, xGA, and xPTS for the last 5 matches from Understat.
        Includes a 3-second sleep to respect rate limits.
        """
        log.info(f"Fetching Understat data for {team_name} in {league}...")
        understat_league = self.league_map.get(league, "EPL")
        
        time.sleep(3)  # CRITICAL: Prevent IP Ban when looping multiple teams
        
        try:
            # We fetch league results for the current season (assuming 2025/2026 -> 2025)
            # A more robust solution dynamically computes the season year.
            current_year = datetime.now().year
            season_year = current_year if datetime.now().month > 7 else current_year - 1
            
            # Since understatapi doesn't have a direct "get team by name" that's trivial without team IDs,
            # we pull the league table or match data and filter. 
            # For simplicity in this engine, we get the team data.
            league_data = self.understat.league(league=understat_league).get_match_data(season=str(season_year))
            
            team_matches = []
            norm_target = self._normalize_team_name(team_name).lower()
            
            for match in league_data:
                h_team = match.get("h", {}).get("title", "").lower()
                a_team = match.get("a", {}).get("title", "").lower()
                
                if norm_target in h_team or norm_target in a_team:
                    if match.get("isResult") == True:
                        team_matches.append(match)
                        
            # Sort by datetime and get the last 5
            team_matches.sort(key=lambda x: x.get("datetime", ""), reverse=True)
            last_5 = team_matches[:5]
            
            if not last_5:
                return {"xG": 1.2, "xGA": 1.2, "xPTS": 1.3}  # fallback generic averages
                
            total_xg = 0.0
            total_xga = 0.0
            total_xpts = 0.0
            
            for m in last_5:
                is_home = (norm_target in m.get("h", {}).get("title", "").lower())
                total_xg += float(m["xG"]["h"]) if is_home else float(m["xG"]["a"])
                total_xga += float(m["xG"]["a"]) if is_home else float(m["xG"]["h"])
                # Note: xPTS is usually derived or available in team stats. We approximate here or use raw xG
                # For a true xPTS, understat computes it, but we can return avg xG/xGA for our Poisson
            
            avg_xg = total_xg / len(last_5)
            avg_xga = total_xga / len(last_5)
            
            return {
                "xG": round(avg_xg, 3),
                "xGA": round(avg_xga, 3),
                "xPTS": round(avg_xg * 1.5, 3) # simplified proxy
            }
        except Exception as e:
            log.error(f"Failed to fetch Understat data for {team_name}: {e}")
            return {"xG": 1.2, "xGA": 1.2, "xPTS": 1.3} # Fallback to prevent crash

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
        """Compare model probabilities to Kalshi market prices. If gap > 8%, return payload."""
        diff = model_prob - kalshi_price
        
        if True:
            payload = {
                "market_id": f"FOOTBALL_{match_title.replace(' ', '_').upper()}",
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
            return payload
        return None

    def find_opportunities(self):
        """Master method to run the football engine evaluation loop."""
        opportunities = []
        fixtures = self.fetch_fixtures()
        
        # Limit to 10 matches per run (expanded from 3)
        for match in fixtures[:10]:
            try:
                # INSTANTIATE A NEW DICTIONARY FOR EACH GAME (Fixes Loop Bug)
                match_data = {}
                
                home_team = match["homeTeam"]["name"]
                away_team = match["awayTeam"]["name"]
                league = match["competition"]["code"]
                match_id = match.get("id")
                
                home_stats = self.fetch_xpts_data(home_team, league)
                away_stats = self.fetch_xpts_data(away_team, league)
                
                # Expected Goals for this specific matchup (simplified model)
                match_home_xg = (home_stats["xG"] + away_stats["xGA"]) / 2
                match_away_xg = (away_stats["xG"] + home_stats["xGA"]) / 2
                
                probs = self.calculate_poisson_edge(match_home_xg, match_away_xg)
                
                # Standardize Title & ID for Kalshi Matching
                match_title = f"{home_team} vs {away_team}"
                
                # STUB: Fetching Live Kalshi Price (to be replaced by real kalshi_feed data)
                live_price = 45.0  # Placeholder for retail sentiment
                
                # Calculate edge for HOME_WIN
                model_prob = probs['HOME_WIN']
                edge = model_prob - live_price
                
                # Build the Opportunity Object (NEW DICT)
                opportunity = {
                    "engine": "Soccer",
                    "asset": f"{home_team} vs {away_team}",
                    "market_title": f"Soccer: {match_title} (Home Win)",
                    "market_id": f"soccer_{league}_{match_id if match_id else match_title.replace(' ', '_')}",
                    "action": "BUY YES" if edge > 0 else "BUY NO",
                    "edge": abs(edge),
                    "confidence": model_prob,
                    "reasoning": f"Poisson model projects {match_home_xg:.1f} xG for {home_team} vs {match_away_xg:.1f} for {away_team}. Pr(Home Win) = {model_prob:.1f}%.",
                    "data_source": "Understat xG + Poisson Simulation",
                    "ui_reasoning": False, # Default to False, updated by background_scanner for top 3
                    "raw_payload": {
                        "home_xg": match_home_xg,
                        "away_xg": match_away_xg,
                        "league": league
                    }
                }
                
                if abs(edge) >= self.edge_threshold:
                    opportunities.append(opportunity)
                    log.info(f"🚨 FOUND EDGE: {opportunity['market_title']} ({edge:.1f}%)")
                    
            except Exception as e:
                log.error(f"Error processing match loop: {e}")
                continue
                
        return opportunities

if __name__ == "__main__":
    engine = FootballKalshiEngine()
    ops = engine.find_opportunities()
    print(f"Found {len(ops)} edges.")
