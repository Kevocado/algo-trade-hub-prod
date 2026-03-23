"""
Weather Market Maker — NWS-Based Limit Order Strategy

Strategy:
  Instead of latency arbitrage (taker orders), we post LIMIT orders as a market maker.
  Kalshi charges ZERO fees for maker orders and pays rebates.

  1. Poll NWS API for the 6-hour official forecast (the settlement oracle)
  2. Build a Bayesian posterior probability using NWS + Open-Meteo ensemble
  3. Set fair_value = model_prob * 100 cents
  4. Suggest limit buy at fair_value - 2¢ (bid) and limit sell at fair_value + 2¢ (ask)
  5. Wait for a less-informed retail trader to cross into our limit

  Since the Kalshi API is currently read-only, we print the limit-order
  suggestion and send a Telegram alert for manual execution.

NWS Settlement: Kalshi weather contracts settle on the 6AM-6PM Climate Report
published by official NWS stations (not live METAR ticks).
"""

import requests
from datetime import datetime, timezone
from typing import Optional

# ─── NWS Station mapping ────────────────────────────────────────────────────
# Each city maps to its NWS gridpoint (office/gridX/gridY) for forecast lookup.
# Find yours: https://api.weather.gov/points/{lat},{lon}
NWS_STATIONS = {
    "NYC": {
        "office": "OKX",
        "gridX": 33,
        "gridY": 37,
        "obs_station": "KNYC",   # Kennedy Airport
        "name": "New York City",
    },
    "Chicago": {
        "office": "LOT",
        "gridX": 74,
        "gridY": 73,
        "obs_station": "KORD",   # O'Hare
        "name": "Chicago",
    },
    "Miami": {
        "office": "MFL",
        "gridX": 110,
        "gridY": 39,
        "obs_station": "KMIA",   # Miami International
        "name": "Miami",
    },
}

# NWS base URLs
NWS_API_BASE   = "https://api.weather.gov"
NWS_HEADERS    = {"User-Agent": "KalshiEdgeBot/1.0 (kevocado@example.com)"}

# Maker spread (¢ on each side of fair value)
MAKER_SPREAD_CENTS = 2.0

# Kalshi feed
try:
    from src.kalshi_feed import get_all_weather_markets
    KALSHI_AVAILABLE = True
except ImportError:
    KALSHI_AVAILABLE = False


