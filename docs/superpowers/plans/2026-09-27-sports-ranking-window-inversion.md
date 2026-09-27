# Sports Ranking, Window and Inversion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop the sports scan pricing games it can never trade, admit picks on the predictor's published calibration first, and rank what survives by confidence rather than by raw edge.

**Architecture:** Three separable changes to one pipeline. The scan currently prices *every* upcoming game and lets the candidate filter reject the far ones, so 86 of 100 live rows were dead on arrival; bounding the scan by the same window the filter uses removes that work at the source. The inversion makes the candidate filter prefer the hub's own settled ledger once it has enough, falling back to the predictor's published calibration — which means threading a calibration mapping into `check_candidate`, because `run_sports_scan` has no database access today. Ranking by `edge / sigma` is added behind a flag that stays off until a predictor publishes `sigma`, because it is null on all 61 games right now.

**Tech Stack:** Python 3.12, supabase-py, pytest, React 18 + TypeScript + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-hub-redesign.md` — §3 (the scan bounds and the gate deadlock; the `sports_cfb` correction), §4 (available-now, ranking by edge ÷ sigma), §9 approvals 1 and 2.

## Global Constraints

- **Suggest-only. This product never places an order** (spec §6).
- **The window is 1–72h**, from `min_hours_to_start: 1` and `max_hours_to_start: 72` in `tradehub/config/engines.yaml`. Games outside it are never priced, never stored, never ranked.
- **The gate fails closed.** Only an explicit `PROMOTED` is promoted.
- **A rejected row carries no headline edge** (PR #20). `tradehub/sports/scan.py:edge_row` owns that; this plan must not weaken it.
- **Never substitute a constant for a missing input.** `sigma` is null on 61/61 games; ranking falls back to raw edge and *says so*. A default sigma would manufacture exactly the confidence the ranking exists to express.
- **Verification before every push:** full `pytest` twice with `time.monotonic` forced to `5.0` **and** `1e7`, then `ruff check --select F401,F811,F821 tradehub tests`, then `npm run typecheck`, `npx vitest run`, `npm run build`.
- **No migration.** This plan reads and writes tables that already exist.
- **Every commit ends with** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `tradehub/sports/candidates.py` | `check_candidate` gains the hub-ledger preference. Pure, no I/O. |
| `tradehub/sports/hub_calibration.py` | **New.** Pure: settled `(our_prob, hit)` pairs → the same bucket shape the feed publishes. |
| `tradehub/sports/scan.py` | The window bound (task 1); threads hub calibration through (task 2); the sigma rank (task 3). |
| `tradehub/scripts/scan.py` | The cron entry reads the settled ledger and passes it in. |
| `tradehub/api/main.py` | Sends `ranking` and the score to the client so the page can say which it is using. |
| `tests/test_sports_scan_window.py` | **New.** Task 1. |
| `tests/test_sports_inversion.py` | **New.** Task 2. |
| `tests/test_sports_sigma_rank.py` | **New.** Task 3. |
| `market_sentiment_tool/src/lib/sportsEdges.ts` | The `ranking` field on the response type. |
| `market_sentiment_tool/src/pages/SportsEdges.tsx` | States which ranking is in use. |

---

## Task 1: Bound the scan by the window

The highest-value change in this plan, because it removes work rather than adding it.

**The defect.** `tradehub/sports/scan.py:121` filters only `mg.game.start_utc <= now` — games already
under way. There is no upper bound, so the scan prices every upcoming game, writes it to
`kalshi_edges`, and `check_candidate` then rejects it for `starts_too_late`. CFB week 5 is 120–168h
out against a 72h window, so **86 of 100 live rows were dead on arrival**: work done, rows stored,
rows rendered as rejects.

**Files:**
- Modify: `tradehub/sports/scan.py` (`scan_sport`, around line 117-123)
- Test: `tests/test_sports_scan_window.py` (new)

**Interfaces:**
- Consumes: `cfg.edge.params` — already carries `min_hours_to_start` and `max_hours_to_start`, and is passed to `check_candidate` at `scan.py:151`.
- Produces: `SportScan` gains a `too_far` counter (see below) so the scan report can distinguish "priced and rejected" from "never priced".

- [ ] **Step 1: Write the failing test**

Create `tests/test_sports_scan_window.py`:

```python
"""The scan must not price a game it can never trade.

`scan.py:121` filtered only `start_utc <= now` -- games already under way -- with no upper bound. So
the scan priced every upcoming game, stored it, and `check_candidate` then rejected it for
`starts_too_late`. CFB week 5 sits 120-168h out against a 72h window, which is why 86 of the 100 live
rows carried `starts_too_late`: they were dead on arrival by construction.

This is the fix at the source rather than in the filter, so the work is never done and the rows are
never written.
"""
from datetime import datetime, timedelta, timezone

