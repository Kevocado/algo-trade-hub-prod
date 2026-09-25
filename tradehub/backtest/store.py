"""Reproducible backtest_runs rows: config hash + data-snapshot hash pin a run down exactly."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from datetime import datetime
from typing import Any, Iterable, Mapping

from tradehub.backtest.pit import Decision
from tradehub.backtest.runner import BacktestResult, MarketHistory

BACKTEST_RUNS_TABLE = "backtest_runs"


def stable_hash(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def data_snapshot_hash(decisions: Iterable[Decision], histories: Mapping[str, MarketHistory]) -> str:
    decision_blobs = sorted(stable_hash(asdict(d)) for d in decisions)
    history_blobs = sorted(stable_hash(asdict(h)) for h in histories.values())
    return stable_hash({"decisions": decision_blobs, "histories": history_blobs})


def build_backtest_run_row(
    result: BacktestResult,
    *,
    engine_version: str,
    config: dict[str, Any],
    data_hash: str,
    date_from: datetime,
    date_to: datetime,
) -> dict[str, Any]:
    return {
        "engine": result.engine,
        "engine_version": engine_version,
        "mode": result.mode,
        "config": config,
        "config_hash": stable_hash(config),
        "data_hash": data_hash,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "n_decisions": result.n_decisions,
        "n_fills": result.n_fills,
        "n_settled": result.summary["n_settled"],
        "pnl_after_fees": round(result.pnl_after_fees, 4),
        "max_drawdown": round(result.max_drawdown, 4),
        "turnover": round(result.turnover, 4),
        "brier_ours": result.summary["brier_ours"],
        "brier_market": result.summary["brier_market"],
        "log_loss": None if result.log_loss is None else round(result.log_loss, 8),
        "cal_buckets": result.cal_buckets,
        "max_cal_dev": result.gate["max_cal_dev"],
        "gate_status": result.gate["status"],
        "gate_reasons": result.gate["reasons"],
    }


def record_backtest_run(supa, row: dict[str, Any]) -> dict[str, Any]:
    res = supa.table(BACKTEST_RUNS_TABLE).insert(row).execute()
    data = res.data or []
    return data[0] if data else {}
