"""
FastAPI Main — Thin API layer over the Kalshi Edge System.

Does ZERO business logic — only queries Supabase or the in-memory
scanner cache and returns typed JSON. All heavy lifting stays in the
background_scanner.py and engine modules.

Run locally:
    uvicorn api.main:app --reload --port 8000

Then visit: http://localhost:8000/docs  (Swagger UI — auto-generated)
"""

import logging
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
from tradehub.gate_status import latest_gate_statuses
from tradehub.scripts.shadow_performance import build_shadow_timeline_response
from tradehub.sports.scan import edge_row, edge_sigma_score
from tradehub.sports.scorecard import reviewer_scorecard

log = logging.getLogger(__name__)

# Table -> the migration that creates it. A table that is missing is almost always a migration that
# was never applied, so the response says which one instead of forwarding PostgREST's PGRST205 dump.
# Found the hard way on 2026-09-27: /shadow, /api/positions and /api/pnl_summary were all red in
# production with an error no reader could act on.
TABLE_MIGRATIONS = {
    "signal_events": "20260415090000_signal_events_unification.sql",
    "crypto_signal_events": "20260415090000_signal_events_unification.sql",
    "paper_trades": "20260416000011_war_room_tables.sql",
    "live_opportunities": "20260416000011_war_room_tables.sql",
    "paper_signals": "20260416000011_war_room_tables.sql",
    "trade_history": "20260416000011_war_room_tables.sql",
    "scanner_runs": "20260416000011_war_room_tables.sql",
}


def _missing_table_message(table: str, exc: Exception) -> str:
    """An actionable sentence for a failure a human has to fix by applying a migration."""
    migration = TABLE_MIGRATIONS.get(table)
    detail = str(exc)
    if "PGRST205" in detail or "schema cache" in detail or "Could not find the table" in detail:
        if migration:
            extra = ""
            if table == "signal_events":
                # The rename has not been applied, so the live project still has the old name.
                extra = " The database still has crypto_signal_events under its old name."
            return (f"table '{table}' is not in the database. Apply "
                    f"market_sentiment_tool/supabase/migrations/{migration} and redeploy.{extra}")
        return f"table '{table}' is not in the database and no migration in this repo creates it."
    return detail


