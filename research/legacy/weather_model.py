"""
Weather Arbitrage Model — Open-Meteo vs Kalshi
Fetches free weather forecasts and compares against Kalshi weather market prices.
"""

import re
import requests
import numpy as np
from datetime import datetime, timezone

# Open-Meteo is free and requires no API key
OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# ─── City → Lat/Lon Mapping ─────────────────────────────────────────
CITY_COORDS = {
    "New York":      {"lat": 40.7128, "lon": -74.0060},
    "NYC":           {"lat": 40.7128, "lon": -74.0060},
    "Chicago":       {"lat": 41.8781, "lon": -87.6298},
    "Miami":         {"lat": 25.7617, "lon": -80.1918},
    "Austin":        {"lat": 30.2672, "lon": -97.7431},
    "Los Angeles":   {"lat": 34.0522, "lon": -118.2437},
    "San Francisco": {"lat": 37.7749, "lon": -122.4194},
    "Seattle":       {"lat": 47.6062, "lon": -122.3321},
    "Denver":        {"lat": 39.7392, "lon": -104.9903},
    "Houston":       {"lat": 29.7604, "lon": -95.3698},
    "Phoenix":       {"lat": 33.4484, "lon": -112.0740},
    "Atlanta":       {"lat": 33.7490, "lon": -84.3880},
    "Boston":        {"lat": 42.3601, "lon": -71.0589},
    "Dallas":        {"lat": 32.7767, "lon": -96.7970},
    "Washington":    {"lat": 38.9072, "lon": -77.0369},
    "DC":            {"lat": 38.9072, "lon": -77.0369},
}


def get_weather_forecast(city):
    """
    Fetches Max/Min Temp and Precip Probability for the next 7 days.
    Uses Open-Meteo API (free, no key needed).
    
    Returns:
        dict: {
            "max_temp_f": float (today's max in °F),
            "min_temp_f": float (today's min in °F),
            "rain_prob": int (max precipitation probability %),
            "snow_prob": int (max snowfall probability %),
            "precip_sum_mm": float (total precipitation mm),
            "forecast_days": list of daily forecasts
        }
        or None if unavailable
    """
    if city not in CITY_COORDS:
        return None

    coords = CITY_COORDS[city]
    params = {
        "latitude": coords['lat'],
        "longitude": coords['lon'],
        "daily": [
            "temperature_2m_max",
            "temperature_2m_min",
            "precipitation_probability_max",
            "snowfall_sum",
            "precipitation_sum"
        ],
        "temperature_unit": "fahrenheit",
        "timezone": "America/New_York",
        "forecast_days": 7
    }

    try:
        r = requests.get(OPEN_METEO_URL, params=params, timeout=10)
        data = r.json()
        daily = data.get('daily', {})

        max_temps = daily.get('temperature_2m_max', [])
        min_temps = daily.get('temperature_2m_min', [])
        precip_probs = daily.get('precipitation_probability_max', [])
        snow_sums = daily.get('snowfall_sum', [])
        precip_sums = daily.get('precipitation_sum', [])

        if not max_temps:
            return None

        # Build daily forecast array
        forecast_days = []
        dates = daily.get('time', [])
        for i in range(len(max_temps)):
            forecast_days.append({
                "date": dates[i] if i < len(dates) else f"Day {i}",
                "max_temp_f": max_temps[i],
                "min_temp_f": min_temps[i] if i < len(min_temps) else None,
                "rain_prob": precip_probs[i] if i < len(precip_probs) else 0,
                "snow_mm": snow_sums[i] if i < len(snow_sums) else 0,
                "precip_mm": precip_sums[i] if i < len(precip_sums) else 0,
            })

        return {
            "max_temp_f": max_temps[0],
            "min_temp_f": min_temps[0] if min_temps else None,
            "rain_prob": precip_probs[0] if precip_probs else 0,
            "snow_mm": snow_sums[0] if snow_sums else 0,
            "precip_mm": precip_sums[0] if precip_sums else 0,
            "forecast_days": forecast_days,
            "city": city
        }
    except Exception as e:
        print(f"    ❌ Weather API Error for {city}: {e}")
        return None


def _parse_city_from_title(title):
    """Extracts city name from a Kalshi market title."""
    for city in CITY_COORDS.keys():
        if city.lower() in title.lower():
            return city
    return None