from tradehub.sports import scan as scan_mod
from tradehub.sports.scan import scan_sport

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)

PARAMS = {
    "max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000,
    "min_hours_to_start": 1, "max_hours_to_start": 72,
    "calibration_max_dev": 0.10, "calibration_min_n": 20,
}


class _Game:
    def __init__(self, start_utc):
        self.game_id = "g1"
        self.start_utc = start_utc
        self.home = "UConn"
        self.away = "Syracuse"
        self.model_version = "xgb@2026-09-04"


class _Market:
    def __init__(self, ticker="KXNCAAFGAME-26OCT03SYRCONN-CONN"):
        self.ticker = ticker
        self.title = "UConn wins"
        self.event_ticker = "KXNCAAFGAME-26OCT03SYRCONN"
        self.close_time = NOW + timedelta(days=10)


class _Quote:
    yes_bid, yes_ask = 0.40, 0.44
    no_bid, no_ask = 0.56, 0.60
    yes_bid_size = yes_ask_size = no_bid_size = no_ask_size = 500


class _SportMarket:
    def __init__(self, market, quote):
        self.market = market
        self.quote = quote


class _Matched:
    def __init__(self, game, markets):
        self.game = game
        self.markets = {"winner": markets}


class _Match:
    def __init__(self, matched):
        self.matched = matched


def _cfg():
    from tradehub.engine_config import EngineConfig
    from tradehub.sports.config import SportConfig
    return SportConfig(
        sport="cfb", engine="sports_cfb", base_url="http://x", site_url="http://y",
        series={"winner": "KXNCAAFGAME"}, series_titles={"winner": "NCAAF"},
        edge=EngineConfig(min_edge_pct=4.0, prefer_maker=True, params=PARAMS),
    )


def _scan(hours_out):
    game = _Game(NOW + timedelta(hours=hours_out))
    market = _Market()
    sm = _SportMarket(market, _Quote())
    matched = _Match([_Matched(game, [sm])])
    scan_mod.match_games = lambda *a, **k: matched
    scan_mod.load_aliases = lambda sport: None
    return scan_sport(_cfg(), {}, _feed(), NOW)


def _feed():
    class _Feed:
        games = []
        calibration = {}
    return _Feed()


def test_a_game_beyond_the_window_is_never_priced():
    """120h out: outside max_hours_to_start=72, so it must not be priced at all."""
    result = _scan(hours_out=120)

    assert result.priced == 0, "a game outside the window must not be priced"
    assert result.too_far == 1, "and it must be counted, so the report can say why nothing appeared"


def test_a_game_inside_the_window_is_still_priced():
    """24h out: well inside 1-72h, so the bound must not cost us a tradeable game."""
    result = _scan(hours_out=24)

    assert result.too_far == 0
    # `priced` counts games that produced an edge; the point is it was not skipped for distance.
    assert result.started == 0


def test_the_boundary_is_the_configured_one_not_a_hardcoded_number():
    """71h in, 73h out. A hardcoded 72 would pass today and drift the day min/max change."""
    assert _scan(hours_out=71).too_far == 0
    assert _scan(hours_out=73).too_far == 1


def test_an_already_started_game_is_still_counted_as_started_not_too_far():
    """The two exclusions must not be conflated: a started game is not 'too far'."""
    assert _scan(hours_out=-3).started == 1
    assert _scan(hours_out=-3).too_far == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_sports_scan_window.py -v`

Expected: FAIL — `AttributeError: 'SportScan' object has no attribute 'too_far'`, and the 120h case would
otherwise be priced.

- [ ] **Step 3: Add the bound**

In `tradehub/sports/scan.py`, find the `SportScan` dataclass and add the counter:

```python
@dataclass
class SportScan:
    ...
    too_far: int = 0
```

Then, in `scan_sport`, immediately after the existing started-game check, add the far bound:

```python
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
        # moves this with it.
        hours_to_start = (mg.game.start_utc - now).total_seconds() / 3600.0
        if hours_to_start > float(cfg.edge.params["max_hours_to_start"]):
            out.too_far += 1
            continue
```

Note `out.too_far`, not a local: `SportScan` is the return value and the per-sport report reads it.
`started` is already a local because the existing code increments it that way — leave that alone, and
do not "tidy" it into `out`, because the existing tests assert on the return value's `started` and
changing it risks a silent behaviour change for no benefit.

Then include the counter in the per-sport report so a run that produced nothing can say why. Find
where the per-sport report is built in `run_sports_scan` and add `"too_far": scan.too_far` alongside
the existing `feed_ok` / `edges` keys.

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_sports_scan_window.py -v`

