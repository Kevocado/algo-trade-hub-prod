# Step 6: `cpi_nowcast` Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a suggest-only, shadow `cpi_nowcast` engine. It predicts every open Kalshi KXCPI (headline MoM) and KXCPICORE (core MoM) market from the Cleveland Fed inflation nowcast. It writes those predictions and `MACRO` edges from the scan, and ships with a reproducible point-in-time backtest.

**Architecture:**
- **Data** (`tradehub/data/cleveland_fed.py`): one keyless JSON (`nowcast_month.json`) is parsed into per-month point-in-time observations. Each target month gets a daily nowcast path and the BLS first print ("Actual").
- **Model** (`tradehub/engines/cpi.py`, pure): the first print ~ Normal(latest nowcast known at decision time, σ). σ is the RMS error of the nowcast at the same horizon over the 24 most recent months whose print was already public. P(YES) = `prob_in_interval(μ, σ, yes_interval(m, 0.1))`.
- **Scan and backtest:** the scan gets a `scan_cpi` step with its own failure isolation. It runs at 08, 12 and 16 ET. The backtest CLI gets a `cpi_nowcast` branch that decides at 08:00 ET on release morning. Both write engine `cpi_nowcast`. The `engine_version` (`cpi-v1` headline, `cpi-core-v1` core) keeps the two in separate track records once step 2b lands.

**Tech Stack:** Python 3.12, requests (via `tradehub.backtest.http.default_get_json`), pytest, PyYAML. No new dependencies.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md): §3.1 (energy→inflation chain, `cpi_nowcast` row), §4 (pure engines, edge layer, predictions ledger), §5a (point-in-time backtest, leakage guard), §6 (gate: ≥50 settled contracts for monthly engines, Brier below market, positive P&L, calibration ≤10pp). Rollout tracker "Step 6" outline and handoff contract: [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md).

## Kevin's decisions (2026-09-25) — apply throughout

