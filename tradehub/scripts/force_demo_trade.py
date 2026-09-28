from __future__ import annotations

import argparse
import os
from pathlib import Path

from tradehub.core.env import load_local_env

REPO_ROOT = Path(__file__).resolve().parents[2]

# `market_sentiment_tool.backend.mcp_server` is a heavy import (FastMCP server
# construction, Supabase client). It is resolved on first access via the module
# `__getattr__` below -- `force_demo_trade.submit_kalshi_order` still works for
# callers and tests, but only after something actually asks for it, so importing
# this module stays cheap and side-effect free. See `tradehub.core.env`.
_LAZY = {"submit_kalshi_order": ("market_sentiment_tool.backend.mcp_server", "submit_kalshi_order")}


def __getattr__(name: str):
    try:
        module_path, attr = _LAZY[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    import importlib
    value = getattr(importlib.import_module(module_path), attr)
    globals()[name] = value
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Submit a one-off Kalshi demo order against a known ticker.",
    )
    parser.add_argument("ticker", help="Kalshi market ticker to trade")
    parser.add_argument("side", help="YES or NO")
    return parser.parse_args()


def main() -> int:
    load_local_env()
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
    result = globals()["submit_kalshi_order"](
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
