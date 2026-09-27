# CPI Display Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop CPI presenting itself as an edge, and present it as what the evidence supports — a nowcast-versus-market display, labelled as not an edge engine.

**Architecture:** `scan_cpi` already writes two things: a `predictions` row carrying the nowcast, our probability and the market mid, and an `edges` row presenting it as an opportunity. Only the second is the problem. Keep the predictions, stop writing edges, and add a read endpoint plus a page that show the same numbers as context with an explicit `mode: "display"` label. The gate badge keeps failing closed, so nothing is hidden and nothing is promoted.

**Tech Stack:** Python 3.12, FastAPI, supabase-py, pytest, React 18 + TypeScript + Vite, vitest.

**Spec:** `docs/superpowers/specs/2026-09-27-hub-redesign.md` — §5 (CPI: **OUTCOME: REFUTED**), §5a (why), §6 (page purposes), §9 (approval 3: "DISPLAY ONLY. Show the nowcast vs the market for context; it's not an edge engine").

## Global Constraints

- **Suggest-only. This product never places an order** (spec §6). No code path may imply a balance, a position, or an order.
- **An engine that loses stays visible.** Never delete a losing engine's rows to make a page look better. CPI's existing `predictions` rows stay; the page shows them with the `display` label.
- **The gate fails closed.** Only an explicit `PROMOTED` is promoted; missing or unknown gate status renders as not-promoted (`market_sentiment_tool/src/lib/edgeGate.ts`).
- **`--record`ed backtests and live predictions are separate.** This plan changes what the scan *presents*, never what it *measures*. `predictions` still record `our_prob`, `market_prob` and the nowcast, so the oracle-bound analysis in §5a stays reproducible.
- **Verification before every push:** full `pytest` twice with `time.monotonic` forced to `5.0` **and** `1e7`, then `ruff check --select F401,F811,F821 tradehub tests`, then `npm run typecheck`, `npx vitest run`, `npm run build`. CI runners have a low clock; this has broken CI three times.
- **New migrations are numbered after the highest on `main`.** This plan adds **no migration** — if a task seems to need one, that is a signal the task is wrong.
- **Every commit ends with** `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `tradehub/scripts/scan.py` | `scan_cpi` stops returning edges. Predictions unchanged. |
| `tradehub/api/main.py` | `GET /api/cpi-display` — serves the nowcast-versus-market view from `predictions`. |
| `market_sentiment_tool/src/lib/cpiDisplay.ts` | **New.** Pure: the display row type, formatting, and the "not an edge engine" copy. All of it unit-testable with no network. |
| `market_sentiment_tool/src/lib/cpiDisplay.test.ts` | **New.** Unit tests for the above. |
| `market_sentiment_tool/src/pages/CpiDisplay.tsx` | **New.** The page. Fetches the endpoint, renders the table. |
| `market_sentiment_tool/src/App.tsx` | Route `/cpi` and a nav entry. |
| `tests/test_cpi_display.py` | **New.** Endpoint contract. |
| `tests/test_cpi_no_edges.py` | **New.** The regression: CPI writes predictions, never edges. |

Nothing else changes. In particular `edgeGate.ts`, `GateBadge.tsx` and the sports path are untouched — CPI is a separate engine on a separate page.

---

## Task 1: `scan_cpi` stops presenting CPI as an edge

The defect is one `edges.append(...)` call. The measurements beside it are correct and must stay.

**Files:**
- Modify: `tradehub/scripts/scan.py:323-360` (`scan_cpi`)
- Test: `tests/test_cpi_no_edges.py` (new)

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces: `scan_cpi(live, now, cfg, *, nowcast_fn, targets) -> tuple[list[dict], list[dict]]` — **signature unchanged**, second element now always `[]`. Task 3 reads `predictions`, which keeps its shape.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cpi_no_edges.py`:

