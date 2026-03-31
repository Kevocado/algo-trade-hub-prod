"""
Kalshi Bot - Algorithmic trading daemon for BTC hourly markets.
Pylint-compliant with LightGBM inference and dynamic EV gating.
"""

import logging
import time
from datetime import datetime
from typing import Dict, Optional, Tuple
import pickle

import yfinance as yf
import requests
import numpy as np
import pandas as pd
import ta
from apscheduler.schedulers.blocking import BlockingScheduler

# ============================================================================
# CONFIGURATION
# ============================================================================

KALSHI_DEMO_API_BASE = "https://demo-api.kalshi.com/v1"
KALSHI_API_SLEEP = 1  # seconds between calls (rate limit)
BTC_TICKER = "BTC-USD"
MODEL_PATH = "btc_retail_sniper_v1.pkl"

# Load pre-trained LightGBM model
with open(MODEL_PATH, "rb") as f:
    MODEL = pickle.load(f)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("trades.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# PROFITABLE MATRIX (2025 Research)
# Format: {day_of_week: [hours]}
# day_of_week: 0=Mon, 1=Tue, ..., 5=Fri, 6=Sat, 7=Sun
# ============================================================================

PROFITABLE_MATRIX = {
    1: [22],              # Tuesday 22:00 UTC
    4: [16],              # Friday 16:00 UTC
    5: [16, 20, 22, 23],  # Saturday 16, 20, 22, 23 UTC
    6: [0, 22]            # Sunday 00, 22 UTC
}

# ============================================================================
# TECHNICAL FEATURE ENGINE (From lightgbm_backtest.ipynb Cell 2)
# ============================================================================


def add_technical_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Apply technical indicators to BTC price data.

    Args:
        df: DataFrame with OHLCV columns (Close, High, Low, Volume, index=datetime)

    Returns:
        DataFrame with engineered features
    """
    df = df.copy()

    # 1. VOLATILITY NORMALIZED RETURNS (Shock Resistance)
    rolling_std = df['Close'].pct_change().rolling(window=24).std()
    df['ret_1h_z'] = (
        df['Close'].pct_change(1) / (rolling_std + 1e-6)
    )
    df['ret_4h'] = df['Close'].pct_change(4)

    # 2. TEMPORAL & CYCLICAL FEATURES (Context)
    df['hour'] = df.index.hour
    df['dayofweek'] = df.index.dayofweek
    df['is_weekend'] = (df['dayofweek'] >= 5).astype(int)
    df['is_retail_window'] = (df['dayofweek'] >= 4).astype(int)

    # Cyclical hour encoding (Helps model link 11PM and 12AM)
    df['sin_hour'] = np.sin(2 * np.pi * df['hour'] / 24)
    df['cos_hour'] = np.cos(2 * np.pi * df['hour'] / 24)

    # 3. RSI & MOMENTUM (Z-Score Scaled for Stability)
    df['rsi_5'] = ta.momentum.rsi(df['Close'], window=5)
    df['rsi_7'] = ta.momentum.rsi(df['Close'], window=7)
    df['rsi_14'] = ta.momentum.rsi(df['Close'], window=14)
    rsi_7_mean = df['rsi_7'].rolling(24).mean()
    rsi_7_std = df['rsi_7'].rolling(24).std()
    df['rsi_z'] = (df['rsi_7'] - rsi_7_mean) / (rsi_7_std + 1e-6)

    # 4. INTERACTION & VOLATILITY (The 'Golden Hour' Signals)
    df['retail_rsi'] = df['rsi_z'] * df['is_retail_window']
    df['midnight_signal'] = (df['hour'] == 0).astype(int)

    atr = ta.volatility.average_true_range(
        df['High'],
        df['Low'],
        df['Close'],
        window=14
    )
    df['vol_adj_ret'] = (
        df['Close'].pct_change() / (atr / df['Close'] + 1e-6)
    )
    close_24_mean = df['Close'].rolling(24).mean()
    close_24_std = df['Close'].rolling(24).std()
    df['z_score_24h'] = (
        (df['Close'] - close_24_mean) / (close_24_std + 1e-6)
    )

    # 5. VOLUME CONVICTION
    vol_24_mean = df['Volume'].rolling(24).mean()
    df['vol_spike'] = (df['Volume'] > vol_24_mean).astype(int)

    return df.dropna()


# ============================================================================
# EV DECISION ENGINE (From user's check_dynamic_trade)
# ============================================================================


def check_dynamic_trade(
    model_probability: float,
    current_ask_price: float,
    min_edge: float = 0.05
) -> Dict[str, any]:  # pylint: disable=invalid-name
    """
    Evaluates a dynamic entry based on live Kalshi order book.

    Args:
        model_probability: Model prediction (0-1)
        current_ask_price: Kalshi ask price in cents (e.g., 40 = $0.40)
        min_edge: Minimum edge required to trade (default 0.05 = 5%)

    Returns:
        Dict with keys: "signal" (BUY/PASS), "reason", "ev", "price_limit"
    """
    # Convert Kalshi cents to probability
    market_implied_prob = current_ask_price / 100.0

    # 1. THE EDGE CHECK
    edge = model_probability - market_implied_prob

    if edge < min_edge:
        return {
            "signal": "PASS",
            "reason": (
                f"No Edge. Model: {model_probability:.2f}, "
                f"Market: {market_implied_prob:.2f}"
            )
        }

    # 2. THE EV MATH
    potential_profit = 1.00 - market_implied_prob
    risk_cost = market_implied_prob

    expected_value = (
        (model_probability * potential_profit) -
        ((1 - model_probability) * risk_cost)
    )

    if expected_value > 0:
        return {
            "signal": "BUY",
            "price_limit": current_ask_price,
            "ev": expected_value
        }
    else:
        return {
            "signal": "PASS",
            "reason": "Negative EV"
        }


# ============================================================================
# KALSHI API HELPERS
# ============================================================================


def get_kalshi_ask(market_ticker: str) -> Optional[float]:
    """
    Fetch current ask price from Kalshi Demo API.

    Args:
        market_ticker: Kalshi market identifier

    Returns:
        Ask price (in cents) or None if API call fails
    """
    time.sleep(KALSHI_API_SLEEP)  # Rate limit enforcement
    try:
        response = requests.get(
            f"{KALSHI_DEMO_API_BASE}/markets/{market_ticker}",
            timeout=10
        )
        response.raise_for_status()
        data = response.json()
        ask_price = data.get("ask_price")
        logger.info(f"Kalshi ask for {market_ticker}: {ask_price}¢")
        return ask_price
    except requests.RequestException as error:
        logger.error(f"Kalshi API error: {error}")
        return None


def place_limit_order(
    market_ticker: str,
    side: str,
    limit_price: float,
    quantity: int = 1
) -> Optional[str]:
    """
    Place limit order on Kalshi Demo API.

    Args:
        market_ticker: Kalshi market identifier
        side: "BUY" or "SELL"
        limit_price: Limit price in cents
        quantity: Order size

    Returns:
        Order ID or None if placement fails
    """
    time.sleep(KALSHI_API_SLEEP)  # Rate limit enforcement
    payload = {
        "ticker": market_ticker,
        "side": side,
        "type": "limit",
        "limit_price": limit_price,
        "quantity": quantity
    }
    try:
        response = requests.post(
            f"{KALSHI_DEMO_API_BASE}/orders",
            json=payload,
            timeout=10
        )
        response.raise_for_status()
        order_data = response.json()
        order_id = order_data.get("order_id")
        logger.info(
            f"Order placed: {order_id} | {side} {quantity} @ {limit_price}¢"
        )
        return order_id
    except requests.RequestException as error:
        logger.error(f"Order placement failed: {error}")
        return None


# ============================================================================
# CORE TRADING LOOP
# ============================================================================


def fetch_btc_data() -> Optional[pd.DataFrame]:
    """
    Fetch last 48 hours of BTC data from yfinance.

    Returns:
        DataFrame with OHLCV data or None if fetch fails
    """
    try:
        data = yf.download(
            BTC_TICKER,
            period="3d",
            interval="1h",
            progress=False
        )
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)
        logger.info(f"Fetched {len(data)} candles for {BTC_TICKER}")
        return data
    except Exception as error:  # pylint: disable=broad-except
        logger.error(f"yfinance error: {error}")
        return None


def is_profitable_hour() -> bool:
    """
    Check if current day/hour is in PROFITABLE_MATRIX.

    Returns:
        True if current time is profitable, False otherwise
    """
    now = datetime.utcnow()
    day_of_week = now.weekday()
    hour = now.hour

    is_profitable = (
        day_of_week in PROFITABLE_MATRIX and
        hour in PROFITABLE_MATRIX[day_of_week]
    )

    logger.info(
        f"Profitable check: {day_of_week}/{hour} = {is_profitable}"
    )
    return is_profitable


def trading_job():
    """
    Main trading job: runs at top of every hour.
    Implements: Filter -> Data -> Brain -> Bouncer -> Trigger
    """
    logger.info("===== TRADING JOB START =====")

    # FILTER: Check PROFITABLE_MATRIX
    if not is_profitable_hour():
        logger.info("Not a profitable hour. Sleeping...")
        return

    logger.info("Profitable hour detected. Proceeding...")

    # DATA: Fetch BTC price history
    btc_data = fetch_btc_data()
    if btc_data is None:
        logger.warning("Failed to fetch BTC data. Aborting.")
        return

    # Apply technical features
    try:
        df_features = add_technical_features(btc_data)
        if df_features.empty:
            logger.warning("Feature engineering produced empty DataFrame.")
            return
    except Exception as error:  # pylint: disable=broad-except
        logger.error(f"Feature engineering error: {error}")
        return

    # BRAIN: Extract latest feature row and run inference
    try:
        latest_features = df_features.iloc[-1:].drop(
            columns=['target'],
            errors='ignore'
        )
        probability = MODEL.predict_proba(latest_features)[0, 1]
        logger.info(f"Model probability: {probability:.4f}")
    except Exception as error:  # pylint: disable=broad-except
        logger.error(f"Model inference failed: {error}")
        return

    # BOUNCER: Fetch Kalshi ask price and evaluate EV
    kalshi_ask = get_kalshi_ask("BTCUSD-HOURLY")
    if kalshi_ask is None:
        logger.warning("Failed to fetch Kalshi ask. Aborting.")
        return

    trade_decision = check_dynamic_trade(probability, kalshi_ask)
    logger.info(f"Trade decision: {trade_decision}")

    # TRIGGER: Place order if signal is BUY
    if trade_decision["signal"] == "BUY":
        order_id = place_limit_order(
            market_ticker="BTCUSD-HOURLY",
            side="BUY",
            limit_price=trade_decision["price_limit"],
            quantity=1
        )
        if order_id:
            logger.info(
                f"Trade executed: {order_id} | EV: "
                f"{trade_decision['ev']:.4f}"
            )
        else:
            logger.warning("Order placement failed.")
    else:
        logger.info(
            f"No trade: {trade_decision.get('reason', 'Unknown')}"
        )

    logger.info("===== TRADING JOB END =====\n")


# ============================================================================
# SCHEDULER
# ============================================================================


def start_bot():
    """Initialize and start the trading daemon."""
    logger.info("Starting Kalshi Bot...")
    scheduler = BlockingScheduler()

    # Schedule job to run at minute 1, second 0 of every hour
    scheduler.add_job(
        trading_job,
        "cron",
        minute=1,
        second=0,
        id="trading_job"
    )

    logger.info("Scheduler initialized. Running...")
    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Shutting down gracefully...")
        scheduler.shutdown()


if __name__ == "__main__":
    start_bot()