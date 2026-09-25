"""Replay point-in-time decisions against Kalshi history and score them with the live gate code."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Mapping, Sequence, TypeVar

from tradehub.backtest.fills import Fill, maker_fill, quote_at, taker_fill
from tradehub.backtest.kalshi_history import Candle, Trade
from tradehub.backtest.metrics import fill_pnl, market_mid, max_drawdown, prediction_row
from tradehub.backtest.pit import Decision, LeakageError, check_no_lookahead
from tradehub.track_record import check_promotion_gate, compute_calibration, compute_engine_summary

E = TypeVar("E")
M = TypeVar("M")
R = TypeVar("R")


def _timestamp_key(value: datetime) -> tuple[int, str]:
    if value.tzinfo is None:
        return (0, value.isoformat())
    return (1, value.astimezone(timezone.utc).isoformat())


def _decision_sort_key(decision: Decision) -> tuple[Any, ...]:
    features = tuple(sorted(
        (feature.name, float(feature.value), _timestamp_key(feature.published_at))
        for feature in decision.features
    ))
    return (
        _timestamp_key(decision.decided_at),
        decision.market_ticker,
        float(decision.our_prob),
        features,
    )


@dataclass
class MarketHistory:
    ticker: str
    result: str | None
    close_time: datetime
    candles: list[Candle]
    trades: list[Trade]
    settled_at: datetime | None = None


@dataclass
class BacktestResult:
    engine: str
    cadence: str
    mode: str
    n_decisions: int
    n_fills: int
    pnl_after_fees: float
    max_drawdown: float
    turnover: float
    summary: dict[str, Any]
    cal_buckets: list[dict[str, Any]]
    gate: dict[str, Any]
    fills: list[Fill] = field(default_factory=list)
    log_loss: float | None = None
    # Decisions skipped because the market had no quote yet at decision time
    # (untradeable, and no market Brier to compare against).
    n_unquoted: int = 0


def run_backtest(
    *,
    engine: str,
    cadence: str,
    decisions: Iterable[Decision],
    histories: Mapping[str, MarketHistory],
    mode: str = "taker",
    contracts: int = 1,
    min_edge_pct: float = 0.0,
) -> BacktestResult:
    if mode not in ("taker", "maker"):
        raise ValueError(f"mode must be 'taker' or 'maker', got {mode!r}")
    rows: list[dict[str, Any]] = []
    fills: list[Fill] = []
    pnls: list[float] = []
    settled_pnls: list[tuple[datetime, Fill, float]] = []
    n_unquoted = 0
    for decision in sorted(decisions, key=_decision_sort_key):
        check_no_lookahead(decision)
        history = histories[decision.market_ticker]
        if decision.decided_at >= history.close_time:
            raise LeakageError(f"{decision.market_ticker}: decision at/after market close {history.close_time.isoformat()}")
        if history.result not in ("yes", "no"):
            continue
        market_prob = market_mid(quote_at(history.candles, decision.decided_at))
        if market_prob is None:
            n_unquoted += 1
            continue
        rows.append(prediction_row(decision.our_prob, market_prob, history.result))
        if mode == "taker":
            fill = taker_fill(decision, history.candles, contracts=contracts, min_edge_pct=min_edge_pct)
        else:
            fill = maker_fill(decision, history.candles, history.trades, history.close_time,
                              contracts=contracts, min_edge_pct=min_edge_pct)
        if fill is not None:
            pnl = fill_pnl(fill, history.result)
            fills.append(fill)
            pnls.append(pnl)
            settlement_time = history.settled_at or history.close_time
            settled_pnls.append((settlement_time, fill, pnl))
    summary = compute_engine_summary(rows)
    cal_buckets = compute_calibration(rows)
    mean_log_loss = (
        round(sum(float(row["log_loss"]) for row in rows) / len(rows), 8)
        if rows
        else None
    )
    settlement_order = sorted(
        settled_pnls,
        key=lambda item: (
            _timestamp_key(item[0]),
            _timestamp_key(item[1].filled_at),
            item[1].market_ticker,
            item[1].side,
            item[1].price,
            item[1].contracts,
        ),
    )
    total = sum(pnls)
    gate = check_promotion_gate(engine=engine, cadence=cadence, summary=summary, cal_buckets=cal_buckets,
                                simulated_pnl_after_fees=total if fills else None)
    return BacktestResult(
        engine=engine, cadence=cadence, mode=mode, n_decisions=len(rows), n_fills=len(fills),
        pnl_after_fees=total, max_drawdown=max_drawdown([pnl for _, _, pnl in settlement_order]),
        turnover=sum(f.price * f.contracts for f in fills),
        summary=summary, cal_buckets=cal_buckets, gate=gate, fills=fills,
        log_loss=mean_log_loss,
        n_unquoted=n_unquoted,
    )


def walk_forward(
    events: Sequence[E],
    time_of: Callable[[E], datetime],
    label_available_at: Callable[[E], datetime],
    fit: Callable[[list[E]], M],
    predict: Callable[[M, E], R],
    *,
    min_history: int = 1,
) -> list[tuple[E, R]]:
    """Predict each event using only labels available before its decision time."""
    ordered = sorted(events, key=time_of)
    out: list[tuple[E, R]] = []
    for event in ordered:
        event_time = time_of(event)
        history = [e for e in ordered if e is not event and label_available_at(e) < event_time]
        if len(history) < min_history:
            continue
        out.append((event, predict(fit(history), event)))
    return out
