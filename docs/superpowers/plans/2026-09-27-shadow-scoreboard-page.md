# Shadow Scoreboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A first-class page that answers "should I trust this engine?" by putting every engine's Brier next to the market's, and showing how far each one is from its own gate.

**Architecture:** The data already exists and is already written: `backtest_runs` carries `brier_ours`, `brier_market`, `n_settled`, `gate_status` and `gate_reasons` per run. This plan adds a read endpoint that reduces those runs to one current row per engine, and a page that renders the comparison. It adds no table, no writer, and no new measurement.

**Tech Stack:** Python 3.12, FastAPI, supabase-py, pytest, React 18 + TypeScript + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-hub-redesign.md` — §1 (every engine loses; the product must admit it), §6 (`/shadow` is the most important page and is currently a 500), §9 approval 4: *"Shadow scoreboard: YES, a first-class page. Each engine's Brier vs the market, and its distance to the gate."*

## Global Constraints

- **Suggest-only. This product never places an order** (spec §6). No figure on this page may read as a balance, a position, or a profit available to anyone.
- **An engine that loses stays visible, labelled.** The page's job is to show the losses clearly, not to soften them or hide them. No engine is omitted for having a bad number.
- **The gate fails closed.** Only an explicit `PROMOTED` renders as promoted; missing or unknown reads as not-promoted.
- **An experiment is not the engine.** `engine_version` carries the gas decision lead ([#25](https://github.com/Kevocado/algo-trade-hub-prod/pull/25)), so `gas-v1-lead12h` is an experiment and must never be presented as the engine's record. This plan's most important test is that one.
- **Verification before every push:** full `pytest` twice with `time.monotonic` forced to `5.0` **and** `1e7`, then `ruff check --select F401,F811,F821 tradehub tests`, then `npm run typecheck`, `npx vitest run`, `npm run build`.
- **This plan adds no migration and no writer.** If a task seems to need either, that is a signal the task is wrong.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `tradehub/scoreboard.py` | **New.** Pure reduction: many `backtest_runs` rows → one current row per engine, plus the gate-distance arithmetic. No I/O, so it is testable without a database. |
| `tradehub/api/main.py` | `GET /api/scoreboard` — reads `backtest_runs` and hands them to the pure reducer. |
| `tests/test_scoreboard_reduction.py` | **New.** The reducer, including the experiment/engine_version rule. |
| `tests/test_scoreboard_api.py` | **New.** Endpoint contract. |
| `market_sentiment_tool/src/lib/scoreboard.ts` | **New.** Pure: row type, Brier comparison formatting, gate-distance copy, verdict wording. |
| `market_sentiment_tool/src/lib/scoreboard.test.ts` | **New.** Unit tests. |
| `market_sentiment_tool/src/pages/Scoreboard.tsx` | **New.** The page. |
| `market_sentiment_tool/src/App.tsx` | Route `/scoreboard` and a nav entry. |

The `/shadow` route stays as it is. This is an **additional** page, not a replacement: `/shadow` is the
crypto shadow-timeline backtester, a different thing that happens to share a name. The nav entry is
labelled "Scoreboard" so the two are not confused.

---

## Task 1: The pure reducer

The only interesting logic in this feature, and it is worth isolating because it is where a wrong
answer would be least visible: *which run represents an engine*.

**Files:**
- Create: `tradehub/scoreboard.py`
- Test: `tests/test_scoreboard_reduction.py` (new)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `EXPERIMENT_VERSION = re.compile(r"-lead")`
  - `is_experiment_version(engine_version: str) -> bool`
  - `brier_ratio(brier_ours, brier_market) -> float | None`
  - `settled_distance(n_settled: int, required: int | None) -> dict | None`
  - `required_settled(gate_reasons: list[str], min_settled: int | None) -> int | None`
  - `current_runs(runs: list[dict]) -> list[dict]` — one row per engine, production versions only

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoreboard_reduction.py`:

