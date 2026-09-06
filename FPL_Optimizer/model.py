"""
model.py — train/save/load per-position points-prediction models, and
compute feature importance (what actually drives points for each role).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.inspection import permutation_importance
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from features import LAG_BASE_FEATURES

POSITIONS = ["GK", "DEF", "MID", "FWD"]
TARGET = "total_points"

MODELS_DIR = Path(__file__).parent / "models"
MANIFEST_PATH = MODELS_DIR / "manifest.json"


def _season_order(df: pd.DataFrame) -> pd.Series:
    return df["season"].str.slice(0, 4).astype(int)


def chronological_split(df: pd.DataFrame):
    """Hold out the most recent season as validation; train on the rest."""
    order = _season_order(df)
    latest = order.max()
    val_mask = order == latest
    return df[~val_mask], df[val_mask]


def train_position_model(df_pos: pd.DataFrame, feature_cols: List[str]):
    train_df, val_df = chronological_split(df_pos)

    X_train, y_train = train_df[feature_cols].fillna(0), train_df[TARGET]
    X_val, y_val = val_df[feature_cols].fillna(0), val_df[TARGET]

    model = xgb.XGBRegressor(
        objective="reg:squarederror",
        n_estimators=300,
        learning_rate=0.05,
        max_depth=4,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
    )
    model.fit(X_train, y_train)

    preds = model.predict(X_val)
    metrics = {
        "n_train": int(len(X_train)),
        "n_val": int(len(X_val)),
        "mae": float(mean_absolute_error(y_val, preds)),
        "rmse": float(np.sqrt(mean_squared_error(y_val, preds))),
        "r2": float(r2_score(y_val, preds)),
    }

    gain_importance = dict(zip(feature_cols, model.feature_importances_.astype(float)))

    perm = permutation_importance(
        model, X_val, y_val, n_repeats=5, random_state=42, scoring="r2"
    )
    perm_importance = dict(zip(feature_cols, perm.importances_mean.astype(float)))

    return model, metrics, gain_importance, perm_importance


def train_all_positions(df: pd.DataFrame, feature_cols: List[str]) -> Dict:
    MODELS_DIR.mkdir(exist_ok=True)
    manifest = {
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "features": feature_cols,
        "positions": {},
    }

    for position in POSITIONS:
        df_pos = df[df["position"] == position]
        if len(df_pos) < 50:
            print(f"  ! Skipping {position}: only {len(df_pos)} rows, too few to train")
            continue

        model, metrics, gain_imp, perm_imp = train_position_model(df_pos, feature_cols)
        model.save_model(MODELS_DIR / f"{position}.json")

        # A typical player-gameweek's raw stats for this position, used in
        # scout.py as a last-resort prior for players with no FPL history at
        # all (promoted-club debutants, new signings from abroad).
        position_prior = {
            feat: float(df_pos[feat].mean()) for feat in LAG_BASE_FEATURES if feat in df_pos.columns
        }

        manifest["positions"][position] = {
            "metrics": metrics,
            "importance": {"gain": gain_imp, "permutation": perm_imp},
            "prior": position_prior,
        }
        print(
            f"  > {position}: MAE={metrics['mae']:.2f} RMSE={metrics['rmse']:.2f} "
            f"R2={metrics['r2']:.3f} (train={metrics['n_train']}, val={metrics['n_val']})"
        )

    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2))
    return manifest


def load_manifest() -> Dict:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            "No trained models found. Run `python train.py` first."
        )
    return json.loads(MANIFEST_PATH.read_text())


def load_models() -> Dict[str, xgb.XGBRegressor]:
    manifest = load_manifest()
    models = {}
    for position in manifest["positions"]:
        model = xgb.XGBRegressor()
        model.load_model(MODELS_DIR / f"{position}.json")
        models[position] = model
    return models


def predict(position: str, models: Dict[str, xgb.XGBRegressor], feature_cols: List[str], rows: pd.DataFrame) -> np.ndarray:
    model = models[position]
    X = rows.reindex(columns=feature_cols, fill_value=0).fillna(0)
    return model.predict(X)
