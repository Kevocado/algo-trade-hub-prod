"""One-shot scan (suggest-only): predict every open weather/gas market, flag trade-worthy edges.

Writes every prediction to the predictions ledger and upserts edges (with Kalshi deep links)
into kalshi_edges. Never places orders. Cron-ready: runs once and exits.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.data.kalshi_live import KalshiLive
from tradehub.data.rbob import rbob_closes
from tradehub.data.weather import WEATHER_CITIES, City, historical_forecast_highs, live_forecast_highs
from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
from tradehub.engines.weather import (
    MIN_ERROR_PAIRS,
    WEATHER_ENGINE_VERSION,
    ErrorModel,
    walk_forward_error_model,
    weather_prob,
)
from tradehub.markets import KalshiMarket, event_date, market_url
from tradehub.predictions import build_prediction_row


def edge_row(
    market: KalshiMarket,
    s: EdgeSuggestion,
    edge_type: str,
    *,
    gate_status: str = "SHADOW",
    updated_at: datetime | None = None,
) -> dict[str, Any]:
    timestamp = updated_at or datetime.now(timezone.utc)
    return {
        "market_ticker": market.ticker,
        "market_title": market.title,
        "market_price": s.market_prob,
        "model_probability": s.our_prob,
        "edge": s.net_edge_pct / 100.0,
        "edge_type": edge_type,
        "market_url": market_url(market),
        "side": s.side,
        "entry_price": s.entry_price,
        "maker": s.maker,
        "gate_status": gate_status,
        "updated_at": timestamp.isoformat(),
        "expires_at": market.close_time.isoformat(),
    }


def _mid(quote) -> float | None:
    if quote.yes_bid is None or quote.yes_ask is None:
        return None
    return (quote.yes_bid + quote.yes_ask) / 2.0


def latest_gate_statuses(client, engines: list[str]) -> dict[str, str]:
    """Return the newest backtest gate for each engine, defaulting to SHADOW."""
    requested = list(dict.fromkeys(engines))
    if not requested:
        return {}
    result = (
        client.table("backtest_runs")
        .select("engine,gate_status,created_at")
        .in_("engine", requested)
        .order("created_at", desc=True)
        .execute()
    )
    rows = list(result.data or [])
    statuses: dict[str, str] = {}
    for row in rows:
        engine = row.get("engine")
        if engine in requested and engine not in statuses:
            statuses[engine] = "PROMOTED" if row.get("gate_status") == "PROMOTED" else "SHADOW"
    return {engine: statuses.get(engine, "SHADOW") for engine in requested}


def apply_gate_statuses(edges: list[dict[str, Any]], statuses: dict[str, str]) -> None:
    for row in edges:
        engine = "weather" if row.get("edge_type") == "WEATHER" else "gas"
        row["gate_status"] = statuses.get(engine, "SHADOW")


def remove_stale_edges(client, produced_by_type: dict[str, set[str]]) -> None:
    """Delete only WEATHER/ENERGY rows absent from this scan's edge output."""
    for edge_type, produced in produced_by_type.items():
        result = client.table("kalshi_edges").select("market_id").eq("edge_type", edge_type).execute()
        for row in result.data or []:
            market_id = row.get("market_id")
            if market_id and market_id not in produced:
                client.table("kalshi_edges").delete().eq("market_id", market_id).execute()