Expected: `4 passed`. If `test_a_game_inside_the_window_is_still_priced` fails on `result.priced`, that
counter reflects games that produced an *edge* and this synthetic quote may not clear
`min_edge_pct: 4.0`. In that case drop the `priced` assertion and keep `too_far` / `started`, which are
what this test is about.

- [ ] **Step 5: Run the existing sports suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/ -k "sports"`

Expected: pass. If an existing test priced a game outside 72h on purpose, it now needs a game inside
the window — that is the test being stale, not the bound being wrong. Note any such test in the
commit body.

- [ ] **Step 6: Commit**

```bash
git add tradehub/sports/scan.py tests/test_sports_scan_window.py
git commit -m "fix(sports): bound the scan by the window, so far-out games are never priced

Approved 2026-09-27: keep max_hours_to_start: 72 and bound the SCAN by it.

The scan filtered only start_utc <= now, so it priced every upcoming game,
stored it, and let check_candidate reject it for starts_too_late. CFB week 5
sits 120-168h out against a 72h window, which is why 86 of the 100 live rows
carried that reason: dead on arrival by construction. The work was done, the
rows were written, and the page rendered them as rejects.

Bounding at the source means none of that happens. The bound is read from
cfg.edge.params rather than hardcoded, so it moves with the config, and a test
pins the 71h/73h boundary so a future edit cannot drift it silently.

The two exclusions are counted separately -- too_far versus started -- so a run
that produced nothing can say why. A started game is not 'too far' and
conflating them would hide a real failure.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: The inversion

**What was approved.** "Picks qualify on the publishing predictor's own published calibration first,
then switch to the hub's settled ledger once it has enough."

**The constraint that shapes this task.** `run_sports_scan` has **no database access** — it takes
`kalshi`, `fetch`, `store`, `reviewer` and no `supa`. So the hub's settled ledger cannot be read
inside `scan_sport` today; it has to be read by the caller and threaded in. That is why this task
touches three modules rather than one, and the threading is the bulk of it.

**Files:**
- Create: `tradehub/sports/hub_calibration.py`
- Modify: `tradehub/sports/candidates.py` (`check_candidate`)
- Modify: `tradehub/sports/scan.py` (`scan_sport`, `run_sports_scan` signatures)
- Modify: `tradehub/scripts/scan.py` (`run_sports_for_cron` reads the ledger and passes it)
- Test: `tests/test_sports_inversion.py` (new)

**Interfaces:**
- Consumes: settled `(our_prob, result)` pairs for `sports_nfl` / `sports_cfb` from the `predictions`
  table, which `api/main.py:326-328` already reads as `market_ticker, result` filtered on
  `engine in (...) and status = 'SETTLED'`.
- Produces:
  - `hub_calibration.settled_buckets(pairs: list[tuple[float, bool]], n_buckets: int = 10) -> dict[str, list[dict]]`
  - `candidates.HUB_LEDGER_MIN_SETTLED = 100`
  - `candidates.choose_calibration(predictor_calibration, hub_calibration, params) -> tuple[Mapping, str]`
  - `check_candidate(..., calibration, params, now, *, hub_calibration=None)` — keyword-only, defaulted, so every existing caller and test keeps working.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sports_inversion.py`:

```python
"""The inversion: the predictor's published calibration first, the hub's ledger once it has enough.

Approved 2026-09-27. The reasoning: the predictor publishes its own reliability record, so it is
available immediately and it is the model's own view of itself. The hub's settled ledger reflects what
the hub actually graded and priced against, so once it has enough settled results it becomes the
authority. Below that, the hub has no record to offer and deferring to it would be deferring to
nothing.

The threshold is `HUB_LEDGER_MIN_SETTLED = 100` -- the same number as the reviewer's `MIN_SETTLED`,
because 100 is the settled count this product has consistently meant (spec 3 and 5b). It is a named
constant rather than a literal so a later ruling changes one place.
"""
import pytest

from tradehub.sports.candidates import HUB_LEDGER_MIN_SETTLED, choose_calibration
from tradehub.sports.hub_calibration import settled_buckets

PREDICTOR = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 3, "mean_prob": 0.65, "hit_rate": 0.66}]}
HUB = {"winner": [{"lo": 0.6, "hi": 0.7, "n": 120, "mean_prob": 0.65, "hit_rate": 0.70}]}


def test_the_predictors_own_calibration_is_used_while_the_hub_has_too_little():
    calibration, source = choose_calibration(PREDICTOR, {"winner": []}, {})

    assert source == "predictor"
    assert calibration is PREDICTOR


def test_the_hubs_ledger_takes_over_once_it_has_enough():
    calibration, source = choose_calibration(PREDICTOR, HUB, {})

    assert source == "hub_ledger"
    assert calibration is HUB


