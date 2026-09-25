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
from tradehub.data.weather import WEATHER_CITIES, City, live_forecast_highs
from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
from tradehub.engines.weather import WEATHER_ENGINE_VERSION, ErrorModel, weather_prob
from tradehub.markets import KalshiMarket, event_date, market_url
from tradehub.predictions import build_prediction_row


def edge_row(market: KalshiMarket, s: EdgeSuggestion, edge_type: str) -> dict[str, Any]:
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
    }


def _mid(quote) -> float | None:
    if quote.yes_bid is None or quote.yes_ask is None:
        return None
    return (quote.yes_bid + quote.yes_ask) / 2.0


def scan_weather(
    live, now: datetime, cfg: EngineConfig, *,
    forecast_fn: Callable[..., list] = live_forecast_highs,
    cities: dict[str, City] = WEATHER_CITIES,
) -> tuple[list[dict], list[dict]]:
    error = ErrorModel(bias=cfg.params.get("error_bias", 0.0), sigma=cfg.params.get("error_sigma", 2.5))
    predictions: list[dict] = []
    edges: list[dict] = []
    for series, city in cities.items():
        today = now.astimezone(ZoneInfo(city.lst_timezone)).date()
        by_date = defaultdict(list)
        for lm in live.open_markets(series):
            target = event_date(lm.market.event_ticker)
            if target >= today:
                by_date[target].append(lm)
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
                    edges.append(edge_row(lm.market, suggestion, "WEATHER"))
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
            edges.append(edge_row(lm.market, suggestion, "ENERGY"))
    return predictions, edges


def main() -> int:
    from tradehub.core.supabase_client import get_client, upsert_opportunities
    from tradehub.predictions import record_predictions

    now = datetime.now(timezone.utc)
    live = KalshiLive()
    weather_preds, weather_edges = scan_weather(live, now, load_engine_config("weather"))
    gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
    record_predictions(get_client(), weather_preds + gas_preds)
    upsert_opportunities(weather_edges + gas_edges)
    print(json.dumps({
        "as_of": now.isoformat(),
        "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
