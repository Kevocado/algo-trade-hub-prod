"""
Supabase Client — Thin CRUD wrapper for the trade hub.

Replaces Azure TableClient/BlobServiceClient for all live app state.
Uses the supabase-py SDK with the service role key for server-side writes.
"""

import os
from datetime import datetime, timezone

from tradehub.quarantine import (
    KIND_OPPORTUNITY,
    QUARANTINE_FLAG,
    QUARANTINE_MARK,
    QUARANTINE_NOTE,
    forecast_key,
    is_quarantined_row,
    normalize_edge_type,
)

# NOTE: no `load_dotenv()` here, on purpose. Importing this module must not
# touch `os.environ` -- see `tradehub.core.env`. Credentials come from the
# process environment; entrypoints opt into the developer-local `.env`
# explicitly via `load_local_env()`.
#
# They are also read at call time rather than bound at import time, so that a
# caller which loads its environment after importing this module still gets the
# right values. Nothing outside this module referenced these two names.
_client = None


def supabase_url() -> str:
    return os.getenv("SUPABASE_URL", "").strip('"').strip("'")


def supabase_key() -> str:
    return os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip('"').strip("'")


def get_client():
    """Lazy-init Supabase client singleton."""
    global _client
    if _client is None:
        url, key = supabase_url(), supabase_key()
        if not url or not key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set (environment or .env)")
        from supabase import create_client
        _client = create_client(url, key)
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
    """Upsert opportunities into the new unified kalshi_edges Supabase table.

    **Refuses quarantined rows.** The Weather and Macro real-edge engines are repaired and running
    (`tradehub/quarantine.py`), they produce real output, and none of it is allowed to reach this
    table until the owner rules on whether it should. They mark every row they produce with
    `QUARANTINE_FLAG`, and this function drops any row carrying that mark before building a payload.

    The flag is the mechanism rather than a check on `edge_type`, and it has to be: this writer is
    shared with `tradehub/scripts/scan.py`, whose measured `weather` engine and macro ladder engine
    publish to the SAME two edge types and must keep doing so. A sink that refused `WEATHER` and
    `MACRO` to protect a ruling about two other engines that share those boards would be refusing the
    product's working engines. The flag can only be set by the path that is meant to be quarantined
    -- it is written in exactly one place -- so dropping on it cannot be evaded by a caller and
    cannot be tripped by one either.

    It is a DROP and not a raise, deliberately. This is a shared writer on the scan path: one row
    that ought to be somewhere else must not take the crypto and sports rows down with it. The
    refusal is loud -- it is printed, and the return value is the number dropped -- because a
    silent drop of the thing the whole quarantine exists to prevent is the defect this PR is about,
    reproduced one layer down. `tests/test_weather_macro_quarantine.py` pins that a quarantined row
    handed to this function produces zero writes.

    Returns the number of rows dropped, so the caller can log the refusal instead of inferring it.
    """
    dropped = [op for op in opportunities if is_quarantined_row(op)]
    opportunities = [op for op in opportunities if not is_quarantined_row(op)]
    if dropped:
        print(
            f"  ⛔ QUARANTINE: refused {len(dropped)} row(s) from the trade sink. "
            f"Marked '{QUARANTINE_FLAG}' rows are measured and written to "
            f"kalshi_quarantine_edges instead, and never to kalshi_edges."
        )
    if not opportunities:
        return len(dropped)
    client = get_client()
    # De-duplicate rows by market_id to avoid Supabase 500 error
    unique_rows = {}
    for op in opportunities:
        # Standardize the mapping
        title = op.get("market_title") or op.get("Market") or op.get("title") or "Unknown Market"
        market_id = op.get("market_id") or op.get("market_ticker") or op.get("RowKey") or f"GEN_{title.replace(' ','_').upper()}"
        market_id = str(market_id)[:50]
        
        # Determine market probabilities
        market_prob = op.get("market_price", op.get("MarketYesAsk", op.get("kalshi_price", 50)))
        if market_prob > 1: market_prob = market_prob / 100.0
        
        our_prob = op.get("model_probability", op.get("ModelPred", op.get("model_prob", 50)))
        if our_prob > 1: our_prob = our_prob / 100.0
        
        edge_pct = op.get("edge", op.get("Edge", op.get("edge_pct", 0)))
        if edge_pct > 1 or edge_pct < -1: edge_pct = edge_pct / 100.0
        
        engine = str(op["engine"]).strip().lower() if op.get("engine") else None
        edge_type = op.get("edge_type", "MACRO").upper()
        if edge_type not in ["WEATHER", "MACRO", "SPORTS", "CRYPTO", "ENERGY"]:
            edge_type = "MACRO"
        gate_status = str(op.get("gate_status", "SHADOW")).upper()
        if gate_status not in {"SHADOW", "PROMOTED"}:
            gate_status = "SHADOW"
        updated_at = op.get("updated_at") or datetime.now(timezone.utc).isoformat()

        row = {
            "market_id": market_id,
            "title": title,
            "engine": engine,
            "edge_type": edge_type,
            "our_prob": round(float(our_prob), 4),
            "market_prob": round(float(market_prob), 4),
            "edge_pct": round(float(abs(edge_pct)), 4),
            "market_url": op.get("market_url"),
            "source_url": op.get("source_url"),
            "gate_status": gate_status,
            "updated_at": updated_at,
            "expires_at": op.get("expires_at"),
            "raw_payload": op
        }
        # Game start as its own indexed column (sports edges). expires_at is the Kalshi close
        # time, which for a sports market is ~2 days AFTER kickoff, so nothing could be deleted
        # or filtered by "has this game started" without this column.
        #
        # Sent ONLY when the engine set it. This writer is shared by every engine, and PostgREST
        # rejects a payload containing a column the table does not have, so always sending it made
        # a missing migration break weather and gas too, not just sports. Omitting the key also
        # leaves an existing row's value alone on conflict instead of nulling it.
        if op.get("start_utc"):
            row["start_utc"] = op["start_utc"]
        unique_rows[market_id] = row
        
    rows = list(unique_rows.values())
    client.table("kalshi_edges").upsert(rows, on_conflict="market_id").execute()
    return len(dropped)


