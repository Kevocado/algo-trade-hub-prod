import lightgbm as lgb
import pandas as pd
import numpy as np
import joblib
import os
import scipy.stats as stats
import requests
from scipy.stats import norm
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_squared_error, mean_absolute_error
from datetime import datetime, timezone, timedelta

MODEL_DIR = "model"

# Custom exception for feature mismatches
class FeatureMismatchError(Exception):
    """Raised when model expects different features than provided data."""
    def __init__(self, expected_features, actual_features, expected_count, actual_count):
        self.expected_features = expected_features
        self.actual_features = actual_features
        self.expected_count = expected_count
        self.actual_count = actual_count
        super().__init__(
            f"Feature mismatch: Model expects {expected_count} features but data has {actual_count} features. "
            f"This usually means new features were added. Auto-retraining required."
        )

def get_hf_path(filename):
    """Downloads file from HF Hub and returns local path, or fallback."""
    repo_id = "Kevocado/algo-trade-hub"
    local_path = os.path.join(MODEL_DIR, os.path.basename(filename))
    
    # Temporarily ignore local check to force HF pull for latest .pkl
    # because trainer.py runs hourly on HF space.
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download(repo_id=repo_id, filename=filename, repo_type="space", token=os.getenv("HF_TOKEN"))
    except Exception as e:
        print(f"HF Hub Pull Failed for {filename}: {e}")
        if os.path.exists(local_path):
            return local_path
    return None

