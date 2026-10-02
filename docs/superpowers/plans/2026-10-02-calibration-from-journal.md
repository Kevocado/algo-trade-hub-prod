# Sports Calibration From the Journal (Roadmap v2 item 12) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the hub's own settled sports record, which decides when its calibration replaces the predictor's published one, come from the journal instead of the `predictions` table.

**Architecture:** `scan._hub_settled_ledger` counted every settled `predictions` row, so a ladder of 25 rungs of one spread counted as 25 pieces of evidence. The journal holds one frozen, Kalshi-settled forecast per game and kind. A new reader, `journal_settled_ledger`, returns the same `HubLedger` shape (`engine -> kind -> [(probability, hit)]`) from `journal_forecasts` and `journal_settlements`, with the same failure behaviour (a failed read is `read_failed=True`, published as not measured, and the scan falls back to the predictor's calibration).

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§10 gates). **Depends on:** plan 11 (spread and total consumers) merged.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend suite all-pass at both clocks on the final stack). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Behaviour change to expect and not fix:** the 60 settled winner rows in `predictions` are not in the journal, so the hub record starts again from zero per kind and the existing `HUB_LEDGER_MIN_SETTLED` rule keeps the predictor's calibration in charge until the journal has enough. That is the intended, honest reading: the old rows were never frozen before kickoff.
- `predictions` keeps being written for sports and is still read by the reviewer scorecard (`api/main.py`, all rungs) and by the dedup in `scan.unrecorded`. Do not change those here.
- `_hub_settled_ledger` and its tests stay for now (they document the old rule). Nothing in production calls it after this plan. The roadmap lists its deletion as a follow-up.
- No migration.

---
### Task 1: The journal-backed ledger

**Files:**
- Create: `tradehub/sports/journal_ledger.py`, `tests/test_sports_journal_ledger.py`
- Modify: `tradehub/sports/scan.py` (`run_sports_for_cron` uses it; the import is inside the function because the new module imports `scan`)

