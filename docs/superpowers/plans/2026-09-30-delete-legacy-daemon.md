# Delete the Legacy Daemon and Its Engines (Plan m) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete `background_scanner.py`, `macro_engine.py`, `quant_engine.py` and `discord_notifier.py`, keep the quarantine state machine tested against a frozen copy of the old ruling, and retire only the tests whose subject was deleted.

**Architecture:** Kevin's decision (2026-09-30): the daemon and both engines no longer fit the product. The daemon was the only writer of `kalshi_quarantine_edges`, and it is not run by any VPS timer (only scan, settle and journal run), so no live behaviour depends on it. `tests/legacy_ruling.py` freezes the pre-deletion quarantine ruling as data and an autouse fixture installs it, so the `quarantined` / `could_not_run` state machine and its ~80 pinned tests still run unchanged. The live ruling loses its MacroEngine site and its WeatherEngine site stops claiming a scanner wires it, so every board reads `ran`, which is now true.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§9 Cuts (macro_engine, quant_engine), §12 quarantine-safety tests). **Depends on:** nothing: it is independent of plan (j) and does not touch `ai_validator.py` or `sentiment_filter.py`.

> **Provenance:** every code block below was implemented and run by the reviewer on top of the current `main` in a scratch worktree before this plan was written (backend 1383 passed at monotonic 5.0 and at 1e7; the guard test fails on the pre-deletion code and passes after). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR per plan, from a fresh branch off `main`. Do only this plan's tasks.
- Never write, print or commit secret values; never commit `__pycache__`, `.pyc` or `.env`; never apply a Supabase migration yourself (the reviewer applies it before merge).
- **Deleted:** `tradehub/scripts/background_scanner.py`, `tradehub/engines/macro_engine.py`, `tradehub/engines/quant_engine.py`, `tradehub/core/discord_notifier.py` (only the daemon used it).
- **Kept on purpose:** `tradehub/core/ai_validator.py` (still imported by the dead `core/microstructure_engine.py`), `tradehub/engines/weather_engine.py` (used by `scripts/weather_auto_sell.py`), `tradehub/engines/weather_maker.py`, `tradehub/quarantine.py`, the quarantine sink table and its API/UI. Do not delete them here.
- **Retired tests, exactly these and nothing else:** the three tests that drove `background_scanner.run_scan` (publish-path, discord-alert, scanner half of the source-path test), the macro halves of the engine-measure tests, the macro unpriceable-market test, and the scanner-consumer section of `tests/test_kalshi_quote_cents.py`. Their subjects no longer exist. The property they guarded, that a quarantined row never reaches the trade sink, is still enforced and tested at `upsert_opportunities` and `upsert_quarantined`.
- Every other quarantine and engine-health test keeps its assertions; they now read the frozen ruling through `legacy_ruling.install`.
- No migration. No dependency change (the `scanner` extra stays; `google-genai` is still imported by `ai_validator.py`).
- Out of scope, flag in the PR body: `shared/background_scanner.py` (a separate old file), `/api/opportunities` (its cache has no writer and returns `[]`), and the now-unused `torch`/`transformers` extras.

---
### Task 1: Guard, frozen ruling, test re-pointing

**Files:**
- Create: `tests/test_legacy_daemon_gone.py`, `tests/legacy_ruling.py`
- Modify: `tests/test_engine_health.py`, `tests/test_weather_macro_quarantine.py`, `tests/test_env_hygiene.py`, `tests/test_kalshi_quote_cents.py`