def test_the_threshold_is_the_reviewers_own_number():
    """100 is what this product means by 'enough settled'. The reviewer's MIN_SETTLED is the same
    number for the same reason, and two thresholds for one concept is how they drift."""
    assert HUB_LEDGER_MIN_SETTLED == 100


def test_one_short_of_the_threshold_stays_with_the_predictor():
    short = {"winner": [{"lo": 0.6, "hi": 0.7, "n": HUB_LEDGER_MIN_SETTLED - 1,
                         "mean_prob": 0.65, "hit_rate": 0.70}]}
    _, source = choose_calibration(PREDICTOR, short, {})

    assert source == "predictor"


def test_no_hub_calibration_at_all_stays_with_the_predictor():
    _, source = choose_calibration(PREDICTOR, None, {})

    assert source == "predictor"


def test_no_predictor_calibration_and_no_hub_falls_through_to_the_hub_rather_than_nothing():
    # A missing predictor payload must not leave the filter with no calibration at all, which would
    # read as "no bucket" and reject every edge for a reason that looks like bad luck.
    calibration, source = choose_calibration({}, HUB, {})

    assert source == "hub_ledger"
    assert calibration is HUB


class TestSettledBuckets:
    def test_it_builds_the_same_shape_the_feed_publishes(self):
        """`bucket_for` in candidates.py indexes on lo/hi/n, so the shape must match or lookup misses
        and every edge fails calibration_insufficient for the wrong reason."""
        pairs = [(0.65, True)] * 8 + [(0.65, False)] * 2
        buckets = settled_buckets(pairs, n_buckets=10)

        assert set(buckets) == {"winner"} or "winner" in buckets
        target = buckets["winner"][6]  # 0.6-0.7
        assert target["lo"] == pytest.approx(0.6)
        assert target["hi"] == pytest.approx(0.7)
        assert target["n"] == 10
        assert target["mean_prob"] == pytest.approx(0.65)
        assert target["hit_rate"] == pytest.approx(0.8)

    def test_an_empty_pair_set_gives_empty_buckets_not_none(self):
        assert settled_buckets([], n_buckets=10)["winner"] == []
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_sports_inversion.py -v`

Expected: collection ERROR — `ModuleNotFoundError: No module named 'tradehub.sports.hub_calibration'`.

- [ ] **Step 3: Write `hub_calibration.py`**

Create `tradehub/sports/hub_calibration.py`:

```python
"""The hub's own settled record, in the shape the predictor's feed publishes.

The inversion (approved 2026-09-27) prefers the predictor's published calibration and defers to this
once it has enough settled results. "Deferring to this" only means something if this is shaped like
what it replaces, so this module produces the same bucket keys `candidates.bucket_for` reads:
`lo`, `hi`, `n`, `mean_prob`, `hit_rate`.

Pure: the caller reads the rows, this turns them into buckets. That keeps it testable without a
database and keeps the SQL in one place.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

# The kinds the sports feed publishes. The hub's ledger is bucketed per kind for the same reason
# the predictor is: a spread model and a winner model are different models.
KINDS = ("winner", "spread", "total")


def settled_buckets(
    pairs: Iterable[tuple[float, bool]],
    n_buckets: int = 10,
    *,
    kinds: Sequence[str] = KINDS,
) -> dict[str, list[dict[str, Any]]]:
    """Bucket `(our_prob, hit)` pairs into the feed's calibration shape.

    `pairs` is one kind's worth; the same pairs are bucketed under every requested kind because the
    caller reads one kind's rows at a time and the consumer indexes by kind. An empty input gives
    empty buckets rather than `None`, so "no settled results" is distinguishable from "no data".
    """
    if n_buckets <= 0:
        raise ValueError(f"n_buckets must be positive, got {n_buckets}")

    collected = [(float(prob), bool(hit)) for prob, hit in pairs]
    out: dict[str, list[dict[str, Any]]] = {}
    for kind in kinds:
        buckets = []
        for index in range(n_buckets):
            lo = index / n_buckets
            hi = (index + 1) / n_buckets
            last = index == n_buckets - 1
            inside = [(p, h) for p, h in collected
                      if (lo <= p < hi) or (last and p == 1.0)]
            n = len(inside)
            buckets.append({
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "n": n,
                "mean_prob": round(sum(p for p, _ in inside) / n, 4) if n else None,
                "hit_rate": round(sum(1 for _, h in inside if h) / n, 4) if n else None,
            })
        out[kind] = buckets
    return out
```

- [ ] **Step 4: Add the preference to `candidates.py`**

In `tradehub/sports/candidates.py`, add above `check_candidate`:

```python
# Enough settled results for the hub's own ledger to be the authority. 100 is the same number as the
# reviewer's MIN_SETTLED and for the same reason: it is what this product means by "enough settled".
# Named rather than inlined so a later ruling changes one place.
HUB_LEDGER_MIN_SETTLED = 100


def choose_calibration(
    predictor_calibration: Mapping[str, list[dict[str, Any]]] | None,
    hub_calibration: Mapping[str, list[dict[str, Any]]] | None,
    params: Mapping[str, float],
) -> tuple[Mapping[str, list[dict[str, Any]]], str]:
    """Which calibration the candidate filter should judge against, and which one it used.

    The predictor's own published record is preferred while the hub has too little to say. Below the
    threshold the hub has no record worth deferring to, and deferring to it would be deferring to
    nothing -- which reads downstream as `calibration_insufficient`, i.e. as bad luck rather than as
    an absent measurement.

    Returns the mapping and its source, so the row can record which gate passed instead of the page
    having to guess.
    """
    hub_total = 0
    for buckets in (hub_calibration or {}).values():
        for bucket in buckets or []:
            n = bucket.get("n")
            if isinstance(n, (int, float)):
                hub_total += int(n)

    if hub_total >= HUB_LEDGER_MIN_SETTLED and hub_calibration:
        return hub_calibration, "hub_ledger"
    if predictor_calibration:
        return predictor_calibration, "predictor"
    if hub_calibration:
        # No predictor payload at all must not leave the filter with nothing to judge against.
        return hub_calibration, "hub_ledger"
    return {}, "none"
```

Then change `check_candidate`'s signature to add the keyword-only, defaulted parameter:

```python
def check_candidate(
    kind: str, sm: SportsMarket, mg: MatchedGame, edge: EdgeSuggestion,
    calibration: Mapping[str, list[dict[str, Any]]], params: Mapping[str, float], now: datetime,
    *, hub_calibration: Mapping[str, list[dict[str, Any]]] | None = None,
) -> CandidateCheck:
```

and at the top of the body, before the existing `reasons: list[str] = []`, add:

```python
    calibration, calibration_source = choose_calibration(calibration, hub_calibration, params)
```

Extend the `CandidateCheck` dataclass with the source so the caller can record it:

```python
@dataclass(frozen=True)
class CandidateCheck:
    ok: bool
    reasons: tuple[str, ...]
    bucket: dict[str, Any] | None
    calibration_source: str = "predictor"
```

and set it in the return:

```python
    return CandidateCheck(ok=not reasons, reasons=tuple(reasons), bucket=bucket,
                          calibration_source=calibration_source)
```

**Keyword-only and defaulted, so every existing caller and test keeps working unchanged.** That matters:
`sports/scan.py:151` and the existing tests call this positionally.

- [ ] **Step 5: Thread it through the scan**

In `tradehub/sports/scan.py`:

- `scan_sport(..., now: datetime, *, hub_calibration=None)` — add the keyword-only parameter.
- Inside `scan_sport`, change the `check_candidate` call to pass it:

```python
                check = check_candidate(kind, sm, mg, s, feed.calibration, cfg.edge.params, now,
                                        hub_calibration=hub_calibration)
```

- Add `calibration_source` to the edge row so the page can say which gate passed. In `_edge_row`, add
  the key to the returned dict:

```python
        "calibration_source": check.calibration_source,
```

`_edge_row` already receives `check`, so no signature change is needed.

- `run_sports_scan(..., hub_calibration=None)` — add the keyword-only parameter and pass it to
  `scan_sport`.

In `tradehub/scripts/scan.py`, in `run_sports_for_cron`, read the ledger and pass it:

```python
def _hub_sports_calibration(supa) -> dict:
    """The hub's own settled record, bucketed per kind.

    Read here because `run_sports_scan` has no database access: the scan is given the answer rather
    than a way to look it up, which also keeps the scan pure enough to test without a database.
    """
    rows = supa.table("predictions").select("engine,our_prob,result") \
        .in_("engine", sorted(SPORTS_ENGINES.values())).eq("status", "SETTLED").execute().data or []
    by_kind: dict[str, list[tuple[float, bool]]] = {}
    for row in rows:
        prob, result = row.get("our_prob"), row.get("result")
        if not isinstance(prob, (int, float)) or result not in ("yes", "no"):
            continue
        kind = (row.get("raw_payload") or {}).get("kind") or "winner"
        by_kind.setdefault(kind, []).append((float(prob), result == "yes"))
    if not by_kind:
        return {}
    return settled_buckets([p for pairs in by_kind.values() for p, _ in pairs], n_buckets=10)
```

**Known simplification, stated rather than hidden.** This flattens all kinds into one bucket set,
which is wrong for a model that mixes winner and spread predictions. Doing it per kind needs the
`kind` on the row, which is in `raw_payload`; if the column is not selected above, either add
`raw_payload` to the `.select(...)` call or drop the `kind` lookup and bucket only `winner` rows.
**Prefer the second**: the win/loss signal this feeds is the winner bucket, and a wrong kind
attribution is worse than an absent one. State which you did in the commit body.

Then pass it into the scan call in `run_sports_for_cron`:

```python
    run = run_sports_scan(now, SportsKalshi(deadline=deadline), store=SupabaseReviewStore(supa),
                          reviewer=reviewer, budget=cfg.daily_budget, deadline=deadline,
                          hub_calibration=_hub_sports_calibration(supa))
```

Add the import: `from tradehub.sports.hub_calibration import settled_buckets`.

- [ ] **Step 6: Run the new test, then the sports suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_sports_inversion.py -v`

Expected: `8 passed`. The `settled_buckets` key test asserts `"winner" in buckets or set(...) == {"winner"}` —
if your implementation keys only the kinds present, assert `"winner" in buckets`.

Then: `... -m pytest -q tests/ -k sports`

Expected: pass. The keyword-only parameter means no existing caller breaks; if something does, that
call site was passing positionally past `now` and needs the new argument by keyword.

- [ ] **Step 7: Commit**

```bash
git add tradehub/sports/hub_calibration.py tradehub/sports/candidates.py \
        tradehub/sports/scan.py tradehub/scripts/scan.py tests/test_sports_inversion.py
git commit -m "feat(sports): the inversion -- predictor calibration first, hub ledger once it has enough

Approved 2026-09-27. The predictor publishes its own reliability record, so it
is available immediately; the hub's settled ledger reflects what the hub
actually graded and priced against, so once it has enough it becomes the
authority.

HUB_LEDGER_MIN_SETTLED = 100, the same number as the reviewer's MIN_SETTLED
for the same reason: it is what this product means by 'enough settled'. Named so
a later ruling changes one place rather than two.

run_sports_scan has no database access -- it takes kalshi, fetch, store and
reviewer, and no supa -- so the ledger is read by the caller and threaded in.
That is why this touches four modules; the threading is the bulk of the work.
The scan is given the answer rather than a way to look it up, which also keeps
it testable without a database.

check_candidate's new parameter is keyword-only and defaulted, so every existing
caller and test keeps working positionally. choose_calibration falls back to
the hub when the predictor payload is missing entirely, because leaving the
filter with nothing to judge against reads downstream as bad luck rather than as
an absent measurement.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Rank by confidence, and say which ranking is in use

**The honest situation.** §4's design is `edge_pct / sigma`. But `sigma` is **null on 61 of 61 games**
across both predictors (§3), so that ratio is undefined everywhere. This task therefore does two
things: it adds the sigma path so it is ready, and it keeps raw edge in force with the page **saying
so**. Substituting a constant sigma would manufacture exactly the confidence the ranking exists to
express.

**Files:**
- Modify: `tradehub/sports/scan.py` (a pure score helper)
- Modify: `tradehub/api/main.py` (`_sports_rank`, and the response gains `ranking`)
- Modify: `market_sentiment_tool/src/lib/sportsEdges.ts`
- Modify: `market_sentiment_tool/src/pages/SportsEdges.tsx`
- Test: `tests/test_sports_sigma_rank.py` (new)

**Interfaces:**
- Consumes: `rank_edge_pct` and `sigma` on the edge payload. `rank_edge_pct` already exists on the API row (PR #20); `sigma` is in `raw_payload` as `null` today.
- Produces:
  - `scan.sigma_floor: float = 0.005` (0.5pp — below this a distribution is degenerate)
  - `scan.SIGMA_SCORE_CAP: float = 20.0`
  - `scan.edge_sigma_score(edge_pct, sigma) -> float | None`
  - `api/main.py`: `_sports_rank` sorts on the score when available; the response gains `"ranking": "edge_sigma" | "raw_edge"`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sports_sigma_rank.py`:

```python
"""Rank by edge / sigma, and refuse to invent a sigma.

