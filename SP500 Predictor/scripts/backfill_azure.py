import sys
import os
import pandas as pd
from datetime import timedelta

# Add src to path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.data_loader import fetch_data
from src.feature_engineering import create_features
from src.model import load_model, predict_next_hour, calculate_probability, get_recent_rmse
from src.azure_logger import log_prediction

def backfill_history(ticker="SPX", days=5):
    print(f"Starting backfill for {ticker} over last {days} days...")
    
    # 1. Fetch Data
    df = fetch_data(ticker=ticker, period=f"{days}d", interval="1m")
    if df.empty:
        print("No data fetched.")
        return

    # 2. Load Model
    model = load_model(ticker=ticker)
    if model is None:
        print(f"No model found for {ticker}. Please train it first.")
        return

    # 3. Iterate through data (simulate hourly predictions)
    # We'll take a sample every 60 minutes
    df_resampled = df.resample('60min').last().dropna()
    
    print(f"Found {len(df_resampled)} hourly points to backfill.")
    
    rmse = get_recent_rmse(model, df, ticker=ticker)
    
    count = 0
    for timestamp, row in df_resampled.iterrows():
        # We need features for this specific point in time.
        # Ideally we'd re-calculate features on a rolling basis, but for a quick backfill,
        # let's just use the features from the full dataset at that index.
        
        # Create features on full df first
        df_features = create_features(df)
        
        if timestamp not in df_features.index:
            continue
            
        # Prepare single row for prediction
        row_features = df_features.loc[[timestamp]]
        
        try:
            prediction = predict_next_hour(model, row_features, ticker=ticker)
            current_price = row['Close']
            
            # Generate Fake Edge Data for the log
            strikes = [current_price + i*10 for i in range(-2, 3)]
            edge_data = []
            for strike in strikes:
                prob_yes = calculate_probability(prediction, strike, rmse)
                # Simulate market price with some noise
                import random
                noise = random.uniform(-10, 10)
                market_price = min(99, max(1, int(prob_yes + noise)))
                edge = prob_yes - market_price
                
                action = "PASS"
                if prob_yes > 60 and edge > 5: action = "🟢 BUY YES"
                elif prob_yes < 40 and edge < -5: action = "🔴 BUY NO"
                
                edge_data.append({
                    "Strike": f"> ${strike}",
                    "Edge": f"{edge:.1f}%",
                    "Action": action
                })
            
            # Log with HISTORICAL timestamp
            log_prediction(prediction, current_price, rmse, edge_data, ticker=ticker, timestamp=timestamp)
            print(f"Logged: {timestamp} | Pred: {prediction:.2f} | Act: {current_price:.2f}")
            count += 1
            
        except Exception as e:
            print(f"Error at {timestamp}: {e}")
            continue

    print(f"Backfill complete! Logged {count} entries to Azure.")

if __name__ == "__main__":
    # Backfill for main assets
    for ticker in ["SPX", "Nasdaq", "BTC", "ETH"]:
        backfill_history(ticker, days=5)
