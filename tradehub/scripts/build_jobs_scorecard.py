"""Build (or refresh) the Jobs Scorecard: one jobs_scorecard row per release, payrolls and unemployment.

Idempotent: rows are upserted on (series, reference_month), so it can run
monthly after each Employment Situation release (VPS timer) or be re-run
at any time. Uses only public Kalshi endpoints and keyless ALFRED vintages.

    python -m tradehub.scripts.build_jobs_scorecard --since 2023-01 [--dry-run] [--out rows.json]
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.fills import quote_at
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.data.labor_inputs import load_labor_inputs, payroll_nowcasts
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_RESOLUTION,
    PAYROLL_SERIES,
    TRAIN_START,
    U3_RESOLUTION,
    U3_SERIES,
    Vintage,
    add_months,
    decision_time,
    estimate_path,
    first_prints,
    greater_threshold,
    labor_market,
    month_end,
    pre_release_time,
)
from tradehub.engines.ladder import Ladder, isotonic_survival, usable_mid
from tradehub.jobs_scorecard import (
    SERIES_PAYROLLS,
    SERIES_UNEMPLOYMENT,
    NowcastSnapshot,
    scorecard_row,
    upsert_scorecard,
)
from tradehub.markets import KalshiMarket, event_month

U3_BASELINE_VERSION = "u3-naive-v0"
MIN_U3_SIGMA = 0.1
CANDLE_LOOKBACK = timedelta(days=2)  # thin ladders can go hours without a two-sided quote
_ET = ZoneInfo("America/New_York")
log = logging.getLogger(__name__)


def group_events(raws: Iterable[dict[str, Any]], since: date, today: date) -> dict[date, list[KalshiMarket]]:
    """{reference month: markets} for months >= since whose reference month has ended."""
    out: dict[date, dict[str, KalshiMarket]] = defaultdict(dict)
    for raw in raws:
        month = event_month(raw["event_ticker"])
        if month >= since and month_end(month) < today:
            market = labor_market(raw)
            out[month][market.ticker] = market
    return {month: sorted(by_ticker.values(), key=lambda m: m.ticker) for month, by_ticker in out.items()}


def event_ladders(client: KalshiHistoryClient, markets: list[KalshiMarket], resolution: float,
                  unit: float) -> tuple[Ladder, Ladder]:
    """Isotonic Kalshi ladders one hour before the release and at the last pre-release quote.

    One candle request per strike covers both moments.

    `market_settled_at` is what selects the tier: without it `merged_candles` assumes the market is
    still live and builds `/series/{series}/markets/{ticker}/candlesticks`, which 404s for every
    market that settled before `/historical/cutoff`'s `market_settled_ts` -- i.e. all of them, for a
    historical scorecard. An open market has no settlement time, so it correctly stays on the live
    path.

    A market whose candles are missing costs that one strike, not the event: the remaining ladder is
    still a usable (if partial) read on the market, and the scorecard keeps the nowcast-vs-print half
    of the row, which is the part this table exists for.
    """
    at_1h: list[tuple[float, float]] = []
    at_close: list[tuple[float, float]] = []
    for market in markets:
        first, last = decision_time(market), pre_release_time(market)
        try:
            candles = client.merged_candles(market.ticker, first - CANDLE_LOOKBACK, last,
                                            market_settled_at=market.settlement_ts,
                                            series_ticker=market.series_ticker)
        except Exception as exc:
            # Deliberately broad: the failure modes here are HTTP (404 on the wrong tier, 429, 5xx)
            # and payload shape, and one unbuildable strike must not end the run.
            log.warning("jobs scorecard: no candles for %s (%s): %s: %s", market.ticker,
                        market.event_ticker, type(exc).__name__, exc)
            continue
        if not candles:
            log.warning("jobs scorecard: empty candles for %s (%s)", market.ticker, market.event_ticker)
            continue
        cut = greater_threshold(market.floor_strike, resolution) / unit
        for moment, points in ((first, at_1h), (last, at_close)):
            candle = quote_at(candles, moment)
            mid = None if candle is None else usable_mid(candle.yes_bid, candle.yes_ask)
            if mid is not None:
                points.append((cut, mid))
    return isotonic_survival(at_1h), isotonic_survival(at_close)


def _ladder_is_full(markets: list[KalshiMarket], ladder_1h: Ladder, ladder_close: Ladder) -> bool:
    """Did every strike in the event contribute a usable mid at BOTH moments?"""
    return len(ladder_1h) == len(markets) and len(ladder_close) == len(markets)


def u3_baseline(unrate: Mapping[date, Vintage], month: date) -> NowcastSnapshot | None:
    """Naive random walk: last known rate; sigma = RMS of first-print monthly changes over the prior 36 months."""
    vintage = unrate.get(month_end(month))
    if not vintage:
        return None
    last = vintage[max(vintage)]
    prints = first_prints({d: v for d, v in unrate.items() if d <= month_end(month)}, change=False)
    months = sorted(m for m in prints if m < month)[-37:]
    diffs = [prints[b] - prints[a] for a, b in zip(months, months[1:]) if add_months(a, 1) == b]
    sigma = math.sqrt(sum(d * d for d in diffs) / len(diffs)) if len(diffs) >= 6 else 0.2
    return NowcastSnapshot(last, max(MIN_U3_SIGMA, sigma), U3_BASELINE_VERSION, {"last_rate": last})


def _release(markets: list[KalshiMarket]) -> tuple[datetime, date]:
    close = min(m.close_time for m in markets)
    return close, close.astimezone(_ET).date()


def build_rows(client: KalshiHistoryClient, *, since: date, today: date,
               cache_dir: Path | None) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Build every (series, reference_month) row, and the counts that say how well it went.

    Each row is isolated. A Kalshi ladder that cannot be built costs that row its ladder and nothing
    else: the nowcast, the first print and the revisions are the point of the table, and they come
    from ALFRED, not from Kalshi. A row whose ladder failed is still written (with null Kalshi
    fields) and counted in `rows_skipped`, because dropping it would leave the release with no record
    at all -- and `scorecard_exit_code` turns "every row failed" into a non-zero exit, so a total
    Kalshi outage is still loud.
    """
    events: dict[str, dict[date, list[KalshiMarket]]] = {}
    for series in (PAYROLL_SERIES, U3_SERIES):
        raws = client.settled_markets(series) + client.open_markets(series)
        events[series] = group_events(raws, since, today)
    pay_months = sorted(events[PAYROLL_SERIES])
    releases = {month: _release(markets)[1] for month, markets in events[PAYROLL_SERIES].items()}
    inputs = load_labor_inputs(first_month=TRAIN_START, last_month=max(pay_months), releases=releases, as_of=today,
                               unrate_from=add_months(since, -18), with_adp=False, cache_dir=cache_dir)
    nowcasts = payroll_nowcasts(inputs, pay_months, releases, train_from=TRAIN_START)
    stats = {"rows": 0, "rows_with_full_ladder": 0, "rows_skipped": 0}

    def one_row(series: str, month: date, markets: list[KalshiMarket], resolution: float, unit: float,
                *, nowcast: Any, path: Any) -> dict[str, Any]:
        close, release = _release(markets)
        ladder_1h: Ladder = []
        ladder_close: Ladder = []
        full = False
        try:
            ladder_1h, ladder_close = event_ladders(client, markets, resolution, unit)
            full = _ladder_is_full(markets, ladder_1h, ladder_close)
        except Exception as exc:
            log.warning("jobs scorecard: no ladder for %s %s: %s: %s", series, month.isoformat(),
                        type(exc).__name__, exc)
        row = scorecard_row(series=series, month=month, event_ticker=markets[0].event_ticker, release=release,
                            close_time=close, ladder_1h=ladder_1h, ladder_close=ladder_close,
                            nowcast=nowcast, path=path)
        stats["rows"] += 1
        if full:
            stats["rows_with_full_ladder"] += 1
        if not ladder_1h and not ladder_close:
            stats["rows_skipped"] += 1
        return row

    rows = []
    for month in pay_months:
        nc = nowcasts.get(month)
        rows.append(one_row(
            SERIES_PAYROLLS, month, events[PAYROLL_SERIES][month], PAYROLL_RESOLUTION, 1000.0,
            nowcast=None if nc is None else NowcastSnapshot(nc.mu, nc.sigma, LABOR_ENGINE_VERSION, nc.features.values),
            path=estimate_path(inputs.payems, month),
        ))
    for month in sorted(events[U3_SERIES]):
        rows.append(one_row(
            SERIES_UNEMPLOYMENT, month, events[U3_SERIES][month], U3_RESOLUTION, 1.0,
            nowcast=u3_baseline(inputs.unrate, month),
            path=estimate_path(inputs.unrate, month, change=False),
        ))
    return rows, stats


