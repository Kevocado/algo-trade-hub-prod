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
from typing import Any, Callable, Mapping

from tradehub.edges import EdgeSuggestion, evaluate_edge
from tradehub.markets import kalshi_event_url
from tradehub.predictions import build_prediction_row
from tradehub.sports.candidates import CandidateCheck, check_candidate
from tradehub.sports.config import SportConfig, load_reviewer_config, load_sport_config
from tradehub.sports.deadline import (
    REVIEW_STOP_MARGIN_SECONDS, remaining_seconds, should_review,
)
from tradehub.sports.feed import Feed, FeedUnavailable, fetch_feed
from tradehub.sports.hub_calibration import settled_buckets
from tradehub.sports.kalshi import SportsKalshi, SportsMarket
from tradehub.sports.kinds import KINDS
from tradehub.sports.mapping import MatchedGame, load_aliases, match_games
from tradehub.sports.pricing import price_market
from tradehub.sports.reviewer import (
    MemoryReviewStore, OpenRouterReviewer, Review, ReviewRequest, SupabaseReviewStore, cache_key, price_bucket,
    review_candidates, tier,
)

SPORTS = ("nfl", "cfb")
LEDGER_CHUNK = 100
# PostgREST's default max rows per response, so a read that has to see more pages with .range().
# Same number and same reason as `POSTGREST_CAP` in api/main.py and `PAGE_SIZE` in
# settlement.py / track_record.py; not imported from the API module because that module is a FastAPI
# app and the sports scan has no business importing one.
LEDGER_PAGE = 1000

log = logging.getLogger(__name__)


@dataclass
class SportScan:
    predictions: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)
    review_requests: list[ReviewRequest] = field(default_factory=list)
    report: dict[str, Any] = field(default_factory=dict)
    # Games dropped for being past the far end of the window, kept separate from `games_started` in
    # the report. A field rather than a report key because `run_sports_scan` reads it when it builds
    # the per-sport state: "priced and then rejected" and "never priced" are different failures and
    # the run summary has to be able to tell them apart.
    too_far: int = 0


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
        # The band this edge was judged on, named for what it is and paired with its source.
        #
        # This key used to read `predictor_calibration_in_bucket`, which is a lie the moment the hub
        # is the authority: the reviewer's fact pack would then carry the HUB's mean_prob/hit_rate
        # under a key saying predictor. The reviewer is the component this whole design defers the
        # calibration judgement to, so misattributing the record to it is the one failure this
        # inversion exists to avoid -- the numbers are right and the label is wrong, which is worse
        # than a wrong number because nothing downstream knows to distrust it. The stored edge row
        # (`_edge_row`) already carried `calibration_source`; this brings the fact pack in line.
        "calibration_in_bucket": check.bucket,
        "calibration_source": check.calibration_source,
    }


