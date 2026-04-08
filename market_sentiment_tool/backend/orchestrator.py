"""
orchestrator.py — LangGraph Continuous Orchestration Engine
============================================================
Core state machine running in a continuous heartbeat loop. Polls the local
SQLite WAL for fresh tick data, runs the Quant → Sentiment → Risk → Execute
pipeline, and writes results to Supabase (trades, agent_logs, portfolio_state).

Boot order: Step 4 (after ingestion.py is streaming).
"""

import asyncio
import contextlib
import base64
import io
import json
import os
import re
import sqlite3
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, TypedDict

import aiohttp
import numpy as np
import pandas as pd
from langgraph.graph import StateGraph, START, END
from supabase import create_client, Client as SupabaseClient

"""
Note: keep heavy / optional dependencies (RAG, vector DB) imported lazily inside
their node functions so `ORCHESTRATOR_MODE=crypto` can run with a minimal
requirements set on CPU-only VPS hosts.
"""
from shared.kalshi_ws import connect_and_listen as kalshi_connect_and_listen
from shared.kalshi_ws import sign_kalshi_message
from market_sentiment_tool.backend.runtime_bootstrap import (
    RuntimeBootstrapError,
    critical_var_presence,
    load_canonical_env,
    resolve_kalshi_runtime_settings,
    validate_runtime_env,
)
from market_sentiment_tool.backend.crypto_operator_state import (
    fetch_trading_controls,
    insert_crypto_signal_event,
    is_crypto_trading_enabled,
)

# ── Runtime bootstrap ──
ENV_BOOTSTRAP = load_canonical_env(__file__)
ENV_PATH = str(ENV_BOOTSTRAP.env_path) if ENV_BOOTSTRAP.env_path else "<missing>"
KALSHI_RUNTIME = resolve_kalshi_runtime_settings()

# ── Config ──
SUPABASE_URL = os.getenv("SUPABASE_URL", "") or os.getenv("VITE_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
LOCAL_LLM_ENDPOINT = os.getenv("LOCAL_LLM_ENDPOINT", "http://127.0.0.1:8080/v1")
LOCAL_LLM_MODEL = os.getenv("LOCAL_LLM_MODEL_NAME", "GLM-5-MXFP4")
HEARTBEAT_SECONDS = 10  # How often the orchestrator polls for new ticks
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_ticks.sqlite3")

# Crypto worker config (Kalshi WS + model inference)
ORCHESTRATOR_MODE = os.getenv("ORCHESTRATOR_MODE", "crypto").strip().lower()
CRYPTO_MIN_BACKOFF_S = float(os.getenv("CRYPTO_MIN_BACKOFF_S", "1.0"))
CRYPTO_MAX_BACKOFF_S = float(os.getenv("CRYPTO_MAX_BACKOFF_S", "60.0"))
CRYPTO_JITTER_S = float(os.getenv("CRYPTO_JITTER_S", "0.25"))
CRYPTO_TRADE_COOLDOWN_S = int(os.getenv("CRYPTO_TRADE_COOLDOWN_S", "600"))
CRYPTO_SIGNAL_YES_THRESHOLD = float(os.getenv("CRYPTO_SIGNAL_YES_THRESHOLD", "0.65"))
CRYPTO_SIGNAL_NO_THRESHOLD = float(os.getenv("CRYPTO_SIGNAL_NO_THRESHOLD", "0.35"))
CRYPTO_FEATURE_LOOKBACK_HOURS = int(os.getenv("CRYPTO_FEATURE_LOOKBACK_HOURS", "400"))
CRYPTO_FEATURE_CACHE_TTL_S = float(os.getenv("CRYPTO_FEATURE_CACHE_TTL_S", "30"))
CRYPTO_MIN_FEATURE_BARS = int(os.getenv("CRYPTO_MIN_FEATURE_BARS", "205"))
CRYPTO_OPPORTUNITY_ALERT_DEDUPE_S = int(os.getenv("CRYPTO_OPPORTUNITY_ALERT_DEDUPE_S", "300"))
CRYPTO_NEAR_MISS_ALERT_DEDUPE_S = int(os.getenv("CRYPTO_NEAR_MISS_ALERT_DEDUPE_S", "600"))
CRYPTO_INFERENCE_HEARTBEAT_EVERY = int(os.getenv("CRYPTO_INFERENCE_HEARTBEAT_EVERY", "100"))

# Optional explicit model paths (otherwise auto-discover).
BTC_MODEL_PATH = os.getenv("BTC_MODEL_PATH") or os.getenv("KALSHI_BTC_MODEL_PATH")
ETH_MODEL_PATH = os.getenv("ETH_MODEL_PATH") or os.getenv("KALSHI_ETH_MODEL_PATH")

# Kalshi runtime selection
KALSHI_ENV = KALSHI_RUNTIME.mode
KALSHI_API_BASE = KALSHI_RUNTIME.api_base.rsplit("/trade-api/v2", 1)[0]
KALSHI_TRADE_API_V2_BASE = KALSHI_RUNTIME.api_base
KALSHI_WS_URL = KALSHI_RUNTIME.ws_url
KALSHI_ORDER_COUNT = int(os.getenv("KALSHI_ORDER_COUNT", "1"))
ALPACA_DATA_API_BASE = os.getenv("ALPACA_DATA_API_BASE", "https://data.alpaca.markets").strip('"').strip("'")
ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")


# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [ORCHESTRATOR]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)
_critical_presence = critical_var_presence(
    (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_ROLE_KEY",
        "KALSHI_API_KEY_ID",
        "KALSHI_PRIVATE_KEY_PATH",
    ),
    ENV_BOOTSTRAP.parsed_values,
)
log.info(
    "Env loaded from %s (source=%s SUPABASE_URL_set=%s SUPABASE_SERVICE_ROLE_KEY_set=%s KALSHI_API_KEY_ID_set=%s KALSHI_PRIVATE_KEY_PATH_set=%s KALSHI_ENV=%s)",
    ENV_PATH,
    ENV_BOOTSTRAP.source_label,
    _critical_presence["SUPABASE_URL"],
    _critical_presence["SUPABASE_SERVICE_ROLE_KEY"],
    _critical_presence["KALSHI_API_KEY_ID"],
    _critical_presence["KALSHI_PRIVATE_KEY_PATH"],
    KALSHI_ENV,
)
for _env_error in ENV_BOOTSTRAP.syntax_errors:
    log.error("Env syntax error: %s", _env_error)
for _kalshi_error in KALSHI_RUNTIME.errors:
    log.error("Kalshi config error: %s", _kalshi_error)

# ── Supabase Client (Service Role — bypasses RLS) ──
supa: SupabaseClient | None = None
USER_ID = None
_RUNTIME_VALIDATED = False

# ── pgvector RAG is handled via news_rag.query_news() — no local DB client needed ──

def validate_runtime_bootstrap(*, require_supabase: bool = True, require_kalshi: bool = True) -> None:
    errors = validate_runtime_env(
        env_bootstrap=ENV_BOOTSTRAP,
        kalshi=KALSHI_RUNTIME,
        require_supabase=require_supabase,
        require_kalshi=require_kalshi,
    )
    if errors:
        raise RuntimeBootstrapError("Runtime bootstrap validation failed:\n- " + "\n- ".join(errors))


def initialize_runtime_clients(*, require_supabase: bool = True, require_kalshi: bool = True) -> None:
    global supa, USER_ID, _RUNTIME_VALIDATED
    validate_runtime_bootstrap(require_supabase=require_supabase, require_kalshi=require_kalshi)
    if _RUNTIME_VALIDATED:
        return

    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        supa = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        log.info("Supabase service-role client initialized.")
    else:
        raise RuntimeBootstrapError("Runtime bootstrap validation passed unexpectedly without Supabase credentials.")

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
    except Exception as exc:
        log.error("Failed to query user UUID: %s", exc)

    _RUNTIME_VALIDATED = True


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
        "engine": trade.get("engine"),
        "market_ticker": trade.get("market_ticker"),
        "contract_side": trade.get("contract_side"),
        "external_order_id": trade.get("external_order_id"),
        "error_code": trade.get("error_code"),
        "metadata": trade.get("metadata") or {},
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


def check_crypto_trade_switch() -> bool:
    if supa is None:
        return False
    return is_crypto_trading_enabled(supa, user_id=USER_ID)


def get_crypto_trade_controls() -> dict[str, Any]:
    if supa is None:
        return {}
    return fetch_trading_controls(supa, user_id=USER_ID)


def write_crypto_signal_event(event: dict[str, Any]) -> None:
    if supa is None:
        return
    if not insert_crypto_signal_event(supa, event=event, user_id=USER_ID):
        log.error("crypto_signal_events insert failed: %s", event)


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
    try:
        from .quant_engine import analyze_all_symbols
    except ImportError:
        from quant_engine import analyze_all_symbols

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
        try:
            from .news_rag import query_news  # pgvector-backed semantic search
        except ImportError:
            from news_rag import query_news  # pgvector-backed semantic search

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
# Crypto Models + Kalshi WS Edge Evaluation
# ═══════════════════════════════════════════════════════════════════

_BTC_MODEL: Any | None = None
_ETH_MODEL: Any | None = None
_CRYPTO_FEATURE_ROW_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_pickle_model(path: Path) -> Any:
    """
    Load a model once at startup. Prefer joblib if available, otherwise pickle.
    """
    try:
        import joblib  # type: ignore

        return joblib.load(path)
    except Exception:
        import pickle

        with path.open("rb") as f:
            return pickle.load(f)


def _resolve_model_path(explicit: Optional[str], candidates: list[str], label: str) -> Path:
    if explicit and explicit.strip():
        p = Path(explicit)
        if not p.is_absolute():
            p = _repo_root() / p
        if p.is_file():
            return p
        raise FileNotFoundError(f"{label} model not found at explicit path: {p}")

    searched: list[str] = []
    for c in candidates:
        p = Path(c)
        if not p.is_absolute():
            p = _repo_root() / p
        searched.append(str(p))
        if p.is_file():
            return p

    raise FileNotFoundError(f"{label} model not found. Searched: {searched}")


def load_crypto_models() -> tuple[Any, Any]:
    """
    Load BTC/ETH models into memory once. Subsequent calls return cached models.
    """
    global _BTC_MODEL, _ETH_MODEL
    if _BTC_MODEL is not None and _ETH_MODEL is not None:
        return _BTC_MODEL, _ETH_MODEL

    # The user mentioned /root/kalshibot, but this repo also contains models under ./model/
    # and ./quant_research_lab/models/. We search both families.
    btc_path = _resolve_model_path(
        BTC_MODEL_PATH,
        candidates=[
            "/root/kalshibot/btc_model.pkl",
            "models/btc_model.pkl",
            "quant_research_lab/models/btc_model.pkl",
            "model/btc_model.pkl",
            "model/lgbm_model_BTC.pkl",
            "quant_research_lab/models/btc_sniper.pkl",
            "btc_sniper.pkl",
        ],
        label="BTC",
    )
    eth_path = _resolve_model_path(
        ETH_MODEL_PATH,
        candidates=[
            "/root/kalshibot/eth_model.pkl",
            "models/eth_model.pkl",
            "quant_research_lab/models/eth_model.pkl",
            "model/eth_model.pkl",
            "model/lgbm_model_ETH.pkl",
            "quant_research_lab/models/eth_sniper.pkl",
            "eth_sniper.pkl",
        ],
        label="ETH",
    )

    log.info("Loading BTC model: %s", btc_path)
    _BTC_MODEL = _load_pickle_model(btc_path)
    log.info("Loading ETH model: %s", eth_path)
    _ETH_MODEL = _load_pickle_model(eth_path)

    return _BTC_MODEL, _ETH_MODEL


def _extract_yes_mid_dollars(ticker_message: dict) -> Optional[float]:
    """
    Extract a usable "current price" in dollars from a Kalshi `type="ticker"` message.
    Prefers mid = (yes_bid_dollars + yes_ask_dollars) / 2 when both are present.
    """
    msg = ticker_message.get("msg") or {}
    try:
        bid = msg.get("yes_bid_dollars")
        ask = msg.get("yes_ask_dollars")

        bid_f = float(bid) if bid is not None else None
        ask_f = float(ask) if ask is not None else None

        if bid_f is not None and ask_f is not None and bid_f > 0 and ask_f > 0:
            return (bid_f + ask_f) / 2.0
        if ask_f is not None and ask_f > 0:
            return ask_f
        if bid_f is not None and bid_f > 0:
            return bid_f
    except Exception:
        return None
    return None


def _alpaca_crypto_symbol(asset: str) -> Optional[str]:
    return {"BTC": "BTC/USD", "ETH": "ETH/USD"}.get(asset.upper())


def _yfinance_crypto_symbol(asset: str) -> Optional[str]:
    return {"BTC": "BTC-USD", "ETH": "ETH-USD"}.get(asset.upper())


def _model_feature_names(model: Any) -> list[str]:
    names = getattr(model, "feature_name_", None)
    if names is None:
        names = getattr(model, "feature_names_in_", None)
    if names is None:
        raise TypeError("Model is missing feature names; cannot align live crypto inference features.")
    return [str(name) for name in names]


def _merge_crypto_bar_sources(primary: pd.DataFrame, backfill: pd.DataFrame, *, required_bars: int) -> pd.DataFrame:
    frames = [frame for frame in (backfill, primary) if not frame.empty]
    if not frames:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])

    merged = pd.concat(frames).sort_index()
    merged = merged[~merged.index.duplicated(keep="last")]
    merged = merged[["Open", "High", "Low", "Close", "Volume"]].dropna()
    if required_bars > 0 and len(merged) > required_bars:
        return merged.tail(required_bars)
    return merged


