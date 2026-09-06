"""
historical_data.py — fetch and cache past-season gameweek data for training.

Source: vaastav's Fantasy-Premier-League GitHub repo, which has one CSV per
season with a row per player per gameweek (points, minutes, xG, xA, bps,
opponent, etc.), plus a fixtures.csv per season carrying FPL's own official
fixture difficulty rating (1-5).
"""

import io
from datetime import date
from pathlib import Path
from typing import List

import pandas as pd
import requests

BASE_URL = "https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League/master/data"
CACHE_DIR = Path(__file__).parent / "data_cache"

# Some older seasons use different short position codes.
POSITION_ALIASES = {"GKP": "GK"}


def season_str(start_year: int) -> str:
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def current_season_start_year(today: date | None = None) -> int:
    """The Premier League season starts around July/August."""
    today = today or date.today()
    return today.year if today.month >= 7 else today.year - 1


def default_completed_seasons(n: int = 4, today: date | None = None) -> List[str]:
    """Last n *completed* seasons (excludes the season currently in progress,
    since it won't have a full set of gameweeks yet and is handled separately
    via the live FPL API in fpl_data.py)."""
    last_completed = current_season_start_year(today) - 1
    return [season_str(y) for y in range(last_completed - n + 1, last_completed + 1)]


def _cached_csv(url: str, cache_path: Path, attempts: int = 3) -> pd.DataFrame | None:
    if cache_path.exists():
        return pd.read_csv(cache_path)

    resp = None
    for attempt in range(attempts):
        try:
            resp = requests.get(url, timeout=60)
            break
        except requests.exceptions.RequestException:
            if attempt == attempts - 1:
                raise
    if resp is None or resp.status_code != 200:
        return None

    CACHE_DIR.mkdir(exist_ok=True)
    df = pd.read_csv(io.StringIO(resp.text))
    df.to_csv(cache_path, index=False)
    return df


def fetch_season_gw_data(season: str) -> pd.DataFrame | None:
    url = f"{BASE_URL}/{season}/gws/merged_gw.csv"
    df = _cached_csv(url, CACHE_DIR / f"{season}_merged_gw.csv")
    if df is None:
        return None
    df = df.copy()
    df["season"] = season
    if "position" in df.columns:
        df["position"] = df["position"].replace(POSITION_ALIASES)
    return df


def fetch_season_fixtures(season: str) -> pd.DataFrame | None:
    url = f"{BASE_URL}/{season}/fixtures.csv"
    return _cached_csv(url, CACHE_DIR / f"{season}_fixtures.csv")


def load_training_data(seasons: List[str] | None = None) -> pd.DataFrame:
    """Load and concatenate gameweek data for the given (or default) seasons,
    with each row's fixture difficulty attached."""
    from features import attach_fixture_difficulty

    seasons = seasons or default_completed_seasons()

    frames = []
    for season in seasons:
        gw_df = fetch_season_gw_data(season)
        if gw_df is None or gw_df.empty:
            print(f"  ! Skipping {season}: no gameweek data available")
            continue

        fixtures_df = fetch_season_fixtures(season)
        if fixtures_df is not None:
            gw_df = attach_fixture_difficulty(gw_df, fixtures_df)
        else:
            gw_df["opponent_difficulty"] = 3.0

        print(f"  > {season}: {len(gw_df)} player-gameweek rows")
        frames.append(gw_df)

    if not frames:
        raise RuntimeError("No historical season data could be loaded")

    return pd.concat(frames, ignore_index=True)
