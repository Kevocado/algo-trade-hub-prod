"""
Kalshi Market Feed — Category-First Fetcher
Strategy: Fetch events (have categories) → then fetch markets per event_ticker.
This bypasses the 15k sports parlay flood in the raw /markets endpoint.
"""

import requests
import os
import time
from dotenv import load_dotenv
import pandas as pd
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

# Load .env from root directory
root_dir = Path(__file__).parent.parent
env_path = root_dir / '.env'
load_dotenv(dotenv_path=env_path, override=True)

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_URL = f"{KALSHI_BASE_URL}/markets"
KALSHI_EVENTS_URL = f"{KALSHI_BASE_URL}/events"
API_KEY = os.getenv("KALSHI_API_KEY")

# Categories we care about (skip Sports, Entertainment, Social, Mentions)
TARGET_CATEGORIES = {
    'Climate and Weather',    # → Weather
    'Economics',              # → Economics
    'Financials',             # → Financials
    'Politics',               # → Politics
    'Elections',              # → Politics
    'Companies',              # → Companies
    'Science and Technology', # → Science
    'Health',                 # → Health
    'World',                  # → World
    'Transportation',         # → World
    'Crypto',                 # → Financials
}

# How to normalize/display categories
CATEGORY_NORMALIZE = {
    'Climate and Weather': 'Weather',
    'Science and Technology': 'Science',
    'Elections': 'Politics',
    'Transportation': 'World',
    'Crypto': 'Financials',
}


# ─── HEADERS HELPER ──────────────────────────────────────────────────
def _headers():
    h = {}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h


# ═══════════════════════════════════════════════════════════════════════
# CATEGORY-FIRST FETCH — Used by HybridScanner
# ═══════════════════════════════════════════════════════════════════════

def _fetch_all_events(max_pages=15):
    """Paginates through ALL open events."""
    headers = _headers()
    all_events = []
    cursor = None

    for page in range(max_pages):
        params = {"limit": 200, "status": "open"}
        if cursor:
            params["cursor"] = cursor
        try:
            r = requests.get(KALSHI_EVENTS_URL, params=params, headers=headers, timeout=10)
            if r.status_code != 200:
                break
            data = r.json()
            batch = data.get('events', [])
            if not batch:
                break
            all_events.extend(batch)
            cursor = data.get('cursor')
            if not cursor:
                break
            time.sleep(0.1)
        except Exception as e:
            print(f"   ❌ Events fetch error: {e}")
            break

    return all_events


def _fetch_markets_for_event(event_ticker, headers):
    """Fetches all markets for a specific event_ticker."""
    try:
        r = requests.get(
            KALSHI_API_URL,
            params={"event_ticker": event_ticker, "status": "open", "limit": 200},
            headers=headers,
            timeout=10
        )
        if r.status_code == 200:
            return r.json().get('markets', [])
    except:
        pass
    return []


def get_all_active_markets(limit_pages=10):
    """
    Category-first fetch strategy:
      1. Fetch all events (have real categories)
      2. Filter to non-Sports categories we care about
      3. Fetch markets per event_ticker using threading
      4. Clean and return with proper categories
    """
    headers = _headers()

    # ── PASS 1: Get all events ──
    print("📋 Pass 1: Scanning event catalog...")
    all_events = _fetch_all_events()

    # Filter to target categories
    target_events = []
    cat_counts = {}
    for e in all_events:
        raw_cat = e.get('category', 'Other')
        if raw_cat in TARGET_CATEGORIES:
            norm_cat = CATEGORY_NORMALIZE.get(raw_cat, raw_cat)
            target_events.append({
                'event_ticker': e.get('event_ticker', ''),
                'category': norm_cat,
                'title': e.get('title', '')
            })
            cat_counts[norm_cat] = cat_counts.get(norm_cat, 0) + 1

    print(f"   ✅ Found {len(target_events)} relevant events from {len(all_events)} total")
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        print(f"      {cat}: {cnt}")

    # ── PASS 2: Fetch markets per event (threaded) ──
    print(f"\n📡 Pass 2: Fetching markets for {len(target_events)} events...")

    all_raw_markets = []
    event_cat_map = {}

    # Build event_ticker → category map
    for ev in target_events:
        event_cat_map[ev['event_ticker']] = ev['category']

    # Thread the market fetches for speed
    fetched_count = 0
    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {}
        for ev in target_events:
            f = executor.submit(_fetch_markets_for_event, ev['event_ticker'], headers)
            futures[f] = ev

        for future in as_completed(futures):
            ev = futures[future]
            try:
                markets = future.result()
                for m in markets:
                    m['_category'] = ev['category']  # Inject category
                all_raw_markets.extend(markets)
                fetched_count += 1
                if fetched_count % 50 == 0:
                    print(f"   📡 Fetched markets for {fetched_count}/{len(target_events)} events...")
            except:
                pass

    print(f"   ✅ Got {len(all_raw_markets)} markets from {fetched_count} events")

    # ── CLEAN ──
    return clean_market_data(all_raw_markets, event_cat_map)

