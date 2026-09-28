"""Oracle bound for an engine: raw Brier, perfectly-calibrated Brier, market Brier.

Usage
-----
Reproduce a backtest window's bound, using the *same* decisions and the *same* scoring
code as `backtest_labor` (it reuses that module's builders and cross-checks its own mean
Brier against `run_backtest`'s, so a disagreement fails loudly instead of quietly):

    python -m tradehub.scripts.oracle_bound --engine labor_nowcast \
        --start 2023-03 --end 2026-08 --market-brier 0.1659

Read the bound off the `predictions` ledger instead (SETTLED rows only, contract-weighted
the way the gate weights them):

    python -m tradehub.scripts.oracle_bound --engine labor_nowcast --from-ledger

The ledger mode exists because a ledger bound and a backtest bound are not the same
measurement: the ledger's `market_prob` is the mid at scan time (07:05/12:05/17:05 ET)
while the backtest's is the quote one hour before close, and the two hold different sets of
rows. Both report their own market Brier, and neither is silently substituted for the other.

What the output means
---------------------
`brier_oracle_pit` replaces every prediction with its own calibration bucket's observed hit
rate, estimated only from rows decided strictly earlier. If that is still worse than
`brier_market`, the residual is discrimination and no recalibration can close it. See
`tradehub/backtest/oracle.py` for the full argument, and for why the full-sample variant is
reported separately rather than used as the headline.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from tradehub.backtest.fills import quote_at
from tradehub.backtest.http import ThrottledGetJson
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.metrics import market_mid, prediction_row
from tradehub.backtest.oracle import oracle_bound
from tradehub.backtest.pit import Decision
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.engines.labor import CORE_FEATURES, PAYROLL_SERIES, TRAIN_START
from tradehub.markets import event_month

ENGINES = ("labor_nowcast",)


def _month_arg(text: str) -> date:
    # Naive intermediate is discarded to a `date`; the return value carries no tz, and this
    # mirrors `backtest_labor._month_arg` so both CLIs accept the same argument strings.
    return datetime.strptime(text, "%Y-%m").date()  # noqa: DTZ007


# ── ledger ────────────────────────────────────────────────────────────────────

def ledger_rows(supa, engine: str) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Settled prediction rows for one engine, shaped for `oracle_bound`.

    Contract-weighted, because the hourly scan predicts the same market many times and an
    unweighted mean would let one contract count ~24 times -- the same reason
    `track_record._contract_weights` exists for the gate.
    """
    from tradehub.track_record import fetch_settled_rows

    rows = fetch_settled_rows(supa, engine)
    quoted = [r for r in rows if r.get("market_prob") is not None]
    counts = Counter(str(r.get("market_ticker")) for r in quoted)
    out: list[dict[str, Any]] = []
    for row in quoted:
        entry = prediction_row(float(row["our_prob"]), float(row["market_prob"]), str(row["result"]),
                               market_ticker=row.get("market_ticker"))
        entry["decided_at"] = row.get("as_of")
        entry["month"] = (row.get("raw_payload") or {}).get("month")
        entry["weight"] = 1.0 / counts[str(row.get("market_ticker"))]
        out.append(entry)
    stats = {"settled_rows": len(rows), "quoted_rows": len(quoted),
             "unquoted_rows": len(rows) - len(quoted), "contracts": len(counts)}
    return out, stats


# ── backtest path ─────────────────────────────────────────────────────────────

