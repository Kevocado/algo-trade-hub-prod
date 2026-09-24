"""
api_server.py — Dedicated FastAPI HTTP Server for the React Frontend
====================================================================
Serves Kalshi scanner status to the
React dashboard. The React frontend fetches its live trading data
(trades, portfolio_state, agent_logs) directly from Supabase via
real-time WebSockets — this server is ONLY for Python-computed results
that cannot come from Supabase directly.

DO NOT use mcp_server.py as the API server.
mcp_server.py is the FastMCP Alpaca trade-execution bridge (internal-only).

Boot: PYTHONPATH=. uvicorn shared.api_server:app --host 0.0.0.0 --port 8000
"""

import logging
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared import config  # noqa: E402  — loaded after sys.path fix
from supabase import create_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [API-SERVER]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(
    title="Algo-Trade-Hub API",
    description="Serves Kalshi scanner status to the React frontend.",
    version="1.0.0",
)

# ── CORS — allow the Vite dev server and production domain ──────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Supabase client (read-only queries for status endpoints) ─────────────────
supa = None
try:
    supa = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
    log.info("Supabase client initialized.")
except Exception as exc:
    log.warning("Supabase client init failed: %s", exc)


# ═══════════════════════════════════════════════════════════════════
# Health Check
# ═══════════════════════════════════════════════════════════════════

@app.get("/health", tags=["ops"])
def health():
    return {"status": "ok", "timestamp": datetime.now(timezone.utc).isoformat()}


# ═══════════════════════════════════════════════════════════════════
# Kalshi Scanner Status Endpoints
# ═══════════════════════════════════════════════════════════════════

@app.get("/kalshi/edges", tags=["kalshi"])
def get_kalshi_edges(
    edge_type: str = Query(default=None),
    limit: int = Query(default=20, le=100),
):
    """
    Return the latest discovered Kalshi edges from the database.
    Optionally filter by edge_type: WEATHER | MACRO | SPORTS.
    """
    if supa is None:
        raise HTTPException(status_code=503, detail="Supabase not connected.")
    try:
        query = (
            supa.table("kalshi_edges")
            .select("*")
            .order("discovered_at", desc=True)
            .limit(limit)
        )
        if edge_type:
            query = query.eq("edge_type", edge_type.upper())
        res = query.execute()
        return res.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.get("/kalshi/macro-signals", tags=["kalshi"])
def get_macro_signals(limit: int = Query(default=20, le=100)):
    """Return recent FRED / NWS macro signals written by the slow scanner."""
    if supa is None:
        raise HTTPException(status_code=503, detail="Supabase not connected.")
    try:
        res = (
            supa.table("macro_signals")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return res.data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
