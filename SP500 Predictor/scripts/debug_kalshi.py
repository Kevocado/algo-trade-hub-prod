import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from src.kalshi_feed import get_real_kalshi_markets, check_kalshi_connection
import json

print("--- Checking Connection ---")
is_connected = check_kalshi_connection()
print(f"Connection Status: {is_connected}")

print("\n--- Fetching SPX Markets ---")
markets, method, debug_info = get_real_kalshi_markets("SPX")

print(f"\nMethod: {method}")
print(f"Market Count: {len(markets)}")
print("\nDebug Info:")
print(json.dumps(debug_info, indent=2, default=str))

if markets:
    print("\nSample Market:")
    print(markets[0])
else:
    print("\nNo OPEN markets found. Checking CLOSED markets to verify ticker...")
    import requests
    url = "https://api.elections.kalshi.com/trade-api/v2/markets"
    
    # Check KXINX specifically without status filter
    print("\n--- Checking KXINX (Any Status) ---")
    resp = requests.get(url, params={"series_ticker": "KXINX", "limit": 5})
    if resp.status_code == 200:
        found = resp.json().get('markets', [])
        print(f"Found {len(found)} markets for KXINX (any status).")
        if found:
            print(f"Sample: {found[0]['ticker']} | Status: {found[0]['status']}")
    else:
        print(f"Error checking KXINX: {resp.status_code}")
    print("\n--- Checking SPX (KXINX) ---")
    markets, method, debug_info = get_real_kalshi_markets("SPX")
    print(f"SPX Markets: {len(markets)} | Method: {method}")
    if markets:
        print(f"Sample: {markets[0]['market_id']} | Exp: {markets[0]['expiration']}")
    else:
        print("Debug Info:")
        print(debug_info)

    print("\n--- Checking BTC (KXBTC) ---")
    markets_btc, _, _ = get_real_kalshi_markets("BTC")
    print(f"BTC Markets Found: {len(markets_btc)}")
    if markets_btc:
        print(f"Sample: {markets_btc[0]['market_id']} | Exp: {markets_btc[0]['expiration']}")