```python
"""CPI must stop presenting itself as an edge.

Approved 2026-09-27 as DISPLAY ONLY, on the evidence in spec section 5a: the market's Brier at 5 days
out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices CPI about as accurately a
week ahead as it does in the last half hour. The market is not pricing off the Cleveland Fed nowcast
at all, so a nowcast-based model has nothing to exploit by being early. At every lead we are
1.33-1.43x behind, and P&L is negative at every lead.

So the fix is presentational, not analytical. The `predictions` row is correct and stays -- it is what
carries the nowcast, our probability and the market mid, i.e. exactly the context the display needs.
The `edges` row is what tells a reader "here is an opportunity", and that claim is not supported.
"""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from tradehub.backtest.pit import Observation
from tradehub.engine_config import EngineConfig
from tradehub.scripts import scan as scan_mod
from tradehub.scripts.scan import scan_cpi


class _Quote:
    def __init__(self, yes_bid=0.40, yes_ask=0.44):
        self.yes_bid = yes_bid
        self.yes_ask = yes_ask
        self.no_bid = 1 - yes_ask
        self.no_ask = 1 - yes_bid
        self.yes_bid_size = 500
        self.yes_ask_size = 500
        self.no_bid_size = 500
        self.no_ask_size = 500


class _Market:
    def __init__(self, ticker):
        self.ticker = ticker
        self.title = f"Will CPI be above {ticker[-5:]}?"
        self.event_ticker = "KXCPIDEC-26SEP"
        self.close_time = datetime(2026, 9, 10, 12, 25, tzinfo=timezone.utc)
        self.quote = _Quote()


def _live(markets):
    def open_markets(series):
        return markets if series == "KXCPI" else []
    return SimpleNamespace(open_markets=open_markets)


def _nowcast_history(kind):
    return {"2026-09": [Observation("CLEVELAND-2026-09", 0.3, datetime(2026, 8, 20, tzinfo=timezone.utc))]}


def _cfg():
    return EngineConfig(min_edge_pct=2.0, prefer_maker=True, params={"train_months": 24, "use_bias": 0.0})


def _scan():
    now = datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc)
    return scan_cpi(
        _live([SimpleNamespace(market=_Market("KXCPI-26SEP09-3.0"), quote=_Quote())]),
        now, _cfg(), nowcast_fn=_nowcast_history,
    )


def test_cpi_writes_no_edges():
    """The whole point. `edges` is what presents CPI as an opportunity, and the evidence does not
    support that claim."""
    predictions, edges = _scan()

    assert edges == [], f"CPI must not write edges; it is display-only, got {len(edges)}"


def test_cpi_still_writes_its_prediction_with_the_nowcast_and_the_market_mid():
    """Deleting the edge must not delete the measurement. The display page reads this row, and the
    oracle-bound analysis in spec 5a has to stay reproducible from it."""
    predictions, _ = _scan()

    assert predictions, "the nowcast context is the product; it must survive"
    row = predictions[0]
    assert row["engine"] == "cpi_nowcast"
    assert 0.0 <= row["our_prob"] <= 1.0
    assert 0.0 <= row["market_prob"] <= 1.0
    assert row["raw_payload"]["nowcast"] == 0.3
    assert row["raw_payload"]["sigma"] > 0


def test_the_prediction_is_still_marked_shadow_and_never_promoted():
    predictions, _ = _scan()

    assert predictions[0]["gate_status"] == "SHADOW", (
        "display-only is not promoted; the gate fails closed and must keep saying so"
    )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_cpi_no_edges.py -v`

Expected: `test_cpi_writes_no_edges` FAILS with a non-empty `edges` list. The other two PASS.

- [ ] **Step 3: Remove the edge write**

In `tradehub/scripts/scan.py`, inside `scan_cpi`, delete this block (currently around line 355):

```python
                suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
                                           prefer_maker=cfg.prefer_maker)
                if suggestion:
                    edges.append(edge_row(lm.market, suggestion, "MACRO", engine="cpi_nowcast",
                                          engine_version=version, updated_at=now))
```

and replace it with:

```python
                # No edge row, deliberately (approved 2026-09-27, spec 5a): CPI is a display engine.
                # The prediction above is the product -- it carries the nowcast, our probability and
                # the market mid. An `edges` row would tell a reader "here is an opportunity", and at
                # 1.33-1.43x behind the market at every lead that claim is not supported. The
                # prediction is retained so the display page has something to show and so the
                # oracle-bound analysis stays reproducible.
                del lm
```

Then change the function's return type comment and the `edges` initialisation to make the contract explicit. Replace:

```python
    predictions: list[dict] = []
    edges: list[dict] = []
```

with:

```python
    predictions: list[dict] = []
    # Always empty: CPI is a display engine (spec 5a). The return shape is unchanged so the caller
    # at scan.py:490 needs no edit and the signature stays honest about what it produces.
    edges: list[dict] = []
```

