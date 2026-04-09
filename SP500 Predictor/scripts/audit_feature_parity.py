from __future__ import annotations

import argparse
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market_sentiment_tool.backend.runtime_bootstrap import load_canonical_env
from shared.crypto_features import CANONICAL_CRYPTO_FEATURES, build_features

AUDIT_MODULE = "orchestrator.crypto_feature_audit"
AUDIT_KIND = "feature_distribution_snapshot"
DEFAULT_LIVE_HOURS = 1
DEFAULT_TRAIN_HOURS = 24
DEFAULT_WARMUP_HOURS = 21 * 24
RED_FLAG_THRESHOLD = 1.5
ASSET_SYMBOLS = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
SUCCESS_FEATURES = ("Volume", "force_idx")


def load_env() -> None:
    load_canonical_env(__file__)


def create_supabase_client():
    url = os.getenv("SUPABASE_URL", "") or os.getenv("VITE_SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("Missing SUPABASE_URL/VITE_SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY.")
    return create_client(url, key)


def _latest_session_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    ordered = sorted(
        rows,
        key=lambda row: pd.to_datetime(row["timestamp_utc"], utc=True, errors="coerce"),
    )
    session_start_index = 0
    previous_eval_count: int | None = None
    for index, row in enumerate(ordered):
        evaluation_count = row.get("evaluation_count")
        if isinstance(evaluation_count, (int, float)):
            current_eval_count = int(evaluation_count)
            if previous_eval_count is not None and current_eval_count < previous_eval_count:
                session_start_index = index
            previous_eval_count = current_eval_count
    return ordered[session_start_index:]


def fetch_live_audit_snapshots(
    supa: Any,
    *,
    hours: int = DEFAULT_LIVE_HOURS,
) -> dict[str, pd.DataFrame]:
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    result = (
        supa.table("agent_logs")
        .select("timestamp, reasoning_context")
        .eq("module", AUDIT_MODULE)
        .gte("timestamp", cutoff_iso)
        .execute()
    )

    asset_rows: dict[str, list[dict[str, Any]]] = {}
    for row in result.data or []:
        context = row.get("reasoning_context") or {}
        if context.get("audit_kind") != AUDIT_KIND:
            continue
        asset = str(context.get("asset") or "").upper()
        feature_vector = context.get("feature_vector") or {}
        if asset not in ASSET_SYMBOLS or not feature_vector:
            continue
        feature_row = {
            name: float(feature_vector[name])
            for name in CANONICAL_CRYPTO_FEATURES
            if name in feature_vector
        }
        feature_row["timestamp_utc"] = str(context.get("timestamp_utc") or row.get("timestamp") or "")
        feature_row["evaluation_count"] = context.get("evaluation_count")
        asset_rows.setdefault(asset, []).append(
            feature_row
        )

    return {
        asset: pd.DataFrame(_latest_session_rows(rows), columns=["timestamp_utc", "evaluation_count", *CANONICAL_CRYPTO_FEATURES])[CANONICAL_CRYPTO_FEATURES]
        for asset, rows in asset_rows.items()
        if rows
    }


def fetch_training_feature_frame(
    asset: str,
    *,
    train_hours: int = DEFAULT_TRAIN_HOURS,
    warmup_hours: int = DEFAULT_WARMUP_HOURS,
) -> pd.DataFrame:
    symbol = ASSET_SYMBOLS.get(asset.upper())
    if not symbol:
        raise ValueError(f"Unsupported asset for training baseline: {asset}")

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=train_hours + warmup_hours)
    frame = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=(end + timedelta(hours=1)).strftime("%Y-%m-%d"),
        interval="1h",
        progress=False,
        auto_adjust=False,
    )
    if frame.empty:
        raise RuntimeError(f"yfinance returned no hourly bars for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)
    frame.index = pd.to_datetime(frame.index, utc=True)
    frame = frame[["Open", "High", "Low", "Close", "Volume"]].apply(pd.to_numeric, errors="coerce").dropna()
    frame = frame.loc[(frame.index >= start) & (frame.index <= end)]
    features = build_features(frame, asset=asset, is_live_inference=True)
    if features.empty:
        raise RuntimeError(f"Unable to build training baseline features for {asset}")
    cutoff = features.index.max() - timedelta(hours=train_hours - 1)
    return features.loc[features.index >= cutoff, CANONICAL_CRYPTO_FEATURES]


def compute_drift_table(live_frame: pd.DataFrame, train_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for feature in CANONICAL_CRYPTO_FEATURES:
        if feature not in live_frame.columns or feature not in train_frame.columns:
            continue
        live_series = pd.to_numeric(live_frame[feature], errors="coerce").dropna()
        train_series = pd.to_numeric(train_frame[feature], errors="coerce").dropna()
        if live_series.empty or train_series.empty:
            continue

        live_mean = float(live_series.mean())
        train_mean = float(train_series.mean())
        train_std = float(train_series.std(ddof=0))
        diff = abs(live_mean - train_mean)
        if train_std <= 1e-12:
            drift_score = 0.0 if diff <= 1e-12 else math.inf
        else:
            drift_score = diff / train_std

        rows.append(
            {
                "feature": feature,
                "live_mean": live_mean,
                "train_mean": train_mean,
                "train_std": train_std,
                "drift_score": float(drift_score),
            }
        )

    return pd.DataFrame(rows).sort_values("drift_score", ascending=False, na_position="last")


def format_drift_value(value: float) -> str:
    if math.isinf(value):
        return "INF"
    return f"{value:.3f}"


def print_asset_report(asset: str, drift_table: pd.DataFrame) -> None:
    print(f"\n=== {asset} Feature Drift ===")
    if drift_table.empty:
        print("No drift rows available.")
        return

    print("Ranked drift:")
    for row in drift_table.itertuples(index=False):
        print(
            f"  {row.feature:<16} drift={format_drift_value(row.drift_score):>6} "
            f"live_mean={row.live_mean:>12.6f} train_mean={row.train_mean:>12.6f} train_std={row.train_std:>12.6f}"
        )

    red_flags = drift_table[drift_table["drift_score"] > RED_FLAG_THRESHOLD]
    print("\nRed Flag features (> 1.5):")
    if red_flags.empty:
        print("  none")
    else:
        for row in red_flags.itertuples(index=False):
            print(f"  {row.feature}: drift={format_drift_value(row.drift_score)}")

    print("\nCalibration targets:")
    for feature in SUCCESS_FEATURES:
        feature_rows = drift_table.loc[drift_table["feature"] == feature]
        if feature_rows.empty:
            print(f"  {feature}: unavailable")
            continue
        drift_score = float(feature_rows.iloc[0]["drift_score"])
        status = "PASS" if math.isfinite(drift_score) and drift_score < 1.0 else "CHECK"
        print(f"  {feature}: drift={format_drift_value(drift_score)} [{status}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit crypto live-vs-training feature parity.")
    parser.add_argument("--live-hours", type=int, default=DEFAULT_LIVE_HOURS, help="Lookback window for live snapshots.")
    parser.add_argument("--train-hours", type=int, default=DEFAULT_TRAIN_HOURS, help="Window used for training baseline distribution stats.")
    parser.add_argument("--warmup-hours", type=int, default=DEFAULT_WARMUP_HOURS, help="Warmup hours for training baseline features.")
    args = parser.parse_args()

    load_env()
    supa = create_supabase_client()
    live_frames = fetch_live_audit_snapshots(supa, hours=args.live_hours)
    if not live_frames:
        raise RuntimeError("No live audit snapshots found in agent_logs for the requested window.")

    for asset in ("BTC", "ETH"):
        live_frame = live_frames.get(asset)
        if live_frame is None or live_frame.empty:
            print(f"\n=== {asset} Feature Drift ===")
            print("No live audit snapshots found.")
            continue
        train_frame = fetch_training_feature_frame(asset, train_hours=args.train_hours, warmup_hours=args.warmup_hours)
        drift_table = compute_drift_table(live_frame, train_frame)
        print_asset_report(asset, drift_table)


if __name__ == "__main__":
    main()