# ── The quarantine sink ──────────────────────────────────────────────────────────────────────
#
# A second table, and the only place a quarantined row is allowed to land. It exists because PR #38's
# report said this "needs a real second sink, so it is a bigger change", and because the alternative
# is worse in both directions: not repairing the engines leaves the owner unable to see what they
# would do, and repairing them into `kalshi_edges` publishes 295 unvalidated rows a scan from a
# model with no measurement and no gate, which is a data-quality incident rather than a bug report.
#
# What it is NOT, on purpose: not a pipeline, not a queue, not a reconciliation system, and not a
# shadow-trading ledger. Nothing reads it to place an order, nothing settles it, and it feeds no
# scoreboard. It is a measurement surface -- the place a row goes so that the owner can look at it
# and decide -- and it stays that small because anything larger would start accruing state that
# somebody later mistakes for a track record.

def upsert_quarantined(rows: list):
    """Write quarantined rows to `kalshi_quarantine_edges`. Never to `kalshi_edges`.

    Every row written here is stamped three ways, so it cannot be mistaken for a live edge if it is
    read out of context: a literal `quarantined` boolean, the `QUARANTINE_MARK` word, and the note
    explaining what it means. The classification travels too -- `edge_kind`, `independent`, and the
    `forecast_key` a row shares with its restatements -- because a table of 295 rows with no way to
    tell a units artefact from an independent opinion is the same unreadable number the surface was
    built to replace.

    `price_cents` and `model_probability_pct` are stored as the engines produced them, in cents and
    percentage points, rather than rescaled into 0-1 the way `kalshi_edges` stores probabilities. The
    two tables are read by different things and mixing the two conventions is how a 29c quote becomes
    a 0.29% one.

    Returns the number of rows written. A missing figure on a row is stored as NULL, never 0: a row
    that recorded no price has no price, and writing 0 would put a fabricated zero into a table whose
    entire purpose is to hold numbers that were really measured.
    """
    if not rows:
        return 0
    client = get_client()

    written: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not is_quarantined_row(row):
            continue
        title = row.get("market_title") or row.get("title") or "Unknown Market"
        market_id = str(
            row.get("market_id") or row.get("market_ticker") or f"GEN_{title.replace(' ', '_').upper()}"
        )[:50]
        key = forecast_key(row)
        written[market_id] = {
            "market_id": market_id,
            "title": title,
            "engine": _opt_text(row.get("engine")),
            "edge_type": normalize_edge_type(row.get("edge_type")),
            "action": _opt_text(row.get("action")),
            "market_ticker": _opt_text(row.get("market_ticker")),
            "event_ticker": _opt_text(row.get("event_ticker")),
            # Cents, and NULL when there is none. Never 0 -- see the docstring.
            "price_cents": _opt_number(row.get("market_price")),
            "model_probability_pct": _opt_number(row.get("model_probability")),
            "edge_points": _opt_number(row.get("edge")),
            "edge_kind": row.get("edge_kind") or KIND_OPPORTUNITY,
            "independent": bool(row.get("independent", True)),
            "forecast_key": " | ".join(part for part in key if part) or None,
            "reasoning": _opt_text(row.get("reasoning")),
            "kalshi_url": _opt_text(row.get("kalshi_url")),
            "quarantined": True,
            "marker": QUARANTINE_MARK,
            "note": QUARANTINE_NOTE,
            "updated_at": row.get("updated_at") or datetime.now(timezone.utc).isoformat(),
        }

    if not written:
        return 0
    client.table("kalshi_quarantine_edges").upsert(
        list(written.values()), on_conflict="market_id"
    ).execute()
    return len(written)


