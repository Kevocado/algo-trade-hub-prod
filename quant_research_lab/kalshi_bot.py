import logging
import time
import base64
import pickle
import uuid
import requests
from datetime import datetime
from typing import Dict, Optional
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from apscheduler.schedulers.blocking import BlockingScheduler

# ============================================================================
# CONFIGURATION (Absolute Paths for VPS)
# ============================================================================
API_KEY_ID = "4d2e8dc4-7ed7-45ec-9133-f6d1f0ea02c8"
KEY_FILE_PATH = '/root/Kalshi API Trading Bot.txt'
MODELS_PATHS = {
    'BTC': '/root/kalshibot/btc_retail_sniper_v1.pkl',
    'ETH': '/root/kalshibot/eth_sniper.pkl'
}

TELEGRAM_TOKEN = "8328470668:AAH-C-1SrNqyxzmzewCQvGWlDzQxuWuY4rk"
TELEGRAM_CHAT_ID = "5876085554"
BASE_URL = "https://demo-api.kalshi.co"

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("/root/kalshibot/trades.log"), logging.StreamHandler()]
)
logger = logging.getLogger("KalshiBot")

# ============================================================================
# CORE UTILITIES
# ============================================================================

def send_tg(msg: str):
    """Sends a notification to your Telegram bot."""
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Telegram failed: {e}")

def get_auth_headers(method: str, path: str) -> Dict[str, str]:
    """Generates the RSA-PSS signed headers required for Kalshi V2."""
    try:
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
    except Exception as e:
        logger.error(f"Auth Header Generation Failed: {e}")
        return {}

# ============================================================================
# TRADING ENGINE (Lazy Imports to Save RAM)
# ============================================================================

def trade_cycle():
    """Runs at the top of the hour. Only loads heavy libs when needed."""
    logger.info("--- 🏁 Starting Trade Cycle (Loading Libraries) ---")
    
    try:
        import yfinance as yf
        import pandas as pd
        import ta
        import numpy as np
    except ImportError as e:
        send_tg(f"❌ *Import Error:* {e}")
        return

    # 1. Ticker Discovery
    path = "/trade-api/v2/markets?limit=20&status=open&ticker_prefix=BTC,ETH"
    headers = get_auth_headers("GET", path)
    res = requests.get(BASE_URL + path, headers=headers)
    
    if res.status_code != 200:
        logger.error(f"Market fetch failed: {res.text}")
        return

    markets = [m for m in res.json().get('markets', []) if "Hourly" in m.get('title', '')]
    
    for m in markets:
        ticker = m['ticker']
        asset = 'BTC' if 'BTC' in ticker else 'ETH'
        logger.info(f"Analyzing {ticker}...")

        # 2. Load Model
        try:
            with open(MODELS_PATHS[asset], "rb") as f:
                model = pickle.load(f)
        except Exception as e:
            logger.error(f"Model Load Failed for {asset}: {e}")
            continue

        # 3. Get Price/Inference (Logic Placeholder)
        # Note: You'll integrate your specific technical_feature_engine here
        prob = 0.65 # Dummy probability for logic test
        
        # 4. Check Orderbook & Trade
        ob_path = f"/trade-api/v2/markets/{ticker}/orderbook"
        ob_res = requests.get(BASE_URL + ob_path, headers=get_auth_headers("GET", ob_path))
        
        if ob_res.status_code == 200:
            asks = ob_res.json().get('orderbook', {}).get('yes', [])
            if asks:
                best_ask = asks[0][0]
                edge = prob - (best_ask / 100)
                
                if edge > 0.05:
                    send_tg(f"🚀 *Opportunity Found:* `{ticker}`\nEdge: `{edge:.2f}`\nPrice: `{best_ask}¢`")
                    # (Insert POST /orders logic here)

# ============================================================================
# MAIN ENTRY POINT (Instant Startup)
# ============================================================================

if __name__ == "__main__":
    print("🚀 SCRIPT STARTING...")
    # Test Auth Immediately
    try:
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(BASE_URL + path, headers=get_auth_headers("GET", path))
        if res.status_code == 200:
            balance = res.json().get('balance', 0)
            send_tg(f"🤖 *Kalshi Multi-Bot Online*\nMode: `Lazy (Low RAM)`\nAuth: `SUCCESS`\nBalance: `${balance / 100:.2f}`")
        else:
            send_tg(f"❌ *Bot Startup Auth Failure:* {res.status_code}")
    except Exception as e:
        send_tg(f"🚨 *Critical Startup Error:* {e}")

    # Start Scheduler
    scheduler = BlockingScheduler()
    scheduler.add_job(trade_cycle, 'cron', minute=1, second=0)
    
    try:
        logger.info("Bot Initialized. Waiting for next hour...")
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutdown signal received.")