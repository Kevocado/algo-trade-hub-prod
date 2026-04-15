from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from supabase import create_client

REPO_ROOT = Path(__file__).resolve().parents[2]
PREDICTOR_ROOT = Path(__file__).resolve().parents[1]
for path in (REPO_ROOT, PREDICTOR_ROOT):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from market_sentiment_tool.backend.runtime_bootstrap import load_canonical_env
from market_sentiment_tool.backend.signal_events import CRYPTO_DOMAIN, SIGNAL_EVENTS_TABLE, is_supported_signal_event_domain

ENV_BOOTSTRAP = load_canonical_env(__file__)
DEFAULT_LOOKBACK_HOURS = int(os.getenv("SHADOW_SCORECARD_HOURS", "24"))
DEFAULT_BTC_YES = float(os.getenv("CRYPTO_BTC_YES_THRESHOLD", "0.5751"))
DEFAULT_BTC_NO = float(os.getenv("CRYPTO_BTC_NO_THRESHOLD", "0.4249"))
DEFAULT_ETH_YES = float(os.getenv("CRYPTO_ETH_YES_THRESHOLD", "0.551"))
DEFAULT_ETH_NO = float(os.getenv("CRYPTO_ETH_NO_THRESHOLD", "0.449"))
DEFAULT_STALE_GRACE_SECONDS = float(os.getenv("CRYPTO_STALE_DATA_GRACE_SECONDS", "60"))


@dataclass(frozen=True)
class ThresholdConfig:
    yes: float
    no: float


@dataclass(frozen=True)
class EvaluatedSignal:
    asset: str
    created_at: pd.Timestamp
    source_market_ticker: str
    desired_side: str
    probability_yes: float
    base_hour: pd.Timestamp
    realized_hour: pd.Timestamp
    current_close: float
    next_close: float
    realized_yes: int
    correct: bool
    virtual_return_pct: float


def _current_hour_utc(reference: datetime | None = None) -> pd.Timestamp:
    now = reference or datetime.now(timezone.utc)
    return _to_utc_timestamp(now.replace(minute=0, second=0, microsecond=0))


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _missing_env_detail() -> str:
    if ENV_BOOTSTRAP.env_path is not None:
        return f"Loaded env from {ENV_BOOTSTRAP.env_path}"
    return "No canonical .env file was found under the repo root or service root."


def _alpaca_config() -> tuple[str, str, str]:
    api_base = os.getenv("ALPACA_DATA_API_BASE", "https://data.alpaca.markets").strip('"').strip("'")
    api_key = os.getenv("ALPACA_API_KEY", "")
    secret_key = os.getenv("ALPACA_SECRET_KEY", "")
    if not api_key or not secret_key:
        raise RuntimeError(
            "Missing Alpaca API credentials for shadow scorecard. "
            f"Expected ALPACA_API_KEY and ALPACA_SECRET_KEY. {_missing_env_detail()}"
        )
    return api_base, api_key, secret_key


def _load_supabase_client():
    url = os.getenv("SUPABASE_URL", "") or os.getenv("VITE_SUPABASE_URL", "")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError(
            "Missing Supabase credentials for shadow scorecard. "
            f"Expected SUPABASE_URL or VITE_SUPABASE_URL plus SUPABASE_SERVICE_ROLE_KEY. {_missing_env_detail()}"
        )
    return create_client(url, key)


def _scorecard_thresholds(
    *,
    btc_yes: float = DEFAULT_BTC_YES,
    btc_no: float = DEFAULT_BTC_NO,
    eth_yes: float = DEFAULT_ETH_YES,
    eth_no: float = DEFAULT_ETH_NO,
) -> dict[str, ThresholdConfig]:
    return {
        "BTC": ThresholdConfig(yes=float(btc_yes), no=float(btc_no)),
        "ETH": ThresholdConfig(yes=float(eth_yes), no=float(eth_no)),
    }


def _is_manual_test(payload: dict[str, Any]) -> bool:
    signal = payload.get("signal") or {}
    raw = signal.get("raw") or {}
    return bool(payload.get("manual_test") or raw.get("manual_test"))


def fetch_recent_signal_events(
    *,
    hours: int = DEFAULT_LOOKBACK_HOURS,
    limit: int = 500,
    domain: str = CRYPTO_DOMAIN,
) -> list[dict[str, Any]]:
    normalized_domain = str(domain).strip().lower()
    if not is_supported_signal_event_domain(normalized_domain):
        raise RuntimeError(f"Unsupported signal-event domain: {domain}")
    supa = _load_supabase_client()
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    response = (
        supa.table(SIGNAL_EVENTS_TABLE)
        .select("asset,created_at,source_market_ticker,desired_side,status,model_probability_yes,payload")
        .eq("domain", normalized_domain)
        .in_("status", ["signal_detected", "inference_heartbeat"])
        .gte("created_at", cutoff_iso)
        .order("created_at", desc=False)
        .limit(limit)
        .execute()
    )
    rows = response.data or []
    filtered: list[dict[str, Any]] = []
    for row in rows:
        asset = str(row.get("asset") or "").upper()
        payload = row.get("payload") or {}
        if asset not in {"BTC", "ETH"}:
            continue
        if row.get("model_probability_yes") is None:
            continue
        if _is_manual_test(payload):
            continue
        filtered.append(row)
    return filtered


def _alpaca_symbol(asset: str) -> str:
    symbol = {"BTC": "BTC/USD", "ETH": "ETH/USD"}.get(asset.upper())
    if not symbol:
        raise ValueError(f"Unsupported crypto asset: {asset}")
    return symbol


