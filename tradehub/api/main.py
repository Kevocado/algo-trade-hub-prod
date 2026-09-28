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
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from tradehub.core.env import load_local_env
from tradehub.api.schemas import (
    HealthResponse, Position, PnLSummary,
    Opportunity, NWSReading, ShadowPerformanceResponse,
)
from tradehub.api.dependencies import get_supabase, get_scanner_cache
from tradehub.api.frontend import mount_frontend
from tradehub.engines.cpi import CPI_MIN_TRAIN, DEFAULT_CPI_ERROR
from tradehub.engine_catalogue import engine_catalogue
from tradehub.engine_health import engine_health
from tradehub.gate_status import DEFAULT_GATE_STATUS, latest_gate_statuses
from tradehub.quarantine import QUARANTINE_MARK, QUARANTINE_NOTE, quarantine_report
from tradehub.scoreboard import current_runs, market_comparison
from tradehub.scripts.shadow_performance import MissingCredentialError, build_shadow_timeline_response
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
    "predictions": "20260416000003_predictions_ledger.sql",
    "paper_trades": "20260416000011_war_room_tables.sql",
    "live_opportunities": "20260416000011_war_room_tables.sql",
    "paper_signals": "20260416000011_war_room_tables.sql",
    "trade_history": "20260416000011_war_room_tables.sql",
    "scanner_runs": "20260416000011_war_room_tables.sql",
    "backtest_runs": "20260416000004_backtest_runs.sql",
    "kalshi_quarantine_edges": "20260428000012_kalshi_quarantine_edges.sql",
}


# How postgREST says "that table is not there". Matched on the text, never on the exception type:
# postgrest raises its own APIError, which is not a RuntimeError, so a handler that caught
# RuntimeError to find this never ran and the raw PGRST205 dump went out with a 500 instead.
_MISSING_TABLE_MARKERS = ("PGRST205", "schema cache", "Could not find the table")


def _is_missing_table(exc: Exception) -> bool:
    """True when the database does not have the table, whatever exception type carries the news."""
    detail = str(exc)
    return any(marker in detail for marker in _MISSING_TABLE_MARKERS)


# ── The three answers a failed read can have, by status and by name ────────────
# A client branches on the status; a human or a log greps the name. Both are needed, because the
# two deployment-step statuses (503 and 424) are close enough that a client that only remembers one
# of them reintroduces exactly the confusion this replaces.
_STATUS_MISSING_TABLE = 503
_STATUS_MISSING_CREDENTIALS = 424
_STATUS_INTERNAL_ERROR = 500

_CODE_MISSING_TABLE = "missing_table"
_CODE_MISSING_CREDENTIALS = "missing_credentials"
_CODE_INTERNAL_ERROR = "internal_error"

# Env var name -> what it is for. The named service in the message, the variables to set, and the
# file to set them in, all come from here, so adding a credentialed service is a one-line change
# rather than a rewrite of a sentence that has to stay in step with compose.yml.
CREDENTIAL_SOURCES: dict[str, tuple[str, ...]] = {
    "alpaca": ("ALPACA_API_KEY", "ALPACA_SECRET_KEY"),
    "supabase": ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"),
}

# Text fallback for a missing credential raised by something other than
# `tradehub.scripts.shadow_performance.MissingCredentialError` -- `market_sentiment_tool`'s
# orchestrator raises its own for the same two variables, and a helper that only understood one
# module's class would go back to guessing the moment a second caller appeared. Same reason and same
# trade-off as `_is_missing_table`: match the news wherever it is carried, and prefer the typed
# check, which is why `_is_missing_credential` tries the class first.
_CREDENTIAL_MARKERS = ("alpaca api credential", "alpaca_api_key", "supabase credential", "supabase_url")


def _is_missing_credential(exc: Exception) -> bool:
    """True when the read failed because a credential was not set.

    The typed check comes first because it is exact. The text check is the backstop, for a raise
    that did not come from here.
    """
    if isinstance(exc, MissingCredentialError):
        return True
    lowered = str(exc).lower()
    return any(marker in lowered for marker in _CREDENTIAL_MARKERS)


def _credential_variables(exc: Exception) -> tuple[str, ...]:
    """The exact variables to set, preferring what the exception says it was looking for.

    `MissingCredentialError` carries them, so the message is generated from the check that failed
    rather than from a guess at which service was involved. Anything else falls back to the table
    above, keyed off the same text that identified it.
    """
    if isinstance(exc, MissingCredentialError) and exc.variables:
        return exc.variables
    lowered = str(exc).lower()
    for service, variables in CREDENTIAL_SOURCES.items():
        if service in lowered:
            return variables
    return tuple(var for variables in CREDENTIAL_SOURCES.values() for var in variables)


def _credential_service(exc: Exception) -> str:
    """What the credentials are for, in words, for the message to open with.

    Prefers the label the exception carries. A raise that did not come from
    `MissingCredentialError` is keyed off the same text that identified it, so the sentence names a
    service rather than saying "upstream service" and leaving the reader to infer it.
    """
    carried = getattr(exc, "service", "")
    if carried:
        return str(carried)
    lowered = str(exc).lower()
    for service in CREDENTIAL_SOURCES:
        if service in lowered:
            return f"{service.title()} API"
    return "upstream API"