# ── App ─────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Algo Trade Hub API",
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
    """Open paper trade positions from Supabase.

    The ledger this reads (`paper_trades`) is created by migration 20260416000011 and has no
    writer, because the product is suggest-only (spec section 6): an empty list is the true state,
    not a fault. A table that is genuinely absent is reported as such rather than as a raw
    PostgREST dump -- a 500 here is what put a red "unavailable" on the War Room, and the reader
    could not tell a missing table from a broken query.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        q = supabase.table("paper_trades").select("*").eq("status", "open")
        if engine:
            q = q.eq("engine", engine)
        result = q.execute()
        return result.data or []
    except Exception as e:
        raise HTTPException(status_code=503, detail=_missing_table_message("paper_trades", e))


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT 4: /api/pnl_summary
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/pnl_summary", response_model=PnLSummary, tags=["Portfolio"])
async def get_pnl_summary(supabase=Depends(get_supabase)):
    """Aggregated paper PnL statistics across all closed trades.

    Suggest-only product: nothing places an order, so the ledger is empty and every figure below is
    zero. `suggest_only` is in the response so the UI can say "no orders are placed" rather than
    rendering a confident $0.00 that reads as a flat book.
    """
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
        raise HTTPException(status_code=503, detail=_missing_table_message("paper_trades", e))


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
        # The shadow timeline reads signal_events, which 20260415090000 renames into place. That
        # migration was never applied to the live project, so this 503 names it rather than
        # forwarding PostgREST's dump.
        raise HTTPException(status_code=503, detail=_missing_table_message("signal_events", exc))
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
# PostgREST caps a single response at 1000 rows whatever `limit` says, so any read that must
# see more has to page with .range() explicitly.
POSTGREST_CAP = 1000


def _page(limit: int, offset: int) -> tuple[int, int]:
    if limit < 1 or limit > SPORTS_PAGE_MAX or offset < 0:
        raise HTTPException(status_code=422, detail=f"limit must be 1..{SPORTS_PAGE_MAX} and offset >= 0")
    return limit, offset


def _fetch_all(supa, table: str, build, *, page: int = POSTGREST_CAP, cap: int | None = None,
               order: tuple[str, ...] = ("id",)) -> list[dict]:
    """Read a whole table through ordered `.range()` pages.

    A single `.execute()` returns at most PostgREST's 1000-row cap regardless of the `limit`
    asked for, so any read that must see more has to page explicitly and stop on a short page.

    The `.order()` is not decoration. PostgREST without ORDER BY returns rows in whatever order
    the query plan produces, and that order is not guaranteed to be the same between two
    requests, so `.range(0,999)` followed by `.range(1000,1999)` can repeat a row and skip
    another. On this endpoint that means a `total` that does not match the sum of the pages, and
    a keep/drop scorecard computed from a set with duplicates. `id` is the only column that is
    unique and immutable on all three tables read here, so it is the only safe ordering.
    """
    rows: list[dict] = []
    lo = 0
    while True:
        # PostgREST `Range` is inclusive of the last index, so page boundaries advance by `page`.
        chunk = build(supa.table(table)).order(*order).range(lo, lo + page - 1).execute().data or []
        rows.extend(chunk)
        if len(chunk) < page:
            return rows[:cap] if cap is not None else rows
        lo += page
        if cap is not None and len(rows) >= cap:
            return rows[:cap]


@app.get("/api/sports-edges", tags=["Sports"])
def get_sports_edges(
    sport: str | None = None,
    tier: str | None = None,
    limit: int = SPORTS_PAGE_DEFAULT,
    offset: int = 0,
    supabase=Depends(get_supabase),
):
    """Upcoming SPORTS edges (Top Picks first) plus the reviewer keep-or-drop scorecard.

    Three things matter here and each has bitten before:

    1. Every read pages with an ORDERED `.range()`. PostgREST caps a response at 1000 rows, so a
       single `.execute()` silently truncates and `total` would be a lie on a larger table — and
       without `.order()` the pages are not guaranteed to line up at all.
    2. Ranking is applied to ALL matching rows BEFORE offset/limit. Sorting after slicing ranks
       each arbitrary offset window on its own, so a `top_pick` can be stranded on a later page
       behind `filtered` rows.
    3. `tier` lives inside raw_payload and cannot be filtered by the database, so that one
       filter is applied in Python — but the upcoming/started test IS pushed into the query via
       `expires_at`, and Python re-checks it because a malformed `start_utc` must never show.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    if sport is not None and sport not in _SPORTS_ENGINES:
        raise HTTPException(status_code=422, detail=f"sport must be one of {sorted(_SPORTS_ENGINES)}")
    if tier is not None and tier not in _TIER_ORDER:
        raise HTTPException(status_code=422, detail=f"tier must be one of {sorted(_TIER_ORDER)}")
    limit, offset = _page(limit, offset)

    now = datetime.now(timezone.utc)

    def build(q):
        q = q.select("*").eq("edge_type", "SPORTS")
        if sport is not None:
            q = q.eq("engine", _SPORTS_ENGINES[sport])
        # Not-started is the cheap, indexable half of "upcoming"; start_utc inside raw_payload
        # is checked again below because it is what the reviewer/scan actually wrote.
        return q.gte("expires_at", now.isoformat())

    candidates = [r for r in _fetch_all(supabase, "kalshi_edges", build) if _is_upcoming(r, now)]
    if tier is not None:
        candidates = [r for r in candidates if _tier_of(r) == tier]

    # Rank globally, THEN page. top_pick first, then any remaining candidate, then the rest;
    # within a tier by edge_pct descending. Ranking after the slice would let each offset window
    # order itself, stranding a top_pick behind filtered rows on a later page.
    candidates.sort(key=_sports_rank)
    total = len(candidates)
    rows = candidates[offset:offset + limit]
    # Counted over the whole filtered set, before slicing. The UI needs this because a page of
    # rejects is not evidence that nothing passed: rows are ranked candidates-first, so page 2+ is
    # always the reject tail, and a page-derived count reports "all rejected" on a board that has
    # picks on page 1.
    candidate_count = sum(1 for r in candidates if _tier_of(r) != "filtered")

    # sports.scan.edge_row owns the row shape AND the honesty rules: edge_pct is the after-fee
    # edge vs the entry price (not vs market_prob, the mid), it is withheld from any row the
    # candidate filter rejected, quote_spread travels so a wide quote is visible, and a placeholder
    # engine_version is blanked rather than printed as the word "unknown".
    edges = [edge_row(row) for row in rows]

    reviews = _fetch_all(supabase, "sports_reviews",
                         lambda q: q.select("*").eq("status", "ok"), cap=SPORTS_REVIEW_SCAN)
    settled = _fetch_all(supabase, "predictions",
                         lambda q: q.select("market_ticker,result")
                         .in_("engine", sorted(_SPORTS_ENGINES.values())).eq("status", "SETTLED"),
                         cap=SPORTS_REVIEW_SCAN)
    results = {r["market_ticker"]: r["result"] for r in settled}
    return {
        "as_of": now.isoformat(), "edges": edges, "total": total, "limit": limit, "offset": offset,
        # Whole-set candidate count. A client cannot derive it from one page, and deriving it is
        # what made the "everything was rejected" banner wrong on every page after the first.
        "candidate_count": candidate_count,
        # Which ranking produced the order above, over the WHOLE filtered set rather than this page:
        # a sigma on page 3 is a sigma the sort used, and a page-local count would report `raw_edge`
        # while rows were being scored. The page states it, because claiming a confidence ranking it
        # is not applying is worse than never claiming one.
        "ranking": _ranking_mode(candidates),
        "reviewer_scorecard": reviewer_scorecard(reviews, results),
    }


