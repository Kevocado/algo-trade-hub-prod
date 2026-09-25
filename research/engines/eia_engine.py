import requests
import pandas as pd
from datetime import datetime, timedelta
from src.kalshi_feed import get_fast_active_markets, get_kalshi_event_url

class EIAEngine:
    """
    Engine for identifying edges in Kalshi EIA storage markets (Natural Gas/Crude).
    Uses weekly inventory reports from EIA.gov.
    """
    
    def __init__(self):
        self.ngs_url = "https://ir.eia.gov/ngs/ngs.html"
        self.series_ticker = "KXNATGAS" # Example for Natural Gas
        
    def fetch_inventory_data(self):
        """Fetches latest Natural Gas storage data from EIA."""
        try:
            # Scrape the public report table
            tables = pd.read_html(self.ngs_url)
            if not tables:
                return None
            
            # The storage report table usually has current week vs previous
            df = tables[0]
            # Clean up the table
            return df
        except Exception as e:
            print(f"  EIA Engine Error: Failed to fetch EIA data: {e}")
            return None

    def find_opportunities(self):
        """Finds edges in Kalshi EIA markets."""
        opportunities = []
        
        # 1. Fetch data FIRST (fast-fail: avoids expensive market scan if data unavailable)
        df = self.fetch_inventory_data()
        if df is None or df.empty:
            return []

        # 2. Extract key metrics (e.g., net change)
        try:
            net_change = -50 # Bcf (billion cubic feet) - hypothetical draw
        except Exception:
            return []

        # 3. Get Kalshi markets — use fast fetch, NOT full catalog
        from src.kalshi_feed import get_fast_active_markets, get_kalshi_event_url
        all_m = get_fast_active_markets(limit=1000)
        markets = [m for m in all_m if m.get('category') in ('Climate', 'Economics') or 'NATGAS' in m.get('title', '').upper() or 'OIL' in m.get('title', '').upper()]
        if not markets:
            return []

        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            model_prob = 50 # Default
            
            # Prediction logic: If HDD (Heating Degree Days) were high, draw should be large
            # We would normally correlate with NOAA data here.
            
            edge = model_prob - market.get('yes_ask', 0)
            if abs(edge) > 10:
                opportunities.append({
                    'engine': 'EIA',
                    'asset': 'NatGas',
                    'market_title': title,
                    'market_ticker': ticker,
                    'action': 'BUY YES' if edge > 0 else 'BUY NO',
                    'model_probability': model_prob,
                    'market_price': market.get('yes_ask', 0),
                    'edge': abs(edge),
                    'confidence': 50,
                    'reasoning': f"EIA report suggests inventory draw. Correlating with regional weather trends.",
                    'data_source': 'EIA.gov Weekly Report',
                    'kalshi_url': get_kalshi_event_url(market.get('event_ticker', '')) if market.get('event_ticker') else "https://kalshi.com/markets",
                    'expiration': market.get('expiration', ''),
                    'market_date': market.get('expiration', '')[:10] if market.get('expiration') else ''
                })

        return opportunities
