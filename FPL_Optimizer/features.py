"""
features.py — feature engineering shared by training (train.py) and
scouting (scout.py), so both build features the exact same way.
"""

from typing import List, Tuple

import numpy as np
import pandas as pd

# Base stats we compute rolling averages for. Only ones actually present in
# a given dataset are used (older seasons lack some expected-stat columns).
LAG_BASE_FEATURES = [
    "minutes",
    "total_points",
    "goals_scored",
    "assists",
    "bps",
    "ict_index",
    "influence",
    "creativity",
    "threat",
    "clean_sheets",
    "goals_conceded",
    "saves",
    "expected_goals",
    "expected_assists",
]
LAG_WINDOWS = [3, 5]

EXTRA_FEATURES = ["was_home", "opponent_difficulty", "value"]


def attach_fixture_difficulty(gw_df: pd.DataFrame, fixtures_df: pd.DataFrame) -> pd.DataFrame:
    """Attach FPL's official 1-5 fixture difficulty (from the player's own
    team's perspective) to each gameweek row, joined on the fixture id."""
    gw_df = gw_df.copy()
    fx = fixtures_df.set_index("id")[["team_h_difficulty", "team_a_difficulty"]]

    fixture_col = "fixture" if "fixture" in gw_df.columns else None
    if fixture_col is None or "was_home" not in gw_df.columns:
        gw_df["opponent_difficulty"] = 3.0
        return gw_df

    joined = gw_df.join(fx, on=fixture_col)
    was_home = joined["was_home"].astype(bool)
    joined["opponent_difficulty"] = np.where(
        was_home, joined["team_h_difficulty"], joined["team_a_difficulty"]
    )
    joined["opponent_difficulty"] = joined["opponent_difficulty"].fillna(3.0)
    return joined.drop(columns=["team_h_difficulty", "team_a_difficulty"])


def available_lag_features(df: pd.DataFrame) -> List[str]:
    return [f for f in LAG_BASE_FEATURES if f in df.columns]


def build_lag_features(df: pd.DataFrame, group_cols: List[str], sort_cols: List[str]) -> Tuple[pd.DataFrame, List[str]]:
    """Add last-3/last-5 gameweek rolling-average columns for each available
    base stat, using shift(1) so a row's features never see that row's own
    outcome (used for training, where the target is the row's own points)."""
    df = df.sort_values(sort_cols).copy()
    base_feats = available_lag_features(df)

    lag_cols = []
    grouped = df.groupby(group_cols, sort=False)
    for feat in base_feats:
        for w in LAG_WINDOWS:
            col = f"last_{w}_{feat}"
            df[col] = grouped[feat].transform(
                lambda s, w=w: s.shift(1).rolling(w, min_periods=1).mean()
            )
            lag_cols.append(col)

    return df, lag_cols


def full_feature_list(lag_cols: List[str]) -> List[str]:
    return lag_cols + EXTRA_FEATURES


NUMERIC_STRING_STATS = ["influence", "creativity", "threat", "ict_index", "expected_goals", "expected_assists"]


def season_prior_rates(prior_season: dict | None) -> dict | None:
    """Turn a player's last-season season-total stats (from FPL's
    history_past) into a per-game rate, used as a fallback when this season's
    data is too thin to trust on its own. Returns None if the player barely
    played last season (no usable signal)."""
    if not prior_season:
        return None

    starts = prior_season.get("starts") or 0
    minutes = prior_season.get("minutes") or 0
    games_equiv = starts if starts > 0 else minutes / 90
    if games_equiv < 1:
        return None

    rates = {}
    for feat in LAG_BASE_FEATURES:
        val = prior_season.get(feat)
        if val is None:
            continue
        val = float(val) if feat in NUMERIC_STRING_STATS else val
        rates[feat] = val / games_equiv
    return rates


def blended_form_features(
    history_df: pd.DataFrame,
    prior_season: dict | None,
    position_prior: dict | None,
    sort_col: str = "GW",
    windows: List[int] = LAG_WINDOWS,
):
    """For scouting the next gameweek. Blends three tiers of signal, from
    most to least specific:
      1. This season's actual played games (the real signal, once there's
         enough of it).
      2. Last season's per-game rate for this same player, if this season's
         sample is still thin.
      3. The position's average per-game rate across the training data, for
         players with no FPL history at all (promoted-club debutants, new
         signings from abroad).
    As more current-season games accumulate, tiers 2/3 fade out smoothly.

    Returns (feature_dict, confidence) where confidence is one of
    'current', 'prior_season', 'position_avg', 'none'.
    """
    history_df = history_df.sort_values(sort_col) if not history_df.empty else history_df
    games_played = len(history_df)

    prior_rates = season_prior_rates(prior_season)
    fallback = prior_rates or position_prior or {}

    if games_played >= max(windows):
        confidence = "current"
    elif prior_rates is not None:
        confidence = "prior_season"
    elif position_prior is not None:
        confidence = "position_avg"
    elif games_played > 0:
        confidence = "current"
    else:
        confidence = "none"

    row = {}
    for feat in LAG_BASE_FEATURES:
        fallback_rate = fallback.get(feat)
        has_current_col = feat in history_df.columns if games_played > 0 else False
        for w in windows:
            actual_window = min(games_played, w)
            current_avg = history_df[feat].tail(w).mean() if actual_window > 0 and has_current_col else None

            if current_avg is not None and fallback_rate is not None:
                weight = actual_window / w
                blended = weight * current_avg + (1 - weight) * fallback_rate
            elif current_avg is not None:
                blended = current_avg
            else:
                blended = fallback_rate  # may be None; left as NaN downstream

            row[f"last_{w}_{feat}"] = blended

    return row, confidence
