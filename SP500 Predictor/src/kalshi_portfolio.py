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

KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"


class KalshiPortfolio:
    """Read-only Kalshi portfolio client with RSA-PSS authentication."""

    def __init__(self):
        self.api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
        private_key_pem = os.getenv("KALSHI_API_KEY", "")

        if not self.api_key_id:
            raise ValueError(
                "KALSHI_API_KEY_ID not found in .env. "
                "Get it from Kalshi → Settings → API Keys."
            )
        if not private_key_pem:
            raise ValueError("KALSHI_API_KEY (RSA private key) not found in .env.")

        # Load the RSA private key
        # Supports: (1) file path, (2) multi-line PEM string, (3) single-line PEM from .env
        try:
            pem_bytes = None

            # Method 1: KALSHI_API_KEY is a file path to a .pem file
            key_path = os.getenv("KALSHI_KEY_FILE", "")
            if key_path and os.path.isfile(key_path):
                with open(key_path, 'rb') as f:
                    pem_bytes = f.read()
            elif os.path.isfile(private_key_pem.strip()):
                with open(private_key_pem.strip(), 'rb') as f:
                    pem_bytes = f.read()

            # Method 2: Check for a .pem file next to .env
            if pem_bytes is None:
                default_paths = [
                    root_dir / 'Kalshi Edge Tracker.txt',
                    root_dir / 'kalshi_private_key.pem',
                    root_dir / 'kalshi_key.pem',
                    root_dir / '.kalshi_key.pem',
                ]
                for p in default_paths:
                    if p.is_file():
                        with open(p, 'rb') as f:
                            pem_bytes = f.read()
                        break

            # Method 3: Inline PEM in env var (has newlines already)
            if pem_bytes is None and '\n' in private_key_pem:
                pem_bytes = private_key_pem.encode()

            # Method 4: Single-line PEM from .env — reconstruct
            if pem_bytes is None:
                pem = private_key_pem.strip()
                pem_body = pem.replace('-----BEGIN RSA PRIVATE KEY-----', '') \
                              .replace('-----END RSA PRIVATE KEY-----', '') \
                              .replace('-----BEGIN PRIVATE KEY-----', '') \
                              .replace('-----END PRIVATE KEY-----', '') \
                              .replace(' ', '')

                # Fix base64 padding
                pem_body = pem_body.rstrip('=')
                pad = (4 - len(pem_body) % 4) % 4
                pem_body += '=' * pad

                if 'RSA PRIVATE KEY' in private_key_pem:
                    header = '-----BEGIN RSA PRIVATE KEY-----'
                    footer = '-----END RSA PRIVATE KEY-----'
                else:
                    header = '-----BEGIN PRIVATE KEY-----'
                    footer = '-----END PRIVATE KEY-----'

                lines = [pem_body[i:i+64] for i in range(0, len(pem_body), 64)]
                pem_str = header + '\n' + '\n'.join(lines) + '\n' + footer
                pem_bytes = pem_str.encode()

            self.private_key = serialization.load_pem_private_key(
                pem_bytes, password=None
            )
        except Exception as e:
            raise ValueError(
                f"Failed to load RSA private key: {e}\n\n"
                f"💡 Recommended fix: Save your private key as a .pem FILE:\n"
                f"   1. Create a file called 'kalshi_private_key.pem' in your project root\n"
                f"   2. Paste the full RSA private key (with proper line breaks) into it\n"
                f"   3. The app will auto-detect the file"
            )

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
