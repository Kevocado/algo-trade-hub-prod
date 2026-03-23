import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data_loader import fetch_data
from src.feature_engineering import prepare_training_data
from src.model import train_model
from src.model_daily import train_daily_model, prepare_daily_data

def retrain_all():
    tickers = ["SPX", "Nasdaq", "BTC", "ETH"]
    
    print("🚀 Starting Full Retraining Cycle...")
    
    for ticker in tickers:
        print(f"\n-----------------------------------")
        print(f"🔄 Processing {ticker}...")
        
        # 1. Hourly Model
        try:
            print(f"   [Hourly] Fetching data...")
            df_hourly = fetch_data(ticker=ticker, period="30d", interval="1m") # More data for better training
            if not df_hourly.empty:
                print(f"   [Hourly] Preparing features...")
                df_train = prepare_training_data(df_hourly)
                print(f"   [Hourly] Training model...")
                train_model(df_train, ticker=ticker)
                print(f"   ✅ [Hourly] Model retrained.")
            else:
                print(f"   ❌ [Hourly] No data found.")
        except Exception as e:
            print(f"   ❌ [Hourly] Failed: {e}")
            
        # 2. Daily Model
        try:
            print(f"   [Daily] Fetching data...")
            df_daily = fetch_data(ticker=ticker, period="730d", interval="1h") # 2 years of hourly data for daily model
            if not df_daily.empty:
                print(f"   [Daily] Preparing features...")
                df_train_daily, _ = prepare_daily_data(df_daily)
                print(f"   [Daily] Training model...")
                train_daily_model(df_train_daily, ticker=ticker)
                print(f"   ✅ [Daily] Model retrained.")
            else:
                print(f"   ❌ [Daily] No data found.")
        except Exception as e:
            print(f"   ❌ [Daily] Failed: {e}")

    print("\n✨ All models processed.")

if __name__ == "__main__":
    retrain_all()