def _opt_text(value) -> str | None:
    return value if isinstance(value, str) and value else None


def _opt_number(value) -> float | None:
    """A real number or `None`. A missing figure is never a number, and this table is the one place
    that rule has to be enforced rather than assumed -- it exists to hold measured figures, so a
    fabricated 0 in it would be the whole defect again, quieter."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


# ── Signal Ledger (cross-domain shadow-validation log) ────────────────
#
# Mirrors how the crypto worker logs to signal_events, so
# shadow_performance.py-style scoring (Brier score, calibration, hit rate)
# can eventually be extended to football and NBA the same way it already
# works for crypto. This function only logs the signal at detection time;
# it does not settle/score outcomes — that requires fetching finished match
# results (football-data.org) or box scores (BallDontLie) and is tracked as
# a follow-up, not implemented here.

def log_signal_event(
    *,
    domain: str,
    asset: str,
    source_market_ticker: str = "",
    desired_side: str = "",
    model_probability_yes: float | None = None,
    kalshi_price_dollars: float | None = None,
    edge: float | None = None,
    payload: dict | None = None,
):
    """Insert one row into the shared signal_events ledger for a non-crypto domain."""
    client = get_client()
    client.table("signal_events").insert({
        "domain": domain,
        "asset": asset,
        "source_market_ticker": source_market_ticker or "",
        "desired_side": desired_side or "",
        "status": "signal_detected",
        "model_probability_yes": model_probability_yes,
        "kalshi_price_dollars": kalshi_price_dollars,
        "edge": edge,
        "payload": payload or {},
    }).execute()


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

def upsert_kalshi_portfolio(summary: dict):
    """Upsert Kalshi portfolio summary into Supabase."""
    if not summary:
        return
    client = get_client()
    
    row = {
        "id": "MAIN_ACCOUNT", # Hardcoded for now as we likely have one main account
        "balance": summary.get("balance", 0),
        "portfolio_value": summary.get("portfolio_value", 0),
        "total_invested": summary.get("total_invested", 0),
        "total_pnl": summary.get("total_pnl", 0),
        "wins": summary.get("wins", 0),
        "losses": summary.get("losses", 0),
        "open_positions": summary.get("positions", []),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    
    try:
        client.table("kalshi_portfolio").upsert(row, on_conflict="id").execute()
    except Exception as e:
        print(f"Failed to upsert kalshi_portfolio: {e}")


def upsert_portfolio_metrics(metrics: dict):
    """Upsert live portfolio metrics into portfolio_metrics table (id=1)."""
    client = get_client()
    row = {
        "id": 1,
        "total_value": metrics.get("total_value", 0),
        "daily_pnl": metrics.get("daily_pnl", 0),
        "cash_balance": metrics.get("cash_balance", 0),
        "updated_at": datetime.now(timezone.utc).isoformat()
    }
    try:
        client.table("portfolio_metrics").upsert(row).execute()
    except Exception as e:
        print(f"Failed to upsert portfolio_metrics: {e}")


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
        print(f"  ✅ Connected to {supabase_url()}")
        # Quick read test
        result = c.table("scanner_runs").select("*").limit(1).execute()
        print(f"  ✅ Read test passed ({len(result.data)} rows)")
    except Exception as e:
        print(f"  ❌ Connection failed: {e}")
