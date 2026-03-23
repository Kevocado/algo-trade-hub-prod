"""
background_scanner.py — Slow Market & Macro Scanner
===================================================
10-minute loop that:
1. Fetches FRED series (UNRATE, DGS10, CPIAUCSL, etc.) -> macro_signals
2. Scans Kalshi open markets for macro-category events -> kalshi_edges

Procfile: scanner_slow: PYTHONPATH=. python shared/background_scanner.py
"""

import time
import logging
import requests
from datetime import datetime, timezone
from supabase import create_client

from shared import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [SLOW-SCANNER] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supa = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)

FRED_SERIES = ["UNRATE", "DGS10", "CPIAUCSL"]

def fetch_and_store_fred():
    """Fetches key macroeconomic indicators from FRED."""
    if not config.FRED_API_KEY:
        log.warning("No FRED_API_KEY. Skipping FRED fetch.")
        return

    log.info("Fetching FRED macro data...")
    for series in FRED_SERIES:
        try:
            url = f"https://api.stlouisfed.org/fred/series/observations?series_id={series}&api_key={config.FRED_API_KEY}&file_type=json&limit=1&sort_order=desc"
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                observations = data.get("observations", [])
                if observations:
                    obs = observations[0]
                    val = float(obs.get("value", 0))
                    
                    # Store to Supabase
                    supa.table("macro_signals").insert({
                        "source": "FRED",
                        "series_id": series,
                        "value": val,
                        "signal_ts": obs.get("date") + "T00:00:00Z",
                    }).execute()
                    
                    log.info(f"FRED {series}: {val}")
        except Exception as e:
            log.error(f"Failed to fetch FRED {series}: {e}")

def fetch_and_store_kalshi_macro():
    """Scans Kalshi for macro-related open markets to find generic edges."""
    if not config.KALSHI_API_BASE:
        return

    log.info("Scanning Kalshi for MACRO edges...")
    try:
        # Example Kalshi API call to get active economics markets
        url = f"{config.KALSHI_API_BASE}/trade-api/v2/events?series_ticker=ECON"
        resp = requests.get(url, timeout=10)
        if resp.status_code == 200:
            events = resp.json().get("events", [])
            for event in events[:5]:  # limit for demo
                ticker = event.get("ticker", "UNKNOWN")
                title = event.get("title", "Unknown Event")
                
                # We would normally calculate an edge here comparing to our internal model
                # For now, we log the market discovery
                
                supa.table("kalshi_edges").insert({
                    "market_id": ticker,
                    "title": title,
                    "edge_type": "MACRO",
                    "our_prob": 0.50, # Placeholder
                    "market_prob": 0.50, # Placeholder
                    "edge_pct": 0.0,
                    "raw_payload": event,
                }).execute()
                
            log.info(f"Kalshi MACRO scan complete. Found {len(events)} events.")
    except Exception as e:
        log.error(f"Failed to fetch Kalshi MACRO markets: {e}")

def main_loop():
    log.info("Starting slow scanner (10-minute loop)...")
    while True:
        fetch_and_store_fred()
        fetch_and_store_kalshi_macro()
        time.sleep(600)  # 10 minutes

if __name__ == "__main__":
    main_loop()