def scan_weather(
    live, now: datetime, cfg: EngineConfig, *,
    forecast_fn: Callable[..., list] = live_forecast_highs,
    historical_forecast_fn: Callable[..., list] = historical_forecast_highs,
    cities: dict[str, City] = WEATHER_CITIES,
    min_error_pairs: int = MIN_ERROR_PAIRS,
) -> tuple[list[dict], list[dict]]:
    if min_error_pairs < 1:
        raise ValueError(f"min_error_pairs must be >= 1, got {min_error_pairs!r}")
    fallback = ErrorModel(
        bias=float(cfg.params.get("error_bias", 0.0)),
        sigma=float(cfg.params.get("error_sigma", 2.5)),
    )
    predictions: list[dict] = []
    edges: list[dict] = []
    for series, city in cities.items():
        today = now.astimezone(ZoneInfo(city.lst_timezone)).date()
        by_date = defaultdict(list)
        for lm in live.open_markets(series):
            target = event_date(lm.market.event_ticker)
            if target > today:
                by_date[target].append(lm)
        if not by_date:
            continue

        actuals = [
            observation
            for observation in (live.settled_values(series) or [])
            if observation.published_at <= now
        ]
        actuals.sort(key=lambda observation: event_date(observation.name))
        calibration_forecasts = {}
        if len(actuals) >= min_error_pairs:
            for actual in actuals[-min_error_pairs:]:
                day = event_date(actual.name)
                calibration_forecasts[day] = historical_forecast_fn(city, day, 1)
        error = walk_forward_error_model(
            actuals,
            calibration_forecasts,
            now,
            fallback=fallback,
            min_pairs=min_error_pairs,
        )

        for target, markets in sorted(by_date.items()):
            highs = forecast_fn(city, target, now)
            if not highs:
                continue
            values = [o.value for o in highs]
            for lm in markets:
                prob = weather_prob(lm.market, values, error)
                predictions.append(build_prediction_row(
                    market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="weather",
                    as_of=now, engine_version=WEATHER_ENGINE_VERSION,
                    raw_payload={"highs": {o.name: o.value for o in highs}, "bias": error.bias, "sigma": error.sigma},
                ))
                suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                           prefer_maker=cfg.prefer_maker)
                if suggestion:
                    edges.append(edge_row(lm.market, suggestion, "WEATHER", updated_at=now))
    return predictions, edges


def scan_gas(live, now: datetime, cfg: EngineConfig, *, rbob_fn: Callable[[], list] = rbob_closes) -> tuple[list[dict], list[dict]]:
    known = [o for o in live.settled_values(GAS_SERIES) if o.published_at <= now]
    if not known:
        return [], []
    rbob = rbob_fn()
    last = max(known, key=lambda o: event_date(o.name))
    model = fit_gas_model([(x, y) for x, y, published in gas_training_pairs(known, rbob) if published <= now])
    x_now = rbob_change(rbob, now)
    predictions: list[dict] = []
    edges: list[dict] = []
    for lm in live.open_markets(GAS_SERIES):
        horizon = (event_date(lm.market.event_ticker) - event_date(last.name)).days
        if horizon < 1:
            continue
        prob = gas_prob(lm.market, last.value, horizon, x_now, model)
        predictions.append(build_prediction_row(
            market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="gas", as_of=now,
            engine_version=GAS_ENGINE_VERSION,
            raw_payload={"last_aaa": last.value, "last_aaa_event": last.name, "horizon_days": horizon,
                         "rbob_change": x_now, "alpha": model.alpha, "beta": model.beta, "sigma": model.sigma},
        ))
        suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                   prefer_maker=cfg.prefer_maker)
        if suggestion:
            edges.append(edge_row(lm.market, suggestion, "ENERGY", updated_at=now))
    return predictions, edges


def main() -> int:
    from tradehub.core.supabase_client import get_client, upsert_opportunities
    from tradehub.predictions import record_predictions

    now = datetime.now(timezone.utc)
    live = KalshiLive()
    weather_preds, weather_edges = scan_weather(live, now, load_engine_config("weather"))
    gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
    client = get_client()
    statuses = latest_gate_statuses(client, ["weather", "gas"])
    apply_gate_statuses(weather_edges, statuses)
    apply_gate_statuses(gas_edges, statuses)
    record_predictions(client, weather_preds + gas_preds)
    upsert_opportunities(weather_edges + gas_edges)
    remove_stale_edges(
        client,
        {
            "WEATHER": {row["market_ticker"] for row in weather_edges},
            "ENERGY": {row["market_ticker"] for row in gas_edges},
        },
    )
    print(json.dumps({
        "as_of": now.isoformat(),
        "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