- **Losing engines still show their edges, labelled shadow (spec §6).** Never suppress or skip an edge because this engine's backtest or track record loses to the market.
  - Every edge row this plan writes carries `"engine": "cpi_nowcast"` and goes through `tradehub.scripts.scan.edge_row(...)`, which defaults `gate_status` to `"SHADOW"`.
  - `apply_gate_statuses` sets `PROMOTED` only for an engine whose gate passed. PR #4's follow-up changes it to key on each row's `engine`. Before that, it maps every non-WEATHER row to `gas`, which is wrong for this engine.
  - If `edge_row` has no `engine` argument yet when you start, stop and report. Don't work around it.
  - Add a test asserting that every edge this engine produces has `gate_status == "SHADOW"` when the gate lookup returns nothing.
  - The War Room shows a "Shadow" badge on these edges (PR #4 follow-up).
- **Deployment target is the VPS (step 5, [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md)), not Azure.**
  - The code ships in the one `ghcr.io/kevocado/tradehub` image: merge to `main`, then `.github/workflows/deploy-tradehub.yml` runs `ssh deploy@$VPS_HOST deploy tradehub <sha>`.
  - It runs inside the hourly `tradehub-scan` / `tradehub-settle` systemd timers (`/opt/stack/bin/tradehub-job scan|settle`). Runtime secrets live only in `/opt/stack/.env`.
  - Create no Azure resources, jobs or secrets.
  - **Azure is legacy.** The predictor sites still run there until the cutover (Azure for Students credit ends around **2026-10-27**). After that no Azure host exists, so nothing may depend on an `*.azurecontainerapps.io` URL beyond it.
  - `scan_cpi`'s 08/12/16 ET gate relies on the timer firing every hour at :05. The scan container reads the nowcast over the network on each gated run; there is no local cache volume.

## Global Constraints

- **Prerequisites:** PR #3 (backtesting suite) and PR #4 (data layer, weather/gas), both with their review fixes, plus step 2b (gate hardening), all merged to `main`. The patches below were produced against PR #4's head `31b66b1`. If a later fix changed the same lines and `git apply --3way` fails, make the change by hand. Each task's **Intent** says exactly what must hold. Lines most likely to need hand-merging:
  - `tradehub/scripts/scan.py` `main()`: PR #4's fix isolates failures per engine. Keep one try/except per engine, including `cpi_nowcast`, and keep the `cpi_scan_due` gate. If `edge_row` gains `gate_status`/`updated_at`/`expires_at`, `scan_cpi` passes through the same helper and needs no change.
  - `tradehub/scripts/backtest_engines.py` `main()` and `_histories`: PR #3/#4 fixes (walk-forward `label_available_at`, retry/backoff in `backtest/http.py`) don't change the CPI branch's logic. Re-apply the CPI hunks around them.
- **Engine name** written to `predictions.engine` is exactly `cpi_nowcast`. It must match `ENGINES` in `tradehub/scripts/settle_predictions.py`, which already lists `("cpi_nowcast", "monthly")`, so no change is needed there. Versions: `cpi-v1` (KXCPI), `cpi-core-v1` (KXCPICORE).
- **Edge type** is `MACRO`. Migration `20260416000005` allows `('WEATHER', 'MACRO', 'SPORTS', 'CRYPTO', 'ENERGY')`.
- **Keyless sources only:** Kalshi public API and `https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en`. No API keys, and nothing reads `.env`.
- **Tests never hit the network.** They use the recorded, trimmed fixtures under `tests/fixtures/`.
- **Test runs:** from the repo root, `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest ...`.
- **Applying patches:** save the diff block to the named file in `/tmp` and run `git apply --3way /tmp/<file>.patch` from the repo root.
- **Handoff contract** (rollout tracker):
  - branch `plan/2026-09-25-cpi-nowcast`, one commit per task;
  - every commit message ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - evidence report at `docs/superpowers/reports/2026-09-25-cpi-nowcast.md`;
  - never push.
- **Shadow only:** the engine suggests and never trades. Promotion is only through the §6 gate (≥50 settled contracts for `monthly`).

## Decisions and deviations from the tracker outline (read before implementing)

1. **No ALFRED in this step.** The outline listed "FRED CPI components (ALFRED vintages for the backtest)". Two findings replaced it with the Cleveland Fed's own "Actual CPI Inflation" series:
   - That series is the BLS first print. Rounded to one decimal, it equals Kalshi's settled value in **61 of 62** KXCPI months (2021-06 … 2026-08). The one miss is Nov 2025, the shutdown release with no Oct 2025 print.
   - `alfred.stlouisfed.org` was unreachable from the planning machine on 2026-09-25 (`HTTP/2 INTERNAL_ERROR`, or a timeout on HTTP/1.1, also outside the sandbox), so a keyless ALFRED source could not be recorded or verified.
   The existing keyed `AlfredSource` is untouched. Keyless ALFRED (`alfredgraph.csv?...&vintage_date=`) stays available for step 8.
2. **No gasoline residual term.** The Cleveland Fed nowcast is itself built from daily oil and weekly retail gasoline prices, so an AAA residual would double-count its main input. The only point-in-time AAA history is Kalshi's gas settlements, which is too short to fit walk-forward. If step 8 finds it useful, it can be tested as a follow-up.
3. **Publication timing (unverified upstream, so conservative):** the Cleveland Fed doesn't document when each day's value is published, or whether history is as-published.
   - A value labelled day L is treated as known from **00:00 ET on L+1**.
   - The first print is known from **08:30 ET on the release day**.
   - The backtest decides at **08:00 ET on release morning** (`close_time − 25 min`), so it uses the value labelled on the day before release.
   - The live scan uses the same rule, so live and backtest numbers are comparable.
4. **σ window = 24 months, no bias term.** This was chosen a priori, and the sweep in "Validation already done" backs it up: adding a mean-error bias made Brier worse in every variant. The config carries `train_months` and `use_bias`, so this can be retuned without code changes.
5. **Legacy markets:** Kalshi's KXCPI listing includes 330 legacy `CPI-*` markets (2021-06 … 2024), and 121 of them have no `strike_type`/`floor_strike`. `parse_cpi_market` infers `greater` and the strike from the ticker (`-T0.3`, `-TN0.4` = −0.4). Kalshi's `expiration_value` strings are inconsistent (`"0.4"`, `"0.40"`, `".9%"`), so the engine never reads them. Outcomes come from each market's `result`.
6. **Month-only event tickers:** `event_date()` can't parse `KXCPI-26AUG`, so a new `event_month()` reads `%y%b` from the first five characters. This also handles the stray real ticker `KXCPICORE-25DECT`.
7. **Backtest scoring set:** a CPI decision is scored only if the market had a quote at decision time. The gate's market Brier needs full coverage, and this keeps both Briers on the same contracts (461 of 508 settled KXCPI markets).
8. **Scan cadence:** the hourly timer calls `scan_cpi` only at 08, 12 and 16 ET (`cpi_scan_due`). 08:05 ET is the last run before the 08:25 ET release-day close. Other hours skip the 7.6 MB nowcast download.

## Validation already done (2026-09-25)

Every task below was applied exactly as written to a scratch worktree at `31b66b1`. Each RED step failed as stated and each GREEN step passed. After all tasks:
- **311 passed** (the 280 baseline tests plus 31 new);
- `ruff check --select F401,F811,F821 tradehub tests` passes.

**Live smoke (public sources, writes stubbed), 2026-09-25 06:18 UTC:**
- `scan_cpi` took **1.0 s** and produced **25 predictions** (14 KXCPI-26SEP + 11 KXCPICORE-26SEP) and **7 MACRO edges**. Later months (26OCT–26DEC) are open on Kalshi but have no nowcast yet, so they were correctly skipped.
- Inputs: headline nowcast 0.4997 (value labelled 2026-09-24), σ 0.136 from 24 months. Core nowcast 0.2017, σ 0.116.
- The market prices September much hotter than the nowcast. "More than 0.5%": ours 0.356 vs mid 0.635. "More than 0.4%": ours 0.642 vs mid 0.91. So every flagged edge is a NO. The backtest below says the market has been right more often than the nowcast, so these edges are exactly what shadow mode is for.
- The full `scan.main()` with stubbed Supabase took 3.2 s. The summary JSON included `"cpi_nowcast": {"predictions": 25, "edges": 7, "status": "ok"}`.

**Live backtests** (`python -m tradehub.scripts.backtest_engines --engine cpi_nowcast …`, taker mode, `min_edge_pct` 0, 1 contract, Kalshi historical and live tiers). The CLI was run through a small wrapper that retried HTTP 429s, because PR #3's retry/backoff fix isn't merged yet.

| Run | Contracts scored | Brier ours | Brier market | Fills | P&L after fees | Max DD | Gate |
|---|---|---|---|---|---|---|---|
| KXCPI, release morning (lead 0), 2021-06 … 2026-08 | 461 | 0.09877 | **0.07076** | 148 | **−$7.73** | $8.44 | SHADOW (Brier, P&L) |
| KXCPI, 7 days before (lead 7) | 433 | 0.10205 | **0.08204** | 205 | **+$4.26** | $5.24 | SHADOW (Brier) |
| KXCPICORE, release morning (lead 0) | 383 | 0.08410 | **0.07823** | 115 | **+$7.05** | $2.64 | SHADOW (Brier) |

**Reading:**
- The raw Cleveland nowcast is **worse than the market** on headline CPI at both horizons: 0.099 vs 0.071 Brier on release morning, and 0.102 vs 0.082 seven days out. The market already prices the nowcast plus the Street consensus.
- Headline P&L is −$7.73 on release morning. Seven days out it is +$4.26 over 205 one-contract fills, about 2¢ per fill, which is noise.
- Core comes closest: Brier 0.084 vs 0.078, with positive taker P&L. But +$7.05 over 115 one-contract fills is about 6¢ per fill, which is within noise, and the Brier criterion still fails.
- Both stay in **SHADOW**, as the §6 gate intends.
- Nowcast error, release morning (156 months, 2013-08 … 2026-08): RMS 0.149 pp, MAE 0.101 pp. 2021–22 were much worse (σ≈0.25), which is why a 24-month window beats the full history.

**Variant sweep** (KXCPI, lead 0, same 461 contracts, `min_edge_pct` 5). It justifies decision 4, and no setting beats the market:

| σ window | bias | Brier ours | P&L |
|---|---|---|---|
| 12 | off / on | 0.0977 / 0.1016 | −5.24 / −1.52 |
| **24** | **off** / on | **0.0988** / 0.1121 | −2.81 / −0.83 |
| 36 | off / on | 0.1016 / 0.1125 | −5.82 / −4.26 |
| 60 | off / on | 0.1049 / 0.1080 | −7.20 / −9.61 |
| all | off / on | 0.1018 / 0.1038 | −5.32 / −6.05 |

## Review Focus

- **Leakage:** a nowcast labelled L is only visible from 00:00 ET on L+1. A month's first print is only used in σ training after 08:30 ET on its release day. `build_cpi_decisions` attaches every observation it used (nowcast + training pairs) to `Decision.features`, so `check_no_lookahead` covers all of them.
- **`training_pairs`** measures past errors at the **same horizon** before close as the decision being made.
- **`scan_cpi`** never crashes the scan: `main()` wraps it, reports `status`, and still writes weather/gas.
- **KXCPICORE** markets have `cap_strike == floor_strike` on `greater` markets. `yes_interval` uses only `floor_strike` for `greater`, so they parse and price correctly.

---

## File Structure

- **Modify** `tradehub/markets.py`: `event_month`, `parse_cpi_market` (Task 1)
- **Create** `tests/fixtures/kalshi_cpi_markets_trimmed.json`, `tests/test_cpi_markets.py` (Task 1)
- **Create** `tradehub/data/cleveland_fed.py`: fetch and parse the nowcast into `MonthNowcast` (Task 2)
- **Create** `tests/fixtures/cleveland_nowcast_month_trimmed.json`, `tests/test_cleveland_fed.py` (Task 2)
- **Create** `tradehub/engines/cpi.py`: the pure model (Task 3)
- **Create** `tests/test_cpi_engine.py` (Task 3)
- **Modify** `tradehub/scripts/scan.py`: `cpi_scan_due`, `scan_cpi`, isolation in `main` (Task 4)
- **Modify** `tradehub/config/engines.yaml`: the `cpi_nowcast` block (Task 4)
- **Create** `tests/test_scan_cpi.py` (Task 4)
- **Modify** `tradehub/scripts/backtest_engines.py`: `CPI_DECISION_LEAD`, `build_cpi_decisions`, `_histories(lookback=)`, CLI branch (Task 5)
- **Create** `tests/test_backtest_cpi.py` (Task 5)
- **Modify** `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, row 6 (Task 6)
- **Create** `docs/superpowers/reports/2026-09-25-cpi-nowcast.md`: evidence report, written throughout (Task 6)

Setup (once): `git switch main && git switch -c plan/2026-09-25-cpi-nowcast`, then run `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q` and record the baseline count in the report.

---

## Task 1: Month-only CPI tickers and legacy strikes

**Intent:**
- `event_month("KXCPI-26AUG") == date(2026, 8, 1)`. It works for legacy `CPI-22NOV` and for `KXCPICORE-25DECT`.
- `parse_cpi_market` returns `parse_market(raw)` unchanged when the raw has `strike_type` and `floor_strike`. Otherwise it infers `greater` and the strike from the `-T<x>` / `-TN<x>` suffix, and raises `ValueError` for any other suffix.
- `parse_market`, `event_date` and `yes_interval` are unchanged.

**Files:**
- Modify: `tradehub/markets.py` (after `event_date`)
- Create: `tests/fixtures/kalshi_cpi_markets_trimmed.json`, `tests/test_cpi_markets.py`

**Interfaces:**
- Consumes: `parse_market(raw) -> KalshiMarket`, `yes_interval(market, resolution)`, `prob_in_interval(mu, sigma, interval)` (existing).
- Produces: `event_month(event_ticker: str) -> date` (first of month); `parse_cpi_market(raw: dict) -> KalshiMarket`.

- [ ] **Step 1: Write the fixture and the failing test**

`tests/fixtures/kalshi_cpi_markets_trimmed.json` (real Kalshi responses from 2026-09-25, trimmed to the fields used):

```json
[
 {"ticker": "KXCPI-26AUG-T0.3", "event_ticker": "KXCPI-26AUG", "strike_type": "greater", "floor_strike": 0.3, "open_time": "2026-02-20T15:00:00Z", "close_time": "2026-09-11T12:25:00Z", "title": "Will CPI rise more than 0.3% in August 2026?", "result": "yes", "expiration_value": "0.4", "settlement_ts": "2026-09-11T13:28:53.706257Z", "status": "finalized"},
 {"ticker": "KXCPI-26AUG-T0.4", "event_ticker": "KXCPI-26AUG", "strike_type": "greater", "floor_strike": 0.4, "open_time": "2026-02-20T15:00:00Z", "close_time": "2026-09-11T12:25:00Z", "title": "Will CPI rise more than 0.4% in August 2026?", "result": "no", "expiration_value": "0.4", "settlement_ts": "2026-09-11T13:28:53.706257Z", "status": "finalized"},
 {"ticker": "CPI-22AUG-TN0.4", "event_ticker": "CPI-22AUG", "open_time": "2022-09-06T18:25:00Z", "close_time": "2022-09-13T12:25:00Z", "title": "Will inflation rise more than -0.4% in August?", "result": "yes", "expiration_value": "0.1", "settlement_ts": "2022-09-13T17:11:00.3987Z", "status": "finalized"},
 {"ticker": "CPI-21JUN-T0.6", "event_ticker": "CPI-21JUN", "open_time": "2021-06-30T14:00:00Z", "close_time": "2021-07-12T23:00:00Z", "title": "Will the Consumer Price Index (CPI) increase more than 0.6%?", "result": "yes", "expiration_value": ".9%", "settlement_ts": "2021-07-15T18:20:00.557302Z", "status": "finalized"},
 {"ticker": "KXCPICORE-26SEP-T0.3", "event_ticker": "KXCPICORE-26SEP", "strike_type": "greater", "floor_strike": 0.3, "cap_strike": 0.3, "open_time": "2026-06-10T19:50:00Z", "close_time": "2026-10-14T12:25:00Z", "title": "Will CPI Core rise more than 0.3% in September?", "result": "", "expiration_value": "", "status": "active"}
]
```

`tests/test_cpi_markets.py`:

```python
import json
import math
from datetime import date
from pathlib import Path

import pytest

from tradehub.markets import event_month, parse_cpi_market, prob_in_interval, yes_interval

RAWS = {r["ticker"]: r for r in json.loads(
    (Path(__file__).parent / "fixtures" / "kalshi_cpi_markets_trimmed.json").read_text(encoding="utf-8"))}


def test_event_month_parses_month_only_tickers():
    assert event_month("KXCPI-26AUG") == date(2026, 8, 1)
    assert event_month("CPI-21DEC") == date(2021, 12, 1)
    assert event_month("KXCPICORE-26SEP") == date(2026, 9, 1)
    assert event_month("KXCPICORE-25DECT") == date(2025, 12, 1)  # real settled event ticker


def test_parse_cpi_market_keeps_modern_strikes():
    m = parse_cpi_market(RAWS["KXCPI-26AUG-T0.4"])
    assert m.strike_type == "greater" and m.floor_strike == pytest.approx(0.4)
    assert m.series_ticker == "KXCPI"
    lo, hi = yes_interval(m, 0.1)
    assert lo == pytest.approx(0.45) and hi == math.inf  # YES iff the one-decimal print is >= 0.5


def test_parse_cpi_market_infers_legacy_strikes_from_ticker():
    neg = parse_cpi_market(RAWS["CPI-22AUG-TN0.4"])
    pos = parse_cpi_market(RAWS["CPI-21JUN-T0.6"])
    assert neg.strike_type == "greater" and neg.floor_strike == pytest.approx(-0.4)
    assert pos.floor_strike == pytest.approx(0.6) and pos.series_ticker == "CPI"


def test_core_greater_market_with_cap_equal_floor_is_accepted():
    m = parse_cpi_market(RAWS["KXCPICORE-26SEP-T0.3"])
    assert m.cap_strike == pytest.approx(0.3)
    assert yes_interval(m, 0.1)[0] == pytest.approx(0.35)
    assert 0.0 < prob_in_interval(0.3, 0.1, yes_interval(m, 0.1)) < 0.5


def test_settled_results_agree_with_the_one_decimal_rule():
    # Aug 2026 printed 0.4: "more than 0.3" is YES, "more than 0.4" is NO.
    for ticker, expected in (("KXCPI-26AUG-T0.3", "yes"), ("KXCPI-26AUG-T0.4", "no")):
        lo, _ = yes_interval(parse_cpi_market(RAWS[ticker]), 0.1)
        assert ("yes" if 0.4 > lo else "no") == RAWS[ticker]["result"] == expected


def test_parse_cpi_market_rejects_unparseable_tickers():
    with pytest.raises(ValueError):
        parse_cpi_market(dict(RAWS["CPI-21JUN-T0.6"], ticker="CPI-21JUN-B0.6"))
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cpi_markets.py -q`
Expected: collection error, `ImportError: cannot import name 'event_month' from 'tradehub.markets'` (`1 error`).

- [ ] **Step 3: Implement.** Save as `/tmp/cpi-t1.patch`, then `git apply --3way /tmp/cpi-t1.patch`:

```diff
diff --git a/tradehub/markets.py b/tradehub/markets.py
index 7cd89a4..edd4aa1 100644
--- a/tradehub/markets.py
+++ b/tradehub/markets.py
@@ -47,6 +47,29 @@ def event_date(event_ticker: str) -> date:
     return datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()


+def event_month(event_ticker: str) -> date:
+    """Monthly-release events: 'KXCPI-26AUG' (and legacy 'CPI-22NOV') -> first day of that month.
+
+    Only the first five characters are read: Kalshi has at least one stray suffix ('KXCPICORE-25DECT').
+    """
+    return datetime.strptime(event_ticker.split("-")[1][:5], "%y%b").date()
+
+
+def parse_cpi_market(raw: dict[str, Any]) -> KalshiMarket:
+    """parse_market for CPI ladders, including legacy 'CPI-*' markets that carry no strike fields.
+
+    Every CPI market is 'more than X%' on the one-decimal BLS value; legacy tickers
+    encode X as '-T0.3', or '-TN0.4' for -0.4.
+    """
+    if raw.get("strike_type") and raw.get("floor_strike") is not None:
+        return parse_market(raw)
+    suffix = raw["ticker"].rsplit("-", 1)[1]
+    if not suffix.startswith("T"):
+        raise ValueError(f"cannot infer strike from {raw['ticker']!r}")
+    strike = -float(suffix[2:]) if suffix.startswith("TN") else float(suffix[1:])
+    return parse_market(dict(raw, strike_type="greater", floor_strike=strike, cap_strike=None))
+
+
 def yes_interval(market: KalshiMarket, resolution: float) -> tuple[float, float]:
     """Continuous interval of the settled value for which the market resolves YES.

```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cpi_markets.py tests/test_markets.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/markets.py tests/test_cpi_markets.py tests/fixtures/kalshi_cpi_markets_trimmed.json
git commit -m "feat: parse month-only and legacy Kalshi CPI markets

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Cleveland Fed nowcast as point-in-time observations

**Intent:**
- `parse_nowcast_month(payload, kind)` turns the FusionCharts payload into `{first-of-month: MonthNowcast}`.
- Series data lines up with the **non-vline** categories only.
- An `MM/DD` label whose month is below the target month belongs to the next year (December → January rollover).
- Empty values are skipped.
- Path observation: `name "CPI:2026-08@2026-09-10"`, `published_at` = 00:00 ET the next day.
- Actual observation: `name "CPI:2026-08:actual"`, `published_at` = 08:30 ET on its label day. A month with no print has `actual=None`.
- `kind="core"` reads "Core CPI Inflation" / "Actual Core CPI Inflation", with prefix `CORECPI`.
- `fetch_nowcast_history(kind, get_json)` makes exactly one `get_json(NOWCAST_MONTH_URL)` call.

**Files:**
- Create: `tradehub/data/cleveland_fed.py`
- Create: `tests/fixtures/cleveland_nowcast_month_trimmed.json`, `tests/test_cleveland_fed.py`

**Interfaces:**
- Consumes: `tradehub.backtest.pit.Observation(name, value, published_at)`, `tradehub.backtest.http.default_get_json(url, params=None)`.
- Produces: `MonthNowcast(month: date, path: tuple[Observation, ...], actual: Observation | None)` (path sorted by `published_at`); `parse_nowcast_month(payload: list[dict], kind: str = "headline") -> dict[date, MonthNowcast]`; `fetch_nowcast_history(kind: str = "headline", get_json=default_get_json) -> dict[date, MonthNowcast]`; `NOWCAST_MONTH_URL`.

- [ ] **Step 1: Write the fixture and the failing test**

`tests/fixtures/cleveland_nowcast_month_trimmed.json` is the real `nowcast_month.json` from 2026-09-25, trimmed:
- to target months 2021-12 (year rollover), 2025-10 (no print, shutdown) and 2026-8 (printed 0.396);
- to a few category labels (vlines kept);
- to five of the eight series, with `tooltext`/`color` dropped.

```json
[
 {
  "chart": {"_comment": "2026-09-24 00:00", "caption": "Inflation Nowcasting", "subcaption": "2021-12", "yaxisname": "Month-over-month percent change"},
  "categories": [{"category": [{"label": "12/01"}, {"label": "12/10"}, {"label": "CPI Nov", "vline": "true"}, {"label": "12/31"}, {"label": "01/11"}, {"label": "01/12"}, {"label": "CPI Dec", "vline": "true"}, {"label": "01/13"}]}],
  "dataset": [
   {"seriesname": "CPI Inflation", "data": [{"value": "0.135092008807369"}, {"value": "0.420285410429762"}, {"value": "0.388985413110369"}, {"value": "0.388985413110369"}, {"value": ""}, {"value": ""}]},
   {"seriesname": "Core CPI Inflation", "data": [{"value": "0.391334142249688"}, {"value": "0.404667075043658"}, {"value": "0.404667075043658"}, {"value": "0.404667075043658"}, {"value": ""}, {"value": ""}]},
   {"seriesname": "PCE Inflation", "data": [{"value": "0.215716068609123"}, {"value": "0.378713276235002"}, {"value": "0.369967901607565"}, {"value": "0.369967901607565"}, {"value": "0.379818997142973"}, {"value": "0.379818997142973"}]},
   {"seriesname": "Actual CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": ""}, {"value": ""}, {"value": "0.470453241537583"}, {"value": ""}]},
   {"seriesname": "Actual Core CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": ""}, {"value": ""}, {"value": "0.550139300355568"}, {"value": ""}]}
  ]
 },
 {
  "chart": {"_comment": "2026-09-24 00:00", "caption": "Inflation Nowcasting", "subcaption": "2025-10", "yaxisname": "Month-over-month percent change"},
  "categories": [{"category": [{"label": "10/01"}, {"label": "12/17"}, {"label": "12/18"}, {"label": "CPI Nov", "vline": "true"}]}],
  "dataset": [
   {"seriesname": "CPI Inflation", "data": [{"value": "0.198552626727325"}, {"value": "0.183254751516416"}, {"value": ""}]},
   {"seriesname": "Core CPI Inflation", "data": [{"value": "0.251132146717158"}, {"value": "0.248744105819295"}, {"value": ""}]},
   {"seriesname": "PCE Inflation", "data": [{"value": "0.198079893921763"}, {"value": "0.187752977774929"}, {"value": "0.179281309437696"}]},
   {"seriesname": "Actual CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": ""}]},
   {"seriesname": "Actual Core CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": ""}]}
  ]
 },
 {
  "chart": {"_comment": "2026-09-24 00:00", "caption": "Inflation Nowcasting", "subcaption": "2026-8", "yaxisname": "Month-over-month percent change"},
  "categories": [{"category": [{"label": "08/03"}, {"label": "09/10"}, {"label": "09/11"}, {"label": "CPI Aug", "vline": "true"}, {"label": "09/14"}]}],
  "dataset": [
   {"seriesname": "CPI Inflation", "data": [{"value": "0.320941031024802"}, {"value": "0.359180537639179"}, {"value": ""}, {"value": ""}]},
   {"seriesname": "Core CPI Inflation", "data": [{"value": "0.203008223327511"}, {"value": "0.203341742698412"}, {"value": ""}, {"value": ""}]},
   {"seriesname": "PCE Inflation", "data": [{"value": "0.329204026425306"}, {"value": "0.35365703803959"}, {"value": "0.342798456247959"}, {"value": "0.342798456247959"}]},
   {"seriesname": "Actual CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": "0.396018184385816"}, {"value": ""}]},
   {"seriesname": "Actual Core CPI Inflation", "data": [{"value": ""}, {"value": ""}, {"value": "0.289795688101457"}, {"value": ""}]}
  ]
 }
]
```

`tests/test_cleveland_fed.py`:

```python
import json
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.cleveland_fed import NOWCAST_MONTH_URL, fetch_nowcast_history, parse_nowcast_month

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))


def test_parse_headline_path_and_actual():
    history = parse_nowcast_month(PAYLOAD)
    aug = history[date(2026, 8, 1)]
    assert [o.name for o in aug.path] == ["CPI:2026-08@2026-08-03", "CPI:2026-08@2026-09-10"]
    assert aug.path[-1].value == pytest.approx(0.359180537639179)
    # A value labelled Sep 10 is usable from 00:00 ET Sep 11 (04:00 UTC in EDT).
    assert aug.path[-1].published_at == datetime(2026, 9, 11, 4, 0, tzinfo=timezone.utc)
    assert aug.actual.name == "CPI:2026-08:actual"
    assert aug.actual.value == pytest.approx(0.396018184385816)
    assert aug.actual.published_at == datetime(2026, 9, 11, 12, 30, tzinfo=timezone.utc)  # 08:30 EDT


def test_vline_categories_do_not_shift_the_data():
    dec = parse_nowcast_month(PAYLOAD)[date(2021, 12, 1)]
    by_name = {o.name: o.value for o in dec.path}
    assert by_name["CPI:2021-12@2021-12-31"] == pytest.approx(0.388985413110369)  # after the "CPI Nov" vline
    assert dec.actual.value == pytest.approx(0.470453241537583)


def test_december_labels_roll_into_the_next_year():
    dec = parse_nowcast_month(PAYLOAD)[date(2021, 12, 1)]
    assert dec.path[-1].name == "CPI:2021-12@2022-01-11"
    assert dec.actual.published_at == datetime(2022, 1, 12, 13, 30, tzinfo=timezone.utc)  # 08:30 EST


def test_month_without_a_release_has_no_actual():
    oct25 = parse_nowcast_month(PAYLOAD)[date(2025, 10, 1)]  # Oct 2025 CPI was never published (shutdown)
    assert oct25.actual is None
    assert oct25.path[-1].name == "CPI:2025-10@2025-12-17"


def test_core_series():
    aug = parse_nowcast_month(PAYLOAD, "core")[date(2026, 8, 1)]
    assert aug.path[-1].name == "CORECPI:2026-08@2026-09-10"
    assert aug.path[-1].value == pytest.approx(0.203341742698412)
    assert aug.actual.value == pytest.approx(0.289795688101457)


def test_fetch_uses_the_keyless_json_url():
    calls = []

    def get_json(url, params=None):
        calls.append((url, params))
        return PAYLOAD

    history = fetch_nowcast_history(get_json=get_json)
    assert calls == [(NOWCAST_MONTH_URL, None)]
    assert set(history) == {date(2021, 12, 1), date(2025, 10, 1), date(2026, 8, 1)}
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cleveland_fed.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tradehub.data.cleveland_fed'`.

- [ ] **Step 3: Implement** `tradehub/data/cleveland_fed.py`:

```python
"""Cleveland Fed inflation nowcast (keyless) as point-in-time observations.

nowcast_month.json is a FusionCharts payload: one entry per target month
(chart.subcaption "2026-8"), daily "MM/DD" category labels without a year,
plus "vline" categories (release markers) that carry no data point. Each
series' data list lines up with the non-vline categories.

Timing rules (the publish time of each daily value is not documented):
- a nowcast labelled day L is treated as known from 00:00 ET on L+1;
- the "Actual" value sits on the BLS release day R and is known from 08:30 ET on R.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from tradehub.backtest.http import default_get_json
from tradehub.backtest.pit import Observation

NOWCAST_MONTH_URL = (
    "https://www.clevelandfed.org/-/media/files/webcharts/inflationnowcasting/nowcast_month.json?sc_lang=en"
)
ET = ZoneInfo("America/New_York")
BLS_RELEASE_TIME = time(8, 30)
SERIES = {
    "headline": ("CPI", "CPI Inflation", "Actual CPI Inflation"),
    "core": ("CORECPI", "Core CPI Inflation", "Actual Core CPI Inflation"),
}


@dataclass(frozen=True)
class MonthNowcast:
    month: date
    path: tuple[Observation, ...]
    actual: Observation | None


def _label_date(label: str, month: date) -> date:
    mm, dd = (int(part) for part in label.split("/"))
    year = month.year if mm >= month.month else month.year + 1
    return date(year, mm, dd)


def _value(point: dict[str, Any]) -> float | None:
    raw = point.get("value")
    return None if raw in (None, "") else float(raw)


def parse_nowcast_month(payload: list[dict[str, Any]], kind: str = "headline") -> dict[date, MonthNowcast]:
    prefix, nowcast_name, actual_name = SERIES[kind]
    out: dict[date, MonthNowcast] = {}
    for entry in payload:
        year, mon = (int(part) for part in entry["chart"]["subcaption"].split("-"))
        month = date(year, mon, 1)
        labels = [c["label"] for c in entry["categories"][0]["category"] if not c.get("vline")]
        series = {s["seriesname"]: s["data"] for s in entry["dataset"]}
        tag = f"{prefix}:{month:%Y-%m}"
        path = []
        for label, point in zip(labels, series.get(nowcast_name, [])):
            value = _value(point)
            if value is None:
                continue
            day = _label_date(label, month)
            known = datetime.combine(day + timedelta(days=1), time(0), ET).astimezone(timezone.utc)
            path.append(Observation(f"{tag}@{day.isoformat()}", value, known))
        actual = None
        for label, point in zip(labels, series.get(actual_name, [])):
            value = _value(point)
            if value is not None:
                released = datetime.combine(_label_date(label, month), BLS_RELEASE_TIME, ET).astimezone(timezone.utc)
                actual = Observation(f"{tag}:actual", value, released)
                break
        out[month] = MonthNowcast(month, tuple(sorted(path, key=lambda o: o.published_at)), actual)
    return out


def fetch_nowcast_history(
    kind: str = "headline", get_json: Callable[..., Any] = default_get_json
) -> dict[date, MonthNowcast]:
    return parse_nowcast_month(get_json(NOWCAST_MONTH_URL), kind)
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cleveland_fed.py -q`
Expected: `6 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/data/cleveland_fed.py tests/test_cleveland_fed.py tests/fixtures/cleveland_nowcast_month_trimmed.json
git commit -m "feat: parse the Cleveland Fed CPI nowcast into point-in-time observations

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: The pure CPI model

**Intent:**
- `latest_nowcast` is the newest path observation with `published_at <= as_of`, or `None`.
- `training_pairs(history, as_of, horizon)` returns `(nowcast, actual)` pairs for months whose actual was published by `as_of`, oldest first. The nowcast is the one known at `actual.published_at − 5 min − horizon`, the same distance before that month's close.
- `fit_cpi_error` uses the last `window` pairs, and falls back to `DEFAULT_CPI_ERROR` (0, 0.15) under 12 pairs. It computes σ as the RMS error around 0, or the population SD around the mean when `use_bias`, floored at 0.05.
- `cpi_prob` = `prob_in_interval(nowcast + bias, σ, yes_interval(m, 0.1))`.

**Files:**
- Create: `tradehub/engines/cpi.py`
- Create: `tests/test_cpi_engine.py`

**Interfaces:**
- Consumes: `MonthNowcast` (Task 2), `parse_cpi_market` (Task 1), `prob_in_interval`, `yes_interval`.
- Produces: `CPI_ENGINE_VERSION = "cpi-v1"`, `CPI_CORE_ENGINE_VERSION = "cpi-core-v1"`, `CPI_SERIES = "KXCPI"`, `CPI_TARGETS: dict[str, tuple[str, str]]` (series → (kind, version)), `CPI_TRAIN_MONTHS = 24`, `CpiErrorModel(bias, sigma)`, `DEFAULT_CPI_ERROR`, `MIN_CPI_SIGMA`, `latest_nowcast(month: MonthNowcast | None, as_of) -> Observation | None`, `training_pairs(history, as_of, horizon: timedelta) -> list[tuple[Observation, Observation]]`, `fit_cpi_error(pairs, *, window=24, min_points=12, use_bias=False) -> CpiErrorModel`, `cpi_prob(market, nowcast: float, model) -> float`.

- [ ] **Step 1: Write the failing test** `tests/test_cpi_engine.py`:

```python
from datetime import date, datetime, timedelta, timezone

import pytest

from tradehub.backtest.pit import Observation
from tradehub.data.cleveland_fed import MonthNowcast
from tradehub.engines.cpi import (
    CPI_TARGETS,
    DEFAULT_CPI_ERROR,
    MIN_CPI_SIGMA,
    CpiErrorModel,
    cpi_prob,
    fit_cpi_error,
    latest_nowcast,
    training_pairs,
)
from tradehub.markets import parse_cpi_market

UTC = timezone.utc


def _month(year, mon, nowcast, actual, release_day=12):
    """A month whose nowcast is known from the 1st and 10th of the next month, printed on `release_day`."""
    month = date(year, mon, 1)
    nxt = date(year + (mon == 12), mon % 12 + 1, 1)
    tag = f"CPI:{month:%Y-%m}"
    path = (
        Observation(f"{tag}@a", nowcast - 0.2, datetime(nxt.year, nxt.month, 1, 4, tzinfo=UTC)),
        Observation(f"{tag}@b", nowcast, datetime(nxt.year, nxt.month, 10, 4, tzinfo=UTC)),
    )
    released = datetime(nxt.year, nxt.month, release_day, 12, 30, tzinfo=UTC)
    return MonthNowcast(month, path, None if actual is None else Observation(f"{tag}:actual", actual, released))


def _market(strike, event="KXCPI-26AUG", close="2026-09-11T12:25:00Z"):
    return parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                             "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                             "title": "CPI"})


def test_targets_cover_headline_and_core():
    assert CPI_TARGETS == {"KXCPI": ("headline", "cpi-v1"), "KXCPICORE": ("core", "cpi-core-v1")}


def test_latest_nowcast_respects_publication_time():
    m = _month(2026, 8, 0.36, 0.40)
    assert latest_nowcast(m, datetime(2026, 9, 5, tzinfo=UTC)).name == "CPI:2026-08@a"
    assert latest_nowcast(m, datetime(2026, 9, 11, tzinfo=UTC)).name == "CPI:2026-08@b"
    assert latest_nowcast(m, datetime(2026, 8, 20, tzinfo=UTC)) is None
    assert latest_nowcast(None, datetime(2026, 9, 11, tzinfo=UTC)) is None


def test_training_pairs_only_use_released_months_at_the_same_horizon():
    history = {m.month: m for m in (_month(2026, 6, 0.20, 0.30), _month(2026, 7, 0.10, 0.10),
                                    _month(2026, 8, 0.36, 0.40))}
    as_of = datetime(2026, 9, 1, tzinfo=UTC)  # July printed Aug 12; August not printed yet
    pairs = training_pairs(history, as_of, timedelta(minutes=25))
    assert [a.name for _, a in pairs] == ["CPI:2026-06:actual", "CPI:2026-07:actual"]
    assert all(n.published_at <= as_of and a.published_at <= as_of for n, a in pairs)
    assert [n.name for n, _ in pairs] == ["CPI:2026-06@b", "CPI:2026-07@b"]
    # Five days before release, only the early nowcast ("@a", known on the 1st) was available.
    early = training_pairs(history, as_of, timedelta(days=5))
    assert [n.name for n, _ in early] == ["CPI:2026-06@a", "CPI:2026-07@a"]


def _pairs(errors):
    out = []
    for i, err in enumerate(errors):
        t = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(days=31 * i)
        out.append((Observation(f"n{i}", 0.2, t), Observation(f"a{i}", 0.2 + err, t + timedelta(days=1))))
    return out


def test_fit_defaults_until_enough_history():
    assert fit_cpi_error(_pairs([0.1] * 11)) == DEFAULT_CPI_ERROR


def test_fit_is_rms_error_without_bias_and_uses_the_recent_window():
    model = fit_cpi_error(_pairs([0.5] * 10 + [0.1, -0.1] * 12), window=24)
    assert model.bias == 0.0
    assert model.sigma == pytest.approx(0.1)  # the ten old 0.5 errors fall outside the window
    biased = fit_cpi_error(_pairs([0.2, 0.0] * 12), use_bias=True)
    assert biased.bias == pytest.approx(0.1) and biased.sigma == pytest.approx(0.1)


def test_fit_floors_sigma():
    assert fit_cpi_error(_pairs([0.0] * 24)).sigma == MIN_CPI_SIGMA


def test_cpi_prob_uses_one_decimal_thresholds():
    model = CpiErrorModel(bias=0.0, sigma=0.1)
    # "more than 0.3" is YES iff the print rounds to >= 0.4, i.e. unrounded > 0.35.
    assert cpi_prob(_market(0.3), 0.35, model) == pytest.approx(0.5)
    assert cpi_prob(_market(0.4), 0.36, model) < 0.2
    assert cpi_prob(_market(-0.4), 0.36, model) > 0.999
    assert cpi_prob(_market(0.3), 0.30, CpiErrorModel(bias=0.05, sigma=0.1)) == pytest.approx(0.5)
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cpi_engine.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tradehub.engines.cpi'`.

- [ ] **Step 3: Implement** `tradehub/engines/cpi.py`:

```python
"""CPI nowcast engine (pure): P(Kalshi KXCPI / KXCPICORE 'more than X%' resolves YES).

The first-print MoM change ~ Normal(latest Cleveland Fed nowcast + bias, sigma), with
bias/sigma fit on past (nowcast at the same horizon before release, first print) pairs,
using only months whose print was public at decision time.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Mapping

from tradehub.backtest.pit import Observation
from tradehub.data.cleveland_fed import MonthNowcast
from tradehub.markets import KalshiMarket, prob_in_interval, yes_interval

CPI_ENGINE_VERSION = "cpi-v1"
CPI_CORE_ENGINE_VERSION = "cpi-core-v1"
CPI_SERIES = "KXCPI"
# Kalshi series -> (Cleveland Fed series kind, engine_version). Both write engine "cpi_nowcast";
# the version keeps headline and core in separate track records (step 2b keys on engine_version).
CPI_TARGETS = {"KXCPI": ("headline", CPI_ENGINE_VERSION), "KXCPICORE": ("core", CPI_CORE_ENGINE_VERSION)}
CPI_RESOLUTION = 0.1
CLOSE_TO_RELEASE = timedelta(minutes=5)  # Kalshi closes 08:25 ET, BLS publishes 08:30 ET
MIN_CPI_SIGMA = 0.05
CPI_TRAIN_MONTHS = 24
CPI_MIN_TRAIN = 12


@dataclass(frozen=True)
class CpiErrorModel:
    bias: float
    sigma: float


DEFAULT_CPI_ERROR = CpiErrorModel(bias=0.0, sigma=0.15)


def latest_nowcast(month: MonthNowcast | None, as_of: datetime) -> Observation | None:
    if month is None:
        return None
    known = [o for o in month.path if o.published_at <= as_of]
    return known[-1] if known else None


def training_pairs(
    history: Mapping[date, MonthNowcast], as_of: datetime, horizon: timedelta
) -> list[tuple[Observation, Observation]]:
    """(nowcast, first print) for every month released by `as_of`.

    The nowcast is the one known `horizon` before that month's market close, so the
    error distribution matches the horizon of the decision being made.
    """
    pairs = []
    for month in history.values():
        actual = month.actual
        if actual is None or actual.published_at > as_of:
            continue
        nowcast = latest_nowcast(month, actual.published_at - CLOSE_TO_RELEASE - horizon)
        if nowcast is not None:
            pairs.append((nowcast, actual))
    return sorted(pairs, key=lambda pair: pair[1].published_at)


def fit_cpi_error(
    pairs: list[tuple[Observation, Observation]],
    *,
    window: int = CPI_TRAIN_MONTHS,
    min_points: int = CPI_MIN_TRAIN,
    use_bias: bool = False,
) -> CpiErrorModel:
    recent = pairs[-window:]
    if len(recent) < min_points:
        return DEFAULT_CPI_ERROR
    errors = [actual.value - nowcast.value for nowcast, actual in recent]
    bias = statistics.fmean(errors) if use_bias else 0.0
    sigma = statistics.pstdev(errors, mu=bias)
    return CpiErrorModel(bias=bias, sigma=max(MIN_CPI_SIGMA, sigma))


def cpi_prob(market: KalshiMarket, nowcast: float, model: CpiErrorModel) -> float:
    return prob_in_interval(nowcast + model.bias, model.sigma, yes_interval(market, CPI_RESOLUTION))
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_cpi_engine.py -q`
Expected: `7 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/engines/cpi.py tests/test_cpi_engine.py
git commit -m "feat: add the cpi_nowcast model (nowcast + walk-forward error sigma)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Scan wiring, config, failure isolation

**Intent:**
- `scan_cpi(live, now, cfg, *, nowcast_fn, targets)` loops over `CPI_TARGETS`. It fetches the nowcast (once per series, and only if that series has open markets) and predicts every open market whose month has a nowcast and whose close is in the future.
- Every market gets a prediction row: engine `cpi_nowcast`, the target's version, and `raw_payload` holding nowcast, source obs, bias, σ, n_train and hours_to_close.
- Edges come from `evaluate_edge` as `edge_type "MACRO"`.
- `main()` runs it only when `cpi_scan_due(now)` (ET hour in 8/12/16), inside try/except. A failure becomes `"status": "error: ..."` in the summary, and weather/gas are still written.
- `engines.yaml` gains `cpi_nowcast` (`min_edge_pct` 5.0, `prefer_maker` true, `train_months` 24, `use_bias` 0).

**Files:**
- Modify: `tradehub/scripts/scan.py`, `tradehub/config/engines.yaml`
- Create: `tests/test_scan_cpi.py`

**Interfaces:**
- Consumes: `fetch_nowcast_history(kind)` (Task 2); `CPI_TARGETS`, `CPI_TRAIN_MONTHS`, `latest_nowcast`, `training_pairs`, `fit_cpi_error`, `cpi_prob` (Task 3); `event_month` (Task 1); existing `edge_row`, `_mid`, `evaluate_edge`, `build_prediction_row`, `load_engine_config`.
- Produces: `CPI_SCAN_HOURS_ET = (8, 12, 16)`, `cpi_scan_due(now) -> bool`, `scan_cpi(live, now, cfg, *, nowcast_fn=fetch_nowcast_history, targets=CPI_TARGETS) -> tuple[list[dict], list[dict]]`. The summary JSON key is `"cpi_nowcast": {"predictions", "edges", "status"}`.

- [ ] **Step 1: Write the failing test** `tests/test_scan_cpi.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.data.kalshi_live import LiveMarket
from tradehub.edges import Quote
from tradehub.engine_config import EngineConfig, load_engine_config
from tradehub.markets import parse_cpi_market
from tradehub.scripts import scan

PAYLOAD = json.loads((Path(__file__).parent / "fixtures" / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))
NOW = datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc)  # 08:05 EDT on the Aug-2026 release morning
CFG = EngineConfig(min_edge_pct=5.0, prefer_maker=True, params={"train_months": 24.0, "use_bias": 0.0})


