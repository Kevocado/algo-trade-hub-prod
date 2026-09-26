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
from tradehub.data.labor_inputs import load_labor_inputs, payroll_nowcasts
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
from tradehub.gate_status import latest_gate_statuses
from tradehub.engines.cpi import (
    CPI_TARGETS,
    CPI_TRAIN_MONTHS,
    cpi_prob,
    fit_cpi_error,
    latest_nowcast,
    training_pairs,
)
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_SERIES,
    TRAIN_START,
    month_end,
    payroll_prob,
)
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
    prune_sports_if_healthy, remove_started_sports_edges, run_sports_for_cron, sports_due,
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
    """Delete stale rows only for the scan-owned weather/gas/payrolls engines."""
    for engine, produced in produced_by_engine.items():
        if engine not in {"weather", "gas", "cpi_nowcast", "labor_nowcast", "sports_nfl", "sports_cfb"}:
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


def scan_labor(
    live, now: datetime, cfg: EngineConfig, *, inputs_fn: Callable[..., Any] = load_labor_inputs,
    deadline: float | None = None,
) -> tuple[list[dict], list[dict]]:
    """Nowcast the next jobs report once its reference month has ended; predict every open KXPAYROLLS strike."""
    by_month: dict = defaultdict(list)
    for lm in live.open_markets(PAYROLL_SERIES):
        month = event_month(lm.market.event_ticker)
        if month_end(month) < now.astimezone(_ET).date() and lm.market.close_time > now:
            by_month[month].append(lm)
    if not by_month:
        return [], []
    releases = {m: min(lm.market.close_time for lm in lms).astimezone(_ET).date()
                for m, lms in by_month.items()}
    inputs = inputs_fn(first_month=TRAIN_START, last_month=max(by_month), releases=releases, as_of=now.date(),
                       with_adp=False, deadline=deadline)
    nowcasts = payroll_nowcasts(inputs, sorted(by_month), releases, train_from=TRAIN_START)
    predictions: list[dict] = []
    edges: list[dict] = []
    for month, markets in sorted(by_month.items()):
        nc = nowcasts.get(month)
        if nc is None:
            continue
        payload = {"month": month.isoformat(), "mu_k": round(nc.mu, 2), "sigma_k": round(nc.sigma, 2),
                   "features": nc.features.values, "n_train": nc.model.n_train,
                   "coef": dict(zip(nc.model.features, nc.model.coef))}
        for lm in markets:
            try:
                prob = payroll_prob(lm.market, nc.mu, nc.sigma)
            except Exception:
                log.exception("scan engine=labor_nowcast market=%s failed; skipping", lm.market.ticker)
                continue
            predictions.append(build_prediction_row(
                market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="labor_nowcast",
                as_of=now, engine_version=LABOR_ENGINE_VERSION, raw_payload=payload,
            ))
            suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                       prefer_maker=cfg.prefer_maker)
            if suggestion:
                edges.append(edge_row(lm.market, suggestion, "MACRO", engine="labor_nowcast",
                                      engine_version=LABOR_ENGINE_VERSION, updated_at=now))
    return predictions, edges


LABOR_SCAN_HOURS_ET = (7, 12, 17)  # the :05 timer's 07:05 ET run is the last one before the 08:30 release


def labor_scan_due(now: datetime) -> bool:
    return now.astimezone(_ET).hour in LABOR_SCAN_HOURS_ET


