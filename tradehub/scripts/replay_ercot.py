"""Walk-forward replay of the ERCOT peak model. A backtest, not counted in the journal.

Runs `ercot_peak ls-v1` over every operating day ERCOT's daily forecast-zone report covers (from
2024-05-07), refitting monthly on days strictly before each target's month, and scores a fixed 500 MW
"above N MW" ladder with the Brier score. It reports the model's Brier skill against the same-weekday
baseline over the whole span, and -- for the days Kalshi has settled -- against the Kalshi mid at
freeze (hourly candlesticks).

Kalshi's KXTXERCOTPEAKD began in 2026-08, so "the last 3 years" is bounded by ERCOT's own data (from
2024-05-07) and by Kalshi's history (~7 weeks); the report prints the actual spans.

Usage: python -m tradehub.scripts.replay_ercot [--skip-kalshi]
"""

from __future__ import annotations

import argparse
import math
import statistics
from datetime import date, datetime, timedelta

from tradehub.backtest.http import default_get_json, default_get_text
from tradehub.backtest.kalshi_history import KalshiHistoryClient, parse_ts
from tradehub.data.ercot import FIRST_DAY, central_today, fetch_historical_temps, load_peaks
from tradehub.journal.forecasters.ercot import (
    BASELINE_WEEKS,
    MIN_LEAD,
    MIN_TRAIN,
    SERIES,
    fit,
    mean_load,
)
from tradehub.markets import event_date, prob_in_interval

STRIKES = tuple(range(30000, 90001, 500))   # a fixed 500 MW ladder spanning ERCOT's peak range


def samples_for(*, get_json=default_get_json, get_text=default_get_text, cache_dir=None,
                today: date | None = None) -> dict[date, tuple[float, float]]:
    """{operating day: (peak MW, population-weighted max-temp F)}."""
    today = today or central_today()
    peaks = load_peaks(FIRST_DAY, today, get_text=get_text, cache_dir=cache_dir, today=today)
    temps = fetch_historical_temps(FIRST_DAY, today, get_json=get_json)
    return {d: (peaks[d], temps[d]) for d in peaks if d in temps}


def _training(samples: dict[date, tuple[float, float]], day: date) -> list[tuple[date, float, float]]:
    return [(d, p, t) for d, (p, t) in samples.items() if d < day.replace(day=1)]


def _baseline_prob(samples: dict[date, tuple[float, float]], day: date, strike: float) -> float | None:
    prior = [samples[d][0] for d in (day - timedelta(days=7 * k) for k in range(1, BASELINE_WEEKS + 1))
             if d in samples]
    if not prior:
        return None
    return (sum(1 for p in prior if p > strike) + 0.5) / (len(prior) + 1)


def walk_forward(samples: dict[date, tuple[float, float]]) -> list[tuple[date, float, float, float, float]]:
    """(day, strike, outcome, model prob, baseline prob) for every scored contract."""
    rows: list[tuple[date, float, float, float, float]] = []
    for day in sorted(samples):
        train = _training(samples, day)
        if len(train) < MIN_TRAIN:
            continue
        beta, sigma = fit(train)
        mu = mean_load(beta, samples[day][1], day)
        peak = samples[day][0]
        for n in STRIKES:
            base = _baseline_prob(samples, day, n)
            if base is None:
                continue
            outcome = 1.0 if peak > n else 0.0
            rows.append((day, float(n), outcome, prob_in_interval(mu, sigma, (n, math.inf)), base))
    return rows


def _brier(rows: list[tuple], index: int) -> float:
    return statistics.fmean((row[index] - row[2]) ** 2 for row in rows)


def _price_at_freeze(client: KalshiHistoryClient, market: dict, freeze: datetime) -> float | None:
    settled_at = parse_ts(market["settlement_ts"]) if market.get("settlement_ts") else None
    try:
        candles = client.merged_candles(market["ticker"], freeze - timedelta(hours=24), freeze,
                                        market_settled_at=settled_at, series_ticker=SERIES)
    except Exception:   # noqa: BLE001 - an unpriceable market is a skipped contract, never a crash
        return None
    usable = [c for c in candles if c.yes_bid is not None and c.yes_ask is not None]
    if not usable:
        return None
    last = usable[-1]
    return (last.yes_bid + last.yes_ask) / 2.0


def kalshi_replay(samples: dict[date, tuple[float, float]], client: KalshiHistoryClient
                  ) -> list[tuple[str, float, float, float, float]]:
    """(event, strike, outcome, model prob, Kalshi mid at freeze) for the settled rungs we can price."""
    by_event: dict[str, list[dict]] = {}
    for market in client.settled_markets(SERIES):
        if market.get("event_ticker"):
            by_event.setdefault(market["event_ticker"], []).append(market)
    rows: list[tuple[str, float, float, float, float]] = []
    for event, rungs in sorted(by_event.items()):
        day = event_date(event) - timedelta(days=1)
        if day not in samples:
            continue
        train = _training(samples, day)
        if len(train) < MIN_TRAIN:
            continue
        beta, sigma = fit(train)
        mu = mean_load(beta, samples[day][1], day)
        close = next((parse_ts(m["close_time"]) for m in rungs if m.get("close_time")), None)
        if close is None:
            continue
        freeze = close - MIN_LEAD
        for market in rungs:
            strike, result = market.get("floor_strike"), market.get("result")
            if strike is None or result not in ("yes", "no"):
                continue
            price = _price_at_freeze(client, market, freeze)
            if price is None:
                continue
            rows.append((event, float(strike), 1.0 if result == "yes" else 0.0,
                         prob_in_interval(mu, sigma, (float(strike), math.inf)), price))
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-kalshi", action="store_true", help="only the baseline walk-forward")
    parser.add_argument("--cache-dir", default=None)
    args = parser.parse_args()

    samples = samples_for(cache_dir=args.cache_dir)
    rows = walk_forward(samples)
    days = sorted({r[0] for r in rows})
    model, base = _brier(rows, 3), _brier(rows, 4)
    print("=== ERCOT peak model walk-forward (backtest, not counted) ===")
    print(f"span {days[0]} .. {days[-1]}  days={len(days)}  contracts={len(rows)}  strikes/day={len(STRIKES)}")
    print(f"Brier model={model:.4f}  baseline(same weekday, {BASELINE_WEEKS} wks)={base:.4f}  "
          f"skill={100 * (1 - model / base):+.2f}%")

    if args.skip_kalshi:
        return
    kalshi = kalshi_replay(samples, KalshiHistoryClient())
    if not kalshi:
        print("=== vs Kalshi mid: no settled rung could be priced ===")
        return
    events = {r[0] for r in kalshi}
    model_k, book = _brier(kalshi, 3), _brier(kalshi, 4)
    print("=== vs Kalshi mid at freeze (settled events) ===")
    print(f"events={len(events)}  contracts={len(kalshi)}")
    print(f"Brier model={model_k:.4f}  kalshi={book:.4f}  skill={100 * (1 - model_k / book):+.2f}%")


if __name__ == "__main__":
    main()