Also delete the now-unused `evaluate_edge` import **only if** `ruff --select F401` reports it unused. Check with:

```bash
cd /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod && .venv/bin/python -m ruff check --select F401 tradehub/scripts/scan.py
```

If it reports `evaluate_edge` imported and unused, remove it from the `from tradehub.edges import ...` line. If it is still used elsewhere in the file, leave the import.

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_cpi_no_edges.py -v`

Expected: `3 passed`.

- [ ] **Step 5: Run the full suite to catch anything that depended on CPI edges**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q`

Expected: all pass. If a test asserted CPI produced an edge, **update that test to assert the display contract instead** — do not re-add the edge. Note which test you changed and why in the commit body.

- [ ] **Step 6: Commit**

```bash
git add tradehub/scripts/scan.py tests/test_cpi_no_edges.py
git commit -m "feat(cpi): stop writing edges; CPI is a display engine

Approved DISPLAY ONLY on the evidence in spec 5a: the market's Brier at 5 days
out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi prices CPI
about as accurately a week ahead as in the last half hour. The market is not
pricing off the nowcast, so a nowcast-based model has nothing to exploit by
being early, and at every lead we are 1.33-1.43x behind with negative P&L.

The fix is presentational, not analytical. predictions are unchanged -- they
carry the nowcast, our probability and the market mid, which is exactly the
context the display needs and what keeps the oracle-bound analysis reproducible.
Only the edges row is removed, because that is what claims an opportunity.

Return shape unchanged, so the caller at scan.py:490 needs no edit.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Purge the `cpi_nowcast` edges already on the board

Task 1 stops *writing* CPI edges. It does not remove the ones already written, and they would keep
posing as opportunities — which is the thing the approval forbids.

This is easy to miss because the cleanup that looks like it should handle it does not.
`remove_closed_cpi_edges` (`tradehub/scripts/scan.py:115`) deletes only rows whose market has **closed**
(`expires_at <= now`). With no new rows being written, every *open* CPI edge in the database stays
there indefinitely, still rendered as an opportunity, until its own market closes. CPI markets are open
right now, so this is live, not theoretical.

**Files:**
- Create: `market_sentiment_tool/supabase/migrations/<N>_cpi_display_only.sql`

**Interfaces:**
- Consumes: nothing.
- Produces: an empty `kalshi_edges` set for `engine = 'cpi_nowcast'`, which is what makes Task 1
  visually complete rather than merely eventually true.

- [ ] **Step 1: Find the next migration number**

```bash
ls /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/market_sentiment_tool/supabase/migrations/ | sort | tail -3
```

Use the next number after the highest present. **Do not hardcode it in the plan** — #20 carries
`20260416000011_war_room_tables.sql` and is unmerged, so the answer changes with merge order and a
collision is worse than an odd-looking filename. State the number you chose in the PR comment.

- [ ] **Step 2: Write the migration**

Create `market_sentiment_tool/supabase/migrations/<N>_cpi_display_only.sql`:

```sql
-- CPI is a display engine as of 2026-09-27 (spec 2026-09-27-hub-redesign.md, sections 5a and 9).
--
-- WHAT THIS DOES: deletes every existing kalshi_edges row with engine = 'cpi_nowcast'. One statement.
--
-- The scan no longer writes them, but the ones already written would otherwise stay on the board
-- posing as opportunities: remove_closed_cpi_edges only deletes rows whose market has CLOSED, so an
-- open CPI edge would sit there indefinitely still claiming to be a trade.
--
-- The measurements are NOT deleted. `predictions` rows for engine = 'cpi_nowcast' carry the
-- nowcast, our probability and the market mid -- that is what the display page reads, and it is
-- also what keeps the oracle-bound analysis in spec 5a reproducible. This is the difference between
-- hiding a losing engine and misrepresenting one.
--
-- No other engine's rows are touched, and no other table is touched.

DELETE FROM kalshi_edges WHERE engine = 'cpi_nowcast';
```

- [ ] **Step 3: Verify the migration is scoped to CPI only**

Re-read the file. There must be exactly one statement, and its `WHERE` must name only
`engine = 'cpi_nowcast'`. A migration that touches another engine's rows is wrong whatever the comment
says.

- [ ] **Step 4: Commit**

```bash
git add market_sentiment_tool/supabase/migrations/<N>_cpi_display_only.sql
git commit -m "chore(db): remove the cpi_nowcast edges already on the board

