"""
FastAPI Main — Thin API layer over the Kalshi Edge System.

Does ZERO business logic — only queries Supabase or the in-memory
scanner cache and returns typed JSON. All heavy lifting stays in the
background_scanner.py and engine modules.

Run locally:
    uvicorn api.main:app --reload --port 8000

Then visit: http://localhost:8000/docs  (Swagger UI — auto-generated)
"""

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from api.schemas import (
    HealthResponse, Position, PnLSummary,
    Opportunity, NWSReading, NBASignal, F1Signal,
)
from api.dependencies import get_supabase, get_scanner_cache

# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Kalshi Edge API",
    description="Thin API layer over the Kalshi prediction engine. Paper trading only until 200+ trade +EV proof.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS ─────────────────────────────────────────────────────────────────────
# Allow Vite (localhost:5173) and any future React frontend
import yaml
_settings_path = Path(__file__).parent.parent / "config" / "settings.yaml"
try:
    with open(_settings_path) as f:
        _cfg = yaml.safe_load(f)
    _cors_origins = _cfg.get("api", {}).get("cors_origins", ["*"])
except Exception:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 1: /api/health
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health():
    """Liveness check. Returns 200 if the API process is running."""
    return HealthResponse(status="ok", timestamp=datetime.now(timezone.utc))


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 2: /api/opportunities
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/opportunities", response_model=List[Opportunity], tags=["Scanner"])
async def get_opportunities(
    engine: Optional[str] = Query(None, description="Filter by engine name"),
    min_edge: float = Query(0.0, description="Minimum edge % to return"),
    cache: dict = Depends(get_scanner_cache),
):
    """
    Returns the latest scanner opportunities from the in-memory cache.
    The background_scanner refreshes this every scan cycle.
    """
    opps = cache.get("opportunities", [])
    if engine:
        opps = [o for o in opps if o.get("engine", "").lower() == engine.lower()]
    if min_edge > 0:
        opps = [o for o in opps if o.get("edge_pct", 0) >= min_edge]
    return opps


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 3: /api/positions
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/positions", response_model=List[Position], tags=["Portfolio"])
async def get_positions(
    engine: Optional[str] = Query(None, description="Filter by engine name"),
    supabase=Depends(get_supabase),
):
    """Open paper trade positions from Supabase."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        q = supabase.table("paper_trades").select("*").eq("status", "open")
        if engine:
            q = q.eq("engine", engine)
        result = q.execute()
        return result.data or []
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4: /api/pnl_summary
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/pnl_summary", response_model=PnLSummary, tags=["Portfolio"])
async def get_pnl_summary(supabase=Depends(get_supabase)):
    """Aggregated paper PnL statistics across all closed trades."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        result = supabase.table("paper_trades").select("*").eq("status", "closed").execute()
        trades = result.data or []

        if not trades:
            return PnLSummary(
                total_paper_trades=0, winning_trades=0, win_rate_pct=0.0,
                total_pnl_cents=0.0, avg_edge_pct=0.0,
                largest_win_cents=0.0, largest_loss_cents=0.0,
                as_of=datetime.now(timezone.utc),
            )

        pnls = [t.get("pnl_cents", 0) for t in trades]
        edges = [t.get("edge_pct", 0) for t in trades]
        wins = [p for p in pnls if p > 0]

        return PnLSummary(
            total_paper_trades=len(trades),
            winning_trades=len(wins),
            win_rate_pct=round(len(wins) / len(trades) * 100, 1),
            total_pnl_cents=round(sum(pnls), 2),
            avg_edge_pct=round(sum(edges) / len(edges), 2) if edges else 0.0,
            largest_win_cents=max(pnls) if pnls else 0.0,
            largest_loss_cents=min(pnls) if pnls else 0.0,
            as_of=datetime.now(timezone.utc),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 5: /api/nws_weather
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/nws_weather", response_model=List[NWSReading], tags=["Weather"])
async def get_nws_weather(
    city: Optional[str] = Query(None, description="Filter by city name"),
    cache: dict = Depends(get_scanner_cache),
):
    """
    Latest NWS temperature readings used by the weather maker engine.
    Keyed by city name. Returns the observed/forecast highs.
    """
    readings = cache.get("nws_readings", {})
    result = []
    for city_name, data in readings.items():
        if city and city_name.lower() != city.lower():
            continue
        result.append(NWSReading(
            city=city_name,
            date=data.get("date", ""),
            observed_high_f=data.get("observed_high_f"),
            forecast_high_f=data.get("forecast_high_f"),
            nws_station=data.get("nws_station"),
            fetched_at=data.get("fetched_at", datetime.now(timezone.utc)),
        ))
    return result


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 6: /api/nba_props
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/nba_props", response_model=List[NBASignal], tags=["Sports"])
async def get_nba_props(
    min_edge: float = Query(0.0),
    injury_only: bool = Query(False, description="Only return injury-repriced signals"),
    cache: dict = Depends(get_scanner_cache),
):
    """Latest NBA player prop signals from the NBAEngine."""
    signals = cache.get("nba_signals", [])
    if min_edge > 0:
        signals = [s for s in signals if abs(s.get("edge_pct", 0)) >= min_edge]
    if injury_only:
        signals = [s for s in signals if s.get("injury_flag")]
    return signals


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 7: /api/f1_signals
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/f1_signals", response_model=List[F1Signal], tags=["Sports"])
async def get_f1_signals(
    min_edge: float = Query(0.0),
    cache: dict = Depends(get_scanner_cache),
):
    """Latest F1 telemetry-derived signals from the F1Engine."""
    signals = cache.get("f1_signals", [])
    if min_edge > 0:
        signals = [s for s in signals if abs(s.get("edge_pct", 0)) >= min_edge]
    return signals


# ── Dev entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
    )
