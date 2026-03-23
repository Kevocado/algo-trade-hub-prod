import sys
import os
import pandas as pd

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'src'))

from data_loader import fetch_data
from feature_engineering import prepare_training_data
from model import train_model

def train_all():
    # List of tickers to train
    tickers = ["SPX", "Nasdaq", "BTC", "ETH"]
    
    for ticker in tickers:
        print(f"\n=== Training model for {ticker} ===")
        try:
            # Fetch data (using 7 days which is max for 1m data on Yahoo)
            df = fetch_data(ticker=ticker, period="7d", interval="1m")
            # Yahoo 1m is limited to 7d. 7d of 1m data is ~2700 rows.
            # 60d of 5m data is ~4600 rows.
            # Let's stick to what the app uses: 1m data.
            # But wait, for "production" model we might want more data?
            # The app uses 1m data. If we train on 5m, we must infer on 5m?
            # The feature engineering is time-agnostic mostly (rolling windows), but "next hour" shift depends on rows.
            # In feature_engineering.py: df['target_next_hour'] = df['Close'].shift(-60)
            # This HARDCODES 60 rows = 1 hour. This assumes 1m interval.
            # So we MUST use 1m data.
            
            df = fetch_data(ticker=ticker, period="7d", interval="1m")
            
            if df.empty:
                print(f"Skipping {ticker}: No data found.")
                continue
                
            df_processed = prepare_training_data(df)
            train_model(df_processed, ticker=ticker)
            print(f"Successfully trained {ticker}.")
            
        except Exception as e:
            print(f"Error training {ticker}: {e}")

if __name__ == "__main__":
    train_all()