**Interfaces:**
- Consumes: `tradehub.journal.store.{FORECASTS, select_all, fetch_settlements}`, `scan.{SPORTS_ENGINES, HubLedger}`, `sports.kinds.KINDS`.
- Produces: `journal_settled_ledger(supa) -> HubLedger`; `HUB_FEED_VERSION == 'feed-v1'` (pinned to the journal's own constant by a test).

- [ ] **Step 1: Write the failing test** (`tests/test_sports_journal_ledger.py`)

`tests/test_sports_journal_ledger.py`:

```python
from datetime import UTC, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.journal.forecasters.sports import FEED_VERSION
from tradehub.sports import scan as scan_mod
from tradehub.sports.journal_ledger import HUB_FEED_VERSION, journal_settled_ledger

NOW = datetime(2026, 9, 27, 2, 0, tzinfo=UTC)


def _seed(db, forecaster, target, prob, outcome, *, version=FEED_VERSION):
    """One frozen forecast and, when `outcome` is not None, its settlement, via the fake's own rules."""
    clock = db.clock
    if not any(c["target"] == target for c in db.tables["journal_calendars"]):
        db.insert("journal_calendars", {"target": target, "family": "f", "cadence": "daily",
                                        "cutoff_at": (NOW + timedelta(hours=10)).isoformat(),
                                        "market_linked": True, "climatology_prob": None})
    db.insert("journal_forecasts", {"forecaster": forecaster, "forecaster_version": version, "target": target,
                                    "probability": prob, "market_prob": None, "source_hash": None, "payload": {}})
    if outcome is not None:
        db.clock = lambda: NOW + timedelta(hours=11)
        if not any(s["target"] == target for s in db.tables["journal_settlements"]):
            db.insert("journal_settlements", {"target": target, "outcome": outcome, "realized_value": None,
                                              "source": "kalshi"})
        db.clock = clock


def _db():
    return FakeJournalDB(lambda: NOW)


def test_the_hub_reads_the_feed_version_the_journal_writes():
    assert HUB_FEED_VERSION == FEED_VERSION


def test_each_kind_is_read_from_its_own_forecaster_and_filed_under_the_hub_engine():
    db = _db()
    _seed(db, "sports_nfl", "kalshi:W1", 0.65, 1)
    _seed(db, "sports_nfl", "kalshi:W2", 0.62, 0)
    _seed(db, "sports_nfl_spread", "kalshi:S1", 0.30, 0)
    _seed(db, "sports_cfb_total", "kalshi:T1", 0.72, 1)
    _seed(db, "sports_cfb", "kalshi:W3", 0.40, 0)
    # never part of the record: a market baseline, another version, an unsettled forecast, a stranger
    _seed(db, "kalshi_implied_sports_nfl", "kalshi:W1", 0.5, 1)
    _seed(db, "sports_nfl", "kalshi:W4", 0.9, 1, version="feed-v0")
    _seed(db, "sports_nfl", "kalshi:W5", 0.55, None)
    _seed(db, "spy_quant", "kalshi:X", 0.5, 1)
    ledger = journal_settled_ledger(db)
    assert ledger.pairs_by_engine == {
        "sports_nfl": {"winner": [(0.65, True), (0.62, False)], "spread": [(0.30, False)]},
        "sports_cfb": {"winner": [(0.40, False)], "total": [(0.72, True)]},
    }
    assert ledger.unrecognised_by_engine == {} and ledger.read_failed is False


def test_a_probability_is_the_frozen_one_and_the_hit_is_the_settled_outcome_not_a_guess():
    db = _db()
    _seed(db, "sports_nfl", "kalshi:A", 0.2, 1)   # the model said 20% and YES happened
    assert journal_settled_ledger(db).pairs_by_engine == {"sports_nfl": {"winner": [(0.2, True)]}}


def test_a_failed_read_is_not_measured_not_empty():
    class Broken:
        def table(self, _name):
            raise RuntimeError("postgrest 500")

    ledger = journal_settled_ledger(Broken())
    assert ledger == scan_mod.HubLedger(read_failed=True) and ledger != scan_mod.HubLedger()


def test_a_missing_journal_table_is_not_measured_too():
    class NoTable:
        def table(self, _name):
            raise RuntimeError('relation "journal_forecasts" does not exist')

    assert journal_settled_ledger(NoTable()).read_failed is True


def test_the_cron_reads_the_journal_not_the_predictions_table(monkeypatch):
    seen = {}

    def fake_run(now, kalshi, **kw):
        seen["ledger"] = kw["hub_ledger"]
        return scan_mod.SportsRun([], [], {}, {})

    db = _db()
    _seed(db, "sports_nfl", "kalshi:A", 0.7, 1)
    monkeypatch.setattr(scan_mod, "run_sports_scan", fake_run)
    monkeypatch.setattr(scan_mod, "unrecorded", lambda supa, rows: rows)
    monkeypatch.setattr(scan_mod, "SupabaseReviewStore", lambda supa: None)
    scan_mod.run_sports_for_cron(NOW, db)
    assert seen["ledger"].pairs_by_engine == {"sports_nfl": {"winner": [(0.7, True)]}}
```

- [ ] **Step 2: Run it** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_sports_journal_ledger.py` — Expected: FAIL (the code below does not exist yet).

- [ ] **Step 3: Implement**

`tradehub/sports/journal_ledger.py`:

```python
"""The hub's own settled record for sports, read from the prediction journal.

`scan._hub_settled_ledger` used to build this from every settled `predictions` row, which counted all the
rungs of a spread or total ladder as separate evidence. The journal journals one market per game and kind
(`tradehub.journal.forecasters.sports`), frozen before kickoff and settled on Kalshi's own result, so this
record is the same facts without the double counting. The shape it returns, `HubLedger`, is unchanged:
`engine -> kind -> [(probability, hit)]`.

It never raises: a failed or impossible read returns `HubLedger(read_failed=True)`, which the run report
publishes as "not measured", and the scan falls back to the predictor's published calibration exactly as it
did before.
"""

from __future__ import annotations

import logging

from tradehub.journal.store import FORECASTS, fetch_settlements, select_all
from tradehub.sports.kinds import KINDS
from tradehub.sports.scan import SPORTS_ENGINES, HubLedger

log = logging.getLogger(__name__)

# Spelled out, not imported: `journal.forecasters.sports` imports `sports.scan`, so importing it back
# would be a cycle. A test pins this to the journal's own constant.
HUB_FEED_VERSION = "feed-v1"


def _forecaster(sport: str, kind: str) -> str:
    """The journal's name for one sport and kind: `sports_nfl`, `sports_nfl_spread`, `sports_nfl_total`."""
    return f"sports_{sport}" + ("" if kind == "winner" else f"_{kind}")


def journal_settled_ledger(supa) -> HubLedger:
    pairs: dict[str, dict[str, list[tuple[float, bool]]]] = {}
    try:
        for sport, engine in SPORTS_ENGINES.items():
            for kind in KINDS:
                name = _forecaster(sport, kind)
                forecasts = select_all(
                    supa, FORECASTS,
                    lambda q, n=name: q.eq("forecaster", n).eq("forecaster_version", HUB_FEED_VERSION),
                    ("id",))
                outcomes = fetch_settlements(supa, [f["target"] for f in forecasts])
                rows = [(float(f["probability"]), bool(outcomes[f["target"]]))
                        for f in forecasts if f["target"] in outcomes]
                if rows:
                    pairs.setdefault(engine, {})[kind] = rows
    except Exception:
        log.exception("sports scan: journal read failed; using the predictor's calibration")
        return HubLedger(read_failed=True)
    return HubLedger(pairs, {})
```

`tradehub/sports/scan.py`:

```diff
diff --git a/tradehub/sports/scan.py b/tradehub/sports/scan.py
index b3cd6d3..cdc3615 100644
--- a/tradehub/sports/scan.py
+++ b/tradehub/sports/scan.py
@@ -996,6 +996,8 @@ def _hub_settled_ledger(supa) -> HubLedger:
 
 
 def run_sports_for_cron(now: datetime, supa, *, deadline: float | None = None) -> SportsRun:
+    from tradehub.sports.journal_ledger import journal_settled_ledger  # here: it imports this module
+
     cfg = load_reviewer_config()
     key = os.getenv("OPENROUTER_API_KEY")
     reviewer = OpenRouterReviewer(key, cfg.model, cfg.timeout_seconds, deadline=deadline) if key else None
@@ -1003,7 +1005,7 @@ def run_sports_for_cron(now: datetime, supa, *, deadline: float | None = None) -
     # series and must not be able to overrun the hourly timer and overlap the next run.
     run = run_sports_scan(now, SportsKalshi(deadline=deadline), store=SupabaseReviewStore(supa), reviewer=reviewer,
                           budget=cfg.daily_budget, deadline=deadline,
-                          hub_ledger=_hub_settled_ledger(supa))
+                          hub_ledger=journal_settled_ledger(supa))
     return SportsRun(unrecorded(supa, run.predictions), run.edges, run.reports, run.per_sport)
 
 