def _fetch_alpaca_hourly_closes(asset: str, *, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    api_base, api_key, secret_key = _alpaca_config()
    symbol = _alpaca_symbol(asset)
    response = requests.get(
        f"{api_base}/v1beta3/crypto/us/bars",
        headers={
            "accept": "application/json",
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": secret_key,
        },
        params={
            "symbols": symbol,
            "timeframe": "1Hour",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 1000,
            "sort": "asc",
        },
        timeout=20,
    )
    response.raise_for_status()
    payload = response.json()
    rows = ((payload.get("bars") or {}).get(symbol)) or []
    if not rows:
        return pd.DataFrame(columns=["Close"])
    frame = pd.DataFrame(rows)
    frame["timestamp"] = pd.to_datetime(frame["t"], utc=True)
    frame["Close"] = pd.to_numeric(frame["c"], errors="coerce")
    frame = frame.set_index("timestamp")[["Close"]].dropna().sort_index()
    current_hour = _current_hour_utc()
    return frame[frame.index < current_hour]


def _event_hours(created_at: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    created_ts = _to_utc_timestamp(created_at)
    created_hour = created_ts.floor("h")
    return created_hour - pd.Timedelta(hours=1), created_hour


def _threshold_side(probability_yes: float, thresholds: ThresholdConfig) -> str | None:
    if probability_yes >= thresholds.yes:
        return "YES"
    if probability_yes <= thresholds.no:
        return "NO"
    return None


def _considered_signal_count(rows: list[dict[str, Any]], thresholds: dict[str, ThresholdConfig]) -> dict[str, int]:
    total = 0
    considered = 0
    dead_zone = 0
    for row in rows:
        asset = str(row.get("asset") or "").upper()
        if asset not in thresholds:
            continue
        probability_yes = row.get("model_probability_yes")
        if probability_yes is None:
            continue
        total += 1
        if _threshold_side(float(probability_yes), thresholds[asset]) is None:
            dead_zone += 1
        else:
            considered += 1
    return {"evaluated_count": total, "considered_count": considered, "dead_zone_count": dead_zone}


def _latest_bar_status(asset: str, *, current_hour: pd.Timestamp, grace_seconds: float = DEFAULT_STALE_GRACE_SECONDS) -> dict[str, Any]:
    start = current_hour - pd.Timedelta(hours=6)
    closes = _fetch_alpaca_hourly_closes(asset, start=start, end=current_hour)
    if closes.empty:
        return {"asset": asset, "latest_bar": None, "age_hours": None, "is_stale": True}
    latest_bar = closes.index.max()
    age = current_hour.to_pydatetime() - latest_bar.to_pydatetime()
    stale_cutoff = timedelta(hours=2) + timedelta(seconds=max(float(grace_seconds), 0.0))
    return {
        "asset": asset,
        "latest_bar": latest_bar,
        "age_hours": age.total_seconds() / 3600.0,
        "is_stale": age > stale_cutoff,
    }


def _probability_bucket(probability_yes: float) -> str:
    if probability_yes <= 0.45:
        return "<=0.45"
    if probability_yes < 0.50:
        return "0.45-0.50"
    if probability_yes < 0.55:
        return "0.50-0.55"
    if probability_yes < 0.60:
        return "0.55-0.60"
    return ">=0.60"


def evaluate_recent_signals(
    rows: list[dict[str, Any]],
    *,
    thresholds: dict[str, ThresholdConfig],
) -> list[EvaluatedSignal]:
    if not rows:
        return []

    current_hour = _current_hour_utc()
    needed_by_asset: dict[str, list[tuple[dict[str, Any], pd.Timestamp, pd.Timestamp]]] = {"BTC": [], "ETH": []}
    for row in rows:
        base_hour, realized_hour = _event_hours(str(row["created_at"]))
        if realized_hour >= current_hour:
            continue
        needed_by_asset[str(row["asset"]).upper()].append((row, base_hour, realized_hour))

    evaluated: list[EvaluatedSignal] = []
    for asset, grouped in needed_by_asset.items():
        if not grouped:
            continue
        start = min(base_hour for _, base_hour, _ in grouped)
        end = current_hour
        closes = _fetch_alpaca_hourly_closes(asset, start=start, end=end)
        if closes.empty:
            continue
        for row, base_hour, realized_hour in grouped:
            threshold_side = _threshold_side(float(row["model_probability_yes"]), thresholds[asset])
            if threshold_side is None:
                continue
            if base_hour not in closes.index or realized_hour not in closes.index:
                continue
            current_close = float(closes.loc[base_hour, "Close"])
            next_close = float(closes.loc[realized_hour, "Close"])
            if next_close == current_close:
                continue
            realized_yes = int(next_close > current_close)
            desired_side = threshold_side
            correct = (desired_side == "YES" and realized_yes == 1) or (desired_side == "NO" and realized_yes == 0)
            hourly_return = (next_close - current_close) / current_close
            virtual_return_pct = hourly_return * 100.0 if desired_side == "YES" else (-hourly_return * 100.0)
            evaluated.append(
                EvaluatedSignal(
                    asset=asset,
                    created_at=_to_utc_timestamp(row["created_at"]),
                    source_market_ticker=str(row.get("source_market_ticker") or ""),
                    desired_side=desired_side,
                    probability_yes=float(row["model_probability_yes"]),
                    base_hour=base_hour,
                    realized_hour=realized_hour,
                    current_close=current_close,
                    next_close=next_close,
                    realized_yes=realized_yes,
                    correct=correct,
                    virtual_return_pct=virtual_return_pct,
                )
            )
    return evaluated


def _asset_summary(evaluated: list[EvaluatedSignal], asset: str) -> dict[str, float | int | None]:
    subset = [item for item in evaluated if item.asset == asset]
    if not subset:
        return {"count": 0, "hit_rate": None, "virtual_pnl_pct": 0.0, "brier_score": None}
    outcomes = np.array([item.realized_yes for item in subset], dtype=float)
    probs = np.array([item.probability_yes for item in subset], dtype=float)
    return {
        "count": len(subset),
        "hit_rate": float(np.mean([item.correct for item in subset])),
        "virtual_pnl_pct": float(np.sum([item.virtual_return_pct for item in subset])),
        "brier_score": float(np.mean((probs - outcomes) ** 2)),
    }


def build_shadow_report(
    *,
    hours: int = DEFAULT_LOOKBACK_HOURS,
    domain: str = CRYPTO_DOMAIN,
    btc_yes: float = DEFAULT_BTC_YES,
    btc_no: float = DEFAULT_BTC_NO,
    eth_yes: float = DEFAULT_ETH_YES,
    eth_no: float = DEFAULT_ETH_NO,
) -> dict[str, Any]:
    normalized_domain = str(domain).strip().lower()
    thresholds = _scorecard_thresholds(
        btc_yes=btc_yes,
        btc_no=btc_no,
        eth_yes=eth_yes,
        eth_no=eth_no,
    )
    current_hour = _current_hour_utc()
    errors: list[str] = []
    rows: list[dict[str, Any]] = []
    try:
        rows = fetch_recent_signal_events(hours=hours, domain=normalized_domain)
    except RuntimeError as exc:
        errors.append(str(exc))

    consideration = _considered_signal_count(rows, thresholds)

    evaluated: list[EvaluatedSignal] = []
    if rows:
        try:
            evaluated = evaluate_recent_signals(rows, thresholds=thresholds)
        except RuntimeError as exc:
            errors.append(str(exc))

    freshness: dict[str, dict[str, Any]] = {}
    for asset in ("BTC", "ETH"):
        try:
            freshness[asset] = _latest_bar_status(asset, current_hour=current_hour)
        except RuntimeError as exc:
            if str(exc) not in errors:
                errors.append(str(exc))
            freshness[asset] = {"asset": asset, "latest_bar": None, "age_hours": None, "is_stale": None}

    if not evaluated:
        return {
            "domain": normalized_domain,
            "hours": hours,
            "thresholds": thresholds,
            "signals": [],
            "overall": {"count": 0, "hit_rate": None, "virtual_pnl_pct": 0.0, "brier_score": None},
            "by_asset": {"BTC": _asset_summary([], "BTC"), "ETH": _asset_summary([], "ETH")},
            "bucket_stats": {},
            "consideration": consideration,
            "freshness": freshness,
            "errors": errors,
        }

    outcomes = np.array([item.realized_yes for item in evaluated], dtype=float)
    probs = np.array([item.probability_yes for item in evaluated], dtype=float)
    bucket_stats: dict[str, dict[str, float | int]] = {}
    for bucket in sorted({_probability_bucket(item.probability_yes) for item in evaluated}):
        bucket_items = [item for item in evaluated if _probability_bucket(item.probability_yes) == bucket]
        bucket_stats[bucket] = {
            "count": len(bucket_items),
            "hit_rate": float(np.mean([item.correct for item in bucket_items])),
        }

    return {
        "domain": normalized_domain,
        "hours": hours,
        "thresholds": thresholds,
        "signals": evaluated,
        "overall": {
            "count": len(evaluated),
            "hit_rate": float(np.mean([item.correct for item in evaluated])),
            "virtual_pnl_pct": float(np.sum([item.virtual_return_pct for item in evaluated])),
            "brier_score": float(np.mean((probs - outcomes) ** 2)),
        },
        "by_asset": {
            "BTC": _asset_summary(evaluated, "BTC"),
            "ETH": _asset_summary(evaluated, "ETH"),
        },
        "bucket_stats": bucket_stats,
        "consideration": consideration,
        "freshness": freshness,
        "errors": errors,
    }


def render_shadow_report(report: dict[str, Any], *, telegram: bool = False) -> str:
    domain = str(report.get("domain") or CRYPTO_DOMAIN).strip().lower()
    consideration = report.get("consideration") or {"evaluated_count": 0, "considered_count": 0, "dead_zone_count": 0}
    freshness = report.get("freshness") or {}
    title = "Crypto Accuracy" if domain == CRYPTO_DOMAIN else f"{domain.title()} Accuracy"

    def _freshness_line(asset: str) -> str:
        status = freshness.get(asset) or {}
        latest_bar = status.get("latest_bar")
        age_hours = status.get("age_hours")
        is_stale = status.get("is_stale")
        if latest_bar is None or age_hours is None:
            return f"{asset}: freshness unavailable"
        freshness_label = "STALE" if is_stale else "fresh"
        return f"{asset}: {freshness_label} | latest {pd.Timestamp(latest_bar).isoformat()} | age {float(age_hours):.2f}h"

    if not report["overall"]["count"]:
        prefix = f"📊 *{title}*" if telegram else title
        lines = [
            prefix,
            "",
            f"Window: {report['hours']}h",
            f"Inference Events Reviewed: {int(consideration['evaluated_count'])}",
            f"Bot Would Have Considered: {int(consideration['considered_count'])} trades",
            f"Dead Zone: {int(consideration['dead_zone_count'])}",
            _freshness_line("BTC"),
            _freshness_line("ETH"),
        ]
        if report.get("errors"):
            lines.extend(["", f"Scorecard Warning: {report['errors'][0]}"])
        else:
            lines.extend(
                [
                    "",
                    "No recent shadow outcomes with a fully closed next-hour bar.",
                ]
            )
        return "\n".join(lines)

    overall = report["overall"]
    btc = report["by_asset"]["BTC"]
    eth = report["by_asset"]["ETH"]
    btc_yes = report["thresholds"]["BTC"].yes
    eth_yes = report["thresholds"]["ETH"].yes
    lines = [
        f"📊 *{title}*" if telegram else title,
        "",
        f"Window: {report['hours']}h",
        f"Inference Events Reviewed: {int(consideration['evaluated_count'])}",
        f"Bot Would Have Considered: {int(consideration['considered_count'])} trades",
        f"Dead Zone: {int(consideration['dead_zone_count'])}",
        f"Signals Evaluated: {overall['count']}",
        f"Overall Hit Rate: {float(overall['hit_rate']) * 100:.1f}%",
        f"Brier Score: {float(overall['brier_score']):.4f}",
        f"Virtual PnL: {float(overall['virtual_pnl_pct']):+.2f}% at BTC>{btc_yes:.4f}, ETH>{eth_yes:.3f}",
        f"BTC: {int(btc['count'])} signals | hit rate {float(btc['hit_rate'] or 0.0) * 100:.1f}% | pnl {float(btc['virtual_pnl_pct']):+.2f}%",
        f"ETH: {int(eth['count'])} signals | hit rate {float(eth['hit_rate'] or 0.0) * 100:.1f}% | pnl {float(eth['virtual_pnl_pct']):+.2f}%",
        _freshness_line("BTC"),
        _freshness_line("ETH"),
    ]
    if report.get("errors"):
        lines.append(f"Scorecard Warning: {report['errors'][0]}")
    if not telegram and report["bucket_stats"]:
        lines.append("")
        lines.append("Threshold Buckets:")
        for bucket, stats in report["bucket_stats"].items():
            lines.append(
                f"  {bucket}: count={int(stats['count'])} hit_rate={float(stats['hit_rate']) * 100:.1f}%"
            )
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute domain shadow hit rate, Brier Score, and virtual PnL.")
    parser.add_argument("--hours", type=int, default=DEFAULT_LOOKBACK_HOURS)
    parser.add_argument("--domain", type=str, default=CRYPTO_DOMAIN)
    parser.add_argument("--btc-yes", type=float, default=DEFAULT_BTC_YES)
    parser.add_argument("--btc-no", type=float, default=DEFAULT_BTC_NO)
    parser.add_argument("--eth-yes", type=float, default=DEFAULT_ETH_YES)
    parser.add_argument("--eth-no", type=float, default=DEFAULT_ETH_NO)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    report = build_shadow_report(
        hours=args.hours,
        domain=args.domain,
        btc_yes=args.btc_yes,
        btc_no=args.btc_no,
        eth_yes=args.eth_yes,
        eth_no=args.eth_no,
    )
    print(render_shadow_report(report, telegram=False))
    return 2 if report.get("errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