The scan no longer writes them, but the existing rows would otherwise stay
visible as opportunities: remove_closed_cpi_edges only deletes rows whose
market has closed, so an open CPI edge would linger indefinitely still claiming
to be a trade.

predictions are NOT touched. Those carry the nowcast, our probability and the
market mid -- the display page reads them, and they keep the oracle-bound
analysis in spec 5a reproducible. Nothing is hidden: the edge claim is removed
and the measurement stays.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: `GET /api/cpi-display` — the context, explicitly labelled

**Files:**
- Modify: `tradehub/api/main.py` (new endpoint, after `/api/sports-edges`)
- Test: `tests/test_cpi_display.py` (new)

**Interfaces:**
- Consumes: the `predictions` rows written by Task 1 — `engine == "cpi_nowcast"`, columns `market_ticker`, `our_prob`, `market_prob`, `raw_payload` (with `nowcast`, `nowcast_obs`, `sigma`, `n_train`, `hours_to_close`), `updated_at`.
- Produces: `GET /api/cpi-display?limit=50&offset=0` → `CpiDisplayResponse` (shape below). Task 3 consumes this.

- [ ] **Step 1: Write the failing test**

Create `tests/test_cpi_display.py`:

```python
"""The CPI display endpoint: context, with the "not an edge engine" claim carried in the payload.

The label is the point. A reader who sees a probability and a market price will assume an
opportunity unless something says otherwise, and this engine is 1.33-1.43x behind the market at every
lead (spec 5a). So `mode` and `edge_pct` travel with every row rather than being left to the page.
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

    def table(self, name):
        if name != "predictions":
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")
        return _Q(self.rows)


def _row(ticker, *, our, market, nowcast):
    return {
        "market_ticker": ticker,
        "our_prob": our,
        "market_prob": market,
        "engine": "cpi_nowcast",
        "gate_status": "SHADOW",
        "updated_at": "2026-09-27T12:00:00+00:00",
        "raw_payload": {
            "nowcast": nowcast, "nowcast_obs": "CLEVELAND-2026-09", "sigma": 0.15,
            "n_train": 24, "hours_to_close": 6.5,
        },
    }


def _get(rows, **params):
    app = api_main.app
    app.dependency_overrides[get_supabase] = lambda: _Supa(rows)
    try:
        return TestClient(app).get("/api/cpi-display", params=params)
    finally:
        app.dependency_overrides.clear()


def test_every_row_declares_itself_display_only_and_carries_no_edge():
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)]).json()

    assert body["mode"] == "display"
    assert body["edge_pct"] is None, "a display row must not carry an edge number"
    row = body["rows"][0]
    assert row["edge_pct"] is None
    assert row["nowcast"] == 0.3
    assert row["our_prob"] == 0.55
    assert row["market_prob"] == 0.52


def test_the_response_says_why_in_words_not_just_a_flag():
    """A bare `mode: display` is jargon. The sentence is what a reader actually reads."""
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)]).json()

    assert "not an edge engine" in body["reason"].lower()
    assert "market" in body["reason"].lower()


def test_the_gate_still_reads_shadow():
    """Fails closed. Display-only must never read as promoted."""
    body = _get([_row("KXCPI-26SEP09-3.0", our=0.55, market=0.52, nowcast=0.3)]).json()

    assert body["rows"][0]["gate_status"] == "SHADOW"


def test_it_paginates():
    rows = [_row(f"KXCPI-26SEP09-{i}.0", our=0.5, market=0.5, nowcast=0.3) for i in range(5)]
    body = _get(rows, limit=2, offset=0).json()

    assert len(body["rows"]) == 2
    assert body["total"] == 5
    assert body["limit"] == 2
    assert body["offset"] == 0


def test_an_empty_league_returns_a_valid_empty_payload_not_an_error():
    body = _get([]).json()

    assert body == {**body, "rows": [], "total": 0}
    assert body["mode"] == "display"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_cpi_display.py -v`

Expected: all FAIL — `GET /api/cpi-display` returns 404, so `.json()` is `{"detail": "Not Found"}` and the first assertion errors.

- [ ] **Step 3: Add the endpoint**

In `tradehub/api/main.py`, immediately after the `/api/sports-edges` endpoint's closing `}`, add:

