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
    # No per-bucket calibration test here, and that is deliberate (ruled 2026-09-27).
    #
    # This used to be: `elif abs(mean_prob - hit_rate) > calibration_max_dev` -> `calibration_off`.
    # At calibration_min_n 20 and a 10pp threshold, a *correctly calibrated* bucket trips that about
    # 37% of the time -- n=20 gives an 11.2pp standard error, so 10pp is 0.89 SD. It rejected weather
    # on a bucket with n=23 and z=1.42, which is a coin flip wearing a threshold.
    #
    # It could not be tuned into shape either, because the two demands are mutually exclusive:
    # admission wants a small min_n (the aggregate n_buckets x min_n must stay under the reviewer's
    # 100) while a 10pp comparison needs n >= 97. At 10 buckets that asks for min_n <= 10 and
    # min_n >= 97 at once.
    #
    # So the quality call belongs to the reviewer, which is built for it and already requires
    # n_settled >= 100 (MIN_SETTLED in sports/scorecard.py). What is left here is what can honestly
    # be tested at small n: is it tradeable, is the window open, and is there any settled history in
    # this bucket at all. `calibration_insufficient` stays for exactly that reason -- n < min_n is an
    # absence, not a noisy comparison.
    return CandidateCheck(ok=not reasons, reasons=tuple(reasons), bucket=bucket)
