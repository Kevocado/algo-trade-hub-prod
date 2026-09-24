import os
import time
import base64
import requests
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding

# --- CONFIGURATION ---
API_KEY_ID = "4d2e8dc4-7ed7-45ec-9133-f6d1f0ea02c8"
KEY_FILE_PATH = '/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab/Kalshi API Trading Bot.txt'
BASE_URL = "https://demo-api.kalshi.co" # Root URL

def test_kalshi_v2_official():
    print(f"🔒 Loading Key: {KEY_FILE_PATH}")
    
    try:
        with open(KEY_FILE_PATH, "rb") as f:
            private_key = serialization.load_pem_private_key(f.read(), password=None)
    except Exception as e:
        print(f"❌ Load Error: {e}")
        return

    method = "GET"
    # 🚨 CRITICAL CHANGE: The path MUST include the version prefix for the signature
    path = "/trade-api/v2/portfolio/balance"
    timestamp = str(int(time.time() * 1000))
    
    # Message String: {timestamp}{method}{full_path}
    msg = timestamp + method + path
    print(f"📝 Signing Official Message: {msg}")

    try:
        # 🔑 KALSHI V2 REQUIREMENT: RSA-PSS with SHA256
        signature = private_key.sign(
            msg.encode('utf-8'),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH # Standard salt length
            ),
            hashes.SHA256()
        )
        encoded_sig = base64.b64encode(signature).decode('utf-8')
    except Exception as e:
        print(f"❌ Signing Error: {e}")
        return

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": encoded_sig,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    url = f"{BASE_URL}{path}"
    print(f"📡 Pinging Kalshi V2 Endpoint: {url}")
    
    try:
        res = requests.get(url, headers=headers, timeout=10)
        
        if res.status_code == 200:
            data = res.json()
            print("\n" + "🏁"*15)
            print("✅ SUCCESS! AUTHENTICATED WITH OFFICIAL SPEC.")
            print(f"Balance: ${data.get('balance', 0) / 100:.2f}")
            print("🏁"*15)
        else:
            print(f"\n❌ FAILED ({res.status_code}): {res.text}")
            print("\n💡 If PSS fails, Kalshi sometimes defaults back to PKCS1v15.")
            
    except Exception as e:
        print(f"❌ Connection Error: {e}")

if __name__ == "__main__":
    test_kalshi_v2_official()