def _fetch_yfinance_crypto_bars(asset: str, *, lookback_hours: int = CRYPTO_FEATURE_LOOKBACK_HOURS) -> pd.DataFrame:
    symbol = _yfinance_crypto_symbol(asset)
    if not symbol:
        raise ValueError(f"Unsupported crypto asset for yfinance backfill: {asset}")

    try:
        import yfinance as yf
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "yfinance is required for crypto historical backfill; install market_sentiment_tool/backend/requirements.txt into the PM2 interpreter environment."
        ) from exc

    period_days = max(int(np.ceil(lookback_hours / 24)) + 5, 14)
    frame = yf.download(symbol, period=f"{period_days}d", interval="1h", progress=False, auto_adjust=False)
    if frame.empty:
        raise ValueError(f"yfinance returned no hourly bars for {symbol}")
    if isinstance(frame.columns, pd.MultiIndex):
        frame.columns = frame.columns.get_level_values(0)

    frame.index = pd.to_datetime(frame.index, utc=True)
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    missing_cols = [column for column in required_cols if column not in frame.columns]
    if missing_cols:
        raise ValueError(f"yfinance payload missing required columns for {symbol}: {missing_cols}")
    frame = frame[required_cols].copy()
    for column in required_cols:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna().sort_index()


def _fetch_alpaca_crypto_bars(asset: str, *, lookback_hours: int = CRYPTO_FEATURE_LOOKBACK_HOURS) -> pd.DataFrame:
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        raise RuntimeError("Missing Alpaca API credentials for crypto feature fetch.")

    symbol = _alpaca_crypto_symbol(asset)
    if not symbol:
        raise ValueError(f"Unsupported crypto asset: {asset}")

    import requests

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=max(lookback_hours, 240))
    url = f"{ALPACA_DATA_API_BASE}/v1beta3/crypto/us/bars"
    response = requests.get(
        url,
        headers={
            "accept": "application/json",
            "APCA-API-KEY-ID": ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
        },
        params={
            "symbols": symbol,
            "timeframe": "1Hour",
            "start": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "end": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": max(lookback_hours + 24, 300),
            "sort": "asc",
        },
        timeout=15,
    )
    response.raise_for_status()
    payload = response.json()
    bars = (payload.get("bars") or {}).get(symbol) or []
    if not bars:
        raise ValueError(f"Alpaca returned no hourly crypto bars for {symbol}")

    frame = pd.DataFrame(bars)
    rename_map = {"t": "timestamp", "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"}
    frame = frame.rename(columns=rename_map)
    if "timestamp" not in frame.columns:
        raise ValueError(f"Alpaca bar payload missing timestamp for {symbol}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.set_index("timestamp").sort_index()
    required_cols = ["Open", "High", "Low", "Close", "Volume"]
    missing_cols = [column for column in required_cols if column not in frame.columns]
    if missing_cols:
        raise ValueError(f"Alpaca bar payload missing required columns for {symbol}: {missing_cols}")
    for column in required_cols:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame[required_cols].dropna()
    if len(frame) < CRYPTO_MIN_FEATURE_BARS:
        log.info(
            "[CRYPTO EDGE] Alpaca returned only %s hourly bars for %s; attempting yfinance backfill to reach %s bars.",
            len(frame),
            symbol,
            CRYPTO_MIN_FEATURE_BARS,
        )
        try:
            historical = _fetch_yfinance_crypto_bars(asset, lookback_hours=lookback_hours)
            merged = _merge_crypto_bar_sources(frame, historical, required_bars=max(lookback_hours, CRYPTO_MIN_FEATURE_BARS))
            if len(merged) >= CRYPTO_MIN_FEATURE_BARS:
                log.info(
                    "[CRYPTO EDGE] Backfilled %s hourly bars via yfinance (%s Alpaca + %s merged).",
                    symbol,
                    len(frame),
                    len(merged),
                )
                return merged
            log.warning(
                "[CRYPTO EDGE] yfinance backfill for %s completed but merged history is still short (%s < %s bars).",
                symbol,
                len(merged),
                CRYPTO_MIN_FEATURE_BARS,
            )
        except Exception as exc:
            log.warning("[CRYPTO EDGE] Failed to backfill %s hourly bars via yfinance: %s", symbol, exc)
        raise ValueError(f"Need at least {CRYPTO_MIN_FEATURE_BARS} hourly bars for {symbol}; received {len(frame)}")
    return frame


def _build_crypto_feature_frame(bars: pd.DataFrame) -> pd.DataFrame:
    import ta

    df = bars.copy().sort_index()
    df["rsi_5_raw"] = ta.momentum.rsi(df["Close"], window=5)
    df["rsi_7_raw"] = ta.momentum.rsi(df["Close"], window=7)
    df["rsi_14_raw"] = ta.momentum.rsi(df["Close"], window=14)

    atr = ta.volatility.average_true_range(df["High"], df["Low"], df["Close"], window=14)
    rolling_std_24 = df["Close"].pct_change().rolling(window=24).std()
    rolling_std_168 = df["Close"].pct_change().rolling(window=168).std()

    df["hour"] = df.index.hour
    df["dayofweek"] = df.index.dayofweek
    df["is_weekend"] = (df["dayofweek"] >= 5).astype(int)
    df["is_retail_window"] = (df["dayofweek"] >= 4).astype(int)
    df["is_us_session"] = ((df["hour"] >= 14) & (df["hour"] <= 21)).astype(int)
    df["sin_hour"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["cos_hour"] = np.cos(2 * np.pi * df["hour"] / 24)
    df["midnight_signal"] = (df["hour"] == 0).astype(int)

    df["vol_ratio_raw"] = rolling_std_24 / (rolling_std_168 + 1e-6)
    df["dist_ma200_raw"] = (df["Close"] - df["Close"].rolling(200).mean()) / (df["Close"].rolling(200).std() + 1e-6)
    df["force_idx_raw"] = df["Close"].diff(1) * df["Volume"]
    df["rsi_slope"] = df["rsi_7_raw"].diff(3)
    df["price_slope"] = df["Close"].diff(3)
    df["rsi_div_raw"] = ((df["rsi_slope"] < 0) & (df["price_slope"] > 0)).astype(int)

    for raw_column in (
        "rsi_5_raw",
        "rsi_7_raw",
        "rsi_14_raw",
        "vol_ratio_raw",
        "dist_ma200_raw",
        "force_idx_raw",
        "rsi_div_raw",
    ):
        df[raw_column.replace("_raw", "")] = df[raw_column].shift(1)

    df["ret_1h_z"] = (df["Close"].pct_change(1) / (rolling_std_24 + 1e-6)).shift(1)
    df["ret_4h"] = df["Close"].pct_change(4).shift(1)
    df["rsi_z"] = ((df["rsi_7_raw"] - df["rsi_7_raw"].rolling(24).mean()) / (df["rsi_7_raw"].rolling(24).std() + 1e-6)).shift(1)
    df["z_score_24h"] = ((df["Close"] - df["Close"].rolling(24).mean()) / (df["Close"].rolling(24).std() + 1e-6)).shift(1)
    df["vol_adj_ret"] = (df["Close"].pct_change() / (atr / df["Close"] + 1e-6)).shift(1)
    df["relative_vol"] = (df["Volume"] / (df["Volume"].rolling(24).mean() + 1e-6)).shift(1)
    df["vol_pressure"] = df["relative_vol"] / (df["vol_ratio_raw"].shift(1) + 1e-6)
    df["vol_spike"] = (df["Volume"] > df["Volume"].rolling(24).mean()).astype(int).shift(1)
    df["retail_rsi"] = df["rsi_z"] * df["is_retail_window"]

    plus_dm = df["High"].diff().clip(lower=0)
    minus_dm = df["Low"].diff().clip(upper=0).abs()
    df["trend_bias"] = ((plus_dm.rolling(14).mean() - minus_dm.rolling(14).mean()) / (atr + 1e-6)).shift(1)

    cols_to_drop = [column for column in df.columns if "_raw" in column or "slope" in column]
    return df.drop(columns=cols_to_drop).dropna()


def _latest_crypto_feature_row(asset: str, model: Any) -> pd.DataFrame:
    cache_key = asset.upper()
    cached = _CRYPTO_FEATURE_ROW_CACHE.get(cache_key)
    now_ts = time.time()
    if cached and (now_ts - cached[0]) < CRYPTO_FEATURE_CACHE_TTL_S:
        return cached[1]

    feature_names = _model_feature_names(model)
    bars = _fetch_alpaca_crypto_bars(asset)
    features = _build_crypto_feature_frame(bars)
    if features.empty:
        raise ValueError(f"No usable crypto features generated for {asset}")

    last_row = features.tail(1).reindex(columns=feature_names)
    missing_features = [name for name in feature_names if name not in last_row.columns]
    if missing_features:
        raise ValueError(f"Crypto feature pipeline missing model columns for {asset}: {missing_features}")
    if last_row.isnull().any(axis=None):
        bad_columns = last_row.columns[last_row.isnull().any()].tolist()
        raise ValueError(f"Crypto feature row contains NaN values for {asset}: {bad_columns}")

    _CRYPTO_FEATURE_ROW_CACHE[cache_key] = (now_ts, last_row)
    return last_row


def _model_yes_probability(model: Any, feature_frame: pd.DataFrame) -> float:
    """
    Adapter for common sklearn/lightgbm-style models.
    Contract: feed aligned live feature row, get P(YES).
    """
    x = feature_frame

    if hasattr(model, "predict_proba"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            probs = model.predict_proba(x)
        try:
            return float(probs[0][1])
        except Exception:
            return float(probs[0])

    if hasattr(model, "predict"):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            pred = model.predict(x)
        pred_val = float(pred[0]) if isinstance(pred, (list, tuple, np.ndarray)) else float(pred)
        if 0.0 <= pred_val <= 1.0:
            return pred_val
        return 1.0 if pred_val > 0 else 0.0

    if callable(model):
        pred_val = float(model(price_dollars))
        return max(0.0, min(1.0, pred_val))

    raise TypeError("Unsupported model type (no predict/predict_proba and not callable).")


class TradeSignal(TypedDict):
    asset: str
    market_ticker: str
    side: str  # "YES" or "NO"
    probability_yes: float
    price_dollars: float
    spot_price_dollars: Optional[float]
    resolved_ticker: Optional[str]
    edge: Optional[float]
    created_at: str
    raw: dict


class CryptoAgentState(TypedDict):
    ticker: dict
    trade_signal: Optional[TradeSignal]
    resolved_market_ticker: Optional[str]
    final_edge: Optional[float]
    execution_result: Optional[dict]


def evaluate_crypto_edge(state: CryptoAgentState) -> dict:
    """
    Node: evaluate_crypto_edge

    When a BTC/ETH ticker update arrives, run the corresponding in-memory model.
    Emit a TRADE_SIGNAL when:
      - P(YES) >= 0.65  => YES signal
      - P(YES) <= 0.35  => NO signal
    """
    btc_model, eth_model = load_crypto_models()

    ticker_message = state.get("ticker") or {}
    msg = ticker_message.get("msg") or {}
    market_ticker = str(msg.get("market_ticker") or "")
    if not market_ticker:
        return {"trade_signal": None}

    mt = market_ticker.upper()
    if "BTC" in mt:
        model = btc_model
        asset = "BTC"
    elif "ETH" in mt:
        model = eth_model
        asset = "ETH"
    else:
        return {"trade_signal": None}

    price = _extract_yes_mid_dollars(ticker_message)
    if price is None:
        _record_inference_skip(
            asset=asset,
            market_ticker=market_ticker,
            reason="no_usable_kalshi_price",
        )
        log.info(
            "[CRYPTO INFERENCE] asset=%s source=%s classification=no_usable_kalshi_price",
            asset,
            market_ticker,
        )
        return {"trade_signal": None}

    try:
        feature_row = _latest_crypto_feature_row(asset, model)
        prob_yes = _model_yes_probability(model, feature_row)
    except Exception as exc:
        log.error("[CRYPTO EDGE] %s feature inference failed: %s", market_ticker, exc)
        return {"trade_signal": None}

    side: Optional[str] = None
    classification = "dead_zone"
    if prob_yes >= CRYPTO_SIGNAL_YES_THRESHOLD:
        side = "YES"
        classification = "yes_signal"
    elif prob_yes <= CRYPTO_SIGNAL_NO_THRESHOLD:
        side = "NO"
        classification = "no_signal"

    log.info(
        "[CRYPTO INFERENCE] asset=%s source=%s p_yes=%.3f signal_price=$%.4f classification=%s",
        asset,
        market_ticker,
        prob_yes,
        price,
        classification,
    )

    if side is None:
        if _should_record_inference_heartbeat(asset):
            _record_inference_event(
                asset=asset,
                market_ticker=market_ticker,
                status="inference_heartbeat",
                probability_yes=float(prob_yes),
                signal_price_dollars=float(price),
                payload={"classification": classification},
            )
        return {"trade_signal": None}

    _record_inference_event(
        asset=asset,
        market_ticker=market_ticker,
        status="signal_detected",
        probability_yes=float(prob_yes),
        signal_price_dollars=float(price),
        desired_side=side,
        payload={"classification": classification},
    )

    signal: TradeSignal = {
        "asset": asset,
        "market_ticker": market_ticker,
        "side": side,
        "probability_yes": float(prob_yes),
        "price_dollars": float(price),
        "spot_price_dollars": None,
        "resolved_ticker": None,
        "edge": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": ticker_message,
    }

    log.info("[CRYPTO EDGE] %s %s P(YES)=%.3f price=$%.4f", market_ticker, side, prob_yes, price)
    return {"trade_signal": signal}


_KALSHI_REST_PRIVATE_KEY: Any | None = None
_TRADED_TICKER_LAST_TS: dict[str, float] = {}
_INFERENCE_EVAL_COUNTER: dict[str, int] = {}


def _kalshi_load_rest_key():
    global _KALSHI_REST_PRIVATE_KEY
    if _KALSHI_REST_PRIVATE_KEY is not None:
        return _KALSHI_REST_PRIVATE_KEY

    private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
    if not private_key_path:
        raise ValueError("Missing KALSHI_PRIVATE_KEY_PATH for Kalshi REST signing.")

    from shared.kalshi_ws import load_rsa_private_key

    _KALSHI_REST_PRIVATE_KEY = load_rsa_private_key(private_key_path)
    return _KALSHI_REST_PRIVATE_KEY


def _kalshi_rest_headers(method: str, path: str) -> dict[str, str]:
    api_key_id = os.getenv("KALSHI_API_KEY_ID", "")
    if not api_key_id:
        raise ValueError("Missing KALSHI_API_KEY_ID for Kalshi REST signing.")

    private_key = _kalshi_load_rest_key()
    ts = str(int(time.time() * 1000))
    msg = f"{ts}{method.upper()}{path.split('?')[0]}"
    signature = sign_kalshi_message(private_key=private_key, message=msg.encode("utf-8"))

    return {
        "Content-Type": "application/json",
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def _kalshi_get(path: str, params: dict | None = None) -> dict:
    import requests

    url = f"{KALSHI_TRADE_API_V2_BASE}{path}"
    headers = _kalshi_rest_headers("GET", f"/trade-api/v2{path}")
    resp = requests.get(url, headers=headers, params=params, timeout=12)
    resp.raise_for_status()
    return resp.json()


def _fetch_alpaca_spot_price(asset: str) -> Optional[float]:
    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        log.warning("[RESOLUTION] Missing Alpaca API credentials; cannot fetch %s spot.", asset)
        return None

    symbol_map = {"BTC": "BTC/USD", "ETH": "ETH/USD"}
    symbol = symbol_map.get(asset.upper())
    if not symbol:
        return None

    try:
        import requests

        url = f"{ALPACA_DATA_API_BASE}/v1beta3/crypto/us/latest/bars"
        resp = requests.get(
            url,
            headers={
                "accept": "application/json",
                "APCA-API-KEY-ID": ALPACA_API_KEY,
                "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
            },
            params={"symbols": symbol},
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        bar = (data.get("bars") or {}).get(symbol)
        if isinstance(bar, list):
            bar = bar[-1] if bar else None
        if not isinstance(bar, dict):
            raise ValueError(f"No latest bar returned for {symbol}")

        for key in ("c", "close", "price"):
            value = bar.get(key)
            if value is not None:
                return float(value)
        raise ValueError(f"Latest bar payload missing close for {symbol}: {bar}")
    except Exception as exc:
        log.error("[RESOLUTION] Failed to fetch Alpaca %s spot: %s", asset, exc)
        return None


def _kalshi_extract_strike_price(market: dict) -> Optional[float]:
    for k in ("strike_price", "strike", "floor_strike", "cap_strike"):
        v = market.get(k)
        if v is None:
            continue
        try:
            return float(str(v).replace(",", ""))
        except Exception:
            pass

    for k in ("functional_strike", "custom_strike", "subtitle", "title"):
        s = market.get(k)
        if not s:
            continue
        m = re.search(r"(\d{1,3}(?:,\d{3})*(?:\.\d+)?)", str(s))
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except Exception:
                pass
    return None


def _market_matches_asset(market: dict, asset: str) -> bool:
    asset_u = asset.upper()
    haystack = " ".join(
        str(market.get(key) or "")
        for key in ("ticker", "event_ticker", "title", "subtitle")
    ).upper()
    return asset_u in haystack or f"KX{asset_u}" in haystack


def _is_hourly_market(market: dict) -> bool:
    haystack = " ".join(
        str(market.get(key) or "")
        for key in ("ticker", "event_ticker", "title", "subtitle")
    ).upper()
    if any(token in haystack for token in ("15 MIN", "15MIN", "15-MIN", "15M")):
        return False
    return any(token in haystack for token in ("HOURLY", "TODAY AT", "-H", " H"))


def _parse_market_close_time(close_time: Any) -> Optional[datetime]:
    if not close_time:
        return None
    try:
        text = str(close_time).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def resolve_kalshi_market(*, asset: str, spot_price: float) -> Optional[dict[str, Any]]:
    """Resolve the nearest future hourly event and choose the strike closest to spot."""
    cursor: Optional[str] = None
    pages = 0
    now = datetime.now(timezone.utc)
    hourly_buckets: dict[str, dict[str, Any]] = {}

    while pages < 10:
        pages += 1
        params: dict[str, Any] = {"status": "open", "limit": 200}
        if cursor:
            params["cursor"] = cursor

        data = _kalshi_get("/markets", params=params)
        markets = data.get("markets", []) or []
        cursor = data.get("cursor")

        for market in markets:
            if not _market_matches_asset(market, asset):
                continue
            if not _is_hourly_market(market):
                continue

            strike = _kalshi_extract_strike_price(market)
            close_dt = _parse_market_close_time(market.get("close_time"))
            if strike is None or close_dt is None or close_dt <= now:
                continue

            bucket_key = str(market.get("event_ticker") or close_dt.isoformat())
            bucket = hourly_buckets.setdefault(
                bucket_key,
                {"close_time": close_dt, "markets": []},
            )
            if close_dt < bucket["close_time"]:
                bucket["close_time"] = close_dt
            bucket["markets"].append(market)

        if not cursor:
            break

    if not hourly_buckets:
        return None

    _, selected_bucket = min(hourly_buckets.items(), key=lambda item: item[1]["close_time"])
    best_market: Optional[dict[str, Any]] = None
    best_distance = float("inf")

    for market in selected_bucket["markets"]:
        strike = _kalshi_extract_strike_price(market)
        ticker = str(market.get("ticker") or "")
        if strike is None or not ticker:
            continue
        distance = abs(float(strike) - float(spot_price))
        if distance < best_distance:
            best_distance = distance
            best_market = market

    if best_market is None:
        return None

    return {
        "ticker": str(best_market.get("ticker") or ""),
        "strike_price": _kalshi_extract_strike_price(best_market),
        "event_ticker": str(best_market.get("event_ticker") or ""),
        "close_time": selected_bucket["close_time"].isoformat(),
    }


def _kalshi_orderbook_bbo_dollars(market_ticker: str) -> dict[str, Optional[float]]:
    """
    Returns best bid and implied best ask in dollars for YES/NO.

    Per Kalshi docs: orderbook endpoint returns bids for yes_dollars/no_dollars.
    Asks are derived:
      yes_ask = 1 - no_bid
      no_ask  = 1 - yes_bid
    """
    data = _kalshi_get(f"/markets/{market_ticker}/orderbook")
    ob = data.get("orderbook_fp") or data.get("orderbook") or {}

    yes = ob.get("yes_dollars") or ob.get("yes") or []
    no = ob.get("no_dollars") or ob.get("no") or []

    def _best_price(levels: Any) -> Optional[float]:
        try:
            if not levels:
                return None
            return float(levels[0][0])
        except Exception:
            return None

    yes_bid = _best_price(yes)
    no_bid = _best_price(no)
    yes_ask = (1.0 - no_bid) if (no_bid is not None) else None
    no_ask = (1.0 - yes_bid) if (yes_bid is not None) else None

    return {"yes_bid": yes_bid, "yes_ask": yes_ask, "no_bid": no_bid, "no_ask": no_ask}


def _cooldown_allows_trade(ticker_id: str) -> bool:
    now = time.time()
    last = _TRADED_TICKER_LAST_TS.get(ticker_id)
    if last and (now - last) < CRYPTO_TRADE_COOLDOWN_S:
        return False

    if supa is None:
        return True

    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=CRYPTO_TRADE_COOLDOWN_S)).isoformat()
    try:
        res = (
            supa.table("agent_logs")
            .select("id")
            .eq("module", "orchestrator.crypto_trade")
            .gte("timestamp", cutoff_iso)
            .contains("reasoning_context", {"resolved_ticker": ticker_id})
            .limit(1)
            .execute()
        )
        if res.data:
            return False
    except Exception:
        return True

    return True


def _crypto_alert_dedupe_key(signal: TradeSignal, resolved_ticker: Optional[str]) -> str:
    return str(resolved_ticker or signal.get("market_ticker") or "unknown")


def _should_emit_opportunity_alert(dedupe_key: str) -> bool:
    if supa is None:
        return True
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=CRYPTO_OPPORTUNITY_ALERT_DEDUPE_S)).isoformat()
    try:
        result = (
            supa.table("crypto_signal_events")
            .select("id")
            .eq("dedupe_key", dedupe_key)
            .eq("alert_kind", "opportunity")
            .eq("alert_sent", True)
            .gte("created_at", cutoff_iso)
            .limit(1)
            .execute()
        )
        return not bool(result.data)
    except Exception as exc:
        log.error("crypto opportunity dedupe query failed: %s", exc)
        return True


def _should_emit_near_miss_alert(dedupe_key: str) -> bool:
    if supa is None:
        return True
    cutoff_iso = (datetime.now(timezone.utc) - timedelta(seconds=CRYPTO_NEAR_MISS_ALERT_DEDUPE_S)).isoformat()
    try:
        result = (
            supa.table("crypto_signal_events")
            .select("id")
            .eq("dedupe_key", dedupe_key)
            .eq("alert_kind", "near_miss")
            .eq("alert_sent", True)
            .gte("created_at", cutoff_iso)
            .limit(1)
            .execute()
        )
        return not bool(result.data)
    except Exception as exc:
        log.error("crypto near-miss dedupe query failed: %s", exc)
        return True


def _append_notification(result: Optional[dict], notification: dict[str, Any]) -> dict[str, Any]:
    merged = dict(result or {})
    notifications = list(merged.get("notifications") or [])
    notifications.append(notification)
    merged["notifications"] = notifications
    return merged


def _record_crypto_event(
    *,
    signal: TradeSignal,
    status: str,
    resolved_ticker: Optional[str],
    execution_result: Optional[dict] = None,
    skip_reason: Optional[str] = None,
    alert_kind: Optional[str] = None,
    alert_sent: bool = False,
    final_edge: Optional[float] = None,
    strike_price: Optional[float] = None,
    event_ticker: Optional[str] = None,
    event_close_time: Optional[str] = None,
    kalshi_price_dollars: Optional[float] = None,
) -> None:
    event = {
        "asset": signal.get("asset"),
        "source_market_ticker": signal.get("market_ticker"),
        "resolved_ticker": resolved_ticker,
        "desired_side": signal.get("side"),
        "status": status,
        "skip_reason": skip_reason,
        "execution_status": (execution_result or {}).get("status"),
        "alert_kind": alert_kind,
        "alert_sent": alert_sent,
        "dedupe_key": _crypto_alert_dedupe_key(signal, resolved_ticker),
        "model_probability_yes": signal.get("probability_yes"),
        "signal_price_dollars": signal.get("price_dollars"),
        "spot_price_dollars": signal.get("spot_price_dollars"),
        "kalshi_price_dollars": kalshi_price_dollars,
        "edge": final_edge,
        "strike_price": strike_price,
        "event_ticker": event_ticker,
        "event_close_time": event_close_time,
        "payload": {
            "signal": signal,
            "execution_result": execution_result,
        },
    }
    write_crypto_signal_event(event)


def _record_inference_event(
    *,
    asset: str,
    market_ticker: str,
    status: str,
    probability_yes: float,
    signal_price_dollars: Optional[float] = None,
    desired_side: Optional[str] = None,
    payload: Optional[dict[str, Any]] = None,
) -> None:
    write_crypto_signal_event(
        {
            "asset": asset,
            "source_market_ticker": market_ticker,
            "resolved_ticker": None,
            "desired_side": desired_side,
            "status": status,
            "model_probability_yes": probability_yes,
            "signal_price_dollars": signal_price_dollars,
            "payload": payload or {},
        }
    )


def _record_inference_skip(
    *,
    asset: str,
    market_ticker: str,
    reason: str,
    probability_yes: Optional[float] = None,
    signal_price_dollars: Optional[float] = None,
    resolved_ticker: Optional[str] = None,
    edge: Optional[float] = None,
    desired_side: Optional[str] = None,
    execution_result: Optional[dict[str, Any]] = None,
    strike_price: Optional[float] = None,
    event_ticker: Optional[str] = None,
    event_close_time: Optional[str] = None,
    kalshi_price_dollars: Optional[float] = None,
) -> None:
    write_crypto_signal_event(
        {
            "asset": asset,
            "source_market_ticker": market_ticker,
            "resolved_ticker": resolved_ticker,
            "desired_side": desired_side,
            "status": "execution_skip",
            "skip_reason": reason,
            "execution_status": (execution_result or {}).get("status"),
            "model_probability_yes": probability_yes,
            "signal_price_dollars": signal_price_dollars,
            "kalshi_price_dollars": kalshi_price_dollars,
            "edge": edge,
            "strike_price": strike_price,
            "event_ticker": event_ticker,
            "event_close_time": event_close_time,
            "payload": {"execution_result": execution_result or {}},
        }
    )


def _should_record_inference_heartbeat(asset: str) -> bool:
    count = int(_INFERENCE_EVAL_COUNTER.get(asset, 0)) + 1
    _INFERENCE_EVAL_COUNTER[asset] = count
    interval = max(1, CRYPTO_INFERENCE_HEARTBEAT_EVERY)
    return count % interval == 0


def _load_async_telegram_notifier():
    predictor_root = Path(__file__).resolve().parents[2] / "SP500 Predictor"
    predictor_root_text = str(predictor_root)
    if predictor_root_text not in sys.path:
        sys.path.insert(0, predictor_root_text)
    from src.telegram_notifier import TelegramNotifier

    return TelegramNotifier


def _run_crypto_graph_once(graph, initial_state: CryptoAgentState) -> dict[str, Any]:
    final_state: dict[str, Any] = {}
    for output in graph.stream(initial_state):
        final_state.update(output)
    return final_state


def _schedule_async_notification(coroutine: Any) -> None:
    task = asyncio.create_task(coroutine)

    def _consume_task_result(done_task: asyncio.Task) -> None:
        try:
            done_task.result()
        except Exception as exc:
            log.error("Async Telegram task failed: %s", exc)

    task.add_done_callback(_consume_task_result)


def market_resolution(state: CryptoAgentState) -> dict:
    """
    Resolve a generated crypto signal into an actionable Kalshi market + safe execution.

    Requirements:
    - Market discovery: find active hourly BTC/ETH markets and pick ATM strike from Alpaca spot.
    - Edge calculation: edge = P(outcome) - price_to_pay.
    - Safe execution: if edge > 5%, place a strict-limit order via the execution bridge in mcp_server.py.
    - Persistence: log full trade metadata to agent_logs (Supabase).
    - Cooldown: don't trade the same ticker_id more than once per configured cooldown window.
    """
    signal = state.get("trade_signal")
    if not signal:
        return {"resolved_market_ticker": None, "final_edge": None, "execution_result": None}

    asset = str(signal.get("asset") or "").upper()
    if asset not in {"BTC", "ETH"}:
        return {"resolved_market_ticker": None, "final_edge": None, "execution_result": None}

    signal_with_resolution: TradeSignal = dict(signal)
    source_market_ticker = str(signal.get("market_ticker") or "")
    signal_price = float(signal.get("price_dollars", 0.0))
    prob_yes = float(signal.get("probability_yes", 0.0))
    desired_side = str(signal.get("side") or "").upper()  # YES or NO

    if not check_crypto_trade_switch():
        controls = get_crypto_trade_controls()
        disable_reason = controls.get("crypto_trading_disabled_reason") or "crypto_auto_trade_enabled is False."
        execution_result = {"status": "blocked", "reason": disable_reason, "code": "crypto_trading_disabled"}
        log.warning("[RESOLUTION] %s signal blocked: %s", source_market_ticker, disable_reason)
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason="crypto_disabled",
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            desired_side=desired_side,
            execution_result=execution_result,
        )
        _record_crypto_event(
            signal=signal_with_resolution,
            status="blocked",
            resolved_ticker=None,
            execution_result=execution_result,
            skip_reason="crypto_trading_disabled",
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": None,
            "final_edge": None,
            "execution_result": execution_result,
        }

    spot_price = _fetch_alpaca_spot_price(asset)
    if spot_price is None:
        signal_with_resolution["spot_price_dollars"] = None
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason="alpaca_spot_unavailable",
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            desired_side=desired_side,
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_SKIPPED asset={asset} reason=alpaca_spot_unavailable",
            level="WARN",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "resolved_ticker": None,
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": None,
            "final_edge": None,
            "execution_result": {"status": "skipped", "reason": "alpaca_spot_unavailable"},
        }

    signal_with_resolution["spot_price_dollars"] = float(spot_price)
    resolved_market = resolve_kalshi_market(asset=asset, spot_price=spot_price)
    if not resolved_market:
        log.warning("[RESOLUTION] No matching %s hourly market found (spot=%.2f)", asset, spot_price)
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason="no_hourly_market",
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            desired_side=desired_side,
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_SKIPPED asset={asset} reason=no_market_match",
            level="WARN",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "spot_price_dollars": float(spot_price),
                "resolved_ticker": None,
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": None,
            "final_edge": None,
            "execution_result": {"status": "skipped", "reason": "no_market_match"},
        }

    resolved_ticker = str(resolved_market["ticker"])
    signal_with_resolution["resolved_ticker"] = resolved_ticker

    if not _cooldown_allows_trade(resolved_ticker):
        log.info("[COOLDOWN] Skipping %s (already traded within %ss)", resolved_ticker, CRYPTO_TRADE_COOLDOWN_S)
        should_alert = _should_emit_opportunity_alert(_crypto_alert_dedupe_key(signal_with_resolution, resolved_ticker))
        execution_result = {"status": "skipped", "reason": "cooldown"}
        if should_alert:
            execution_result = _append_notification(
                execution_result,
                {
                    "kind": "opportunity",
                    "asset": asset,
                    "resolved_ticker": resolved_ticker,
                    "desired_side": desired_side,
                    "probability_yes": prob_yes,
                    "price_dollars": signal_price,
                },
            )
        _record_crypto_event(
            signal=signal_with_resolution,
            status="execution_skip",
            resolved_ticker=resolved_ticker,
            execution_result=execution_result,
            skip_reason="cooldown_active",
            alert_kind="opportunity" if should_alert else None,
            alert_sent=should_alert,
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_SKIPPED asset={asset} reason=cooldown",
            level="INFO",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "spot_price_dollars": float(spot_price),
                "resolved_ticker": resolved_ticker,
                "strike_price": resolved_market.get("strike_price"),
                "cooldown_seconds": CRYPTO_TRADE_COOLDOWN_S,
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": None,
            "execution_result": execution_result,
        }

    bbo = _kalshi_orderbook_bbo_dollars(resolved_ticker)

    if desired_side == "YES":
        price_to_pay = bbo.get("yes_ask") or bbo.get("yes_bid")
        prob_outcome = prob_yes
        kalshi_side = "yes"
    else:
        price_to_pay = bbo.get("no_ask") or bbo.get("no_bid")
        prob_outcome = 1.0 - prob_yes
        kalshi_side = "no"

    if price_to_pay is None:
        log.warning("[RESOLUTION] Missing orderbook prices for %s", resolved_ticker)
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason="missing_orderbook",
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            resolved_ticker=resolved_ticker,
            desired_side=desired_side,
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_SKIPPED asset={asset} reason=missing_orderbook",
            level="WARN",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "spot_price_dollars": float(spot_price),
                "resolved_ticker": resolved_ticker,
                "strike_price": resolved_market.get("strike_price"),
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": None,
            "execution_result": {"status": "skipped", "reason": "missing_orderbook"},
        }

    final_edge = float(prob_outcome) - float(price_to_pay)
    confidence = float(prob_outcome)
    signal_with_resolution["edge"] = final_edge
    log.info(
        "[RESOLUTION] %s side=%s prob=%.3f price=$%.4f edge=%.3f",
        resolved_ticker,
        desired_side,
        prob_outcome,
        float(price_to_pay),
        final_edge,
    )

    if final_edge <= 0.05:
        should_alert = _should_emit_near_miss_alert(_crypto_alert_dedupe_key(signal_with_resolution, resolved_ticker))
        execution_result = {"status": "skipped", "reason": "edge_below_threshold"}
        if should_alert:
            execution_result = _append_notification(
                execution_result,
                {
                    "kind": "near_miss",
                    "asset": asset,
                    "resolved_ticker": resolved_ticker,
                    "desired_side": desired_side,
                    "probability_yes": prob_yes,
                    "price_dollars": float(price_to_pay),
                    "edge": final_edge,
                },
            )
        _record_crypto_event(
            signal=signal_with_resolution,
            status="near_miss",
            resolved_ticker=resolved_ticker,
            execution_result=execution_result,
            skip_reason="edge_below_threshold",
            alert_kind="near_miss" if should_alert else None,
            alert_sent=should_alert,
            final_edge=final_edge,
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
            kalshi_price_dollars=float(price_to_pay),
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_SKIPPED asset={asset} reason=edge_below_threshold",
            level="INFO",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "spot_price_dollars": float(spot_price),
                "resolved_ticker": resolved_ticker,
                "strike_price": resolved_market.get("strike_price"),
                "desired_side": desired_side,
                "limit_price_dollars": float(price_to_pay),
                "edge": final_edge,
                "model_probability_yes": prob_yes,
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": final_edge,
            "execution_result": execution_result,
        }

    try:
        try:
            from market_sentiment_tool.backend.mcp_server import submit_kalshi_order  # type: ignore
        except ImportError:
            from mcp_server import submit_kalshi_order  # type: ignore

        exec_res = submit_kalshi_order(
            ticker=resolved_ticker,
            side=kalshi_side,
            action="buy",
            count=KALSHI_ORDER_COUNT,
            limit_price_dollars=f"{float(price_to_pay):.4f}",
        )
    except Exception as exc:
        log.error("Kalshi execution bridge call failed: %s", exc)
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason="order_rejected",
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            resolved_ticker=resolved_ticker,
            edge=final_edge,
            desired_side=desired_side,
            execution_result={"status": "error", "detail": str(exc)},
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
            kalshi_price_dollars=float(price_to_pay),
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": final_edge,
            "execution_result": {"status": "error", "detail": str(exc)},
        }

    status = str(exec_res.get("status") or "").lower()
    trade_record = {
        "symbol": asset,
        "side": "BUY",
        "qty": KALSHI_ORDER_COUNT,
        "execution_price": float(price_to_pay),
        "status": status.upper() if status else "PENDING",
        "agent_confidence": confidence,
        "engine": "crypto_kalshi",
        "market_ticker": resolved_ticker,
        "contract_side": desired_side,
        "external_order_id": exec_res.get("external_order_id") or exec_res.get("order_id") or exec_res.get("id"),
        "error_code": exec_res.get("code"),
        "metadata": {
            "asset": asset,
            "source_market_ticker": source_market_ticker,
            "resolved_ticker": resolved_ticker,
            "model_probability_yes": prob_yes,
            "desired_side": desired_side,
            "edge": final_edge,
            "strike_price": resolved_market.get("strike_price"),
            "event_ticker": resolved_market.get("event_ticker"),
            "event_close_time": resolved_market.get("close_time"),
            "execution_result": exec_res,
        },
    }

    if status not in ("ok", "open", "resting", "filled", "accepted", "success"):
        execution_result = dict(exec_res)
        if str(exec_res.get("reason") or "").lower() == "insufficient_funds":
            execution_result = _append_notification(
                execution_result,
                {
                    "kind": "trading_disabled",
                    "asset": asset,
                    "resolved_ticker": resolved_ticker,
                    "reason": exec_res.get("detail") or exec_res.get("reason"),
                },
            )
            skip_reason = "insufficient_funds"
        else:
            execution_result = _append_notification(
                execution_result,
                {
                    "kind": "execution_failed",
                    "asset": asset,
                    "resolved_ticker": resolved_ticker,
                    "reason": exec_res.get("detail") or exec_res.get("reason") or exec_res.get("code"),
                },
            )
            skip_reason = "order_rejected"
        _record_inference_skip(
            asset=asset,
            market_ticker=source_market_ticker,
            reason=skip_reason,
            probability_yes=prob_yes,
            signal_price_dollars=signal_price,
            resolved_ticker=resolved_ticker,
            edge=final_edge,
            desired_side=desired_side,
            execution_result=execution_result,
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
            kalshi_price_dollars=float(price_to_pay),
        )
        trade_record["status"] = "FAILED"
        write_trade_to_supabase(trade_record)
        _record_crypto_event(
            signal=signal_with_resolution,
            status="failed",
            resolved_ticker=resolved_ticker,
            execution_result=execution_result,
            final_edge=final_edge,
            strike_price=resolved_market.get("strike_price"),
            event_ticker=resolved_market.get("event_ticker"),
            event_close_time=resolved_market.get("close_time"),
            kalshi_price_dollars=float(price_to_pay),
        )
        log_to_supabase(
            "orchestrator.crypto_trade",
            f"KALSHI_TRADE_FAILED asset={asset} ticker_id={resolved_ticker}",
            level="ERROR",
            context={
                "asset": asset,
                "source_market_ticker": source_market_ticker,
                "signal_price_dollars": signal_price,
                "spot_price_dollars": float(spot_price),
                "resolved_ticker": resolved_ticker,
                "strike_price": resolved_market.get("strike_price"),
                "desired_side": desired_side,
                "limit_price_dollars": float(price_to_pay),
                "edge": final_edge,
                "execution_result": exec_res,
            },
        )
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": final_edge,
            "execution_result": execution_result,
        }

    _TRADED_TICKER_LAST_TS[resolved_ticker] = time.time()
    execution_result = _append_notification(
        dict(exec_res),
        {
            "kind": "trade_executed",
            "asset": asset,
            "resolved_ticker": resolved_ticker,
            "desired_side": desired_side,
            "edge": final_edge,
            "price_dollars": float(price_to_pay),
        },
    )
    trade_record["status"] = "OPEN" if status in ("ok", "open", "resting", "accepted", "success") else "FILLED"
    write_trade_to_supabase(trade_record)
    _record_crypto_event(
        signal=signal_with_resolution,
        status="trade_placed",
        resolved_ticker=resolved_ticker,
        execution_result=execution_result,
        final_edge=final_edge,
        strike_price=resolved_market.get("strike_price"),
        event_ticker=resolved_market.get("event_ticker"),
        event_close_time=resolved_market.get("close_time"),
        kalshi_price_dollars=float(price_to_pay),
    )

    log_to_supabase(
        "orchestrator.crypto_trade",
        f"KALSHI_TRADE_PLACED ticker_id={resolved_ticker} side={desired_side} edge={final_edge:.3f}",
        level="INFO",
        context={
            "asset": asset,
            "ticker_id": resolved_ticker,
            "resolved_ticker": resolved_ticker,
            "source_market_ticker": source_market_ticker,
            "signal_confidence": confidence,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "edge": final_edge,
            "signal_price_dollars": signal_price,
            "spot_price_dollars": float(spot_price),
            "kalshi_price_dollars": float(price_to_pay),
            "model_probability_yes": prob_yes,
            "desired_side": desired_side,
            "strike_price": resolved_market.get("strike_price"),
            "event_ticker": resolved_market.get("event_ticker"),
            "event_close_time": resolved_market.get("close_time"),
            "cooldown_seconds": CRYPTO_TRADE_COOLDOWN_S,
            "execution_result": execution_result,
        },
    )

    return {
        "trade_signal": signal_with_resolution,
        "resolved_market_ticker": resolved_ticker,
        "final_edge": final_edge,
        "execution_result": execution_result,
    }


