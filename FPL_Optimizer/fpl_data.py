"""
fpl_data.py — thin client for the live FPL API: current player pool,
prices/availability, and each team's next fixture + official difficulty.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import requests

BASE_URL = "https://fantasy.premierleague.com/api"
HISTORY_CACHE_DIR = Path(__file__).parent / "data_cache" / "live_history"
HISTORY_CACHE_TTL_SECONDS = 6 * 3600

POSITION_MAP = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}

# Columns element-summary returns as strings; cast to float for feature use.
NUMERIC_STRING_COLS = ["influence", "creativity", "threat", "ict_index", "expected_goals", "expected_assists"]


def fetch_bootstrap() -> Dict:
    resp = requests.get(f"{BASE_URL}/bootstrap-static/", timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_fixtures() -> List[Dict]:
    resp = requests.get(f"{BASE_URL}/fixtures/", timeout=30)
    resp.raise_for_status()
    return resp.json()


def fixtures_as_frame(fixtures: List[Dict]) -> pd.DataFrame:
    df = pd.DataFrame(fixtures)
    return df[["id", "event", "team_h", "team_a", "team_h_difficulty", "team_a_difficulty", "finished"]]


def get_next_event_id(bootstrap: Dict) -> Optional[int]:
    events = bootstrap.get("events", [])
    for e in events:
        if e.get("is_next"):
            return e["id"]
    unfinished = [e["id"] for e in events if not e.get("finished")]
    return min(unfinished) if unfinished else None


def build_player_table(bootstrap: Dict) -> pd.DataFrame:
    teams = {t["id"]: t["name"] for t in bootstrap["teams"]}
    rows = []
    for el in bootstrap["elements"]:
        rows.append(
            {
                "id": el["id"],
                "name": f"{el['first_name']} {el['second_name']}",
                "web_name": el["web_name"],
                "team": teams.get(el["team"], "Unknown"),
                "team_id": el["team"],
                "position": POSITION_MAP.get(el["element_type"], "Unknown"),
                "price": el["now_cost"] / 10.0,
                "status": el["status"],  # a=available, i=injured, d=doubtful, s=suspended, u=unavailable
                "news": el.get("news", ""),
                "chance_of_playing_next_round": el.get("chance_of_playing_next_round"),
                "selected_by_percent": float(el.get("selected_by_percent", 0) or 0),
                "form": float(el.get("form", 0) or 0),
            }
        )
    return pd.DataFrame(rows)


def build_next_fixture_map(fixtures: List[Dict], next_event: int) -> Dict[int, Dict]:
    """team_id -> {opponent_team_id, was_home, difficulty}. Teams with a blank
    gameweek (no fixture) are simply absent from the map. If a team has a
    double gameweek, only the first fixture is used."""
    team_fixtures: Dict[int, Dict] = {}
    for f in fixtures:
        if f.get("event") != next_event:
            continue
        home, away = f["team_h"], f["team_a"]
        if home not in team_fixtures:
            team_fixtures[home] = {
                "opponent_team_id": away,
                "was_home": True,
                "difficulty": f["team_h_difficulty"],
            }
        if away not in team_fixtures:
            team_fixtures[away] = {
                "opponent_team_id": home,
                "was_home": False,
                "difficulty": f["team_a_difficulty"],
            }
    return team_fixtures


def fetch_player_summary(player_id: int, current_event: Optional[int] = None):
    """Returns (history_df, prior_season_row) for one player:
    - history_df: this season's played-gameweek rows so far.
    - prior_season_row: dict of last season's season-total stats (for
      players with little/no current-season data yet), or None if the
      player has no FPL history at all (e.g. straight from the Championship).

    Cached on disk, keyed by the current gameweek so it auto-invalidates once
    a new gameweek starts, and also expires after a few hours within a
    gameweek."""
    HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = HISTORY_CACHE_DIR / f"{player_id}.json"

    if cache_path.exists():
        cached = json.loads(cache_path.read_text())
        fresh_gw = cached.get("current_event") == current_event
        fresh_time = (time.time() - cached.get("fetched_at", 0)) < HISTORY_CACHE_TTL_SECONDS
        if fresh_gw and fresh_time:
            return _normalize_history(pd.DataFrame(cached["history"])), cached.get("prior_season")

    resp = requests.get(f"{BASE_URL}/element-summary/{player_id}/", timeout=30)
    resp.raise_for_status()
    data = resp.json()
    history = data.get("history", [])
    history_past = data.get("history_past", [])
    prior_season = history_past[-1] if history_past else None

    cache_path.write_text(
        json.dumps(
            {
                "current_event": current_event,
                "fetched_at": time.time(),
                "history": history,
                "prior_season": prior_season,
            }
        )
    )
    return _normalize_history(pd.DataFrame(history)), prior_season


def _normalize_history(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.rename(columns={"round": "GW"})
    for col in NUMERIC_STRING_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df
