import os
from pathlib import Path

# Add project root to path

from tradehub.core.kalshi_portfolio import KalshiPortfolio
from tradehub.core.supabase_client import upsert_kalshi_portfolio

def sync():
    print("🔄 Syncing Kalshi Portfolio to Supabase...")
    try:
        portfolio = KalshiPortfolio()
        summary = portfolio.get_portfolio_summary()
        
        if summary.get('error'):
            print(f"❌ Portfolio Error: {summary['error']}")
            return
            
        upsert_kalshi_portfolio(summary)
        print(f"✅ Portfolio Synced: Balance=${summary.get('balance', 0):.2f}, Positions={summary.get('total_positions', 0)}")
    except Exception as e:
        print(f"❌ Sync Failed: {e}")

if __name__ == "__main__":
    sync()
