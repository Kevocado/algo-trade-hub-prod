"""Point-in-time decision builders for the weather, gas and CPI engines, plus a backtest CLI.

Each decision carries only observations published at or before its decision time
(checked by tradehub.backtest.pit.check_no_lookahead inside run_backtest); model
parameters are fit walk-forward on data knowable at that time.
"""

from __future__ import annotations

import argparse
import json
import sys

from datetime import date, datetime, time, timedelta, timezone
from typing import Callable, Iterable, Mapping

from tradehub.backtest.fills import quote_at
from tradehub.backtest.kalshi_history import KalshiHistoryClient
from tradehub.backtest.pit import Decision, Observation
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
from tradehub.data.cleveland_fed import MonthNowcast, fetch_nowcast_history
from tradehub.data.kalshi_live import safe_event_date, settlement_observations
from tradehub.data.rbob import front_month_roll_dates, rbob_closes
from tradehub.data.weather import (
    WEATHER_CITIES,
    WEATHER_DECISION_TIME,  # noqa: F401 - re-exported for callers/tests
    City,
    forecast_target_date,
    historical_forecast_highs_range,
    weather_decision_time,
)
from tradehub.engines.cpi import (
    CPI_SERIES,
    CPI_TARGETS,
    CPI_TRAIN_MONTHS,
    cpi_prob,
    fit_cpi_error,
    latest_nowcast,
    training_pairs,
)
from tradehub.engines.gas import (
    GAS_ENGINE_VERSION,
    GAS_SERIES,
    fit_gas_model,
    gas_prob,
    gas_training_pairs,
    rbob_change_window,
)
from tradehub.engines.weather import (
    DEFAULT_ERROR,
    MIN_ERROR_PAIRS,
    WEATHER_ENGINE_VERSION,
    ErrorModel,
    select_forecast_observations,
    walk_forward_error_model,
    weather_prob,
)
from tradehub.engine_config import load_engine_config
from tradehub.markets import KalshiMarket, event_date, event_month, parse_cpi_market, parse_market

GAS_DECISION_LEAD = timedelta(hours=2)
CPI_DECISION_LEAD = timedelta(minutes=25)  # 08:00 ET on release morning (close is 08:25 ET)



def fetch_weather_forecasts(
    city: City,
    days: Iterable[date],
    *,
    forecast_fn: Callable[[City, date, date], list[Observation]] = historical_forecast_highs_range,
) -> dict[date, list[Observation]]:
    """Fetch one previous-runs range and return stable per-date groups."""
    ordered_days = sorted(set(days))
    if not ordered_days:
        return {}
    observations = forecast_fn(city, ordered_days[0], ordered_days[-1])
    out = {day: [] for day in ordered_days}
    for observation in observations:
        target = forecast_target_date(observation)
        if target in out:
            out[target].append(observation)
    return out


def build_weather_decisions(
    markets: list[KalshiMarket],
    forecasts: Mapping[date, list[Observation]],
    actuals: list[Observation],
    city: City,
    lead_days: int = 1,
    *,
    fallback: ErrorModel = DEFAULT_ERROR,
    min_pairs: int = MIN_ERROR_PAIRS,
) -> list[Decision]:
    decisions = []
    for market in markets:
        target = event_date(market.event_ticker)
        decided_at = weather_decision_time(target, lead_days, city)
        highs = select_forecast_observations(forecasts.get(target, ()), decided_at)
        if not highs:
            continue
        error = walk_forward_error_model(
            actuals,
            forecasts,
            decided_at,
            decision_time_for=lambda day: weather_decision_time(day, lead_days, city),
            min_pairs=min_pairs,
            fallback=fallback,
        )
        prob = weather_prob(market, [o.value for o in highs], error)
        decisions.append(Decision(market.ticker, decided_at, prob, tuple(highs)))
    return decisions


