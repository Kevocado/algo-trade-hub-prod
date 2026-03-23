import requests
import json
import os
from dotenv import load_dotenv
from pathlib import Path

# Load .env
root_dir = Path(__file__).parent.parent
load_dotenv(dotenv_path=root_dir / '.env', override=True)

class PredictItEngine:
    """
    PhD Milestone 2: Cross-Venue Arbitrage (PredictIt)
    Fetches PredictIt market data to find price discrepancies vs Kalshi.
    """

    def __init__(self):
        self.base_url = "https://www.predictit.org/api/marketdata"

    def fetch_all_markets(self):
        """Fetches all active markets from PredictIt."""
        url = f"{self.base_url}/all/"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json().get('markets', [])
            return []
        except Exception as e:
            print(f"PredictIt API Error: {e}")
            return []

    def fetch_market(self, market_id):
        """Fetches a specific market by ID."""
        url = f"{self.base_url}/markets/{market_id}"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json()
            return None
        except Exception:
            return None

    def find_matching_market(self, kalshi_ticker):
        """
        PhD Logic: Maps Kalshi tickers to PredictIt Market IDs using keywords.
        """
        base = kalshi_ticker.split('-')[0].upper()
        
        # Keyword-based heuristics
        search_terms = {
            "KXPRES": ["Presidential Election", "White House"],
            "KXSENATE": ["Senate Control", "Senate"],
            "KXHOUSE": ["House Control", "House"],
            "KXRECESSION": ["Recession"],
            "KXCPY": ["Inflation", "CPI"],
            "KXFED": ["Interest Rate", "Fed"],
        }
        
        terms = search_terms.get(base)
        if not terms:
            return None
            
        markets = self.fetch_all_markets()
        for m in markets:
            m_name = m.get('name', '').lower()
            for t in terms:
                if t.lower() in m_name:
                    return m.get('id')
        return None

    def get_arbitrage_alerts(self, live_opps):
        """
        PhD Milestone 2: Scans all live opportunities for PredictIt arbitrage.
        Returns a list of opportunities with 'pi_delta' and 'pi_price'.
        """
        pi_markets = self.fetch_all_markets()
        if not pi_markets:
            return []
            
        alerts = []
        for opp in live_opps:
            ticker = opp.get('MarketTicker')
            if not ticker: continue
            
            # 1. Map Ticker
            pi_id = self.find_matching_market(ticker)
            if not pi_id: continue
            
            # 2. Fetch Pi Data
            pi_data = self.fetch_market(pi_id)
            if not pi_data: continue
            
            # 3. Find matching contract (Fuzzy)
            # Kalshi: "Will Republicans win the House?"
            # PI: "House Control" -> Contract "Republicans"
            # This requires more complex parsing per-category.
            # For now, we look for the contract with the closest price to Kalshi
            # as a proxy for the 'same' event.
            k_price = float(opp.get('MarketPrice', 0)) # cents
            
            best_match = None
            min_diff = 100
            
            for contract in pi_data.get('contracts', []):
                pi_price = float(contract.get('bestBuyYesCost', 0)) * 100 # convert to cents
                diff = abs(pi_price - k_price)
                if diff < min_diff:
                    min_diff = diff
                    best_match = contract
            
            if best_match and min_diff < 15: # Within 15 cents, likely the same event
                pi_price = float(best_match.get('bestBuyYesCost', 0)) * 100
                delta = pi_price - k_price
                
                if abs(delta) >= 3: # Significant discrepancy (>3%)
                    alerts.append({
                        "MarketTicker": ticker,
                        "PredictIt_Market": pi_data.get('name'),
                        "PredictIt_Contract": best_match.get('name'),
                        "Kalshi_Price": k_price,
                        "PI_Price": pi_price,
                        "Delta": round(delta, 1),
                        "Type": "Arbitrage" if abs(delta) > 8 else "Alignment"
                    })
        return alerts

if __name__ == "__main__":
    # Test
    engine = PredictItEngine()
    print("Fetching PredictIt Arbitrage Alerts...")
    # Mock some opportunities
    mock_opps = [{"MarketTicker": "KXHOUSE-2026", "MarketPrice": 50}]
    alerts = engine.get_arbitrage_alerts(mock_opps)
    print(json.dumps(alerts, indent=2))
