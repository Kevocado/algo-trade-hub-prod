"""
train.py — build the per-position points-prediction models.

Usage:
    python train.py

Fetches the last few completed Premier League seasons of gameweek data,
builds lag/fixture features, trains one XGBoost model per position
(GK/DEF/MID/FWD), and saves them + their metrics + feature importance to
FPL_Optimizer/models/.
"""

from features import build_lag_features, full_feature_list
from historical_data import default_completed_seasons, load_training_data
from model import train_all_positions


def main():
    seasons = default_completed_seasons()
    print(f"Training on seasons: {seasons}\n")

    print("Fetching historical gameweek data...")
    df = load_training_data(seasons)
    print(f"Loaded {len(df)} total player-gameweek rows\n")

    print("Building lag features...")
    df, lag_cols = build_lag_features(
        df, group_cols=["season", "element"], sort_cols=["season", "GW"]
    )
    feature_cols = full_feature_list(lag_cols)

    # Drop rows with no prior history yet (a player's first gameweek in a season)
    df = df.dropna(subset=[lag_cols[0]]) if lag_cols else df
    print(f"{len(df)} rows have enough history to train on\n")

    print("Training per-position models...")
    train_all_positions(df, feature_cols)
    print("\nDone. Models saved to FPL_Optimizer/models/")


if __name__ == "__main__":
    main()