def _missing_credential_message(exc: Exception) -> str:
    """An actionable sentence for a failure a human fixes by setting environment variables.

    It has to name the variables and where they go, because "Missing Alpaca API credentials" is not
    an instruction: it is the name of the problem, and the operator still has to work out which
    file on which machine. `vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub service at
    all, so setting the variables alone would not be enough -- the service block has to name them
    too, exactly as it already does for `FRED_API_KEY`.

    Deliberately contains no `supabase/migrations/` path. The frontend classifies a failed read as
    "waiting on a database migration" by matching that substring
    (`market_sentiment_tool/src/lib/shadowPerformance.ts`), and an unset credential is not a
    migration. Naming one here would be the third way for this endpoint to say something false.
    """
    variables = _credential_variables(exc)
    service = _credential_service(exc)
    names = " and ".join(variables)
    compose_lines = " and ".join(f"'{name}: ${{{name}:-}}'" for name in variables)
    alias = (
        " SUPABASE_URL is also accepted as VITE_SUPABASE_URL."
        if "SUPABASE_URL" in variables
        else ""
    )
    return (
        f"This service has no {service} credentials, so the shadow timeline cannot be read. "
        f"The database is fine -- this is not a migration. "
        f"Set {names} in the stack's .env file, beside vps-stack/compose.yml.{alias} "
        f"Then add {compose_lines} to the tradehub service's environment: block, and redeploy."
    )


def _missing_table_message(table: str, exc: Exception) -> str:
    """An actionable sentence for a failure a human has to fix by applying a migration."""
    migration = TABLE_MIGRATIONS.get(table)
    detail = str(exc)
    if _is_missing_table(exc):
        if migration:
            extra = ""
            if table == "signal_events":
                # The rename has not been applied, so the live project still has the old name.
                extra = " The database still has crypto_signal_events under its old name."
            return (f"table '{table}' is not in the database. Apply "
                    f"market_sentiment_tool/supabase/migrations/{migration} and redeploy.{extra}")
        return f"table '{table}' is not in the database and no migration in this repo creates it."
    return detail


def _table_fault(table: str, exc: Exception) -> HTTPException:
    """The one place a failed read becomes an HTTP answer, for every handler that has one.

    THREE different facts, and a reader has to be able to tell them apart without reading prose:

    - the table is not in the database. A fact about the deployment, fixed by applying a
      migration. 503, `missing_table`, and the detail names the file.
    - the table is fine and a CREDENTIAL is missing. Also a fact about the deployment, fixed by
      setting environment variables -- and a completely different act. 424, `missing_credentials`,
      and the detail names the variables and the file to put them in.
    - anything else. A fact about this code. 500, `internal_error`, and the exception text.

    Three statuses, not three sentences, because the status is the one field a client can branch on
    without parsing English. Two of these are still "a human has to go and do something", and giving
    them one status is what made this undiagnosable: /api/shadow-performance served a bare
    "Missing Alpaca API credentials" string under a 500, and a reader could not tell from that
    whether the migration was still unapplied, the credentials were still unset, or the code was
    broken. All three said the same thing, and all three needed a different next step.

    424 Failed Dependency is the deliberate choice for the credential case rather than a second 503:
    it is unused anywhere in this repo, it is a real RFC 4918 code, and "this request failed because
    a dependency it needs did not succeed" is exactly the situation -- the Alpaca market-data API is
    a dependency of this endpoint, and this deployment cannot reach it. A reader who has never seen
    424 before does not need to have: the `code` below is the name, and the status is the fallback
    for a client that only looks at numbers.

    `detail` stays a plain string on all three, because the frontend reads `payload.detail` and
    hands it straight to a person (`market_sentiment_tool/src/hooks/useShadowPerformance.ts`). This
    is why classification cannot live in the body alone; the body is prose, and prose is what this
    endpoint has been reduced to.
    """
    if _is_missing_credential(exc):
        return HTTPException(
            status_code=_STATUS_MISSING_CREDENTIALS,
            detail=_missing_credential_message(exc),
            headers={"X-Error-Code": _CODE_MISSING_CREDENTIALS},
        )
    if _is_missing_table(exc):
        return HTTPException(
            status_code=_STATUS_MISSING_TABLE,
            detail=_missing_table_message(table, exc),
            headers={"X-Error-Code": _CODE_MISSING_TABLE},
        )
    return HTTPException(
        status_code=_STATUS_INTERNAL_ERROR,
        detail=str(exc),
        headers={"X-Error-Code": _CODE_INTERNAL_ERROR},
    )