**Interfaces:**
- Produces: `legacy_ruling.{LEGACY_SITES, DELETED_MODULES, LiveTuple, STOPPED_SITES, WIRED_STOPPED_SITES, UNWIRED_STOPPED_SITES, install(monkeypatch)}` (`STOPPED_SITES` etc. are read-through views of the installed ruling, so a test that imports them sees the fixture's value); guard tests that fail while any deleted file exists or is imported.

- [ ] **Step 1: Write the failing guard** (`tests/test_legacy_daemon_gone.py`)

```python
"""Guards for deleting the legacy daemon and its engines (v2 spec §9): what is gone stays gone."""

import ast
from pathlib import Path

from tradehub import engine_health as health

ROOT = Path(__file__).resolve().parents[1]
DELETED = (
    "tradehub/scripts/background_scanner.py",
    "tradehub/engines/macro_engine.py",
    "tradehub/engines/quant_engine.py",
    "tradehub/core/discord_notifier.py",
)
DELETED_MODULES = {p[:-3].replace("/", ".") for p in DELETED}


def test_the_deleted_files_do_not_exist():
    assert [p for p in DELETED if (ROOT / p).exists()] == []


def test_nothing_imports_a_deleted_module():
    offenders = []
    for path in (ROOT / "tradehub").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
                if isinstance(node, ast.ImportFrom) else [])
            hit = DELETED_MODULES.intersection(names)
            if hit:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert not offenders, offenders


def test_the_live_ruling_has_no_macro_site_and_no_wired_site():
    """No scanner is wired to a ruled-against engine any more, so every board reads `ran`, truthfully.

    The state machine (`quarantined`, `could_not_run`) is still code and is still tested, against the
    frozen pre-deletion ruling in `tests/legacy_ruling.py`.
    """
    assert "MacroEngine" not in {s.name for s in health.STOPPED_SITES}
    assert health.WIRED_STOPPED_SITES == ()
    assert {health.edge_type_state(edge_type) for edge_type, _ in health.EDGE_TYPES} == {health.STATE_RAN}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_legacy_daemon_gone.py -v`
Expected: 3 FAILED (the files exist, `ai_validator`/others import them, the live ruling still has a MacroEngine site).

- [ ] **Step 3: Add the frozen ruling and re-point the tests** (these changes keep the suite green on the current code; nothing is deleted yet)

`tests/legacy_ruling.py`:

```python
"""The quarantine ruling as it stood while the legacy daemon ran, kept as DATA so its state machine stays tested.

`tradehub/scripts/background_scanner.py`, `macro_engine.py` and `quant_engine.py` were deleted (v2 spec §9)
and the daemon was the only thing that ever wired `WeatherEngine` or `MacroEngine` to a scanner. So in
production no site is wired any more and every edge type reads `ran`: truthfully, because `scan.py` feeds
the boards. The `quarantined` and `could_not_run` states, the partition and the copy around them are still
code, still reachable through `tradehub.engine_health`, and still pinned by `test_engine_health.py` and
`test_weather_macro_quarantine.py`; those tests assert against this frozen ruling instead of the live one.

`LiveTuple` makes the three ruling constants read the module's CURRENT value each time they are touched, so
a test that imports `STOPPED_SITES` sees whatever the autouse fixture (or its own monkeypatch) installed.
"""

from __future__ import annotations

from dataclasses import replace

from tradehub import engine_health as health


class LiveTuple:
    """A read-through view of `tradehub.engine_health.<name>`; iterates, indexes, sizes and tests membership."""

    def __init__(self, name: str):
        self._name = name

    def _value(self):
        return getattr(health, self._name)

    def __iter__(self):
        return iter(self._value())

    def __len__(self):
        return len(self._value())

    def __getitem__(self, index):
        return self._value()[index]

    def __contains__(self, item):
        return item in self._value()


STOPPED_SITES = LiveTuple("STOPPED_SITES")
WIRED_STOPPED_SITES = LiveTuple("WIRED_STOPPED_SITES")
UNWIRED_STOPPED_SITES = LiveTuple("UNWIRED_STOPPED_SITES")

_REAL = {site.name: site for site in health.STOPPED_SITES}

LEGACY_SITES = (
    replace(_REAL["WeatherEngine"], wired_to_a_scanner=True),
    health.StoppedSite(
        name="MacroEngine",
        module="tradehub/engines/macro_engine.py",  # deleted: a tombstone, so file-evidence tests skip it
        site="tradehub/engines/macro_engine.py:459",
        edge_type="MACRO",
        wired_to_a_scanner=True,
        disposition="repaired_quarantined",
        reason=("This is the Tier-1 real-edge macro engine, and it prices every market against `yes_ask`. "
                + health._THE_API_MOVED + health._REPAIRED_AND_QUARANTINED),
    ),
    _REAL["WeatherMaker"],
    _REAL["clean_market_data"],
)

DELETED_MODULES = frozenset({"tradehub/engines/macro_engine.py"})


def install(monkeypatch) -> None:
    """Make `tradehub.engine_health` answer from the legacy ruling for the duration of one test."""
    monkeypatch.setattr(health, "STOPPED_SITES", LEGACY_SITES)
    monkeypatch.setattr(health, "STOPPED_SITE_NAMES", frozenset(s.name for s in LEGACY_SITES))
    monkeypatch.setattr(health, "WIRED_STOPPED_SITES", tuple(s for s in LEGACY_SITES if s.wired_to_a_scanner))
    monkeypatch.setattr(health, "UNWIRED_STOPPED_SITES", tuple(s for s in LEGACY_SITES if not s.wired_to_a_scanner))
```

```diff
diff --git a/tests/test_engine_health.py b/tests/test_engine_health.py
index cdda633..c493984 100644
--- a/tests/test_engine_health.py
+++ b/tests/test_engine_health.py
@@ -26,9 +26,6 @@ from tradehub.engine_health import (
     STATE_COULD_NOT_RUN,
     STATE_QUARANTINED,
     STATE_RAN,
-    STOPPED_SITES,
-    UNWIRED_STOPPED_SITES,
-    WIRED_STOPPED_SITES,
     edge_type_entry,
     edge_type_state,
     engine_health,
@@ -37,8 +34,19 @@ from tradehub.engine_health import (
     stopped_sites_for,
 )
 
+import pytest
+
+import legacy_ruling
+from legacy_ruling import DELETED_MODULES, STOPPED_SITES, UNWIRED_STOPPED_SITES, WIRED_STOPPED_SITES
+
 REPO_ROOT = Path(__file__).resolve().parents[1]
 
+
+@pytest.fixture(autouse=True)
+def _legacy_ruling(monkeypatch):
+    """These tests pin the state machine; the live ruling has no wired site since the daemon was deleted."""
+    legacy_ruling.install(monkeypatch)
+
 # The reads that were the defect, per site, quoted rather than pattern-matched. Kalshi moved these
 # fields and the readers moved with it in neither case; this map is what made "the ruling is stale"
 # a test failure rather than an opinion.
@@ -120,6 +128,8 @@ class TestStoppedEnginesReadAsBroken:
         """
         for site in STOPPED_SITES:
             assert site.module, site
+            if site.module in DELETED_MODULES:
+                continue  # a tombstone in the frozen legacy ruling: the file was deleted on purpose
             path = REPO_ROOT / site.module
             assert path.is_file(), f"{site.module} does not exist; the ruling points at nothing"
             module, _, line = site.site.partition(":")
@@ -144,6 +154,8 @@ class TestStoppedEnginesReadAsBroken:
         assert len(repaired) == 2, "both wired sites were repaired; if this is not 2 the maps below are stale"
 
         for site in repaired:
+            if site.module in DELETED_MODULES:
+                continue  # deleted with the legacy daemon; nothing left to revert
             expected = REPAIRED_READS[site.site]
             module_, _, line = site.site.partition(":")
             body = (REPO_ROOT / module_).read_text().splitlines()[int(line) - 1]
diff --git a/tests/test_env_hygiene.py b/tests/test_env_hygiene.py
index 27340f3..f4b8246 100644
--- a/tests/test_env_hygiene.py
+++ b/tests/test_env_hygiene.py
@@ -179,7 +179,6 @@ def test_entrypoints_still_opt_into_the_local_env_file():
         "tradehub/api/main.py": "load_local_env()",
         "tradehub/scripts/scan.py": "load_local_env()",
         "tradehub/scripts/settle_predictions.py": "load_local_env()",
-        "tradehub/scripts/background_scanner.py": "load_local_env()",
         "tradehub/scripts/market_alerts.py": "load_local_env()",
         "tradehub/scripts/weather_auto_sell.py": "load_local_env()",
         "tradehub/scripts/auto_retrain_regime.py": "load_local_env()",
diff --git a/tests/test_kalshi_quote_cents.py b/tests/test_kalshi_quote_cents.py
index c3d9dfc..99e7f07 100644
--- a/tests/test_kalshi_quote_cents.py
+++ b/tests/test_kalshi_quote_cents.py
@@ -7,7 +7,6 @@ and ``my_prob - 0`` published a probability-sized "edge" at an untradeable
 price. A missing figure is never a number, so it must be None.
 """
 
-import pandas as pd
 import pytest
 from cryptography.hazmat.primitives import serialization
 from cryptography.hazmat.primitives.asymmetric import rsa
@@ -15,7 +14,6 @@ from cryptography.hazmat.primitives.asymmetric import rsa
 from tradehub.core.kalshi_feed import process_markets
 from tradehub.core.kalshi_portfolio import KalshiPortfolio
 from tradehub.markets import QUOTE_FIELDS, quote_cents
-from tradehub.scripts import background_scanner
 
 # The real market from the briefing: 62c/63c YES, 37c/38c NO.
 LIVE_T64 = {
@@ -119,84 +117,6 @@ def test_process_markets_still_reads_a_legacy_only_market():
     assert (row["yes_bid"], row["yes_ask"], row["no_bid"], row["no_ask"]) == (62, 63, 37, 38)
 
 
-# ─── site 1 consumer: background_scanner ──────────────────────────────────────
-
-def _stub_quant(monkeypatch, markets=(), pred=0.70, raw_markets=None):
-    """Run scan_quant_ml with the model and network stubbed out.
-
-    Pass `raw_markets` to drive the real chain (raw Kalshi payload ->
-    process_markets -> scan_quant_ml) instead of prepared market dicts.
-    """
-    from tradehub.engines import quant_engine
-
-    df = pd.DataFrame({"Close": [100.0, 101.0]})
-    monkeypatch.setattr(quant_engine, "fetch_live_btc_alpaca", lambda: df)
-    monkeypatch.setattr(quant_engine, "create_walk_forward_features", lambda d: d)
-    monkeypatch.setattr(background_scanner, "load_model", lambda t: (object(), False))
-    monkeypatch.setattr(background_scanner, "predict_next_hour", lambda m, d, t: pred)
-    monkeypatch.setattr(background_scanner, "get_market_volatility", lambda d, window=24: 0.01)
-    if raw_markets is None:
-        monkeypatch.setattr(background_scanner, "get_real_kalshi_markets", lambda t: (list(markets), "Stub", {}))
-    else:
-        monkeypatch.setattr(
-            background_scanner, "get_real_kalshi_markets", lambda t: (process_markets(list(raw_markets), t), "Targeted", {})
-        )
-    return background_scanner.scan_quant_ml()
-
-
-def _market(**overrides):
-    return {"title": "Will BTC be above 100,000?", "market_id": "KXBTC-26", **overrides}
-
-
-def test_quant_engine_prices_the_edge_at_the_real_ask(monkeypatch):
-    records, opportunities = _stub_quant(monkeypatch, [_market(yes_ask=63.0, yes_bid=62.0)])
-    (record,) = records
-    assert record["market_yes_ask"] == 63.0
-    assert record["model_prob"] == 70.0
-    assert record["calculated_edge"] == pytest.approx(7.0)  # 70 - 63, not 70 - 0
-    assert record["calculated_edge"] != 70.0
-    assert record["kelly_bet"] > 0
-    assert (opportunities[0]["Edge"], opportunities[0]["Action"]) == (7.0, "BUY YES")
-
-
-@pytest.mark.parametrize("market", [
-    pytest.param(_market(), id="no price fields at all"),
-    pytest.param(_market(yes_ask=None), id="explicit None"),
-    pytest.param(_market(yes_ask=0, yes_bid=0), id="zero ask is a price of nothing"),
-])
-def test_quant_engine_never_fabricates_an_edge_without_a_price(monkeypatch, market):
-    records, opportunities = _stub_quant(monkeypatch, [market])
-    assert records == []
-    assert opportunities == []
-    assert "calculated_edge" not in {k for r in records for k in r}
-
-
-def test_quant_engine_skips_only_the_unpriced_market(monkeypatch):
-    records, opportunities = _stub_quant(
-        monkeypatch, [_market(yes_ask=None), _market(yes_ask=63.0, market_id="Priced")]
-    )
-    assert [r["market_id"] for r in records] == ["Priced"]
-    assert [o["MarketId"] for o in opportunities] == ["Priced"]
-
-
-# ─── the whole chain: raw Kalshi payload -> process_markets -> scan_quant_ml ────
-
-def test_end_to_end_prices_the_edge_from_the_dollar_quote(monkeypatch):
-    records, opportunities = _stub_quant(monkeypatch, raw_markets=[{**LIVE_T64, **_market()}])
-    (record,) = records
-    assert record["market_yes_ask"] == 63.0
-    assert record["calculated_edge"] == 7.0
-    assert record["calculated_edge"] != 70.0  # the pre-fix figure: my_prob - 0
-    assert opportunities[0]["MarketYesAsk"] == 63
-
-
-def test_end_to_end_unpriced_market_is_skipped_not_credited_with_an_edge(monkeypatch):
-    unpriced = {k: v for k, v in LIVE_T64.items() if not k.endswith("_dollars")}
-    records, opportunities = _stub_quant(monkeypatch, raw_markets=[{**unpriced, **_market()}])
-    assert records == []
-    assert opportunities == []
-
-
 # ─── site 2: kalshi_portfolio.get_portfolio_summary ────────────────────────────
 
 def _portfolio(monkeypatch, market):
diff --git a/tests/test_weather_macro_quarantine.py b/tests/test_weather_macro_quarantine.py
index 155fc09..d608319 100644
--- a/tests/test_weather_macro_quarantine.py
+++ b/tests/test_weather_macro_quarantine.py
@@ -38,7 +38,6 @@ from tradehub.engine_health import (
     STATE_COULD_NOT_RUN,
     STATE_QUARANTINED,
     STATE_RAN,
-    STOPPED_SITES,
     edge_type_entry,
     edge_type_state,
     engine_health,
@@ -60,7 +59,18 @@ from tradehub.quarantine import (
     quarantine_report,
 )
 
+import legacy_ruling
+from legacy_ruling import DELETED_MODULES, STOPPED_SITES
+
 REPO_ROOT = Path(__file__).resolve().parents[1]
+
+
+@pytest.fixture(autouse=True)
+def _legacy_ruling(monkeypatch):
+    """The state machine is pinned against the frozen ruling; see `tests/legacy_ruling.py`."""
+    legacy_ruling.install(monkeypatch)
+
+
 FIXTURES = Path(__file__).resolve().parent / "fixtures" / "quarantine"
 
 # ── the fixtures, and what they are for ─────────────────────────────────────────────────────
@@ -208,74 +218,6 @@ def recording_client(monkeypatch) -> _RecordingClient:
     return client
 
 
-def test_the_quarantine_writes_nothing_to_the_trade_sink(recording_client, monkeypatch, weather_markets, macro_markets):
-    """The whole safety property, as one test: repairing these engines must not publish them.
-
-    This drives the REAL publish path -- `background_scanner.run_scan`, with both engines replaced
-    by the repaired ones run against real market snapshots -- and asserts on the payloads that would
-    have gone to the database. Not a grep for a table name, not a check that a list is empty: a
-    real write, recorded.
-
-    Two independent things have to hold and both are asserted, because each alone would be a promise
-    rather than a property:
-
-      * `run_scan` never puts a quarantined row in the list it publishes, and
-      * `upsert_opportunities` drops any marked row even if handed one.
-
-    Breaking either is caught here. That is the point of having both: it takes breaking BOTH to get a
-    quarantined row into `kalshi_edges`, and a refactor that does the first is stopped by the second.
-    """
-    from tradehub.scripts import background_scanner as scanner
-    from tradehub.engines.macro_engine import MacroEngine
-    from tradehub.engines.weather_engine import WeatherEngine
-
-    weather_engine = WeatherEngine()
-    weather_engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
-    monkeypatch.setattr(
-        scanner, "WeatherEngine", lambda: _StubbedEngine(weather_engine, weather_markets, "WEATHER")
-    )
-
-    macro_engine = MacroEngine.__new__(MacroEngine)
-    macro_engine._cache = {}
-    macro_engine.get_latest_cpi_yoy = lambda: 3.1
-    macro_engine.get_fed_rate_prediction = lambda: 3.75
-    macro_engine.get_gdp_prediction = lambda: 1.9
-    macro_engine.get_unemployment_rate = lambda: 4.4
-    macro_engine.get_transition_penalty = lambda: {
-        "in_transition": False, "penalty": 0, "reasoning": "none"}
-    macro_engine.get_leading_inflation_signals = lambda: {
-        "signal": "neutral", "adjustment": 0, "ppi_trend": "flat", "oil_trend": "flat",
-        "reasoning": "none"}
-    macro_engine.get_tariff_shock_factor = lambda: {
-        "shock_detected": False, "multiplier": 1.0, "reasoning": "none"}
-    macro_engine.get_taylor_rule_rate = lambda: {
-        "taylor_rate": None, "divergence": 0.0, "reasoning": "none"}
-    monkeypatch.setattr(
-        scanner, "MacroEngine", lambda: _StubbedEngine(macro_engine, macro_markets, "MACRO")
-    )
-    # Frozen for the same reason `_measure` freezes: without it the weather
-    # fixtures expire and this test proves the property against zero weather
-    # rows, which is a weaker claim wearing the same green.
-    _freeze_fixture_time(monkeypatch)
-    # The paper-trading tier and the notifiers are not what this test is about, and letting them
-    # run would make the assertion depend on a crypto model download.
-    monkeypatch.setattr(scanner, "scan_quant_ml", lambda: ([], []))
-
-    scanner.run_scan()
-
-    assert "kalshi_edges" not in recording_client.tables_written(), (
-        "the quarantined path wrote to the trade-proposal sink. Everything in this PR exists so "
-        f"this cannot happen; the writes were to {sorted(recording_client.tables_written())}"
-    )
-    # And the paper tier, which is allowed to publish, proves the recorder works. Without this the
-    # assertion above would also pass on a client that recorded nothing at all -- which is the
-    # failure mode a fake makes, and the reason this line is here.
-    assert recording_client.tables_written() == {"kalshi_quarantine_edges"}, (
-        "expected the quarantine sink and nothing else; got "
-        f"{sorted(recording_client.tables_written())}"
-    )
-
-
 def test_upsert_opportunities_refuses_a_quarantined_row_even_when_handed_one(recording_client, monkeypatch):
     """Defence in depth, as its own test so a failure names which of the two mechanisms broke.
 
@@ -362,14 +304,12 @@ def test_the_quarantine_sink_is_a_different_table_from_the_trade_sink(recording_
 def test_no_source_path_leads_a_quarantined_row_to_the_trade_sink():
     """The structural claim, as a source-level fact rather than a promise.
 
-    Deliberately narrow. It does not try to prove the absence of every possible path -- a source
-    grep cannot do that, and a test that pretended to would be worse than none. What it does check is
-    the two things a future edit is most likely to get wrong: that `upsert_quarantined` names one
-    table and it is not `kalshi_edges`, and that the publish call in `run_scan` is handed something
-    that does not include the quarantine list.
+    Deliberately narrow. It checks that `upsert_quarantined` names one table and it is not
+    `kalshi_edges`. The second half of this test used to inspect the legacy daemon's `run_scan`; the
+    daemon was deleted (v2 spec §9) and with it the only producer of quarantined rows, so what is left
+    to pin is the sink itself plus `upsert_opportunities` refusing a marked row (tested separately).
     """
     from tradehub.core import supabase_client
-    from tradehub.scripts import background_scanner
 
     # The docstring says `kalshi_edges` a dozen times, on purpose -- it is the sentence explaining
     # where those rows do NOT go. So this checks the CODE, with the docstring removed, and asserts
@@ -380,30 +320,6 @@ def test_no_source_path_leads_a_quarantined_row_to_the_trade_sink():
     assert "kalshi_edges" not in code, "the quarantine sink must never open the trade sink"
     assert 'client.table("kalshi_quarantine_edges")' in sink_source
 
-    scan_source = inspect.getsource(background_scanner.run_scan)
-    # The publish call's argument is built from the paper tier alone. Asserted as a source fact
-    # because `run_scan` is 60 lines of orchestration and the guarantee lives in one assignment.
-    assert "all_opps = list(paper_ops)" in scan_source, scan_source
-    assert "all_opps = real_edge_ops" not in scan_source, scan_source
-    assert "all_opps = real_edge_ops + paper_ops" not in scan_source, scan_source
-
-
-def test_the_discord_alert_path_never_receives_a_quarantined_row():
-    """A push notification is the one place the marker cannot travel beside the number.
-
-    A Discord alert carries a headline and nothing else. "84-point edge" with no QUARANTINED word on
-    it is exactly the false reading this change exists to prevent, and it would arrive in someone's
-    phone where the only context is the message. So the alert call is handed an empty list, and this
-    asserts it stays that way.
-    """
-    from tradehub.scripts import background_scanner
-
-    source = inspect.getsource(background_scanner.run_scan)
-    assert "notifier.send_alert([], min_edge=30.0)" in source, (
-        "the Discord path must be handed nothing; quarantined rows are not alerted on"
-    )
-    assert "notifier.send_alert(quarantined_ops" not in source
-
 
 # ── 2. the engines now MEASURE, and the numbers are pinned ──────────────────────────────────
 
@@ -456,65 +372,35 @@ def _freeze_fixture_time(monkeypatch) -> None:
     )
 
 
-def _measure(monkeypatch, weather_markets, macro_markets) -> list[dict]:
-    """Run both engines the way `scan_real_edge` does, and return the marked rows."""
-    from tradehub.scripts import background_scanner as scanner
-    from tradehub.engines.macro_engine import MacroEngine
+def _measure(monkeypatch, weather_markets) -> list[dict]:
+    """Run the weather engine against the recorded snapshot and return the marked rows.
+
+    Weather only: the macro engine and the daemon that ran both were deleted (v2 spec §9). The engine
+    class is the real one; only its NWS call is replaced.
+    """
     from tradehub.engines.weather_engine import WeatherEngine
 
     _freeze_fixture_time(monkeypatch)
-
-    weather_engine = WeatherEngine()
-    weather_engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
-    monkeypatch.setattr(
-        scanner, "WeatherEngine", lambda: _StubbedEngine(weather_engine, weather_markets, "WEATHER")
-    )
-    macro_engine = MacroEngine.__new__(MacroEngine)
-    macro_engine._cache = {}
-    macro_engine.get_latest_cpi_yoy = lambda: 3.1
-    macro_engine.get_fed_rate_prediction = lambda: 3.75
-    macro_engine.get_gdp_prediction = lambda: 1.9
-    macro_engine.get_unemployment_rate = lambda: 4.4
-    macro_engine.get_transition_penalty = lambda: {
-        "in_transition": False, "penalty": 0, "reasoning": "none"}
-    macro_engine.get_leading_inflation_signals = lambda: {
-        "signal": "neutral", "adjustment": 0, "ppi_trend": "flat", "oil_trend": "flat",
-        "reasoning": "none"}
-    macro_engine.get_tariff_shock_factor = lambda: {
-        "shock_detected": False, "multiplier": 1.0, "reasoning": "none"}
-    macro_engine.get_taylor_rule_rate = lambda: {
-        "taylor_rate": None, "divergence": 0.0, "reasoning": "none"}
-    monkeypatch.setattr(
-        scanner, "MacroEngine", lambda: _StubbedEngine(macro_engine, macro_markets, "MACRO")
-    )
-    return scanner.scan_real_edge()
+    engine = WeatherEngine()
+    engine.get_nws_forecast = lambda city: {"2026-09-28": 74, "2026-09-29": 76}
+    return mark_quarantine(_StubbedEngine(engine, weather_markets, "WEATHER").find_opportunities())
 
 
 class TestTheEnginesMeasureSomething:
-    def test_the_repaired_engines_return_a_non_zero_count(self, monkeypatch, weather_markets, macro_markets):
-        """Not "more than zero" -- the exact figures these fixtures produce, pinned.
-
-        Previously both engines returned 0 for every market they fetched: `market.get('yes_ask', 0)`
-        read a key Kalshi stopped sending, so every price came back 0, `if yes_ask == 0: continue`
-        skipped all of them, and the scan logged "Found 0 opportunities" and exited cleanly. That is
-        the state PR #38 labelled. Pinning the exact numbers means a regression to zero fails here,
-        and a large drift fails as a NUMBER somebody has to look at rather than as a quiet change.
-
-        These are the counts for the FIXTURES, which are a trimmed economics snapshot -- 30 rows of
-        weather (all of it) and 47 of macro. The full 441-market run produced 30 and 265, and that
-        measurement is pinned separately in `test_the_measured_live_run_is_pinned` against the
-        recorded rows. Two different numbers for two different inputs, kept apart on purpose: one
-        says the repair works reproducibly, the other says what the market actually looked like.
+    def test_the_repaired_engine_returns_a_non_zero_count(self, monkeypatch, weather_markets):
+        """Not "more than zero" -- the exact figure this fixture produces, pinned.
+
+        Previously the engine returned 0 for every market it fetched: `market.get('yes_ask', 0)` read a
+        key Kalshi stopped sending, so every price came back 0 and `if yes_ask == 0: continue` skipped
+        all of them. Pinning the exact number means a regression to zero fails here, and a large drift
+        fails as a NUMBER somebody has to look at rather than as a quiet change. The weather fixture is
+        the complete live 30-market snapshot, so its count is the real one. (The macro half of this test
+        went with the macro engine.)
         """
-        rows = _measure(monkeypatch, weather_markets, macro_markets)
-
-        by_engine: dict[str, list] = {}
-        for row in rows:
-            by_engine.setdefault(row["engine"], []).append(row)
-        assert len(by_engine["Weather"]) == FIXTURE_WEATHER_ROWS
-        assert len(by_engine["Macro"]) == FIXTURE_MACRO_ROWS
-        assert len(rows) == FIXTURE_WEATHER_ROWS + FIXTURE_MACRO_ROWS
+        rows = _measure(monkeypatch, weather_markets)
 
+        assert len(rows) == FIXTURE_WEATHER_ROWS
+        assert all(row["engine"] == "Weather" for row in rows)
         # Every row is measured, priced, and marked. The count going to zero is a regression to a
         # known defect, not a quiet market.
         assert all(row["market_price"] for row in rows)
@@ -647,46 +533,6 @@ class TestTheEnginesMeasureSomething:
         for key, value in measured["counts"].items():
             assert partition_quarantine(live_rows).counts()[key] == value, key
 
-    def test_a_market_the_engine_cannot_price_is_skipped_and_counted(self, macro_markets):
-        """110 of the 441 live economics markets quote no tradeable YES ask. They must be SKIPPED.
-
-        The engine tests `yes_ask is None`, not a falsy check, and that distinction is the whole
-        repair on the skip side. With a falsy check, normalising alone would hand these markets
-        `None` through to `edge = model_probability - yes_ask` and raise `TypeError` on each --
-        swallowed by `scan_real_edge` back to a zero, which is the pre-repair symptom wearing a new
-        cause. With the `is None` test they are skipped, and skipping an unpriceable market is the
-        honest move: there is no price to buy at, so there is no edge to compute.
-        """
-        from tradehub.markets import quote_cents
-
-        unpriceable = [m for m in macro_markets if quote_cents(m)["yes_ask"] is None]
-        assert unpriceable, "the fixture must contain markets with no tradeable quote"
-
-        from tradehub.engines.macro_engine import MacroEngine
-
-        engine = MacroEngine.__new__(MacroEngine)
-        engine._cache = {}
-        engine.get_latest_cpi_yoy = lambda: 3.1
-        engine.get_fed_rate_prediction = lambda: 3.75
-        engine.get_gdp_prediction = lambda: 1.9
-        engine.get_unemployment_rate = lambda: 4.4
-        engine.get_transition_penalty = lambda: {
-            "in_transition": False, "penalty": 0, "reasoning": "none"}
-        engine.get_leading_inflation_signals = lambda: {
-            "signal": "neutral", "adjustment": 0, "ppi_trend": "flat", "oil_trend": "flat",
-            "reasoning": "none"}
-        engine.get_tariff_shock_factor = lambda: {
-            "shock_detected": False, "multiplier": 1.0, "reasoning": "none"}
-        engine.get_taylor_rule_rate = lambda: {
-            "taylor_rate": None, "divergence": 0.0, "reasoning": "none"}
-
-        rows = engine.find_opportunities(macro_markets)
-
-        unpriceable_tickers = {m["ticker"] for m in unpriceable}
-        assert unpriceable_tickers.isdisjoint({r["market_ticker"] for r in rows})
-        # And no row carries the fabricated zero the pre-repair read produced.
-        assert all(r["market_price"] for r in rows), "a 0c price is a missing figure, not a quote"
-
 
 # ── 3. the artefacts are distinguished from the opportunities ───────────────────────────────
 
@@ -1081,7 +927,7 @@ class TestTheRulingIsNotStale:
         is caught by the same mechanism that caught this one.
         """
         for site in STOPPED_SITES:
-            if site.disposition != "repaired_quarantined":
+            if site.disposition != "repaired_quarantined" or site.module in DELETED_MODULES:
                 continue
             module, _, line = site.site.partition(":")
             assert module == site.module
```

- [ ] **Step 4: Run the re-pointed tests** (still before any deletion)

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_engine_health.py tests/test_weather_macro_quarantine.py tests/test_kalshi_quote_cents.py tests/test_env_hygiene.py -v`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add tests/legacy_ruling.py tests/test_legacy_daemon_gone.py tests/test_engine_health.py tests/test_weather_macro_quarantine.py tests/test_env_hygiene.py tests/test_kalshi_quote_cents.py
git commit -m "test: pin the quarantine state machine against a frozen ruling; retire tests of deleted code"
```

---

### Task 2: Delete the daemon and both engines, and make the live ruling true

**Files:**
- Delete: `tradehub/scripts/background_scanner.py`, `tradehub/engines/macro_engine.py`, `tradehub/engines/quant_engine.py`, `tradehub/core/discord_notifier.py`
- Modify: `tradehub/engine_health.py`, `tradehub/quarantine.py` (docstring), `tradehub/api/main.py` and `tradehub/api/dependencies.py` (comments), `tradehub/scripts/weather_auto_sell.py` and `tradehub/scripts/market_alerts.py` (docstrings), `README.md`, `SYSTEM_ARCH.md`, `pyproject.toml` (comment)

**Interfaces:**
- Produces: a live ruling with no `MacroEngine` site and `WeatherEngine.wired_to_a_scanner = False`, so `edge_type_state(...)` is `ran` for every edge type.

- [ ] **Step 1: Delete**

```bash
git rm tradehub/scripts/background_scanner.py tradehub/engines/macro_engine.py tradehub/engines/quant_engine.py tradehub/core/discord_notifier.py
```

- [ ] **Step 2: Update the ruling and the stale references**

```diff
diff --git a/README.md b/README.md
index 2b461cc..f1fc86a 100644
--- a/README.md
+++ b/README.md
@@ -10,7 +10,7 @@ A unified, production-grade Kalshi trading and analytics monorepo. The canonical
 
 Algo-Trade-Hub operates on a separated hybrid model to maximize VPS performance while delivering a lightning-fast React UI.
 
-1. **The Core Engines (VPS / Local):** Python data pipelines running on a continuous daemon (`background_scanner.py`). They pull from NWS, FRED, Kalshi, and Tiingo APIs, calculate mathematical edges, and write heavily normalized JSON data directly to a Supabase PostgreSQL database via a secure Service Role Key.
+1. **The Core Engines (VPS / Local):** Python data pipelines run as hourly systemd timers (`tradehub-scan`, `tradehub-settle`, `tradehub-journal`; the legacy continuous daemon `background_scanner.py` was deleted). They pull from NWS, FRED, Kalshi, and Tiingo APIs, calculate mathematical edges, and write heavily normalized JSON data directly to a Supabase PostgreSQL database via a secure Service Role Key.
 2. **The Terminal UI (Vercel):** A dynamic React frontend that acts as a read-only terminal dashboard. Built on modern Vite, it queries Supabase directly without relying on a continuously open Python FastAPI server, separating rendering limits from deep machine learning computation.
 
 ---
@@ -39,7 +39,7 @@ Ensure you have created a `.env` in the root mapping your API connections and `S
 uv venv .venv --python 3.12
 uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner
 .venv/bin/python -m pytest            # run from the repo root
-.venv/bin/python -m tradehub.scripts.background_scanner
+.venv/bin/python -m tradehub.scripts.scan
 ```
 
 ### 2. Launching the Frontend Dashboard (Local Dev)
diff --git a/SYSTEM_ARCH.md b/SYSTEM_ARCH.md
index ae29812..6ae2b40 100644
--- a/SYSTEM_ARCH.md
+++ b/SYSTEM_ARCH.md
@@ -25,12 +25,10 @@ Algo-Trade-Hub/                          ← Root monorepo (one git repo)
 │   │   ├── supabase_client.py           ← Unified Supabase write client (upsert_opportunities)
 │   │   └── ...
 │   ├── engines/                          ← Standalone specialized edge models
-│   │   ├── quant_engine.py              ← Paper trading ML engine (Crypto/SPX)
 │   │   ├── weather_engine.py            ← NWS → Kalshi weather arbitrage
-│   │   ├── macro_engine.py              ← FRED → Kalshi CPI/macro arbitrage
 │   │   └── weather_maker.py             ← Weather market-making helper
 │   ├── scripts/                          ← Operator scripts & daemons
-│   │   └── background_scanner.py        ← Central Daemon (runs all engines, pushes to Supabase)
+│   │   └── scan.py                      ← Hourly scan (weather, gas, CPI, labor, sports), suggest-only
 │   ├── api/                              ← FastAPI service (main.py, schemas.py, dependencies.py)
 │   └── config/                           ← settings.yaml
 │
@@ -70,9 +68,9 @@ The VPS focuses entirely on running heavy machine learning inference (LightGBM/F
 
 **Key Flow:**
 1. The hourly `tradehub-scan` timer runs `python -m tradehub.scripts.scan` (weather + gas, suggest-only).
-2. The scanner initializes specific engines (`weather_engine`, `macro_engine`, `quant_engine`). TSA/EIA engines now live as parked research under `research/engines` and are not run.
+2. The scan runs the pure engines in `tradehub/engines/` (weather, gas, CPI, labor) and the sports consumers. The legacy daemon and its macro and quant engines were deleted. TSA/EIA engines now live as parked research under `research/engines` and are not run.
 3. **Threshold-Free Discovery:** Engines ingest raw data and compute mathematical edges. Instead of filtering out low-edge markets, engines return *all* strictly tracked live markets (e.g., creating a massive grid of 100+ upcoming weather markets).
-4. **Dynamic Data Tagging:** The `background_scanner` assigns a strict `edge_type` string to the payload: `'WEATHER'`, `'MACRO'`, `'CRYPTO'`, or `'SPORTS'`.
+4. **Dynamic Data Tagging:** `scan.py` assigns a strict `edge_type` string to the payload: `'WEATHER'`, `'MACRO'`, `'CRYPTO'`, or `'SPORTS'`.
 5. **Supabase Injection:** `supabase_client.py` uses the `SUPABASE_SERVICE_ROLE_KEY` to securely `UPSERT` normalized records into the `kalshi_edges` database table.
 
 ### 2. The Database Bridge (Supabase)
diff --git a/pyproject.toml b/pyproject.toml
index 5165f45..1274ade 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -26,7 +26,8 @@ dependencies = [
 ]
 
 [project.optional-dependencies]
-# Heavier deps used only by tradehub.scripts.background_scanner's AI/news path and HF model downloads.
+# Heavier deps once used by the deleted background_scanner daemon's AI/news path and HF model downloads.
+# `google-genai` is still imported by tradehub/core/ai_validator.py; the rest are candidates for removal.
 scanner = [
     "fredapi>=0.5.1",
     "google-genai>=0.1.0",
diff --git a/tradehub/api/dependencies.py b/tradehub/api/dependencies.py
index d16f62f..7888e56 100644
--- a/tradehub/api/dependencies.py
+++ b/tradehub/api/dependencies.py
@@ -36,7 +36,8 @@ def get_supabase():
 
 
 # ─── In-memory scanner results cache ─────────────────────────────────────────
-# The background_scanner writes into this dict; the API reads from it.
+# Nothing populates this dict since the legacy background_scanner daemon was deleted; the API reads from it
+# and serves an empty list. Kept so the endpoint's contract is unchanged until it is retired on its own.
 # This avoids hammering Supabase on every API request.
 _scanner_cache: dict = {
     "opportunities": [],
diff --git a/tradehub/api/main.py b/tradehub/api/main.py
index ae169fe..74f3c0c 100644
--- a/tradehub/api/main.py
+++ b/tradehub/api/main.py
@@ -3,7 +3,7 @@ FastAPI Main — Thin API layer over the Kalshi Edge System.
 
 Does ZERO business logic — only queries Supabase or the in-memory
 scanner cache and returns typed JSON. All heavy lifting stays in the
-background_scanner.py and engine modules.
+the scan scripts and engine modules.
 
 Run locally:
     uvicorn api.main:app --reload --port 8000
@@ -304,7 +304,7 @@ async def get_opportunities(
 ):
     """
     Returns the latest scanner opportunities from the in-memory cache.
-    The background_scanner refreshes this every scan cycle.
+    Empty since the legacy background_scanner daemon was deleted: nothing refreshes this cache now.
     """
     opps = cache.get("opportunities", [])
     if engine:
diff --git a/tradehub/engine_health.py b/tradehub/engine_health.py
index 2d0f8e2..1affdf1 100644
--- a/tradehub/engine_health.py
+++ b/tradehub/engine_health.py
@@ -192,25 +192,17 @@ STOPPED_SITES: tuple[StoppedSite, ...] = (
         module="tradehub/engines/weather_engine.py",
         site="tradehub/engines/weather_engine.py:220",
         edge_type="WEATHER",
-        wired_to_a_scanner=True,
+        # False since the legacy daemon (`background_scanner.py`) was deleted: the only scanner that ran
+        # this class is gone, so it cannot be the reason the Weather board is empty or quarantined. The
+        # board is fed by `tradehub/scripts/scan.py` (the pure `engines/weather.py`). The class is still
+        # listed because `scripts/weather_auto_sell.py` calls it and it still prices against `yes_ask`.
+        wired_to_a_scanner=False,
         disposition="repaired_quarantined",
         reason=(
             "This is the Tier-1 real-edge weather engine, and it prices every market against "
             "`yes_ask`. " + _THE_API_MOVED + _REPAIRED_AND_QUARANTINED
         ),
     ),
-    StoppedSite(
-        name="MacroEngine",
-        module="tradehub/engines/macro_engine.py",
-        site="tradehub/engines/macro_engine.py:459",
-        edge_type="MACRO",
-        wired_to_a_scanner=True,
-        disposition="repaired_quarantined",
-        reason=(
-            "This is the Tier-1 real-edge macro engine, and it prices every market against "
-            "`yes_ask`. " + _THE_API_MOVED + _REPAIRED_AND_QUARANTINED
-        ),
-    ),
     StoppedSite(
         name="WeatherMaker",
         module="tradehub/engines/weather_maker.py",
diff --git a/tradehub/quarantine.py b/tradehub/quarantine.py
index ebe14dc..62e5210 100644
--- a/tradehub/quarantine.py
+++ b/tradehub/quarantine.py
@@ -20,8 +20,8 @@ this module is that **none of it is published**.
 output is measured and displayed, and not one row reaches `kalshi_edges`. Three independent things
 enforce it, because one would be a promise:
 
-  1. `tradehub/scripts/background_scanner.py::run_scan` never puts a quarantined row in the list it
-     hands to `upsert_opportunities`. The structural separation: the two lists are different objects
+  1. (Historical: the legacy daemon's `run_scan`, deleted with `macro_engine.py` and `quant_engine.py`, was the
+     only producer of quarantined rows, and it never put one in the list it handed to `upsert_opportunities`. The structural separation: the two lists are different objects
      and the quarantine one's only destination is the quarantine sink.
   2. `upsert_opportunities` DROPS any row carrying `QUARANTINE_FLAG`, so a future refactor that
      concatenates the two lists writes zero of them anyway. The flag is a poison pill, and it is set
diff --git a/tradehub/scripts/market_alerts.py b/tradehub/scripts/market_alerts.py
index 68154a2..884768c 100644
--- a/tradehub/scripts/market_alerts.py
+++ b/tradehub/scripts/market_alerts.py
@@ -7,7 +7,7 @@ Alerts:
   3. VIX Emergency: VIX > 45 → crisis-level fear
   4. Model Drift: Brier score exceeds threshold → retraining needed
 
-Called from background_scanner.py on each scan cycle.
+Legacy: was called by the deleted background_scanner.py; run by hand.
 """
 
 # The developer-local `.env` is loaded by the entrypoint, not at import time.
diff --git a/tradehub/scripts/weather_auto_sell.py b/tradehub/scripts/weather_auto_sell.py
index bb1bb4e..4312139 100644
--- a/tradehub/scripts/weather_auto_sell.py
+++ b/tradehub/scripts/weather_auto_sell.py
@@ -12,7 +12,7 @@ Rules:
   4. Settlement: Kalshi uses 6AM-6PM daily highs from NWS
 
 Usage:
-  Called from background_scanner.py on each scan cycle.
+  Legacy: was called by the deleted background_scanner.py; run it by hand.
 """
 
 import re
@@ -168,7 +168,7 @@ def evaluate_positions(positions, nws_forecasts):
 def run_auto_sell_check():
     """
     Main entry point: fetch positions + NWS data, evaluate, send Telegram alerts.
-    Called by background_scanner.py on each scan cycle.
+    Legacy: was called by the deleted background_scanner.py; run by hand.
 
     Returns:
         list of alerts that were sent (empty if no action)
```

- [ ] **Step 3: Run the guard and the whole suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_legacy_daemon_gone.py -v && SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider`
Expected: the 3 guard tests pass and the whole suite passes (reviewer baseline 1383).

- [ ] **Step 4: Commit**

```bash
git add -A tradehub README.md SYSTEM_ARCH.md pyproject.toml
git commit -m "cut: delete the legacy daemon, the macro and quant engines, and the discord notifier"
```

---

### Task 3: Verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on every file this plan created or changed: `.venv/bin/python -m ruff check <files>` → `All checks passed!` (pre-existing ruff debt elsewhere is not yours to fix here).
- [ ] In the PR body list the out-of-scope leftovers named in Global Constraints so Kevin can decide on them.
- [ ] Open the PR from a fresh branch off `main`. Body: what changed, the verification output, and whether a migration needs applying.

## Self-Review

- **Spec §9:** `macro_engine.py` and the `quant_engine.py` loader are deleted with their tests and references; the daemon that required both goes with them. Git history keeps all of it.
- **Spec §12:** the quarantine-safety tests are not deleted wholesale: the state machine, the partition rules, the artefact classification and the sink-refusal tests all still run. Only tests whose subject (the daemon's `run_scan`, `MacroEngine`) no longer exists were retired, and the two sink-level guarantees that remain are still asserted.
- **Truthfulness:** with the daemon gone nothing is wired to a ruled-against engine, so the live engine-health ruling reads `ran` for every board, which matches production (boards are fed by `scan.py`).
- **Type consistency:** `legacy_ruling.install` patches exactly the four module names the functions in `engine_health.py` read (`STOPPED_SITES`, `STOPPED_SITE_NAMES`, `WIRED_STOPPED_SITES`, `UNWIRED_STOPPED_SITES`).