```python
@app.get("/api/cpi-display", tags=["CPI"])
def get_cpi_display(
    limit: int = Query(CPI_PAGE_DEFAULT, ge=1, le=200),
    offset: int = Query(0, ge=0),
    supabase=Depends(get_supabase),
):
    """CPI as context, not as an opportunity.

    Approved display-only on 2026-09-27 (spec section 9, approval 3), on the evidence in 5a: the
    market's Brier at 5 days out (0.0710) is barely worse than at 25 minutes (0.0677), so Kalshi
    prices CPI about as accurately a week ahead as in the last half hour. The market is not pricing
    off the nowcast, so a nowcast-based model has nothing to exploit by being early, and at every
    lead we are 1.33-1.43x behind with negative P&L.

    So this reads the `predictions` rows -- which carry the nowcast, our probability and the market
    mid -- and labels them. `edge_pct` is present and always null: a reader shown a probability and a
    market price will assume an opportunity unless something says otherwise, and the null says it in
    the shape a client checks rather than in prose it might ignore.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase not configured")
    rows = _fetch_all(
        supabase, "predictions",
        lambda q: q.select("*").eq("engine", "cpi_nowcast").order("updated_at", desc=True),
        cap=200,
    )
    total = len(rows)
    page = rows[offset:offset + limit]
    out = []
    for row in page:
        raw = row.get("raw_payload") or {}
        out.append({
            "market_ticker": row.get("market_ticker"),
            "our_prob": row.get("our_prob"),
            # The quote mid, the same quantity the sports endpoint reports. It is NOT what any edge
            # would be measured against, and edge_pct below is null so nothing implies otherwise.
            "market_prob": row.get("market_prob"),
            "edge_pct": None,
            "nowcast": raw.get("nowcast"),
            "nowcast_obs": raw.get("nowcast_obs"),
            "sigma": raw.get("sigma"),
            "n_train": raw.get("n_train"),
            "hours_to_close": raw.get("hours_to_close"),
            "gate_status": row.get("gate_status") or "SHADOW",
            "updated_at": row.get("updated_at"),
        })
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "mode": "display",
        "reason": (
            "CPI is not an edge engine. Measured on 2026-06-01..2026-09-20 the market prices this "
            "series about as accurately 5 days out as 25 minutes before close, so it is not pricing "
            "off the Cleveland Fed nowcast and an earlier decision buys nothing. Shown for context."
        ),
        "edge_pct": None,
        "rows": out,
        "total": total,
        "limit": limit,
        "offset": offset,
    }
```

Then add the page-size constant next to the existing ones near the top of the file:

```python
CPI_PAGE_DEFAULT = 50
```

`_fetch_all` **already exists** at `tradehub/api/main.py:232`, with the signature
`(supa, table, build, *, page=POSTGREST_CAP, cap=None, order=("id",))`. Use it as the call above
— do **not** add a second copy. The `.order("updated_at", desc=True)` belongs inside `build`,
and `cap=200` bounds the read. `Query`, `datetime` and `timezone` are already imported.

- [ ] **Step 4: Run the test to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q tests/test_cpi_display.py -v`

Expected: `5 passed`. If `test_an_empty_league_returns_a_valid_empty_payload_not_an_error` fails, remove the odd `body == {**body, "rows": [], "total": 0}` line and assert the two keys directly — it was a clumsy assertion, not a real requirement.

- [ ] **Step 5: Run the full suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q`

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add tradehub/api/main.py tests/test_cpi_display.py
git commit -m "feat(api): serve the CPI display view with the label it needs

Reads the predictions rows scan_cpi still writes -- nowcast, our probability,
market mid -- and labels them as context rather than opportunity.

edge_pct is present on every row and always null. A reader shown a probability
and a market price assumes an opportunity unless something says otherwise, and a
null says it in the shape a client actually checks rather than in prose it might
ignore. The reason travels in the payload too, because a bare mode: display is
jargon and the sentence is what gets read.

Gate still reads SHADOW: display-only must never read as promoted.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: The page

**Files:**
- Create: `market_sentiment_tool/src/lib/cpiDisplay.ts`
- Create: `market_sentiment_tool/src/lib/cpiDisplay.test.ts`
- Create: `market_sentiment_tool/src/pages/CpiDisplay.tsx`
- Modify: `market_sentiment_tool/src/App.tsx` (route + nav)
- Test: `market_sentiment_tool/src/lib/cpiDisplay.test.ts`

