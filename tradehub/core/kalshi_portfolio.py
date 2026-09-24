"""
Kalshi Portfolio — Read-Only API Integration (RSA-Signed Auth)

Fetches account balance, open positions, and settlement history.
Uses RSA-PSS signing per Kalshi API docs.

Required .env vars:
  KALSHI_API_KEY_ID  — Your API key ID (from Kalshi account settings)
  KALSHI_API_KEY     — Your RSA private key (PEM format)
"""

import requests
import os
import time
import base64
from datetime import datetime
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from dotenv import load_dotenv
from pathlib import Path

root_dir = Path(__file__).parent.parent
load_dotenv(dotenv_path=root_dir / '.env', override=True)

KALSHI_API_BASE = os.getenv("KALSHI_API_BASE", "https://demo-api.kalshi.co").strip('"').strip("'")
KALSHI_BASE_URL = f"{KALSHI_API_BASE}/trade-api/v2"


class KalshiPortfolio:
    """Read-only Kalshi portfolio client with RSA-PSS authentication."""

    def __init__(self):
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        private_key_pem = os.getenv("KALSHI_API_KEY", "")
        self.key_file_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

        if not self.api_key_id:
            raise ValueError(
                "KALSHI_API_KEY_ID not found in .env. "
                "Get it from Kalshi → Settings → API Keys."
            )
        if not private_key_pem and not self.key_file_path:
            raise ValueError("KALSHI_API_KEY or KALSHI_PRIVATE_KEY_PATH (RSA private key) not found in .env.")

        # Load the RSA private key
        try:
            pem_bytes = None

            # Method 1: Check if a path is provided and valid
            key_path = self.key_file_path or os.getenv("KALSHI_KEY_FILE", "")
            if key_path:
                potential_path = Path(key_path)
                if potential_path.is_file():
                    pem_bytes = potential_path.read_bytes()
                elif (root_dir / key_path).is_file():
                    pem_bytes = (root_dir / key_path).read_bytes()

            # Method 2: Check default filenames in root_dir
            if pem_bytes is None:
                for fname in ['kalshi_private_key.pem', 'kalshi_key.pem', '.kalshi_key.pem', 'Kalshi Edge Tracker.txt']:
                    p = root_dir / fname
                    if p.is_file():
                        pem_bytes = p.read_bytes()
                        break

            # Method 3: Fallback to KALSHI_API_KEY environment variable
            if pem_bytes is None and private_key_pem:
                if 'BEGIN' in private_key_pem:
                    pem_bytes = private_key_pem.encode()
                else:
                    # Generic reconstruction for single-line PEMs
                    body = private_key_pem.strip().replace(' ', '').replace('\\n', '\n')
                    if 'BEGIN' not in body:
                        # Add headers if missing
                        body = f"-----BEGIN RSA PRIVATE KEY-----\n{body}\n-----END RSA PRIVATE KEY-----"
                    pem_bytes = body.encode()

            if pem_bytes is None:
                raise ValueError("No private key found (checked paths and env)")

            # Final Cleanup: Remove any non-printable chars or weird whitespace that might break base64
            # We preserve newlines as they are ignored by PEM loaders
            clean_pem = b""
            for b in pem_bytes:
                if b in b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=-\n\r " or b == ord('-'):
                    clean_pem += bytes([b])
            
            self.private_key = serialization.load_pem_private_key(
                clean_pem, password=None
            )
        except Exception as e:
            raise ValueError(f"Failed to load RSA private key: {e}")

    def _sign_request(self, method, path):
        """
        Generate RSA-PSS signed headers for a Kalshi API request.
        Kalshi requires: timestamp_ms + method + path (no query params) signed with RSA-PSS + SHA256.
        """
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method}{path}"

        signature = self.private_key.sign(
            message.encode(),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH,
            ),
            hashes.SHA256(),
        )
        sig_b64 = base64.b64encode(signature).decode()

        return {
            "KALSHI-ACCESS-KEY": self.api_key_id,
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
            "KALSHI-ACCESS-SIGNATURE": sig_b64,
            "Content-Type": "application/json",
        }

    def _get(self, endpoint, params=None):
        """Make authenticated GET request."""
        path = f"/trade-api/v2{endpoint}"
        url = f"{KALSHI_BASE_URL}{endpoint}"
        headers = self._sign_request("GET", path)
        try:
            r = requests.get(url, headers=headers, params=params, timeout=10)
            if r.status_code == 200:
                return r.json()
            else:
                # Silently fail for market data if needed, but log for others
                if "/markets/" not in endpoint:
                    print(f"  Kalshi API {endpoint}: {r.status_code} — {r.text[:200]}")
                return None
        except Exception as e:
            if "/markets/" not in endpoint:
                print(f"  Kalshi API error: {e}")
            return None

    def get_market_data(self, ticker):
        """Get raw market data for a single ticker."""
        return self._get(f"/markets/{ticker}")

    def get_balance(self):
        """Get account balance. Returns dict with 'balance' in cents."""
        return self._get("/portfolio/balance")

    def get_positions(self, limit=200):
        """Get all open positions."""
        data = self._get("/portfolio/positions", params={"limit": limit})
        if data:
            positions = data.get('market_positions', data.get('positions', []))
            return positions
        return []

    def get_settlements(self, limit=50):
        """Get recent settlements (closed positions and payouts)."""
        data = self._get("/portfolio/settlements", params={"limit": limit})
        if data:
            return data.get('settlements', [])
        return []

    def get_fills(self, limit=50):
        """Get recent trade fills (execution history)."""
        data = self._get("/portfolio/fills", params={"limit": limit})
        if data:
            return data.get('fills', [])
        return []

    def get_portfolio_summary(self):
        """
        Aggregate portfolio data into a summary dict.
        Returns balance, positions, recent P&L, and stats.
        """
        summary = {
            'balance': None,
            'portfolio_value': None,
            'positions': [],
            'total_invested': 0,
            'market_exposure': 0,
            'total_positions': 0,
            'settlements': [],
            'total_pnl': 0,
            'wins': 0,
            'losses': 0,
            'error': None,
        }

        try:
            # Balance
            bal = self.get_balance()
            if bal:
                summary['balance'] = bal.get('balance', 0) / 100  # cents → dollars
                summary['portfolio_value'] = bal.get('portfolio_value', 0) / 100

            # Open positions
            positions = self.get_positions()
            summary['positions'] = positions
            summary['total_positions'] = len(positions)

            for pos in positions:
                ticker = pos.get('ticker')
                # total_traded = total cost in cents, market_exposure = current value in cents
                summary['total_invested'] += float(pos.get('total_traded_dollars', pos.get('total_traded', 0) / 100))
                
                # Fetch live price for accurate exposure
                m_data = self.get_market_data(ticker)
                if m_data and m_data.get('market'):
                    m = m_data['market']
                    # Use yes_ask/yes_bid to estimate mid-market
                    yes_ask = m.get('yes_ask', 0)
                    yes_bid = m.get('yes_bid', 0)
                    current_price = (yes_ask + yes_bid) / 2 if (yes_ask and yes_bid) else (yes_ask or yes_bid or 0)
                    pos['current_price'] = current_price
                    pos['market_exposure_dollars'] = (current_price * pos.get('position', 0)) / 100
                
                summary['market_exposure'] += float(pos.get('market_exposure_dollars', pos.get('market_exposure', 0) / 100))

            # Settlements
            settlements = self.get_settlements(limit=30)
            summary['settlements'] = settlements

            for s in settlements:
                payout = s.get('revenue', 0) / 100  # cents → dollars
                summary['total_pnl'] += payout
                if payout > 0:
                    summary['wins'] += 1
                elif payout < 0:
                    summary['losses'] += 1

        except Exception as e:
            summary['error'] = str(e)

        return summary