def scorecard_exit_code(stats: dict[str, int]) -> int:
    """Non-zero only when EVERY row lost its ladder.

    A partial outage must not fail a monthly job that still recorded 40 of 42 releases; a total one
    must, or the timer would report success over an empty table.
    """
    rows = stats.get("rows", 0)
    return 1 if rows and stats.get("rows_skipped", 0) >= rows else 0


def _month_arg(text: str) -> date:
    return datetime.strptime(text, "%Y-%m").date()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the Jobs Scorecard (jobs_scorecard table).")
    parser.add_argument("--since", type=_month_arg, default=date(2023, 1, 1), help="first reference month, YYYY-MM")
    parser.add_argument("--cache-dir", type=Path, default=None, help="ALFRED vintage cache (default $TRADEHUB_ALFRED_CACHE)")
    parser.add_argument("--dry-run", action="store_true", help="build rows but do not write to Supabase")
    parser.add_argument("--out", type=Path, default=None, help="also write the rows to this JSON file")
    args = parser.parse_args(argv)

    today = datetime.now(timezone.utc).date()
    rows, stats = build_rows(KalshiHistoryClient(get_json=ThrottledGetJson()), since=args.since, today=today,
                             cache_dir=args.cache_dir)
    if args.out:
        args.out.write_text(json.dumps(rows, indent=1), encoding="utf-8")
    written = 0
    if not args.dry_run:
        from tradehub.core.supabase_client import get_client

        written = upsert_scorecard(get_client(), rows, datetime.now(timezone.utc))
    by_series = defaultdict(int)
    for row in rows:
        by_series[row["series"]] += 1
    print(json.dumps({"rows": len(rows), "by_series": dict(by_series), "written": written,
                      "with_first_print": sum(1 for r in rows if r["first_print"] is not None),
                      "rows_with_full_ladder": stats["rows_with_full_ladder"],
                      "rows_skipped": stats["rows_skipped"]}))
    return scorecard_exit_code(stats)


if __name__ == "__main__":
    sys.exit(main())