```python
"""Reduce many backtest_runs rows to one honest row per engine.

The rule that matters most: a run whose `engine_version` carries a decision lead
(`gas-v1-lead12h`, from PR #25) is an EXPERIMENT, not the engine's record. Gas is
4.29x behind the market at the production 2h and 2.16x behind at 12h, so the two
disagree about the engine -- and the scoreboard's whole purpose is to tell a reader
whether to trust an engine. Presenting a 12h run as the record would make the page
wrong in the direction that flatters the engine.

So experiments are excluded from `current_runs` rather than shown with a footnote.
A footnote is a thing a reader skips; an absent row is a thing they cannot
misread. They remain in `backtest_runs` and remain reproducible from the CLI.
"""
import pytest

from tradehub.scoreboard import (
    brier_ratio,
    current_runs,
    is_experiment_version,
    required_settled,
    settled_distance,
)


def _run(engine, *, version, brier_ours=0.1242, brier_market=0.09713, n_settled=672,
         reasons=None, created_at="2026-09-27T00:00:00+00:00", mode="taker"):
    return {
        "engine": engine,
        "engine_version": version,
        "mode": mode,
        "date_from": "2026-06-01T00:00:00+00:00",
        "date_to": "2026-09-20T00:00:00+00:00",
        "n_decisions": 672,
        "n_fills": 232,
        "n_settled": n_settled,
        "pnl_after_fees": -7.62,
        "max_drawdown": 8.87,
        "brier_ours": brier_ours,
        "brier_market": brier_market,
        "gate_status": "SHADOW",
        "gate_reasons": reasons if reasons is not None else ["model Brier 0.1242 is not below market Brier 0.09713"],
        "created_at": created_at,
    }


class TestExperimentVersions:
    def test_a_tagged_lead_is_recognised(self):
        assert is_experiment_version("gas-v1-lead12h") is True
        assert is_experiment_version("gas-v1-lead6.5h") is True

    def test_the_production_version_is_not_an_experiment(self):
        assert is_experiment_version("gas-v1") is False

    def test_an_unrecognised_version_is_not_silently_treated_as_production(self):
        # Fail safe in the direction that matters: anything unexpected is not the plain engine.
        assert is_experiment_version("") is True
        assert is_experiment_version(None) is True
        assert is_experiment_version(123) is True

    def test_a_malformed_tag_still_counts_as_an_experiment(self):
        # The hole that made this unanchored: `-lead<number>h` does not match `gas-v1-lead`, so a
        # hand-edited or truncated tag would have read as the production engine.
        assert is_experiment_version("gas-v1-lead") is True
        assert is_experiment_version("gas-v1-lead12") is True

    @pytest.mark.parametrize("version", ["gas-v1", "weather-v1", "cpi-v1", "cpi-core-v1", "labor-v1"])
    def test_every_real_production_version_is_not_an_experiment(self, version):
        assert is_experiment_version(version) is False


class TestCurrentRuns:
    def test_an_experiment_never_becomes_the_engines_record(self):
        runs = [
            _run("gas", version="gas-v1", brier_ours=0.1148, brier_market=0.02676,
                 created_at="2026-09-20T00:00:00+00:00"),
            # Later, and better-looking. Must still lose.
            _run("gas", version="gas-v1-lead12h", brier_ours=0.11216, brier_market=0.0519,
                 created_at="2026-09-27T00:00:00+00:00"),
        ]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert rows[0]["engine_version"] == "gas-v1"
        assert float(rows[0]["brier_ours"]) == pytest.approx(0.1148)

    def test_the_latest_production_run_wins(self):
        runs = [
            _run("weather", version="weather-v1", brier_ours=0.13, created_at="2026-09-01T00:00:00+00:00"),
            _run("weather", version="weather-v1", brier_ours=0.1242, created_at="2026-09-20T00:00:00+00:00"),
        ]

        rows = current_runs(runs)

        assert len(rows) == 1
        assert float(rows[0]["brier_ours"]) == pytest.approx(0.1242)

    def test_taker_and_maker_are_kept_apart(self):
        # They are different fills and different economics; collapsing them would mix two
        # experiments into one number that means neither.
        runs = [
            _run("weather", version="weather-v1", mode="taker", brier_ours=0.1242),
            _run("weather", version="weather-v1", mode="maker", brier_ours=0.1180),
        ]

        rows = current_runs(runs)

        assert {r["mode"] for r in rows} == {"taker", "maker"}

    def test_one_row_per_engine_and_mode(self):
        runs = [
            _run("weather", version="weather-v1", mode="taker"),
            _run("gas", version="gas-v1", mode="taker"),
            _run("cpi_nowcast", version="cpi-v1", mode="taker"),
        ]

        assert len(current_runs(runs)) == 3

    def test_a_losing_engine_is_never_dropped(self):
        """The page exists to show losses. Omitting one would defeat it."""
        runs = [
            _run("gas", version="gas-v1", brier_ours=0.1148, brier_market=0.02676),
            _run("weather", version="weather-v1", brier_ours=0.1242),
            _run("labor_nowcast", version="labor-v1", brier_ours=0.1792, brier_market=0.1659),
        ]

        assert {r["engine"] for r in current_runs(runs)} == {"gas", "weather", "labor_nowcast"}


class TestBrierRatio:
    def test_the_ratio_is_how_far_behind_we_are(self):
        assert brier_ratio(0.1148, 0.02676) == pytest.approx(4.29, abs=0.01)

    def test_a_better_model_than_the_market_is_below_one(self):
        assert brier_ratio(0.05, 0.10) == pytest.approx(0.5)

    def test_missing_or_unusable_values_return_none_rather_than_guessing(self):
        assert brier_ratio(None, 0.1) is None
        assert brier_ratio(0.1, None) is None
        assert brier_ratio(0.1, 0) is None, "a zero market Brier has no defined ratio"


class TestGateDistance:
    def test_the_required_count_is_read_out_of_the_gate_reason(self):
        # The gate states its own requirement in words: "only 42 settled contracts, need 200 (daily)".
        assert required_settled(["only 42 settled contracts, need 200 (daily)"], None) == 200

    def test_an_explicit_minimum_wins_when_the_reason_does_not_state_one(self):
        assert required_settled(["no market Brier recorded"], 100) == 100

    def test_no_requirement_anywhere_is_none_not_zero(self):
        # Zero would render as "0 of 0", i.e. as having met the gate.
        assert required_settled(["model Brier 0.1 is not below market Brier 0.2"], None) is None

    def test_distance_reports_what_is_still_needed(self):
        assert settled_distance(42, 200) == {"n_settled": 42, "required": 200, "remaining": 158,
                                             "met": False, "pct": 21.0}

    def test_a_met_gate_says_so(self):
        assert settled_distance(120, 100) == {"n_settled": 120, "required": 100, "remaining": 0,
                                              "met": True, "pct": 100.0}

    def test_an_unknown_requirement_yields_no_distance(self):
        assert settled_distance(42, None) is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_scoreboard_reduction.py -v`