def labor_rows(client: KalshiHistoryClient, start: date, end: date
               ) -> tuple[list[dict[str, Any]], list[Decision], dict[str, MarketHistory], list[date]]:
    """Prediction rows from the same point-in-time decisions `backtest_labor` builds.

    Returns the rows, the decisions and histories (so the caller can re-score them with
    `run_backtest`), and the months that produced a nowcast.
    """
    from tradehub.backtest.pit import check_no_lookahead
    from tradehub.data.labor_inputs import load_labor_inputs, payroll_nowcasts
    from tradehub.engines.labor import decision_time, labor_market, payroll_prob
    from tradehub.scripts.backtest_labor import CANDLE_WINDOW, release_dates, settled_ladder

    all_raws = client.settled_markets(PAYROLL_SERIES)
    raws = settled_ladder(all_raws, start, end)
    markets = [labor_market(raw) for raw in raws]
    results = {raw["ticker"]: raw["result"] for raw in raws}
    releases = release_dates(all_raws)
    months = sorted({event_month(m.event_ticker) for m in markets})
    inputs = load_labor_inputs(first_month=TRAIN_START, last_month=end, releases=releases,
                               as_of=datetime.now(UTC).date(), with_adp=False)
    nowcasts = payroll_nowcasts(inputs, months, releases, train_from=TRAIN_START, features=CORE_FEATURES)

    rows: list[dict[str, Any]] = []
    decisions: list[Decision] = []
    histories: dict[str, MarketHistory] = {}
    for market in markets:
        nc = nowcasts.get(event_month(market.event_ticker))
        if nc is None:
            continue
        decision = Decision(market.ticker, decision_time(market),
                            payroll_prob(market, nc.mu, nc.sigma), nc.features.sources)
        check_no_lookahead(decision)
        # `market_settled_at` selects the Kalshi tier. Without it `merged_candles` assumes
        # the market is live and calls the /series/... endpoint, which 404s for a market that
        # settled months ago. `backtest_engines.py` and `build_jobs_scorecard.py` both pass it;
        # `backtest_labor.labor_histories` does not, so that script currently crashes on this
        # series. See the report -- it is reported, not fixed here.
        candles = client.merged_candles(market.ticker, market.close_time - CANDLE_WINDOW,
                                        market.close_time,
                                        market_settled_at=market.settlement_ts,
                                        series_ticker=market.series_ticker)
        histories[market.ticker] = MarketHistory(market.ticker, results.get(market.ticker),
                                                 market.close_time, candles, [])
        decisions.append(decision)
        mid = market_mid(quote_at(candles, decision.decided_at))
        if mid is None:
            continue  # unquoted at decision time: no market Brier to compare against
        row = prediction_row(decision.our_prob, mid, str(results[market.ticker]),
                             market_ticker=market.ticker)
        row["decided_at"] = decision.decided_at
        row["month"] = event_month(market.event_ticker).isoformat()
        rows.append(row)
    return rows, decisions, histories, months


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Oracle bound for one engine's Brier.")
    parser.add_argument("--engine", choices=ENGINES, default="labor_nowcast")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--from-ledger", action="store_true", help="score the SETTLED predictions rows")
    source.add_argument("--start", type=_month_arg, help="first reference month, YYYY-MM (backtest mode)")
    parser.add_argument("--end", type=_month_arg, help="last reference month, YYYY-MM (backtest mode)")
    parser.add_argument("--market-brier", type=float, default=None,
                        help="the market Brier to beat, from the published backtest")
    parser.add_argument("--shrink", type=float, default=5.0, help="pseudo-observations for the PIT rate")
    args = parser.parse_args(argv)

    report: dict[str, Any] = {"engine": args.engine, "source": "ledger" if args.from_ledger else "backtest"}

    if args.from_ledger:
        from tradehub.core.supabase_client import get_client

        rows, stats = ledger_rows(get_client(), args.engine)
        report["ledger"] = stats
    else:
        if args.end is None:
            parser.error("--end is required in backtest mode")
        client = KalshiHistoryClient(get_json=ThrottledGetJson())
        rows, decisions, histories, months = labor_rows(client, args.start, args.end)
        result = run_backtest(engine=args.engine, cadence="monthly", decisions=decisions,
                              histories=histories, mode="taker")
        mine = round(sum(r["brier"] for r in rows) / len(rows), 5) if rows else None
        report["backtest_crosscheck"] = {
            "n_decisions": result.n_decisions,
            "n_rows_scored": len(rows),
            "brier_ours": result.summary["brier_ours"],
            "brier_market": result.summary["brier_market"],
            "n_unquoted": result.n_unquoted,
            "months_with_nowcast": len(months),
            "oracle_rows_brier_ours": mine,
        }
        # A bound whose raw Brier disagrees with the backtest's own is not comparable to any
        # published number, so fail rather than report a number that looks measured.
        if result.summary["brier_ours"] is not None and mine is not None and abs(
                result.summary["brier_ours"] - mine) > 5e-5:
            print("ERROR: oracle rows disagree with run_backtest's Brier "
                  f"({mine} vs {result.summary['brier_ours']}); refusing to report a bound",
                  file=sys.stderr)
            return 2

    if not rows:
        report["bound"] = None
        report["note"] = ("no settled rows carrying a market quote: the bound cannot be computed. "
                          "This is an honest 'not yet', not a negative result.")
        print(json.dumps(report, indent=2, default=str))
        return 1

    report["bound"] = oracle_bound(rows, shrink=args.shrink, market_brier=args.market_brier)
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
