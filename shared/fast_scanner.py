"""
fast_scanner.py — High-Frequency Weather Arbitrage Scanner
==========================================================
60-90 second loop that:
1. Polls NWS API (api.weather.gov) for active macro alerts
2. Queries Kalshi for any weather-related open markets (Chicago rain, NY temps)
3. Computes implied probability and generates WEATHER edges -> kalshi_edges

Procfile: scanner_fast: PYTHONPATH=. python shared/fast_scanner.py
"""

import time
import logging
import requests
from datetime import datetime, timezone
from supabase import create_client

from shared import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [FAST-SCANNER] %(levelname)s %(message)s")
log = logging.getLogger(__name__)

supa = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)

# Key Zones we care about for Kalshi (NYC, Chicago, Miami, etc)
NWS_ZONES = ["NYZ072", "ILZ104", "FLZ074"]

def fetch_nws_alerts():
    """Polls the National Weather Service for active alerts in key zones."""
    log.info("Polling NWS API for active weather alerts...")
    
    headers = {
        "User-Agent": "Algo-Trade-Hub/1.0",
        "Accept": "application/geo+json"
    }
    
    active_alerts = 0
    for zone in NWS_ZONES:
        try:
            url = f"https://api.weather.gov/alerts/active/zone/{zone}"
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                features = resp.json().get("features", [])
                
                for feature in features:
                    props = feature.get("properties", {})
                    event = props.get("event", "Unknown Alert")
                    severity = props.get("severity", "Unknown")
                    
                    # Store NWS signal
                    supa.table("macro_signals").insert({
                        "source": "NWS",
                        "series_id": f"NWS_{zone}_{event.replace(' ', '_').upper()}",
                        "value": 1.0 if severity in ["Severe", "Extreme"] else 0.5,
                        "signal_ts": datetime.now(timezone.utc).isoformat(),
                    }).execute()
                    active_alerts += 1
                    
        except Exception as e:
            log.error(f"Failed NWS fetch for zone {zone}: {e}")
            
    log.info(f"NWS poll complete. {active_alerts} active alerts written to macro_signals.")

def fetch_kalshi_weather():
    """Scans Kalshi for WEATHER events to find latency arbitrage edges."""
    if not config.KALSHI_API_BASE:
        return
        
    try:
        # Example to find weather events (High temps, rain, etc)
        url = f"{config.KALSHI_API_BASE}/trade-api/v2/events?series_ticker=KXWDXD" # Example ticker for Daily High Temps
        resp = requests.get(url, timeout=5)
        
        if resp.status_code == 200:
            events = resp.json().get("events", [])
            for event in events[:3]:
                ticker = event.get("ticker", "UNKNOWN")
                title = event.get("title", "Weather Event")
                
                # Mock edge calculation -- in reality this compares NWS data to market odds
                edge_pct = 0.05 
                
                supa.table("kalshi_edges").insert({
                    "market_id": ticker,
                    "title": title,
                    "edge_type": "WEATHER",
                    "our_prob": 0.60, 
                    "market_prob": 0.55, 
                    "edge_pct": edge_pct,
                    "raw_payload": event,
                }).execute()
                
    except Exception as e:
        log.error(f"Failed to fetch Kalshi WEATHER markets: {e}")

def main_loop():
    log.info("Starting fast scanner (60-second loop)...")
    while True:
        fetch_nws_alerts()
        fetch_kalshi_weather()
        time.sleep(60)

if __name__ == "__main__":
    main_loop()
