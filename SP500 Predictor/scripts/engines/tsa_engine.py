import requests
import pandas as pd
from datetime import datetime, timedelta
import os
import json
from src.kalshi_feed import get_fast_active_markets, get_kalshi_event_url

class TSAEngine:
    """
    Engine for identifying edges in Kalshi TSA throughput markets.
    Uses daily throughput data from TSA.gov.
    """
    
    def __init__(self):
        self.tsa_url = "https://www.tsa.gov/travel/passenger-volumes"
        self.kalshi_category = "Transportation" # Kalshi categorizes TSA/Travel here
        
    def fetch_tsa_data(self):
        """Scrapes daily TSA throughput data."""
        try:
            # TSA.gov table can be read via pandas read_html
            tables = pd.read_html(self.tsa_url)
            if not tables:
                return None
            
            df = tables[0]
            # Expected columns: Date, [Year] Throughput, [Previous Year] Throughput
            # We want to normalize this.
            return df
        except Exception as e:
            print(f"  TSA Engine Error: Failed to fetch TSA data: {e}")
            return None

    def find_opportunities(self):
        """Finds edges in Kalshi TSA markets."""
        opportunities = []
        
        # 1. Fetch TSA historical data FIRST (fast-fail: avoids expensive market scan)
        tsa_df = self.fetch_tsa_data()
        if tsa_df is None or tsa_df.empty:
            return []

        # 2. Extract recent throughput
        try:
            recent_count = str(tsa_df.iloc[0, 1]).replace(',', '')
            recent_val = int(recent_count)
            ma_7d = tsa_df.iloc[:7, 1].replace(',', '', regex=True).astype(int).mean()
        except Exception:
            return []

        # 3. Get Kalshi markets ONLY after data is confirmed available
        from src.kalshi_feed import get_fast_active_markets
        all_m = get_fast_active_markets()
        markets = [m for m in all_m if m.get('category') == 'World' or 'TSA' in m.get('title', '').upper()]
        if not markets:
            return []

        for market in markets:
            ticker = market.get('ticker', '')
            title = market.get('title', '')
            subtitle = market.get('subtitle', '')
            event_ticker = market.get('event_ticker', '')
            yes_ask = market.get('yes_ask', 0)
            
            # Parse strike price from title (e.g., "Will TSA throughput be above 2,500,000?")
            # This is a simplified example; real parsing would be more robust.
            floor = None
            if "above" in title.lower():
                import re
                match = re.search(r'([\d,]+)', title)
                if match:
                    floor = int(match.group(1).replace(',', ''))

            if floor is not None:
                # Basic seasonal model: If yesterday > floor + margin, prob is high
                model_prob = 0
                if recent_val > floor * 1.05:
                    model_prob = 85
                elif recent_val > floor:
                    model_prob = 60
                elif recent_val > floor * 0.95:
                    model_prob = 30
                else:
                    model_prob = 10
                
                edge = model_prob - yes_ask
                
                if abs(edge) > 10:
                    action = 'BUY YES' if edge > 0 else 'BUY NO'
                    opportunities.append({
                        'engine': 'TSA',
                        'asset': 'Travel',
                        'market_title': f"{title} ({subtitle})",
                        'market_ticker': ticker,
                        'event_ticker': event_ticker,
                        'action': action,
                        'model_probability': model_prob,
                        'market_price': yes_ask,
                        'edge': abs(edge),
                        'confidence': model_prob,
                        'reasoning': f"Recent TSA throughput: {recent_val:,}. 7-day Avg: {ma_7d:,.0f}. Strike: {floor:,}. Model suggests {model_prob}% prob.",
                        'data_source': 'TSA.gov Passenger Volumes',
                        'kalshi_url': get_kalshi_event_url(event_ticker) if event_ticker else "https://kalshi.com/markets/transportation",
                        'expiration': market.get('expiration', ''),
                        'market_date': market.get('expiration', '')[:10] if market.get('expiration') else ''
                    })

        return opportunities