def _lm(series, strike, month="26AUG", close="2026-09-11T12:25:00Z", bid=0.30, ask=0.34):
    event = f"{series}-{month}"
    market = parse_cpi_market({"ticker": f"{event}-T{strike}", "event_ticker": event, "strike_type": "greater",
                               "floor_strike": strike, "open_time": "2026-07-23T21:00:00Z", "close_time": close,
                               "title": f"{series} {strike}"})
    return LiveMarket(market, Quote(yes_bid=bid, yes_ask=ask, yes_bid_size=50.0, yes_ask_size=50.0))


class FakeLive:
    def __init__(self, markets):
        self.markets = markets

    def open_markets(self, series):
        return [lm for lm in self.markets if lm.market.series_ticker == series]


def _nowcast_fn(calls):
    def fn(kind):
        calls.append(kind)
        return parse_nowcast_month(PAYLOAD, kind)
    return fn


def test_scan_cpi_predicts_headline_and_core_with_their_versions():
    calls = []
    live = FakeLive([_lm("KXCPI", 0.3), _lm("KXCPI", 0.4), _lm("KXCPICORE", 0.2)])
    preds, edges = scan.scan_cpi(live, NOW, CFG, nowcast_fn=_nowcast_fn(calls))
    assert calls == ["headline", "core"]
    by_ticker = {p["market_ticker"]: p for p in preds}
    assert set(by_ticker) == {"KXCPI-26AUG-T0.3", "KXCPI-26AUG-T0.4", "KXCPICORE-26AUG-T0.2"}
    assert all(p["engine"] == "cpi_nowcast" for p in preds)
    assert by_ticker["KXCPI-26AUG-T0.3"]["engine_version"] == "cpi-v1"
    assert by_ticker["KXCPICORE-26AUG-T0.2"]["engine_version"] == "cpi-core-v1"
    headline = by_ticker["KXCPI-26AUG-T0.3"]["raw_payload"]
    # The Sep-10 value (0.3592) became usable at 00:00 ET Sep 11; too few released months -> default sigma.
    assert headline["nowcast_obs"] == "CPI:2026-08@2026-09-10"
    assert headline["nowcast"] == pytest.approx(0.359180537639179)
    assert headline["sigma"] == pytest.approx(0.15) and headline["n_train"] == 1
    assert by_ticker["KXCPI-26AUG-T0.3"]["our_prob"] == pytest.approx(0.5244, abs=1e-4)  # P(N(0.3592, 0.15) > 0.35)
    assert edges and all(e["edge_type"] == "MACRO" for e in edges)


