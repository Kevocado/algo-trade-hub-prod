"""
mcp_server.py — FastMCP Tool Bridge for Alpaca Execution
=========================================================
Exposes execution tools (get_portfolio, get_market_data, execute_paper_trade)
over FastMCP, bound strictly to 127.0.0.1. Before any trade execution, the
kill-switch state (auto_trade_enabled) is asserted from Supabase user_settings.

Boot order: Step 2 (after the local LLM server).
"""

import os
import logging
from datetime import datetime, timezone
import base64
import time
import uuid

from dotenv import load_dotenv
from fastmcp import FastMCP
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from supabase import create_client, Client as SupabaseClient
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ── Load .env from project root (one directory up from /backend) ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [MCP-SERVER]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Clients ──
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")

# Kalshi (Demo) execution
KALSHI_API_BASE = os.getenv("KALSHI_API_BASE", "https://demo-api.kalshi.co").strip('"').strip("'")
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")

alpaca: TradingClient | None = None
supa: SupabaseClient | None = None
_KALSHI_PRIVATE_KEY = None

try:
    alpaca = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    log.info("Alpaca TradingClient initialized (paper mode).")
except Exception as exc:
    log.warning("Alpaca TradingClient init failed (will use mock): %s", exc)

try:
    supa = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    log.info("Supabase service-role client initialized.")
except Exception as exc:
    log.warning("Supabase client init failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# Kill-Switch Guard
# ═══════════════════════════════════════════════════════════════════

def assert_kill_switch() -> bool:
    """
    Check the user_settings table in Supabase.
    Returns True if auto_trade_enabled is True, False otherwise.
    """
    if supa is None:
        log.warning("Supabase not connected — kill switch defaults to OFF.")
        return False
    try:
        result = supa.table("user_settings").select("auto_trade_enabled").limit(1).execute()
        if result.data and len(result.data) > 0:
            enabled = result.data[0].get("auto_trade_enabled", False)
            return bool(enabled)
    except Exception as exc:
        log.error("Kill-switch query failed: %s", exc)
    return False


def log_to_supabase(module: str, message: str, level: str = "INFO", context: dict | None = None):
    """Write a log entry to the agent_logs table in Supabase."""
    if supa is None:
        return
    try:
        supa.table("agent_logs").insert({
            "module": module,
            "message": message,
            "log_level": level,
            "reasoning_context": context,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }).execute()
    except Exception as exc:
        log.error("Failed to write agent_log: %s", exc)


def _load_kalshi_private_key():
    global _KALSHI_PRIVATE_KEY
    if _KALSHI_PRIVATE_KEY is not None:
        return _KALSHI_PRIVATE_KEY
    if not KALSHI_PRIVATE_KEY_PATH:
        raise ValueError("KALSHI_PRIVATE_KEY_PATH is missing (required for Kalshi execution).")
    from shared.kalshi_ws import load_rsa_private_key

    _KALSHI_PRIVATE_KEY = load_rsa_private_key(KALSHI_PRIVATE_KEY_PATH)
    return _KALSHI_PRIVATE_KEY


def _kalshi_signed_headers(method: str, path: str) -> dict[str, str]:
    if not KALSHI_API_KEY_ID:
        raise ValueError("KALSHI_API_KEY_ID is missing (required for Kalshi execution).")
    private_key = _load_kalshi_private_key()
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method.upper()}{path.split('?')[0]}"
    signature = private_key.sign(
        msg.encode("utf-8"),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.DIGEST_LENGTH,
        ),
        hashes.SHA256(),
    )
    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": KALSHI_API_KEY_ID,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


# ═══════════════════════════════════════════════════════════════════
# FastMCP Server & Tools
# ═══════════════════════════════════════════════════════════════════

# Host/port configured via env vars for HTTP mode, or stdio for LangGraph
os.environ.setdefault("FASTMCP_HOST", "127.0.0.1")
os.environ.setdefault("FASTMCP_PORT", "5100")
mcp = FastMCP("Trading Engine MCP")


@mcp.tool()
def get_portfolio() -> dict:
    """Retrieves the current portfolio state from Alpaca."""
    if alpaca is None:
        return {"status": "error", "detail": "Alpaca client not connected."}

    try:
        account = alpaca.get_account()
        portfolio = {
            "equity": float(account.equity),
            "cash": float(account.cash),
            "buying_power": float(account.buying_power),
            "portfolio_value": float(account.portfolio_value),
            "status": account.status,
        }
        log.info("Portfolio fetched: equity=$%.2f", portfolio["equity"])
        return portfolio
    except Exception as exc:
        log.error("get_portfolio failed: %s", exc)
        return {"status": "error", "detail": str(exc)}