def _parse_strike_from_title(title):
    """Extracts temperature strike value from title."""
    # Match patterns like "> 50°", "above 50", "below 32°F", etc.
    patterns = [
        r'(\d+(?:\.\d+)?)\s*°',          # 50° or 50°F
        r'(?:above|over|>)\s*(\d+)',      # above 50
        r'(?:below|under|<)\s*(\d+)',     # below 32
    ]
    for p in patterns:
        match = re.search(p, title, re.IGNORECASE)
        if match:
            return float(match.group(1))
    return None


def scan_weather_markets(kalshi_markets):
    """
    Finds edge in Weather markets by comparing Open-Meteo forecasts vs Kalshi prices.
    
    Returns list of opportunities with edge > 15%.
    """
    opportunities = []

    weather_markets = [m for m in kalshi_markets if m.get('category') == 'Weather']

    for m in weather_markets:
        title = m['title']

        # 1. Parse City
        city = _parse_city_from_title(title)
        if not city:
            continue

        # 2. Get Forecast
        forecast = get_weather_forecast(city)
        if not forecast:
            continue

        # 3. Analyze Temperature Markets
        is_temp_market = any(kw in title.lower() for kw in [
            'temperature', 'temp', 'high', 'hot', 'cold', 'degrees'
        ])

        if is_temp_market:
            strike = _parse_strike_from_title(title)
            if strike is None:
                continue

            # Determine direction
            is_above = any(kw in title.lower() for kw in ['above', 'over', '>', 'high'])
            is_below = any(kw in title.lower() for kw in ['below', 'under', '<', 'low'])

            # Calculate our probability
            temp_diff = forecast['max_temp_f'] - strike
            if temp_diff > 5:
                my_prob = 95
            elif temp_diff > 3:
                my_prob = 85
            elif temp_diff > 1:
                my_prob = 70
            elif temp_diff > -1:
                my_prob = 50
            elif temp_diff > -3:
                my_prob = 30
            elif temp_diff > -5:
                my_prob = 15
            else:
                my_prob = 5

            if is_below:
                my_prob = 100 - my_prob

            # Calculate Edge
            edge = my_prob - m['price']

            if abs(edge) > 15:
                action = "BUY YES" if edge > 0 else "BUY NO"
                opportunities.append({
                    "title": title,
                    "city": city,
                    "type": "Temperature",
                    "forecast": f"{forecast['max_temp_f']:.0f}°F",
                    "strike": f"{strike:.0f}°F",
                    "my_prob": my_prob,
                    "mkt_prob": m['price'],
                    "edge": abs(edge),
                    "action": action,
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                })

        # 4. Analyze Rain/Snow Markets
        is_precip_market = any(kw in title.lower() for kw in [
            'rain', 'snow', 'precipitation', 'precip'
        ])

        if is_precip_market:
            is_rain = 'rain' in title.lower()
            is_snow = 'snow' in title.lower()

            if is_rain:
                my_prob = min(95, max(5, forecast['rain_prob']))
            elif is_snow:
                # Snow probability: based on snowfall amount
                if forecast['snow_mm'] > 10:
                    my_prob = 90
                elif forecast['snow_mm'] > 2:
                    my_prob = 60
                elif forecast['snow_mm'] > 0:
                    my_prob = 30
                else:
                    # Check if temp is below freezing and there's precip
                    if forecast.get('min_temp_f', 50) < 32 and forecast['precip_mm'] > 0:
                        my_prob = 40
                    else:
                        my_prob = 10
            else:
                continue

            edge = my_prob - m['price']

            if abs(edge) > 15:
                action = "BUY YES" if edge > 0 else "BUY NO"
                forecast_detail = (
                    f"Rain: {forecast['rain_prob']}%" if is_rain
                    else f"Snow: {forecast['snow_mm']:.1f}mm"
                )
                opportunities.append({
                    "title": title,
                    "city": city,
                    "type": "Rain" if is_rain else "Snow",
                    "forecast": forecast_detail,
                    "strike": "Yes/No",
                    "my_prob": my_prob,
                    "mkt_prob": m['price'],
                    "edge": abs(edge),
                    "action": action,
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                })

    # Sort by edge
    opportunities.sort(key=lambda x: x['edge'], reverse=True)
    return opportunities
