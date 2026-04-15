"""
Pydantic schemas for all FastAPI response models.
Keeps the API layer typed, validated, and self-documenting (Swagger UI).
"""

from pydantic import BaseModel
from typing import Optional, List, Dict
from datetime import datetime


# ─── Generic ─────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    timestamp: datetime
    version: str = "1.0.0"


# ─── Positions & PnL ─────────────────────────────────────────────────────────

class Position(BaseModel):
    ticker: str
    engine: str        # e.g. "weather_maker", "nba_props", "f1_telemetry"
    side: str          # "YES" or "NO"
    contracts: int
    avg_cost_cents: float
    current_price_cents: Optional[float] = None
    unrealized_pnl_cents: Optional[float] = None
    opened_at: Optional[datetime] = None


class PnLSummary(BaseModel):
    total_paper_trades: int
    winning_trades: int
    win_rate_pct: float
    total_pnl_cents: float
    avg_edge_pct: float
    largest_win_cents: float
    largest_loss_cents: float
    as_of: datetime


# ─── Scanner Opportunities ───────────────────────────────────────────────────

class Opportunity(BaseModel):
    engine: str
    ticker: str
    title: str
    action: str          # "BUY YES" | "BUY NO"
    my_prob: float
    kalshi_price: float
    edge_pct: float
    kelly_bet_cents: float
    kalshi_url: Optional[str] = None
    reasoning: Optional[str] = None
    detected_at: Optional[datetime] = None


# ─── Weather ─────────────────────────────────────────────────────────────────

class NWSReading(BaseModel):
    city: str
    date: str            # YYYY-MM-DD
    observed_high_f: Optional[float] = None
    forecast_high_f: Optional[float] = None
    nws_station: Optional[str] = None
    fetched_at: datetime


# ─── NBA Props ────────────────────────────────────────────────────────────────

class NBASignal(BaseModel):
    player: str
    team: str
    stat: str            # "points", "rebounds", "assists"
    line: float          # DK/BallDontLie prop line
    model_prob_over: float
    kalshi_yes_ask: Optional[float] = None
    edge_pct: Optional[float] = None
    action: Optional[str] = None  # "BUY YES" | "BUY NO" | None
    injury_flag: bool = False
    game_date: Optional[str] = None
    detected_at: Optional[datetime] = None


# ─── F1 ──────────────────────────────────────────────────────────────────────

class F1Signal(BaseModel):
    driver: str
    team: str
    event: str
    session: str         # "Qualifying", "Race"
    signal_type: str     # "podium", "fastest_lap", "dnf_risk"
    model_prob: float
    kalshi_yes_ask: Optional[float] = None
    edge_pct: Optional[float] = None
    action: Optional[str] = None
    key_metric: Optional[str] = None  # e.g. "sector_z_score: -1.8σ"
    detected_at: Optional[datetime] = None


# ─── Shadow Performance ──────────────────────────────────────────────────────

class ShadowThreshold(BaseModel):
    yes: float
    no: float


class ShadowFreshness(BaseModel):
    asset: str
    latest_bar: Optional[datetime] = None
    age_hours: Optional[float] = None
    is_stale: Optional[bool] = None


class ShadowSummary(BaseModel):
    evaluated_count: int
    considered_count: int
    dead_zone_count: int
    hit_rate: Optional[float] = None
    brier_score: Optional[float] = None
    virtual_pnl_pct: float


class ShadowPerformancePoint(BaseModel):
    timestamp: str
    asset: str
    market_ticker: str
    probability_yes: float
    threshold_side: Optional[str] = None
    threshold_triggered: bool
    current_price: float
    next_hour_price: float
    realized_yes: int
    shadow_outcome: str
    correct: bool
    virtual_return_pct: float


class ShadowPerformanceResponse(BaseModel):
    domain: str
    hours: int
    generated_at: datetime
    thresholds: Dict[str, ShadowThreshold]
    summary: ShadowSummary
    freshness: Dict[str, ShadowFreshness]
    series: List[ShadowPerformancePoint]
