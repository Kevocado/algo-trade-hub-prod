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

from tradehub.api.schemas import (
    HealthResponse, Position, PnLSummary,
    Opportunity, NWSReading, ShadowPerformanceResponse,
)
from tradehub.api.dependencies import get_supabase, get_scanner_cache
from tradehub.api.frontend import mount_frontend
from tradehub.scripts.shadow_performance import build_shadow_timeline_response
from tradehub.sports.scorecard import reviewer_scorecard

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
# ENDPOINT 8: /api/shadow-performance
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/shadow-performance", response_model=ShadowPerformanceResponse, tags=["Shadow"])
async def get_shadow_performance(
    domain: str = Query("crypto", description="Domain to visualize; currently only crypto is supported"),
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
):
    try:
        return build_shadow_timeline_response(domain=domain, hours=hours)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/track-record (served via the service-role client, so the
# owner-only RLS on track_record never has to be opened to the anon key)
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/track-record", tags=["Track Record"])
async def get_track_record(supabase=Depends(get_supabase)):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = supabase.table("track_record").select("*").order("engine").execute()
    return result.data or []


# ════════════════════════════════════════════════════════════════════════════
# Sports edges (rollout step 7): candidate edges with review verdicts and links
# ════════════════════════════════════════════════════════════════════════════
_TIER_ORDER = {"top_pick": 0, "flagged": 1, "unreviewed": 2, "filtered": 3}
_EDGE_FIELDS = ("sport", "kind", "side", "entry_price", "maker", "home", "away", "start_utc", "game_id",
                "tier", "candidate", "reject_reasons", "review", "engine_version")
_SPORTS_ENGINES = {"nfl": "sports_nfl", "cfb": "sports_cfb"}
SPORTS_PAGE_MAX = 200
SPORTS_PAGE_DEFAULT = 100
SPORTS_REVIEW_SCAN = 5000


def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > SPORTS_PAGE_MAX or offset < 0:
        raise HTTPException(status_code=422, detail=f"limit must be 1..{SPORTS_PAGE_MAX} and offset >= 0")
    return limit, offset


@app.get("/api/sports-edges", tags=["Sports"])
def get_sports_edges(
    sport: str | None = None,
    tier: str | None = None,
    limit: int = SPORTS_PAGE_DEFAULT,
    offset: int = 0,
    supabase=Depends(get_supabase),
):
    """Upcoming SPORTS edges (Top Picks first) plus the reviewer keep-or-drop scorecard.

    Filtered and paginated: the kalshi_edges table is never cleaned by sport alone and the
    season's rows accumulate, so an unbounded select would grow with the schedule. `sport` and
    `tier` are pushed into the query; `total` is the count AFTER filtering but BEFORE paging,
    so the UI can say "20 of 240" rather than guessing.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    if sport is not None and sport not in _SPORTS_ENGINES:
        raise HTTPException(status_code=422, detail=f"sport must be one of {sorted(_SPORTS_ENGINES)}")
    if tier is not None and tier not in _TIER_ORDER:
        raise HTTPException(status_code=422, detail=f"tier must be one of {sorted(_TIER_ORDER)}")
    limit, offset = _page(limit, offset)

    now = datetime.now(timezone.utc)

    def base_query():
        q = supabase.table("kalshi_edges").select("*").eq("edge_type", "SPORTS")
        if sport is not None:
            q = q.eq("engine", _SPORTS_ENGINES[sport])
        return q

    filtered = base_query()
    if tier is not None:
        # tier lives in raw_payload, so it cannot be filtered by the database; narrow in Python
        # and count there, then page. Bounded by the review scan cap rather than the table.
        candidates = [r for r in (filtered.execute().data or []) if _tier_of(r) == tier]
        candidates = [r for r in candidates if _is_upcoming(r, now)]
        total = len(candidates)
        rows = candidates[offset:offset + limit]
    else:
        rows_all = base_query().execute().data or []
        upcoming = [r for r in rows_all if _is_upcoming(r, now)]
        total = len(upcoming)
        rows = upcoming[offset:offset + limit]

    edges = []
    for row in rows:
        raw = row.get("raw_payload") or {}
        edges.append({
            "market_id": row["market_id"], "title": row.get("title"), "our_prob": row.get("our_prob"),
            "market_prob": row.get("market_prob"), "edge_pct": row.get("edge_pct"),
            "market_url": row.get("market_url"), "source_url": row.get("source_url"),
            # The gate is keyed on (engine, engine_version); the UI needs both to badge the row
            # and to explain which predictor version it is looking at.
            "engine": row.get("engine"),
            "gate_status": row.get("gate_status") or "SHADOW",
            **{k: raw.get(k) for k in _EDGE_FIELDS},
        })
    edges.sort(key=lambda e: (_TIER_ORDER.get(e["tier"], 9), -float(e["edge_pct"] or 0)))

    reviews = (supabase.table("sports_reviews").select("*").eq("status", "ok")
               .limit(SPORTS_REVIEW_SCAN).execute().data or [])
    settled = (supabase.table("predictions").select("market_ticker,result")
               .in_("engine", sorted(_SPORTS_ENGINES.values())).eq("status", "SETTLED")
               .limit(SPORTS_REVIEW_SCAN).execute().data or [])
    results = {r["market_ticker"]: r["result"] for r in settled}
    return {
        "as_of": now.isoformat(), "edges": edges, "total": total, "limit": limit, "offset": offset,
        "reviewer_scorecard": reviewer_scorecard(reviews, results),
    }


def _tier_of(row: dict) -> str | None:
    return ((row.get("raw_payload") or {}).get("tier"))


def _is_upcoming(row: dict, now: datetime) -> bool:
    """A row with no parsable start_utc is not upcoming and is never shown."""
    start = (row.get("raw_payload") or {}).get("start_utc")
    if not start:
        return False
    try:
        return datetime.fromisoformat(start) > now
    except (TypeError, ValueError):
        return False


# ── War Room SPA (mounted last so every /api route above wins) ─────────────
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))
mount_frontend(app, FRONTEND_DIST)


# ── Dev entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "tradehub.api.main:app",
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
        reload=True,
    )
