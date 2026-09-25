"""Point-in-time decision builders for the weather and gas engines, plus a backtest CLI.

Each decision carries only observations published at or before its decision time
(checked by tradehub.backtest.pit.check_no_lookahead inside run_backtest); model
parameters are fit walk-forward on data knowable at that time.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from datetime import date, datetime, time, timedelta, timezone
from typing import Mapping
from zoneinfo import ZoneInfo

from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.pit import Decision, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
from tradehub.data.kalshi_live import settlement_observations
from tradehub.data.rbob import rbob_closes
from tradehub.data.weather import WEATHER_CITIES, City, historical_forecast_highs
from tradehub.engines.gas import (
    GAS_ENGINE_VERSION,
    GAS_SERIES,
    RBOB_WINDOW,
    fit_gas_model,
    gas_prob,
    gas_training_pairs,
    rbob_change,
)
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, fit_error_model, weather_prob
from tradehub.markets import KalshiMarket, event_date, parse_market

WEATHER_DECISION_TIME = time(23, 30)
GAS_DECISION_LEAD = timedelta(hours=2)


def weather_decision_time(target: date, lead_days: int, city: City) -> datetime:
    return datetime.combine(target - timedelta(days=lead_days), WEATHER_DECISION_TIME, ZoneInfo(city.lst_timezone))


def build_weather_decisions(
    markets: list[KalshiMarket],
    forecasts: Mapping[date, list[Observation]],
    actuals: list[Observation],
    city: City,
    lead_days: int = 1,
) -> list[Decision]:
    decisions = []
    for market in markets:
        target = event_date(market.event_ticker)
        decided_at = weather_decision_time(target, lead_days, city)
        highs = [observation for observation in (forecasts.get(target) or [])
                 if observation.published_at <= decided_at]
        if not highs:
            continue
        pairs = []
        for actual in actuals:
            day = event_date(actual.name)
            if actual.published_at > decided_at:
                continue
            known_forecasts = [observation for observation in (forecasts.get(day) or [])
                               if observation.published_at <= decided_at]
            if known_forecasts:
                pairs.append((statistics.fmean(observation.value for observation in known_forecasts), actual.value))
        prob = weather_prob(market, [o.value for o in highs], fit_error_model(pairs))
        decisions.append(Decision(market.ticker, decided_at, prob, tuple(highs)))
    return decisions


def build_gas_decisions(markets: list[KalshiMarket], aaa: list[Observation], rbob: list[Observation]) -> list[Decision]:
    rbob_sorted = sorted(rbob, key=lambda o: o.published_at)
    decisions = []
    for market in markets:
        decided_at = market.close_time - GAS_DECISION_LEAD
        known = [o for o in aaa if o.published_at <= decided_at]
        if not known:
            continue
        last = max(known, key=lambda o: event_date(o.name))
        horizon = (event_date(market.event_ticker) - event_date(last.name)).days
        if horizon < 1:
            continue
        model = fit_gas_model([
            (x, y)
            for x, y, published in gas_training_pairs(known, rbob_sorted)
            if published <= decided_at
        ])
        prob = gas_prob(market, last.value, horizon, rbob_change(rbob_sorted, decided_at), model)
        used_rbob = tuple(o for o in rbob_sorted if o.published_at <= decided_at)[-(RBOB_WINDOW + 1):]
        decisions.append(Decision(market.ticker, decided_at, prob, (last,) + used_rbob))
    return decisions


def _histories(
    client: KalshiHistoryClient,
    markets: list[KalshiMarket],
    results: Mapping[str, str | None],
) -> dict[str, MarketHistory]:
    out = {}
    for market in markets:
        out[market.ticker] = MarketHistory(
            ticker=market.ticker,
            result=results.get(market.ticker),
            close_time=market.close_time,
            candles=client.merged_candles(
                market.ticker,
                market.open_time,
                market.close_time,
                series_ticker=market.series_ticker,
            ),
            trades=client.merged_trades(market.ticker, start=market.open_time, end=market.close_time),
        )
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time backtest for the weather or gas engine.")
    parser.add_argument("--engine", choices=["weather", "gas"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
    parser.add_argument("--series", default=None, help="weather series ticker (default KXHIGHNY)")
    parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
    parser.add_argument(
        "--train-days",
        type=int,
        default=90,
        help="days of history before --start used to fit the weather error model",
    )
    args = parser.parse_args(argv)

    client = KalshiHistoryClient()
    series = args.series or ("KXHIGHNY" if args.engine == "weather" else GAS_SERIES)
    settled_raws = client.merged_settled_markets(series)
    raws = [
        raw
        for raw in settled_raws
        if args.start <= event_date(raw["event_ticker"]) <= args.end
    ]
    markets = [parse_market(raw) for raw in raws]
    results = {raw["ticker"]: raw.get("result") for raw in raws}
    if args.engine == "weather":
        city = WEATHER_CITIES[series]
        actuals = settlement_observations(settled_raws)
        train_from = args.start - timedelta(days=args.train_days)
        actuals = [obs for obs in actuals if train_from <= event_date(obs.name) <= args.end]
        days = sorted(
            {event_date(market.event_ticker) for market in markets}
            | {event_date(obs.name) for obs in actuals}
        )
        forecasts = {day: historical_forecast_highs(city, day, 1) for day in days}
        decisions = build_weather_decisions(markets, forecasts, actuals, city)
        version = WEATHER_ENGINE_VERSION
    else:
        aaa = settlement_observations(settled_raws)
        decisions = build_gas_decisions(markets, aaa, rbob_closes())
        version = GAS_ENGINE_VERSION
    histories = _histories(
        client,
        [market for market in markets if market.ticker in {decision.market_ticker for decision in decisions}],
        results,
    )
    result = run_backtest(
        engine=args.engine,
        cadence="daily",
        decisions=decisions,
        histories=histories,
        mode=args.mode,
    )
    config = {
        "engine": args.engine,
        "series": series,
        "mode": args.mode,
        "start": str(args.start),
        "end": str(args.end),
        "train_days": args.train_days,
    }
    row = build_backtest_run_row(
        result,
        engine_version=version,
        config=config,
        data_hash=data_snapshot_hash(decisions, histories),
        date_from=datetime.combine(args.start, time(0), tzinfo=timezone.utc),
        date_to=datetime.combine(args.end, time(23, 59), tzinfo=timezone.utc),
    )
    print(
        json.dumps(
            {
                key: row[key]
                for key in (
                    "engine",
                    "mode",
                    "n_decisions",
                    "n_fills",
                    "pnl_after_fees",
                    "max_drawdown",
                    "brier_ours",
                    "brier_market",
                    "gate_status",
                    "gate_reasons",
                )
            },
            default=str,
            indent=2,
        )
    )
    if args.record:
        from tradehub.core.supabase_client import get_client

        record_backtest_run(get_client(), row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
