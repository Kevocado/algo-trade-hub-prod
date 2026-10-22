"""
Kalshi Market Feed — Category-First Fetcher
Strategy: Fetch events (have categories) → then fetch markets per event_ticker.
This bypasses the 15k sports parlay flood in the raw /markets endpoint.
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

from tradehub.markets import quote_cents

# No `load_dotenv()` at import time -- see `tradehub.core.env`. `API_KEY` is
# resolved at call time (see `api_key()`) so an entrypoint that loads its
# environment after importing this module still gets the right value.
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_API_URL = f"{KALSHI_BASE_URL}/markets"
KALSHI_EVENTS_URL = f"{KALSHI_BASE_URL}/events"


def api_key() -> str | None:
    """KALSHI_API_KEY, read now rather than bound at import time."""
    return os.getenv("KALSHI_API_KEY")


# ─── Circuit breaker state (module-level, per-process) ──────────────────
# After 3 consecutive fetch failures (5xx/network), we stop trying for the
# remainder of the journal run to protect the 20-minute budget.
_FETCH_FAILURE_STRIKES = 0
_CIRCUIT_BREAKER_OPEN = False
_MAX_STRIKES = 3


def _reset_circuit_breaker():
    """Reset circuit breaker state (called at start of each journal run)."""
    global _FETCH_FAILURE_STRIKES, _CIRCUIT_BREAKER_OPEN
    _FETCH_FAILURE_STRIKES = 0
    _CIRCUIT_BREAKER_OPEN = False


def _record_fetch_failure():
    """Record a fetch failure; open circuit breaker after 3 strikes."""
    global _FETCH_FAILURE_STRIKES, _CIRCUIT_BREAKER_OPEN
    _FETCH_FAILURE_STRIKES += 1
    if _FETCH_FAILURE_STRIKES >= _MAX_STRIKES:
        _CIRCUIT_BREAKER_OPEN = True


def _record_fetch_success():
    """Record a successful fetch; reset strike counter."""
    global _FETCH_FAILURE_STRIKES, _CIRCUIT_BREAKER_OPEN
    _FETCH_FAILURE_STRIKES = 0
    _CIRCUIT_BREAKER_OPEN = False


def _circuit_open() -> bool:
    return _CIRCUIT_BREAKER_OPEN


# ─── HEADERS HELPER ──────────────────────────────────────────────────
def _headers():
    h = {}
    key = api_key()
    if key:
        h["Authorization"] = f"Bearer {key}"
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
        except Exception as e:  # noqa: BLE001
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
    except Exception:  # noqa: BLE001, S110 - preserve best-effort event fetch
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
            except Exception:  # noqa: BLE001, S110 - preserve best-effort event fetch
                pass

    print(f"   ✅ Got {len(all_raw_markets)} markets from {fetched_count} events")

    # ── CLEAN ──
    return clean_market_data(all_raw_markets, event_cat_map)

# ═══════════════════════════════════════════════════════════════════════
# SPORTS FETCH — Dedicated, keyword-filtered path around the Sports exclusion
# ═══════════════════════════════════════════════════════════════════════
#
# get_all_active_markets() above deliberately excludes the 'Sports' category
# to avoid the ~15k-market parlay/props flood on the raw /markets endpoint.
# That exclusion is still correct for callers who want non-sports categories.
# Sports-specific engines need their own narrower fetch instead of reworking
# the shared one.
#
# NOTE: the league keyword lists below are a starting point for matching
# event/market tickers and titles, not a verified Kalshi contract. Confirm
# actual ticker prefixes against a live `/events?status=open` response
# before trusting the keyword filter in production — see
# (sports brief removed; sports now live in the dedicated predictor repos).
SPORTS_LEAGUE_KEYWORDS = {
    'NBA': ['NBA'],
    'EPL': ['EPL', 'PREM', 'PREMIER LEAGUE'],
    'LALIGA': ['LALIGA', 'LA LIGA'],
}


def get_active_sports_markets(leagues=None, limit_pages=10):
    """
    Fetches only Sports-category events, optionally narrowed to specific
    leagues by keyword match against the event ticker/title. This keeps the
    per-league market count small instead of pulling every sport Kalshi
    offers (tennis, golf, MMA, parlays, etc).

    Args:
        leagues: list of keys into SPORTS_LEAGUE_KEYWORDS (e.g. ['NBA']),
                 or None to return all Sports-category events unfiltered.
        limit_pages: forwarded to the underlying event pagination.

    Returns:
        Cleaned market dicts (same shape as get_all_active_markets).
    """
    headers = _headers()

    keyword_set = set()
    if leagues:
        for lg in leagues:
            keyword_set.update(k.upper() for k in SPORTS_LEAGUE_KEYWORDS.get(lg.upper(), [lg.upper()]))

    print("📋 Pass 1: Scanning Sports event catalog...")
    all_events = _fetch_all_events(max_pages=limit_pages)

    target_events = []
    for e in all_events:
        if e.get('category') != 'Sports':
            continue
        ticker = (e.get('event_ticker') or '').upper()
        title = (e.get('title') or '').upper()
        if keyword_set and not any(kw in ticker or kw in title for kw in keyword_set):
            continue
        target_events.append({
            'event_ticker': e.get('event_ticker', ''),
            'category': 'Sports',
            'title': e.get('title', ''),
        })

    print(f"   ✅ Found {len(target_events)} matching sports events from {len(all_events)} total")

    event_cat_map = {ev['event_ticker']: 'Sports' for ev in target_events}
    all_raw_markets = []

    with ThreadPoolExecutor(max_workers=15) as executor:
        futures = {
            executor.submit(_fetch_markets_for_event, ev['event_ticker'], headers): ev
            for ev in target_events
        }
        for future in as_completed(futures):
            try:
                markets = future.result()
                for m in markets:
                    m['_category'] = 'Sports'
                all_raw_markets.extend(markets)
            except Exception:  # noqa: BLE001, S110 - preserve best-effort sports fetch
                pass

    print(f"   ✅ Got {len(all_raw_markets)} sports markets from {len(target_events)} events")
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
    except Exception as e:  # noqa: BLE001
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

    except Exception as e:  # noqa: BLE001
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

    except Exception as e:  # noqa: BLE001
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
            # quote_cents() reads Kalshi's *_dollars strings and rescales them to
            # cents; an unpriceable market gets None, never a fabricated 0.
            **quote_cents(m),
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
    except:  # noqa: E722 - preserve connection-probe behavior
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
    'Austin': 'KXHIGHAUS',
    'Denver': 'KXHIGHDEN',
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
    except Exception as e:  # noqa: BLE001
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
    for info in WEATHER_SERIES_ALL.values():
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


def fetch_market(ticker: str, *, get: callable | None = None) -> dict:
    """Fetch the public market snapshot for a ticker (`GET /markets/{ticker}`).

    Primary: GET /markets/{ticker} with retries on 5xx/network errors.
    Fallback: GET /markets?event_ticker=<event>&limit=200 (NOT tickers=).
    Derives event_ticker by stripping the last "-" segment from the market ticker.
    Does NOT hardcode status=open in fallback (hides settled markets).
    Re-wraps fallback response: finds matching ticker in markets list and returns {"market": markets[i]}.

    Retries only on 5xx/network errors; 4xx are NOT retried.
    Honors Retry-After header if present.
    Circuit breaker: 3-strike module-level state stops retries/fallback after 3 consecutive failures
    within the current journal run (call _reset_circuit_breaker() at start of each run).

    Args:
        ticker: The market ticker to fetch.
        get: Optional callable for dependency injection (testing). Signature:
             get(url, headers=None, timeout=30, params=None) -> response-like object.
             If not provided, uses `requests.get`.

    Returns:
        Dict with shape {"market": {...}} compatible with tradehub.settlement.parse_market_result.
    """
    if get is None:
        get = requests.get

    # Check circuit breaker first
    if _circuit_open():
        raise RuntimeError(f"Kalshi fetch circuit breaker open (3 consecutive failures); aborting fetch for {ticker}")

    headers = _headers()
    max_retries = 3
    base_delay = 1.0  # seconds

    # Derive event_ticker by stripping last "-" segment (e.g., KXHIGHNY-26OCT20-T70 -> KXHIGHNY-26OCT20)
    event_ticker = ticker.rsplit("-", 1)[0]

    # Try single-market endpoint with retries on 5xx/network errors only
    single_url = f"{KALSHI_API_URL}/{ticker}"
    for attempt in range(max_retries):
        try:
            resp = get(f"{KALSHI_API_URL}/{ticker}", headers=headers, timeout=30)
            if resp.status_code == 200:
                _record_fetch_success()
                return resp.json()
            elif 500 <= resp.status_code < 600:
                # 5xx: retry with backoff, honor Retry-After
                if attempt < max_retries - 1:
                    retry_after = resp.headers.get("Retry-After")
                    delay = int(retry_after) if retry_after and retry_after.isdigit() else base_delay * (2 ** attempt)
                    time.sleep(delay)
                    continue
                # Last 5xx attempt - break to fallback
                break
            else:
                # 4xx: do NOT retry - fail immediately
                _record_fetch_failure()
                resp.raise_for_status()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            # Only network errors retry
            if attempt < max_retries - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise
        except requests.exceptions.RequestException:
            # Other request exceptions (including HTTPError from raise_for_status) - don't retry
            _record_fetch_failure()
            raise

    # Fallback: event_ticker list endpoint (NOT tickers=)
    try:
        resp = get(
            KALSHI_API_URL,
            params={"event_ticker": event_ticker, "limit": 200},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 200:
            data = resp.json()
            markets = data.get("markets", [])
            for m in markets:
                if m.get("ticker") == ticker:
                    _record_fetch_success()
                    return {"market": m}
            raise RuntimeError(f"Ticker {ticker} not found in event_ticker {event_ticker} markets")
        elif 500 <= resp.status_code < 600:
            _record_fetch_failure()
            raise RuntimeError(f"Fallback event_ticker fetch failed with {resp.status_code}")
        else:
            _record_fetch_failure()
            resp.raise_for_status()
    except requests.exceptions.RequestException:
        _record_fetch_failure()
        raise

    # If we reach here, all attempts failed
    _record_fetch_failure()
    raise RuntimeError(f"Kalshi market fetch failed for {ticker} after retries and fallback")

