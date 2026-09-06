"""
scout.py — build a ranked "who to pick for the next gameweek" table using
the trained per-position models.

Usage:
    python scout.py            # prints top overall + top-per-position to terminal

Or import build_gameweek_scout_table() from the Streamlit app.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Optional, Tuple

import pandas as pd

import fpl_data
import model as model_lib
from features import LAG_WINDOWS, blended_form_features

MIN_GAMES_FOR_CONFIDENCE = max(LAG_WINDOWS)


def _fetch_all_summaries(player_ids, next_event: int, max_workers: int = 20) -> Dict[int, Tuple[pd.DataFrame, Optional[dict]]]:
    summaries: Dict[int, Tuple[pd.DataFrame, Optional[dict]]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {
            pool.submit(fpl_data.fetch_player_summary, pid, next_event): pid for pid in player_ids
        }
        for future in as_completed(futures):
            pid = futures[future]
            try:
                summaries[pid] = future.result()
            except Exception:
                summaries[pid] = (pd.DataFrame(), None)
    return summaries


def build_gameweek_scout_table(min_minutes_share: float = 0.0) -> pd.DataFrame:
    manifest = model_lib.load_manifest()
    feature_cols = manifest["features"]
    models = model_lib.load_models()
    position_priors = {pos: manifest["positions"][pos].get("prior") for pos in models}

    bootstrap = fpl_data.fetch_bootstrap()
    fixtures = fpl_data.fetch_fixtures()
    next_event = fpl_data.get_next_event_id(bootstrap)

    players_df = fpl_data.build_player_table(bootstrap)
    players_df = players_df[players_df["position"].isin(models.keys())]

    next_fixture_map = fpl_data.build_next_fixture_map(fixtures, next_event)

    print(f"Fetching recent form for {len(players_df)} players (gameweek {next_event})...")
    summaries = _fetch_all_summaries(players_df["id"].tolist(), next_event)

    feature_rows = []
    for _, player in players_df.iterrows():
        fixture_info = next_fixture_map.get(player["team_id"])
        history, prior_season = summaries.get(player["id"], (pd.DataFrame(), None))
        games_played = len(history)

        row = {
            "id": player["id"],
            "has_fixture": fixture_info is not None,
            "games_played": games_played,
        }
        if fixture_info is not None:
            row["was_home"] = int(fixture_info["was_home"])
            row["opponent_difficulty"] = fixture_info["difficulty"]
            row["opponent_team_id"] = fixture_info["opponent_team_id"]

        form_features, confidence = blended_form_features(
            history, prior_season, position_priors.get(player["position"])
        )
        row.update(form_features)
        row["data_confidence"] = confidence
        row["value"] = player["price"] * 10
        feature_rows.append(row)

    features_df = pd.DataFrame(feature_rows).set_index("id")
    result = players_df.set_index("id").join(features_df)

    team_names = {t["id"]: t["name"] for t in bootstrap["teams"]}
    result["next_opponent"] = result["opponent_team_id"].map(team_names)
    result["low_data"] = result["data_confidence"] != "current"

    result["predicted_points"] = float("nan")
    for position, mdl in models.items():
        mask = (result["position"] == position) & result["has_fixture"]
        if not mask.any():
            continue
        preds = model_lib.predict(position, models, feature_cols, result.loc[mask])
        result.loc[mask, "predicted_points"] = preds

    # Discount for known unavailability -- a model prior has no way to know a
    # player is injured/suspended, but the live API already tells us.
    unavailable = result["status"].isin(["i", "s", "u"])
    result.loc[unavailable, "predicted_points"] = 0.0
    doubtful = result["status"] == "d"
    chance = result.loc[doubtful, "chance_of_playing_next_round"].fillna(50) / 100.0
    result.loc[doubtful, "predicted_points"] = result.loc[doubtful, "predicted_points"] * chance

    result["predicted_points_per_million"] = (result["predicted_points"] / result["price"]).round(2)
    result["predicted_points"] = result["predicted_points"].round(2)

    if min_minutes_share > 0:
        result = result[result.get("last_5_minutes", 0).fillna(0) >= min_minutes_share * 90]

    display_cols = [
        "web_name", "name", "team", "position", "price", "status", "news",
        "selected_by_percent", "next_opponent", "was_home", "opponent_difficulty",
        "games_played", "data_confidence", "low_data", "predicted_points", "predicted_points_per_million",
    ]
    result = result.reset_index()
    result = result[["id"] + [c for c in display_cols if c in result.columns]]
    return result.sort_values("predicted_points", ascending=False, na_position="last")


def main():
    table = build_gameweek_scout_table()
    playable = table[table["predicted_points"].notna()]

    low_data_share = playable["low_data"].mean() if len(playable) else 0
    if low_data_share > 0.3:
        n_low = int(playable["low_data"].sum())
        n_prior = int((playable["data_confidence"] == "prior_season").sum())
        n_pos = int((playable["data_confidence"] == "position_avg").sum())
        print(
            f"Note: {n_low}/{len(playable)} players have played fewer than "
            f"{MIN_GAMES_FOR_CONFIDENCE} games this season, so their prediction blends "
            f"in last season's form ({n_prior} players) or a position-average prior for "
            f"players with no FPL history ({n_pos} players) — flagged low_data.\n"
        )

    print("=== Top 20 overall ===")
    print(playable.head(20)[["web_name", "team", "position", "price", "predicted_points", "next_opponent"]].to_string(index=False))

    for position in ["GK", "DEF", "MID", "FWD"]:
        print(f"\n=== Top 10 {position} ===")
        subset = playable[playable["position"] == position].head(10)
        print(subset[["web_name", "team", "price", "predicted_points", "next_opponent"]].to_string(index=False))


if __name__ == "__main__":
    main()