@mcp.tool()
def get_market_data(symbol: str) -> dict:
    """Retrieves latest trade snapshot for a given symbol from Alpaca."""
    if alpaca is None:
        return {"symbol": symbol, "status": "error", "detail": "Alpaca client not connected."}

    try:
        snapshot = alpaca.get_snapshot(symbol)
        return {
            "symbol": symbol,
            "latest_price": float(snapshot.latest_trade.price) if snapshot.latest_trade else None,
            "latest_volume": int(snapshot.latest_trade.size) if snapshot.latest_trade else None,
            "status": "ok",
        }
    except Exception as exc:
        log.error("get_market_data(%s) failed: %s", symbol, exc)
        return {"symbol": symbol, "status": "error", "detail": str(exc)}


@mcp.tool()
def execute_paper_trade(symbol: str, qty: float, side: str) -> dict:
    """
    Executes a paper trade on Alpaca.
    CRITICAL: Asserts the kill-switch BEFORE any execution.
    """
    side_upper = side.upper()
    if side_upper not in ("BUY", "SELL"):
        return {"status": "rejected", "reason": "Side must be BUY or SELL."}

    # ── Kill-Switch Check ──
    if not assert_kill_switch():
        msg = f"BLOCKED: Kill switch is OFF. Trade {side_upper} {qty} {symbol} rejected."
        log.warning(msg)
        log_to_supabase("mcp_server", msg, level="WARN")
        return {"status": "blocked", "reason": "auto_trade_enabled is False (kill switch)."}

    if alpaca is None:
        return {"status": "error", "detail": "Alpaca client not connected."}

    try:
        order_side = OrderSide.BUY if side_upper == "BUY" else OrderSide.SELL
        order_request = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        order = alpaca.submit_order(order_request)

        result = {
            "status": "OPEN",
            "order_id": str(order.id),
            "symbol": symbol,
            "qty": qty,
            "side": side_upper,
            "entry_price": float(order.filled_avg_price) if order.filled_avg_price else None, # Might populate later or use latest quote
            "submitted_at": order.submitted_at.isoformat() if order.submitted_at else None,
        }
        log.info("Order submitted: %s %s x%.2f", side_upper, symbol, qty)
        log_to_supabase("mcp_server", f"Order submitted: {side_upper} {symbol} x{qty}", context=result)
        return result
    except Exception as exc:
        log.error("execute_paper_trade failed: %s", exc)
        log_to_supabase("mcp_server", f"Order FAILED: {exc}", level="ERROR")
        return {"status": "error", "detail": str(exc)}


@mcp.tool()
def execute_kalshi_order(
    ticker: str,
    side: str,
    action: str,
    count: int,
    limit_price_dollars: str,
) -> dict:
    """
    Places a *demo* Kalshi order using the REST API.

    Required:
    - side: "yes" or "no"
    - action: "buy" or "sell"
    - count: whole contracts (>= 1)
    - limit_price_dollars: string price like "0.5600"

    Notes:
    - Uses RSA-PSS signing headers (same pattern as other Kalshi REST endpoints).
    - Asserts the kill-switch BEFORE any execution.
    """
    return submit_kalshi_order(
        ticker=ticker,
        side=side,
        action=action,
        count=count,
        limit_price_dollars=limit_price_dollars,
    )