Expected: collection ERROR — `ModuleNotFoundError: No module named 'tradehub.scoreboard'`.

- [ ] **Step 3: Write the module**

Create `tradehub/scoreboard.py`:

```python
"""Reduce `backtest_runs` to one honest row per engine, for the scoreboard.

Pure on purpose: no I/O, so every rule below is testable without a database, and
so a reviewer can check the arithmetic rather than the plumbing.

The rule that matters: a run whose `engine_version` carries a decision lead is an
EXPERIMENT, not the engine's record. Gas is 4.29x behind the market at the
production 2h and 2.16x behind at 12h (PR #24), so the two runs disagree about
the engine, and this page exists to answer whether to trust an engine. Presenting
the 12h run as the record would make the page wrong in the direction that
flatters the engine. Experiments are therefore excluded rather than footnoted: a
footnote is something a reader skips, an absent row is something they cannot
misread. The runs stay in `backtest_runs` and stay reproducible from the CLI.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

# Any occurrence of the marker, NOT the anchored `-lead<number>h` form.
#
# The anchored version was tried first and has a hole: a malformed `gas-v1-lead` (missing the
# number and the h) does not match it and so reads as the production engine -- which is exactly the
# direction that must not fail. Unanchored is safe because no real production version contains
# "lead": they are gas-v1, weather-v1, cpi-v1, cpi-core-v1, labor-v1.
EXPERIMENT_VERSION = re.compile(r"-lead")

# The gate's own words, e.g. "only 42 settled contracts, need 200 (daily)".
_REQUIRED_IN_REASON = re.compile(r"need (\d+) settled", re.IGNORECASE)


def is_experiment_version(engine_version: Any) -> bool:
    """True for anything that is not plainly the production version.

    Fails safe: an absent, empty or unrecognised version is treated as an
    experiment, so a new tagging scheme cannot silently start being presented as
    an engine's record.
    """
    if not isinstance(engine_version, str) or not engine_version:
        return True
    return bool(EXPERIMENT_VERSION.search(engine_version))


def brier_ratio(brier_ours: Any, brier_market: Any) -> float | None:
    """How many times worse our Brier is than the market's. `None` when undefined.

    A zero or absent market Brier has no defined ratio, and returning a number
    there would be inventing one.
    """
    if not isinstance(brier_ours, (int, float)) or not isinstance(brier_market, (int, float)):
        return None
    if brier_market <= 0:
        return None
    return round(float(brier_ours) / float(brier_market), 4)


def required_settled(gate_reasons: Iterable[Any] | None, min_settled: int | None) -> int | None:
    """The settled count this engine's gate requires, or `None` if it does not say.

    The gate already states its own requirement in `gate_reasons`, so it is read
    from there rather than hardcoded per engine -- the bars genuinely differ, and
    duplicating them here would be a second place to get wrong.
    """
    for reason in gate_reasons or []:
        if not isinstance(reason, str):
            continue
        match = _REQUIRED_IN_REASON.search(reason)
        if match:
            return int(match.group(1))
    if isinstance(min_settled, int) and min_settled > 0:
        return min_settled
    return None


def settled_distance(n_settled: Any, required: int | None) -> dict[str, Any] | None:
    """How much settled evidence is still needed, or `None` if the bar is unknown."""
    if required is None or not isinstance(n_settled, (int, float)):
        return None
    required = int(required)
    met = int(n_settled) >= required
    return {
        "n_settled": int(n_settled),
        "required": required,
        "remaining": max(0, required - int(n_settled)),
        "met": met,
        "pct": round(min(100.0, 100.0 * int(n_settled) / required), 1) if required > 0 else 0.0,
    }


def current_runs(runs: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """One row per (engine, mode), from the newest production run.

    `mode` is part of the key: taker and maker are different fills and different
    economics, so collapsing them would blend two experiments into a number that
    means neither.
    """
    best: dict[tuple[str, str], Mapping[str, Any]] = {}
    for run in runs or []:
        engine = run.get("engine")
        if not engine or is_experiment_version(run.get("engine_version")):
            continue
        key = (str(engine), str(run.get("mode") or ""))
        seen = best.get(key)
        if seen is None or str(run.get("created_at") or "") > str(seen.get("created_at") or ""):
            best[key] = run

    out: list[dict[str, Any]] = []
    for (engine, mode), run in sorted(best.items()):
        reasons = run.get("gate_reasons") or []
        out.append({
            "engine": engine,
            "engine_version": run.get("engine_version"),
            "mode": mode,
            "date_from": run.get("date_from"),
            "date_to": run.get("date_to"),
            "n_decisions": run.get("n_decisions"),
            "n_fills": run.get("n_fills"),
            "n_settled": run.get("n_settled"),
            "brier_ours": run.get("brier_ours"),
            "brier_market": run.get("brier_market"),
            "brier_ratio": brier_ratio(run.get("brier_ours"), run.get("brier_market")),
            "pnl_after_fees": run.get("pnl_after_fees"),
            "max_drawdown": run.get("max_drawdown"),
            "gate_status": run.get("gate_status") or "SHADOW",
            "gate_reasons": reasons,
            "settled_distance": settled_distance(
                run.get("n_settled"), required_settled(reasons, None)
            ),
        })
    return out
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_scoreboard_reduction.py -v`

