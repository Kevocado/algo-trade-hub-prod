"""
Supabase Client — Thin CRUD wrapper for the SP500 Predictor.

Replaces Azure TableClient/BlobServiceClient for all live app state.
Uses the supabase-py SDK with the service role key for server-side writes.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip('"').strip("'")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip('"').strip("'")

_client = None


def get_client():
    """Lazy-init Supabase client singleton."""
    global _client
    if _client is None:
        if not SUPABASE_URL or not SUPABASE_KEY:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env")
        from supabase import create_client
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ── Live Opportunities ──────────────────────────────────────────────

def insert_opportunities(run_id: str, opportunities: list):
    """Batch-insert scanner opportunities."""
    if not opportunities:
        return
    client = get_client()
    rows = []
    for opp in opportunities:
        rows.append({
            "run_id": run_id,
            "engine": opp.get("engine", "Unknown"),
            "asset": opp.get("asset", ""),
            "market_title": opp.get("market_title", ""),
            "market_ticker": opp.get("market_ticker", ""),
            "event_ticker": opp.get("event_ticker", ""),
            "action": opp.get("action", ""),
            "model_prob": opp.get("model_probability", 0),
            "market_price": opp.get("market_price", 0),
            "edge": opp.get("edge", 0),
            "confidence": opp.get("confidence", 0),
            "reasoning": opp.get("reasoning", ""),
            "data_source": opp.get("data_source", ""),
            "kalshi_url": opp.get("kalshi_url", ""),
            "market_date": opp.get("market_date", ""),
            "expiration": opp.get("expiration", ""),
            "ai_approved": opp.get("ai_approved", True),
            "ai_reasoning": opp.get("ai_reasoning", ""),
        })
    client.table("live_opportunities").insert(rows).execute()

def upsert_opportunities(opportunities: list):
    """Upsert opportunities into the new unified kalshi_edges Supabase table."""
    if not opportunities:
        return
    client = get_client()
    rows = []
    for op in opportunities:
        # Standardize the mapping from our various python engine schemas to kalshi_edges schema
        title = op.get("market_title") or op.get("Market") or "Unknown Market"
        
        # Determine market probabilities
        # Some engines use MarketPrice, MarketYesAsk, some use kalshi_price
        market_prob = op.get("market_price", op.get("MarketYesAsk", op.get("kalshi_price", 50)))
        # Make sure it's 0-1 scale if it's currently 0-100
        if market_prob > 1: market_prob = market_prob / 100.0
        
        our_prob = op.get("model_probability", op.get("ModelPred", op.get("model_prob", 50)))
        if our_prob > 1: our_prob = our_prob / 100.0
        
        edge_pct = op.get("edge", op.get("Edge", op.get("edge_pct", 0)))
        if edge_pct > 1 or edge_pct < -1: edge_pct = edge_pct / 100.0
        
        # Enforce edge_type constraints
        edge_type = op.get("edge_type", "MACRO").upper()
        if edge_type not in ["WEATHER", "MACRO", "SPORTS", "CRYPTO"]:
            edge_type = "MACRO"
            
        rows.append({
            "market_id": op.get("market_ticker", op.get("RowKey", f"GEN_{title.replace(' ','_').upper()}[:30]")),
            "title": title,
            "edge_type": edge_type,
            "our_prob": round(float(our_prob), 4),
            "market_prob": round(float(market_prob), 4),
            "edge_pct": round(float(abs(edge_pct)), 4),
            "reasoning": str(op.get("reasoning", op.get("Reasoning", ""))),
            "raw_payload": op
        })
        
    try:
        # We can perform an upsert if market_id is unique
        client.table("kalshi_edges").upsert(rows, on_conflict="market_id").execute()
    except Exception as e:
        print(f"Failed to upsert kalshi_edges: {e}")


def get_latest_opportunities(limit=50):
    """Fetch the most recent opportunities."""
    client = get_client()
    result = client.table("live_opportunities") \
        .select("*") \
        .order("created_at", desc=True) \
        .limit(limit) \
        .execute()
    return result.data


# ── Paper Signals ───────────────────────────────────────────────────

def insert_paper_signal(run_id: str, signal: dict):
    """Insert a single Quant ML paper trade signal."""
    client = get_client()
    client.table("paper_signals").insert({
        "run_id": run_id,
        "ticker": signal.get("ticker", ""),
        "predicted_price": signal.get("predicted_price", 0),
        "current_price": signal.get("current_price", 0),
        "direction": signal.get("direction", ""),
        "model_prob": signal.get("model_prob", 0),
        "kelly_bet": signal.get("kelly_bet", 0),
        "edge": signal.get("edge", 0),
        "rmse": signal.get("rmse", 0),
    }).execute()


# ── Trade History ───────────────────────────────────────────────────

def insert_trade_log(log: dict):
    """Log a prediction for backtesting."""
    client = get_client()
    client.table("trade_history").insert({
        "ticker": log.get("ticker", ""),
        "predicted_price": log.get("predicted_price", 0),
        "current_price": log.get("current_price", 0),
        "actual_price": log.get("actual_price"),
        "model_rmse": log.get("model_rmse", 0),
        "best_edge": log.get("best_edge", 0),
        "best_action": log.get("best_action", ""),
        "best_strike": log.get("best_strike", ""),
        "brier_score": log.get("brier_score"),
        "pnl_cents": log.get("pnl_cents"),
    }).execute()


def get_trade_history(ticker=None, limit=200):
    """Fetch trade history, optionally filtered by ticker."""
    client = get_client()
    q = client.table("trade_history").select("*").order("created_at", desc=True).limit(limit)
    if ticker:
        q = q.eq("ticker", ticker)
    return q.execute().data


# ── Scanner Runs ────────────────────────────────────────────────────

def start_run(run_id: str, engines: list):
    """Record the start of a scanner run."""
    client = get_client()
    client.table("scanner_runs").insert({
        "run_id": run_id,
        "status": "running",
        "engines_run": engines,
    }).execute()


def complete_run(run_id: str, total_opps: int, duration_sec: float, error_msg=None):
    """Mark a scanner run as completed or failed."""
    client = get_client()
    status = "failed" if error_msg else "completed"
    client.table("scanner_runs").update({
        "status": status,
        "total_opps": total_opps,
        "duration_sec": round(duration_sec, 2),
        "error_msg": error_msg,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }).eq("run_id", run_id).execute()


def get_wipe_date():
    """Get the most recent hard-reset wipe date, if any."""
    client = get_client()
    result = client.table("scanner_runs") \
        .select("wipe_date") \
        .not_.is_("wipe_date", "null") \
        .order("created_at", desc=True) \
        .limit(1) \
        .execute()
    if result.data:
        return result.data[0].get("wipe_date")
    return None


if __name__ == "__main__":
    print("Testing Supabase connection...")
    try:
        c = get_client()
        print(f"  ✅ Connected to {SUPABASE_URL}")
        # Quick read test
        result = c.table("scanner_runs").select("*").limit(1).execute()
        print(f"  ✅ Read test passed ({len(result.data)} rows)")
    except Exception as e:
        print(f"  ❌ Connection failed: {e}")
