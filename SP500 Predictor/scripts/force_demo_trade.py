from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from market_sentiment_tool.backend.mcp_server import submit_kalshi_order


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit a one-off Kalshi demo order against a known ticker.",
    )
    parser.add_argument("ticker", help="Kalshi market ticker to trade")
    parser.add_argument("side", help="YES or NO")
    return parser.parse_args()


def main() -> int:
    load_dotenv(REPO_ROOT / ".env")
    args = _parse_args()

    if os.getenv("KALSHI_ENV", "").strip().lower() != "demo":
        print("ERROR: force_demo_trade.py is only allowed when KALSHI_ENV=demo.")
        return 2

    side = str(args.side or "").strip().upper()
    if side not in {"YES", "NO"}:
        print("ERROR: side must be YES or NO.")
        return 2

    ticker = str(args.ticker or "").strip()
    if not ticker:
        print("ERROR: ticker is required.")
        return 2

    print(f"Submitting forced demo order: ticker={ticker} side={side} count=1")
    result = submit_kalshi_order(
        ticker=ticker,
        side=side.lower(),
        action="buy",
        count=1,
        limit_price_dollars="0.5000",
    )

    status = str((result or {}).get("status") or "").lower()
    if status in {"ok", "accepted", "pending", "placed"}:
        print("SUCCESS:", result)
        return 0

    print("FAILURE:", result)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
