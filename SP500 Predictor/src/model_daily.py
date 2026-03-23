"""
Model Daily — LightGBM price predictor + direction classifier for SPY/QQQ

Uses the full 21-feature pipeline from feature_engineering.py.
Two models per ticker:
  1. LGBMRegressor  → next-hour close price (RMSE)
  2. LGBMClassifier → next-hour direction probability (Brier Score)

The classifier outputs P(up) which is directly comparable to
Kalshi implied probabilities for arbitrage detection.

Sizing: Quarter-Kelly (0.25×).
"""

import pandas as pd
import numpy as np
import lightgbm as lgb
import joblib
import os
from dotenv import load_dotenv

load_dotenv()


def prepare_daily_data(df, ticker="SPY"):
    """
    Prepares data using the full 3-cluster feature pipeline.
    Target: NEXT-HOUR close price (shift(-1)).

    Filters overnight/weekend gaps so shift(-1) only references
    the actual next intraday bar, not Monday's open from Friday's close.
    """
    from src.feature_engineering import create_features, FEATURE_COLUMNS

    df, gex_data = create_features(df, ticker)

    # Filter out overnight/weekend gaps (>2h between bars)
    # shift(-1) on a gap bar would predict Monday from Friday — not useful
    time_gaps = df.index.to_series().diff().shift(-1).dt.total_seconds() / 3600
    intraday_mask = time_gaps <= 2.0  # next bar is within 2 hours
    df = df[intraday_mask]

    # Target: next hour's close price (the actual next bar)
    df['Target_Close'] = df['Close'].shift(-1)

    # Target for regressor: next-bar % return (scale-invariant)
    df['Target_Return'] = (df['Target_Close'] - df['Close']) / df['Close'] * 100

    # Binary direction target: 1 if next bar is up, 0 if down
    df['Target_Direction'] = (df['Target_Close'] > df['Close']).astype(int)

    # Drop NaN (last row has no next bar)
    df = df.dropna(subset=FEATURE_COLUMNS + ['Target_Close', 'Target_Direction', 'Target_Return'])

    return df, FEATURE_COLUMNS, gex_data


def train_daily_model(df, ticker="SPY"):
    """
    Trains two models:
      1. LGBMRegressor for price prediction (RMSE)
      2. LGBMClassifier for directional probability (Brier Score)
    """
    df_proc, feature_cols, gex_data = prepare_daily_data(df, ticker)

    if len(df_proc) < 50:
        print(f"  ⚠️ Insufficient data ({len(df_proc)} rows). Need 50+ for training.")
        return None

    X = df_proc[feature_cols]
    y_return = df_proc["Target_Return"]
    y_dir = df_proc["Target_Direction"]

    # Time-based train/test split
    train_size = int(len(X) * 0.85)
    X_train, X_test = X.iloc[:train_size], X.iloc[train_size:]
    y_ret_train, y_ret_test = y_return.iloc[:train_size], y_return.iloc[train_size:]
    y_dir_train, y_dir_test = y_dir.iloc[:train_size], y_dir.iloc[train_size:]

    # ── Model 1: Return Regressor (RMSE in % points) ──
    regressor = lgb.LGBMRegressor(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    regressor.fit(
        X_train, y_ret_train,
        eval_set=[(X_test, y_ret_test)],
        eval_metric="rmse",
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)]
    )

    preds = regressor.predict(X_test)
    rmse = np.sqrt(np.mean((preds - y_ret_test) ** 2))
    print(f"  📊 {ticker} Regressor RMSE: {rmse:.4f}% (next-hour return)")

    # ── Model 2: Direction Classifier (Brier Score) ──
    classifier = lgb.LGBMClassifier(
        n_estimators=500,
        learning_rate=0.05,
        max_depth=6,
        num_leaves=31,
        min_child_samples=20,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
        objective='binary',
        is_unbalance=True,
    )
    classifier.fit(
        X_train, y_dir_train,
        eval_set=[(X_test, y_dir_test)],
        eval_metric="binary_logloss",
        callbacks=[lgb.early_stopping(stopping_rounds=20, verbose=False)]
    )

    # Brier Score = mean((predicted_prob - actual_outcome)²)
    # Perfect = 0.0, Coin flip = 0.25, Useless > 0.25
    dir_probs = classifier.predict_proba(X_test)[:, 1]  # P(up)
    brier = np.mean((dir_probs - y_dir_test.values) ** 2)
    dir_accuracy = np.mean(classifier.predict(X_test) == y_dir_test.values)
    print(f"  🎯 {ticker} Classifier: Brier={brier:.4f} | Accuracy={dir_accuracy:.1%}")

    # ── Save Both Models ──
    os.makedirs("model", exist_ok=True)
    joblib.dump(regressor, f"model/lgbm_model_{ticker}.pkl")
    joblib.dump(classifier, f"model/lgbm_direction_{ticker}.pkl")
    joblib.dump(feature_cols, f"model/features_{ticker}.pkl")
    print(f"  💾 Models saved: model/lgbm_model_{ticker}.pkl + lgbm_direction_{ticker}.pkl")

    return regressor


