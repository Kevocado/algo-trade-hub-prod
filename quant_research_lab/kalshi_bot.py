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
    logger.info("⏰ Hour mark reached. Discovering latest markets...")
    
    # 1. Fetch ALL open BTC and ETH markets
    # We use a broad prefix to catch everything currently active
    path = "/trade-api/v2/markets?limit=50&status=open&ticker_prefix=BTC,ETH"
    headers = get_auth_headers("GET", path)
    
    try:
        res = requests.get(BASE_URL + path, headers=headers, timeout=10)
        if res.status_code != 200:
            logger.error(f"Market fetch failed: {res.status_code}")
            return

        all_markets = res.json().get('markets', [])
        
        # 2. Filter for 'Hourly' markets and sort by expiration (latest first)
        # Kalshi usually has the 'latest' market as the one ending soonest
        hourly_markets = [m for m in all_markets if "Hourly" in m.get('title', '')]
        
        # Sort by 'close_time' so we are always looking at the most immediate opportunity
        hourly_markets.sort(key=lambda x: x.get('close_time', ''))

        # Map to find the "Top" one for each asset
        targets = {'BTC': None, 'ETH': None}
        for m in hourly_markets:
            asset = 'BTC' if 'BTC' in m['ticker'] else 'ETH'
            if not targets[asset]:
                targets[asset] = m['ticker']

        if not targets['BTC'] and not targets['ETH']:
            logger.warning("No active hourly markets discovered.")
            return

        # 3. Import heavy libs ONLY if we found targets
        import pandas as pd
        import yfinance as yf

        for asset, ticker in targets.items():
            if not ticker: continue
            
            # 4. Get the real-time Quote
            price = get_quote(ticker)
            if price is None: continue
            
            # 5. Run your Model Inference (Logic placeholder)
            # This is where you'd call: prob = model.predict(get_features(asset))
            model_prob = 0.75 
            market_prob = price / 100
            edge = model_prob - market_prob
            
            logger.info(f"Analysis: {ticker} | Price: {price}c | Prob: {model_prob:.2f} | Edge: {edge:.2f}")

            # 6. Telegram Alert
            if edge > 0.05:
                msg = (f"🎯 *Edge Found: {asset}*\n"
                       f"Ticker: `{ticker}`\n"
                       f"Price: `{price}¢` ({market_prob:.1%})\n"
                       f"Model: `{model_prob:.1%}`\n"
                       f"🔥 **Edge: {edge:.1%}**")
                send_tg(msg)
                
    except Exception as e:
        logger.error(f"Trade cycle crashed: {e}")
        send_tg(f"🚨 *Cycle Crash:* {e}")
        
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