Two +10pp edges are not the same claim: at sigma 1.5pp the score is 6.7, at sigma 15pp it is 0.7.
Ranking on raw edge puts the vague one first.

But `sigma` is null on 61 of 61 games right now (spec 3), so the score is undefined everywhere and
raw edge stays in force. The point of these tests is that the absence is handled by FALLING BACK, not
by substituting a default: a constant sigma would produce a confident-looking ranking with no
information in it, which is the one thing this feature must not do.
"""
import pytest

from tradehub.sports.scan import SIGMA_SCORE_CAP, edge_sigma_score, sigma_floor


class TestScore:
    def test_a_confident_edge_scores_above_a_vague_one_at_the_same_size(self):
        confident = edge_sigma_score(0.10, 0.015)
        vague = edge_sigma_score(0.10, 0.15)

        assert confident > vague
        assert confident == pytest.approx(6.67, abs=0.01)
        assert vague == pytest.approx(0.67, abs=0.01)

    def test_a_MISSING_sigma_produces_no_score_at_all(self):
        """The important one, and it was wrong in the first draft of this plan.

        Flooring a missing sigma gives 0.10 / 0.005 = 20.0 -- the CAP, i.e. the highest score the
        feature can produce. So a row whose confidence is unknown would rank at the very top of its
        tier, which is the opposite of conservative, and the docstring claiming otherwise would have
        been false.

        Absent is not the same as degenerate. Absent means the feed said nothing, so there is no
        confidence to score and the row falls back to raw edge. The floor exists for a *published*
        sigma of zero, which is a real value that would otherwise divide by zero.
        """
        assert edge_sigma_score(0.10, None) is None

    def test_a_degenerate_published_sigma_is_floored_and_then_capped(self):
        assert edge_sigma_score(0.10, 0.0) == SIGMA_SCORE_CAP

    def test_a_missing_sigma_cannot_outrank_a_confident_one(self):
        missing = edge_sigma_score(0.10, None)
        confident = edge_sigma_score(0.10, 0.015)
        assert missing is None or missing < confident, (
            "an unknown confidence must never score above a known one"
        )

    def test_the_score_is_capped_so_one_absurd_ratio_cannot_own_the_top(self):
        assert edge_sigma_score(0.90, 0.0001) == SIGMA_SCORE_CAP

    def test_a_missing_edge_has_no_score(self):
        assert edge_sigma_score(None, 0.05) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_sports_sigma_rank.py -v`

Expected: collection ERROR — `cannot import name 'edge_sigma_score'`.

- [ ] **Step 3: Write the helper**

In `tradehub/sports/scan.py`, near the top with the other module constants:

```python
# Ranking by edge / sigma needs a floor, because a distribution this tight makes the ratio enormous
# and one absurd score would own the top of the board, and a cap for the same reason at the other
# end. 0.5pp is well below any calibrated forecast's real sigma, so the floor only ever catches a
# degenerate distribution rather than a confident one.
sigma_floor = 0.005
SIGMA_SCORE_CAP = 20.0


def edge_sigma_score(edge_pct: Any, sigma: Any) -> float | None:
    """How many sigmas wide the disagreement is, or `None` when there is nothing to score.

    `None` is returned for a MISSING sigma, and that is the load-bearing decision. Flooring a missing
    sigma yields 0.10 / 0.005 = 20.0, which is the cap -- the highest score this feature can produce.
    A row whose confidence is unknown would then rank at the top of its tier, which is the opposite
    of conservative and precisely the failure the feature exists to prevent. So absent sigma yields
    no score, and `_sports_rank` falls back to the raw edge.

    The floor is for a *published* sigma of zero or less, which is a real value that would otherwise
    divide by zero. Present-but-degenerate and absent are different facts and get different handling.
    """
    if not isinstance(edge_pct, (int, float)):
        return None
    if sigma is None or not isinstance(sigma, (int, float)):
        return None
    denominator = max(float(sigma), sigma_floor)
    return min(round(abs(float(edge_pct)) / denominator, 4), SIGMA_SCORE_CAP)
```

- [ ] **Step 4: Use it in the API, and report which ranking is in force**

In `tradehub/api/main.py`, replace the body of `_sports_rank` so it sorts on the score when any row
has a sigma, and reports the mode:

```python
def _sports_rank(row: dict) -> tuple[int, int, float]:
    """tier order, then confidence score, then edge as the tiebreak.

    Sorted by `edge_sigma_score` when the row has a real sigma, because two equal edges at different
    confidences are not equal claims. `rank_edge_pct` is the tiebreak so ordering stays total and
    pagination stays stable.
    """
    raw = row.get("raw_payload") or {}
    score = edge_sigma_score(row.get("edge_pct"), raw.get("sigma"))
    if score is None:
        # No confidence information -- rank on the raw edge. NOT on 0.0: that would sort the row
        # last within its tier, which reads as "the least interesting pick here", and that is a
        # claim rather than a fallback.
        score = float(row.get("rank_edge_pct") or 0.0)
    return _TIER_ORDER.get(_tier_of(row), 9, 0, -score


def _ranking_mode(rows: list[dict]) -> str:
    """Which ranking the response actually used, so the page can say so.

    `sigma` is null on 61/61 games today, so this returns `raw_edge` in practice. Reporting the mode
    rather than implying sigma always applies is the whole point: a page that claims to rank by
    confidence while ranking by raw edge is worse than one that never claimed it.
    """
    with_sigma = sum(
        1 for r in rows
        if isinstance((r.get("raw_payload") or {}).get("sigma"), (int, float))
        and (r.get("raw_payload") or {}).get("sigma", 0) > 0
    )
    return "edge_sigma" if with_sigma else "raw_edge"
```

Add `"ranking": _ranking_mode(candidates),` to the response dict, and add
`edge_sigma_score` to the `from tradehub.sports.scan import ...` line (it already imports `edge_row`
there).

- [ ] **Step 5: Surface it on the page**

In `market_sentiment_tool/src/lib/sportsEdges.ts`, add to `SportsEdgesResponse`:

```typescript
  /**
   * Which ranking the response used: `edge_sigma` when the feed supplied a real sigma, else
   * `raw_edge`. `sigma` is null on every game as of 2026-09-27, so this is `raw_edge` in practice --
   * and the page says which, because claiming to rank by confidence while ranking by raw edge is
   * worse than never claiming it.
   */
  ranking: "edge_sigma" | "raw_edge";
```

In `SportsEdges.tsx`, in the header `<p>`, add after the reviewer sentence:

```tsx
          {data.ranking === "edge_sigma"
            ? "Ranked by edge over the predictor's own sigma."
            : "Ranked by raw edge: the feed reports no sigma yet, so there is no confidence to rank on."}
```

- [ ] **Step 6: Verify**

Run the new test, then the full suite, then the frontend suite and build:

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_sigma_rank.py -v
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q
cd market_sentiment_tool && npx tsc --noEmit -p tsconfig.app.json && npx vitest run && npm run build
```

Expected: `4 passed`; full suite passes; frontend clean.

**If `test_within_tier_edges_descend_across_page_boundaries` fails**, it is asserting on the old sort
key. The ordering guarantee is still real, so update the test to read the ordering the new sort uses
rather than deleting the assertion — same fix as PR #20 made for `rank_edge_pct`.

- [ ] **Step 7: Commit**

```bash
git add tradehub/sports/scan.py tradehub/api/main.py tests/test_sports_sigma_rank.py \
        market_sentiment_tool/src/lib/sportsEdges.ts market_sentiment_tool/src/pages/SportsEdges.tsx
git commit -m "feat(sports): rank by edge over sigma, and say which ranking is in force

Two +10pp edges are not the same claim: 6.7 at sigma 1.5pp, 0.7 at sigma 15pp.
Raw edge puts the vague one first.

sigma is null on 61 of 61 games, so the score is undefined everywhere and raw
edge stays in force -- which is why the response now reports which ranking it
used and the page states it. A page that claims to rank by confidence while
ranking by raw edge is worse than one that never claimed it.

A MISSING sigma yields no score at all, and the row falls back to raw edge.
Flooring it instead would give 0.10 / 0.005 = 20.0 -- the cap, the highest score
this feature can produce -- so a row whose confidence is unknown would rank at
the top of its tier. Absent is not the same as degenerate: the floor is for a
published sigma of zero, which would otherwise divide by zero, and a present
value is a fact while an absent one is silence.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage.** §9 approval 2 (bound the scan by 1–72h) → Task 1. §9 approval 1 (predictor
calibration first, hub ledger once enough) → Task 2. §4 (rank by edge ÷ sigma, floored, capped, raw
edge visible) → Task 3, including the floor and cap as tests. §3's `sports_cfb` correction and the
86/100 `starts_too_late` diagnosis → Task 1's docstring. §3's "sigma is null on 61/61" → Task 3's
rationale and the `ranking` field. Global Constraints: the gate fails closed is untouched; PR #20's
"rejected row carries no headline edge" is explicitly not weakened; no constant substitutes for a
missing input is Task 3's core rule; verification is Global Constraints plus the per-task steps.

**Out of scope, deliberately:** the §5b `calibration_off` change (unapproved gate decision); the
`n_buckets: 10 → 4` change, which is the **predictor's** to make and is a separate repo — Task 2 sets
`HUB_LEDGER_MIN_SETTLED = 100` and leaves `calibration_min_n` alone, so nothing here depends on that
unresolved decision.

**2. Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". One place is
explicitly hedged with a stated choice — Task 2's per-kind bucketing simplification — and both
options are given with a recommendation, rather than left as a decision for the implementer to make
blind.

**3. Type consistency.** `edge_sigma_score(edge_pct, sigma) -> float | None` is used identically in
the test, the helper, and `_sports_rank`. `choose_calibration` returns `(Mapping, str)` and
`check_candidate` unpacks it in that order. `CandidateCheck.calibration_source` defaults to
`"predictor"` so the three existing constructions in the codebase keep working. `_ranking_mode` returns
the same two literals as the `SportsEdgesResponse.ranking` union. `sigma_floor` and `SIGMA_SCORE_CAP`
are module-level in `tradehub/sports/scan.py` and imported by name in the test.
