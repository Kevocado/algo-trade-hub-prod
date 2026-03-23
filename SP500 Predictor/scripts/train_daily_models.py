import sys
import os
import pandas as pd

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.data_loader import fetch_data
from src.model_daily import train_daily_model

def train_all_daily():
    # List of tickers to train
    tickers = ["SPX", "Nasdaq", "BTC", "ETH"]
    
    for ticker in tickers:
        print(f"\n=== Training DAILY model for {ticker} ===")
        try:
            # Fetch 2 years of Hourly data
            # Yahoo Finance allows 730d for 1h interval
            df = fetch_data(ticker=ticker, period="730d", interval="1h")
            
            if df.empty:
                print(f"Skipping {ticker}: No data found.")
                continue
                
            train_daily_model(df, ticker)
            print(f"Successfully trained Daily model for {ticker}.")
            
        except Exception as e:
            print(f"Error training {ticker}: {e}")

if __name__ == "__main__":
    train_all_daily()