Expected: `15 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scoreboard.py tests/test_scoreboard_reduction.py
git commit -m "feat(scoreboard): reduce backtest_runs to one honest row per engine

Pure, so every rule is testable without a database and a reviewer can check the
arithmetic rather than the plumbing.

The rule that matters: a run whose engine_version carries a decision lead
(gas-v1-lead12h, from PR #25) is an EXPERIMENT, not the engine's record. Gas is
4.29x behind the market at the production 2h and 2.16x behind at 12h, so the
two disagree about the engine, and this page exists to answer whether to trust
one. Presenting the 12h run would make the page wrong in the direction that
flatters the engine.

Experiments are excluded rather than footnoted: a footnote is something a reader
skips, an absent row is something they cannot misread. The runs stay in
backtest_runs and stay reproducible from the CLI.

mode is part of the key, because taker and maker are different fills and
collapsing them would blend two experiments into a number meaning neither. And
the settled requirement is read out of the gate's own gate_reasons rather than
hardcoded per engine, so there is no second place for the bars to be wrong.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: `GET /api/scoreboard`

**Files:**
- Modify: `tradehub/api/main.py` (new endpoint)
- Test: `tests/test_scoreboard_api.py` (new)

**Interfaces:**
- Consumes: `current_runs(runs)` from Task 1; `backtest_runs` columns `engine`, `engine_version`, `mode`, `date_from`, `date_to`, `n_decisions`, `n_fills`, `n_settled`, `pnl_after_fees`, `max_drawdown`, `brier_ours`, `brier_market`, `gate_status`, `gate_reasons`, `created_at`.
- Produces: `GET /api/scoreboard` → `ScoreboardResponse`. Task 3 consumes it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scoreboard_api.py`:

```python
"""The scoreboard endpoint: one row per engine, with the comparison and the distance.

Override the dependency on the module-level `app`, the way the existing sports tests do. A
hand-built app with copied route objects does NOT work -- the copied APIRoute keeps resolving
Depends() against its original app, so the override never applies and the real client is built.
"""
from fastapi.testclient import TestClient

from tradehub.api import main as api_main
from tradehub.api.dependencies import get_supabase


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *a):
        return self

    def eq(self, *a):
        return self

    def order(self, *a):
        return self

    def limit(self, *a):
        return self

    def range(self, lo, hi):
        self.rows = self.rows[lo:hi + 1]
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, rows):
        self.rows = rows
        self.queried = []

    def table(self, name):
        self.queried.append(name)
        if name != "backtest_runs":
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")
        return _Q(self.rows)


def _run(engine, version, **over):
    row = {
        "engine": engine, "engine_version": version, "mode": "taker",
        "date_from": "2026-06-01T00:00:00+00:00", "date_to": "2026-09-20T00:00:00+00:00",
        "n_decisions": 672, "n_fills": 232, "n_settled": 42,
        "pnl_after_fees": -7.62, "max_drawdown": 8.87,
        "brier_ours": 0.1148, "brier_market": 0.02676,
        "gate_status": "SHADOW",
        "gate_reasons": ["only 42 settled contracts, need 200 (daily)"],
        "created_at": "2026-09-20T00:00:00+00:00",
    }
    row.update(over)
    return row


def _get(rows):
    supa = _Supa(rows)
    app = api_main.app
    app.dependency_overrides[get_supabase] = lambda: supa
    try:
        return TestClient(app).get("/api/scoreboard"), supa
    finally:
        app.dependency_overrides.clear()


def test_it_reads_backtest_runs_and_nothing_else():
    response, supa = _get([_run("gas", "gas-v1")])

    assert response.status_code == 200
    assert supa.queried == ["backtest_runs"]


def test_each_engine_carries_its_brier_beside_the_market_and_the_distance():
    body, _ = _get([_run("gas", "gas-v1")]).json() if False else _get([_run("gas", "gas-v1")])[0].json()

    row = body["rows"][0]
    assert row["brier_ours"] == 0.1148
    assert row["brier_market"] == 0.02676
    assert row["brier_ratio"] == pytest.approx(4.29, abs=0.01)
    assert row["settled_distance"] == {"n_settled": 42, "required": 200, "remaining": 158,
                                       "met": False, "pct": 21.0}


def test_an_experiment_never_reaches_the_client():
    body = _get([
        _run("gas", "gas-v1", created_at="2026-09-20T00:00:00+00:00"),
        _run("gas", "gas-v1-lead12h", brier_ours=0.11216, brier_market=0.0519,
             created_at="2026-09-27T00:00:00+00:00"),
    ])[0].json()

    assert len(body["rows"]) == 1
    assert body["rows"][0]["engine_version"] == "gas-v1"


def test_the_response_states_that_every_engine_is_behind():
    """The page's headline. Derived, not asserted, so it cannot go stale against the data."""
    body = _get([_run("gas", "gas-v1")])[0].json()

    assert body["any_beats_market"] is False
    assert body["engines_behind_market"] == 1


def test_it_says_so_when_one_engine_does_beat_the_market():
    body = _get([_run("weather", "weather-v1", brier_ours=0.05, brier_market=0.10)])[0].json()

    assert body["any_beats_market"] is True
    assert body["engines_behind_market"] == 0


def test_an_empty_table_is_a_valid_empty_scoreboard_not_an_error():
    body = _get([])[0].json()

    assert body["rows"] == []
    assert body["any_beats_market"] is False
    assert body["engines_behind_market"] == 0
```