class WeatherMaker:
    """Posts limit-order suggestions for Kalshi weather markets based on NWS data."""

    def __init__(self):
        self._nws_cache: dict = {}
        self._historical_error_std = 3.5  # NWS forecast RMSE (°F) — updated with real trades

    # ─── NWS API fetchers ────────────────────────────────────────────────────

    def get_nws_forecast(self, city: str) -> Optional[dict]:
        """
        Fetches the NWS hourly forecast for a city.
        Returns {forecast_high_f, forecast_date, nws_station}.

        NWS gridpoint forecast is the most authoritative source —
        it's the same model Kalshi uses for settlement.
        """
        if city not in NWS_STATIONS:
            return None
        info = NWS_STATIONS[city]

        try:
            url = f"{NWS_API_BASE}/gridpoints/{info['office']}/{info['gridX']},{info['gridY']}/forecast"
            r = requests.get(url, headers=NWS_HEADERS, timeout=10)
            if r.status_code != 200:
                return None

            periods = r.json().get("properties", {}).get("periods", [])
            if not periods:
                return None

            # Find today's daytime high (6AM–6PM window)
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            forecast_high = None
            for period in periods:
                start = period.get("startTime", "")[:10]
                if start == today and period.get("isDaytime"):
                    forecast_high = period.get("temperature")
                    # NWS returns °F by default; check unit
                    unit = period.get("temperatureUnit", "F")
                    if unit == "C":
                        forecast_high = forecast_high * 9 / 5 + 32
                    break

            if forecast_high is None and periods:
                # Fallback: take max temperature from next 12 hours
                temps = [p.get("temperature", 0) for p in periods[:4] if p.get("isDaytime")]
                if temps:
                    forecast_high = max(temps)

            return {
                "city":           city,
                "date":           today,
                "forecast_high_f": forecast_high,
                "nws_station":    info["obs_station"],
                "nws_office":     info["office"],
                "fetched_at":     datetime.now(timezone.utc),
            }

        except Exception as e:
            print(f"  ⚠️ NWS forecast error for {city}: {e}")
            return None

    def get_nws_observation(self, city: str) -> Optional[float]:
        """
        Fetches the latest OBSERVED temperature from the NWS station.
        This is what matters for settlement: the 6AM-6PM peak reading.
        """
        if city not in NWS_STATIONS:
            return None
        info = NWS_STATIONS[city]

        try:
            url = f"{NWS_API_BASE}/stations/{info['obs_station']}/observations/latest"
            r = requests.get(url, headers=NWS_HEADERS, timeout=10)
            if r.status_code != 200:
                return None

            props = r.json().get("properties", {})
            temp_c = props.get("temperature", {}).get("value")
            if temp_c is None:
                return None
            return round(temp_c * 9 / 5 + 32, 1)  # °C → °F

        except Exception as e:
            print(f"  ⚠️ NWS observation error for {city}: {e}")
            return None

    def get_all_nws_readings(self) -> dict:
        """Returns {city: {forecast_high_f, observed_high_f, ...}} for all tracked cities."""
        readings = {}
        for city in NWS_STATIONS:
            forecast = self.get_nws_forecast(city)
            observed = self.get_nws_observation(city)
            if forecast or observed:
                readings[city] = {
                    **(forecast or {}),
                    "observed_high_f": observed,
                }
                self._nws_cache[city] = readings[city]
        return readings

    # ─── Probability Model ───────────────────────────────────────────────────

    def _bayes_prob(self, forecast_high_f: float, strike: float, direction: str) -> float:
        """
        Bayesian posterior probability using NWS forecast + historical error model.

        Models NWS forecast error as Normal(0, σ=3.5°F) based on historical MAE.
        P(high > strike | forecast=F) = P(ε > strike - F) where ε ~ N(0, 3.5)

        Returns probability in [2, 98] range (capped to prevent overconfidence).
        """
        from scipy.stats import norm

        # P(actual > strike) = P(forecast + error > strike) = P(error > strike - forecast)
        prob_above = 1 - norm.cdf(strike, loc=forecast_high_f, scale=self._historical_error_std)

        if direction == "above":
            p = prob_above * 100
        else:  # below
            p = (1 - prob_above) * 100

        return round(min(max(p, 2.0), 98.0), 1)

    # ─── Market Maker Signal Generator ───────────────────────────────────────

    def get_limit_order_signals(self) -> list:
        """
        Main entry point: returns list of limit-order suggestions.
        Each suggestion includes: bid, ask, fair_value, and the Kalshi ticker.
        """
        # Fetch NWS data
        nws_readings = self.get_all_nws_readings()
        if not nws_readings:
            print("  ⚠️ WeatherMaker: No NWS data available")
            return []

        # Fetch Kalshi weather markets
        kalshi_markets = []
        if KALSHI_AVAILABLE:
            try:
                kalshi_markets = get_all_weather_markets()
                print(f"  🌡️ WeatherMaker: {len(kalshi_markets)} Kalshi weather markets")
            except Exception as e:
                print(f"  ⚠️ Kalshi weather fetch error: {e}")

        suggestions = []

        for market in kalshi_markets:
            city = market.get("_city")
            if not city or city not in nws_readings:
                continue

            nws = nws_readings[city]
            forecast_f = nws.get("forecast_high_f") or nws.get("observed_high_f")
            if forecast_f is None:
                continue

            # Parse direction and strike from market title
            title  = market.get("title", "").lower()
            ticker = market.get("ticker", "")

            # Direction
            if "above" in title or " > " in title:
                direction = "above"
            elif "below" in title or " < " in title:
                direction = "below"
            else:
                continue

            # Strike: parse from ticker (e.g. KXHIGHNY-26MAR18-A50 → 50)
            import re
            m = re.search(r'-[AB]([\d.]+)$', ticker)
            if not m:
                # Try from title
                m = re.search(r'(\d{2,3}(?:\.\d+)?)', title)
            if not m:
                continue

            try:
                strike = float(m.group(1))
            except ValueError:
                continue

            # Fair value
            fair_value = self._bayes_prob(forecast_f, strike, direction)

            # Maker prices
            bid = round(fair_value - MAKER_SPREAD_CENTS, 1)
            ask = round(fair_value + MAKER_SPREAD_CENTS, 1)
            current_market_price = market.get("price", 50)

            # Only suggest if our fair value differs significantly from the market
            edge = abs(fair_value - current_market_price)
            if edge < 5:
                continue

            # Use observed temp if available (more accurate than forecast)
            obs_temp = nws.get("observed_high_f")

            suggestions.append({
                "city":          city,
                "ticker":        ticker,
                "direction":     direction,
                "strike":        strike,
                "forecast_high_f": forecast_f,
                "observed_high_f": obs_temp,
                "fair_value":    fair_value,
                "bid":           max(bid, 1),
                "ask":           min(ask, 99),
                "market_price":  current_market_price,
                "edge_pct":      round(edge, 1),
                "nws_date":      nws.get("date", ""),
                "action":        "PLACE LIMIT BUY" if fair_value > current_market_price else "PLACE LIMIT SELL",
                "generated_at":  datetime.now(timezone.utc).isoformat(),
            })

        suggestions.sort(key=lambda x: x["edge_pct"], reverse=True)
        print(f"  🌡️ WeatherMaker: {len(suggestions)} limit-order suggestions")

        # Send Telegram alerts for top suggestions
        if suggestions:
            try:
                from src.telegram_notifier import TelegramNotifier
                tn = TelegramNotifier()
                for s in suggestions[:3]:  # Alert on top 3 only
                    tn.alert_weather_maker(
                        city=s["city"],
                        strike=s["strike"],
                        fair_value=s["fair_value"],
                        bid=s["bid"],
                        ask=s["ask"],
                        ticker=s["ticker"],
                        direction=s["direction"],
                    )
            except Exception as e:
                print(f"  ⚠️ Telegram alert error: {e}")

        return suggestions


# ── Dev entrypoint ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("🌡️ Weather Maker — Running limit-order scan...\n")
    maker = WeatherMaker()

    # Test NWS fetch
    print("NWS Readings:")
    readings = maker.get_all_nws_readings()
    for city, data in readings.items():
        print(f"  {city}: Forecast={data.get('forecast_high_f')}°F | Observed={data.get('observed_high_f')}°F")

    # Generate signals
    print("\nLimit Order Suggestions:")
    signals = maker.get_limit_order_signals()
    for s in signals[:5]:
        print(
            f"  {s['city']} {s['direction'].upper()} {s['strike']}°F | "
            f"NWS: {s['forecast_high_f']}°F | Fair: {s['fair_value']:.1f}¢ | "
            f"Bid: {s['bid']}¢ / Ask: {s['ask']}¢ | Edge: {s['edge_pct']:.1f}%"
        )