def test_scan_cpi_skips_months_without_a_nowcast_and_closed_markets():
    live = FakeLive([_lm("KXCPI", 0.3, month="26OCT", close="2026-11-10T13:25:00Z"),
                     _lm("KXCPI", 0.3, close="2026-09-11T12:00:00Z")])
    assert scan.scan_cpi(live, NOW, CFG, nowcast_fn=_nowcast_fn([])) == ([], [])


def test_scan_cpi_does_not_fetch_the_nowcast_without_open_markets():
    calls = []
    assert scan.scan_cpi(FakeLive([]), NOW, CFG, nowcast_fn=_nowcast_fn(calls)) == ([], [])
    assert calls == []


def test_cpi_scan_due_hours_are_eastern():
    assert scan.cpi_scan_due(datetime(2026, 9, 11, 12, 5, tzinfo=timezone.utc))      # 08:05 EDT
    assert scan.cpi_scan_due(datetime(2026, 12, 10, 13, 5, tzinfo=timezone.utc))     # 08:05 EST
    assert not scan.cpi_scan_due(datetime(2026, 9, 11, 13, 5, tzinfo=timezone.utc))  # 09:05 EDT


def test_repo_config_has_cpi_nowcast():
    cfg = load_engine_config("cpi_nowcast")
    assert cfg.min_edge_pct > 0 and cfg.prefer_maker is True
    assert cfg.params == {"train_months": 24.0, "use_bias": 0.0}