def build_crypto_graph():
    workflow = StateGraph(CryptoAgentState)
    workflow.add_node("evaluate_crypto_edge", evaluate_crypto_edge)
    workflow.add_node("market_resolution", market_resolution)

    workflow.add_edge(START, "evaluate_crypto_edge")
    workflow.add_edge("evaluate_crypto_edge", "market_resolution")
    workflow.add_edge("market_resolution", END)

    return workflow.compile()


async def _dispatch_crypto_notifications(notifier: Any, final_state: dict[str, Any]) -> None:
    if notifier is None or not notifier.is_enabled():
        return

    execution_result = final_state.get("execution_result") or {}
    notifications = list(execution_result.get("notifications") or [])
    trade_signal = final_state.get("trade_signal") or {}

    for notification in notifications:
        kind = notification.get("kind")
        if kind == "opportunity":
            _schedule_async_notification(
                notifier.alert_crypto_opportunity(
                    asset=str(notification.get("asset") or trade_signal.get("asset") or ""),
                    market_ticker=str(notification.get("resolved_ticker") or final_state.get("resolved_market_ticker") or ""),
                    side=str(notification.get("desired_side") or trade_signal.get("side") or ""),
                    probability_yes=float(notification.get("probability_yes") or trade_signal.get("probability_yes") or 0.0),
                    edge=final_state.get("final_edge"),
                    price_dollars=float(notification.get("price_dollars") or trade_signal.get("price_dollars") or 0.0),
                    reason="cooldown",
                )
            )
        elif kind == "trade_executed":
            _schedule_async_notification(
                notifier.alert_crypto_trade_executed(
                    asset=str(notification.get("asset") or trade_signal.get("asset") or ""),
                    market_ticker=str(notification.get("resolved_ticker") or final_state.get("resolved_market_ticker") or ""),
                    side=str(notification.get("desired_side") or trade_signal.get("side") or ""),
                    price_dollars=float(notification.get("price_dollars") or 0.0),
                    edge=float(notification.get("edge") or final_state.get("final_edge") or 0.0),
                    count=KALSHI_ORDER_COUNT,
                    execution_result=execution_result,
                )
            )
        elif kind == "execution_failed":
            _schedule_async_notification(
                notifier.alert_crypto_trade_failed(
                    asset=str(notification.get("asset") or trade_signal.get("asset") or ""),
                    market_ticker=str(notification.get("resolved_ticker") or final_state.get("resolved_market_ticker") or ""),
                    reason=str(notification.get("reason") or execution_result.get("detail") or execution_result.get("reason") or "order failed"),
                )
            )
        elif kind == "trading_disabled":
            _schedule_async_notification(
                notifier.alert_crypto_trading_disabled(
                    asset=str(notification.get("asset") or trade_signal.get("asset") or ""),
                    market_ticker=str(notification.get("resolved_ticker") or final_state.get("resolved_market_ticker") or ""),
                    reason=str(notification.get("reason") or execution_result.get("detail") or execution_result.get("reason") or "trading disabled"),
                )
            )
        elif kind == "near_miss":
            _schedule_async_notification(
                notifier.alert_crypto_opportunity(
                    asset=str(notification.get("asset") or trade_signal.get("asset") or ""),
                    market_ticker=str(notification.get("resolved_ticker") or final_state.get("resolved_market_ticker") or ""),
                    side=str(notification.get("desired_side") or trade_signal.get("side") or ""),
                    probability_yes=float(notification.get("probability_yes") or trade_signal.get("probability_yes") or 0.0),
                    edge=float(notification.get("edge") or final_state.get("final_edge") or 0.0),
                    price_dollars=float(notification.get("price_dollars") or 0.0),
                    reason="near_miss",
                )
            )


