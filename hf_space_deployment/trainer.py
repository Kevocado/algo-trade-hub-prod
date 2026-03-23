import os
import json
import time
from datetime import datetime
import pandas as pd
import yfinance as yf
import lightgbm as lgb
import joblib
from huggingface_hub import HfApi

# Configuration
SYMBOL = "BTC-USD"
WINDOW_SIZE = 720  # 30 days of hourly data for training
DATA_DAYS = 730    # Maximum data fetch

def create_features(df):
    """Generates features for Walk-Forward model. Target: Next-Hour Return Direction."""
    df = df.copy()
    
    # Returns
    df['log_ret'] = pd.Series(df['Close']).pct_change()
    for lag in [1, 2, 3, 5, 12, 24, 48]:
        df[f'lag_ret_{lag}'] = df['log_ret'].shift(lag)
        
    df['price_velocity'] = df['Close'].diff(1)
    df['price_acceleration'] = df['price_velocity'].diff(1)
    df['volatility_30'] = df['log_ret'].rolling(30).std()
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    
    # Target (Directional Return, Not Price)
    df['Target_Close'] = df['Close'].shift(-1)
    df['Target_Return'] = (df['Target_Close'] - df['Close']) / df['Close']
    df['Target_Direction'] = (df['Target_Close'] > df['Close']).astype(int)
    
    df = df.dropna()
    return df

def walk_forward_train():
    """Runs the rolling window trainer across the historical data."""
    status = {
        "last_update": datetime.now().isoformat(),
        "status": "Fetching data...",
        "brier_score": None,
        "accuracy": None,
        "latest_prob": None,
        "current_price": None,
    }
    with open("training_status.json", "w") as f: json.dump(status, f)

    print(f"📡 Fetching {DATA_DAYS} days of {SYMBOL} hourly data from yfinance...")
    df = yf.download(tickers=SYMBOL, period=f"{DATA_DAYS}d", interval="1h")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.droplevel(1)
    df = df.dropna()
    
    status["status"] = "Generating features..."
    with open("training_status.json", "w") as f: json.dump(status, f)
    
    df_feat = create_features(df)
    
    feature_cols = [c for c in df_feat.columns if "lag_" in c or "volatility" in c or c in ["log_ret", "price_velocity", "price_acceleration", "hour", "dayofweek"]]
    
    print(f"📊 Starting Walk-Forward Validation (Rolling Window = {WINDOW_SIZE})")
    status["status"] = f"Training (Rolling {WINDOW_SIZE}h Window)..."
    with open("training_status.json", "w") as f: json.dump(status, f)
    
    total_steps = len(df_feat) - WINDOW_SIZE
    if total_steps <= 0:
        print("Not enough data for rolling window.")
        return
        
    predictions = []
    actuals = []
    
    # Fast iteration through history (can take a minute to train 1000s of trees)
    # We will sample to avoid timing out if it's running live
    # Wait! If we actually train 16000 models here it will take hours.
    # So we'll run Walk-Forward on the last 500 steps for validation, 
    # but the final model is trained on the absolute latest 720h window.
    
    BACKTEST_STEPS = 300 # Test over the last 300 hours
    start_idx = len(df_feat) - BACKTEST_STEPS - WINDOW_SIZE
    if start_idx < 0: start_idx = 0
    
    for i in range(start_idx, len(df_feat) - WINDOW_SIZE):
        train_window = df_feat.iloc[i : i + WINDOW_SIZE]
        test_step = df_feat.iloc[i + WINDOW_SIZE : i + WINDOW_SIZE + 1]
        
        X_train = train_window[feature_cols]
        y_train = train_window['Target_Direction']
        
        # FRESH classifier every step!
        model = lgb.LGBMClassifier(n_estimators=100, learning_rate=0.05, random_state=42, n_jobs=-1, force_col_wise=True)
        model.fit(X_train, y_train)
        
        X_test = test_step[feature_cols]
        y_test = test_step['Target_Direction'].iloc[0]
        
        prob = model.predict_proba(X_test)[0][1]
        predictions.append(prob)
        actuals.append(y_test)
        
        if i % 100 == 0:
            print(f"  Step {i} / {len(df_feat) - WINDOW_SIZE}")

    # Calculate metrics
    import numpy as np
    brier = np.mean((np.array(predictions) - np.array(actuals))**2)
    acc = np.mean((np.array(predictions) > 0.5) == np.array(actuals))
    
    print(f"🏆 Walk-Forward Metrics: Brier={brier:.4f}, Accuracy={acc*100:.1f}%")
    
    # ── Finally, Train on the Absolute Edge (Current timeframe) ──
    latest_train = df_feat.iloc[-WINDOW_SIZE:]
    X_latest = latest_train[feature_cols]
    y_latest = latest_train['Target_Direction']
    
    final_model = lgb.LGBMClassifier(n_estimators=150, learning_rate=0.05, random_state=42, n_jobs=-1, force_col_wise=True)
    final_model.fit(X_latest, y_latest)
    
    # The 'next' prediction (live edge)
    # Feature for the last row (we don't know the target yet!)
    live_row = df.iloc[-1:]
    live_feat = create_features(pd.concat([df.iloc[-50:], live_row])) # Need context to create lags
    X_live = live_feat.iloc[-1:][feature_cols]
    
    latest_prob = final_model.predict_proba(X_live)[0][1]
    curr_price = df['Close'].iloc[-1]
    print(f"🔮 LIVE BTC PREDICTION: {latest_prob*100:.1f}% probability of upward drift. Price={curr_price}")
    
    # Save model and feature list
    joblib.dump({"model": final_model, "features": feature_cols}, "btc_hourly_model.pkl")
    
    # Update Status
    status = {
        "last_update": datetime.now().isoformat(),
        "status": "Ready",
        "brier_score": round(float(brier), 4),
        "accuracy": round(float(acc) * 100, 1),
        "latest_prob": round(float(latest_prob) * 100, 1),
        "current_price": float(curr_price),
    }
    with open("training_status.json", "w") as f: json.dump(status, f)
    
    # Push to HF Hub if token exists
    hf_token = os.getenv("HF_TOKEN")
    if hf_token:
        print("☁️ Pushing model to Hugging Face Hub...")
        try:
            api = HfApi()
            # Replace Kevocado/algo-trade-hub with the actual private repo map
            api.upload_file(
                path_or_fileobj="btc_hourly_model.pkl",
                path_in_repo="models/btc_hourly_model.pkl",
                repo_id="Kevocado/algo-trade-hub", # Adjust based on actual HF repo
                repo_type="space",
                token=hf_token
            )
            print("✅ HF Push Complete.")
        except Exception as e:
            print(f"⚠️ HF Push Failed: {e}")

if __name__ == "__main__":
    walk_forward_train()