def test_main_isolates_a_cpi_failure(monkeypatch, capsys):
    from tradehub import predictions
    from tradehub.core import supabase_client

    written = {}
    monkeypatch.setattr(supabase_client, "get_client", lambda: "client")
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: written.setdefault("edges", rows))
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: written.setdefault("preds", rows))
    monkeypatch.setattr(scan, "KalshiLive", lambda: object())
    monkeypatch.setattr(scan, "scan_weather", lambda live, now, cfg: ([{"w": 1}], []))
    monkeypatch.setattr(scan, "scan_gas", lambda live, now, cfg: ([{"g": 1}], [{"e": 1}]))
    monkeypatch.setattr(scan, "cpi_scan_due", lambda now: True)

    def boom(live, now, cfg):
        raise RuntimeError("cleveland fed down")

    monkeypatch.setattr(scan, "scan_cpi", boom)
    assert scan.main() == 0
    assert written == {"preds": [{"w": 1}, {"g": 1}], "edges": [{"e": 1}]}
    summary = json.loads(capsys.readouterr().out)
    assert summary["cpi_nowcast"]["status"].startswith("error: RuntimeError")
    assert summary["cpi_nowcast"]["predictions"] == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan_cpi.py -q`
Expected: `6 failed`, with `AttributeError: module 'tradehub.scripts.scan' has no attribute 'scan_cpi'` / `'cpi_scan_due'` and `KeyError: 'cpi_nowcast'`.

- [ ] **Step 3: Implement.** Save as `/tmp/cpi-t4.patch`, then `git apply --3way /tmp/cpi-t4.patch`. If PR #4's per-engine isolation already reshaped `main()`, keep its structure and add the CPI block as one more isolated engine, as described in Intent.

```diff
diff --git a/tradehub/config/engines.yaml b/tradehub/config/engines.yaml
index cb0f025..1f82ad7 100644
--- a/tradehub/config/engines.yaml
+++ b/tradehub/config/engines.yaml
@@ -7,3 +7,8 @@ weather:
 gas:
   min_edge_pct: 3.0
   prefer_maker: true