def _tier_of(row: dict) -> str | None:
    return ((row.get("raw_payload") or {}).get("tier"))


def _sports_rank(row: dict) -> tuple[int, int, float]:
    """Sort key: top_pick, then any other candidate, then the rest; then the confidence score.

    A `filtered` row is one the candidate filter rejected, so it ranks below every candidate
    regardless of its edge — a large gap the filter already refused should not lead the board. That
    grouping is the outer key and the confidence score only ever orders rows WITHIN it.

    Within a tier, the sort is on `edge_sigma_score` when the feed published a sigma, because two
    equal edges at different confidences are not equal claims. The score is capped, floored and
    `None` when there is no sigma, and the fallback is the raw edge: NOT 0.0, which would sort the
    row last in its tier and read as "the least interesting pick here" — a claim, made by a
    fallback, about a row whose confidence is merely unknown.

    The stored column is `edge_pct` (this runs before `edge_row`); the same number is published to
    clients as `rank_edge_pct`, which is why the fallback is that number.
    """
    tier = _tier_of(row)
    if tier == "top_pick":
        group = 0
    elif (row.get("raw_payload") or {}).get("candidate"):
        group = 1
    else:
        group = 2
    score = edge_sigma_score(row.get("edge_pct"), (row.get("raw_payload") or {}).get("sigma"))
    if score is None:
        # A partly-publishing feed compares INCOMMENSURABLE UNITS in this one key, deliberately, and
        # the ordering it produces can INVERT the board -- not merely bias it toward the scored rows
        # at equal edge, which is how this used to be described and which undersells it. A scored
        # row's key is a z-score; an unscored row's is its edge in decimal. So the comparison is
        # score-vs-edge, not score-vs-score, and those are not two numbers on one scale: a scored
        # 2pp edge at sigma 0.001 scores 20.0 and outranks an unscored 40pp edge outright, and the
        # row that leads its tier is the one the 20.0 cap invented. The cap is the tell -- a
        # saturated score is a value the feature refused to measure precisely, and here it is
        # out-measuring a real 40pp disagreement.
        #
        # Every one of those terms is reachable: `sigma_floor` is 0.005, and a predictor publishing
        # a width of 0.1pp on a genuine edge produces exactly 20.0. So this is a latent inversion
        # that fires on the first run where one sport publishes a sigma and another row does not --
        # which is the same run on which the page's sentence starts claiming a confidence ranking.
        #
        # The alternative is inventing a sigma for the row that has none, which is the one thing
        # this feature must never do -- a made-up sigma ranks confidently off nothing, and
        # 0.10 / 0.005 is the cap. So the bias stands, it is recorded here rather than left to be
        # discovered, and the page's sentence says it out loud ("...wherever the feed publishes one,
        # and by raw edge for the rest"), because a reader comparing a 4pp z-scored row against a
        # 4pp unscored one is owed the reason one of them led. The disclosed sentence is what makes
        # this acceptable rather than a defect: the page does not claim a total order it cannot
        # deliver, it names the fallback and the fact that the two are not on one scale.
        score = float(row.get("edge_pct") or 0)
    return group, _TIER_ORDER.get(tier, 9), -score


