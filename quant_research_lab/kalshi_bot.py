import os, logging, time, base64, pickle, uuid, requests
from dotenv import load_dotenv
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from apscheduler.schedulers.blocking import BlockingScheduler

# Load .env first
load_dotenv('/root/kalshibot/.env')
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# CONFIG
API_KEY_ID = "4d2e8dc4-7ed7-45ec-9133-f6d1f0ea02c8"
KEY_FILE_PATH = '/root/Kalshi API Trading Bot.txt'
MODELS_PATHS = {'BTC': '/root/kalshibot/btc_retail_sniper_v1.pkl', 'ETH': '/root/kalshibot/eth_sniper.pkl'}
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKE")
TELEGRAM_CHAT_ID = "5876085554"
BASE_URL = "https://demo-api.kalshi.co"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")
logger = logging.getLogger("KalshiBot")

def get_gemini_opinion(asset, ticker, model_prob, market_price):
    if not GEMINI_API_KEY: return "LLM Key Missing"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    prompt = {"contents": [{"parts": [{"text": f"Analyze this {asset} hourly trade. ML Model Prob: {model_prob:.1%}. Market Price: {market_price}c. Give a 1-sentence conviction statement."}]}]}
    try:
        res = requests.post(url, json=prompt, timeout=10)
        return res.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except: return "Analyst offline."

def send_tg(msg):
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={"chat_id": TELEGRAM_CHAT_ID, "text": msg, "parse_mode": "Markdown"})

def get_auth_headers(method, path):
    with open(KEY_FILE_PATH, "rb") as f:
        key = serialization.load_pem_private_key(f.read(), password=None)
    ts = str(int(time.time() * 1000))
    sig = key.sign((ts+method+path).encode(), padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.MAX_LENGTH), hashes.SHA256())
    return {"KALSHI-ACCESS-KEY": API_KEY_ID, "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(), "KALSHI-ACCESS-TIMESTAMP": ts, "Content-Type": "application/json"}

def get_quote(ticker):
    path = f"/trade-api/v2/markets/{ticker}/orderbook"
    res = requests.get(BASE_URL + path, headers=get_auth_headers("GET", path))
    if res.status_code == 200:
        asks = res.json().get('orderbook', {}).get('yes', [])
        return asks[0][0] if asks else None
    return None
def trade_cycle():
    logger.info("⏰ Cycle triggered. Scanning for crypto series...")
    
    # 1. Fetch more markets (100) to ensure we see the new KX prefixes
    path = "/trade-api/v2/markets?limit=100&status=open"
    headers = get_auth_headers("GET", path)
    
    try:
        res = requests.get(BASE_URL + path, headers=headers, timeout=10)
        if res.status_code != 200:
            logger.error(f"Market fetch failed: {res.status_code}")
            return

        all_markets = res.json().get('markets', [])
        
        # 2. Robust Filtering for 2026 Tickers
        # We look for BTC/ETH in ticker AND ('Hourly' in title OR '-H' in ticker)
        hourly_markets = [
            m for m in all_markets 
            if any(asset in m.get('ticker', '') for asset in ['BTC', 'ETH']) 
            and ("Hourly" in m.get('title', '') or "-H" in m.get('ticker', ''))
        ]
        
        # Sort by closing soonest (the current active hour)
        hourly_markets.sort(key=lambda x: x.get('close_time', ''))
        
        targets = {'BTC': None, 'ETH': None}
        for m in hourly_markets:
            asset = 'BTC' if 'BTC' in m['ticker'] else 'ETH'
            if not targets[asset]:
                targets[asset] = m['ticker']
                # THIS WILL SHOW IN YOUR TERMINAL NOW:
                print(f"✅ Found Target: {asset} -> {m['ticker']}")

        if not any(targets.values()):
            print("⚠️ No active hourly markets found. Kalshi might be between contract hours.")
            return

        # 3. Model Logic
        import pandas as pd
        for asset, ticker in targets.items():
            if not ticker: continue
            
            price = get_quote(ticker)
            if price is None: continue
            
            model_prob = 0.75 # Placeholder
            market_prob = price / 100
            edge = model_prob - market_prob
            
            print(f"📊 Analyzing {ticker} | Price: {price}c | Edge: {edge:.2%}")

            if edge > 0.05:
                analysis = get_gemini_opinion(asset, ticker, model_prob, price)
                send_tg(f"🎯 *Edge Found: {asset}*\nPrice: `{price}¢` | Edge: `{edge:.1%}`\n\n🤖 *Analyst:* {analysis}")

    except Exception as e:
        logger.error(f"Cycle crashed: {e}")
        send_tg(f"🚨 *Cycle Crash:* {e}")
if __name__ == "__main__":
    print("🚀 SCRIPT STARTING...")
    send_tg("🤖 *Kalshi Intelligence Online*")
    sched = BlockingScheduler()
    sched.add_job(trade_cycle, 'cron', minute=1)
    sched.start()