+cpi_nowcast:
+  min_edge_pct: 5.0
+  prefer_maker: true
+  train_months: 24       # most recent released months used to fit the nowcast error (see step-6 backtest)
+  use_bias: 0            # 1 = also shift by the mean error; off: it worsened Brier in every step-6 backtest variant
diff --git a/tradehub/scripts/scan.py b/tradehub/scripts/scan.py
index 4de4bad..b856d24 100644
--- a/tradehub/scripts/scan.py
+++ b/tradehub/scripts/scan.py
@@ -1,4 +1,4 @@
-"""One-shot scan (suggest-only): predict every open weather/gas market, flag trade-worthy edges.
+"""One-shot scan (suggest-only): predict every open weather/gas/CPI market, flag trade-worthy edges.

 Writes every prediction to the predictions ledger and upserts edges (with Kalshi deep links)
 into kalshi_edges. Never places orders. Cron-ready: runs once and exits.
@@ -9,20 +9,25 @@ from __future__ import annotations
 import json
 import sys
 from collections import defaultdict
-from datetime import datetime, timezone
+from datetime import datetime, timedelta, timezone
 from typing import Any, Callable
 from zoneinfo import ZoneInfo

+from tradehub.data.cleveland_fed import fetch_nowcast_history
 from tradehub.data.kalshi_live import KalshiLive
 from tradehub.data.rbob import rbob_closes
 from tradehub.data.weather import WEATHER_CITIES, City, live_forecast_highs
 from tradehub.edges import EdgeSuggestion, evaluate_edge
 from tradehub.engine_config import EngineConfig, load_engine_config
+from tradehub.engines.cpi import CPI_TARGETS, CPI_TRAIN_MONTHS, cpi_prob, fit_cpi_error, latest_nowcast, training_pairs
 from tradehub.engines.gas import GAS_ENGINE_VERSION, GAS_SERIES, fit_gas_model, gas_prob, gas_training_pairs, rbob_change
 from tradehub.engines.weather import WEATHER_ENGINE_VERSION, ErrorModel, weather_prob
-from tradehub.markets import KalshiMarket, event_date, market_url
+from tradehub.markets import KalshiMarket, event_date, event_month, market_url
 from tradehub.predictions import build_prediction_row

