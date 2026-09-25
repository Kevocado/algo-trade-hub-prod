"""Deterministic candidate filter (spec §3.2 stage 1): edge after fees is decided by
tradehub.edges; this adds liquidity, time-to-start and predictor calibration in the bucket."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from tradehub.edges import EdgeSuggestion
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame
from tradehub.sports.pricing import home_oriented


@dataclass(frozen=True)
class CandidateCheck:
    ok: bool
    reasons: tuple[str, ...]
    bucket: dict[str, Any] | None


def bucket_for(buckets: list[dict[str, Any]], prob: float) -> dict[str, Any] | None:
    for b in buckets:
        if b["lo"] <= prob < b["hi"] or (prob == 1.0 and b["hi"] == 1.0):
            return b
    return None


def check_candidate(
    kind: str, sm: SportsMarket, mg: MatchedGame, edge: EdgeSuggestion,
    calibration: Mapping[str, list[dict[str, Any]]], params: Mapping[str, float], now: datetime,
) -> CandidateCheck:
    reasons: list[str] = []
    q = sm.quote
    if q.yes_bid is None or q.yes_ask is None or q.yes_ask - q.yes_bid > params["max_quote_spread"] + 1e-9:
        reasons.append("wide_quote")
    if min(q.yes_bid_size, q.yes_ask_size) < params["min_resting_size"]:
        reasons.append("thin_book")
    if sm.volume < params["min_volume"]:
        reasons.append("low_volume")
    hours = (mg.game.start_utc - now).total_seconds() / 3600.0
    if hours < params["min_hours_to_start"]:
        reasons.append("starts_too_soon")
    elif hours > params["max_hours_to_start"]:
        reasons.append("starts_too_late")
    bucket = bucket_for(calibration.get(kind) or [], home_oriented(kind, sm, mg, edge.our_prob))
    if bucket is None or bucket["n"] < params["calibration_min_n"] or bucket["mean_prob"] is None:
        reasons.append("calibration_insufficient")
    elif abs(bucket["mean_prob"] - bucket["hit_rate"]) > params["calibration_max_dev"]:
        reasons.append("calibration_off")
    return CandidateCheck(ok=not reasons, reasons=tuple(reasons), bucket=bucket)
