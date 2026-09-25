"""Sports edge scan (suggest-only): predictor feed x open Kalshi markets -> predictions, edges, reviews.

Cron: tradehub.scripts.scan calls run_sports_for_cron() every third hour (spec §5: sports every 3h).
Smoke test without Supabase or the LLM:  python -m tradehub.sports.scan --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.markets import kalshi_event_url
from tradehub.predictions import build_prediction_row
from tradehub.sports.candidates import CandidateCheck, check_candidate
from tradehub.sports.config import SportConfig, load_reviewer_config, load_sport_config
from tradehub.sports.feed import Feed, FeedUnavailable, fetch_feed
from tradehub.sports.kalshi import SportsKalshi, SportsMarket
from tradehub.sports.mapping import MatchedGame, load_aliases, match_games
from tradehub.sports.pricing import price_market
from tradehub.sports.reviewer import (
    MemoryReviewStore, OpenRouterReviewer, Review, ReviewRequest, SupabaseReviewStore, cache_key, price_bucket,
    review_candidates, tier,
)

SPORTS = ("nfl", "cfb")
LEDGER_CHUNK = 100


@dataclass
class SportScan:
    predictions: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    review_requests: list[ReviewRequest] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)


def _fact_pack(cfg: SportConfig, kind: str, sm: SportsMarket, mg: MatchedGame, s: EdgeSuggestion,
               check: CandidateCheck, now: datetime) -> dict[str, Any]:
    """Public facts only (spec §3.2 'Data sent'): no keys, no account data."""
    g = mg.game
    return {
        "sport": cfg.sport,
        "matchup": {"home": g.home, "away": g.away, "start_utc": g.start_utc.isoformat(),
                    "hours_to_start": round((g.start_utc - now).total_seconds() / 3600, 1)},
        "market": {"ticker": sm.market.ticker, "title": sm.market.title, "kind": kind, "side": s.side,
                   "entry_price": s.entry_price, "maker": s.maker, "yes_bid": sm.quote.yes_bid, "yes_ask": sm.quote.yes_ask},
        "predictor": {"yes_prob": round(s.our_prob, 4), "p_home": round(g.p_home, 4), "margin_mu": g.margin_mu,
                      "sigma": g.sigma, "total_mu": g.total_mu, "total_sigma": g.total_sigma,
                      "model_version": g.model_version, "snapshotted_at": g.snapshotted_at.isoformat(),
                      "snapshot_age_hours": round((now - g.snapshotted_at).total_seconds() / 3600, 1)},
        "net_edge_pct_after_fees": round(s.net_edge_pct, 2),
        "predictor_calibration_in_bucket": check.bucket,
    }


def _edge_row(cfg: SportConfig, kind: str, sm: SportsMarket, mg: MatchedGame, s: EdgeSuggestion,
              check: CandidateCheck) -> dict[str, Any]:
    series = cfg.series[kind]
    g = mg.game
    return {
        "market_ticker": sm.market.ticker,
        "market_title": sm.market.title,
        "market_price": s.market_prob,
        "model_probability": s.our_prob,
        "edge": s.net_edge_pct / 100.0,
        "edge_type": "SPORTS",
        "market_url": kalshi_event_url(series, cfg.series_titles[series], sm.market.event_ticker),
        # Sports_Predictor has no per-game route yet; the params are ready for when it does.
        "source_url": f"{cfg.site_url}/?sport={cfg.sport}&game={g.game_id}",
        "side": s.side,
        "entry_price": s.entry_price,
        "maker": s.maker,
        "sport": cfg.sport,
        "kind": kind,
        "game_id": g.game_id,
        "home": g.home,
        "away": g.away,
        "start_utc": g.start_utc.isoformat(),
        "snapshotted_at": g.snapshotted_at.isoformat(),
        "model_version": g.model_version,
        "candidate": check.ok,
        "reject_reasons": list(check.reasons),
        "calibration_bucket": check.bucket,
        "tier": "unreviewed" if check.ok else "filtered",
        "review": None,
    }


def scan_sport(cfg: SportConfig, markets_by_series: dict[str, list[SportsMarket]], feed: Feed, now: datetime) -> SportScan:
    aliases = load_aliases(cfg.sport)
    bucket_cents = load_reviewer_config().price_bucket_cents
    match = match_games(feed.games, markets_by_series, cfg.series, aliases)
    out = SportScan()
    priced = 0
    for mg in match.matched:
        for kind, markets in mg.markets.items():
            for sm in markets:
                prob = price_market(kind, sm, mg)
                if prob is None:
                    continue
                priced += 1
                q = sm.quote
                if q.yes_bid is not None and q.yes_ask is not None:
                    out.predictions.append(build_prediction_row(
                        market_ticker=sm.market.ticker, our_prob=prob, market_prob=(q.yes_bid + q.yes_ask) / 2.0,
                        engine=cfg.engine, as_of=now, engine_version=f"feed:{mg.game.model_version or 'unknown'}",
                        raw_payload={"sport": cfg.sport, "game_id": mg.game.game_id, "kind": kind,
                                     "start_utc": mg.game.start_utc.isoformat(),
                                     "snapshotted_at": mg.game.snapshotted_at.isoformat(),
                                     "alias_version": aliases.version, "date_shift_days": mg.date_shift_days},
                    ))
                s = evaluate_edge(sm.market.ticker, prob, q, min_edge_pct=cfg.edge.min_edge_pct,
                                  prefer_maker=cfg.edge.prefer_maker)
                if s is None:
                    continue
                check = check_candidate(kind, sm, mg, s, feed.calibration, cfg.edge.params, now)
                row = _edge_row(cfg, kind, sm, mg, s, check)
                if check.ok:
                    bucket = price_bucket(s.entry_price, bucket_cents)
                    req = ReviewRequest(
                        key=cache_key(cfg.sport, mg.game.game_id, sm.market.ticker, s.side, bucket),
                        sport=cfg.sport, game_id=mg.game.game_id, market_ticker=sm.market.ticker, side=s.side,
                        entry_price=s.entry_price, price_bucket=bucket, our_prob=s.our_prob,
                        net_edge_pct=s.net_edge_pct, fact_pack=_fact_pack(cfg, kind, sm, mg, s, check, now),
                    )
                    row["review_key"] = req.key
                    out.review_requests.append(req)
                out.edges.append(row)
    out.report = {
        "feed_games": len(feed.games), "feed_rejected": feed.rejected, "matched": len(match.matched),
        "unmatched_games": match.unmatched_games, "unmatched_events": match.unmatched_events,
        "markets_priced": priced, "predictions": len(out.predictions), "edges": len(out.edges),
        "candidates": len(out.review_requests), "alias_version": aliases.version,
    }
    return out


def apply_reviews(edges: list[dict[str, Any]], reviews: dict[str, Review]) -> None:
    """Attach review verdicts. Only tier/review change; probabilities and edges never do."""
    for edge in edges:
        review = reviews.get(edge.get("review_key", ""))
        if review is None:
            continue
        edge["tier"] = tier(review)
        edge["review"] = {"status": review.status, "explainable": review.explainable,
                          "drivers": list(review.drivers), "red_flags": list(review.red_flags), "model": review.model}


@dataclass
class SportsRun:
    predictions: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    reports: dict[str, Any]


def run_sports_scan(now: datetime, kalshi, *, fetch: Callable[[str], Feed] = fetch_feed, store=None,
                    reviewer: OpenRouterReviewer | None = None, budget: int = 0,
                    sports: tuple[str, ...] = SPORTS) -> SportsRun:
    predictions: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    requests: list[ReviewRequest] = []
    reports: dict[str, Any] = {}
    for sport in sports:
        cfg = load_sport_config(sport)
        try:
            feed = fetch(cfg.base_url)
        except FeedUnavailable as exc:
            reports[sport] = {"feed_error": str(exc)}
            continue
        markets = {series: kalshi.open_markets(series) for series in cfg.series.values()}
        result = scan_sport(cfg, markets, feed, now)
        predictions += result.predictions
        edges += result.edges
        requests += result.review_requests
        reports[sport] = result.report
    reviews = review_candidates(requests, store or MemoryReviewStore(), reviewer, budget=budget, now=now)
    apply_reviews(edges, reviews)
    reports["reviews"] = {status: sum(r.status == status for r in reviews.values())
                          for status in sorted({r.status for r in reviews.values()})}
    return SportsRun(predictions, edges, reports)


def unrecorded(supa, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows whose market already has a ledger row for the same engine. The feed probability is
    frozen, so one prediction per market is the honest record (and keeps the 3-hourly scan from
    multiplying rows for the promotion gate)."""
    seen: set[tuple[str, str]] = set()
    by_engine: dict[str, list[str]] = {}
    for row in rows:
        by_engine.setdefault(row["engine"], []).append(row["market_ticker"])
    for engine, tickers in by_engine.items():
        for i in range(0, len(tickers), LEDGER_CHUNK):
            chunk = tickers[i:i + LEDGER_CHUNK]
            res = supa.table("predictions").select("market_ticker").eq("engine", engine).in_("market_ticker", chunk).execute()
            seen |= {(engine, r["market_ticker"]) for r in res.data or []}
    return [r for r in rows if (r["engine"], r["market_ticker"]) not in seen]