def build_gas_decisions(
    markets: list[KalshiMarket],
    aaa: list[Observation],
    rbob: list[Observation],
    *,
    roll_dates: list[date] | None = None,
) -> list[Decision]:
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
        model = fit_gas_model(
            [
                (x, y)
                for x, y, published in gas_training_pairs(
                    known,
                    rbob_sorted,
                    roll_dates=roll_dates,
                )
                if published <= decided_at
            ],
            aaa=known,
        )
        rbob_window = rbob_change_window(rbob_sorted, decided_at, roll_dates=roll_dates)
        rbob_x = None if rbob_window is None else rbob_window[0]
        used_rbob = () if rbob_window is None else rbob_window[1]
        prob = gas_prob(market, last.value, horizon, rbob_x, model)
        decisions.append(Decision(market.ticker, decided_at, prob, (last,) + used_rbob))
    return decisions


def build_cpi_decisions(
    markets: list[KalshiMarket],
    history: Mapping[date, MonthNowcast],
    *,
    extra_lead: timedelta = timedelta(0),
    window: int = CPI_TRAIN_MONTHS,
    use_bias: bool = False,
) -> list[Decision]:
    decisions = []
    for market in markets:
        decided_at = market.close_time - CPI_DECISION_LEAD - extra_lead
        nowcast = latest_nowcast(history.get(event_month(market.event_ticker)), decided_at)
        if nowcast is None:
            continue
        pairs = training_pairs(history, decided_at, market.close_time - decided_at)[-window:]
        prob = cpi_prob(market, nowcast.value, fit_cpi_error(pairs, window=window, use_bias=use_bias))
        used = tuple(obs for pair in pairs for obs in pair)
        decisions.append(Decision(market.ticker, decided_at, prob, (nowcast,) + used))
    return decisions


def _histories(
    client: KalshiHistoryClient,
    markets: list[KalshiMarket],
    results: Mapping[str, str | None],
    mode: str,
    lookback: timedelta | None = None,
) -> dict[str, MarketHistory]:
    if mode not in ("taker", "maker"):
        raise ValueError(f"mode must be 'taker' or 'maker', got {mode!r}")
    out = {}
    for market in markets:
        start = market.open_time if lookback is None else max(market.open_time, market.close_time - lookback)
        candles = client.merged_candles(
            market.ticker,
            start,
            market.close_time,
            market_settled_at=market.settlement_ts,
            series_ticker=market.series_ticker,
        )
        trades = (
            client.merged_trades(market.ticker, start=start, end=market.close_time)
            if mode == "maker"
            else []
        )
        out[market.ticker] = MarketHistory(
            ticker=market.ticker,
            result=results.get(market.ticker),
            close_time=market.close_time,
            candles=candles,
            trades=trades,
            settled_at=market.settlement_ts,
        )
    return out


