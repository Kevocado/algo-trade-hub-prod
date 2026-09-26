"""One-shot scan (suggest-only): predict every open weather/gas/CPI market, flag trade-worthy edges.

Writes every prediction to the predictions ledger and upserts edges (with Kalshi deep links)
into kalshi_edges. Never places orders. Cron-ready: runs once and exits.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.data.cleveland_fed import fetch_nowcast_history
from tradehub.data.kalshi_live import KalshiLive
from tradehub.data.rbob import front_month_roll_dates, rbob_closes
from tradehub.data.weather import (
    WEATHER_CITIES,
    weather_decision_time,
    City,
    forecast_target_date,
    historical_forecast_highs_range,
    live_forecast_highs,
)
from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.cpi import (
    CPI_TARGETS,
    CPI_TRAIN_MONTHS,
    cpi_prob,
    fit_cpi_error,
    latest_nowcast,
    training_pairs,
)
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
from tradehub.engines.weather import (
    MIN_ERROR_PAIRS,
    WEATHER_ENGINE_VERSION,
    ErrorModel,
    walk_forward_error_model,
    weather_prob,
)
from tradehub.markets import KalshiMarket, event_date, event_month, market_url
from tradehub.predictions import build_prediction_row
from tradehub.sports.scan import (
    prune_sports_if_healthy, remove_started_sports_edges_errors, run_sports_for_cron, sports_due,
)


log = logging.getLogger(__name__)
SCAN_DEADLINE_SECONDS = 15 * 60
CPI_SCAN_HOURS_ET = (8, 12, 16)  # 08:05 ET is the last run before the 08:25 ET release-day close
_ET = ZoneInfo("America/New_York")


def _ensure_scan_deadline(deadline: float) -> None:
    if time.monotonic() >= deadline:
        raise TimeoutError("scan deadline exceeded")


def edge_row(
    market: KalshiMarket,
    s: EdgeSuggestion,
    edge_type: str,
    *,
    engine: str,
    engine_version: str,
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
        "engine": engine,
        "engine_version": engine_version,
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


def latest_gate_statuses(client, pairs: set[tuple[str, str]]) -> dict[tuple[str, str], str]:
    """Promote a pair only when its latest backtest and track record both say PROMOTED."""
    statuses: dict[tuple[str, str], str] = {}
    for engine, version in pairs:
        backtest = client.table("backtest_runs") \
            .select("engine,engine_version,gate_status,created_at") \
            .eq("engine", engine).eq("engine_version", version) \
            .order("created_at", desc=True).limit(1).execute()
        rows = list(backtest.data or [])
        if not rows or rows[0].get("gate_status") != "PROMOTED":
            statuses[(engine, version)] = "SHADOW"
            continue
        track = client.table("track_record").select("gate_status") \
            .eq("engine", engine).eq("engine_version", version).limit(1).execute()
        track_rows = list(track.data or [])
        statuses[(engine, version)] = (
            "PROMOTED" if track_rows and track_rows[0].get("gate_status") == "PROMOTED" else "SHADOW"
        )
    return statuses


def apply_gate_statuses(edges: list[dict[str, Any]], statuses: dict[tuple[str, str], str]) -> None:
    for row in edges:
        row["gate_status"] = statuses.get((row["engine"], row.get("engine_version", "v0")), "SHADOW")


def remove_closed_cpi_edges(client, now: datetime) -> None:
    """Delete cpi_nowcast edges as soon as their market closes, on every hourly scan.

    One filtered DELETE rather than a SELECT followed by a DELETE per row: the predicate is
    entirely expressible in PostgREST, so the database does the comparison and the round trip
    count does not grow with the number of closed markets.
    """
    client.table("kalshi_edges").delete() \
        .eq("engine", "cpi_nowcast") \
        .lte("expires_at", now.isoformat()) \
        .execute()


def remove_stale_edges(client, produced_by_engine: dict[str, set[str]]) -> None:
    """Delete stale rows only for the scan-owned weather/gas engines."""
    for engine, produced in produced_by_engine.items():
        if engine not in {"weather", "gas", "cpi_nowcast", "sports_nfl", "sports_cfb"}:
            continue
        current_market_ids = {str(market_id)[:50] for market_id in produced}
        result = client.table("kalshi_edges").select("market_id").eq("engine", engine).execute()
        for row in result.data or []:
            market_id = row.get("market_id")
            if market_id and market_id not in current_market_ids:
                client.table("kalshi_edges").delete().eq("engine", engine).eq("market_id", market_id).execute()


def _scan_weather_city(
    live,
    now: datetime,
    cfg: EngineConfig,
    series: str,
    city: City,
    *,
    forecast_fn: Callable[..., list],
    historical_forecast_range_fn: Callable[..., list],
    min_error_pairs: int,
    train_days: int,
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

    train_from = today - timedelta(days=train_days)
    actuals = [
        observation
        for observation in (live.settled_values(series) or [])
        if observation.published_at <= now
        and train_from <= event_date(observation.name) <= today
    ]
    actuals.sort(key=lambda observation: event_date(observation.name))
    calibration_forecasts = defaultdict(list)
    if len(actuals) >= min_error_pairs:
        for observation in historical_forecast_range_fn(city, train_from, today):
            calibration_forecasts[forecast_target_date(observation)].append(observation)
    error = walk_forward_error_model(
        actuals,
        calibration_forecasts,
        now,
        # Same rule as the backtest (lead 1 = decide at D-1 23:30 LST), so live and
        # backtested probabilities come from the same error model.
        decision_time_for=lambda day: weather_decision_time(day, 1, city),
        fallback=fallback,
        min_pairs=min_error_pairs,
    )

    for target, markets in sorted(by_date.items()):
        highs = [
            observation
            for observation in forecast_fn(city, target, now)
            if observation.published_at <= now
        ]
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
                edges.append(edge_row(lm.market, suggestion, "WEATHER", engine="weather",
                                      engine_version=WEATHER_ENGINE_VERSION, updated_at=now))
    return predictions, edges


def scan_weather(
    live, now: datetime, cfg: EngineConfig, *,
    forecast_fn: Callable[..., list] = live_forecast_highs,
    historical_forecast_range_fn: Callable[..., list] = historical_forecast_highs_range,
    cities: dict[str, City] = WEATHER_CITIES,
    train_days: int = 90,
    min_error_pairs: int = MIN_ERROR_PAIRS,
    failures: list[str] | None = None,
) -> tuple[list[dict], list[dict]]:
    if min_error_pairs < 1:
        raise ValueError(f"min_error_pairs must be >= 1, got {min_error_pairs!r}")
    if train_days < 1:
        raise ValueError(f"train_days must be >= 1, got {train_days!r}")
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
                historical_forecast_range_fn=historical_forecast_range_fn,
                min_error_pairs=min_error_pairs,
                train_days=train_days,
            )
        except Exception as exc:
            if failures is None:
                raise
            message = f"weather/{series}: {type(exc).__name__}: {exc}"
            failures.append(message)
            log.exception("scan engine=weather city=%s failed", series)
            log.info("scan engine=weather city=%s predictions=0 edges=0 status=failed", series)
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


def scan_gas(
    live,
    now: datetime,
    cfg: EngineConfig,
    *,
    rbob_fn: Callable[[], list] = rbob_closes,
    roll_dates_fn: Callable[[date, date], list[date]] = front_month_roll_dates,
) -> tuple[list[dict], list[dict]]:
    known = [o for o in live.settled_values(GAS_SERIES) if o.published_at <= now]
    if not known:
        return [], []
    rbob = rbob_fn()
    last = max(known, key=lambda o: event_date(o.name))
    roll_dates = roll_dates_fn(min(event_date(o.name) for o in known), now.astimezone(timezone.utc).date())
    model = fit_gas_model(
        [(x, y) for x, y, published in gas_training_pairs(known, rbob, roll_dates=roll_dates) if published <= now],
        aaa=known,
    )
    x_now = rbob_change(rbob, now, roll_dates=roll_dates)
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
            edges.append(edge_row(lm.market, suggestion, "ENERGY", engine="gas",
                                  engine_version=GAS_ENGINE_VERSION, updated_at=now))
    return predictions, edges


def cpi_scan_due(now: datetime) -> bool:
    """The nowcast moves at most once a day, so CPI runs on three of the hourly scans, not all 24."""
    return now.astimezone(_ET).hour in CPI_SCAN_HOURS_ET


def scan_cpi(
    live, now: datetime, cfg: EngineConfig, *,
    nowcast_fn: Callable[[str], dict] = fetch_nowcast_history,
    targets: dict[str, tuple[str, str]] = CPI_TARGETS,
) -> tuple[list[dict], list[dict]]:
    window = int(cfg.params.get("train_months", CPI_TRAIN_MONTHS))
    use_bias = bool(cfg.params.get("use_bias", 0.0))
    predictions: list[dict] = []
    edges: list[dict] = []
    for series, (kind, version) in targets.items():
        markets = live.open_markets(series)
        if not markets:
            continue
        history = nowcast_fn(kind)
        for lm in markets:
            try:
                nowcast = latest_nowcast(history.get(event_month(lm.market.event_ticker)), now)
                horizon = lm.market.close_time - now
                if nowcast is None or horizon <= timedelta(0):
                    continue
                pairs = training_pairs(history, now, horizon)[-window:]
                model = fit_cpi_error(pairs, window=window, use_bias=use_bias)
                prob = cpi_prob(lm.market, nowcast.value, model)
                predictions.append(build_prediction_row(
                    market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="cpi_nowcast",
                    as_of=now, engine_version=version,
                    raw_payload={"nowcast": nowcast.value, "nowcast_obs": nowcast.name, "bias": model.bias,
                                 "sigma": model.sigma, "n_train": len(pairs),
                                 "hours_to_close": round(horizon.total_seconds() / 3600.0, 2)},
                ))
                suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                           prefer_maker=cfg.prefer_maker)
                if suggestion:
                    edges.append(edge_row(lm.market, suggestion, "MACRO", engine="cpi_nowcast",
                                          engine_version=version, updated_at=now))
            except Exception:
                log.exception("scan engine=cpi_nowcast market=%s failed; skipping", lm.market.ticker)
    return predictions, edges


def main(
    *,
    now: datetime | None = None,
    live=None,
    client=None,
    deadline: float | None = None,
) -> int:
    from tradehub.core.supabase_client import get_client, upsert_opportunities
    from tradehub.predictions import record_predictions

    now = now or datetime.now(timezone.utc)
    deadline = time.monotonic() + SCAN_DEADLINE_SECONDS if deadline is None else float(deadline)
    failures: list[str] = []
    engine_states: dict[str, dict[str, Any]] = {}
    if live is None:
        live = KalshiLive(deadline=deadline)

    def forecast_with_deadline(city, target, as_of):
        return live_forecast_highs(city, target, as_of, deadline=deadline)

    def historical_forecast_with_deadline(city, start, end):
        return historical_forecast_highs_range(city, start, end, deadline=deadline)

    def rbob_with_deadline():
        return rbob_closes(deadline=deadline)

    def run_engine(name: str) -> tuple[list[dict], list[dict]]:
        state = {"predictions": [], "edges": [], "errors": [], "complete": False, "ran": False}
        engine_states[name] = state
        city_failures: list[str] = []
        try:
            _ensure_scan_deadline(deadline)
            cfg = load_engine_config(name)
            if name == "weather":
                predictions, edges = scan_weather(
                    live,
                    now,
                    cfg,
                    forecast_fn=forecast_with_deadline,
                    historical_forecast_range_fn=historical_forecast_with_deadline,
                    failures=city_failures,
                )
            elif name == "gas":
                predictions, edges = scan_gas(live, now, cfg, rbob_fn=rbob_with_deadline)
            else:
                predictions, edges = scan_cpi(live, now, cfg)
            _ensure_scan_deadline(deadline)
        except Exception as exc:
            message = f"{name}: {type(exc).__name__}: {exc}"
            state["errors"].append(message)
            failures.append(message)
            log.exception("scan engine=%s failed", name)
            log.info("scan engine=%s predictions=0 edges=0 status=failed", name)
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
    cpi_predictions: list[dict] = []
    cpi_edges: list[dict] = []
    if cpi_scan_due(now):
        cpi_predictions, cpi_edges = run_engine("cpi_nowcast")
    else:
        engine_states["cpi_nowcast"] = {
            "predictions": [], "edges": [], "errors": [], "complete": True, "ran": False,
        }

    if client is None:
        try:
            client = get_client()
        except Exception as exc:
            message = f"client: {type(exc).__name__}: {exc}"
            failures.append(message)
            log.exception("scan client initialization failed")

    sports_predictions: list[dict] = []
    sports_edges: list[dict] = []
    sports_per_sport: dict[str, dict[str, Any]] = {}
    sports_summary: dict[str, Any] = {"status": "skipped: not due (every third UTC hour)"}
    sports_ran = False
    if client is not None and sports_due(now):
        try:
            run = run_sports_for_cron(now, client, deadline=deadline)
            sports_predictions, sports_edges, sports_summary = run.predictions, run.edges, run.reports
            sports_per_sport = run.per_sport
            sports_ran = True
        except Exception as exc:  # a predictor/Kalshi outage must not cost weather/gas
            sports_summary = {"error": repr(exc)}
            failures.append(f"sports: {type(exc).__name__}: {exc}")
            log.exception("scan sports step failed")

    if client is not None:
        try:
            remove_closed_cpi_edges(client, now)
        except Exception as exc:
            failures.append(f"cpi_nowcast.closed_cleanup: {type(exc).__name__}: {exc}")
            log.exception("scan closed CPI edge cleanup failed")
        all_edges = weather_edges + gas_edges + cpi_edges + sports_edges
        pairs = {(row["engine"], row.get("engine_version", "v0")) for row in all_edges}
        try:
            statuses = latest_gate_statuses(client, pairs)
        except Exception as exc:
            message = f"gate_status: {type(exc).__name__}: {exc}"
            failures.append(message)
            statuses = {}
            log.exception("scan gate-status lookup failed")
        for edges in (weather_edges, gas_edges, cpi_edges, sports_edges):
            apply_gate_statuses(edges, statuses)

        prediction_writes: dict[str, str] = {}
        edge_writes: dict[str, str] = {}
        for name, predictions, edges in (
            ("weather", weather_predictions, weather_edges),
            ("gas", gas_predictions, gas_edges),
            ("cpi_nowcast", cpi_predictions, cpi_edges),
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

        for name, edges in (
            ("weather", weather_edges),
            ("gas", gas_edges),
            ("cpi_nowcast", cpi_edges),
        ):
            if not engine_states[name]["complete"] or edge_writes.get(name) != "ok":
                continue
            try:
                remove_stale_edges(client, {name: {row["market_ticker"] for row in edges}})
            except Exception as exc:
                message = f"{name}.cleanup: {type(exc).__name__}: {exc}"
                failures.append(message)
                log.exception("scan stale-edge cleanup failed engine=%s", name)

        writes = {"predictions": prediction_writes, "edges": edge_writes}
        if sports_ran:
            try:
                record_predictions(client, sports_predictions)
                writes["predictions"]["sports"] = "ok"
            except Exception as exc:
                failures.append(f"sports.predictions: {type(exc).__name__}: {exc}")
                writes["predictions"]["sports"] = "failed"
            try:
                upsert_opportunities(sports_edges)
                writes["edges"]["sports"] = "ok"
            except Exception as exc:
                failures.append(f"sports.edges: {type(exc).__name__}: {exc}")
                writes["edges"]["sports"] = "failed"
        else:
            writes["predictions"]["sports"] = "skipped"
            writes["edges"]["sports"] = "skipped"

        # Sports edges are written after the engine loop above, so they are pruned here.
        # A sport prunes only when its feed fetch AND its edge write both succeeded, so neither
        # a feed outage nor a failed upsert can be read as "the engine produced nothing" and
        # delete the live edges. Pruning a zero-edge run is the point: that is exactly when the
        # previous hour's rows must go.
        if sports_ran:
            # Fill in write_ok before pruning, so the health check sees the real outcome.
            for state in sports_per_sport.values():
                state["write_ok"] = writes["edges"].get("sports") == "ok"
            failures.extend(remove_started_sports_edges_errors(client, now))
            failures.extend(prune_sports_if_healthy(client, sports_per_sport,
                                                    remove=remove_stale_edges, now=now))
    else:
        writes = {"predictions": {}, "edges": {}}

    cpi_state = engine_states["cpi_nowcast"]
    cpi_errors = cpi_state["errors"]
    cpi_status = (
        "error: " + "; ".join(error.split(": ", 1)[-1] for error in cpi_errors) if cpi_errors
        else "skipped" if not cpi_state["ran"]
        else "ok"
    )
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
        "cpi_nowcast": {
            "status": cpi_status,
            "predictions": len(cpi_predictions),
            "edges": len(cpi_edges),
            "errors": cpi_errors,
        },
        "sports": sports_summary,
        "writes": writes,
        "failures": failures,
    }
    print(json.dumps(summary, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