**Interfaces:**
- Consumes: `GET /api/cpi-display` from Task 2 — `{ as_of, mode, reason, edge_pct, rows, total, limit, offset }`, each row `{ market_ticker, our_prob, market_prob, edge_pct, nowcast, nowcast_obs, sigma, n_train, hours_to_close, gate_status, updated_at }`.
- Produces: nothing other tasks consume.

- [ ] **Step 1: Write the failing test**

Create `market_sentiment_tool/src/lib/cpiDisplay.test.ts`:

```typescript
import { describe, expect, it } from "vitest";

import { cpiHeadline, cpiRowNote, formatProb, isDisplayOnly } from "./cpiDisplay";

/**
 * The copy rules for a display-only engine.
 *
 * The failure mode this guards: a page showing a model probability beside a market price reads as
 * "here is an edge" no matter what the heading says, because that is what a probability beside a
 * price means everywhere else in finance. The label has to be in the row, not only in the page title.
 */
describe("isDisplayOnly", () => {
  it("is true unless the payload positively claims otherwise", () => {
    expect(isDisplayOnly({ mode: "display" })).toBe(true);
    // An older or absent payload must not be read as an edge engine either.
    expect(isDisplayOnly({})).toBe(true);
    expect(isDisplayOnly(null)).toBe(true);
  });
});

describe("cpiRowNote", () => {
  const row = {
    market_ticker: "KXCPI-26SEP09-3.0",
    our_prob: 0.55,
    market_prob: 0.52,
    edge_pct: null,
    nowcast: 0.3,
    nowcast_obs: "CLEVELAND-2026-09",
    sigma: 0.15,
    n_train: 24,
    hours_to_close: 6.5,
    gate_status: "SHADOW",
    updated_at: "2026-09-27T12:00:00Z",
  };

  it("names what the row actually is and never implies an edge", () => {
    const note = cpiRowNote(row);

    expect(note).toMatch(/not an edge/i);
    expect(note).not.toMatch(/\b\d+\.\d+ ?pp\b/); // no edge figure anywhere in the note
  });

  it("states the nowcast and where it came from", () => {
    expect(cpiRowNote(row)).toMatch(/CLEVELAND-2026-09/);
  });

  it("never claims promotion", () => {
    expect(cpiRowNote(row)).toMatch(/shadow/i);
    expect(cpiRowNote({ ...row, gate_status: "PROMOTED" })).toMatch(/promoted/i);
  });
});

describe("cpiHeadline", () => {
  it("says display, not edge", () => {
    expect(cpiHeadline(0).label).toMatch(/display/i);
  });

  it("counts rows rather than claiming an outcome", () => {
    // With no settled record, any win/loss word would be a claim.
    expect(cpiHeadline(0).value).not.toMatch(/win|loss|lose|profit/i);
    expect(cpiHeadline(12).value).toContain("12");
  });
});

describe("formatProb", () => {
  it("renders a probability as a percentage", () => {
    expect(formatProb(0.55)).toBe("55%");
  });

  it("renders an absent value as unknown, not as zero", () => {
    expect(formatProb(null)).toBe("—");
    expect(formatProb(undefined)).not.toBe("0%");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd market_sentiment_tool && npx vitest run src/lib/cpiDisplay.test.ts`

Expected: FAIL — `Cannot find module './cpiDisplay'`.

- [ ] **Step 3: Write the module**

Create `market_sentiment_tool/src/lib/cpiDisplay.ts`:

```typescript
/**
 * Copy rules for a display-only engine.
 *
 * CPI was approved DISPLAY ONLY on 2026-09-27: the market prices the series about as accurately five
 * days out as it does 25 minutes before close, so it is not pricing off the nowcast and an earlier
 * decision buys nothing. We are 1.33–1.43x behind at every lead.
 *
 * The reason this needs a module rather than a string in the page: a model probability shown beside
 * a market price reads as an edge no matter what the heading says, because that is what a
 * probability beside a price means everywhere else in finance. The label has to live in the row, and
 * it has to be unit-testable without a browser.
 */

export interface CpiDisplayRow {
  market_ticker: string;
  our_prob: number | null;
  market_prob: number | null;
  edge_pct: number | null;
  nowcast: number | null;
  nowcast_obs: string | null;
  sigma: number | null;
  n_train: number | null;
  hours_to_close: number | null;
  gate_status: string | null;
  updated_at: string | null;
}

export interface CpiDisplayResponse {
  as_of: string;
  mode: string;
  reason: string;
  edge_pct: null;
  rows: CpiDisplayRow[];
  total: number;
  limit: number;
  offset: number;
}

/** Display-only unless the payload positively claims otherwise. */
export function isDisplayOnly(payload: { mode?: string } | null | undefined): boolean {
  return (payload?.mode ?? "display") === "display";
}

export function formatProb(value: number | null | undefined): string {
  if (typeof value !== "number" || !Number.isFinite(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

/** The per-row sentence. No edge figure, ever — there isn't one. */
export function cpiRowNote(row: CpiDisplayRow): string {
  const gate = (row.gate_status ?? "SHADOW").toUpperCase();
  const source = row.nowcast_obs ? ` from ${row.nowcast_obs}` : "";
  const lead =
    typeof row.hours_to_close === "number" ? `${row.hours_to_close.toFixed(1)}h to close` : "close time unknown";
  return `Cleveland Fed nowcast ${formatProb(row.nowcast)}${source} · ${lead} · not an edge · ${gate}`;
}

export interface CpiHeadline {
  label: string;
  value: string;
}

export function cpiHeadline(rowCount: number): CpiHeadline {
  return {
    label: "CPI display",
    value: `${rowCount} market${rowCount === 1 ? "" : "s"} shown`,
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd market_sentiment_tool && npx vitest run src/lib/cpiDisplay.test.ts`

Expected: `12 passed` (4 describe blocks, 11 tests). If the count differs, check no assertion was dropped.

- [ ] **Step 5: Write the page**

Create `market_sentiment_tool/src/pages/CpiDisplay.tsx`:

```tsx
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import {
  cpiHeadline,
  cpiRowNote,
  formatProb,
  isDisplayOnly,
  type CpiDisplayResponse,
} from "@/lib/cpiDisplay";

/**
 * CPI, shown for context.
 *
 * Not an edge engine, and the page says so in its heading, in its reason line, and in every row —
 * because a probability beside a price reads as an opportunity everywhere else in finance, and one
 * heading is not enough to overcome that.
 */
export default function CpiDisplay() {
  const [data, setData] = useState<CpiDisplayResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/cpi-display?limit=50"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        setData(payload as CpiDisplayResponse);
        setError(null);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) {
    return (
      <div className="p-8">
        <div className="rounded-lg border border-rose-900 bg-rose-950/30 p-4 text-sm text-rose-200">
          <p className="font-semibold">CPI nowcast unavailable</p>
          <p className="mt-1 text-rose-300/80">{error}</p>
        </div>
      </div>
    );
  }

  if (!data) return <div className="p-8 text-slate-400">Loading CPI nowcast…</div>;

  const headline = cpiHeadline(data.rows.length);

  return (
    <div className="p-8 space-y-6">
      <header className="border-b border-slate-900 pb-4">
        <h1 className="text-2xl font-bold text-white">{headline.label}</h1>
        <p className="text-sm text-slate-400">{headline.value}</p>
      </header>

      {/* The reason is above the table, not only inside each row, so it is read before the numbers
          rather than after them. */}
      <div className="rounded-lg border border-amber-900/60 bg-amber-950/20 p-4 text-sm text-amber-100">
        <p className="font-semibold">Not an edge engine</p>
        <p className="mt-1 text-amber-200/90">{data.reason}</p>
      </div>

      {data.rows.length === 0 ? (
        <p className="text-slate-400">
          No open CPI markets right now. The nowcast is published on a schedule, so an empty board
          between prints is expected rather than a fault.
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            CPI nowcast against the market. This engine is not an edge engine; the figures are context.
          </caption>
          <thead>
            <tr className="border-b border-slate-800">
              {["Market", "Model", "Market mid", "Nowcast", "Why this is here"].map((label) => (
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
              <tr key={row.market_ticker} className="border-t border-slate-800 align-top">
                <th scope="row" className="py-2 pr-3 text-left font-normal font-medium text-slate-100">
                  {row.market_ticker}
                </th>
                <td className="py-2 pr-3 text-slate-300">{formatProb(row.our_prob)}</td>
                <td className="py-2 pr-3 text-slate-300">{formatProb(row.market_prob)}</td>
                <td className="py-2 pr-3 text-slate-300">{formatProb(row.nowcast)}</td>
                <td className="py-2 pr-3 text-xs text-slate-400">{cpiRowNote(row)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {isDisplayOnly(data) && null}
    </div>
  );
}
```