def get_fast_active_markets(limit=1000):
    """
    Fast fetch of just the top N markets using a single API call.
    Bypasses the expensive category/event fetching logic.
    """
    headers = _headers()
    try:
        r = requests.get(KALSHI_API_URL, params={"limit": limit, "status": "open"}, headers=headers, timeout=10)
        if r.status_code == 200:
            return r.json().get('markets', [])
    except Exception as e:
        print(f"  ❌ Fast fetch failed: {e}")
    return []


def clean_market_data(raw_markets, event_cat_map=None):
    """Cleans markets with categories from the event lookup."""
    cleaned = []

    for m in raw_markets:
        # Liquidity Check
        yes_ask = m.get('yes_ask', 0)
        if yes_ask == 0:
            continue

        # Get category (injected or from map)
        category = m.get('_category')
        if not category and event_cat_map:
            category = event_cat_map.get(m.get('event_ticker', ''), 'Other')
        if not category:
            category = 'Other'

        # Clean title
        display_title = m.get('subtitle') or m.get('title', 'Unknown')
        if len(display_title) > 100:
            display_title = display_title[:97] + '...'

        cleaned.append({
            'ticker': m.get('ticker'),
            'title': display_title,
            'category': category,
            'event_ticker': m.get('event_ticker', ''),
            'price': yes_ask,
            'no_price': m.get('no_ask', 0),
            'volume': m.get('volume', 0),
            'expiration': m.get('expiration_time'),
            'spread': abs(yes_ask - m.get('yes_bid', 0)),
            'liquidity': m.get('liquidity', 0),
            'raw': m
        })

    # Sort by Volume
    cleaned.sort(key=lambda x: x['volume'], reverse=True)
    return cleaned


# ═══════════════════════════════════════════════════════════════════════
# TARGETED FETCH — Used by AI Predictor tab for specific tickers
# ═══════════════════════════════════════════════════════════════════════

def get_real_kalshi_markets(ticker):
    """
    Fetches active markets from Kalshi for a specific financial ticker.
    Returns a tuple: (list of market dicts, fetch_method_string, debug_info)
    """
    ticker_map = {
        "BTC": "KXBTC",
        "ETH": "KXETH",
        "SPX": "KXINX",
        "Nasdaq": "KXNASDAQ100"
    }
    series_ticker = ticker_map.get(ticker, ticker)
    headers = _headers()
    debug_info = {"step": "Init", "error": None}

    # Step A: Targeted Fetch
    try:
        params = {
            "series_ticker": series_ticker,
            "status": "open",
            "limit": 200,
        }
        response = requests.get(KALSHI_API_URL, params=params, headers=headers, timeout=10)
        if response.status_code == 200:
            markets = response.json().get('markets', [])
            if markets:
                debug_info["step"] = "Targeted Success"
                return process_markets(markets, ticker), "Targeted", debug_info

    except Exception as e:
        debug_info["error"] = str(e)

    # Step B: Fallback Broad Fetch
    try:
        params = {"limit": 1000, "status": "open"}
        response = requests.get(KALSHI_API_URL, params=params, headers=headers, timeout=15)
        if response.status_code == 200:
            all_m = response.json().get('markets', [])
            filtered = [m for m in all_m if series_ticker in m.get('ticker', '') or ticker in m.get('ticker', '')]
            if filtered:
                debug_info["step"] = "Fallback Success"
                return process_markets(filtered, ticker), "Fallback", debug_info

    except Exception as e:
        debug_info["error"] = str(e)

    debug_info["step"] = "Empty"
    return [], "Empty", debug_info


def process_markets(markets, ticker):
    """Processes raw market data into structured format for the ML predictor."""
    results = []
    for m in markets:
        floor = m.get('floor_strike')
        cap = m.get('cap_strike')

        is_range = (floor is not None and cap is not None)
        if is_range:
            strike_price = None
            market_type = 'range'
        elif floor is not None:
            strike_price = floor
            market_type = 'above'
        elif cap is not None:
            strike_price = cap
            market_type = 'below'
        else:
            continue

        results.append({
            'ticker': ticker,
            'strike_price': strike_price,
            'floor_strike': floor,
            'cap_strike': cap,
            'market_type': market_type,
            'yes_bid': m.get('yes_bid', 0),
            'no_bid': m.get('no_bid', 0),
            'yes_ask': m.get('yes_ask', 0),
            'no_ask': m.get('no_ask', 0),
            'expiration': m.get('expiration_time'),
            'market_id': m.get('ticker'),
            'title': m.get('title', ''),
            'yes_subtitle': m.get('yes_sub_title', ''),
            'no_subtitle': m.get('no_sub_title', '')
        })
    return results


def check_kalshi_connection():
    """Checks if the Kalshi API is accessible."""
    try:
        response = requests.get(KALSHI_API_URL, params={"limit": 1, "status": "open"}, timeout=5)
        return response.status_code == 200
    except:
        return False


# ═══════════════════════════════════════════════════════════════════════
# SERIES-BASED FETCH — Fastest way to get category-specific markets
# ═══════════════════════════════════════════════════════════════════════