def sports_due(now: datetime) -> bool:
    """The hourly scan timer runs sports every third UTC hour; SPORTS_SCAN_EVERY_RUN=1 forces it."""
    return os.getenv("SPORTS_SCAN_EVERY_RUN") == "1" or now.astimezone(timezone.utc).hour % 3 == 0


def run_sports_for_cron(now: datetime, supa) -> tuple[list[dict], list[dict], dict]:
    cfg = load_reviewer_config()
    key = os.getenv("OPENROUTER_API_KEY")
    reviewer = OpenRouterReviewer(key, cfg.model, cfg.timeout_seconds) if key else None
    run = run_sports_scan(now, SportsKalshi(), store=SupabaseReviewStore(supa), reviewer=reviewer,
                          budget=cfg.daily_budget)
    return unrecorded(supa, run.predictions), run.edges, run.reports


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="print the report; write nothing, call no LLM")
    parser.add_argument("--sport", choices=SPORTS, action="append")
    args = parser.parse_args(argv)
    if not args.dry_run:
        parser.error("only --dry-run is supported here; the cron path is tradehub.scripts.scan")
    now = datetime.now(timezone.utc)
    run = run_sports_scan(now, SportsKalshi(), sports=tuple(args.sport or SPORTS))
    top = sorted(run.edges, key=lambda e: (not e["candidate"], -e["edge"]))[:15]
    print(json.dumps({
        "as_of": now.isoformat(), "reports": run.reports, "predictions": len(run.predictions),
        "edges": len(run.edges), "candidates": sum(e["candidate"] for e in run.edges),
        "top_edges": [{k: e[k] for k in ("market_ticker", "side", "entry_price", "model_probability", "market_price",
                                         "edge", "candidate", "reject_reasons", "tier")} for e in top],
    }, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