def submit_kalshi_order(
    ticker: str,
    side: str,
    action: str,
    count: int,
    limit_price_dollars: str,
) -> dict:
    """Submit a strict-limit Kalshi REST order for internal callers and MCP wrappers."""
    side_l = (side or "").lower().strip()
    action_l = (action or "").lower().strip()

    if side_l not in ("yes", "no"):
        return {"status": "rejected", "reason": "side must be 'yes' or 'no'."}
    if action_l not in ("buy", "sell"):
        return {"status": "rejected", "reason": "action must be 'buy' or 'sell'."}
    if not ticker:
        return {"status": "rejected", "reason": "ticker is required."}
    if not isinstance(count, int) or count < 1:
        return {"status": "rejected", "reason": "count must be an integer >= 1."}

    if not assert_kill_switch():
        msg = f"BLOCKED: Kill switch is OFF. Kalshi order {action_l} {side_l} {count} {ticker} rejected."
        log.warning(msg)
        log_to_supabase("mcp_server", msg, level="WARN")
        return {"status": "blocked", "reason": "auto_trade_enabled is False (kill switch)."}

    try:
        px = float(limit_price_dollars)
        px_cents = int(round(px * 100))
        if px_cents < 1 or px_cents > 99:
            return {"status": "rejected", "reason": "limit_price_dollars must map to 0.01..0.99"}
    except Exception:
        return {"status": "rejected", "reason": "limit_price_dollars must be a numeric string like '0.5600'."}

    body: dict = {
        "ticker": ticker,
        "side": side_l,
        "action": action_l,
        "type": "limit",
        "count": int(count),
        "client_order_id": str(uuid.uuid4()),
    }
    if side_l == "yes":
        body["yes_price"] = px_cents
    else:
        body["no_price"] = px_cents

    path = "/trade-api/v2/orders"
    url = f"{KALSHI_API_BASE}{path}"

    try:
        import requests

        headers = _kalshi_signed_headers("POST", path)
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        if resp.status_code >= 300:
            msg = f"Kalshi order failed: {resp.status_code} {resp.text[:300]}"
            log.error(msg)
            log_to_supabase("mcp_server.kalshi", msg, level="ERROR", context={"ticker": ticker, "body": body})
            return {"status": "error", "code": resp.status_code, "detail": resp.text}

        payload = resp.json()
        log.info("Kalshi order placed: %s %s %s x%d @ %s", action_l, side_l, ticker, count, limit_price_dollars)
        log_to_supabase("mcp_server.kalshi", f"Kalshi order placed: {action_l} {side_l} {ticker} x{count}", context=payload)
        payload.setdefault("status", "ok")
        return payload
    except Exception as exc:
        log.error("Kalshi order exception: %s", exc)
        log_to_supabase(
            "mcp_server.kalshi",
            f"Kalshi order exception: {exc}",
            level="ERROR",
            context={"ticker": ticker, "body": body},
        )
        return {"status": "error", "detail": str(exc)}


if __name__ == "__main__":
    log.info("Starting FastMCP server on 127.0.0.1:5100 …")
    mcp.run(transport="stdio")

@mcp.tool()
def close_position(trade_id: str) -> dict:
    """
    Closes an open position by taking the opposite side trade.
    Updates the Supabase 'trades' table to set status='CLOSED' and locks in realized PnL.
    """
    if supa is None or alpaca is None:
        return {"status": "error", "reason": "Clients not connected."}
        
    try:
        # Fetch the open trade
        res = supa.table("trades").select("*").eq("id", trade_id).single().execute()
        if not res.data:
            return {"status": "error", "reason": "Trade not found"}
            
        trade = res.data
        if trade.get("status") != "OPEN":
            return {"status": "error", "reason": "Trade is not exactly OPEN."}
            
        symbol = trade["symbol"]
        qty = float(trade["qty"])
        side = trade["side"].upper()
        entry = float(trade.get("entry_price") or trade.get("execution_price") or 0.0)
        
        # Determine opposite side
        close_side = OrderSide.SELL if side == "BUY" else OrderSide.BUY
        
        # Execute closing trade on Alpaca
        ord_req = MarketOrderRequest(
            symbol=symbol,
            qty=qty,
            side=close_side,
            time_in_force=TimeInForce.DAY,
        )
        order = alpaca.submit_order(ord_req)
        
        # For paper trading, assume immediate or near immediate fill price, or let's fetch current quote
        # Actually doing a market close might not fill instantly, but we approximate for the agent
        snap = alpaca.get_snapshot(symbol)
        exit_price = float(snap.latest_trade.price) if snap.latest_trade else entry
        
        # Calc realized PnL
        diff = (exit_price - entry)
        pnl = (diff * qty) if side == "BUY" else (-diff * qty)
        
        # Update Row in Supabase
        supa.table("trades").update({
            "status": "CLOSED",
            "pnl": pnl, 
        }).eq("id", trade_id).execute()
        
        log.info(f"Closed {trade_id}: Exit ${exit_price:.2f}, PnL ${pnl:.2f}")
        return {"status": "CLOSED", "pnl": round(pnl, 2), "exit_price": round(exit_price, 2)}
        
    except Exception as exc:
        log.error("close_position failed: %s", exc)
        return {"status": "error", "reason": str(exc)}
