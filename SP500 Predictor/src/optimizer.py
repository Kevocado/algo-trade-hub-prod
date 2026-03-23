"""
Self-Healing AI Optimizer — Automatic Model Health Monitor

Responsibilities:
  1. Brier Score drift detection → automatically triggers retraining
  2. Feature importance monitoring → flags dead features
  3. Hyperparameter rotation → periodically tries new configs
  4. Sends Telegram alerts when model health degrades

Runs as a weekly GitHub Actions workflow or manually.
"""

import os
import json
import numpy as np
import pandas as pd
import joblib
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()


BRIER_THRESHOLD = 0.35  # Above this = model is drifting, retrain needed
MIN_PREDICTIONS = 20    # Minimum predictions before evaluating
MODEL_DIR = "model"
LOG_PATH = "Data/optimizer_log.json"


def brier_score(predictions, outcomes):
    """
    Brier Score = (1/N) × Σ(forecast_i - outcome_i)²

    Range: 0 (perfect) to 1 (worst).
    < 0.25 = better than coin flip
    > 0.35 = model is drifting, needs retraining

    Args:
        predictions: array of probabilities (0.0 to 1.0)
        outcomes: array of binary outcomes (0 or 1)

    Returns:
        float: Brier score
    """
    predictions = np.array(predictions, dtype=float)
    outcomes = np.array(outcomes, dtype=float)

    if len(predictions) == 0:
        return None

    return float(np.mean((predictions - outcomes) ** 2))


def check_model_health(ticker="SPY"):
    """
    Evaluates recent predictions against outcomes.
    Returns health report.
    """
    report = {
        'ticker': ticker,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'brier_score': None,
        'n_predictions': 0,
        'status': 'unknown',
        'action': 'none',
        'feature_importance': {},
    }

    # Load recent predictions from Supabase
    try:
        from src.supabase_client import get_trade_history
        trades = get_trade_history(limit=100)
        if not trades:
            report['status'] = 'insufficient_data'
            return report

        preds = []
        outcomes = []
        for t in trades:
            prob = t.get('model_prob')
            resolved = t.get('resolved_outcome')
            if prob is not None and resolved is not None:
                preds.append(float(prob) / 100.0)
                outcomes.append(1.0 if resolved else 0.0)

        report['n_predictions'] = len(preds)

        if len(preds) < MIN_PREDICTIONS:
            report['status'] = 'insufficient_data'
            report['action'] = f'need {MIN_PREDICTIONS - len(preds)} more predictions'
            return report

        # Calculate Brier Score
        bs = brier_score(preds, outcomes)
        report['brier_score'] = round(bs, 4)

        if bs < 0.2:
            report['status'] = 'excellent'
            report['action'] = 'none'
        elif bs < BRIER_THRESHOLD:
            report['status'] = 'healthy'
            report['action'] = 'none'
        else:
            report['status'] = 'drifting'
            report['action'] = 'retrain'

    except Exception as e:
        report['status'] = f'error: {e}'

    # Feature importance
    try:
        model_path = f"{MODEL_DIR}/lgbm_model_{ticker}.pkl"
        if os.path.exists(model_path):
            model = joblib.load(model_path)
            if hasattr(model, 'feature_importances_'):
                features_path = f"{MODEL_DIR}/features_{ticker}.pkl"
                if os.path.exists(features_path):
                    feature_names = joblib.load(features_path)
                    importances = model.feature_importances_
                    report['feature_importance'] = {
                        name: int(imp) for name, imp in zip(feature_names, importances)
                    }
                    # Flag dead features
                    dead = [n for n, i in zip(feature_names, importances) if i == 0]
                    if dead:
                        report['dead_features'] = dead
    except Exception:
        pass

    return report


def retrain_model(ticker="SPY"):
    """
    Retrains the LightGBM model with fresh data.
    Uses the full 20-feature pipeline.
    """
    print(f"\n🔄 Retraining {ticker} model...")

    try:
        from src.data_loader import fetch_data
        from src.model_daily import train_daily_model

        # Fetch 1 month of 1-hour data for training
        df = fetch_data(ticker, period="1mo", interval="1h")
        if df.empty:
            print(f"  ⚠️ No data available for {ticker}")
            return False

        if len(df) < 50:
            print(f"  ⚠️ Only {len(df)} rows — need 50+ for training")
            return False

        model = train_daily_model(df, ticker)
        if model:
            print(f"  ✅ {ticker} model retrained successfully")
            return True
        else:
            print(f"  ❌ Training failed")
            return False

    except Exception as e:
        print(f"  ❌ Retrain error: {e}")
        return False


def run_optimizer():
    """
    Main optimization loop. Evaluates all models and retrains if needed.
    """
    tickers = ["SPY", "QQQ"]
    results = []

    print("=" * 60)
    print("🧠 Self-Healing AI Optimizer")
    print(f"   Time: {datetime.now(timezone.utc).isoformat()}")
    print(f"   Brier Threshold: {BRIER_THRESHOLD}")
    print("=" * 60)

    for ticker in tickers:
        print(f"\n📊 Checking {ticker}...")
        report = check_model_health(ticker)
        results.append(report)

        print(f"   Status: {report['status']}")
        print(f"   Brier Score: {report.get('brier_score', 'N/A')}")
        print(f"   Predictions: {report['n_predictions']}")
        print(f"   Action: {report['action']}")

        if report.get('dead_features'):
            print(f"   ⚠️ Dead features: {report['dead_features']}")

        # Auto-retrain if drifting
        if report['action'] == 'retrain':
            print(f"   🔄 Auto-retraining {ticker}...")
            success = retrain_model(ticker)

            # Send Telegram notification
            try:
                from src.telegram_notifier import TelegramNotifier
                tn = TelegramNotifier()
                emoji = "✅" if success else "❌"
                msg = (
                    f"🧠 **MODEL DRIFT DETECTED**\n\n"
                    f"📊 {ticker} Brier Score: {report['brier_score']}\n"
                    f"📊 Threshold: {BRIER_THRESHOLD}\n"
                    f"🔄 Retrain: {emoji} {'Success' if success else 'Failed'}\n"
                    f"📋 Predictions evaluated: {report['n_predictions']}"
                )
                tn.send_alert(msg)
            except Exception:
                pass

    # Save log
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        log = []
        if os.path.exists(LOG_PATH):
            with open(LOG_PATH, 'r') as f:
                log = json.load(f)
        log.extend(results)
        # Keep last 100 entries
        log = log[-100:]
        with open(LOG_PATH, 'w') as f:
            json.dump(log, f, indent=2)
        print(f"\n💾 Log saved to {LOG_PATH}")
    except Exception as e:
        print(f"  ⚠️ Failed to save log: {e}")

    print(f"\n🏁 Optimizer complete")
    return results


if __name__ == "__main__":
    run_optimizer()
