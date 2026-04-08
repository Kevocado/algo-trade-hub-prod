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
import json
import os
import re
import sqlite3
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Optional, TypedDict

import aiohttp
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from langgraph.graph import StateGraph, START, END
from supabase import create_client, Client as SupabaseClient

"""
Note: keep heavy / optional dependencies (RAG, vector DB) imported lazily inside
their node functions so `ORCHESTRATOR_MODE=crypto` can run with a minimal
requirements set on CPU-only VPS hosts.
"""
from shared.kalshi_ws import connect_and_listen as kalshi_connect_and_listen
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding

# ── Load .env from project root (one directory up from /backend) ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

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

# Optional explicit model paths (otherwise auto-discover).
BTC_MODEL_PATH = os.getenv("BTC_MODEL_PATH") or os.getenv("KALSHI_BTC_MODEL_PATH")
ETH_MODEL_PATH = os.getenv("ETH_MODEL_PATH") or os.getenv("KALSHI_ETH_MODEL_PATH")

# Kalshi REST (Demo) for market discovery / pricing / execution
_KALSHI_API_BASE_RAW = (
    os.getenv("KALSHI_API_BASE", "")
    or os.getenv("KALSHI_DEMO_API_BASE", "")
    or "https://demo-api.kalshi.co"
)
_KALSHI_API_BASE_RAW = _KALSHI_API_BASE_RAW.strip().strip('"').strip("'")
KALSHI_WS_URL = os.getenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2").strip().strip('"').strip("'")


def _normalize_kalshi_api_base(raw: str) -> tuple[str, str]:
    raw = (raw or "").strip().strip('"').strip("'").rstrip("/")
    if not raw:
        raw = "https://demo-api.kalshi.co"
    marker = "/trade-api/v2"
    if marker in raw:
        host = raw.split(marker, 1)[0]
        trade_base = f"{host}{marker}"
        return host, trade_base
    return raw, f"{raw}{marker}"


KALSHI_API_BASE, KALSHI_TRADE_API_V2_BASE = _normalize_kalshi_api_base(_KALSHI_API_BASE_RAW)
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

# ── Supabase Client (Service Role — bypasses RLS) ──
supa: SupabaseClient | None = None
USER_ID = None

# ── pgvector RAG is handled via news_rag.query_news() — no local DB client needed ──

try:
    if SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY:
        supa = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        log.info("Supabase service-role client initialized.")
    else:
        log.warning("Supabase not configured (missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY).")
    
    # ── Fetch User ID for RLS Bypass ──
    # The frontend logs in as sigey2@illinois.edu. We need this UUID to insert rows
    # so they pass Row Level Security (RLS) policies and appear in the UI.
    if supa is not None:
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


def _model_yes_probability(model: Any, price_dollars: float) -> float:
    """
    Adapter for common sklearn/lightgbm-style models.
    Contract: feed current price, get P(YES).
    """
    x = np.array([[float(price_dollars)]], dtype=float)

    if hasattr(model, "predict_proba"):
        probs = model.predict_proba(x)
        try:
            return float(probs[0][1])
        except Exception:
            return float(probs[0])

    if hasattr(model, "predict"):
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

    price = _extract_yes_mid_dollars(ticker_message)
    if price is None:
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

    prob_yes = _model_yes_probability(model, price)

    side: Optional[str] = None
    if prob_yes >= CRYPTO_SIGNAL_YES_THRESHOLD:
        side = "YES"
    elif prob_yes <= CRYPTO_SIGNAL_NO_THRESHOLD:
        side = "NO"

    if side is None:
        return {"trade_signal": None}

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

    spot_price = _fetch_alpaca_spot_price(asset)
    if spot_price is None:
        signal_with_resolution["spot_price_dollars"] = None
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
            "execution_result": {"status": "skipped", "reason": "cooldown"},
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
            "execution_result": {"status": "skipped", "reason": "edge_below_threshold"},
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
        return {
            "trade_signal": signal_with_resolution,
            "resolved_market_ticker": resolved_ticker,
            "final_edge": final_edge,
            "execution_result": {"status": "error", "detail": str(exc)},
        }

    status = str(exec_res.get("status") or "").lower()
    if status not in ("ok", "open", "resting", "filled", "accepted", "success"):
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
            "execution_result": exec_res,
        }

    _TRADED_TICKER_LAST_TS[resolved_ticker] = time.time()

    confidence = float(prob_outcome)
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
            "execution_result": exec_res,
        },
    )

    return {
        "trade_signal": signal_with_resolution,
        "resolved_market_ticker": resolved_ticker,
        "final_edge": final_edge,
        "execution_result": exec_res,
    }


def build_crypto_graph():
    workflow = StateGraph(CryptoAgentState)
    workflow.add_node("evaluate_crypto_edge", evaluate_crypto_edge)
    workflow.add_node("market_resolution", market_resolution)

    workflow.add_edge(START, "evaluate_crypto_edge")
    workflow.add_edge("evaluate_crypto_edge", "market_resolution")
    workflow.add_edge("market_resolution", END)

    return workflow.compile()


async def crypto_worker_loop() -> None:
    """
    Persistent, autonomous worker: await Kalshi WS ticker messages forever and
    run the LangGraph evaluation pipeline per message.
    """
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

    graph = build_crypto_graph()
    log.info("Crypto worker started; awaiting Kalshi ticker updates…")

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

            final_state: dict = {}
            for output in graph.stream(initial_state):
                final_state.update(output)

            _ = final_state
    finally:
        listener_task.cancel()
        with contextlib.suppress(Exception):
            await listener_task


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
    log.info("Starting Orchestrator (mode=%s)…", ORCHESTRATOR_MODE)
    try:
        if ORCHESTRATOR_MODE == "market_sentiment":
            asyncio.run(heartbeat_loop())
        else:
            asyncio.run(crypto_worker_loop())
    except KeyboardInterrupt:
        log.info("Orchestrator shutting down gracefully.")
        log_to_supabase("orchestrator", "Shutdown (KeyboardInterrupt).", level="WARN")