def edge_row(row: dict[str, Any]) -> dict[str, Any]:
    """One sports edge as the API serves it, with the comparison it is actually making.

    Two things this refuses to do, both found by reading the live page on 2026-09-27:

    - It never shows `edge_pct` next to `market_prob` as though one were derived from the other.
      `edge_pct` is the AFTER-FEE edge against the entry price on the chosen side; `market_prob` is
      the quote mid. On the live rows those were a 0.18c entry against a 0.33 mid, which reads as
      "78% vs 33%" and invites a subtraction that is not the number shown.
    - It never puts a headline edge on a row the candidate filter rejected. Every one of those rows
      was a ~30c-wide quote, so the "edge" WAS the spread -- `wide_quote` was the first reject
      reason on all 100. A rejected row reports its reasons and no number.

    `quote_spread` is carried so the page can show the thing that explains the number.
    """
    raw = row.get("raw_payload") or {}
    tier = row.get("tier") or raw.get("tier") or "filtered"
    candidate = bool(row.get("candidate", raw.get("candidate", False)))
    reasons = list(raw.get("reject_reasons") or [])

    yes_bid, yes_ask = raw.get("yes_bid"), raw.get("yes_ask")
    spread = round(yes_ask - yes_bid, 4) if isinstance(yes_bid, (int, float)) and isinstance(yes_ask, (int, float)) else None

    # A real row has engine_version as a column (sports/scan.py writes it flat); older rows and the
    # API tests carry it inside raw_payload. Read both rather than depend on which.
    version = row.get("engine_version") or raw.get("engine_version") or ""
    # `feed:unknown` is a placeholder, not a version. Printing the bare word "unknown" under every
    # row (as the live page did) reads as a bug; a blank plus the flag says what is true.
    known = bool(version) and not version.endswith("unknown")

    out = {
        "market_id": row.get("market_id"), "title": row.get("title"), "our_prob": row.get("our_prob"),
        "market_prob": row.get("market_prob"),
        # No headline number on any row the filter rejected, whatever `candidate` and `tier` say.
        # They can disagree after a re-scan, and the reasons are the authority: `wide_quote` in
        # particular means the "edge" was the spread.
        "edge_pct": row.get("edge_pct") if (candidate and tier != "filtered" and not reasons) else None,
        # The same number, named for what it is for. Rows are RANKED by it across page boundaries
        # (a real guarantee, and tests/test_sports_api_range_paging.py pins it), so it cannot simply
        # be dropped -- but it is not the headline, and the UI must not render it on a rejected row.
        "rank_edge_pct": row.get("edge_pct"),
        "market_url": row.get("market_url"), "source_url": row.get("source_url"),
        "engine": row.get("engine"), "gate_status": row.get("gate_status") or "SHADOW",
        "engine_version": version if known else None,
        "model_version_known": known,
        "quote_spread": spread,
    }
    for key in ("side", "entry_price", "maker", "sport", "kind", "home", "away", "start_utc",
                "game_id", "reject_reasons", "tier", "candidate"):
        if key in raw:
            out[key] = raw[key]
    out.setdefault("tier", tier)
    out.setdefault("candidate", candidate)
    out["reject_reasons"] = reasons
    return out


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
        # Which record the admission decision was made against: the predictor's published
        # calibration, or the hub's own settled ledger once it had enough (approved 2026-09-27).
        "calibration_source": check.calibration_source,
        "tier": "unreviewed" if check.ok else "filtered",
        "review": None,
    }


def _hub_calibration(
    feed: Feed, pairs_by_kind: Mapping[str, list[tuple[float, bool]]] | None,
) -> dict[str, list[dict[str, Any]]] | None:
    """The hub's settled pairs as calibration bands, one band set per kind, or `None`.

    `pairs_by_kind` is one sport's ledger, already keyed by `raw_payload.kind`, so each kind is
    bucketed only on its own evidence -- which is what `choose_calibration`'s per-kind count assumes.
    All three kinds are published even when a sport has settled nothing in one of them: an empty
    band set would read as "this kind has no record at all", whereas `n: 0` bands read as "nothing
    settled in this band", and those two are different facts.

    The bucket COUNT comes off the feed (`Feed.n_buckets`), never from a literal in this file. It is
    the predictor's setting and the 2026-09-27 ruling moves it from 10 to 4 in NFL_Predictor and
    CFB_Predictor; hub buckets cut on different edges are not a replacement for the published record,
    they are a different measurement wearing its name. So the bucketing happens HERE, where the feed
    is, and only the pairs are threaded in from the caller that has the database.

    `None` when there is nothing to cut against (no pairs, or a feed that published no count at all).
    `None` means "no hub record to offer", which is the behaviour before this change: the published
    calibration stays in charge. Inventing a count would be a measurement nobody made.
    """
    if not pairs_by_kind:
        return None
    n_buckets = feed.n_buckets
    if not n_buckets:
        log.warning("sports scan: the feed published no n_buckets, so the hub's settled ledger is "
                    "not used and the predictor's calibration stays in force")
        return None
    return {
        kind: settled_buckets(pairs_by_kind.get(kind) or [], n_buckets, kinds=(kind,))[kind]
        for kind in KINDS
    }