async def crypto_worker_loop(notifier: Any | None = None) -> None:
    """
    Persistent, autonomous worker: await Kalshi WS ticker messages forever and
    run the LangGraph evaluation pipeline per message.
    """
    initialize_runtime_clients(require_supabase=True, require_kalshi=True)
    crypto_tick_queue: asyncio.Queue = asyncio.Queue(maxsize=5000)

    # Load models once at startup; keep them in memory for the lifetime of the worker.
    load_crypto_models()

    listener_task = asyncio.create_task(
        kalshi_connect_and_listen(
            crypto_tick_queue,
            ws_url=KALSHI_WS_URL,
            min_backoff_s=CRYPTO_MIN_BACKOFF_S,
            max_backoff_s=CRYPTO_MAX_BACKOFF_S,
            jitter_s=CRYPTO_JITTER_S,
        )
    )
    log.info("Kalshi WS listener task started (ws_url=%s)", KALSHI_WS_URL)
    log_to_supabase(
        "orchestrator.crypto_runtime",
        f"Kalshi WS listener task started (ws_url={KALSHI_WS_URL})",
        level="INFO",
    )

    graph = build_crypto_graph()
    log.info("Crypto worker started; awaiting Kalshi ticker updates…")
    saw_first_tick = False

    try:
        while True:
            try:
                ticker_message = await asyncio.wait_for(crypto_tick_queue.get(), timeout=30.0)
            except asyncio.TimeoutError:
                if listener_task.done():
                    exc = listener_task.exception()
                    raise RuntimeError(f"Kalshi WS listener exited: {exc}") from exc
                log.info("No Kalshi ticks yet (ws_url=%s)", KALSHI_WS_URL)
                continue

            initial_state: CryptoAgentState = {
                "ticker": ticker_message,
                "trade_signal": None,
                "resolved_market_ticker": None,
                "final_edge": None,
                "execution_result": None,
            }

            final_state = await asyncio.to_thread(_run_crypto_graph_once, graph, initial_state)
            if not saw_first_tick:
                saw_first_tick = True
                log_to_supabase(
                    "orchestrator.crypto_runtime",
                    f"Kalshi WS active and receiving ticks (ws_url={KALSHI_WS_URL})",
                    level="INFO",
                )
            await _dispatch_crypto_notifications(notifier, final_state)
    finally:
        listener_task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await listener_task