```

- [ ] **Step 4: Run** — `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_sports_journal_ledger.py tests/test_sports_inversion.py tests/test_sports_scan.py` — Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports tests/test_sports_journal_ledger.py
git commit -m "feat(sports): the hub's settled record comes from the journal"
```

---

### Task 2: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass (reviewer baseline on the final stack: see the roadmap).

- [ ] Ruff on the files this plan created or changed: `.venv/bin/python -m ruff check --select F tradehub/sports/journal_ledger.py tests/test_sports_journal_ledger.py` → `All checks passed!` (import-order findings on files you did not create are older debt, not yours).
- [ ] Open the PR from a fresh branch off `main` (title in the roadmap). Body: what changed, the verification output, and whether a migration needs applying. Then stop and report in 4 lines.

---

## Amendment (2026-10-02): the ledger covers winner markets only

**This plan's code is no longer what shipped.** PR #75 implemented it as written; a review of that work
then found a problem the plan did not anticipate, and Kevin ruled on it.

`journal_settled_ledger` as written iterates `kinds.KINDS`, so it filed settled spread and total pairs
into `HubLedger`. That is wrong, because of how plan 11 chose what to freeze: `one_rung` freezes only the
rung whose Kalshi mid is nearest a coin flip, so the settled spread/total probabilities cluster around 0.5
**by construction**. Calibration bands cut from that describe only the middle of the price range, and the
scan then applies them to every edge of the kind -- including the 0.9-priced rungs that no settled row can
ever represent. It fails closed, so nothing is mis-admitted, but it drops the highest-conviction edges while
the run report shows a settled record and nothing that would warn a reader.

**The ruling:** the hub's own settled record applies to **winner markets only**. For spread and total the
scan keeps the predictor's published calibration, whatever the journal ledger holds. The journal's
spread/total records still score and still appear on the page; they are simply not authoritative for
calibration.

**What shipped instead** (PR #79): `tradehub/sports/journal_ledger.py` gained

```python
HUB_LEDGER_KINDS = ("winner",)
```

and iterates that. **Revisit** when a season of settled rungs covers the whole price range -- and measure
before widening the tuple, because widening it is the entire fix.

## Self-Review

- **Reads what the journal writes:** one test seeds forecasts and settlements through the journal's own fake database and asserts the per-kind pairs, including that the baseline forecaster, another version, an unsettled forecast and a stranger are excluded.
- **Fails safe:** a broken client and a missing table both give `HubLedger(read_failed=True)`, which is not equal to a clean empty ledger.
- **Wired:** `test_the_cron_reads_the_journal_not_the_predictions_table` runs `run_sports_for_cron` and checks the ledger it hands the scan.
