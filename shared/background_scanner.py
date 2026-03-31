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
import sys
import os

# Add "SP500 Predictor" to sys.path so we can import its scripts module despite the space in the folder name
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'SP500 Predictor')))
from scripts.engines.football_engine import FootballKalshiEngine

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

# This dictionary represents backtested "Green Islands" (Win Rate > 60%, Trades > 20)
# Format: {day_index: [list_of_profitable_hours]}
# day_index: 0=Monday, 6=Sunday
PROFITABLE_MATRIX = {
    1: [22],             # Tuesday: 22:00 (Asia Open transition)
    4: [16],             # Friday: 16:00 (NY Close / Start of Retail Window)
    5: [16, 20, 22, 23], # Saturday: The absolute sweet spot for your bot
    6: [0, 22]           # Sunday: 00:00 & 22:00 (Weekend transitions)
}

def is_profitable_regime(dt_now):
    """
    Checks if current time is inside a high-conviction backtested window.
    """
    day = dt_now.weekday() 
    hour = dt_now.hour
    
    if day in PROFITABLE_MATRIX:
        return hour in PROFITABLE_MATRIX[day]
    return False

def main_loop():
    log.info("Starting slow scanner (10-minute loop)...")
    while True:
        now = datetime.now(timezone.utc)
        if not is_profitable_regime(now):
            log.info(f"💤 Sleep Mode: {now.strftime('%A %H:00')} is a Danger Zone. Skipping trade scan.")
        else:
            fetch_and_store_fred()
            fetch_and_store_kalshi_macro()
            fetch_and_store_football()
        
        time.sleep(600)  # 10 minutes

if __name__ == "__main__":
    main_loop()