**Before committing, delete the line `{isDisplayOnly(data) && null}`.** It is left here only to keep the
`isDisplayOnly` import honest; it renders nothing and must not ship. Either remove the line and the
import, or keep the import out of the page entirely — `isDisplayOnly` is exercised by the lib test and
is not needed by this page. Preferred: remove both the line and the `isDisplayOnly` import.

- [ ] **Step 6: Wire the route and the nav**

In `market_sentiment_tool/src/App.tsx`, add the import next to the other page imports:

```typescript
import CpiDisplay from "@/pages/CpiDisplay";
```

Add the route inside the `<Routes>` block, after the `/sports` route:

```typescript
        <Route path="/cpi" element={<CpiDisplay />} />
```

Add a nav entry after the Sports one, copying the existing `NavLink` className expression exactly and
swapping the label and icon:

```typescript
        <NavLink
          to="/cpi"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <BarChart3 className="w-5 h-5 text-amber-400" /> CPI Nowcast
        </NavLink>
```

Add `BarChart3` to the existing `lucide-react` import on line 9. If `BarChart3` is not exported by the
installed `lucide-react` version, use `LineChart`, which is already imported.

- [ ] **Step 7: Verify the frontend**

```bash
cd market_sentiment_tool
npx tsc --noEmit -p tsconfig.app.json
npx vitest run
npm run build
```

Expected: typecheck clean, all vitest pass (the existing 8 files plus `cpiDisplay.test.ts`), build
succeeds.

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

Expected: both pytest runs pass, ruff clean. Paste all three outputs in the PR comment.

- [ ] **Step 9: Commit**

```bash
git add market_sentiment_tool/src/lib/cpiDisplay.ts \
        market_sentiment_tool/src/lib/cpiDisplay.test.ts \
        market_sentiment_tool/src/pages/CpiDisplay.tsx \
        market_sentiment_tool/src/App.tsx
git commit -m "feat(web): a CPI page that says what it is in every row

A model probability shown beside a market price reads as an edge no matter what
the heading says, because that is what a probability beside a price means
everywhere else in finance. One heading was not enough, so the label lives in
the row: the nowcast and its source, the time to close, 'not an edge', and the
gate state. The reason also sits above the table so it is read before the
numbers rather than after.

Empty state says an empty board between prints is expected, since the nowcast
publishes on a schedule.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage.** §5's CPI outcome (REFUTED) → Task 1 removes the edge claim. §5a's numbers → Task 3's `reason` string, so the page cites what it rests on. §6's page purposes → Task 4. §9 approval 3 ("DISPLAY ONLY. Show the nowcast vs the market for context") → Tasks 1–4 together. Global constraints: suggest-only is why no balance or position appears; "an engine that loses stays visible" is why Task 1 keeps `predictions`; the gate fails closed is asserted in `test_the_gate_still_reads_shadow`; the verification contract is Global Constraints plus Task 4 Step 8; the commit trailer is in every commit.

**Not in scope here, and deliberately:** the §5b `calibration_off` change (it is a gate-threshold
decision awaiting a ruling — putting it in this PR would smuggle an unapproved change into an approved
one); the oracle-bound tooling for labor (that plan is blocked on ALFRED access); the sports ranking
and window work (separate plan).

**2. Placeholder scan.** No TBD, TODO, or "handle edge cases". Every code block is complete and
copyable. The one thing to watch is Task 4 Step 5, which deliberately shows a line to delete — it is
called out explicitly and the preferred action is stated, so it cannot ship by accident.

**3. Type consistency.** `CpiDisplayResponse` and `CpiDisplayRow` are defined once in Task 4 Step 3 and
used by both the lib test and the page in the same task. `scan_cpi`'s signature is unchanged, so the
caller at `scan.py:490` needs no edit and Task 2's reliance on `predictions` columns is satisfied by
Task 1's test, which asserts those exact keys. `edge_pct` is `null` in the type, matching the endpoint.
`isDisplayOnly` takes `{ mode?: string } | null | undefined` and the page passes the full response,
which is structurally compatible.
