import logging, time, base64, pickle, uuid, requests
from datetime import datetime
from typing import Dict
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from apscheduler.schedulers.blocking import BlockingScheduler

# === CONFIG ===
API_KEY_ID = "4d2e8dc4-7ed7-45ec-9133-f6d1f0ea02c8"
KEY_FILE_PATH = '/root/Kalshi API Trading Bot.txt'
MODELS_PATHS = {'BTC': '/root/kalshibot/btc_retail_sniper_v1.pkl', 'ETH': '/root/kalshibot/eth_sniper.pkl'}
TELEGRAM_TOKEN = "8328470668:AAH-C-1SrNqyxzmzewCQvGWlDzQxuWuY4rk"
TELEGRAM_CHAT_ID = "5876085554"
BASE_URL = "https://demo-api.kalshi.co" # Change to api.kalshi.com for live

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("KalshiBot")

# === UTILS ===
def send_tg(msg: str):
    try: requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"}, timeout=10)
    except: pass

def get_auth_headers(method: str, path: str):
    with open(KEY_FILE_PATH, "rb") as f:
        private_key = serialization.load_pem_private_key(f.read(), password=None)
    ts = str(int(time.time() * 1000))
    signature = private_key.sign((ts + method + path).encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": API_KEY_ID, "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode(), "KALSHI-ACCESS-TIMESTAMP": ts, "Content-Type": "application/json"}

# === QUOTING & EXECUTION ===
def get_quote(ticker: str):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    res = requests.get(BASE_URL + path, headers=get_auth_headers("GET", path))
    if res.status_code == 200:
        asks = res.json().get('orderbook', {}).get('yes', [])
        return asks[0][0] if asks else None
    return None

def place_order(ticker: str, side: str, count: int, price: int):
    """Place a limit order on Kalshi."""
    path = "/trade-api/v2/portfolio/orders"
    payload = {
        "ticker": ticker,
        "action": "buy",
        "type": "limit",
        "side": side, # 'yes' or 'no'
        "count": count,
        "yes_price": price,
        "client_order_id": str(uuid.uuid4())
    }
    res = requests.post(BASE_URL + path, json=payload, headers=get_auth_headers("POST", path))
    if res.status_code == 201:
        logger.info(f"✅ Order Placed: {ticker} at {price}c")
        return res.json()
    logger.error(f"❌ Order Failed: {res.text}")
    return None

# === ENGINE ===
def trade_cycle():
    logger.info("⏰ Cycle triggered. Discovering markets...")
    
    # Discovery
    path = "/trade-api/v2/markets?limit=20&status=open&ticker_prefix=BTC,ETH"
    res = requests.get(BASE_URL + path, headers=get_auth_headers("GET", path))
    if res.status_code != 200: return

    # Filter for Hourly tickers
    markets = [m for m in res.json().get('markets', []) if "Hourly" in m.get('title', '')]
    
    if not markets:
        logger.warning("No active hourly markets found.")
        return

    # Heavy imports inside cycle to keep VPS RAM low
    import pandas as pd
    import yfinance as yf

    for m in markets:
        ticker = m['ticker']
        asset = 'BTC' if 'BTC' in ticker else 'ETH'
        
        # 1. Get Quote
        best_ask = get_quote(ticker)
        if best_ask is None: continue
        
        # 2. Get Model Probability (Placeholder for your inference logic)
        try:
            with open(MODELS_PATHS[asset], "rb") as f:
                model = pickle.load(f)
            # prob = model.predict(your_features)
            prob = 0.75 # Hardcoded for testing
        except: continue

        # 3. Calculate Edge
        market_prob = best_ask / 100
        edge = prob - market_prob
        
        if edge > 0.05:
            send_tg(f"🎯 *Edge Detected!* \nTicker: `{ticker}`\nPrice: `{best_ask}c` \nEdge: `{edge:.1%}`")
            # To go live, uncomment below:
            # place_order(ticker, 'yes', 1, best_ask)

if __name__ == "__main__":
    print("🚀 SCRIPT STARTING...")
    try:
        path = "/trade-api/v2/portfolio/balance"
        res = requests.get(BASE_URL + path, headers=get_auth_headers("GET", path))
        if res.status_code == 200:
            bal = res.json().get('balance', 0)
            send_tg(f"🤖 *KalshiBot Online*\nAuth: `SUCCESS`\nBalance: `${bal/100:.2f}`")
    except Exception as e:
        send_tg(f"🚨 Startup Error: {e}")

    scheduler = BlockingScheduler()
    scheduler.add_job(trade_cycle, 'cron', minute=1, second=0)
    scheduler.start()