def settled_in_range(raws: Iterable[dict], start: date, end: date) -> list[dict]:
    """Settled markets whose event date is in [start, end]; unparseable legacy tickers are skipped."""
    kept = []
    for raw in raws:
        day = safe_event_date(raw.get("event_ticker"))
        if day is not None and start <= day <= end:
            kept.append(raw)
    return kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Point-in-time backtest for the weather, gas or CPI engine.")
    parser.add_argument("--engine", choices=["weather", "gas", "cpi_nowcast"], required=True)
    parser.add_argument("--start", type=date.fromisoformat, required=True)
    parser.add_argument("--end", type=date.fromisoformat, required=True)
    parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
    parser.add_argument("--series", default=None, help="series ticker (default KXHIGHNY / KXAAAGASD / KXCPI)")
    parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
    parser.add_argument(
        "--train-days",
        type=int,
        default=90,
        help="days of history before --start used for weather calibration and RBOB loading",
    )
    parser.add_argument("--lead-days", type=int, default=0,
                        help="cpi_nowcast: decide this many days before release morning (default 0)")
    args = parser.parse_args(argv)
    if args.train_days < 0:
        parser.error("--train-days must be >= 0")
    if args.end < args.start:
        parser.error("--end must not precede --start")

    client = KalshiHistoryClient()
    default_series = {"weather": "KXHIGHNY", "gas": GAS_SERIES, "cpi_nowcast": CPI_SERIES}
    series = args.series or default_series[args.engine]
    if args.engine == "cpi_nowcast" and series not in CPI_TARGETS:
        parser.error(f"unknown CPI series {series!r}; choose from {sorted(CPI_TARGETS)}")
    cfg = load_engine_config(args.engine)
    settled_raws = client.settled_markets(series)
    if args.engine == "cpi_nowcast":
        raws = [raw for raw in settled_raws if args.start <= event_month(raw["event_ticker"]) <= args.end]
    else:
        raws = settled_in_range(settled_raws, args.start, args.end)
    markets = [parse_cpi_market(raw) if args.engine == "cpi_nowcast" else parse_market(raw) for raw in raws]
    results = {raw["ticker"]: raw.get("result") for raw in raws}
    cadence = "daily"
    lookback: timedelta | None = None
    if args.engine == "cpi_nowcast":
        kind, version = CPI_TARGETS[series]
        decisions = build_cpi_decisions(
            markets,
            fetch_nowcast_history(kind),
            extra_lead=timedelta(days=args.lead_days),
        )
        cadence = "monthly"
        lookback = timedelta(days=args.lead_days + 3)
    elif args.engine == "weather":
        city = WEATHER_CITIES[series]
        actuals = settlement_observations(settled_raws)
        train_from = args.start - timedelta(days=args.train_days)
        actuals = [obs for obs in actuals if train_from <= event_date(obs.name) <= args.end]
        days = sorted(
            {event_date(market.event_ticker) for market in markets}
            | {event_date(obs.name) for obs in actuals}
        )
        forecasts = fetch_weather_forecasts(
            city,
            days,
            forecast_fn=historical_forecast_highs_range,
        )
        fallback = ErrorModel(
            bias=float(cfg.params.get("error_bias", DEFAULT_ERROR.bias)),
            sigma=float(cfg.params.get("error_sigma", DEFAULT_ERROR.sigma)),
        )
        decisions = build_weather_decisions(
            markets,
            forecasts,
            actuals,
            city,
            fallback=fallback,
            min_pairs=MIN_ERROR_PAIRS,
        )
        version = WEATHER_ENGINE_VERSION
    else:
        aaa = settlement_observations(settled_raws)
        train_from = args.start - timedelta(days=args.train_days)
        rbob = rbob_closes(start=train_from, end=args.end)
        roll_dates = front_month_roll_dates(train_from, args.end)
        decisions = build_gas_decisions(markets, aaa, rbob, roll_dates=roll_dates)
        version = GAS_ENGINE_VERSION
    histories = _histories(
        client,
        [market for market in markets if market.ticker in {decision.market_ticker for decision in decisions}],
        results,
        mode=args.mode,
        **({"lookback": lookback} if lookback is not None else {}),
    )
    if args.engine == "cpi_nowcast":
        # Score only contracts with a visible quote at decision time, so our Brier and the
        # market's Brier cover the same contracts (the gate needs full market coverage).
        decisions = [d for d in decisions if quote_at(histories[d.market_ticker].candles, d.decided_at) is not None]
    result = run_backtest(
        engine=args.engine,
        cadence=cadence,
        decisions=decisions,
        histories=histories,
        mode=args.mode,
        min_edge_pct=cfg.min_edge_pct,
    )
    config = {
        "engine": args.engine,
        "series": series,
        "mode": args.mode,
        "start": str(args.start),
        "end": str(args.end),
        "train_days": args.train_days,
        "min_edge_pct": cfg.min_edge_pct,
    }
    if args.engine == "cpi_nowcast":
        config["lead_days"] = args.lead_days
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
            }
            | {"n_unquoted": getattr(result, "n_unquoted", 0)},
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
