import logging
import time
import base64
import pickle
import uuid
from datetime import datetime
from typing import Dict, Optional

import yfinance as yf
import requests
import numpy as np
import pandas as pd
import ta
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from apscheduler.schedulers.blocking import BlockingScheduler

# ============================================================================
# CONFIGURATION
# ============================================================================
API_KEY_ID = "4d2e8dc4-7ed7-45ec-9133-f6d1f0ea02c8"
KEY_FILE_PATH = '/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab/Kalshi API Trading Bot.txt'
BASE_URL = "https://demo-api.kalshi.co"

# Telegram Credentials
TELEGRAM_TOKEN = "8328470668:AAH-C-1SrNqyxzmzewCQvGWlDzQxuWuY4rk"
TELEGRAM_CHAT_ID = "5876085554"

BTC_TICKER = "BTC-USD"
MODEL_PATH = "/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab/btc_retail_sniper_v1.pkl"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("trades.log"), logging.StreamHandler()]
)
logger = logging.getLogger("KalshiBot")

# ============================================================================
# UTILITIES
# ============================================================================

def send_telegram_msg(message: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": message, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Telegram Notification Failed: {e}")

def get_auth_headers(method: str, path: str) -> Dict[str, str]:
    """Generates RSA-PSS signed headers for Kalshi V2."""
    with open(KEY_FILE_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    
    timestamp = str(int(time.time() * 1000))
    msg = timestamp + method + path
    
    signature = private_key.sign(
        msg.encode('utf-8'),
        padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH),
        hashes.SHA256()
    )
    
    return {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode('utf-8'),
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

# ============================================================================
# MARKET DISCOVERY
# ============================================================================

def get_active_btc_ticker() -> Optional[str]:
    """Dynamically finds the current BTC Hourly ticker."""
    path = "/trade-api/v2/markets?limit=20&status=open&ticker_prefix=BTC"
    headers = get_auth_headers("GET", path)
    try:
        res = requests.get(BASE_URL + path, headers=headers)
        if res.status_code == 200:
            markets = res.json().get('markets', [])
            for m in markets:
                # We want the 'Close' price hourly market
                if "Hourly" in m.get('title', '') and "BHE" in m.get('ticker', ''):
                    return m['ticker']
    except Exception as e:
        logger.error(f"Market discovery failed: {e}")
    return None

# ============================================================================
# TRADING TASK
# ============================================================================

def trading_job():
    logger.info("--- 🏁 Hourly Trade Signal Check ---")
    
    # 1. Market Discovery
    ticker = get_active_btc_ticker()
    if not ticker:
        logger.warning("No active hourly BTC market found.")
        return
    
    logger.info(f"Targeting Market: {ticker}")

    # 2. Get Orderbook/Ask
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    headers = get_auth_headers("GET", path)
    res = requests.get(BASE_URL + path, headers=headers)
    
    if res.status_code == 200:
        orderbook = res.json().get('orderbook', {})
        # Kalshi V2 returns lists of [price, quantity]
        yes_asks = orderbook.get('yes', [])
        if not yes_asks:
            logger.info("Orderbook empty for Yes side.")
            return
            
        best_ask = yes_asks[0][0] # First element is the best price
        
        # 3. Model Inference (Simplified for this script - wrap your existing logic here)
        # probability = MODEL.predict_proba(latest_features)[0, 1]
        probability = 0.65 # Dummy value for logic testing
        
        edge = probability - (best_ask / 100)
        logger.info(f"Prob: {probability:.2f} | Mkt: {best_ask/100:.2f} | Edge: {edge:.2f}")

        if edge > 0.05:
            # 4. Execute POST Order
            order_path = "/trade-api/v2/portfolio/orders"
            order_payload = {
                "ticker": ticker,
                "action": "buy",
                "side": "yes",
                "count": 1,
                "type": "limit",
                "yes_price": int(best_ask),
                "client_order_id": str(uuid.uuid4())
            }
            order_headers = get_auth_headers("POST", order_path)
            trade_res = requests.post(BASE_URL + order_path, json=order_payload, headers=order_headers)
            
            if trade_res.status_code in [200, 201]:
                msg = f"🚀 *TRADE EXECUTED*\nMkt: `{ticker}`\nEdge: `{edge:.2f}`\nPrice: `{best_ask}¢`"
                send_telegram_msg(msg)
            else:
                send_telegram_msg(f"❌ *ORDER FAILED*\n{trade_res.text}")
        else:
            logger.info("Insufficient edge. Skipping.")

# ============================================================================
# STARTUP
# ============================================================================

if __name__ == "__main__":
    send_telegram_msg("🤖 *KalshiBot Active*\nMode: `Demo`\nFrequency: `1m past top-of-hour`")
    
    scheduler = BlockingScheduler()
    scheduler.add_job(trading_job, 'cron', minute=1, second=0)
    
    try:
        logger.info("Scheduler Started. Standing by.")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass