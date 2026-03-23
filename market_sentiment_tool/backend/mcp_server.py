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

from dotenv import load_dotenv
from fastmcp import FastMCP
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from supabase import create_client, Client as SupabaseClient

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

alpaca: TradingClient | None = None
supa: SupabaseClient | None = None

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