Add `import pytest` at the top of the file — it is used by the ratio assertion.

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_scoreboard_api.py -v`

Expected: FAIL — `/api/scoreboard` 404s, so `.json()` is `{"detail": "Not Found"}`.

- [ ] **Step 3: Add the endpoint**

In `tradehub/api/main.py`, add the import:

```python
from tradehub.scoreboard import current_runs
```

Then add the endpoint after `/api/sports-edges`:

```python
@app.get("/api/scoreboard", tags=["Scoreboard"])
def get_scoreboard(supabase=Depends(get_supabase), cap: int = 200):
    """Every engine's Brier next to the market's, and how far each is from its own gate.

    Approved 2026-09-27 as a first-class page (spec section 9, approval 4). It exists because this is
    the question the whole product turns on -- should I trust this engine -- and it was the one page
    answering it that returned a 500.

    The reduction is pure and lives in `tradehub/scoreboard.py`. The rule that matters there: a run
    whose `engine_version` carries a decision lead is an experiment, not the engine's record, and is
    excluded rather than footnoted.

    `any_beats_market` and `engines_behind_market` are computed here from the rows rather than left to
    the page, so the headline cannot go stale against the data underneath it.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    runs = _fetch_all(
        supabase, "backtest_runs",
        lambda q: q.select("*").order("created_at", desc=True),
        cap=cap,
    )
    rows = current_runs(runs)
    behind = sum(1 for r in rows if r["brier_ratio"] is not None and r["brier_ratio"] > 1.0)
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
        "engines": len(rows),
        "engines_behind_market": behind,
        "any_beats_market": any(r["brier_ratio"] is not None and r["brier_ratio"] < 1.0 for r in rows),
        # Stated in words as well as flags, because this is the sentence a reader takes away.
        "headline": (
            "No engine beats the market after fees." if not any(
                r["brier_ratio"] is not None and r["brier_ratio"] < 1.0 for r in rows
            ) else "At least one engine beats the market on Brier. Check the settled count before "
                   "reading that as an edge."
        ),
    }
```

`_fetch_all` already exists at `tradehub/api/main.py:232` — use it, do not add a second copy.

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_scoreboard_api.py -v`

Expected: `6 passed`. If `test_each_engine_carries_its_brier_beside_the_market_and_the_distance` errors on
the odd `if False else` expression, replace that line with:

```python
    body = _get([_run("gas", "gas-v1")])[0].json()
```

- [ ] **Step 5: Run the full suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tradehub/api/main.py tests/test_scoreboard_api.py
git commit -m "feat(api): GET /api/scoreboard -- each engine's Brier beside the market's

Answers the question the product turns on, which is the one page that used to
return a 500. One row per engine and mode, reduced by the pure helper from the
previous commit.

any_beats_market and engines_behind_market are computed server-side from the
rows rather than left to the page, so the headline cannot go stale against the
data underneath it. The headline sentence travels with it, because that is what
a reader actually takes away -- and the qualified version is the honest one when
an engine does lead, since a Brier win on a small settled count is not an edge.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The page

**Files:**
- Create: `market_sentiment_tool/src/lib/scoreboard.ts`
- Create: `market_sentiment_tool/src/lib/scoreboard.test.ts`
- Create: `market_sentiment_tool/src/pages/Scoreboard.tsx`
- Modify: `market_sentiment_tool/src/App.tsx` (route + nav)
- Test: `market_sentiment_tool/src/lib/scoreboard.test.ts`

**Interfaces:**
- Consumes: `GET /api/scoreboard` from Task 2 — `{ as_of, rows, engines, engines_behind_market, any_beats_market, headline }`, each row `{ engine, engine_version, mode, date_from, date_to, n_decisions, n_fills, n_settled, brier_ours, brier_market, brier_ratio, pnl_after_fees, max_drawdown, gate_status, gate_reasons, settled_distance }`.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Create `market_sentiment_tool/src/lib/scoreboard.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { brierVerdict, formatBrier, gateDistanceNote, summarise } from "./scoreboard";

/**
 * How a losing comparison is worded.
 *
 * Every engine currently loses (spec §1). The temptation on a page like this is to soften it —
 * "close", "competitive", a coloured delta that reads as near-parity. Gas at 4.29x the market's Brier
 * is not close, and a reader who is told otherwise cannot judge the engine. So the wording is pinned
 * by test: a ratio states the multiple, and nothing is called competitive unless it is.
 */
const behind = {
  engine: "gas",
  engine_version: "gas-v1",
  mode: "taker",
  date_from: "2026-06-01T00:00:00+00:00",
  date_to: "2026-09-20T00:00:00+00:00",
  n_decisions: 1982,
  n_fills: 274,
  n_settled: 42,
  brier_ours: 0.1148,
  brier_market: 0.02676,
  brier_ratio: 4.29,
  pnl_after_fees: -3.84,
  max_drawdown: 7.06,
  gate_status: "SHADOW",
  gate_reasons: ["only 42 settled contracts, need 200 (daily)"],
  settled_distance: { n_settled: 42, required: 200, remaining: 158, met: false, pct: 21.0 },
};

describe("formatBrier", () => {
  it("renders a Brier to five decimals, the precision it is compared at", () => {
    expect(formatBrier(0.1148)).toBe("0.11480");
  });

  it("renders an absent Brier as unknown, not as zero", () => {
    expect(formatBrier(null)).toBe("—");
    expect(formatBrier(undefined)).not.toBe("0.00000");
  });
});

describe("brierVerdict", () => {
  it("states the multiple when the model is behind", () => {
    expect(brierVerdict(behind)).toMatch(/4\.3/);
  });

  it("never calls a large deficit competitive", () => {
    for (const ratio of [1.1, 2, 4.29, 9]) {
      expect(brierVerdict({ ...behind, brier_ratio: ratio })).not.toMatch(/close|competitive|nearly/i);
    }
  });

  it("says so when the model is ahead", () => {
    expect(brierVerdict({ ...behind, brier_ratio: 0.5 })).toMatch(/ahead/i);
  });

  it("says unknown rather than guessing when there is no ratio", () => {
    expect(brierVerdict({ ...behind, brier_ratio: null, brier_ours: null })).toMatch(/unknown|cannot/i);
  });
});

describe("gateDistanceNote", () => {
  it("says what is still needed, not just what is there", () => {
    expect(gateDistanceNote(behind)).toMatch(/158/);
    expect(gateDistanceNote(behind)).toMatch(/200/);
  });

  it("says unknown when the bar is unknown, rather than implying zero remaining", () => {
    expect(gateDistanceNote({ ...behind, settled_distance: null })).toMatch(/unknown|not stated/i);
  });

  it("reports a met gate plainly", () => {
    const met = { ...behind, settled_distance: { n_settled: 200, required: 200, remaining: 0, met: true, pct: 100 } };
    expect(gateDistanceNote(met)).toMatch(/met|200 of 200/i);
  });
});

describe("summarise", () => {
  it("repeats the server's own headline rather than inventing one", () => {
    // The server computes it from the rows; the page restating its own logic is how the two drift.
    const summary = summarise({ any_beats_market: false, engines_behind_market: 3, engines: 3, headline: "No engine beats the market after fees." });
    expect(summary.value).toBe("No engine beats the market after fees.");
    expect(summary.tone).toBe("behind");
  });

  it("does not claim a win when the sample is too small to mean one", () => {
    const summary = summarise({ any_beats_market: true, engines_behind_market: 0, engines: 1, headline: "At least one engine beats the market on Brier. Check the settled count before reading that as an edge." });
    expect(summary.value).toMatch(/Check the settled count/i);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/lib/scoreboard.test.ts`

Expected: FAIL — `Cannot find module './scoreboard'`.

- [ ] **Step 3: Write the module**

Create `market_sentiment_tool/src/lib/scoreboard.ts`:

```typescript
/**
 * Wording for the engine scoreboard.
 *
 * Every engine currently loses (spec §1). The temptation on a page like this is to soften that —
 * "close", "competitive", a coloured delta that reads as near-parity. Gas sits at 4.29x the market's
 * Brier, which is not close, and a reader who is told otherwise cannot judge the engine. So the
 * wording is pinned by test rather than left to taste.
 */

export interface SettledDistance {
  n_settled: number;
  required: number;
  remaining: number;
  met: boolean;
  pct: number;
}

export interface ScoreboardRow {
  engine: string;
  engine_version: string | null;
  mode: string;
  date_from: string | null;
  date_to: string | null;
  n_decisions: number | null;
  n_fills: number | null;
  n_settled: number | null;
  brier_ours: number | null;
  brier_market: number | null;
  brier_ratio: number | null;
  pnl_after_fees: number | null;
  max_drawdown: number | null;
  gate_status: string | null;
  gate_reasons: string[];
  settled_distance: SettledDistance | null;
}

export interface ScoreboardResponse {
  as_of: string;
  rows: ScoreboardRow[];
  engines: number;
  engines_behind_market: number;
  any_beats_market: boolean;
  headline: string;
}

/** Brier is compared at the fifth decimal, so that is how it is shown. */
export function formatBrier(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return value.toFixed(5);
}

export function brierVerdict(row: ScoreboardRow): string {
  if (typeof row.brier_ratio !== "number" || !Number.isFinite(row.brier_ratio)) {
    return "Cannot compare — no market Brier was recorded at decision time.";
  }
  if (row.brier_ratio < 1) {
    return `Ahead of the market (${row.brier_ratio.toFixed(2)}x its Brier).`;
  }
  // The multiple, stated. No softening, and no colour that implies parity.
  return `${row.brier_ratio.toFixed(1)}x the market's Brier — behind.`;
}

export function gateDistanceNote(row: ScoreboardRow): string {
  const distance = row.settled_distance;
  if (!distance) return "Gate distance unknown: this run's gate did not state a requirement.";
  if (distance.met) return `Gate met on count: ${distance.n_settled} of ${distance.required}.`;
  return `${distance.n_settled} of ${distance.required} settled — ${distance.remaining} more needed.`;
}

export interface ScoreboardSummary {
  value: string;
  tone: "behind" | "mixed";
}

/** Restates the server's own headline. Recomputing it here is how the two drift apart. */
export function summarise(body: {
  any_beats_market: boolean;
  engines_behind_market: number;
  engines: number;
  headline: string;
}): ScoreboardSummary {
  return { value: body.headline, tone: body.any_beats_market ? "mixed" : "behind" };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run src/lib/scoreboard.test.ts`

Expected: `13 passed`. If the count differs, check no assertion was dropped.

- [ ] **Step 5: Write the page**

Create `market_sentiment_tool/src/pages/Scoreboard.tsx`:

```tsx
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import {
  brierVerdict,
  formatBrier,
  gateDistanceNote,
  summarise,
  type ScoreboardResponse,
} from "@/lib/scoreboard";

/**
 * Should I trust this engine?
 *
 * This is the question the product turns on, and it is the question every other page is downstream
 * of. So the numbers are shown without softening: the Brier beside the market's, the multiple, and
 * the gate distance. An engine that is behind reads as behind.
 *
 * A separate page rather than a change to `/shadow`: that route is the crypto shadow-timeline
 * backtester, a different thing that happens to share a name.
 */
export default function Scoreboard() {
  const [data, setData] = useState<ScoreboardResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/scoreboard"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        }
        setData(payload as ScoreboardResponse);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">Scoreboard unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
          <p className="mt-2 text-rose-300/60">
            The scoreboard reads <code>backtest_runs</code>. If it is missing, migration
            20260416000004 has not been applied.
          </p>
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-slate-400">Loading engine scoreboard…</div>;

  const summary = summarise(data);

  return (
    <div className="p-8 space-y-6">
      <header className="border-b border-slate-900 pb-4">
        <h1 className="text-2xl font-bold text-white">Engine scoreboard</h1>
        <p className="text-sm text-slate-400">
          Each engine&apos;s Brier score against the market&apos;s, on the same decisions. A lower
          Brier is better. This is the record the promotion gate reads.
        </p>
      </header>

      <div
        className={`rounded-lg border p-4 text-sm ${
          summary.tone === "behind"
            ? "border-amber-900/60 bg-amber-950/20 text-amber-100"
            : "border-sky-900/60 bg-sky-950/20 text-sky-100"
        }`}
      >
        <p className="font-semibold">{summary.value}</p>
        <p className="mt-1 opacity-90">
          {data.engines_behind_market} of {data.engines} engine
          {data.engines === 1 ? " is" : "s are"} behind the market on this measure.
        </p>
      </div>

      {data.rows.length === 0 ? (
        <p className="text-slate-400">
          No recorded backtest runs yet. Run{" "}
          <code>python -m tradehub.scripts.backtest_engines --engine &lt;engine&gt; --record</code> to
          produce one.
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            Per-engine Brier against the market, and distance to the promotion gate.
          </caption>
          <thead>
            <tr className="border-b border-slate-800">
              {[
                "Engine",
                "Brier (ours)",
                "Brier (market)",
                "Verdict",
                "Decisions",
                "Gate distance",
                "Gate",
              ].map((label) => (
                <th
                  key={label}
                  scope="col"
                  className="py-2 pr-3 text-left text-xs font-semibold uppercase tracking-wide text-slate-500"
                >
                  {label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.rows.map((row) => (
              <tr key={`${row.engine}-${row.mode}`} className="border-t border-slate-800 align-top">
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <div className="font-medium text-slate-100">{row.engine}</div>
                  <div className="text-xs text-slate-500">
                    {row.mode}
                    {row.engine_version ? ` · ${row.engine_version}` : ""}
                  </div>
                  {row.date_from && row.date_to && (
                    <div className="text-xs text-slate-600">
                      {row.date_from.slice(0, 10)} → {row.date_to.slice(0, 10)}
                    </div>
                  )}
                </th>
                <td className="py-2 pr-3 font-mono text-slate-200">{formatBrier(row.brier_ours)}</td>
                <td className="py-2 pr-3 font-mono text-slate-400">{formatBrier(row.brier_market)}</td>
                <td className="py-2 pr-3 text-slate-300">{brierVerdict(row)}</td>
                <td className="py-2 pr-3 text-slate-400">
                  {row.n_decisions ?? "—"}
                  <span className="block text-xs text-slate-600">{row.n_fills ?? "—"} filled</span>
                </td>
                <td className="py-2 pr-3 text-xs text-slate-300">
                  {gateDistanceNote(row)}
                  {row.gate_reasons.length > 0 && (
                    <ul className="mt-1 list-disc pl-4 text-slate-500">
                      {row.gate_reasons.map((reason) => (
                        <li key={reason}>{reason}</li>
                      ))}
                    </ul>
                  )}
                </td>
                <td className="py-2 pr-3">
                  <span
                    className={`rounded-full border px-2 py-0.5 text-[10px] font-bold uppercase ${
                      row.gate_status === "PROMOTED"
                        ? "border-emerald-500/40 bg-emerald-500/10 text-emerald-300"
                        : "border-slate-700 bg-slate-800 text-slate-400"
                    }`}
                  >
                    {row.gate_status ?? "SHADOW"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Wire the route and the nav**

In `market_sentiment_tool/src/App.tsx`, add the import beside the other page imports:

```typescript
import Scoreboard from "@/pages/Scoreboard";
```

Add the route inside `<Routes>`, after `/shadow`:

```typescript
        <Route path="/scoreboard" element={<Scoreboard />} />
```

Add a nav entry after the Shadow one. Copy the existing `NavLink` className expression exactly and
swap the label and icon:

```typescript
        <NavLink
          to="/scoreboard"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Scale className="w-5 h-5 text-rose-400" /> Scoreboard
        </NavLink>
```

Add `Scale` to the existing `lucide-react` import. If `Scale` is not exported by the installed
version, use `Trophy`, which is already imported.

- [ ] **Step 7: Verify the frontend**

```bash
cd market_sentiment_tool
npx tsc --noEmit -p tsconfig.app.json
npx vitest run
npm run build
```

Expected: typecheck clean, all vitest pass, build succeeds.

- [ ] **Step 8: Full verification before pushing**

```bash
cd /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -c "
import time, sys
time.monotonic = lambda: 5.0
import pytest; sys.exit(pytest.main(['-q']))
"
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -c "
import time, sys
time.monotonic = lambda: 1e7
import pytest; sys.exit(pytest.main(['-q']))
"
.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
```

Expected: both pytest runs pass, ruff clean. Paste all three in the PR comment.

- [ ] **Step 9: Commit**

```bash
git add market_sentiment_tool/src/lib/scoreboard.ts \
        market_sentiment_tool/src/lib/scoreboard.test.ts \
        market_sentiment_tool/src/pages/Scoreboard.tsx \
        market_sentiment_tool/src/App.tsx
git commit -m "feat(web): the engine scoreboard, without softening the losses

Each engine's Brier beside the market's, the multiple between them, and the
distance to the gate -- the question the product turns on, and the one page
that used to return a 500.

The wording is pinned by test rather than left to taste. Every engine currently
loses, and the temptation on a page like this is to soften that: 'close',
'competitive', a coloured delta that reads as near-parity. Gas is 4.29x the
market's Brier, which is not close, and a reader told otherwise cannot judge the
engine. So no ratio above 1 is ever described as close, and the headline is
restated from the server rather than recomputed here, because two implementations
of the same summary is how they drift.

Error state names the table and the migration that creates it.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage.** §6 ("/shadow is the most important page and is currently a 500") → Tasks 2–3.
§9 approval 4 ("each engine's Brier vs the market, and its distance to the gate") → the two columns,
with `gateDistanceNote` asserting the *remaining* count rather than only the achieved one. §1 (every
engine loses) → `any_beats_market` / `engines_behind_market` computed server-side, and the wording
tests that pin "behind" as behind. Global Constraints: suggest-only is why no balance appears; losing
engines stay visible is `test_a_losing_engine_is_never_dropped`; the gate fails closed is the
`PROMOTED`-only render; the verification contract is Global Constraints plus Task 3 Step 8.

**Deliberately out of scope:** the §5b `calibration_off` change (an unapproved gate decision — putting
it here would smuggle it in); making `/shadow` work (that is Alpaca credentials and a migration, both
the operator's); the per-engine model work (blocked or refuted — see §9 of the spec).

**2. Placeholder scan.** No TBD, TODO, "handle edge cases", or "similar to Task N". Every code block is
complete. Two places name a concrete fallback (`Scale` → `Trophy`, `BarChart3` → `LineChart` in the CPI
plan) because the installed icon set is not knowable from here; both name an icon already imported by
`App.tsx`, so neither can fail.

**3. Type consistency.** `ScoreboardRow` is defined once in Task 3 Step 3 and used by the lib test, the
page, and the fixtures — all three construct it with the same keys. `settled_distance` is
`SettledDistance | null` in the type, matching the reducer's `settled_distance(...)` which returns
`None`. `brier_ratio` is `number | null`, and `brierVerdict` handles `null` explicitly rather than
formatting it. `current_runs` is imported by name from `tradehub.scoreboard` in Task 2 and the import
line is given in Step 3.