def check_portfolio_available():
    """Check if portfolio integration is configured."""
    api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
    api_key = os.getenv("KALSHI_API_KEY", "")
    return bool(api_key_id and api_key)


if __name__ == "__main__":
    print("Testing Kalshi Portfolio API...")

    if not check_portfolio_available():
        print("❌ Missing KALSHI_API_KEY_ID in .env")
        print("   Get it from: Kalshi → Settings → API Keys")
        exit(1)

    try:
        portfolio = KalshiPortfolio()
        summary = portfolio.get_portfolio_summary()

        print(f"\n💰 Balance: ${summary['balance']:.2f}" if summary['balance'] else "Balance: N/A")
        print(f"📊 Open Positions: {summary['total_positions']}")
        print(f"💵 Total Invested: ${summary['total_invested']:.2f}")
        print(f"📈 Settlement P&L: ${summary['total_pnl']:.2f}")
        print(f"   Wins: {summary['wins']} | Losses: {summary['losses']}")

        if summary['positions']:
            print(f"\n── Open Positions ──")
            for p in summary['positions'][:10]:
                print(f"  {p.get('ticker', 'Unknown')}: qty={p.get('total_traded', 0)}, "
                      f"avg={p.get('average_price', 0)}¢")

    except ValueError as e:
        print(f"❌ {e}")