def fetch_live_btc_alpaca():
    """Fetches the last 5 days of hourly BTC-USD data from Alpaca Data API"""
    import os
    API_KEY = os.getenv("ALPACA_API_KEY")
    SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
    
    url = "https://data.alpaca.markets/v1beta3/crypto/us/bars"
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=5)
    
    headers = {
        "accept": "application/json",
        "APCA-API-KEY-ID": API_KEY,
        "APCA-API-SECRET-KEY": SECRET_KEY
    }
    
    params = {
        "symbols": "BTC/USD",
        "timeframe": "1Hour",
        "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    
    res = requests.get(url, headers=headers, params=params)
    if res.status_code == 200:
        data = res.json()
        bars = data.get("bars", {}).get("BTC/USD", [])
        if not bars:
            return pd.DataFrame()
            
        df = pd.DataFrame(bars)
        df['timestamp'] = pd.to_datetime(df['t'])
        df.set_index('timestamp', inplace=True)
        df.rename(columns={'o': 'Open', 'h': 'High', 'l': 'Low', 'c': 'Close', 'v': 'Volume'}, inplace=True)
        return df
    else:
        print(f"Alpaca API Error: {res.text}")
        return pd.DataFrame()

def create_walk_forward_features(df):
    """Exact match of the Walk-Forward trainer's feature set."""
    df = df.copy()
    df['log_ret'] = pd.Series(df['Close']).pct_change()
    for lag in [1, 2, 3, 5, 12, 24, 48]:
        df[f'lag_ret_{lag}'] = df['log_ret'].shift(lag)
        
    df['price_velocity'] = df['Close'].diff(1)
    df['price_acceleration'] = df['price_velocity'].diff(1)
    df['volatility_30'] = df['log_ret'].rolling(30).std()
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    
    return df.dropna()

def validate_model_features(model, ticker):
    # Deprecated for Walk-Forward model.
    return True, 0, 0, []

def get_model_path(ticker, download=False):
    if ticker == "BTC-USD":
        local_path = os.path.join(MODEL_DIR, "btc_hourly_model.pkl")
        if download:
            path = get_hf_path("models/btc_hourly_model.pkl")
            if path: return path
        return local_path
    
    local_path = os.path.join(MODEL_DIR, f"lgbm_direction_{ticker}.pkl")
    if download:
        path = get_hf_path(f"models/lgbm_direction_{ticker}.pkl")
        if path: return path
    return local_path

def train_model(df, ticker="SPY"):
    pass # Deprecated by HF Space Trainer

def load_model(ticker="SPY"):
    """Loads the trained model for the given ticker."""
    model_path = get_model_path(ticker, download=True)
    if not model_path or not os.path.exists(model_path):
        print(f"Model file {model_path} not found.")
        return None, True
    
    try:
        data = joblib.load(model_path)
        # Walk-forward models save a dict: {"model": model, "features": [...] }
        if isinstance(data, dict) and "model" in data and "features" in data:
            return data, False
        else:
            # Legacy model format
            return data, False
    except Exception as e:
        print(f"❌ Error loading model for {ticker}: {e}")
        return None, True

def predict_next_hour(model_data, current_data_df, ticker="SPY"):
    """
    Predicts the next hour direction probability given the latest data.
    """
    if isinstance(model_data, dict):
        model = model_data["model"]
        feature_cols = model_data["features"]
    else:
        # Legacy fallback
        model = model_data
        feature_names_path = get_hf_path(f"models/features_{ticker}.pkl")
        if feature_names_path and os.path.exists(feature_names_path):
            feature_cols = joblib.load(feature_names_path)
        else:
            raise FileNotFoundError(f"Feature list not found for {ticker}")

    last_row = current_data_df.iloc[[-1]]
    available_features = set(last_row.columns)
    expected_features = set(feature_cols)
    
    if len(available_features & expected_features) != len(expected_features):
        missing = expected_features - available_features
        extra = available_features - expected_features
        if missing or extra:
            print(f"⚠️ Feature alignment issue for {ticker}:")
            print(f"    [FAILSAFE] Auto-dropping {len(extra)} extra features and zero-filling {len(missing)} missing features.")
    
    last_row_aligned = last_row.reindex(columns=feature_cols, fill_value=0)
    prediction = model.predict_proba(last_row_aligned.values)[0][1]
    return prediction

def get_market_volatility(df, window=24):
    """
    Calculates hourly volatility from rolling log returns.
    """
    df = df.copy()
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
    hourly_vol = df['log_ret'].rolling(window=window).std().iloc[-1]
    
    return hourly_vol if not np.isnan(hourly_vol) else 0.01  # Fallback

def calculate_probability(current_price, predicted_price, strike, hourly_vol, hours_left):
    """
    Returns probability (0-100%) that Price > Strike at expiration.
    Uses Black-Scholes-inspired Z-Score logic.
    """
    if hours_left <= 0:
        return 0.1 if current_price < strike else 99.9
    if hourly_vol <= 0:
        return 50.0

    # 1. Expected Drift (from ML Model)
    drift = (predicted_price - current_price) / current_price

    # 2. Volatility over time horizon
    sigma_t = hourly_vol * np.sqrt(hours_left)

    # 3. Distance to Strike (Log Moneyness)
    if current_price <= 0 or strike <= 0:
        return 50.0
    log_distance = np.log(current_price / strike)

    # 4. Z-Score
    z_score = (log_distance + drift) / sigma_t

    # 5. Prob of being ABOVE Strike
    prob_above = norm.cdf(z_score) * 100

    # Clamp to avoid 0/100
    return max(0.1, min(99.9, prob_above))

def kelly_criterion(my_prob, market_prob, bankroll=20, fractional=0.25):
    """
    Calculates bet size ($) using Fractional Kelly Criterion.
    """
    p = my_prob / 100
    q = 1 - p
    price = market_prob / 100

    if price >= 1.0 or price <= 0:
        return 0

    b = (1 - price) / price  # Odds offered by the market

    if b <= 0:
        return 0

    f = p - (q / b)

    # Only bet if we have an edge
    if f <= 0:
        return 0

    # Fractional Kelly (Safety)
    safe_f = f * fractional
    bet_size = bankroll * safe_f

    return round(min(bet_size, bankroll), 2)

def get_orderbook(market_ticker):
    """
    Fetches live order book from Kalshi for a specific market.
    """
    try:
        API_KEY = os.getenv("KALSHI_API_KEY")
        headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
        
        r = requests.get(
            f"https://api.elections.kalshi.com/trade-api/v2/markets/{market_ticker}/orderbook",
            headers=headers, timeout=5
        )
        if r.status_code != 200:
            return None
            
        data = r.json().get('orderbook', {})
        yes_bids = data.get('yes', []) or []
        no_bids = data.get('no', []) or []
        
        # Calculate depth
        total_yes = sum(qty for _, qty in yes_bids)
        total_no = sum(qty for _, qty in no_bids)
        
        # Calculate spread
        best_yes = yes_bids[-1][0] if yes_bids else 0  # Highest yes bid
        best_no = no_bids[-1][0] if no_bids else 0    # Highest no bid
        spread = max(0, 100 - best_yes - best_no)
        
        return {
            'yes_bids': yes_bids,
            'no_bids': no_bids,
            'total_yes_depth': total_yes,
            'total_no_depth': total_no,
            'spread': spread,
            'best_yes': best_yes,
            'best_no': best_no
        }
    except Exception:
        return None

def generate_trading_signals(ticker, predicted_price, current_price, rmse):
    """
    Generates trading signals for both Direction (Strikes) and Volatility (Ranges).
    """
    signals = {
        'status': 'PAPER TRADE ONLY',
        'strikes': [],
        'ranges': []
    }
    
    # --- 1. Strike Signals (Direction) ---
    if current_price > 10000: # BTC-like
        step = 100
        buffer = 50
    elif current_price > 1000: # ETH/SPX-like
        step = 10
        buffer = 5
    else:
        step = 1
        buffer = 0.5
        
    base_price = round(current_price / step) * step
    strikes_to_check = [base_price + (k * step) for k in range(-5, 6)]
    
    for strike in strikes_to_check:
        z_score = (predicted_price - strike) / rmse
        prob = stats.norm.cdf(z_score) * 100
        
        action = "PASS"
        if predicted_price > strike + buffer:
            action = "🟢 BUY YES"
        elif predicted_price < strike - buffer:
            action = "🔴 BUY NO"
            
        if action != "PASS":
            signals['strikes'].append({
                "Strike": f"> ${strike}",
                "Prob": f"{prob:.1f}%",
                "Action": action,
                "Raw_Strike": strike
            })

    # --- 2. Range Signals (Volatility) ---
    if ticker in ["BTC", "BTC-USD"]:
        range_step = 1000
    elif ticker in ["ETH", "ETH-USD"]:
        range_step = 100
    elif ticker in ["SPX", "NDX", "Nasdaq"]:
        range_step = 50
    else:
        range_step = 10
        
    pred_base = (predicted_price // range_step) * range_step
    
    ranges_to_check = []
    for k in range(-2, 3):
        start = pred_base + (k * range_step)
        end = start + range_step
        ranges_to_check.append((start, end))
        
    for r_start, r_end in ranges_to_check:
        in_range = r_start <= predicted_price < r_end
        
        action = "PASS"
        if in_range:
            action = "🟢 BUY YES"
            
        signals['ranges'].append({
            "Range": f"${r_start:,.0f} - ${r_end:,.0f}",
            "Predicted In Range?": "✅ YES" if in_range else "❌ NO",
            "Action": action,
            "Is_Winner": in_range
        })
        
    return signals
