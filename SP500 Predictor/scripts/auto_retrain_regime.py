from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.crypto_features import CANONICAL_CRYPTO_FEATURES, build_features
from market_sentiment_tool.backend import orchestrator


@dataclass(frozen=True)
class RetrainResult:
    asset: str
    training_window_start: str
    training_window_end: str
    incumbent_score: float | None
    candidate_score: float | None
    promoted: bool
    reason: str
    model_path: str


def _fetch_training_bars(asset: str, *, days: int = 14) -> pd.DataFrame:
    try:
        import yfinance as yf
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError("yfinance is required for crypto retraining.") from exc

    symbol = {"BTC": "BTC-USD", "ETH": "ETH-USD"}[asset]
    frame = yf.download(symbol, period=f"{days}d", interval="1h", progress=False, auto_adjust=False)
    if frame.empty:
        raise ValueError(f"yfinance returned no hourly bars for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[["Open", "High", "Low", "Close", "Volume"]].copy()
    for column in frame.columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().sort_index()


def _validation_score_from_brier(brier_score: float) -> float:
    return 1.0 - float(brier_score)


def _brier_score(model: Any, x: pd.DataFrame, y: pd.Series) -> float:
    probabilities = model.predict_proba(x)[:, 1]
    return float(np.mean((probabilities - y.to_numpy(dtype=float)) ** 2))


def _candidate_model_path(asset: str) -> Path:
    explicit = orchestrator.BTC_MODEL_PATH if asset == "BTC" else orchestrator.ETH_MODEL_PATH
    candidates = [
        "/root/kalshibot/btc_model.pkl" if asset == "BTC" else "/root/kalshibot/eth_model.pkl",
        f"models/{asset.lower()}_model.pkl",
        f"quant_research_lab/models/{asset.lower()}_model.pkl",
        f"model/{asset.lower()}_model.pkl",
        f"model/lgbm_model_{asset}.pkl",
        f"quant_research_lab/models/{asset.lower()}_sniper.pkl",
        f"{asset.lower()}_sniper.pkl",
    ]
    try:
        return orchestrator._resolve_model_path(explicit, candidates, asset)
    except FileNotFoundError:
        return REPO_ROOT / "models" / f"{asset.lower()}_model.pkl"


def _feature_contract_matches(model: Any) -> bool:
    try:
        return list(orchestrator._model_feature_names(model)) == list(CANONICAL_CRYPTO_FEATURES)
    except Exception:
        return False


def _train_candidate_model(features: pd.DataFrame):
    import lightgbm as lgb

    x = features[CANONICAL_CRYPTO_FEATURES].copy()
    y = features["target"].astype(int).copy()
    split_index = max(int(len(x) * 0.8), 1)
    x_train, x_valid = x.iloc[:split_index], x.iloc[split_index:]
    y_train, y_valid = y.iloc[:split_index], y.iloc[split_index:]
    if x_train.empty or x_valid.empty:
        raise ValueError("Need both train and validation slices for retraining.")

    model = lgb.LGBMClassifier(
        n_estimators=300,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
        objective="binary",
        is_unbalance=True,
    )
    model.fit(
        x_train,
        y_train,
        eval_set=[(x_valid, y_valid)],
        eval_metric="binary_logloss",
    )
    candidate_brier = _brier_score(model, x_valid, y_valid)
    return model, x_valid, y_valid, _validation_score_from_brier(candidate_brier)


def retrain_asset(asset: str) -> RetrainResult:
    asset = asset.upper()
    bars = _fetch_training_bars(asset, days=14)
    features = build_features(bars, asset=asset, is_live_inference=False, include_target=True)
    if features.empty:
        raise ValueError(f"No training features generated for {asset}.")

    window_start = features.index.min().isoformat()
    window_end = features.index.max().isoformat()
    candidate_model, x_valid, y_valid, candidate_score = _train_candidate_model(features)

    model_path = _candidate_model_path(asset)
    model_path.parent.mkdir(parents=True, exist_ok=True)
    incumbent_score: float | None = None
    reason = "candidate_beats_incumbent"
    promoted = False

    if model_path.exists():
        incumbent_model = orchestrator._load_pickle_model(model_path)
        if not _feature_contract_matches(incumbent_model):
            reason = "incumbent_feature_contract_mismatch"
        else:
            incumbent_brier = _brier_score(incumbent_model, x_valid, y_valid)
            incumbent_score = _validation_score_from_brier(incumbent_brier)
            if candidate_score <= incumbent_score:
                reason = "candidate_not_strictly_better"
            else:
                promoted = True
    else:
        promoted = True
        reason = "no_incumbent_model"

    if promoted:
        joblib.dump(candidate_model, model_path)
        metadata_path = model_path.with_suffix(model_path.suffix + ".metrics.json")
        metadata = {
            "asset": asset,
            "training_window_start": window_start,
            "training_window_end": window_end,
            "candidate_score": candidate_score,
            "incumbent_score": incumbent_score,
            "promoted": True,
            "reason": reason,
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata_path.write_text(json.dumps(metadata, indent=2))

    return RetrainResult(
        asset=asset,
        training_window_start=window_start,
        training_window_end=window_end,
        incumbent_score=incumbent_score,
        candidate_score=candidate_score,
        promoted=promoted,
        reason=reason,
        model_path=str(model_path),
    )


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    results = [retrain_asset("BTC"), retrain_asset("ETH")]
    for result in results:
        print(
            json.dumps(
                {
                    "asset": result.asset,
                    "training_window_start": result.training_window_start,
                    "training_window_end": result.training_window_end,
                    "incumbent_score": result.incumbent_score,
                    "candidate_score": result.candidate_score,
                    "promoted": result.promoted,
                    "reason": result.reason,
                    "model_path": result.model_path,
                }
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
