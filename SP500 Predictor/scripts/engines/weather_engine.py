"""
Weather Arbitrage Engine - NWS API + Kalshi Series

EDGE SOURCE: National Weather Service is the official settlement source for Kalshi weather markets.
If NWS forecast says 90% chance of 40°F+ high, but Kalshi "above 40°" trading at 50¢ → 40% edge.

KALSHI SERIES (ALL CLIMATE EVENTS):
  Temperature: KXHIGHNY, KXHIGHCHI, KXHIGHMIA
  Snowfall:    KXSNOWNY, KXSNOWCHI
  Wind Speed:  KXWINDNY, KXWINDCHI
  Precipitation: KXRAINNY, KXRAINCHI, KXRAINMIA

DATA: FREE - https://api.weather.gov (NWS is settlement source!)
NWS provides: temperature, precipitation probability, wind speed, snowfall estimates,
              short forecast descriptions, and dew point data.
"""

import requests
from datetime import datetime, timedelta
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
from src.kalshi_feed import get_weather_markets, get_kalshi_event_url


class WeatherEngine:
    def __init__(self):
        self.base_url = "https://api.weather.gov"

        # NWS gridpoints for cities with Kalshi markets
        self.cities = {
            'NYC': {'office': 'OKX', 'gridX': 33, 'gridY': 37},
            'Chicago': {'office': 'LOT', 'gridX': 76, 'gridY': 74},
            'Miami': {'office': 'MFL', 'gridX': 110, 'gridY': 50},
        }

        self.conn_str = os.getenv("AZURE_CONNECTION_STRING", "").strip('"').strip("'")
        self.blob_service = None
        self.container_name = "weather-forecasts"
        
        if self.conn_str:
            try:
                from azure.storage.blob import BlobServiceClient
                self.blob_service = BlobServiceClient.from_connection_string(self.conn_str, connection_timeout=10, read_timeout=10)
                try:
                    self.blob_service.create_container(self.container_name, connection_timeout=10, read_timeout=10)
                except Exception:
                    pass
            except Exception as e:
                print(f"    ⚠️ failed to initialize blob service in WeatherEngine: {e}")

    def get_nws_forecast(self, city):
        """
        Fetch NWS hourly forecast and extract high temp predictions.
        Returns forecast highs for today and tomorrow.
        """
        try:
            grid = self.cities[city]
            url = f"{self.base_url}/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast/hourly"

            response = requests.get(url, headers={'User-Agent': 'KalshiEdgeFinder/1.0'}, timeout=15)
            response.raise_for_status()

            data = response.json()
            periods = data['properties']['periods']

            # Group temps by date, strict 6 AM to 6 PM window (Kalshi rules)
            daily_highs = {}
            for p in periods:
                dt = datetime.fromisoformat(p['startTime'].replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d')
                
                # Kalshi strictly settles based on the 6AM-6PM High Temp
                if 6 <= dt.hour <= 18:
                    temp = p['temperature']
                    if date_str not in daily_highs or temp > daily_highs[date_str]:
                        daily_highs[date_str] = temp

            return daily_highs

        except Exception as e:
            print(f"    ⚠️ NWS fetch error for {city}: {e}")
            return {}

    def get_nws_full_forecast(self, city):
        """
        Fetch comprehensive NWS forecast including temp, precip, wind, snow.
        Returns dict per date with all climate metrics.
        """
        try:
            grid = self.cities[city]
            url = f"{self.base_url}/gridpoints/{grid['office']}/{grid['gridX']},{grid['gridY']}/forecast/hourly"
            response = requests.get(url, headers={'User-Agent': 'KalshiEdgeFinder/1.0'}, timeout=15)
            response.raise_for_status()
            periods = response.json()['properties']['periods']

            daily = {}
            for p in periods:
                dt = datetime.fromisoformat(p['startTime'].replace('Z', '+00:00'))
                date_str = dt.strftime('%Y-%m-%d')

                if date_str not in daily:
                    daily[date_str] = {
                        'high_temp': None,
                        'max_wind': 0,
                        'max_precip_pct': 0,
                        'snow_likely': False,
                        'conditions': set(),
                    }

                temp = p['temperature']
                wind_speed = p.get('windSpeed', '0 mph')
                precip_pct = p.get('probabilityOfPrecipitation', {}).get('value', 0) or 0
                short_forecast = p.get('shortForecast', '').lower()

                # Temperature (6AM-6PM only for Kalshi)
                if 6 <= dt.hour <= 18:
                    if daily[date_str]['high_temp'] is None or temp > daily[date_str]['high_temp']:
                        daily[date_str]['high_temp'] = temp

                # Wind speed (extract number from "10 mph")
                try:
                    ws = int(str(wind_speed).split()[0])
                    if ws > daily[date_str]['max_wind']:
                        daily[date_str]['max_wind'] = ws
                except (ValueError, IndexError):
                    pass

                # Precipitation probability
                if precip_pct > daily[date_str]['max_precip_pct']:
                    daily[date_str]['max_precip_pct'] = precip_pct

                # Snow detection
                if any(w in short_forecast for w in ['snow', 'sleet', 'ice', 'wintry']):
                    daily[date_str]['snow_likely'] = True

                # Conditions summary
                daily[date_str]['conditions'].add(short_forecast)

            # Convert condition sets to strings
            for d in daily:
                conditions = daily[d]['conditions']
                # Pick the most descriptive condition
                daily[d]['conditions'] = ', '.join(list(conditions)[:3])

            return daily
        except Exception as e:
            print(f"    ⚠️ NWS full forecast error for {city}: {e}")
            return {}

    def get_all_forecasts(self):
        """
        Fetch all city forecasts. Returns both simple temp dict (for backward compat)
        and full climate data.
        """
        forecasts = {}
        full_forecasts = {}
        for city in self.cities:
            # Simple temp highs (backward compatible)
            highs = self.get_nws_forecast(city)
            if highs:
                forecasts[city] = highs

            # Full climate data
            full = self.get_nws_full_forecast(city)
            if full:
                full_forecasts[city] = full

        # Store full forecasts for UI access
        self._full_forecasts = full_forecasts
        return forecasts

    def check_for_forecast_changes(self, city, new_forecasts):
        """ Compare new daily highs against stored daily highs. Alert on change. """
        if not self.blob_service:
            return
            
        import json
        blob_name = f"forecasts_{city}.json"
        blob_client = self.blob_service.get_blob_client(container=self.container_name, blob=blob_name)
        
        try:
            old_data = blob_client.download_blob().readall()
            old_forecasts = json.loads(old_data)
            
            changes = []
            for date, temp in new_forecasts.items():
                if date in old_forecasts:
                    old_temp = old_forecasts[date]
                    if old_temp != temp:
                        changes.append(f"• {date}: **{old_temp}°F** ➡️ **{temp}°F**")
            
            if changes:
                from src.discord_notifier import DiscordNotifier
                notifier = DiscordNotifier()
                if notifier.is_enabled():
                    payload = {
                        "content": f"🚨 **NWS Forecast Changed for {city}!** Check your Kalshi positions.\n" + "\n".join(changes)
                    }
                    requests.post(notifier.webhook_url, json=payload)
                    print(f"    🔔 Sent Weather Change Alert for {city}")
        except Exception:
            pass # Blob doesn't exist yet
            
        try:
            blob_client.upload_blob(json.dumps(new_forecasts), overwrite=True)
        except Exception as e:
            print(f"    ⚠️ Failed to sync weather cache for {city}: {e}")

    def find_opportunities(self, kalshi_markets=None):
        """
        Compare NWS forecasts to Kalshi temperature markets.
        Uses get_weather_markets() from kalshi_feed.py to get real market data.

        Returns list of opportunities with edge > 10%.
        """
        # Fetch Kalshi weather markets directly by series ticker
        if kalshi_markets is None:
            kalshi_markets = get_weather_markets()

        if not kalshi_markets:
            print("    No Kalshi weather markets found.")
            return []

        opportunities = []

        # Get NWS forecasts for all cities
        forecasts = {}
        for city in self.cities:
            highs = self.get_nws_forecast(city)
            if highs:
                forecasts[city] = highs
                print(f"    📡 NWS {city}: {highs}")
                self.check_for_forecast_changes(city, highs)

        # Match against Kalshi markets
        now = datetime.now()
        today_str = now.strftime('%Y-%m-%d')

        for market in kalshi_markets:
            city = market.get('_city', '')
            if city not in forecasts:
                continue

            # Parse the market's date from event_ticker (e.g., KXHIGHNY-26FEB23)
            event_ticker = market.get('event_ticker', '')
            market_date = self._parse_event_date(event_ticker)
            if not market_date:
                continue

            # ── EXPIRATION FILTER ──
            # Skip markets whose date has passed
            if market_date < today_str:
                continue
            # Skip same-day markets after 6PM (high temp already recorded)
            if market_date == today_str and now.hour >= 18:
                continue

            # Get the NWS forecast high for that date
            forecast_high = forecasts[city].get(market_date)
            if forecast_high is None:
                continue

            # Market structure: floor_strike = "above X", cap_strike = "below X"
            floor = market.get('floor_strike')
            cap = market.get('cap_strike')
            yes_ask = market.get('yes_ask', 0)
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            subtitle = market.get('subtitle', '')
            expiration = market.get('expiration_time', '')

            if yes_ask == 0:
                continue

            # Calculate our probability based on NWS forecast
            edge = None
            action = None
            nws_prob = None

            if floor is not None and cap is None:
                # "Above X" market — e.g. "Will the high temp be >40°?"
                if forecast_high > floor + 3:
                    nws_prob = 90  # Very confident above
                elif forecast_high > floor:
                    nws_prob = 75  # Moderately confident above
                elif forecast_high > floor - 2:
                    nws_prob = 40  # On the edge
                else:
                    nws_prob = 10  # Unlikely above

                edge = nws_prob - yes_ask
                action = 'BUY YES' if edge > 0 else 'BUY NO'

            elif cap is not None and floor is None:
                # "Below X" market — e.g. "Will the high temp be <33°?"
                if forecast_high < cap - 3:
                    nws_prob = 90
                elif forecast_high < cap:
                    nws_prob = 75
                elif forecast_high < cap + 2:
                    nws_prob = 40
                else:
                    nws_prob = 10

                edge = nws_prob - yes_ask
                action = 'BUY YES' if edge > 0 else 'BUY NO'

            elif floor is not None and cap is not None:
                # Range market — e.g. "Will the high temp be 35-36°?"
                if floor <= forecast_high <= cap:
                    nws_prob = 70  # In range
                elif abs(forecast_high - (floor + cap) / 2) <= 2:
                    nws_prob = 35  # Near range
                else:
                    nws_prob = 5   # Out of range

                edge = nws_prob - yes_ask
                action = 'BUY YES' if edge > 0 else 'BUY NO'

            if edge is not None and abs(edge) > 10:
                kalshi_url = get_kalshi_event_url(event_ticker)
                opportunities.append({
                    'engine': 'Weather',
                    'asset': city,
                    'market_title': f"{title} ({subtitle})" if subtitle else title,
                    'market_ticker': ticker,
                    'event_ticker': event_ticker,
                    'action': action,
                    'model_probability': nws_prob,
                    'market_price': yes_ask,
                    'edge': abs(edge),
                    'confidence': nws_prob,
                    'reasoning': f"NWS forecasts {forecast_high}°F high for {city} on {market_date}. "
                                 f"Model says {nws_prob}% prob, market at {yes_ask}¢.",
                    'data_source': 'NWS Official API (Settlement Source)',
                    'kalshi_url': kalshi_url,
                    'market_date': market_date,
                    'expiration': expiration or market_date,
                })

        return opportunities

    def _parse_event_date(self, event_ticker):
        """Parse date from event ticker like KXHIGHNY-26FEB23 → 2026-02-23"""
        try:
            parts = event_ticker.split('-')
            if len(parts) >= 2:
                date_part = parts[1]  # e.g., "26FEB23"
                # Parse: YY + MON + DD
                year = 2000 + int(date_part[:2])
                month_str = date_part[2:5]
                day = int(date_part[5:])
                months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                           'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
                month = months.get(month_str.upper(), 0)
                if month:
                    return f"{year}-{month:02d}-{day:02d}"
        except:
            pass
        return None


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    print("Running Weather Engine...")
    engine = WeatherEngine()

    # Show NWS forecasts
    for city in engine.cities:
        highs = engine.get_nws_forecast(city)
        if highs:
            for date, temp in sorted(highs.items())[:2]:
                print(f"  {city} {date}: High {temp}°F")

    # Find opportunities
    opps = engine.find_opportunities()
    print(f"\n  Found {len(opps)} weather opportunities")
    for o in opps:
        print(f"  {o['asset']}: {o['action']} | Edge: {o['edge']:.1f}% | {o['reasoning'][:80]}")
        print(f"    → {o['kalshi_url']}")