# ── App ─────────────────────────────────────────────────────────────────────
# The developer-local `.env` is loaded here, in the app's lifespan, and NOT at
# import time. That placement is the whole point: a lifespan handler runs when
# uvicorn actually boots the server, so `import tradehub.api.main` -- which the
# test suite does, several times -- leaves `os.environ` alone. See
# `tradehub.core.env` for why that matters. In production this is a no-op:
# the container gets real variables from compose and ships no `.env`.
@asynccontextmanager
async def lifespan(_app: FastAPI):
    load_local_env()
    yield


app = FastAPI(
    title="Algo Trade Hub API",
    description="Thin API layer over the Kalshi prediction engine. Paper trading only until 200+ trade +EV proof.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
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
        raise _table_fault("paper_trades", e)


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
        raise _table_fault("paper_trades", e)


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
        # The one failure that is about the request rather than the database: an unsupported domain.
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        # The shadow timeline reads signal_events, which 20260415090000 renames into place. That
        # migration was never applied to the live project, so a missing table is a 503 that names
        # it. Handing every exception to _table_fault is what makes that true for the APIError
        # postgREST actually raises, not just for the RuntimeError this used to catch.
        raise _table_fault("signal_events", exc)


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

# ── CPI display (display-only, approved 2026-09-27) ─────────────────────────
CPI_ENGINE = "cpi_nowcast"
CPI_PAGE_DEFAULT = 50
CPI_PAGE_MAX = 200
# `predictions` is append-only and nothing prunes it: one row per open CPI market per scan run,
# three runs a day, forever. So the read has to be bounded, and the bound has to be visible -- a
# `total` that quietly counts only the rows we happened to read is a claim about the data, the same
# silent-truncation hazard the scoreboard's cap=200 and the edges hook's limit(100) already carry.
# Ordering by `as_of` descending means the bound drops the OLDEST history, which is the right thing
# to drop for a live display.
CPI_ROW_SCAN = 200

# The gate, and the honest reason there is no gate. `predictions` has no `gate_status` column --
# 20260416000003_predictions_ledger.sql:10 defines the table and `gate_status` is `track_record`'s,
# at line 43 of the same file -- and `build_prediction_row` (tradehub/predictions.py:41) never sets
# one. So this endpoint cannot read a gate status and does not try: a display engine is not a
# candidate for promotion, so there is nothing to check. The gate fails closed, so the value is
# SHADOW, and `gate_checked` says out loud that no gate was consulted -- because "SHADOW" on its own
# is the gate's own vocabulary and reads as "not promoted", i.e. as a verdict that was reached.
# The status is the shared fail-closed default, not a second copy of the string:
# two literals in this module is how the scan and the API would start disagreeing
# about whether an edge is tradable, which is what DEFAULT_GATE_STATUS exists to
# prevent. What makes CPI's verdict its own is CPI_GATE_CHECKED below -- the gate
# was never checked, which is not the same claim as "checked, and it said no".
CPI_GATE_STATUS = DEFAULT_GATE_STATUS
CPI_GATE_CHECKED = False
CPI_GATE_CHECKED_REASON = (
    "No gate was consulted and none is expected. cpi_nowcast is a display engine, not a candidate "
    "for promotion, and the predictions table has no gate_status column to read one from. This "
    "SHADOW is a fails-closed default, not a verdict from a gate that was checked and said no."
)

CPI_DISPLAY_REASON = (
    "Not an edge engine. CPI is shown for context only. Measured over 2026-06-01..2026-09-20 the "
    "market's Brier score was 0.0677 at 25 minutes before close and 0.0710 five days out, so it "
    "prices this series about as accurately a week ahead as in the last half hour. The market is "
    "not pricing off the Cleveland Fed nowcast, so a nowcast-based model has nothing to exploit by "
    "being early. At every lead this model is 1.33-1.43x behind the market, with negative P&L."
)

# Why a row is withheld FROM THE COMPARISON (it is never withheld from the page). A release scanned
# before its first quote has no market mid at all, which is a different fact from a market
# probability of zero -- `useMarketEdges` still fabricates that zero with `?? 0`, and the same
# "right number, wrong attribution" shape is not repeated here.
CPI_NOT_COMPARABLE = (
    "No market mid was recorded for this release, so there is no market probability to set the "
    "nowcast against. The nowcast is shown on its own; nothing here is a comparison, and a missing "
    "mid is not a market mid of zero."
)

# `fit_cpi_error` (tradehub/engines/cpi.py) returns DEFAULT_CPI_ERROR -- a CONSTANT -- whenever it
# has fewer than CPI_MIN_TRAIN training pairs, so a row's `our_prob` can come out of a hardcoded
# sigma rather than a fit. Nothing distinguished the two on the page, which is the inverse of the
# rule this endpoint is built on: a figure that was not measured is being presented as though it
# were, and the reader cannot tell. `n_train` is the honest signal, because it is what the branch in
# `fit_cpi_error` actually tested, so the flag is derived from it rather than from `sigma == 0.15`
# (which a fitted model can also return).
CPI_DEFAULT_ERROR_SIGMA = DEFAULT_CPI_ERROR.sigma
CPI_DEFAULT_ERROR_MODEL = (
    f"The error model is the default, not a fit: fewer than {CPI_MIN_TRAIN} nowcast/print pairs "
    f"were available, so the {CPI_DEFAULT_ERROR_SIGMA}pp sigma is the constant the engine falls back "
    "to rather than something measured. This row's probability comes from that default."
)

# `offset` is advertised, echoed and bounds-tested, so paging reads as supported. But the read is
# bounded at CPI_ROW_SCAN, and the window is applied to that bounded list, so any offset past the
# bound returns an empty page while `total` still says CPI_ROW_SCAN: a 200 with no rows, which is
# indistinguishable from a ledger that has none. At three scans a day the ledger passes 200 rows in
# about two weeks, so this is the normal case and not an edge case. Rejected instead of served.
CPI_PAGE_WINDOW_MAX = CPI_ROW_SCAN
CPI_PAGE_WINDOW_DETAIL = (
    f"offset + limit must be at most {CPI_PAGE_WINDOW_MAX}: the read is bounded at that many rows, "
    f"so a window past it could only ever return an empty page, and an empty page reads as a ledger "
    f"with nothing in it. Ask for a smaller limit, or start from an earlier offset."
)

# `comparable=true` keeps only the rows that carry a market mid. The page asks for it (see
# CPI_CONTEXT_ROWS in market_sentiment_tool/src/lib/cpiDisplay.ts for the count and the reasoning),
# and the filter lives HERE rather than in the component for two reasons that both come from the
# review this endpoint was built under: no rule that filters or reorders data may live in TSX, and a
# client-side filter would describe a window the response does not describe -- `total` would count
# rows the response never sent, and the page would be reporting on its own reordering rather than on
# the read. Opt-in, so an unfiltered read of the whole ledger is still available to a caller that
# wants it; the page is not the only possible reader of this endpoint.
#
# The number of rows is a low-teens count decided by the page's own request, not clamped here: this
# endpoint has no opinion about how much context a reader wants, and a clamp would make a short page
# a server-side policy the reader could not see.
CPI_COMPARABLE_HELP = (
    "comparable=true keeps only the releases that carry a market mid to set the nowcast against. "
    "Rows without one are still counted in `withheld_count` -- a shorter page is not a licence to "
    "stop saying what was withheld."
)


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
# ENDPOINT: /api/scoreboard — every engine's Brier beside the market's, and its
# distance to its own gate. Approved 2026-09-27 (spec section 9, approval 4).
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route added after it
# is shadowed and this endpoint would answer with the app shell.
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/scoreboard", tags=["Scoreboard"])
def get_scoreboard(supabase=Depends(get_supabase)):
    """Should I trust this engine? One row per engine and mode, from the current run.

    The route reads and hands over. It decides nothing.

    - The reduction is `current_runs` (`tradehub/scoreboard.py`), which is pure, so every rule
      that decides what appears is testable without a database. In particular the rule this
      endpoint exists to protect: a run whose `engine_version` carries a decision lead
      (`gas-v1-lead12h`) is an EXPERIMENT, and is excluded from the page rather than footnoted.
      The experiment stays in `backtest_runs` and stays reproducible from the CLI; presenting it
      as the engine's record would make the page wrong in the direction that flatters the engine.
    - The headline and the counts behind it are `market_comparison`, from the same module. The
      "is this engine ahead" threshold lives there, because a second copy of it here is how the
      page and the API start disagreeing with nothing downstream able to tell which one drifted.
    - Each row's `market_verdict` is `market_verdict`, also from that module, so the page renders
      a word rather than comparing ratios in TypeScript.
    - `MIN_SETTLED` is not named in this file. It rides on each row's `settled_distance` as the
      reviewer's floor, separately from the bar the gate itself stated, and the row says which
      one the verdict was made against.
    - `catalogue` is `engine_catalogue` (`tradehub/engine_catalogue.py`), also pure. It is the
      answer to "which engines does this product have, and what does each one claim to predict",
      and it joins that to the rows above rather than replacing them: an engine with no backtest
      run is in the response with `measured: false` rather than absent, because an absent engine
      reads as "this engine has nothing to show" and that is a claim nobody made. Its counts are
      here for the same reason the headline's are -- `engines_not_measured` is a subtraction on a
      set, and a page that does it at render time does it in a component.

    The one lookup this endpoint makes, and the one it does not:

    - `promotion_status` is `latest_gate_statuses` (`tradehub/gate_status.py`) -- the SAME
      function the scan uses, keyed on `(engine, engine_version)`, requiring the latest backtest
      for that exact version AND a `track_record` row to both say PROMOTED, and failing closed
      otherwise. `row["gate_status"]` is NOT that: it is what `check_promotion_gate` returned when
      the run was recorded (`tradehub/track_record.py:126`), which never consults `track_record`
      at all. So a run can carry `gate_status: "PROMOTED"` while the engine is not promoted, and
      rendering that under the word PROMOTED reads as a promotion to a human. Both travel, both
      labelled. The alternative -- a private reimplementation here -- is what that function's
      docstring exists to prevent, and the extra reads are the price of there being one answer
      about whether an edge is tradable rather than two.
    - The verdict is per `(engine, engine_version)` while a row is per `(engine, mode)`, so both
      rows of one engine carry the same verdict. That is the gate's own key, not a convenience.
    - **A failed lookup fails closed and is announced.** `SHADOW` is the safe direction -- it
      cannot make a non-tradable edge look tradable -- but a column of SHADOW badges that were
      never verified is still a claim, so `promotion_lookup_failed` says so and the page says it
      too. Same shape as the read failure below, applied to a read that is not the whole story.

    Two decisions in the read itself:

    - **The read is paged, with no cap.** PostgREST caps one response at 1000 rows, so a single
      `.execute()` silently truncates; and a cap is worse, because the cap and the reduction pull
      in opposite directions. `backtest_runs` grows by one row per recorded CLI run, so the 200
      newest are overwhelmingly gas: a monthly-cadence engine whose only recent run falls outside
      that window is not rendered slightly stale, it is ABSENT -- and an absent engine reads as
      "this engine has no settled contracts", which is a claim about the engine. The table is one
      row per recorded run rather than a growing event log, so paging it whole is cheap, and
      `runs_read` travels in the response so a truncation is visible if one is ever added.
    - **A read failure is a 503, never an empty scoreboard.** `_fetch_all` raises on the first
      failing page, including a later one, so a partial read cannot be mistaken for a complete
      one: either the whole ledger reduces or the page says it could not be read. The two are
      distinguishable in the body as well as in the status -- a failure carries `detail` and no
      `rows` at all, and a genuinely empty ledger returns 200 with `rows: []` and its own
      headline. One sentinel, one meaning.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    try:
        runs = _fetch_all(supabase, "backtest_runs", lambda q: q.select("*"))
    except Exception as e:
        raise HTTPException(status_code=503, detail=_missing_table_message("backtest_runs", e))
    rows = current_runs(runs)

    # The shared lookup, asked once for the pairs this board actually has. The version is part of
    # the key and is dropped from neither side: a version that is not promoted must not inherit
    # another version's promotion.
    pairs = {(r["engine"], r["engine_version"]) for r in rows if r["engine"] and r["engine_version"]}
    promotion: dict[tuple[str, str], str] = {}
    promotion_lookup_failed = False
    if pairs:
        try:
            promotion = latest_gate_statuses(supabase, pairs)
        except Exception:
            # Failing closed, and saying so. Same handling as /api/jobs-scorecard below, for the
            # same reason: the rows are readable, so a failure here must not take the page down,
            # and must not be mistaken for a verdict.
            log.exception("api: scoreboard promotion-gate lookup failed")
            promotion_lookup_failed = True
    for row in rows:
        row["promotion_status"] = promotion.get(
            (row["engine"], row["engine_version"]), DEFAULT_GATE_STATUS
        )

    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "runs_read": len(runs),
        "rows": rows,
        # True when the promotion verdict below could not be read. Every row then reads SHADOW,
        # which is the fail-closed default and NOT a measurement.
        "promotion_lookup_failed": promotion_lookup_failed,
        # Distinct engines, because `rows_*` below counts (engine, mode) pairs and one name under
        # two labels is what made a single number unable to say what it was counting.
        "engines": len({row["engine"] for row in rows}),
        **market_comparison(rows),
        # Built LAST, because each entry carries its rows whole and those rows have to carry
        # `promotion_status` -- an entry built before the loop above would ship a gate the board
        # does not show, which is a right number under the wrong label on a page about labels.
        "catalogue": engine_catalogue(rows),
    }


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
        row["gate_status"] = (
            statuses.get((engine, version), DEFAULT_GATE_STATUS)
            if engine and version
            else DEFAULT_GATE_STATUS
        )
    return rows


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/cpi-display (the nowcast against the market, as context)
# ════════════════════════════════════════════════════════════════════════════
def _cpi_display_row(row: dict) -> dict:
    """One `predictions` row as a display row. Nothing measured is changed, and nothing missing is
    invented: a figure the scan did not record stays null, and the row says why it cannot be
    compared rather than being passed off as a comparison."""
    raw = row.get("raw_payload") or {}
    market_prob = row.get("market_prob")
    comparable = market_prob is not None
    n_train = raw.get("n_train")
    # The same branch `fit_cpi_error` took, decided from the number it branched on. `sigma` is NOT
    # used: the default's own sigma is a value a fitted model can also produce, so comparing against
    # it would label some fitted rows "default" and never miss a default one. An absent n_train
    # means the scan did not record it, which is not evidence the model was fitted -- so the flag is
    # `None` and the row says the count is unknown rather than asserting either way.
    default_error_model: bool | None = None if n_train is None else int(n_train) < CPI_MIN_TRAIN
    return {
        "market_ticker": row.get("market_ticker"),
        "our_prob": row.get("our_prob"),
        # The quote mid, the same quantity the sports endpoint reports. It is NOT what an edge would
        # be measured against, and `edge_pct` below is null so nothing here implies otherwise.
        "market_prob": market_prob,
        # Present and always null. A reader shown a probability and a market price will assume an
        # opportunity unless something says otherwise, and a null says it in the shape a client
        # checks rather than in prose it might ignore. There is no edge here to publish: spec 5a
        # records the outcome as REFUTED, not weak.
        "edge_pct": None,
        "nowcast": raw.get("nowcast"),
        "nowcast_obs": raw.get("nowcast_obs"),
        "sigma": raw.get("sigma"),
        # The training-set size, because a sigma printed without it is a number of unknown origin.
        "n_train": n_train,
        "default_error_model": default_error_model,
        "default_error_model_reason": CPI_DEFAULT_ERROR_MODEL if default_error_model else None,
        "hours_to_close": raw.get("hours_to_close"),
        # `as_of`, not `updated_at`: the ledger's timestamp is the engine's own and is NOT NULL, and
        # `predictions` has no `updated_at` column at all. `status` travels so a settled row from a
        # market that closed last month cannot render as if it were live. The result is deliberately
        # NOT published: a bare yes/no beside a probability reads as our win, which is a claim the
        # ledger supports only through the settlement job, not here.
        "as_of": row.get("as_of"),
        "status": row.get("status"),
        "comparable": comparable,
        "withheld_reason": None if comparable else CPI_NOT_COMPARABLE,
        "gate_status": CPI_GATE_STATUS,
        "gate_checked": CPI_GATE_CHECKED,
    }


@app.get("/api/cpi-display", tags=["CPI"])
def get_cpi_display(
    limit: int = Query(CPI_PAGE_DEFAULT, ge=1, le=CPI_PAGE_MAX),
    offset: int = Query(0, ge=0),
    comparable: bool = Query(False, description=CPI_COMPARABLE_HELP),
    supabase=Depends(get_supabase),
):
    """CPI as context, not as an opportunity.

    Approved display-only on 2026-09-27 (spec section 9, approval 3, quoted verbatim from
    docs/superpowers/specs/2026-09-27-hub-redesign.md:505: "DISPLAY ONLY. Show the nowcast against
    the market for context; not an edge engine."), on the evidence in 5a: the market's
    Brier at 5 days out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices this
    series about as accurately a week ahead as in the last half hour. It is not pricing off the
    nowcast, so a nowcast-based model has nothing to exploit by being early, and at every lead we
    are 1.33-1.43x behind with negative P&L.

    So this reads the `predictions` rows -- which carry the nowcast, our probability and the market
    mid -- and labels them. The label is in the payload and not only in the page, because
    `predictions` is owner-only under RLS, so this endpoint is the only route by which these numbers
    reach a browser: a label that only existed in a component would not travel with the data.

    Six claims this response makes about itself, and each of them is a claim a reader would
    otherwise have to assume:

    * `mode`/`edge_pct`/null: this is context, there is no edge, and nothing here implies otherwise.
    * `withheld_count` and each row's `withheld_reason`: a release with no market mid is shown, and
      says it is not a comparison. The row is withheld from the comparison, never from the page --
      an engine that loses stays visible.
    * `truncated`: a read bounded at CPI_ROW_SCAN says so rather than letting `total` read as the
      whole set.
    * `n_train` with `default_error_model`: a probability produced from the engine's FALLBACK sigma
      says so, because a constant and a fit are otherwise the same figure on the page.
    * `read_count`: how many rows the bounded read examined, which is NOT `total` once `comparable`
      has removed any. The page's "N rows read" comes from here.
    * `comparable_only`: whether this response applied that filter, echoed because a client must be
      able to tell a short page from a filter it did not know about.

    `comparable=true` is the one that answers the complaint this page was built for: on 2026-09-28
    the unfiltered read returned 50 rows of which 69 across the read had no market mid at all, so
    the page was mostly rows with nothing to compare. A row with no market mid has no comparison in
    it, so for a page whose whole job is the comparison it is padding -- but it is still WITHHELD
    rather than discarded, and `withheld_count` still says how many. Filtering happens before the
    window, so `offset`/`limit` index the comparable set, and `total` is the count of what the
    response describes.

    A failed read is a 503, never a 200 with an empty page: "not measured" and "measured, and there
    is nothing there" are different facts and must not look alike. For the same reason a `offset` that
    would read past the bound is a 422 and not an empty window.
    """
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    # The window is checked against the READ'S bound, before the read, because after it an offset
    # past the bound is a well-formed 200 whose `rows` is empty -- the one shape a client cannot tell
    # from a ledger with nothing in it.
    if offset + limit > CPI_PAGE_WINDOW_MAX:
        raise HTTPException(status_code=422, detail=CPI_PAGE_WINDOW_DETAIL)
    try:
        # `as_of` descending, with `_fetch_all` appending `id` as the tiebreak so the pages line up
        # (PostgREST without a stable order can repeat one row and skip another between pages).
        # cap is the bound plus one, so "there are more rows" is something the read established
        # rather than something it guessed from filling the cap.
        read = _fetch_all(
            supabase, "predictions",
            lambda q: q.select("*").eq("engine", CPI_ENGINE).order("as_of", desc=True),
            page=CPI_ROW_SCAN, cap=CPI_ROW_SCAN + 1,
        )
    except Exception as exc:
        # Deliberately not swallowed into an empty list: an empty page means the nowcast has no
        # markets, and a reader who is told that when the database was never reached has been told
        # something false. The detail names the migration, because a 500 with PostgREST's raw dump
        # is what put a red "unavailable" on the War Room.
        raise HTTPException(status_code=503, detail=_missing_table_message("predictions", exc))
    truncated = len(read) > CPI_ROW_SCAN
    read = read[:CPI_ROW_SCAN]
    # Built once for the whole read, so the count and the rows come from the same rule rather than
    # from two copies of "is this row comparable". Counted before any filter and before slicing: a
    # client cannot derive it from one page, and deriving it is what makes an offset window report
    # on itself instead of on the set.
    display = [_cpi_display_row(r) for r in read]
    read_count = len(display)
    # Counted BEFORE the `comparable` filter, which is the whole point. Counting after it would
    # report zero whenever the filter is on -- and that is the one number a reader must never be
    # able to lose, because a short page that also says "nothing was withheld" is a page that is
    # padded and silent about it at the same time.
    withheld_count = sum(1 for r in display if not r["comparable"])
    # The filter runs BEFORE the window, so `offset`/`limit` index the comparable set rather than
    # the raw read. Paging past the withheld rows is what makes the short page reach the same
    # comparable row a reader would have found by scrolling the long one.
    if comparable:
        display = [r for r in display if r["comparable"]]
    # The count of what THIS RESPONSE DESCRIBES, and therefore not a count of what was read once
    # the filter has run. `read_count` is the latter, and `read_count == total + withheld_count`
    # whenever `comparable` is on.
    total = len(display)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mode": "display",
        "engine": CPI_ENGINE,
        "suggest_only": True,
        "reason": CPI_DISPLAY_REASON,
        "edge_pct": None,
        "gate_status": CPI_GATE_STATUS,
        "gate_checked": CPI_GATE_CHECKED,
        "gate_checked_reason": CPI_GATE_CHECKED_REASON,
        "row_order": "as_of desc",
        "rows": display[offset:offset + limit],
        # The number of rows in the set this response describes. When `truncated` is true it is a
        # floor, not a count.
        "total": total,
        "truncated": truncated,
        "withheld_count": withheld_count,
        "read_count": read_count,
        "comparable_only": comparable,
        "limit": limit,
        "offset": offset,
    }


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/engine-health (which edge types are fed by a STOPPED engine)
#
# Registered BEFORE mount_frontend below: the SPA is mounted at "/", so a route added after it is
# shadowed and this endpoint would answer with the app shell. Same ordering rule as
# /api/scoreboard and /api/jobs-scorecard above.
#
# No database, and that is the design rather than a shortcut. This endpoint's subject is whether an
# engine RAN, and whether an engine ran is a written ruling, not a fact about a table: nothing in
# `kalshi_edges` distinguishes "the engine looked and found nothing" from "the engine never got as
# far as looking", because in the second case there is no row to look at. Inferring the state from
# the absence of rows would be the defect restated one layer up -- a quiet board relabelled broken
# the first time a market was thin, and a broken engine relabelled quiet every time it was quiet by
# accident. So the ruling is `engine_health` (pure, in the same language as the engines it rules
# on) and the counts that describe it are computed here rather than in the page.
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/engine-health", tags=["Engine Health"])
def get_engine_health():
    """Which of this product's edge types are fed by an engine that cannot run, and why.

    The defect this exists for: Kalshi's API stopped sending `yes_ask`, and the Tier-1 real-edge
    weather and macro engines still read it with a `0` default. Every market they fetch reads as a
    0c quote, so they skip all of them, publish nothing and raise nothing -- the failure is closed,
    which is why nothing was ever written that was wrong. What was wrong was the DISPLAY: the
    Weather tab rendered "No high-confidence edges detected in weather", and that is a finding. It
    was never looked for. The same ambiguity was already ruled on for CPI, where a withheld row
    that vanished silently read as an engine that had been retired
    (`market_sentiment_tool/src/lib/displayOnlyEngines.ts`); this is the same rule for a run that
    produces no row to withhold.

    A reader has to be able to tell three things apart, and only two of them are this endpoint's
    business:

      * an engine that RAN and found nothing -- a measurement, and the empty board is the finding;
      * an engine that COULD NOT RUN -- nothing was measured, and this endpoint says so;
      * a read that FAILED -- nothing is known at all, which the board already renders separately
        (`edgesError` in the Prediction Lab) and which this endpoint does not participate in,
        because it reads no table and so cannot fail.

    Every edge type in `engine_health.EDGE_TYPES` appears in the response, in one state or the
    other, and the counts are computed here: `edge_types_could_not_run` is a subtraction on a set,
    and a component that does it at render time is a rule in a second language with no test on it.

    `opportunities_found` is present and null on every entry. Not an unfinished field: this
    endpoint reports whether an engine ran, and a count of what it found belongs to the read of the
    ledger, which is a different read over a different bound. A null here is the machine-readable
    half of "nothing was measured" -- and for a stopped engine, `0` would be the single most
    damaging value in the product, because it would read as a search that ran and found nothing.
    """
    return {"as_of": datetime.now(timezone.utc).isoformat(), **engine_health()}


# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/quarantine (what the repaired-but-unpublished engines measured)
#
# Registered BEFORE mount_frontend, on the same rule as every other /api route above: the SPA is
# mounted at "/", so a route added after it answers with the app shell.
#
# This is the second sink's read. It is deliberately NOT an extension of `/api/engine-health`, and
# the difference is the point of both: `/api/engine-health` says whether an engine RAN, which is a
# written ruling in `tradehub/engine_health.py` and needs no table. This one says what a repaired
# engine MEASURED, which is a fact about rows in `kalshi_quarantine_edges` and cannot be answered
# without reading them. Keeping them apart is what stops the ruling from drifting into a summary of
# whatever the table happens to hold, which would relabel a quiet engine broken and a broken one
# quiet -- the defect `engine_health` exists to prevent, arriving through the back door.
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/quarantine", tags=["Quarantine"])
def get_quarantine(
    supabase=Depends(get_supabase),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """The measured output of the quarantined Weather and Macro engines, and what of it is real.

    Every figure here comes from `tradehub/quarantine.py` and the rows, and none of it is computed
    in the client. The three counts a reader needs, and why none of them is the headline on its own:

    - **rows** -- what the scan produced. 295 on the measured run. Not a number of opportunities.
    - **opportunities** -- rows that are not a units artefact, i.e. the recommendation and the price
      on the row are the same side of the book. Still not independent opinions.
    - **independent_opportunities** -- distinct forecasts among those rows, which is the number that
      means "how many separate things did this engine actually think". 143 rows restating one GDP
      point forecast across eleven year-events is 143 rows and one opinion, and the honest headline is
      the one that says so.

    `kalshi_edges_written` is a hard `0` and is not a count of tonight's scan: there is no code path
    from a quarantined row to the trade-proposal sink. See `tradehub/quarantine.py` for the two
    independent mechanisms that hold it, and
    `tests/test_weather_macro_quarantine.py::test_the_quarantine_writes_nothing_to_the_trade_sink`
    for the proof.

    An empty table is NOT reported as `0` opportunities. A table with no rows is either a scan that
    found nothing or a migration that has not been applied, and which one it is has to be said
    rather than inferred from a count -- the same rule as `opportunities_found` on
    `/api/engine-health`, and for the same reason.
    """
    try:
        result = supabase.table("kalshi_quarantine_edges").select("*").execute()
    except Exception as exc:  # noqa: BLE001 - the one place a table read becomes an HTTP answer
        raise _table_fault("kalshi_quarantine_edges", exc) from exc

    rows = list(getattr(result, "data", None) or [])
    # Stamped by `mark_quarantine` in the scan, not recomputed here. A row's own stored
    # classification is what was measured at scan time; re-deriving it at read time would make the
    # surface's numbers depend on a rule that could change under rows nobody re-scanned.
    stamped = [dict(row, edge_kind=row.get("edge_kind"), independent=bool(row.get("independent")))
               for row in rows]

    if not stamped:
        # No rows and no classification. `rows` is 0 because the table is empty -- a real
        # measurement of an empty read -- and the OPPORTUNITY counts are null, because "no rows" is
        # not the same fact as "this engine looked and found nothing": the migration may simply not
        # be applied, and a confident 0 there would be a measurement of a search that never happened.
        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "marker": QUARANTINE_MARK,
            "quarantined": True,
            "note": QUARANTINE_NOTE,
            "rows": 0,
            "measured": False,
            "unmeasured_reason": (
                "kalshi_quarantine_edges is empty, so there is nothing to classify. Either no scan "
                "has written to it, or migration "
                f"{TABLE_MIGRATIONS['kalshi_quarantine_edges']} has not been applied. This is not a "
                "count of zero opportunities: no output has been read."
            ),
            "totals": None,
            "engines": [],
            "kalshi_edges_written": 0,
            "sink": "kalshi_quarantine_edges",
            "rows_page": [],
        }

    report = quarantine_report(stamped)
    page = stamped[offset : offset + limit]
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "marker": report["marker"],
        "quarantined": report["quarantined"],
        "note": report["note"],
        # The real measurement, and deliberately not called "opportunities".
        "rows": report["totals"]["rows"],
        "measured": True,
        "unmeasured_reason": None,
        "totals": report["totals"],
        "engines": report["engines"],
        "reasons": report["reasons"],
        "kalshi_edges_written": report["kalshi_edges_written"],
        "sink": report["sink"],
        "rows_page": page,
        "limit": limit,
        "offset": offset,
        "read_count": len(stamped),
        "truncated": offset + limit < len(stamped),
    }


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