def _ranking_mode(rows: list[dict]) -> str:
    """Which ranking the response actually used, so the page can say so.

    Reads the STORED row, not the served one, and that is not incidental: `sports.scan._edge_row` is
    what writes `raw_payload["sigma"]` at all, and `edge_row` deliberately withholds sigma from the
    payload the page receives. So this is the only place the number exists, and it is also the only
    place the ranking can honestly be described from.

    Reporting the mode rather than implying sigma always applies is the whole point: a page that
    claims to rank by confidence while ranking by raw edge is worse than one that never claimed it.

    `edge_sigma` means the score was in play for at least one row — which is exactly the condition
    under which the sort stopped being a pure raw-edge sort. A *published* sigma of zero counts,
    because it was floored and scored like any other value and the sort did use it; a page reporting
    `raw_edge` there would be describing a sort that did not happen. A *negative* sigma does not
    count, because the score is `None` for it: a corrupt value is handled exactly as an absent one
    is, so it is never the thing that put a row on the board, and a page must not claim the sort used
    confidence because one broken predictor published a negative width. An empty set reports
    `raw_edge`: nothing was ranked, so the answer that claims the least is the honest one.
    """
    for row in rows:
        if edge_sigma_score(row.get("edge_pct"), (row.get("raw_payload") or {}).get("sigma")) is not None:
            return "edge_sigma"
    return "raw_edge"


def _is_upcoming(row: dict, now: datetime) -> bool:
    """A row with no parsable start_utc is not upcoming and is never shown."""
    start = (row.get("raw_payload") or {}).get("start_utc")
    if not start:
        return False
    try:
        return datetime.fromisoformat(start) > now
    except (TypeError, ValueError):
        return False


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/jobs-scorecard (service-role read, like /api/track-record;
# jobs_scorecard keeps owner-only RLS)
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route
# added after it is shadowed and this endpoint would answer with the app shell.
#
# No limit: the table holds one row per (series, reference_month), so it is two
# rows per month of history rather than a growing event log.
# ════════════════════════════════════════════════════════════════════════════
# The scorecard's series -> the engine whose gate applies. `unemployment` is deliberately absent:
# its u3-naive-v0 baseline is not a gated engine.
SCORECARD_ENGINE = {"payrolls": "labor_nowcast"}


@app.get("/api/jobs-scorecard", tags=["Jobs Scorecard"])
async def get_jobs_scorecard(
    series: str = Query("payrolls", pattern="^(payrolls|unemployment)$"),
    supabase=Depends(get_supabase),
):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = (
        supabase.table("jobs_scorecard").select("*").eq("series", series).order("reference_month").execute()
    )
    rows = result.data or []
    if not rows:
        return rows
    # Kevin's decision: the /jobs page shows the engine's gate status next to the nowcast. The
    # scorecard is built out of band, so the status is not on the row and has to be looked up --
    # per (engine, engine_version), defaulting to SHADOW. The unemployment panel is a naive
    # baseline rather than a gated engine, so it must not borrow labor_nowcast's promotion.
    engine = SCORECARD_ENGINE.get(series)
    versions = {row.get("engine_version") for row in rows if row.get("engine_version")}
    statuses: dict[tuple[str, str], str] = {}
    if engine and versions:
        try:
            statuses = latest_gate_statuses(supabase, {(engine, version) for version in versions})
        except Exception:
            # Failing closed: no gate record means SHADOW, and a lookup error must not take the
            # whole page down when the rows themselves are readable.
            log.exception("api: jobs scorecard gate-status lookup failed")
            statuses = {}
    for row in rows:
        version = row.get("engine_version")
        row["engine"] = engine
        row["gate_status"] = statuses.get((engine, version), "SHADOW") if engine and version else "SHADOW"
    return rows


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
