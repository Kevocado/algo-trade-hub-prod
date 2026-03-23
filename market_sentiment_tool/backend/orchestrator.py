"""
orchestrator.py — LangGraph Continuous Orchestration Engine
============================================================
Core state machine running in a continuous heartbeat loop. Polls the local
SQLite WAL for fresh tick data, runs the Quant → Sentiment → Risk → Execute
pipeline, and writes results to Supabase (trades, agent_logs, portfolio_state).

Boot order: Step 4 (after ingestion.py is streaming).
"""

import asyncio
import json
import os
import sqlite3
import logging
from datetime import datetime, timezone
from typing import TypedDict

import aiohttp
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from supabase import create_client, Client as SupabaseClient

from quant_engine import analyze_all_symbols
from news_rag import query_news  # pgvector-backed semantic search

# ── Load .env from project root (one directory up from /backend) ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

# ── Config ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
LOCAL_LLM_ENDPOINT = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:8080/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL_NAME", "GLM-5-MXFP4")
HEARTBEAT_SECONDS = 10  # How often the orchestrator polls for new ticks
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_ticks.sqlite3")


# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [ORCHESTRATOR]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Supabase Client (Service Role — bypasses RLS) ──
supa: SupabaseClient | None = None
USER_ID = None

# ── pgvector RAG is handled via news_rag.query_news() — no local DB client needed ──

try:
    supa = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
    log.info("Supabase service-role client initialized.")
    
    # ── Fetch User ID for RLS Bypass ──
    # The frontend logs in as sigey2@illinois.edu. We need this UUID to insert rows
    # so they pass Row Level Security (RLS) policies and appear in the UI.
    TARGET_EMAIL = "sigey2@illinois.edu"
    try:
        users = supa.auth.admin.list_users()
        for u in users:
            if u.email == TARGET_EMAIL:
                USER_ID = u.id
                log.info("Found USER_ID for %s: %s", TARGET_EMAIL, USER_ID)
                break
        
        if not USER_ID:
            log.warning("User %s not found. Inserts will lack user_id and may be hidden by RLS.", TARGET_EMAIL)
    except Exception as e:
        log.error("Failed to query user UUID: %s", e)

