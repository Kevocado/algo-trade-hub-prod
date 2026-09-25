"""One-shot scan (suggest-only): predict every open weather/gas market, flag trade-worthy edges.

Writes every prediction to the predictions ledger and upserts edges (with Kalshi deep links)
into kalshi_edges. Never places orders. Cron-ready: runs once and exits.
"""

from __future__ import annotations

import json
import logging
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


log = logging.getLogger(__name__)


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


def _scan_weather_city(
    live,
    now: datetime,
    cfg: EngineConfig,
    series: str,
    city: City,
    *,
    forecast_fn: Callable[..., list],
    historical_forecast_fn: Callable[..., list],
    min_error_pairs: int,
) -> tuple[list[dict], list[dict]]:
    fallback = ErrorModel(
        bias=float(cfg.params.get("error_bias", 0.0)),
        sigma=float(cfg.params.get("error_sigma", 2.5)),
    )
    predictions: list[dict] = []
    edges: list[dict] = []
    today = now.astimezone(ZoneInfo(city.lst_timezone)).date()
    by_date = defaultdict(list)
    for lm in live.open_markets(series):
        target = event_date(lm.market.event_ticker)
        if target > today:
            by_date[target].append(lm)
    if not by_date:
        return predictions, edges

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


def scan_weather(
    live, now: datetime, cfg: EngineConfig, *,
    forecast_fn: Callable[..., list] = live_forecast_highs,
    historical_forecast_fn: Callable[..., list] = historical_forecast_highs,
    cities: dict[str, City] = WEATHER_CITIES,
    min_error_pairs: int = MIN_ERROR_PAIRS,
    failures: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    if min_error_pairs < 1:
        raise ValueError(f"min_error_pairs must be >= 1, got {min_error_pairs!r}")
    predictions: list[dict] = []
    edges: list[dict] = []
    for series, city in cities.items():
        try:
            city_predictions, city_edges = _scan_weather_city(
                live,
                now,
                cfg,
                series,
                city,
                forecast_fn=forecast_fn,
                historical_forecast_fn=historical_forecast_fn,
                min_error_pairs=min_error_pairs,
            )
        except Exception as exc:
            if failures is None:
                raise
            message = f"weather/{series}: {type(exc).__name__}: {exc}"
            failures.append(message)
            log.exception("scan engine=weather city=%s failed", series)
            continue
        predictions.extend(city_predictions)
        edges.extend(city_edges)
        log.info(
            "scan engine=weather city=%s predictions=%d edges=%d",
            series,
            len(city_predictions),
            len(city_edges),
        )
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


def main(
    *,
    now: datetime | None = None,
    live=None,
    client=None,
) -> int:
    from tradehub.core.supabase_client import get_client, upsert_opportunities
    from tradehub.predictions import record_predictions

    now = now or datetime.now(timezone.utc)
    failures: list[str] = []
    engine_states: dict[str, dict[str, Any]] = {}
    if live is None:
        live = KalshiLive()

    def run_engine(name: str) -> tuple[list[dict], list[dict]]:
        state = {"predictions": [], "edges": [], "errors": [], "complete": False, "ran": False}
        engine_states[name] = state
        city_failures: list[str] = []
        try:
            cfg = load_engine_config(name)
            if name == "weather":
                predictions, edges = scan_weather(
                    live,
                    now,
                    cfg,
                    failures=city_failures,
                )
            else:
                predictions, edges = scan_gas(live, now, cfg)
        except Exception as exc:
            message = f"{name}: {type(exc).__name__}: {exc}"
            state["errors"].append(message)
            failures.append(message)
            log.exception("scan engine=%s failed", name)
            return [], []
        state["predictions"] = predictions
        state["edges"] = edges
        state["errors"].extend(city_failures)
        state["complete"] = not city_failures
        state["ran"] = True
        failures.extend(city_failures)
        log.info(
            "scan engine=%s predictions=%d edges=%d",
            name,
            len(predictions),
            len(edges),
        )
        return predictions, edges

    weather_predictions, weather_edges = run_engine("weather")
    gas_predictions, gas_edges = run_engine("gas")

    if client is None:
        try:
            client = get_client()
        except Exception as exc:
            message = f"client: {type(exc).__name__}: {exc}"
            failures.append(message)
            log.exception("scan client initialization failed")

    if client is not None:
        try:
            statuses = latest_gate_statuses(client, ["weather", "gas"])
        except Exception as exc:
            message = f"gate_status: {type(exc).__name__}: {exc}"
            failures.append(message)
            statuses = {"weather": "SHADOW", "gas": "SHADOW"}
            log.exception("scan gate-status lookup failed")
        apply_gate_statuses(weather_edges, statuses)
        apply_gate_statuses(gas_edges, statuses)

        prediction_writes: dict[str, str] = {}
        edge_writes: dict[str, str] = {}
        for name, predictions, edges in (
            ("weather", weather_predictions, weather_edges),
            ("gas", gas_predictions, gas_edges),
        ):
            if not engine_states[name]["ran"]:
                prediction_writes[name] = "skipped"
                edge_writes[name] = "skipped"
                continue
            try:
                record_predictions(client, predictions)
                prediction_writes[name] = "ok"
            except Exception as exc:
                message = f"{name}.predictions: {type(exc).__name__}: {exc}"
                failures.append(message)
                prediction_writes[name] = "failed"
                log.exception("scan prediction write failed engine=%s", name)
            try:
                upsert_opportunities(edges)
                edge_writes[name] = "ok"
            except Exception as exc:
                message = f"{name}.edges: {type(exc).__name__}: {exc}"
                failures.append(message)
                edge_writes[name] = "failed"
                log.exception("scan edge write failed engine=%s", name)

        for name, edge_type, edges in (
            ("weather", "WEATHER", weather_edges),
            ("gas", "ENERGY", gas_edges),
        ):
            if not engine_states[name]["complete"] or edge_writes.get(name) != "ok":
                continue
            try:
                remove_stale_edges(client, {edge_type: {row["market_ticker"] for row in edges}})
            except Exception as exc:
                message = f"{name}.cleanup: {type(exc).__name__}: {exc}"
                failures.append(message)
                log.exception("scan stale-edge cleanup failed engine=%s", name)

        writes = {"predictions": prediction_writes, "edges": edge_writes}
    else:
        writes = {"predictions": {}, "edges": {}}

    summary = {
        "as_of": now.isoformat(),
        "status": "partial_failure" if failures else "ok",
        "weather": {
            "status": (
                "partial_failure" if engine_states["weather"]["ran"] and engine_states["weather"]["errors"]
                else "failed" if not engine_states["weather"]["ran"] else "ok"
            ),
            "predictions": len(weather_predictions),
            "edges": len(weather_edges),
            "errors": engine_states["weather"]["errors"],
        },
        "gas": {
            "status": (
                "partial_failure" if engine_states["gas"]["ran"] and engine_states["gas"]["errors"]
                else "failed" if not engine_states["gas"]["ran"] else "ok"
            ),
            "predictions": len(gas_predictions),
            "edges": len(gas_edges),
            "errors": engine_states["gas"]["errors"],
        },
        "writes": writes,
        "failures": failures,
    }
    print(json.dumps(summary, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