async def run_crypto_services() -> None:
    notifier = None
    telegram_task = None
    try:
        TelegramNotifier = _load_async_telegram_notifier()
        notifier = TelegramNotifier()
        if notifier.is_enabled():
            await notifier.start()
            telegram_task = asyncio.create_task(notifier.run_polling(), name="telegram-operator-plane")
            log_to_supabase("orchestrator.crypto_runtime", "Telegram operator plane started.", level="INFO")
    except Exception as exc:
        notifier = None
        telegram_task = None
        log.error("Failed to start Telegram operator plane: %s", exc)
        log_to_supabase("orchestrator.crypto_runtime", f"Telegram operator plane failed to start: {exc}", level="ERROR")

    worker_task = asyncio.create_task(crypto_worker_loop(notifier=notifier), name="crypto-worker")
    tasks = [worker_task]
    if telegram_task is not None:
        tasks.append(telegram_task)

    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
        for completed in done:
            exception = completed.exception()
            if exception:
                raise exception
        for pending_task in pending:
            pending_task.cancel()
        for pending_task in pending:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await pending_task
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if notifier is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await notifier.close()


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
    initialize_runtime_clients(require_supabase=True, require_kalshi=False)
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
    try:
        initialize_runtime_clients(require_supabase=True, require_kalshi=(ORCHESTRATOR_MODE != "market_sentiment"))
        log.info("Starting Orchestrator (mode=%s)…", ORCHESTRATOR_MODE)
        if ORCHESTRATOR_MODE == "market_sentiment":
            asyncio.run(heartbeat_loop())
        else:
            asyncio.run(run_crypto_services())
    except RuntimeBootstrapError as exc:
        log.critical("%s", exc)
        raise SystemExit(1) from exc
    except KeyboardInterrupt:
        log.info("Orchestrator shutting down gracefully.")
        log_to_supabase("orchestrator", "Shutdown (KeyboardInterrupt).", level="WARN")
