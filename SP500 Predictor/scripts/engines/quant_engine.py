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
    repo_id = "KevinSigey/Kalshi-LightGBM"
    local_path = os.path.join(MODEL_DIR, os.path.basename(filename))
    try:
        from huggingface_hub import hf_hub_download
        return hf_hub_download(repo_id=repo_id, filename=filename, token=os.getenv("HF_TOKEN"))
    except Exception as e:
        print(f"HF Hub Pull Failed for {filename}: {e}")
        if os.path.exists(local_path):
            return local_path
    return None

def validate_model_features(model, ticker):
    """
    Validates that the model's expected features match the saved feature list.
    
    Args:
        model: Trained LightGBM model.
        ticker (str): Ticker name.
        
    Returns:
        tuple: (is_valid, expected_count, actual_count, feature_list)
    """
    feature_names_path = get_hf_path(f"models/features_{ticker}.pkl")
    
    if not feature_names_path or not os.path.exists(feature_names_path):
        print(f"⚠️ Feature list not found for {ticker} on HF or locally. Cannot validate.")
        return (False, 0, 0, [])
    
    try:
        saved_features = joblib.load(feature_names_path)
        # LightGBM models have num_feature() method
        model_feature_count = model.num_feature()
        saved_feature_count = len(saved_features)
        
        is_valid = (model_feature_count == saved_feature_count)
        
        if not is_valid:
            print(f"⚠️ Feature count mismatch for {ticker}:")
            print(f"   Model expects: {model_feature_count} features")
            print(f"   Saved list has: {saved_feature_count} features")
        
        return (is_valid, model_feature_count, saved_feature_count, saved_features)
    except Exception as e:
        print(f"❌ Error validating features for {ticker}: {e}")
        return (False, 0, 0, [])

def get_model_path(ticker, download=False):
    if download:
        path = get_hf_path(f"models/lgbm_model_{ticker}.pkl")
        if path: return path
    return os.path.join(MODEL_DIR, f"lgbm_model_{ticker}.pkl")

def train_model(df, ticker="SPY"):
    """
    Trains a LightGBM model to predict next hour close.
    
    Args:
        df (pd.DataFrame): Dataframe with features and target 'target_next_hour'.
        ticker (str): Ticker name to save model for.
    """
    save_path = get_model_path(ticker)
    # Define features and target
    target_col = 'target_next_hour'
    drop_cols = [target_col, 'cum_vol', 'cum_vol_price'] # Drop intermediate calc cols if any
    
    # Filter only numeric columns for features
    feature_cols = [c for c in df.columns if c not in drop_cols and pd.api.types.is_numeric_dtype(df[c])]
    
    X = df[feature_cols]
    y = df[target_col]
    
    print(f"Training on {len(X)} samples with {len(feature_cols)} features.")
    
    # Time Series Split for validation
    tscv = TimeSeriesSplit(n_splits=5)
    
    params = {
        'objective': 'regression',
        'metric': 'rmse',
        'boosting_type': 'gbdt',
        'num_leaves': 31,
        'learning_rate': 0.05,
        'feature_fraction': 0.9
    }
    
    fold = 1
    for train_index, val_index in tscv.split(X):
        X_train, X_val = X.iloc[train_index], X.iloc[val_index]
        y_train, y_val = y.iloc[train_index], y.iloc[val_index]
        
        train_data = lgb.Dataset(X_train, label=y_train)
        val_data = lgb.Dataset(X_val, label=y_val, reference=train_data)
        
        bst = lgb.train(params, train_data, num_boost_round=100, valid_sets=[val_data], 
                        callbacks=[lgb.early_stopping(stopping_rounds=10), lgb.log_evaluation(0)])
        
        preds = bst.predict(X_val, num_iteration=bst.best_iteration)
        rmse = np.sqrt(mean_squared_error(y_val, preds))
        print(f"Fold {fold} RMSE: {rmse:.4f}")
        fold += 1
        
    # Train on all data
    print("Retraining on full dataset...")
    full_train_data = lgb.Dataset(X, label=y)
    final_model = lgb.train(params, full_train_data, num_boost_round=100)
    
    # Save model
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    joblib.dump(final_model, save_path)
    print(f"Model saved to {save_path}")
    
    # Save feature names to ensure consistency during inference
    joblib.dump(feature_cols, os.path.join(os.path.dirname(save_path), f"features_{ticker}.pkl"))
    
    return final_model

def load_model(ticker="SPY"):
    """
    Loads the trained model for the given ticker.
    Also validates that the model's feature count matches the saved feature list.
    
    Returns:
        tuple: (model, needs_retraining) where needs_retraining is True if feature mismatch detected
    """
    model_path = get_model_path(ticker, download=True)
    if not model_path or not os.path.exists(model_path):
        print(f"Model file {model_path} not found.")
        return None, True  # Model missing, needs training
    
    try:
        model = joblib.load(model_path)
        
        # Validate features
        is_valid, expected, actual, _ = validate_model_features(model, ticker)
        
        if not is_valid:
            print(f"⚠️ Model for {ticker} has feature mismatch. Retraining recommended.")
            return model, True  # Return model but flag for retraining
        
        return model, False  # Model is valid
    except Exception as e:
        print(f"❌ Error loading model for {ticker}: {e}")
        return None, True

def predict_next_hour(model, current_data_df, ticker="SPY"):
    """
    Predicts the next hour close given the latest data.
    
    Args:
        model: Trained LightGBM model.
        current_data_df (pd.DataFrame): Dataframe containing the latest data points (needs history for features).
        ticker (str): Ticker to load feature names for.
        
    Returns:
        float: Predicted price.
        
    Raises:
        FeatureMismatchError: If the data features don't match model expectations.
    """
    # Load feature names dynamically from HF Hub
    feature_names_path = get_hf_path(f"models/features_{ticker}.pkl")
    if feature_names_path and os.path.exists(feature_names_path):
        feature_cols = joblib.load(feature_names_path)
    else:
        raise FileNotFoundError(f"Feature list not found for {ticker} on HF Hub. Train model first.")

    # Get the last row of features
    last_row = current_data_df.iloc[[-1]]
    
    # Get available features in the dataframe
    available_features = set(last_row.columns)
    expected_features = set(feature_cols)
    
    # Check for feature mismatch
    if len(available_features & expected_features) != len(expected_features):
        missing = expected_features - available_features
        extra = available_features - expected_features
        
        if missing or extra:
            print(f"⚠️ Feature alignment issue for {ticker}:")
            if missing:
                print(f"   Missing features: {missing}")
            if extra:
                print(f"   Extra features: {extra}")
            
            # Raise exception to trigger retraining
            raise FeatureMismatchError(
                expected_features=feature_cols,
                actual_features=list(last_row.columns),
                expected_count=len(feature_cols),
                actual_count=len(last_row.columns)
            )
    
    # Ensure features match: select only the expected features in the correct order
    # Fill missing features with 0
    last_row_aligned = last_row.reindex(columns=feature_cols, fill_value=0)
    
    prediction = model.predict(last_row_aligned.values)
    return prediction[0]

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
