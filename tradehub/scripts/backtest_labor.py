"""Point-in-time backtest of labor_nowcast against settled KXPAYROLLS ladders.

Decisions are made one hour before each market closes (7:29 ET on release
day for the usual 8:29 close), from inputs public by then (checked by run_backtest's leakage guard).
The model for month M is fit only on first prints of months before M.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.fills import quote_at
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.pit import Decision
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
from tradehub.data.labor_inputs import Nowcast, load_labor_inputs, payroll_nowcasts
from tradehub.engines.labor import (
    ALL_FEATURES,
    CORE_FEATURES,
    LABOR_ENGINE_VERSION,
    PAYROLL_RESOLUTION,
    PAYROLL_SERIES,
    TRAIN_START,
    decision_time,
    greater_threshold,
    labor_market,
    parse_expiration_value,
    payroll_prob,
)
from tradehub.engines.ladder import implied_mean, isotonic_survival, usable_mid
from tradehub.markets import KalshiMarket, event_month

CANDLE_WINDOW = timedelta(days=2)
_ET = ZoneInfo("America/New_York")


def release_dates(raws: Iterable[dict[str, Any]]) -> dict[date, date]:
    """{reference month: release day (ET)} from each event's earliest close_time."""
    out: dict[date, date] = {}
    for raw in raws:
        month = event_month(raw["event_ticker"])
        day = datetime.fromisoformat(raw["close_time"].replace("Z", "+00:00")).astimezone(_ET).date()
        out[month] = min(out.get(month, day), day)
    return out


def settled_ladder(raws: Iterable[dict[str, Any]], start: date, end: date) -> list[dict[str, Any]]:
    """Settled payroll markets in [start, end] whose event has a numeric first print (drops e.g. Oct-2025)."""
    return [raw for raw in raws
            if start <= event_month(raw["event_ticker"]) <= end
            and raw.get("result") in ("yes", "no")
            and parse_expiration_value(raw.get("expiration_value")) is not None]


def build_labor_decisions(markets: list[KalshiMarket], nowcasts: Mapping[date, Nowcast]) -> list[Decision]:
    decisions = []
    for market in markets:
        nc = nowcasts.get(event_month(market.event_ticker))
        if nc is None:
            continue
        decisions.append(Decision(market.ticker, decision_time(market),
                                  payroll_prob(market, nc.mu, nc.sigma), nc.features.sources))
    return decisions


def labor_histories(client: KalshiHistoryClient, markets: list[KalshiMarket], results: Mapping[str, str],
                    mode: str) -> dict[str, MarketHistory]:
    out = {}
    for market in markets:
        start = market.close_time - CANDLE_WINDOW
        candles = client.merged_candles(market.ticker, start, market.close_time, series_ticker=market.series_ticker)
        trades = client.merged_trades(market.ticker, start=start, end=market.close_time) if mode == "maker" else []
        out[market.ticker] = MarketHistory(market.ticker, results.get(market.ticker), market.close_time, candles, trades)
    return out


def quoted_only(decisions: list[Decision], histories: Mapping[str, MarketHistory]) -> list[Decision]:
    """Keep decisions whose market had a two-sided quote at decision time.

    A strike nobody quoted can't be traded or scored against the market, and one
    unquoted row would make the market Brier (and so the gate) undefined.
    """
    return [d for d in decisions if quote_at(histories[d.market_ticker].candles, d.decided_at) is not None]


def kalshi_implied_means(markets: list[KalshiMarket], histories: Mapping[str, MarketHistory]) -> dict[date, float]:
    """Kalshi-implied mean first print (thousands) per month, from usable mids one hour before close."""
    points: dict[date, list[tuple[float, float]]] = {}
    for market in markets:
        history = histories.get(market.ticker)
        if history is None:
            continue
        candle = quote_at(history.candles, decision_time(market))
        mid = None if candle is None else usable_mid(candle.yes_bid, candle.yes_ask)
        if mid is not None:
            cut = greater_threshold(market.floor_strike, PAYROLL_RESOLUTION) / 1000.0
            points.setdefault(event_month(market.event_ticker), []).append((cut, mid))
    return {month: implied_mean(isotonic_survival(pts)) for month, pts in points.items() if len(pts) >= 2}


def _month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time backtest for labor_nowcast (KXPAYROLLS).")
    parser.add_argument("--start", type=_month_arg, default=date(2023, 3, 1), help="first reference month, YYYY-MM")
    parser.add_argument("--end", type=_month_arg, required=True, help="last reference month, YYYY-MM")
    parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
    parser.add_argument("--features", choices=["core", "all"], default="core")
    parser.add_argument("--cache-dir", type=Path, default=None, help="ALFRED vintage cache (default $TRADEHUB_ALFRED_CACHE)")
    parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
    args = parser.parse_args(argv)

    client = KalshiHistoryClient(get_json=ThrottledGetJson())
    all_raws = client.settled_markets(PAYROLL_SERIES)
    raws = settled_ladder(all_raws, args.start, args.end)
    markets = [labor_market(raw) for raw in raws]
    results = {raw["ticker"]: raw["result"] for raw in raws}
    releases = release_dates(all_raws)
    months = sorted({event_month(m.event_ticker) for m in markets})
    features = CORE_FEATURES if args.features == "core" else ALL_FEATURES
    inputs = load_labor_inputs(first_month=TRAIN_START, last_month=args.end, releases=releases,
                               as_of=datetime.now(timezone.utc).date(), with_adp=args.features == "all",
                               cache_dir=args.cache_dir)
    nowcasts = payroll_nowcasts(inputs, months, releases, train_from=TRAIN_START, features=features)
    decisions = build_labor_decisions(markets, nowcasts)
    histories = labor_histories(client, markets, results, args.mode)
    quoted = quoted_only(decisions, histories)
    result = run_backtest(engine="labor_nowcast", cadence="monthly", decisions=quoted, histories=histories,
                          mode=args.mode)
    firsts = {event_month(raw["event_ticker"]): parse_expiration_value(raw["expiration_value"]) / 1000.0 for raw in raws}
    kalshi_means = kalshi_implied_means(markets, histories)
    both = [m for m in nowcasts if m in kalshi_means and m in firsts]
    config = {"engine": "labor_nowcast", "series": PAYROLL_SERIES, "mode": args.mode, "features": list(features),
              "start": args.start.isoformat(), "end": args.end.isoformat()}
    row = build_backtest_run_row(
        result, engine_version=LABOR_ENGINE_VERSION, config=config,
        data_hash=data_snapshot_hash(quoted, histories),
        date_from=datetime.combine(args.start, time(0), tzinfo=timezone.utc),
        date_to=datetime.combine(args.end, time(23, 59), tzinfo=timezone.utc),
    )
    report = {key: row[key] for key in ("engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                                        "brier_ours", "brier_market", "gate_status", "gate_reasons")}
    report.update({
        "months": len(nowcasts),
        "unquoted_dropped": len(decisions) - len(quoted),
        "months_with_kalshi_mean": len(both),
        "mae_nowcast_k": round(statistics.fmean(abs(nowcasts[m].mu - firsts[m]) for m in both), 1) if both else None,
        "mae_kalshi_k": round(statistics.fmean(abs(kalshi_means[m] - firsts[m]) for m in both), 1) if both else None,
    })
    print(json.dumps(report, default=str, indent=2))
    if args.record:
        from tradehub.core.supabase_client import get_client

        record_backtest_run(get_client(), row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