# Known series tickers for our target categories
WEATHER_SERIES = {
    # Daily High Temperature (NWS official settlement)
    'NYC': 'KXHIGHNY',
    'Chicago': 'KXHIGHCHI',
    'Miami': 'KXHIGHMIA',
}

# Extended weather series — all climate events Kalshi offers
WEATHER_SERIES_ALL = {
    # Temperature
    'NYC_TEMP': {'series': 'KXHIGHNY', 'city': 'NYC', 'type': 'temperature'},
    'CHI_TEMP': {'series': 'KXHIGHCHI', 'city': 'Chicago', 'type': 'temperature'},
    'MIA_TEMP': {'series': 'KXHIGHMIA', 'city': 'Miami', 'type': 'temperature'},
    # Snowfall (inches)
    'NYC_SNOW': {'series': 'KXSNOWNY', 'city': 'NYC', 'type': 'snowfall'},
    'CHI_SNOW': {'series': 'KXSNOWCHI', 'city': 'Chicago', 'type': 'snowfall'},
    # Wind Speed (mph)
    'NYC_WIND': {'series': 'KXWINDNY', 'city': 'NYC', 'type': 'wind'},
    'CHI_WIND': {'series': 'KXWINDCHI', 'city': 'Chicago', 'type': 'wind'},
    # Precipitation (inches)
    'NYC_RAIN': {'series': 'KXRAINNY', 'city': 'NYC', 'type': 'precipitation'},
    'CHI_RAIN': {'series': 'KXRAINCHI', 'city': 'Chicago', 'type': 'precipitation'},
    'MIA_RAIN': {'series': 'KXRAINMIA', 'city': 'Miami', 'type': 'precipitation'},
}

ECONOMICS_SERIES = {
    'CPI': 'KXLCPIMAXYOY',
    'Fed Rate': 'KXFED',
    'GDP': 'KXGDPYEAR',
    'Recession': 'KXRECSSNBER',
    'Unemployment': 'KXU3MAX',
    'Fed Decision': 'KXFEDDECISION',
}


def get_markets_by_series(series_ticker, limit=200):
    """
    Fetch all open markets for a specific series_ticker.
    This is the FASTEST way to get category-specific markets from Kalshi.

    Args:
        series_ticker: e.g. 'KXHIGHNY', 'KXLCPIMAXYOY', 'KXFED'
        limit: max markets to return

    Returns:
        list of market dicts with all fields from the API
    """
    headers = _headers()
    try:
        params = {
            'series_ticker': series_ticker,
            'status': 'open',
            'limit': limit,
        }
        r = requests.get(KALSHI_API_URL, params=params, headers=headers, timeout=10)
        if r.status_code == 200:
            markets = r.json().get('markets', [])
            return markets
    except Exception as e:
        print(f"  ❌ Failed to fetch series {series_ticker}: {e}")
    return []


def get_weather_markets():
    """Fetch all active daily temperature markets across all cities."""
    all_markets = []
    for city, series in WEATHER_SERIES.items():
        markets = get_markets_by_series(series)
        for m in markets:
            m['_city'] = city
            m['_series'] = series
            m['_type'] = 'temperature'
        all_markets.extend(markets)
        if markets:
            print(f"  ⛈️ {city}: {len(markets)} temperature markets")
    return all_markets


def get_all_weather_markets():
    """Fetch ALL weather markets: temperature, snowfall, wind, precipitation."""
    all_markets = []
    for key, info in WEATHER_SERIES_ALL.items():
        markets = get_markets_by_series(info['series'])
        for m in markets:
            m['_city'] = info['city']
            m['_series'] = info['series']
            m['_type'] = info['type']
        all_markets.extend(markets)
        if markets:
            print(f"  🌦️ {info['city']} {info['type']}: {len(markets)} markets")
    return all_markets


def get_economics_markets():
    """Fetch all active economics markets (CPI, Fed rate, GDP, etc)."""
    all_markets = []
    for label, series in ECONOMICS_SERIES.items():
        markets = get_markets_by_series(series)
        for m in markets:
            m['_econ_type'] = label
            m['_series'] = series
        all_markets.extend(markets)
        if markets:
            print(f"  🏛️ {label}: {len(markets)} markets")
    return all_markets


def get_kalshi_url(market_ticker):
    """
    Generate clickable Kalshi website URL from a market ticker.

    Example:
        KXHIGHNY-26FEB22-T45 → https://kalshi.com/markets/kxhighny
        KXFED-27MAR-T4.00   → https://kalshi.com/markets/kxfed
    """
    # Extract the series part (everything before the first date/number segment)
    # KXHIGHNY-26FEB22-T45 → series is KXHIGHNY
    parts = market_ticker.split('-')
    series = parts[0].lower() if parts else market_ticker.lower()
    return f"https://kalshi.com/markets/{series}"


def get_kalshi_event_url(event_ticker):
    """
    Generate direct event URL on Kalshi.

    Example:
        KXHIGHNY-26FEB22 → https://kalshi.com/markets/kxhighny/kxhighny-26feb22
    """
    parts = event_ticker.split('-')
    series = parts[0].lower() if parts else event_ticker.lower()
    event_lower = event_ticker.lower()
    return f"https://kalshi.com/markets/{series}/{event_lower}"