+CPI_SCAN_HOURS_ET = (8, 12, 16)  # 08:05 ET is the last run before the 08:25 ET release-day close
+_ET = ZoneInfo("America/New_York")
+

 def edge_row(market: KalshiMarket, s: EdgeSuggestion, edge_type: str) -> dict[str, Any]:
     return {
@@ -107,6 +112,47 @@ def scan_gas(live, now: datetime, cfg: EngineConfig, *, rbob_fn: Callable[[], li
     return predictions, edges


+def cpi_scan_due(now: datetime) -> bool:
+    """The nowcast moves at most once a day, so CPI runs on three of the hourly scans, not all 24."""
+    return now.astimezone(_ET).hour in CPI_SCAN_HOURS_ET
+
+
+def scan_cpi(
+    live, now: datetime, cfg: EngineConfig, *,
+    nowcast_fn: Callable[[str], dict] = fetch_nowcast_history,
+    targets: dict[str, tuple[str, str]] = CPI_TARGETS,
+) -> tuple[list[dict], list[dict]]:
+    window = int(cfg.params.get("train_months", CPI_TRAIN_MONTHS))
+    use_bias = bool(cfg.params.get("use_bias", 0.0))
+    predictions: list[dict] = []
+    edges: list[dict] = []
+    for series, (kind, version) in targets.items():
+        markets = live.open_markets(series)
+        if not markets:
+            continue
+        history = nowcast_fn(kind)
+        for lm in markets:
+            nowcast = latest_nowcast(history.get(event_month(lm.market.event_ticker)), now)
+            horizon = lm.market.close_time - now
+            if nowcast is None or horizon <= timedelta(0):
+                continue
+            pairs = training_pairs(history, now, horizon)[-window:]
+            model = fit_cpi_error(pairs, window=window, use_bias=use_bias)
+            prob = cpi_prob(lm.market, nowcast.value, model)
+            predictions.append(build_prediction_row(
+                market_ticker=lm.market.ticker, our_prob=prob, market_prob=_mid(lm.quote), engine="cpi_nowcast",
+                as_of=now, engine_version=version,
+                raw_payload={"nowcast": nowcast.value, "nowcast_obs": nowcast.name, "bias": model.bias,
+                             "sigma": model.sigma, "n_train": len(pairs),
+                             "hours_to_close": round(horizon.total_seconds() / 3600.0, 2)},
+            ))
+            suggestion = evaluate_edge(lm.market.ticker, prob, lm.quote, min_edge_pct=cfg.min_edge_pct,
+                                       prefer_maker=cfg.prefer_maker)
+            if suggestion:
+                edges.append(edge_row(lm.market, suggestion, "MACRO"))
+    return predictions, edges
+
+
 def main() -> int:
     from tradehub.core.supabase_client import get_client, upsert_opportunities
     from tradehub.predictions import record_predictions
@@ -115,12 +161,22 @@ def main() -> int:
     live = KalshiLive()
     weather_preds, weather_edges = scan_weather(live, now, load_engine_config("weather"))
     gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
-    record_predictions(get_client(), weather_preds + gas_preds)
-    upsert_opportunities(weather_edges + gas_edges)
+    cpi_preds: list[dict] = []
+    cpi_edges: list[dict] = []
+    cpi_status = "skipped"
+    if cpi_scan_due(now):
+        try:  # a Cleveland Fed or CPI-market failure must not block the weather/gas writes
+            cpi_preds, cpi_edges = scan_cpi(live, now, load_engine_config("cpi_nowcast"))
+            cpi_status = "ok"
+        except Exception as exc:  # noqa: BLE001 - isolate the engine, report the error
+            cpi_status = f"error: {exc!r}"
+    record_predictions(get_client(), weather_preds + gas_preds + cpi_preds)
+    upsert_opportunities(weather_edges + gas_edges + cpi_edges)
     print(json.dumps({
         "as_of": now.isoformat(),
         "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
         "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
+        "cpi_nowcast": {"predictions": len(cpi_preds), "edges": len(cpi_edges), "status": cpi_status},
     }))
     return 0

```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_scan_cpi.py tests/test_scan.py tests/test_engine_config.py -q`
Expected: `13 passed`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/scan.py tradehub/config/engines.yaml tests/test_scan_cpi.py
git commit -m "feat: scan KXCPI/KXCPICORE with the cpi_nowcast engine (MACRO edges, isolated)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Point-in-time CPI backtest (builder + CLI)

**Intent:**
- `build_cpi_decisions` decides at `close_time − 25 min − extra_lead`, which is 08:00 ET on release morning by default. It uses the nowcast known then and σ fit on the `window` most recent released months at the same horizon, and puts every observation used into `Decision.features`. Months without a nowcast are skipped.
- The CLI's `--engine cpi_nowcast` (default series `KXCPI`, or `--series KXCPICORE`) does the following:
  - filters settled markets by `event_month`;
  - parses them with `parse_cpi_market`;
  - fetches the nowcast of the series' kind;
  - fetches candles only for the last `lead_days + 3` days before close (`_histories(lookback=)`);
  - scores only decisions with a quote at decision time;
  - runs the backtest with cadence `monthly` and version `CPI_TARGETS[series][1]`;
  - adds `lead_days` to the stored config.
- Weather/gas behaviour, including the `_histories` call and the config dict, is unchanged.

**Files:**
- Modify: `tradehub/scripts/backtest_engines.py`
- Create: `tests/test_backtest_cpi.py`

**Interfaces:**
- Consumes: Tasks 1–3; existing `quote_at`, `run_backtest`, `MarketHistory`, `build_backtest_run_row`, `data_snapshot_hash`.
- Produces: `CPI_DECISION_LEAD = timedelta(minutes=25)`; `build_cpi_decisions(markets, history, *, extra_lead=timedelta(0), window=CPI_TRAIN_MONTHS, use_bias=False) -> list[Decision]`; `_histories(client, markets, results, mode, lookback: timedelta | None = None)`; CLI flags `--engine cpi_nowcast`, `--lead-days N`.

- [ ] **Step 1: Write the failing test** `tests/test_backtest_cpi.py`:

```python
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tradehub.backtest.kalshi_history import Candle
from tradehub.backtest.pit import check_no_lookahead
from tradehub.backtest.runner import MarketHistory, run_backtest
from tradehub.data.cleveland_fed import parse_nowcast_month
from tradehub.markets import parse_cpi_market
from tradehub.scripts import backtest_engines
from tradehub.scripts.backtest_engines import CPI_DECISION_LEAD, build_cpi_decisions

FIXTURES = Path(__file__).parent / "fixtures"
PAYLOAD = json.loads((FIXTURES / "cleveland_nowcast_month_trimmed.json").read_text(encoding="utf-8"))
RAWS = {r["ticker"]: r for r in json.loads((FIXTURES / "kalshi_cpi_markets_trimmed.json").read_text(encoding="utf-8"))}
HISTORY = parse_nowcast_month(PAYLOAD)
UTC = timezone.utc


def test_decision_is_0800_et_on_release_morning_and_leakage_safe():
    market = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    [decision] = build_cpi_decisions([market], HISTORY)
    assert decision.decided_at == datetime(2026, 9, 11, 12, 0, tzinfo=UTC) == market.close_time - CPI_DECISION_LEAD
    check_no_lookahead(decision)
    names = [o.name for o in decision.features]
    assert names[0] == "CPI:2026-08@2026-09-10"  # the latest value usable at 08:00 ET
    assert "CPI:2026-08:actual" not in names      # its own print lands at 08:30 ET
    assert "CPI:2021-12:actual" in names          # the one earlier released month in the fixture
    assert decision.our_prob == pytest.approx(0.5244, abs=1e-4)


def test_extra_lead_uses_an_older_nowcast():
    market = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    [decision] = build_cpi_decisions([market], HISTORY, extra_lead=timedelta(days=7))
    assert decision.decided_at == datetime(2026, 9, 4, 12, 0, tzinfo=UTC)
    assert decision.features[0].name == "CPI:2026-08@2026-08-03"  # the Sep-10 value is not known yet
    check_no_lookahead(decision)


def test_months_without_a_nowcast_are_skipped():
    legacy = parse_cpi_market(RAWS["CPI-22AUG-TN0.4"])  # Aug 2022 is not in the trimmed fixture
    assert build_cpi_decisions([legacy], HISTORY) == []


def test_cpi_decisions_run_through_the_backtester():
    yes = parse_cpi_market(RAWS["KXCPI-26AUG-T0.3"])
    no = parse_cpi_market(RAWS["KXCPI-26AUG-T0.4"])
    candle = [Candle(datetime(2026, 9, 11, 11, 0, tzinfo=UTC), 0.60, 0.62, 100.0)]
    histories = {m.ticker: MarketHistory(m.ticker, RAWS[m.ticker]["result"], m.close_time, candle, [])
                 for m in (yes, no)}
    result = run_backtest(engine="cpi_nowcast", cadence="monthly", decisions=build_cpi_decisions([yes, no], HISTORY),
                          histories=histories)
    assert result.n_decisions == 2
    assert result.summary["brier_market"] is not None


def test_backtest_cli_cpi_branch(monkeypatch):
    raws = [RAWS["KXCPI-26AUG-T0.3"], RAWS["KXCPI-26AUG-T0.4"], RAWS["CPI-22AUG-TN0.4"]]

    class FakeClient:
        def __init__(self):
            self.calls = []

        def merged_settled_markets(self, series):
            self.calls.append(series)
            return raws

    client = FakeClient()
    captured = {}
    kinds = []

    def fake_histories(client, markets, results, mode, lookback=None):
        captured["lookback"] = lookback
        captured["history_tickers"] = sorted(m.ticker for m in markets)
        quoted = [Candle(datetime(2026, 9, 11, 11, 0, tzinfo=UTC), 0.60, 0.62, 100.0)]
        return {m.ticker: MarketHistory(m.ticker, results[m.ticker], m.close_time,
                                        quoted if m.ticker.endswith("T0.3") else [], [])
                for m in markets}

    def fake_run_backtest(**kwargs):
        captured["cadence"] = kwargs["cadence"]
        captured["scored"] = [d.market_ticker for d in kwargs["decisions"]]
        return object()

    def fake_build_row(result, **kwargs):
        captured.update(kwargs)
        return {k: None for k in ("engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                                  "brier_ours", "brier_market", "gate_status", "gate_reasons")}

    def fake_nowcast(kind):
        kinds.append(kind)
        return HISTORY

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", lambda: client)
    monkeypatch.setattr(backtest_engines, "fetch_nowcast_history", fake_nowcast)
    monkeypatch.setattr(backtest_engines, "_histories", fake_histories)
    monkeypatch.setattr(backtest_engines, "run_backtest", fake_run_backtest)
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row", fake_build_row)

    assert backtest_engines.main(["--engine", "cpi_nowcast", "--start", "2026-08-01", "--end", "2026-08-31"]) == 0
    assert client.calls == ["KXCPI"] and kinds == ["headline"]
    assert captured["history_tickers"] == ["KXCPI-26AUG-T0.3", "KXCPI-26AUG-T0.4"]  # Aug 2022 filtered by date
    assert captured["lookback"] == timedelta(days=3)
    assert captured["scored"] == ["KXCPI-26AUG-T0.3"]  # T0.4 had no quote at decision time
    assert captured["cadence"] == "monthly"
    assert captured["engine_version"] == "cpi-v1"
    assert captured["config"]["lead_days"] == 0 and captured["config"]["series"] == "KXCPI"
    assert captured["date_from"] == datetime(2026, 8, 1, tzinfo=UTC)


def test_backtest_cli_core_series_uses_core_nowcast(monkeypatch):
    kinds = []
    captured = {}

    class FakeClient:
        def merged_settled_markets(self, series):
            return []

    monkeypatch.setattr(backtest_engines, "KalshiHistoryClient", FakeClient)
    monkeypatch.setattr(backtest_engines, "fetch_nowcast_history", lambda kind: kinds.append(kind) or {})
    monkeypatch.setattr(backtest_engines, "_histories", lambda *a, **k: {})
    monkeypatch.setattr(backtest_engines, "run_backtest", lambda **kwargs: object())
    monkeypatch.setattr(backtest_engines, "data_snapshot_hash", lambda decisions, histories: "hash")
    monkeypatch.setattr(backtest_engines, "build_backtest_run_row",
                        lambda result, **kw: captured.update(kw) or {k: None for k in (
                            "engine", "mode", "n_decisions", "n_fills", "pnl_after_fees", "max_drawdown",
                            "brier_ours", "brier_market", "gate_status", "gate_reasons")})
    assert backtest_engines.main(["--engine", "cpi_nowcast", "--series", "KXCPICORE",
                                  "--start", "2026-01-01", "--end", "2026-08-31", "--lead-days", "7"]) == 0
    assert kinds == ["core"]
    assert captured["engine_version"] == "cpi-core-v1" and captured["config"]["lead_days"] == 7
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_cpi.py -q`
Expected: collection error, `ImportError: cannot import name 'CPI_DECISION_LEAD' from 'tradehub.scripts.backtest_engines'`.

- [ ] **Step 3: Implement.** Save as `/tmp/cpi-t5.patch`, then `git apply --3way /tmp/cpi-t5.patch`:

```diff
diff --git a/tradehub/scripts/backtest_engines.py b/tradehub/scripts/backtest_engines.py
index 2895437..ec20707 100644
--- a/tradehub/scripts/backtest_engines.py
+++ b/tradehub/scripts/backtest_engines.py
@@ -1,4 +1,4 @@
-"""Point-in-time decision builders for the weather and gas engines, plus a backtest CLI.
+"""Point-in-time decision builders for the weather, gas and CPI engines, plus a backtest CLI.

 Each decision carries only observations published at or before its decision time
 (checked by tradehub.backtest.pit.check_no_lookahead inside run_backtest); model
@@ -16,13 +16,24 @@ from datetime import date, datetime, time, timedelta, timezone
 from typing import Callable, Iterable, Mapping
 from zoneinfo import ZoneInfo

+from tradehub.backtest.fills import quote_at
 from tradehub.backtest.kalshi_history import KalshiHistoryClient
 from tradehub.backtest.pit import Decision, Observation
 from tradehub.backtest.runner import MarketHistory, run_backtest
 from tradehub.backtest.store import build_backtest_run_row, data_snapshot_hash, record_backtest_run
+from tradehub.data.cleveland_fed import MonthNowcast, fetch_nowcast_history
 from tradehub.data.kalshi_live import settlement_observations
 from tradehub.data.rbob import rbob_closes
 from tradehub.data.weather import WEATHER_CITIES, City, historical_forecast_highs
+from tradehub.engines.cpi import (
+    CPI_SERIES,
+    CPI_TARGETS,
+    CPI_TRAIN_MONTHS,
+    cpi_prob,
+    fit_cpi_error,
+    latest_nowcast,
+    training_pairs,
+)
 from tradehub.engines.gas import (
     GAS_ENGINE_VERSION,
     GAS_SERIES,
@@ -33,10 +44,11 @@ from tradehub.engines.gas import (
     rbob_change,
 )
 from tradehub.engines.weather import WEATHER_ENGINE_VERSION, fit_error_model, weather_prob
-from tradehub.markets import KalshiMarket, event_date, parse_market
+from tradehub.markets import KalshiMarket, event_date, event_month, parse_cpi_market, parse_market

 WEATHER_DECISION_TIME = time(23, 30)
 GAS_DECISION_LEAD = timedelta(hours=2)
+CPI_DECISION_LEAD = timedelta(minutes=25)  # 08:00 ET on release morning (close is 08:25 ET)
 WEATHER_FETCH_MAX_WORKERS = 8


@@ -115,24 +127,47 @@ def build_gas_decisions(markets: list[KalshiMarket], aaa: list[Observation], rbo
     return decisions


+def build_cpi_decisions(
+    markets: list[KalshiMarket],
+    history: Mapping[date, MonthNowcast],
+    *,
+    extra_lead: timedelta = timedelta(0),
+    window: int = CPI_TRAIN_MONTHS,
+    use_bias: bool = False,
+) -> list[Decision]:
+    decisions = []
+    for market in markets:
+        decided_at = market.close_time - CPI_DECISION_LEAD - extra_lead
+        nowcast = latest_nowcast(history.get(event_month(market.event_ticker)), decided_at)
+        if nowcast is None:
+            continue
+        pairs = training_pairs(history, decided_at, market.close_time - decided_at)[-window:]
+        prob = cpi_prob(market, nowcast.value, fit_cpi_error(pairs, window=window, use_bias=use_bias))
+        used = tuple(obs for pair in pairs for obs in pair)
+        decisions.append(Decision(market.ticker, decided_at, prob, (nowcast,) + used))
+    return decisions
+
+
 def _histories(
     client: KalshiHistoryClient,
     markets: list[KalshiMarket],
     results: Mapping[str, str | None],
     mode: str,
+    lookback: timedelta | None = None,
 ) -> dict[str, MarketHistory]:
     if mode not in ("taker", "maker"):
         raise ValueError(f"mode must be 'taker' or 'maker', got {mode!r}")
     out = {}
     for market in markets:
+        start = market.open_time if lookback is None else max(market.open_time, market.close_time - lookback)
         candles = client.merged_candles(
             market.ticker,
-            market.open_time,
+            start,
             market.close_time,
             series_ticker=market.series_ticker,
         )
         trades = (
-            client.merged_trades(market.ticker, start=market.open_time, end=market.close_time)
+            client.merged_trades(market.ticker, start=start, end=market.close_time)
             if mode == "maker"
             else []
         )
@@ -147,12 +182,12 @@ def _histories(


 def main(argv: list[str] | None = None) -> int:
-    parser = argparse.ArgumentParser(description="Point-in-time backtest for the weather or gas engine.")
-    parser.add_argument("--engine", choices=["weather", "gas"], required=True)
+    parser = argparse.ArgumentParser(description="Point-in-time backtest for the weather, gas or CPI engine.")
+    parser.add_argument("--engine", choices=["weather", "gas", "cpi_nowcast"], required=True)
     parser.add_argument("--start", type=date.fromisoformat, required=True)
     parser.add_argument("--end", type=date.fromisoformat, required=True)
     parser.add_argument("--mode", choices=["taker", "maker"], default="taker")
-    parser.add_argument("--series", default=None, help="weather series ticker (default KXHIGHNY)")
+    parser.add_argument("--series", default=None, help="series ticker (default KXHIGHNY / KXAAAGASD / KXCPI)")
     parser.add_argument("--record", action="store_true", help="write a backtest_runs row")
     parser.add_argument(
         "--train-days",
@@ -160,19 +195,29 @@ def main(argv: list[str] | None = None) -> int:
         default=90,
         help="days of history before --start used to fit the weather error model",
     )
+    parser.add_argument("--lead-days", type=int, default=0,
+                        help="cpi_nowcast: decide this many days before release morning (default 0)")
     args = parser.parse_args(argv)

     client = KalshiHistoryClient()
-    series = args.series or ("KXHIGHNY" if args.engine == "weather" else GAS_SERIES)
+    default_series = {"weather": "KXHIGHNY", "gas": GAS_SERIES, "cpi_nowcast": CPI_SERIES}
+    series = args.series or default_series[args.engine]
     settled_raws = client.merged_settled_markets(series)
+    event_day = event_month if args.engine == "cpi_nowcast" else event_date
     raws = [
         raw
         for raw in settled_raws
-        if args.start <= event_date(raw["event_ticker"]) <= args.end
+        if args.start <= event_day(raw["event_ticker"]) <= args.end
     ]
-    markets = [parse_market(raw) for raw in raws]
+    markets = [parse_cpi_market(raw) if args.engine == "cpi_nowcast" else parse_market(raw) for raw in raws]
     results = {raw["ticker"]: raw.get("result") for raw in raws}
-    if args.engine == "weather":
+    cadence = "monthly" if args.engine == "cpi_nowcast" else "daily"
+    lookback = None
+    if args.engine == "cpi_nowcast":
+        kind, version = CPI_TARGETS[series]
+        decisions = build_cpi_decisions(markets, fetch_nowcast_history(kind), extra_lead=timedelta(days=args.lead_days))
+        lookback = timedelta(days=args.lead_days + 3)
+    elif args.engine == "weather":
         city = WEATHER_CITIES[series]
         actuals = settlement_observations(settled_raws)
         train_from = args.start - timedelta(days=args.train_days)
@@ -198,10 +243,15 @@ def main(argv: list[str] | None = None) -> int:
         [market for market in markets if market.ticker in {decision.market_ticker for decision in decisions}],
         results,
         mode=args.mode,
+        **({"lookback": lookback} if lookback is not None else {}),
     )
+    if args.engine == "cpi_nowcast":
+        # Score only contracts with a visible quote at decision time, so our Brier and the
+        # market's Brier cover the same contracts (the gate needs full market coverage).
+        decisions = [d for d in decisions if quote_at(histories[d.market_ticker].candles, d.decided_at) is not None]
     result = run_backtest(
         engine=args.engine,
-        cadence="daily",
+        cadence=cadence,
         decisions=decisions,
         histories=histories,
         mode=args.mode,
@@ -214,6 +264,8 @@ def main(argv: list[str] | None = None) -> int:
         "end": str(args.end),
         "train_days": args.train_days,
     }
+    if args.engine == "cpi_nowcast":
+        config["lead_days"] = args.lead_days
     row = build_backtest_run_row(
         result,
         engine_version=version,
```

- [ ] **Step 4: Run to verify it passes, then run the whole suite**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_backtest_cpi.py tests/test_backtest_engines.py -q`
Expected: `17 passed`.

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q && .venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests`
Expected: all pass (on `31b66b1`: `311 passed`; after the prerequisites merge, the baseline count + 31), and `All checks passed!`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/scripts/backtest_engines.py tests/test_backtest_cpi.py
git commit -m "feat: point-in-time backtest for cpi_nowcast (release-morning decisions)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Live verification, evidence report, tracker row

**Intent:**
- Run the engine once against the live public sources, with no Supabase writes.
- Run the backtests and record the real numbers, even if the model loses to the market.
- Mark step 6 in the tracker.

**Files:**
- Create: `docs/superpowers/reports/2026-09-25-cpi-nowcast.md`
- Modify: `docs/superpowers/plans/2026-09-24-rollout-tracker.md` (row 6 only)

- [ ] **Step 1: Live smoke of the engine (no writes).** Run it from the repo root:

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python - <<'EOF'
from collections import Counter
from datetime import datetime, timezone
from tradehub.data.kalshi_live import KalshiLive
from tradehub.engine_config import load_engine_config
from tradehub.scripts.scan import scan_cpi
now = datetime.now(timezone.utc)
preds, edges = scan_cpi(KalshiLive(), now, load_engine_config("cpi_nowcast"))
print(now.isoformat(), "predictions", len(preds), "edges", len(edges))
print(Counter(p["engine_version"] for p in preds))
for p in preds[:3]:
    print(p["market_ticker"], p["our_prob"], p["market_prob"], p["raw_payload"]["nowcast_obs"], round(p["raw_payload"]["sigma"], 3))
EOF
```

Expected: at least one prediction for each version while a KXCPI/KXCPICORE month with a Cleveland Fed nowcast is open (on 2026-09-25: 25 predictions, `cpi-v1` 14 / `cpi-core-v1` 11). Every `nowcast_obs` must be dated no later than yesterday (ET).

- [ ] **Step 2: Live backtests (read-only; do not pass `--record` unless Kevin asks).**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_engines --engine cpi_nowcast --start 2021-06-01 --end 2026-08-31
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.scripts.backtest_engines --engine cpi_nowcast --series KXCPICORE --start 2021-06-01 --end 2026-08-31
```

Expected: JSON with `"gate_status": "SHADOW"`. On 2026-09-25 the headline run gave 461 contracts, Brier 0.09877 vs market 0.07076, and P&L −7.7254. The core run gave 383 contracts, Brier 0.0841 vs 0.07823, and P&L +7.0527. Each run makes ~500 Kalshi requests and takes 3–8 minutes. If you get HTTP 429 and PR #3's retry fix is missing, wait a minute and rerun, then note it in the report.

- [ ] **Step 3: Write the evidence report** `docs/superpowers/reports/2026-09-25-cpi-nowcast.md`. Per the handoff contract it contains:
  - the baseline test count;
  - for each of Tasks 1–5, the RED and GREEN commands with the tail of their output;
  - any hand-merge made against the prerequisite fixes, and why;
  - the Step 1 and Step 2 output verbatim.

- [ ] **Step 4: Update tracker row 6.** In `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, replace exactly this line:

```
| 6 | `cpi_nowcast` | 🗺️ outline only; detail after step 4 lands | — |
```

with:

```
| 6 | `cpi_nowcast` (KXCPI + KXCPICORE, Cleveland Fed nowcast) | ✅ implemented, shadow; backtest loses to market on Brier (headline 0.099 vs 0.071), gate SHADOW | [2026-09-25-cpi-nowcast.md](2026-09-25-cpi-nowcast.md) |
```

Also copy this plan file to `docs/superpowers/plans/2026-09-25-cpi-nowcast.md` if it isn't in the repo yet.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/reports/2026-09-25-cpi-nowcast.md docs/superpowers/plans/2026-09-24-rollout-tracker.md docs/superpowers/plans/2026-09-25-cpi-nowcast.md
git commit -m "docs: step 6 cpi_nowcast evidence report and tracker row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**

| Spec requirement | Where |
|---|---|
| §3.1 `cpi_nowcast` targets KXCPI* MoM brackets from the Cleveland Fed nowcast | Tasks 2–4 (KXCPI + KXCPICORE) |
| §3.1 `gas` engine output as an input | Not wired, see decision 2 (the nowcast already embeds gasoline) |
| §3.1 FRED/ALFRED CPI components | Not used, see decision 1 (Cleveland "Actual" = first print, 61/62 vs Kalshi; ALFRED unreachable) |
| §4 pure engine, no I/O | Task 3 (`engines/cpi.py` does no I/O; it imports only the `MonthNowcast` type from the data layer) |
| §4 edge layer: after-fee edge vs bid/ask, maker-first, no taker <10¢ | Task 4 reuses `evaluate_edge` unchanged |
| §4 every output goes to the predictions ledger | Task 4 (one row per open market per run) |
| §5 scheduled batch, no always-on worker | Task 4 (`cpi_scan_due` on the hourly timer; release-morning 08:05 ET run) |
| §5a point-in-time data, walk-forward, conservative fills, stored run | Task 5 (`build_cpi_decisions`, `run_backtest`, `--record` path unchanged) |
| §5a leakage guard | Task 5 (features include every used observation; `run_backtest` calls `check_no_lookahead`; tests call it directly) |
| §6 monthly engine, ≥50 contracts, gate | Tasks 5–6 (cadence `monthly`; gate reported, SHADOW) |
| §10 recorded-response fetcher tests, no live network | Tasks 1–2 fixtures |
| §11 settled shadow record for ≥3 releases | Operational: accrues from the live scan after deploy (Oct 14, Nov 10, Dec 10 releases) |

**Placeholder scan:** no TBD/TODO. Every code step has the full file or an exact patch.

**Type consistency:**
- `MonthNowcast`, `parse_nowcast_month`, `fetch_nowcast_history(kind)` (Task 2) are used with the same names and arguments in Tasks 3–5.
- `CPI_TARGETS[series] == (kind, version)` is used by `scan_cpi` and the CLI.
- `training_pairs(history, as_of, horizon)` returns `(nowcast, actual)` pairs everywhere.
- `fit_cpi_error(pairs, window=, use_bias=)` matches its callers.

**Open questions for Kevin:**
1. The Cleveland Fed's daily publish time and whether its history is as-published are undocumented. The plan assumes a conservative next-midnight availability. A daily snapshot of `nowcast_month.json` would settle it going forward, but it's out of scope here.
2. The live scan will flag edges (7 on 2026-09-25, all NO against a market pricing September CPI hotter than the nowcast), while the backtest says the market is better calibrated. The edges show as "shadow" per §6, so nothing changes in the UI contract. Should the War Room hide MACRO edges from engines whose backtest Brier loses to the market?
3. Headline and core share `engine = cpi_nowcast` and are split only by `engine_version`. Until step 2b's per-version track record lands, they would mix in one record. That's one more reason to keep 2b as a prerequisite.