def scan_sport(cfg: SportConfig, markets_by_series: dict[str, list[SportsMarket]], feed: Feed,
               now: datetime, *,
               hub_pairs: Mapping[str, list[tuple[float, bool]]] | None = None) -> SportScan:
    aliases = load_aliases(cfg.sport)
    hub_calibration = _hub_calibration(feed, hub_pairs)
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
        # The far bound, from the SAME params the candidate filter uses.
        #
        # There was no upper bound here, so the scan priced every upcoming game, stored it, and
        # `check_candidate` then rejected it for `starts_too_late`. CFB week 5 sits 120-168h out
        # against this 72h window, which is why 86 of the 100 live rows carried that reason: they
        # were dead on arrival by construction. Bounding here means the work is never done.
        #
        # Read from cfg rather than hardcoded, so changing min_hours_to_start / max_hours_to_start
        # moves this with it. tests/test_sports_scan_window.py pins the 71h/73h boundary so a future
        # edit cannot drift it silently.
        if (mg.game.start_utc - now).total_seconds() / 3600.0 > float(cfg.edge.params["max_hours_to_start"]):
            out.too_far += 1
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
                check = check_candidate(kind, sm, mg, s, feed.calibration, cfg.edge.params, now,
                                        hub_calibration=hub_calibration)
                row = _edge_row(cfg, kind, sm, mg, s, check, now)
                if check.ok:
                    bucket = price_bucket(s.entry_price, bucket_cents)
                    req = ReviewRequest(
                        # The source is part of the key because the band this edge was judged on
                        # came from it: the same market is judged on the predictor's published
                        # calibration until the hub has enough settled rows of its kind, and on the
                        # hub's own record from then on. See `reviewer.cache_key`.
                        key=cache_key(cfg.sport, mg.game.game_id, sm.market.ticker, s.side, bucket,
                                      check.calibration_source),
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
class HubLedger:
    """What the hub's own settled record says, and how much of it this build cannot read.

    Two fields because a reader needs both to tell two different failures apart, and neither is
    visible from the other:

    - `pairs_by_engine` is the record the hub calibrates on: `engine -> kind -> [(our_prob, hit)]`.
    - `unrecognised_by_engine` counts the settled rows this build had to keep OUT of that record
      because they named a kind outside `sports.kinds.KINDS`, keyed the same way:
      `engine -> kind -> rows`.

    Without the second, "this kind has no hub record" reads identically whether nothing of that kind
    has settled or this build cannot place that kind at all. Every number downstream is blind to the
    difference -- both produce a band with `n: 0` -- so the difference has to be carried as data,
    not as a log line nobody reads. It rides all the way to `per_sport[sport]["unrecognised_kinds"]`.
    """
    pairs_by_engine: dict[str, dict[str, list[tuple[float, bool]]]] = field(default_factory=dict)
    unrecognised_by_engine: dict[str, dict[str, int]] = field(default_factory=dict)


def _unrecognised_for(hub_ledger: HubLedger | None, sport: str) -> dict[str, int]:
    """One sport's share of the tally, as its own dict (never the ledger's, so a reader that edits
    the report cannot edit the measurement). `{}` when there was nothing this build could not read,
    which is a fact the report has to state rather than leave out: an absent key and an empty one
    are different claims."""
    engine = SPORTS_ENGINES.get(sport, "")
    return dict((hub_ledger.unrecognised_by_engine if hub_ledger else {}).get(engine, {}))


@dataclass
class SportsRun:
    predictions: list[dict[str, Any]]
    edges: list[dict[str, Any]]
    reports: dict[str, Any]
    # sport -> {feed_ok, edges, series_ok, too_far, unrecognised_kinds} on the path that actually
    # scanned, and {feed_ok, edges, unrecognised_kinds} on the three early exits in
    # `run_sports_scan` (deadline, feed 404, every series failed), which have no scan result to
    # count. So read these with .get().
    # `too_far` is games the far bound dropped before pricing. It is the difference between "priced
    # and rejected" and "never priced", which is the first question anybody asks of an empty board
    # (see SportScan.too_far). It reaches a reader through `sports_run_summary`, not from here.
    # `unrecognised_kinds` is on EVERY path, including the early exits, because it is learned when
    # the ledger is read -- which happens before any of them -- and is not a fact about the scan. A
    # key that only appears on the runs that scanned is a key a reader has to wonder about on the
    # runs where it is missing.
    # The write_ok flag is filled in by the caller, which is the only place that knows whether the
    # upsert landed.
    per_sport: dict[str, dict[str, Any]] = field(default_factory=dict)


# The per-sport keys the printed run summary carries on top of the scan's own numbers. They are
# named as one list rather than copied across key by key, because the reason this function exists
# is that a key added to `per_sport` reaches nobody: the cron entry point takes `run.reports` as its
# sports summary and keeps `per_sport` only to decide pruning. That is the `feed:unknown` shape --
# a real measurement, recorded, that no human could see. One list is the answer to "the next
# diagnostic key will not be carried either".
DIAGNOSTIC_KEYS = ("too_far", "unrecognised_kinds")


def sports_run_summary(run: SportsRun) -> dict[str, Any]:
    """`run.reports` with the per-sport diagnostics folded in: the summary a human receives.

    Two facts live only in `per_sport`, and each is the difference between two readings that look
    identical otherwise:

    - `too_far` -- games the window's far bound dropped before pricing. Without it, a run that
      priced two of three games is indistinguishable from a run that priced none.
    - `unrecognised_kinds` -- settled rows naming a kind outside `sports.kinds.KINDS`, which the hub
      record cannot hold. Without it, a kind with no band is indistinguishable from a kind this
      deployment cannot read.

    Every sport in `per_sport` gets both, whether or not it scanned: a sport whose report entry has
    to be synthesised is a sport whose diagnostics would otherwise be dropped by the join, and a
    silently dropped diagnostic is the shape this exists to remove. A sport that never scanned has
    no count to give, so `too_far` is `None` there -- "not measured", which is not the claim `0`
    would be.
    """
    summary: dict[str, Any] = dict(run.reports)
    for sport, state in run.per_sport.items():
        report = dict(summary.get(sport) or {})
        for key in DIAGNOSTIC_KEYS:
            report[key] = state.get(key)
        summary[sport] = report
    return summary


def run_sports_scan(now: datetime, kalshi, *, fetch: Callable[..., Feed] = fetch_feed, store=None,
                    reviewer: OpenRouterReviewer | None = None, budget: int = 0,
                    sports: tuple[str, ...] = SPORTS,
                    deadline: float | None = None,
                    hub_ledger: HubLedger | None = None
                    ) -> SportsRun:
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
            per_sport[sport] = {"feed_ok": False, "edges": [],
                                "unrecognised_kinds": _unrecognised_for(hub_ledger, sport)}
            continue
        cfg = load_sport_config(sport)
        try:
            # The deadline goes into the feed fetch, not just the Kalshi client: an unconditional
            # 60s timeout plus a retry is 122s of predictor call inside a 15-minute scan.
            feed = fetch(cfg.base_url, deadline=effective_deadline)
        except FeedUnavailable as exc:
            # A 404 here is the EXPECTED state until 7a's feed is deployed, so it is neither a
            # failure nor silent: it stays out of `failures` (the exit code must stay 0) but it is
            # a WARNING with the sport and the reason, because the run summary is the only place
            # it used to appear and `journalctl` on the timer showed nothing at all.
            log.warning("sports feed unavailable sport=%s url=%s: %s", sport, cfg.base_url, exc)
            reports[sport] = {"feed_error": str(exc)}
            per_sport[sport] = {"feed_ok": False, "edges": [],
                                "unrecognised_kinds": _unrecognised_for(hub_ledger, sport)}
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
            per_sport[sport] = {"feed_ok": False, "edges": [],
                                "unrecognised_kinds": _unrecognised_for(hub_ledger, sport)}
            continue
        # Only this sport's own ledger, keyed by engine upstream. NFL and CFB are different models
        # with different records, so a shared one would hand a sport a calibration built from the
        # other sport's settled history -- including enough of it to cross the threshold. The
        # unrecognised-kind tally is split the same way, for the same reason: an NFL row the build
        # cannot place is an NFL fact, and reporting it under CFB would make the one sport that has
        # a gap look like both do.
        result = scan_sport(cfg, markets, feed, now,
                            hub_pairs=(hub_ledger.pairs_by_engine if hub_ledger else {})
                            .get(SPORTS_ENGINES.get(sport, "")))
        predictions += result.predictions
        edges += result.edges
        requests += result.review_requests
        report = dict(result.report)
        if series_errors:
            report["series_errors"] = series_errors
        reports[sport] = report
        per_sport[sport] = {"feed_ok": True, "edges": result.edges, "series_ok": not series_errors,
                            "too_far": result.too_far,
                            # The build gap this sport's own settled rows exposed, in the run report
                            # rather than only in a log. `{}` is a real answer: this sport has no
                            # settled row of a kind the build cannot read, which is not the same as
                            # having no such rows' worth of bands and not the same as another sport
                            # having them.
                            "unrecognised_kinds": _unrecognised_for(hub_ledger, sport)}
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

    `series_ok` is a third condition and it is required, not defaulted. `remove_stale_edges`
    deletes by engine and market_id, so a sport where ONE series (say the winner markets)
    failed to fetch has a produced set missing every row of that series — pruning it would
    delete a whole market type. Per-series pruning is not expressible here: the series lives
    inside raw_payload, not in a column, so the honest answer is to skip the sport's prune.
    Rows that go stale in that case are cleaned up on the next healthy run.
    """
    errors: list[str] = []
    for sport, state in per_sport.items():
        engine = SPORTS_ENGINES.get(sport)
        if engine is None:
            continue
        if not state.get("feed_ok") or not state.get("write_ok") or not state.get("series_ok"):
            if not state.get("series_ok") and state.get("feed_ok") and state.get("write_ok"):
                log.warning("scan: not pruning %s; one of its series failed to fetch, so the "
                            "produced set is incomplete", engine)
            continue
        produced = {row["market_ticker"] for row in state.get("edges") or [] if row.get("market_ticker")}
        try:
            remove(client, {engine: produced})
        except Exception as exc:
            errors.append(f"{engine}.cleanup: {type(exc).__name__}: {exc}")
            log.exception("scan stale-edge cleanup failed engine=%s", engine)
    return errors


def _hub_settled_ledger(supa) -> HubLedger:
    """The hub's own settled sports record: `engine -> kind -> [(our_prob, hit), ...]`, plus the
    settled rows this build could not place.

    Read here, by the cron entry point, because `run_sports_scan` has no database access: it takes
    kalshi, fetch, store and reviewer, and no supa. The scan is given the answer rather than a way to
    look it up, which is also what keeps it testable without a database.

    Three things about the shape, each of which was a real hole in the first version:

    **BY KIND.** A row's kind is `raw_payload.kind`, and that is a fact the hub's own scan wrote
    (`build_prediction_row(... raw_payload={"kind": kind ...})` above), not an inference. A row that
    names a kind is filed under it; a row that names none is filed as a winner, which is what the
    scan has always written for a winner market. So the ledger speaks for all three kinds, and
    publishing only some of them is not a narrowing of the record -- it is every spread and total
    edge becoming `calibration_insufficient` the day the hub crosses the threshold. An earlier ruling
    said winner-only, on the premise that a wrong kind attribution is worse than an absent one; the
    premise was false, because the hub is the only writer of this field.

    The kinds come from `sports.kinds.KINDS` -- the same object `parse_feed` reads the payload
    against -- because this filter is what makes an omission here a deletion of evidence rather than
    a narrower view of it. A row of a kind outside KINDS is not `continue`d in silence: it is tallied
    per engine onto `HubLedger.unrecognised_by_engine`, which `run_sports_scan` publishes in the run
    report at `per_sport[sport]["unrecognised_kinds"]`. That is the channel, and it is the only
    durable one: a log line in this codebase is demonstrably not an observed channel -- `core/
    supabase_client.py` upserts to four tables that never existed with bare `print()`s, and nobody
    found out for the life of the system (hence the migration guard in PR #20). A guard whose
    evidence is a log line is the same failure as `feed:unknown` sitting on 100 live rows: the fact
    is true, recorded, and in a place nobody reads. "This build cannot read that kind" and "nothing
    of that kind has settled" are different failures and every number downstream is blind to the
    difference, because both produce a band with `n: 0`. The log line below is kept as the immediate
    half of the report; it is not the half the finding depends on.

    **BY ENGINE.** One ledger shared across both sports would put NFL's rows into CFB's bands and the
    reverse. They are different models with different records (NFL 0 settled, CFB ~61), so a sport
    that reached the threshold would be handing out a calibration built from another sport's history.
    Keyed by engine so `run_sports_scan` can give each `scan_sport` only its own sport's pairs, and
    so the unrecognised tally is attributable to the sport that owns the rows. A row with no engine
    is skipped entirely: it cannot be filed, and it cannot be attributed to a sport either, so
    counting it would report a gap against a sport it does not belong to. (Unreachable from the
    database -- the query filters `engine` to the two sports -- but a row is a row.)

    **PAGED, ORDERED, ON `id`.** A single `.execute()` returns at most PostgREST's 1000-row cap, and
    nothing in this repo deletes sports `predictions` rows, so the table grows monotonically and
    crosses 1000 within a season. Past that, the component that is supposed to BE the authority would
    be deciding on whatever 1000 rows the query plan happened to return -- a silent wrong answer, not
    a visible failure. The `.order("id")` is not decoration either: without it, page 1 and page 2 can
    overlap or skip rows. `id` is the only column on this table that is unique and immutable.

    A failed read returns nothing rather than raising: this is a new failure mode on the sports path
    and it must not be able to cost a scan that works perfectly well on the published calibration.
    A failed read also discards the unrecognised-kind tally, because a count taken from a ledger
    that was never complete is a count nobody can trust, and the `log.exception` above is the whole
    story for that run.
    """
    pairs: dict[str, dict[str, list[tuple[float, bool]]]] = {}
    unknown: dict[str, dict[str, int]] = {}
    start = 0
    while True:
        try:
            page = (
                supa.table("predictions").select("engine,our_prob,result,raw_payload")
                .in_("engine", sorted(SPORTS_ENGINES.values())).eq("status", "SETTLED")
                .order("id").range(start, start + LEDGER_PAGE - 1).execute().data or []
            )
        except Exception:
            log.exception("sports scan: hub settled-ledger read failed; using the predictor's calibration")
            return HubLedger()
        for row in page:
            prob, result = row.get("our_prob"), row.get("result")
            if not isinstance(prob, (int, float)) or result not in ("yes", "no"):
                continue
            engine = row.get("engine")
            if not engine:
                continue
            # Absent or null kind is a winner row: that is what the scan writes for a winner market.
            kind = (row.get("raw_payload") or {}).get("kind") or "winner"
            if kind not in KINDS:
                tally = unknown.setdefault(engine, {})
                tally[kind] = tally.get(kind, 0) + 1
                continue
            pairs.setdefault(engine, {}).setdefault(kind, []).append((float(prob), result == "yes"))
        if len(page) < LEDGER_PAGE:
            for engine, tally in sorted(unknown.items()):
                log.warning(
                    "sports scan: engine %s has %d settled row(s) of %d kind(s) this build does not "
                    "recognise (%s). Those rows are NOT in the ledger, so those kinds stay on the "
                    "predictor's published calibration, or on no record at all -- a build that does "
                    "not know the kind, not a kind with nothing settled. Adding it to "
                    "tradehub/sports/kinds.py is the fix. This is the same tally the run report "
                    "publishes as per_sport[...]['unrecognised_kinds'].",
                    engine, sum(tally.values()), len(tally),
                    ", ".join(f"{kind}={n}" for kind, n in sorted(tally.items())),
                )
            return HubLedger(pairs, {e: {k: n for k, n in sorted(t.items())}
                                     for e, t in sorted(unknown.items())})
        start += LEDGER_PAGE


def run_sports_for_cron(now: datetime, supa, *, deadline: float | None = None) -> SportsRun:
    cfg = load_reviewer_config()
    key = os.getenv("OPENROUTER_API_KEY")
    reviewer = OpenRouterReviewer(key, cfg.model, cfg.timeout_seconds, deadline=deadline) if key else None
    # The scan's deadline, not a fresh budget: sports paginates the public markets API per
    # series and must not be able to overrun the hourly timer and overlap the next run.
    run = run_sports_scan(now, SportsKalshi(deadline=deadline), store=SupabaseReviewStore(supa), reviewer=reviewer,
                          budget=cfg.daily_budget, deadline=deadline,
                          hub_ledger=_hub_settled_ledger(supa))
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
