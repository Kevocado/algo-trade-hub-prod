import os
import time
import base64
import requests
import json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from dotenv import load_dotenv

# 1. Setup Environment
load_dotenv()
API_KEY_ID = os.getenv("KALSHI_API_KEY_ID")
KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH")
BASE_URL = "https://demo-api.kalshi.com/trade-api/v2"

# Run this in a Python cell or a new script
import os

key_path = "/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab/kalshi_private.pem"

if os.path.exists(key_path):
    with open(key_path, "r") as f:
        content = f.read()
    
    # Remove any stray spaces, carriage returns, or hidden junk
    clean_content = content.strip()
    
    with open(key_path, "w") as f:
        f.write(clean_content)
    print("✨ File cleaned and saved successfully.")
else:
    print("❌ Still can't find the file at that path. Check the folder name!")

def test_kalshi_auth():
    print("🔒 Initializing Secure Connection...")
    
    # Load Private Key
    try:
        with open(KEY_PATH, "rb") as key_file:
            private_key = serialization.load_pem_private_key(
                key_file.read(),
                password=None
            )
    except FileNotFoundError:
        print(f"❌ Error: Private key not found at {KEY_PATH}")
        return

    # Define Request
    method = "GET"
    path = "/portfolio/balance"
    url = f"{BASE_URL}{path}"
    timestamp = str(int(time.time() * 1000))
    
    # Create Signature String: timestamp + method + path
    msg = timestamp + method + path
    signature = private_key.sign(msg.encode('utf-8'))
    encoded_sig = base64.b64encode(signature).decode('utf-8')

    headers = {
        "KALSHI-ACCESS-KEY": API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": encoded_sig,
        "KALSHI-ACCESS-TIMESTAMP": timestamp,
        "Content-Type": "application/json"
    }

    # Execute
    print(f"📡 Pinging {BASE_URL}...")
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        balance_data = response.json()
        print("\n" + "="*30)
        print("✅ AUTHENTICATION SUCCESSFUL")
        print("="*30)
        print(f"Current Balance: ${balance_data.get('balance', 0) / 100:.2f}")
        print(f"Account ID:      {balance_data.get('user_id', 'N/A')}")
        print("="*30)
    else:
        print(f"\n❌ AUTHENTICATION FAILED ({response.status_code})")
        print(f"Response: {response.text}")
        print("\nTip: Ensure your Public Key is uploaded to the Kalshi Dashboard.")

if __name__ == "__main__":
    test_kalshi_auth()