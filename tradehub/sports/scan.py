"""Sports edge scan (suggest-only): predictor feed x open Kalshi markets -> predictions, edges, reviews.

Cron: tradehub.scripts.scan calls run_sports_for_cron() every third hour (spec §5: sports every 3h).
Smoke test without Supabase or the LLM:  python -m tradehub.sports.scan --dry-run
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.markets import kalshi_event_url
from tradehub.predictions import build_prediction_row
from tradehub.sports.candidates import CandidateCheck, check_candidate
from tradehub.sports.config import SportConfig, load_reviewer_config, load_sport_config
from tradehub.sports.deadline import (
    REVIEW_STOP_MARGIN_SECONDS, remaining_seconds, should_review,
)
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

log = logging.getLogger(__name__)


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
              check: CandidateCheck, now: datetime) -> dict[str, Any]:
    series = cfg.series[kind]
    g = mg.game
    return {
        "market_ticker": sm.market.ticker,
        "market_title": sm.market.title,
        "market_price": s.market_prob,
        "model_probability": s.our_prob,
        "edge": s.net_edge_pct / 100.0,
        "edge_type": "SPORTS",
        "engine": cfg.engine,
        # Same key the ledger row uses, so the (engine, engine_version) promotion gate can
        # actually match this edge instead of falling back to a placeholder.
        "engine_version": f"feed:{mg.game.model_version or 'unknown'}",
        "gate_status": "SHADOW",
        "updated_at": now.isoformat(),
        "expires_at": sm.market.close_time.isoformat(),
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
    skipped = 0
    started = 0
    for mg in match.matched:
        # A game that has kicked off is not tradeable and must not be written: its market stays
        # open on Kalshi for days afterwards (expires_at is the close time, ~2 days after
        # kickoff), so without this the board fills with edges on games already being played.
        if mg.game.start_utc <= now:
            started += 1
            continue
        for kind, markets in mg.markets.items():
            for sm in markets:
                # One market the pricer or the candidate filter chokes on must not cost the
                # whole sport: a single odd strike used to abort the scan with nothing written.
                try:
                    prob = price_market(kind, sm, mg)
                except Exception:
                    skipped += 1
                    log.exception("sports price failed sport=%s market=%s", cfg.sport, sm.market.ticker)
                    continue
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
                row = _edge_row(cfg, kind, sm, mg, s, check, now)
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
        "markets_priced": priced, "markets_skipped": skipped, "games_started": started,
        "predictions": len(out.predictions), "edges": len(out.edges),
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
    # sport -> {feed_ok, edges}. The write_ok flag is filled in by the caller, which is the only
    # place that knows whether the upsert landed.
    per_sport: dict[str, dict[str, Any]] = field(default_factory=dict)


def run_sports_scan(now: datetime, kalshi, *, fetch: Callable[[str], Feed] = fetch_feed, store=None,
                    reviewer: OpenRouterReviewer | None = None, budget: int = 0,
                    sports: tuple[str, ...] = SPORTS,
                    deadline: float | None = None) -> SportsRun:
    predictions: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    requests: list[ReviewRequest] = []
    reports: dict[str, Any] = {}
    per_sport: dict[str, dict[str, Any]] = {}
    # No deadline given (tests, the dry run) means an effectively unbounded budget.
    effective_deadline = deadline if deadline is not None else time.monotonic() + float("inf")
    for sport in sports:
        if remaining_seconds(effective_deadline) <= 0:
            reports[sport] = {"skipped": "scan deadline reached before this sport"}
            per_sport[sport] = {"feed_ok": False, "edges": []}
            continue
        cfg = load_sport_config(sport)
        try:
            # The deadline goes into the feed fetch, not just the Kalshi client: an unconditional
            # 60s timeout plus a retry is 122s of predictor call inside a 15-minute scan.
            feed = fetch(cfg.base_url, deadline=effective_deadline)
        except FeedUnavailable as exc:
            reports[sport] = {"feed_error": str(exc)}
            per_sport[sport] = {"feed_ok": False, "edges": []}
            continue
        # open_markets is a paginated public-API call per series; one series failing must not
        # cost the sport, and must certainly not be read as "this sport has no edges".
        markets: dict[str, list[SportsMarket]] = {}
        series_errors: dict[str, str] = {}
        for series in cfg.series.values():
            try:
                markets[series] = kalshi.open_markets(series)
            except Exception as exc:
                series_errors[series] = f"{type(exc).__name__}: {exc}"
                log.exception("sports market fetch failed sport=%s series=%s", sport, series)
        if series_errors and not markets:
            reports[sport] = {"kalshi_error": "; ".join(f"{s}: {e}" for s, e in series_errors.items())}
            per_sport[sport] = {"feed_ok": False, "edges": []}
            continue
        result = scan_sport(cfg, markets, feed, now)
        predictions += result.predictions
        edges += result.edges
        requests += result.review_requests
        report = dict(result.report)
        if series_errors:
            report["series_errors"] = series_errors
        reports[sport] = report
        per_sport[sport] = {"feed_ok": True, "edges": result.edges}
    # Reviewing is the optional, slow part: stop when the scan budget is nearly gone. The edges
    # are already computed and are still written, just with tier=unreviewed. review_candidates
    # re-checks the same rule before every call, so a long candidate list cannot walk past it.
    if should_review(effective_deadline):
        reviews = review_candidates(requests, store or MemoryReviewStore(), reviewer, budget=budget,
                                    now=now, deadline=effective_deadline)
        apply_reviews(edges, reviews)
    else:
        log.warning("sports scan: under %ss of scan budget left; skipping reviewer calls",
                    REVIEW_STOP_MARGIN_SECONDS)
        reports["reviews"] = {"skipped_deadline": len(requests)}
        return SportsRun(predictions, edges, reports, per_sport)
    reports["reviews"] = {status: sum(r.status == status for r in reviews.values())
                          for status in sorted({r.status for r in reviews.values()})}
    return SportsRun(predictions, edges, reports, per_sport)


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


SPORTS_ENGINES = {"nfl": "sports_nfl", "cfb": "sports_cfb"}


def sports_prune_targets(edges: list[dict[str, Any]]) -> set[str]:
    """Engines eligible for stale-edge pruning: the CONFIGURED sports, not whatever this run
    happened to produce.

    Deriving this from the produced rows meant a sport that legitimately produced zero edges
    (no market cleared the candidate filter this hour) pruned nothing, and its previous rows
    stayed up indefinitely. A zero-edge run is exactly when pruning matters most.
    """
    return set(SPORTS_ENGINES.values())


def remove_started_sports_edges(client, now: datetime) -> list[str]:
    """Delete sports rows whose game has already started. Returns error strings.

    `remove_stale_edges` only drops rows whose market_id is absent from the produced set, so a
    game that kicked off kept its row until some later scan happened to omit it.

    The predicate is on `start_utc`, the indexed game start, NOT on `expires_at`: expires_at is
    the Kalshi `close_time`, which for a sports market is about two days AFTER kickoff, so an
    expires_at filter left every started game visible on the board for days. Scoped to the two
    sports engines, so no other engine's rows are touched.
    """
    errors: list[str] = []
    for engine in sorted(SPORTS_ENGINES.values()):
        try:
            client.table("kalshi_edges").delete() \
                .eq("engine", engine) \
                .lte("start_utc", now.isoformat()) \
                .execute()
        except Exception as exc:
            errors.append(f"{engine}.started_cleanup: {type(exc).__name__}: {exc}")
            log.exception("scan started-sports cleanup failed engine=%s", engine)
    return errors


def prune_sports_if_healthy(
    client,
    per_sport: dict[str, dict[str, Any]],
    *,
    remove: Callable[[Any, dict[str, set[str]]], None],
    now: datetime,
) -> list[str]:
    """Prune each sport whose feed fetch AND edge write both succeeded. Returns error strings.

    The two conditions are the whole safety story: a feed error means we do not know what the
    sport looks like now, and a failed write means our produced set is not what is on the board.
    Either one would turn "produced nothing" into "delete everything", so neither may prune.
    """
    errors: list[str] = []
    for sport, state in per_sport.items():
        engine = SPORTS_ENGINES.get(sport)
        if engine is None:
            continue
        if not state.get("feed_ok") or not state.get("write_ok"):
            continue
        produced = {row["market_ticker"] for row in state.get("edges") or [] if row.get("market_ticker")}
        try:
            remove(client, {engine: produced})
        except Exception as exc:
            errors.append(f"{engine}.cleanup: {type(exc).__name__}: {exc}")
            log.exception("scan stale-edge cleanup failed engine=%s", engine)
    return errors


def run_sports_for_cron(now: datetime, supa, *, deadline: float | None = None) -> SportsRun:
    cfg = load_reviewer_config()
    key = os.getenv("OPENROUTER_API_KEY")
    reviewer = OpenRouterReviewer(key, cfg.model, cfg.timeout_seconds, deadline=deadline) if key else None
    # The scan's deadline, not a fresh budget: sports paginates the public markets API per
    # series and must not be able to overrun the hourly timer and overlap the next run.
    run = run_sports_scan(now, SportsKalshi(deadline=deadline), store=SupabaseReviewStore(supa), reviewer=reviewer,
                          budget=cfg.daily_budget, deadline=deadline)
    return SportsRun(unrecorded(supa, run.predictions), run.edges, run.reports, run.per_sport)


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