def predict_daily_close(model, current_df_features, feature_cols=None):
    """
    Predicts the Daily Close price using the trained model.
    """
    from src.feature_engineering import FEATURE_COLUMNS
    cols = feature_cols or FEATURE_COLUMNS

    X = current_df_features.reindex(columns=cols, fill_value=0)
    prediction = model.predict(X)[-1] if len(X) > 0 else None
    return prediction


def load_daily_model(ticker="SPY"):
    """
    Loads model from HuggingFace Hub, fallback to local.
    """
    local_model = f"model/lgbm_model_{ticker}.pkl"
    local_features = f"model/features_{ticker}.pkl"

    # Try HF Hub first
    try:
        from huggingface_hub import hf_hub_download
        repo_id = "Kevocado/sp500-predictor-models"
        cached = hf_hub_download(repo_id=repo_id, filename=f"lgbm_model_{ticker}.pkl",
                                 cache_dir="model", force_filename=f"lgbm_model_{ticker}.pkl")
        model = joblib.load(cached)
        print(f"  ✅ Loaded {ticker} model from HF Hub")
        return model
    except Exception as e:
        print(f"  ⚠️ HF Hub failed for {ticker}: {e}")

    # Local fallback
    if os.path.exists(local_model):
        print(f"  ✅ Loaded local {ticker} model")
        return joblib.load(local_model)

    print(f"  ❌ No model found for {ticker}")
    return None


def load_direction_model(ticker="SPY"):
    """Loads the binary direction classifier."""
    local_model = f"model/lgbm_direction_{ticker}.pkl"
    if os.path.exists(local_model):
        print(f"  ✅ Loaded {ticker} direction classifier")
        return joblib.load(local_model)
    print(f"  ⚠️ No direction classifier for {ticker}")
    return None


def predict_direction(classifier, current_df_features, feature_cols=None):
    """
    Predicts direction probability P(up) using the binary classifier.
    Returns float between 0.0 and 1.0.
    Directly comparable to Kalshi implied probabilities.
    """
    from src.feature_engineering import FEATURE_COLUMNS
    cols = feature_cols or FEATURE_COLUMNS

    X = current_df_features.reindex(columns=cols, fill_value=0)
    if len(X) > 0:
        prob = classifier.predict_proba(X)[:, 1]
        return prob[-1]
    return 0.5


def quarter_kelly(edge, prob, max_kelly_pct=6):
    """
    Quarter-Kelly position sizing.

    Full Kelly: f* = (edge × prob) / (1 - prob)
    Quarter-Kelly: f = f* × 0.25

    Capped at max_kelly_pct of bankroll.

    Args:
        edge: float, model edge (0.0 to 1.0)
        prob: float, model probability (0.0 to 1.0)
        max_kelly_pct: float, max % of bankroll per trade

    Returns:
        float: recommended position size as % of bankroll
    """
    if prob >= 1.0 or prob <= 0.0 or edge <= 0:
        return 0.0

    full_kelly = (edge * prob) / (1 - prob) * 100
    quarter = full_kelly * 0.25
    return min(quarter, max_kelly_pct)


if __name__ == "__main__":
    print("Testing Model Pipeline...")

    # Test Kelly sizing
    print("\nQuarter-Kelly Examples:")
    for edge, prob in [(0.25, 0.75), (0.15, 0.65), (0.10, 0.55)]:
        k = quarter_kelly(edge, prob)
        print(f"  Edge={edge:.0%}, Prob={prob:.0%} → Size={k:.1f}% of bankroll")

    # Test model loading
    print("\nModel Loading:")
    for t in ["SPY", "QQQ"]:
        m = load_daily_model(t)
        if m:
            print(f"  {t}: {type(m).__name__}")
