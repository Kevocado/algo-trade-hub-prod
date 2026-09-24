import requests
import json
from pathlib import Path
from dotenv import load_dotenv
import os

# Load .env
load_dotenv()
API_KEY = os.getenv("KALSHI_API_KEY")
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

def _headers():
    h = {}
    if API_KEY:
        h["Authorization"] = f"Bearer {API_KEY}"
    return h

def discover_series():
    """Discover active series by scanning events."""
    headers = _headers()
    url = f"{KALSHI_BASE_URL}/events"
    params = {"limit": 200, "status": "open"}
    
    try:
        r = requests.get(url, params=params, headers=headers)
        if r.status_code != 200:
            print(f"Error: {r.status_code} - {r.text}")
            return
        
        data = r.json()
        events = data.get('events', [])
        
        # Get all categories
        categories = sorted(set(e.get('category', 'Other') for e in events))
        print("Available Categories:")
        for cat in categories:
            print(f" - {cat}")
        
        # Look for TSA or Energy related events
        interesting_events = []
        for e in events:
            title = e.get('title', '').lower()
            category = e.get('category', '').lower()
            ticker = e.get('event_ticker', '')
            
            if any(k in title or k in category for k in ['tsa', 'travel', 'gas', 'oil', 'energy', 'inventory', 'passenger', 'throughput', 'storage', 'eia', 'fred']):
                interesting_events.append({
                    'title': e.get('title'),
                    'ticker': ticker,
                    'category': e.get('category')
                })
        
        print(f"\nFound {len(interesting_events)} interesting events:")
        print(json.dumps(interesting_events, indent=2))
        
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    discover_series()