def run_labor_step(
    live, now: datetime, cfg: EngineConfig, *,
    scan_fn: Callable[..., tuple[list[dict], list[dict]]] | None = None,
    deadline: float | None = None,
) -> tuple[list[dict], list[dict], str]:
    """scan_labor three times a day, isolated: an ALFRED or Kalshi outage returns a status, never raises.

    The traceback is logged HERE, at the point the exception is caught, so the status string that
    travels to main() does not cost the run its cause.
    """
    if not labor_scan_due(now):
        return [], [], "skipped"
    try:
        predictions, edges = (scan_fn or scan_labor)(live, now, cfg, deadline=deadline)
    except Exception as exc:  # noqa: BLE001 - isolate the engine, report the error
        log.exception("scan engine=labor_nowcast failed")
        return [], [], f"error: {type(exc).__name__}: {exc}"
    return predictions, edges, "ok"


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

    # labor_nowcast is declared here but RUNS LATER, after the weather/gas/CPI writes: its failure
    # mode is an ALFRED outage, and a hung predictor request must not delay or endanger another
    # engine's writes. Its own gated write and cleanup live in the labor block below, ahead of
    # sports (which still runs last of all).
    labor_predictions: list[dict] = []
    labor_edges: list[dict] = []
    labor_status = "skipped: not due (07, 12, 17 ET)"
    engine_states["labor_nowcast"] = {
        "predictions": [], "edges": [], "errors": [], "complete": True, "ran": False,
    }

    if client is None:
        try:
            client = get_client()
        except Exception as exc:
            message = f"client: {type(exc).__name__}: {exc}"
            failures.append(message)
            log.exception("scan client initialization failed")

    if client is not None:
        try:
            remove_closed_cpi_edges(client, now)
        except Exception as exc:
            failures.append(f"cpi_nowcast.closed_cleanup: {type(exc).__name__}: {exc}")
            log.exception("scan closed CPI edge cleanup failed")
        all_edges = weather_edges + gas_edges + cpi_edges
        pairs = {(row["engine"], row.get("engine_version", "v0")) for row in all_edges}
        try:
            statuses = latest_gate_statuses(client, pairs)
        except Exception as exc:
            message = f"gate_status: {type(exc).__name__}: {exc}"
            failures.append(message)
            statuses = {}
            log.exception("scan gate-status lookup failed")
        for edges in (weather_edges, gas_edges, cpi_edges):
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

        # ── labor_nowcast ────────────────────────────────────────────────────────────────
        # After the weather/gas/CPI gate lookup, upserts and cleanups, so an ALFRED hang cannot
        # push those back; before sports, which still runs last. Gated and written separately
        # for the same reason sports is: its edges are keyed on their own (engine,
        # engine_version) pair, and its inputs are a third-party HTTP service.
        if not labor_scan_due(now):
            writes["predictions"]["labor_nowcast"] = "skipped"
            writes["edges"]["labor_nowcast"] = "skipped"
        else:
            try:
                _ensure_scan_deadline(deadline)
            except TimeoutError:
                labor_status = "skipped: scan deadline reached before the labor step"
                writes["predictions"]["labor_nowcast"] = "skipped"
                writes["edges"]["labor_nowcast"] = "skipped"
            else:
                try:
                    labor_cfg = load_engine_config("labor_nowcast")
                    labor_predictions, labor_edges, labor_status = run_labor_step(
                        live, now, labor_cfg, deadline=deadline)
                    labor_failed = labor_status.startswith("error:")
                    labor_errors = [f"labor_nowcast: {labor_status}"] if labor_failed else []
                    engine_states["labor_nowcast"] = {
                        "predictions": labor_predictions, "edges": labor_edges, "errors": labor_errors,
                        # A failed step must never prune: "we could not look" is not "the engine
                        # produced nothing", and the second reading deletes live edges.
                        "complete": not labor_failed, "ran": True,
                    }
                    failures.extend(labor_errors)
                    if not labor_failed:
                        try:
                            labor_statuses = latest_gate_statuses(
                                client, {(row["engine"], row.get("engine_version", "v0"))
                                         for row in labor_edges})
                        except Exception as exc:
                            failures.append(f"labor_nowcast.gate_status: {type(exc).__name__}: {exc}")
                            log.exception("scan labor gate-status lookup failed")
                            labor_statuses = {}
                        apply_gate_statuses(labor_edges, labor_statuses)
                        try:
                            record_predictions(client, labor_predictions)
                            writes["predictions"]["labor_nowcast"] = "ok"
                        except Exception as exc:
                            failures.append(f"labor_nowcast.predictions: {type(exc).__name__}: {exc}")
                            writes["predictions"]["labor_nowcast"] = "failed"
                            log.exception("scan labor prediction write failed")
                        try:
                            upsert_opportunities(labor_edges)
                            writes["edges"]["labor_nowcast"] = "ok"
                        except Exception as exc:
                            failures.append(f"labor_nowcast.edges: {type(exc).__name__}: {exc}")
                            writes["edges"]["labor_nowcast"] = "failed"
                            log.exception("scan labor edge write failed")
                        # Stale rows go only when the step ran completely AND its write landed.
                        if engine_states["labor_nowcast"]["complete"] and writes["edges"]["labor_nowcast"] == "ok":
                            try:
                                remove_stale_edges(client, {
                                    "labor_nowcast": {row["market_ticker"] for row in labor_edges}})
                            except Exception as exc:
                                failures.append(f"labor_nowcast.cleanup: {type(exc).__name__}: {exc}")
                                log.exception("scan stale-edge cleanup failed engine=labor_nowcast")
                except Exception as exc:  # a predictor outage must not cost the other engines
                    labor_status = f"error: {type(exc).__name__}: {exc}"
                    engine_states["labor_nowcast"]["errors"] = [f"labor_nowcast: {labor_status}"]
                    engine_states["labor_nowcast"]["complete"] = False
                    engine_states["labor_nowcast"]["ran"] = True
                    writes["predictions"]["labor_nowcast"] = "failed"
                    writes["edges"]["labor_nowcast"] = "failed"
                    failures.append(f"labor_nowcast: {type(exc).__name__}: {exc}")
                    log.exception("scan labor step failed")


        # ── Sports LAST ────────────────────────────────────────────────────────────────
        # The weather/gas/CPI gate lookup, upserts and cleanups above are already done, so a
        # slow sports run can no longer delay them or put them at risk. Sports is gated and
        # written separately because its edges are keyed on their own (engine, engine_version)
        # pairs and it has its own pruning rules.
        sports_predictions: list[dict] = []
        sports_edges: list[dict] = []
        sports_per_sport: dict[str, dict[str, Any]] = {}
        sports_summary: dict[str, Any] = {"status": "skipped: not due (every third UTC hour)"}
        if not sports_due(now):
            writes["predictions"]["sports"] = "skipped"
            writes["edges"]["sports"] = "skipped"
        else:
            try:
                run = run_sports_for_cron(now, client, deadline=deadline)
                sports_predictions, sports_summary = run.predictions, run.reports
                sports_per_sport = run.per_sport
                try:
                    sports_pairs = {(row["engine"], row.get("engine_version", "v0"))
                                    for row in run.edges}
                    sports_statuses = latest_gate_statuses(client, sports_pairs)
                except Exception as exc:
                    failures.append(f"sports.gate_status: {type(exc).__name__}: {exc}")
                    log.exception("scan sports gate-status lookup failed")
                    sports_statuses = {}
                apply_gate_statuses(run.edges, sports_statuses)
                sports_edges = run.edges
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
                # A sport prunes only when its feed fetch AND its edge write both succeeded, so
                # neither a feed outage nor a failed upsert can be read as "produced nothing".
                # Pruning a zero-edge run is the point: that is when the previous rows must go.
                for state in sports_per_sport.values():
                    state["write_ok"] = writes["edges"].get("sports") == "ok"
                failures.extend(remove_started_sports_edges(client, now))
                failures.extend(prune_sports_if_healthy(client, sports_per_sport,
                                                        remove=remove_stale_edges, now=now))
            except Exception as exc:  # a predictor/Kalshi outage must not cost weather/gas
                sports_summary = {"error": repr(exc)}
                writes["predictions"]["sports"] = "failed"
                writes["edges"]["sports"] = "failed"
                failures.append(f"sports: {type(exc).__name__}: {exc}")
                log.exception("scan sports step failed")
    else:
        writes = {"predictions": {}, "edges": {}}
        # No Supabase client (get_client raised), so nothing below ran. These are read by the
        # summary, and leaving them unbound made main() die with an UnboundLocalError in the one
        # situation where a clear report matters most.
        sports_summary = {"status": "skipped: no Supabase client"}
        labor_status = "skipped: no Supabase client"

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
        "labor_nowcast": {
            "status": labor_status,
            "predictions": len(labor_predictions),
            "edges": len(labor_edges),
            "errors": engine_states["labor_nowcast"]["errors"],
        },
        "sports": sports_summary,
        "writes": writes,
        "failures": failures,
    }
    print(json.dumps(summary, default=str))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