except Exception as exc:
    log.warning("Supabase client init failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# Supabase Helpers
# ═══════════════════════════════════════════════════════════════════

def log_to_supabase(module: str, message: str, level: str = "INFO", context: dict | None = None):
    """Insert a log row into agent_logs."""
    if supa is None:
        return
    
    payload = {
        "module": module,
        "message": message,
        "log_level": level,
        "reasoning_context": context,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if USER_ID:
        payload["user_id"] = USER_ID

    try:
        supa.table("agent_logs").insert(payload).execute()
    except Exception as exc:
        log.error("agent_log insert failed: %s", exc)


def write_trade_to_supabase(trade: dict):
    """Insert a trade record into the trades table."""
    if supa is None:
        return
    
    payload = {
        "symbol": trade["symbol"],
        "side": trade.get("side"),
        "qty": trade.get("qty", 0),
        "execution_price": trade.get("execution_price"),
        "status": trade.get("status", "PENDING"),
        "agent_confidence": trade.get("agent_confidence"),
        "pnl": trade.get("pnl"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if USER_ID:
        payload["user_id"] = USER_ID

    try:
        supa.table("trades").insert(payload).execute()
    except Exception as exc:
        log.error("trade insert failed: %s", exc)


def update_portfolio_state(equity: float, cash: float, open_positions: list | dict):
    """Upsert the latest portfolio snapshot into portfolio_state."""
    if supa is None:
        return
    
    payload = {
        "total_equity": equity,
        "available_cash": cash,
        "open_positions": open_positions,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if USER_ID:
        payload["user_id"] = USER_ID

    try:
        supa.table("portfolio_state").insert(payload).execute()
    except Exception as exc:
        log.error("portfolio_state insert failed: %s", exc)


def check_kill_switch() -> bool:
    """Read user_settings.auto_trade_enabled from Supabase."""
    if supa is None:
        return False
    try:
        result = supa.table("user_settings").select("auto_trade_enabled").limit(1).execute()
        if result.data and len(result.data) > 0:
            return bool(result.data[0].get("auto_trade_enabled", False))
    except Exception as exc:
        log.error("Kill-switch query failed: %s", exc)
    return False


# ═══════════════════════════════════════════════════════════════════
# SQLite Tick Polling
# ═══════════════════════════════════════════════════════════════════

_last_tick_id = 0


def poll_latest_ticks(limit: int = 500) -> list[dict]:
    """Fetch new ticks from the SQLite WAL since the last poll (deeper lookback)."""
    global _last_tick_id
    try:
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        cursor = conn.execute(
            "SELECT id, symbol, price, size, timestamp FROM ticks "
            "WHERE id > ? ORDER BY id ASC LIMIT ?",
            (_last_tick_id, limit),
        )
        rows = [dict(r) for r in cursor.fetchall()]
        conn.close()
        if rows:
            _last_tick_id = max(r["id"] for r in rows)
        return rows
    except Exception as exc:
        log.error("SQLite poll failed: %s", exc)
        return []


def aggregate_market_snapshot(ticks: list[dict]) -> dict:
    """Build a simple market snapshot from recent ticks (latest price per symbol)."""
    snapshot: dict[str, dict] = {}
    for t in ticks:
        sym = t["symbol"]
        if sym not in snapshot:
            snapshot[sym] = {"symbol": sym, "price": t["price"], "volume": t["size"]}
        else:
            snapshot[sym]["volume"] += t["size"]
    return snapshot


# ═══════════════════════════════════════════════════════════════════
# LangGraph State & Nodes
# ═══════════════════════════════════════════════════════════════════

class AgentState(TypedDict):
    market_data: dict
    raw_ticks: list          # Raw tick dicts for the quant engine
    # Quant Output
    quant_signal: float
    quant_reasoning: str
    quant_context: dict      # Full institutional metrics (profile + flow)
    # Macro Output
    macro_signal: float
    macro_reasoning: str
    # CIO Output
    cio_decision: str        # 'BUY', 'SELL', 'HOLD', 'CLOSE'
    cio_reasoning: str
    target_symbol: str
    target_qty: float
    risk_approved: bool
    # Execution Output
    execution_result: dict


def quantitative_analysis(state: AgentState) -> dict:
    """
    Agent 1: The Quant Analyst.
    Institutional Volume Profile Skew + Flow Divergence.
    Outputs purely mathematical recommendation based on ticks.
    """
    raw_ticks = state.get("raw_ticks", [])
    quant_result = analyze_all_symbols(raw_ticks)
    aggregate = quant_result.get("aggregate", {})
    signal = aggregate.get("signal", 0.0)
    regime = aggregate.get("regime", "NO_DATA")
    n_symbols = aggregate.get("n_symbols", 0)

    per_symbol_summary = []
    for sym, data in quant_result.get("symbols", {}).items():
        vp = data.get("volume_profile", {})
        fd = data.get("flow_divergence", {})
        per_symbol_summary.append(
            f"{sym}: POC=${vp.get('poc', 0):.2f} Skew={vp.get('skewness', 0):.3f} "
            f"Regime={vp.get('regime', '?')} Δ={fd.get('delta', 0):+d} "
            + (f" ⚠ {fd.get('divergence_reason', '')}" if fd.get('divergence_warning') else "")
        )

    reasoning = (
        f"[QUANT AGENT] Mathematical Signal={signal:.3f}, Regime={regime}, "
        f"{n_symbols} symbols analyzed.\n" + "\n".join(per_symbol_summary)
    )
    log.info(reasoning)
    log_to_supabase("orchestrator.quant", reasoning, context=quant_result)
    
    return {
        "quant_signal": signal,
        "quant_reasoning": reasoning,
        "quant_context": quant_result,
    }

import requests

def _call_local_llm(prompt: str) -> str:
    """Sync POST request to local Ollama API."""
    payload = {
        "model": LOCAL_LLM_MODEL,
        "prompt": prompt,
        "stream": False
    }
    try:
        resp = requests.post(LOCAL_LLM_ENDPOINT, json=payload, timeout=12)
        if resp.status_code == 200:
            return resp.json().get("response", "0.0")
        else:
            log.error("LLM Server returned %s", resp.status_code)
            return "0.0"
    except Exception as e:
        log.error("LLM connection failed: %s", e)
        return "0.0"



def macro_sentiment(state: AgentState) -> dict:
    """
    Agent 2: The Macro Sentiment Analyst.
    Analyzes broader market environment (simulated via LLM prompt for now).
    """
    market = state.get("market_data", {})
    symbols = list(market.keys())[:5]
    
    news_context = "No recent specific news found."
    try:
        query_str = f"Market conditions, interest rates, and news for {', '.join(symbols)}"
        docs = query_news(query_str, n_results=3)
        if docs:
            news_context = "\n".join([f"- {doc}" for doc in docs])
    except Exception as e:
        log.warning("pgvector RAG query failed: %s", e)
    
    prompt = (
        "You are an elite Macroeconomic Sentiment Analyst. "
        f"The active market leaders are: {', '.join(symbols)}. "
        "Briefly assess the current macroeconomic environment risk based on this recent news:\n"
        f"{news_context}\n\n"
        "Respond ONLY with a single float between -1.0 (Risk-Off / Bearish) and 1.0 (Risk-On / Bullish) "
        "on the first line, followed by a one-sentence explanation."
    )

    try:
        llm_response = _call_local_llm(prompt)
    except Exception as e:
        log.error("Exception in macro_sentiment LLM call: %s", e)
        llm_response = "0.0 — Neutral fallback (LLM unavailable)."

    try:
        first_token = llm_response.strip().split()[0].rstrip(".,:;")
        sentiment = float(first_token)
        sentiment = min(max(sentiment, -1.0), 1.0)
    except (ValueError, IndexError):
        sentiment = 0.0

    reasoning = f"[MACRO AGENT] Sentiment={sentiment:.3f} | {llm_response[:200]}"
    log.info(reasoning)
    log_to_supabase("orchestrator.macro", reasoning)
    
    return {
        "macro_signal": sentiment,
        "macro_reasoning": reasoning,
    }


def cio_supervisor(state: AgentState) -> dict:
    """
    Agent 3: Chief Investment Officer (Supervisor).
    Debates findings from Quant and Macro, asserts risk/kill switches,
    and makes the final deterministic call (BUY, SELL, HOLD, or CLOSE).
    """
    quant_sig = state.get("quant_signal", 0.0)
    macro_sig = state.get("macro_signal", 0.0)
    quant_ctx = state.get("quant_context", {})
    market = state.get("market_data", {})
    
    combined = (quant_sig + macro_sig) / 2
    
    # Check Kill Switch
    kill_switch_on = check_kill_switch()
    
    # Check Divergence (Risk)
    any_divergence = any(
        sym_data.get("flow_divergence", {}).get("divergence_warning", False)
        for sym_data in quant_ctx.get("symbols", {}).values()
    )
    
    # Logic for CIO
    decision = "HOLD"
    target_sym = ""
    target_qty = 1.0
    approved = False
    
    if kill_switch_on:
        threshold = 0.5 if any_divergence else 0.3
        if combined > threshold:
            decision = "BUY"
            approved = True
        elif combined < -threshold:
            decision = "SELL"
            approved = True
            
        # Target biggest symbol by default paper trading 1 share
        if market:
            target_sym = max(market.items(), key=lambda x: x[1]['volume'])[0]
            
    reasoning = (
        f"[CIO AGENT] Consensus: Combined={combined:.3f} (Quant={quant_sig:.3f}, Macro={macro_sig:.3f}). "
        f"Divergence Risk={'⚠ YES' if any_divergence else 'NO'}. "
        f"Kill Switch={'ON' if kill_switch_on else 'OFF'}. "
        f"Decision: {decision} {target_sym}."
    )
    
    log.info(reasoning)
    log_to_supabase("orchestrator.cio", reasoning, level="WARN" if not approved else "INFO")
    
    return {
        "cio_decision": decision,
        "cio_reasoning": reasoning,
        "target_symbol": target_sym,
        "target_qty": target_qty,
        "risk_approved": approved
    }


def execute_trade(state: AgentState) -> dict:
    """
    Executes the CIO's decision by pushing trades to Supabase and tracking OPEN state.
    """
    decision = state.get("cio_decision", "HOLD")
    sym = state.get("target_symbol", "")
    qty = state.get("target_qty", 1.0)
    market = state.get("market_data", {})
    
    if not state.get("risk_approved") or decision == "HOLD":
        return {"execution_result": {"status": "skipped", "reason": "CIO elected to HOLD or risk blocked."}}
        
    price = market.get(sym, {}).get("price", 0.0)
    confidence = abs((state.get("quant_signal", 0.0) + state.get("macro_signal", 0.0)) / 2)

    # Note: FastMCP executing `execute_paper_trade` happens here or in the FastMCP server.
    # We will log the "OPEN" state to Supabase directly. 
    # (Alternatively, the LangGraph could call the FastMCP client, but we'll mock the write here for paper DB sync).
    
    trade_record = {
        "symbol": sym,
        "side": decision,
        "qty": qty,
        "execution_price": price,
        "entry_price": price,
        "status": "OPEN", # Now tracking trade duration
        "agent_confidence": round(confidence, 4),
        "pnl": 0.0,
    }
    
    # Actually trigger the write to the frontend state
    write_trade_to_supabase(trade_record)
    
    res = f"Executed: {decision} {qty}x {sym} @ ${price:.2f}"
    log.info(res)
    log_to_supabase("orchestrator.execute", res)
    
    return {"execution_result": trade_record}


# ═══════════════════════════════════════════════════════════════════
# Build the LangGraph Swarm
# ═══════════════════════════════════════════════════════════════════

def build_graph():
    workflow = StateGraph(AgentState)

    # 3-Agent Nodes
    workflow.add_node("quant_analyst", quantitative_analysis)
    workflow.add_node("macro_analyst", macro_sentiment)
    workflow.add_node("cio_supervisor", cio_supervisor)
    workflow.add_node("execute", execute_trade)

    # Swarm Parallel Execution (StateGraph handles this when 2 edges originate from same node)
    workflow.add_edge(START, "quant_analyst")
    workflow.add_edge(START, "macro_analyst")
    
    workflow.add_edge("quant_analyst", "cio_supervisor")
    workflow.add_edge("macro_analyst", "cio_supervisor")
    
    workflow.add_edge("cio_supervisor", "execute")
    workflow.add_edge("execute", END)

    return workflow.compile()


# ═══════════════════════════════════════════════════════════════════
# Live Mark-to-Market & Heartbeat
# ═══════════════════════════════════════════════════════════════════

async def heartbeat_loop():
    """
    Main orchestration loop. Polls SQLite for new ticks every HEARTBEAT_SECONDS.
    If new data arrives, runs the full LangGraph pipeline.
    """
    graph = build_graph()
    cycle = 0

    log.info("Orchestrator heartbeat starting (interval=%ds)…", HEARTBEAT_SECONDS)
    log_to_supabase("orchestrator", "Heartbeat loop started.", level="INFO")

    while True:
        cycle += 1
        try:
            ticks = poll_latest_ticks()

            if not ticks:
                log.debug("Cycle %d: No new ticks. Sleeping…", cycle)
                await asyncio.sleep(HEARTBEAT_SECONDS)
                continue

            log.info("Cycle %d: %d new ticks received. Running pipeline…", cycle, len(ticks))
            snapshot = aggregate_market_snapshot(ticks)

            initial_state: AgentState = {
                "market_data": snapshot,
                "raw_ticks": ticks,
                "quant_signal": 0.0,
                "quant_context": {},
                "sentiment_signal": 0.0,
                "risk_approved": False,
                "execution_result": {},
                "reasoning": "",
            }

            # Run the LangGraph pipeline
            final_state = {}
            for output in graph.stream(initial_state):
                final_state.update(output)
                log.debug("Pipeline node output: %s", output)

            # Extract quant context for portfolio state
            quant_ctx = {}
            if "quant_analyst" in final_state:
                quant_ctx = final_state["quant_analyst"].get("quant_context", {})

            # ── Construct the JSON payload for OrderFlowContext UI widget ──
            # The widget specifically expects: { regime, skew, poc, divergence }
            # We'll use the aggregate regime, and the skew/poc/divergence from the
            # symbol with the most volume (or SPY/AAPL if present)
            
            agg = quant_ctx.get("aggregate", {})
            symbols_data = quant_ctx.get("symbols", {})
            
            # Find the symbol to highlight (highest volume)
            highlight_sym = None
            max_vol = -1
            for sym, data in symbols_data.items():
                vol = data.get("volume_profile", {}).get("total_volume", 0)
                if vol > max_vol:
                    max_vol = vol
                    highlight_sym = sym

            # Build the payload
            order_flow_payload = {
                "regime": agg.get("regime", "NEUTRAL"),
                "skew": None,
                "poc": None,
                "divergence": None
            }

            if highlight_sym and highlight_sym in symbols_data:
                target = symbols_data[highlight_sym]
                vp = target.get("volume_profile", {})
                fd = target.get("flow_divergence", {})
                
                order_flow_payload["skew"] = vp.get("skewness")
                order_flow_payload["poc"] = vp.get("poc")
                
                if fd.get("divergence_warning"):
                    # The widget expects a short string like "BULLISH DIVERGENCE"
                    reason = fd.get("divergence_reason", "")
                    if "BULLISH DIVERGENCE" in reason:
                        order_flow_payload["divergence"] = "BULLISH"
                    elif "BEARISH DIVERGENCE" in reason:
                        order_flow_payload["divergence"] = "BEARISH"
                    else:
                        order_flow_payload["divergence"] = "WARNING"

            log.info("Updating portfolio state with Order Flow JSON: %s", order_flow_payload)

            # ── Live Mark-to-Market PnL ──
            # 1. Fetch all OPEN trades from Supabase
            # 2. Match with latest snapshot price from SQLite
            # 3. Calculate Unrealized PnL
            # 4. Update Trades table & aggregate Portfolio equity
            unrealized_pnl = 0.0
            base_equity = 100000.0  # Would fetch from Alpaca in prod

            if supa:
                try:
                    open_trades_res = supa.table("trades").select("*").eq("status", "OPEN").execute()
                    open_trades = open_trades_res.data or []
                    
                    for row in open_trades:
                        pos_sym = row["symbol"]
                        pos_qty = float(row["qty"])
                        pos_side = row["side"].upper()
                        entry = float(row.get("entry_price") or row.get("execution_price") or 0.0)
                        
                        # Get latest price
                        live_price = entry
                        if pos_sym in snapshot:
                            live_price = float(snapshot[pos_sym]["price"])
                            
                        # Compute PnL
                        diff = live_price - entry
                        u_pnl = (diff * pos_qty) if pos_side == "BUY" else (-diff * pos_qty)
                        unrealized_pnl += u_pnl
                        
                        # Update the specific trade row so UI ActivePositions table updates
                        supa.table("trades").update({
                            "pnl": round(u_pnl, 2),
                            # Optional: could update current_price but frontend might not need it
                        }).eq("id", row["id"]).execute()
                        
                        log.debug(f"M2M: {pos_sym} {pos_side} {pos_qty}x | Entry: ${entry:.2f} Live: ${live_price:.2f} | PnL: ${u_pnl:.2f}")

                except Exception as e:
                    log.error("Live M2M PnL update failed: %s", e)

            total_equity = base_equity + unrealized_pnl

            update_portfolio_state(
                equity=round(total_equity, 2),
                cash=base_equity, # Simplified paper cash
                open_positions=order_flow_payload, # React widget reads this as JSONB
            )

        except Exception as exc:
            log.error("Cycle %d failed: %s", cycle, exc)
            log_to_supabase("orchestrator", f"Cycle {cycle} error: {exc}", level="ERROR")

        await asyncio.sleep(HEARTBEAT_SECONDS)


# ═══════════════════════════════════════════════════════════════════
# Entrypoint
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    log.info("Starting Orchestrator…")
    try:
        asyncio.run(heartbeat_loop())
    except KeyboardInterrupt:
        log.info("Orchestrator shutting down gracefully.")
        log_to_supabase("orchestrator", "Shutdown (KeyboardInterrupt).", level="WARN")
