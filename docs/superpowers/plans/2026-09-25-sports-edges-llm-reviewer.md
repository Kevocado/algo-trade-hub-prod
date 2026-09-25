# Sports Edges + LLM Reviewer (hub side of rollout step 7) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the NFL and CFB predictor sites' frozen pre-game feeds (companion plan `2026-09-25-predictor-pregame-feed.md`, "7a") into Kalshi edge suggestions: map every game to its Kalshi events, price winner, spread and total markets from the predictor's own distribution, flag edges after fees, pass them through the spec's deterministic candidate filter, have an OpenRouter free model review the candidates (strict JSON, never touching a probability), and show the result in a War Room "Sports" page with links to Kalshi and the predictor site.

**Architecture:**
- A new `tradehub/sports/` package of small pure modules: `config`, `feed`, `kalshi`, `mapping` (plus versioned alias JSON), `pricing`, `candidates`, `reviewer` and `scorecard`. An orchestrator, `sports/scan.py`, wires them together.
- The hourly `tradehub.scripts.scan` runs sports every third UTC hour (spec §5: "sports every 3h"). It writes:
  - one `predictions` row per market (engines `sports_nfl`/`sports_cfb`), deduplicated because the feed probability is frozen;
  - `kalshi_edges` rows with `edge_type='SPORTS'`.
- The existing hourly settle job settles the predictions (both engines added to its `ENGINES`, with `daily` cadence).
- Reviews are cached in a new append-only Supabase table, `sports_reviews`.
- The War Room reads everything through `GET /api/sports-edges`.

**Tech Stack:** Python 3.12, requests, PyYAML, FastAPI, Supabase (Postgres), pytest, ruff; React 18 + Vite + vitest (`market_sentiment_tool`); OpenRouter chat completions (`response_format: json_schema`).

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) §3.2 (Sports Edge section), §4 (edge layer, predictions ledger, settlement), §5 (sports every 3h), §5a (sports leakage rule), §6 (gate), §10 (tests: mapping fixtures per sport; recorded LLM responses, malformed JSON → unreviewed, the LLM can never change `our_prob`), §11 (Sports tab success criterion). Rollout step 7 in `docs/superpowers/plans/2026-09-24-rollout-tracker.md`.

## Kevin's decisions (2026-09-25) — apply throughout

- **Losing engines still show their edges, labelled shadow (spec §6).** Never suppress or skip an edge because this engine's backtest or track record loses to the market.
  - Every edge row this plan writes carries `"engine": "sports_nfl"` / `"sports_cfb"` and goes through `tradehub.scripts.scan.edge_row(...)`, which defaults `gate_status` to `"SHADOW"`.
  - `apply_gate_statuses` sets `PROMOTED` only for an engine whose gate passed. PR #4's follow-up changes it to key on each row's `engine`. Before that, it maps every non-WEATHER row to `gas`, which is wrong for this engine.
  - If `edge_row` has no `engine` argument yet when you start, stop and report. Don't work around it.
  - Add a test asserting that every edge this engine produces has `gate_status == "SHADOW"` when the gate lookup returns nothing.
  - The War Room shows a "Shadow" badge on these edges (PR #4 follow-up).
  - The reviewer tiers (`top_pick | flagged | unreviewed | filtered`) are a separate field. A `top_pick` from an unpromoted engine is still labelled shadow, and the Sports page shows both the tier and the Shadow badge.
- **Deployment target is the VPS (step 5, [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md)), not Azure.**
  - The code ships in the one `ghcr.io/kevocado/tradehub` image: merge to `main`, then `.github/workflows/deploy-tradehub.yml` runs `ssh deploy@$VPS_HOST deploy tradehub <sha>`.
  - It runs inside the hourly `tradehub-scan` / `tradehub-settle` systemd timers (`/opt/stack/bin/tradehub-job scan|settle`). Runtime secrets live only in `/opt/stack/.env`.
  - Create no Azure resources, jobs or secrets.
  - **Azure is legacy.** The predictor sites still run there until the cutover (Azure for Students credit ends around **2026-10-27**). After that no Azure host exists, so nothing may depend on an `*.azurecontainerapps.io` URL beyond it.
  - **Predictor URLs point at the VPS:** `SPORTS_NFL_BASE_URL=https://nfl.<domain>`, `SPORTS_CFB_BASE_URL=https://cfb.<domain>`, `SPORTS_NFL_SITE_URL` / `SPORTS_CFB_SITE_URL=https://sports.<domain>`.
    - Kevin's Task 11 checklist sets these, plus `OPENROUTER_API_KEY`, in `/opt/stack/.env`. They also go on the `tradehub` service's `environment:` in `vps-stack/compose.yml`: today that service passes only `SUPABASE_*`, so without that the scan container never sees them.
    - The Azure URLs in `engines.yaml` are only a fallback until the cutover. If the VPS is serving by Task 11, run the live check against the VPS URLs.

## Global Constraints

- **Prerequisites:**
  - Hub steps 3 (PR #3), 4 (PR #4) and 2b are merged to `main`. This plan was verified on top of PR #4's head `31b66b1`, which already includes steps 2–4.
  - Step 5 (VPS deploy) is recommended first: its `mount_frontend(...)` must stay the **last** statement that registers routes (see Task 9 Step 3).
  - 7a is deployed to both predictors before any live (non-dry-run) sports scan.
- **Branch:** `plan/2026-09-25-sports-edges-llm-reviewer` from `main`. Handoff contract: one commit per task; evidence report at `docs/superpowers/reports/2026-09-25-sports-edges-llm-reviewer.md`; stop and record instead of improvising.
- **Test commands (repo root):**
  - `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q`
  - `.venv/bin/ruff check --select F401,F811,F821 tradehub tests`
  - Frontend, from `market_sentiment_tool/`: `npx vitest run` and `npm run build`.
  - Baseline at `31b66b1`: 280 passed, ruff clean, vitest 5 passed.
- **The hub never models sports** (spec §3.2):
  - winner probability = the predictor's `p_home`;
  - spread/total = the predictor's own Normal(`margin_mu`, `sigma`) / Normal(`total_mu`, `total_sigma`) at Kalshi's half-point strikes;
  - no de-vigging and no hub-side model.
- **Leakage rule (spec §5a):** only feed rows with `backfilled == false` and `snapshotted_at < start_utc` are used. `parse_feed` re-checks both.
- **Mapping never guesses:**
  - the event suffix is the ET kickoff date (`%y%b%d`) plus away + home Kalshi codes from the versioned alias table;
  - home-first and ±1 day are accepted only for the same two teams, and a date shift is recorded;
  - anything else is reported as `unmatched_games` / `unmatched_events`.
- **Candidate filter (spec §3.2 stage 1):** net edge after fees ≥ `min_edge_pct` (existing `tradehub.edges.evaluate_edge`), **and** liquidity (quote spread ≤ `max_quote_spread`, resting size ≥ `min_resting_size` at both best bid and best ask, `volume ≥ min_volume`), **and** time to start in `[1 h, 72 h]`, **and** predictor calibration in the probability bucket: `n ≥ 20` and `|mean_prob − hit_rate| ≤ 0.10`.
- **LLM reviewer (spec §3.2 stage 2):**
  - model in `engines.yaml` (`nvidia/nemotron-3-super-120b-a12b:free`);
  - output is strict JSON `{explainable: bool, drivers: [str], red_flags: [str]}`, validated client-side;
  - it never produces or changes a probability;
  - cache key `sport:game:market:side:5¢-bucket`;
  - daily budget 40 calls (the free tier allows 50/day);
  - any failure, or a missing key, leaves the edge "unreviewed" and never blocks it;
  - only public data is sent;
  - Top Pick = `ok` + `explainable` + no red flags.
- **Keep-or-drop:** the reviewer is dropped if approved picks don't beat rejected ones on Brier or P&L after ≥ 100 settled reviewed picks (`scorecard.reviewer_scorecard`).
- **Secrets:**
  - `OPENROUTER_API_KEY` is read only from the process environment, never from a file;
  - tests use recorded or hand-built fixtures and no network;
  - a live LLM call is Kevin's step;
  - never read or print `.env`.
- **Predictor URLs are config:** Azure defaults live in `engines.yaml`, and `SPORTS_NFL_BASE_URL`, `SPORTS_CFB_BASE_URL`, `SPORTS_NFL_SITE_URL` and `SPORTS_CFB_SITE_URL` move them to the VPS (`https://nfl.<domain>`, `https://cfb.<domain>`, `https://sports.<domain>`).
- **Suggest-only.** Nothing places orders. Don't edit `vps-stack` (the env vars are Kevin's follow-up, Task 11).
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Validation already done (2026-09-25)

All 11 tasks were implemented exactly as written in a scratch worktree at `31b66b1`. Each RED failed as stated (an import error, a failed assertion, or `FileNotFoundError` for the migration) and each GREEN passed.
- **Hub:** 280 → **347 passed**; ruff `F401,F811,F821` clean.
- **Frontend:** vitest 5 → **9 passed**, `tsc --noEmit` clean, and `vite build` built.
- **Migration** `20260416000008_sports_reviews.sql` was applied **twice** (idempotent) to a throwaway `postgres:16` with a stubbed `auth` schema. An insert took the JSONB defaults, and the only policy is `sports_reviews_owner_read` (SELECT).
- **Live smoke A: the real Azure predictors plus public Kalshi, 06:28Z.** `python -m tradehub.sports.scan --dry-run` reports `feed_error: 404` for both sports. That is expected until 7a is deployed, and it shows that a missing feed is reported, not fatal.
- **Live smoke B: 7a's feed served locally, plus live Kalshi.** The feeds came from the local 7a smoke ticks (real models, fresh DB).

  | | NFL | CFB |
  |---|---|---|
  | Feed games | 15 | 70 |
  | Matched | **15/15** | **70/70** |
  | Unmatched feed games | 0 | 0 |
  | Kalshi events on the same days with no feed game | 0 | 49 (FCS-only games the FBS predictor doesn't cover) |
  | Markets priced / ledger rows | 702 / 702 | 3,335 / 3,321 |
  | Edges ≥ 4 pp after fees | 513 | 2,663 |
  | Candidates | **0** | **0** |

  Why there are no candidates: every edge fails `calibration_insufficient`, because a fresh DB has no graded pre-game snapshots. Some edges pass liquidity and timing and fail **only** on calibration: NFL 191 (winner 26, median winner edge 10.6 pp) and CFB 592 (winner 89, median 14.7 pp).

  Edges this large and this frequent are a warning, not a result:
  - NFL: the predictor has TEN@NYG at 72% for NYG −7.5 while Kalshi prices it at 28%.
  - CFB: FBS vs FCS spreads (Howard@Rutgers, Central Arkansas@FSU) differ by 50–60 pp. That suggests the CFB model under-rates the gap to FCS opponents.
- **Live smoke C: the deployed Azure `/api/games` + `/batch` (recomputed, used only to check mapping) plus live Kalshi.**
  - NFL: weeks 3–4 have **31/31** upcoming games matched. Only the 15 week-3 games could be priced, because live `/api/predictions/2026/4/batch` returns **500** (fixed by 7a Task 4).
  - CFB: weeks 4–5 have **129/129** matched. This run found the ESPN "TBD" kickoff placeholder: SJSU@HAW is listed at 03:59Z, but Kalshi dates the event `26OCT04`. That led to the ±1-day rule in Task 4 and its test.
- **Kalshi event URLs:** checked in a real browser (Vercel blocks curl). `https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26oct01pitcle` opens "PIT Steelers vs CLE Browns", and the `kxncaafspread/college-football-spread/...gtstan` URL opens "Georgia Tech vs Stanford: Spread".
- **LLM: not called.** `OPENROUTER_API_KEY` was not in the environment. The OpenRouter models API (public) lists all four candidate free models with `structured_outputs`. The fixtures in `tests/fixtures/sports/openrouter_*.json` are **hand-built in OpenRouter's documented response shape, not recorded**. Task 11 Step 3 records a real one.

## Review Focus

- `parse_review` is the only gate between model output and the UI. It must reject extra keys (e.g. `"probability"`), wrong types, and more than 5 items. (Task 7)
- The reviewer must never alter `model_probability`/`our_prob`: `apply_reviews` writes only `tier` and `review`. (Tasks 7, 8)
- `unrecorded()` keeps one ledger row per market and engine. Without it, the 3-hourly scan would multiply rows for the §6 gate. (Task 8)
- A predictor or Kalshi outage must not fail the weather/gas scan: `scan.main` catches sports errors. (Task 8)
- `/api/sports-edges` must be registered **before** `mount_frontend` if step 5 has landed. (Task 9)
- Mapping: a ±1-day match must still need the same two alias codes, and every non-match must appear in the report. (Task 4)

## Design decisions (and why)

- **Review cache in Supabase, not a local JSON file.** The VPS scan runs in a throwaway `docker compose run --rm` container with no volume (`vps-stack/bin/tradehub-job`), so a file would be lost after every run. The table is append-only (one row per API call), so the daily budget count is exact. Only `status='ok'` rows are served from the cache.
- **Cache key per market and side, not per game.** Spec §3.2 says "(game, price bucket)". One game has winner, spread and total candidates with different drivers, so the key includes the market and side. The game id is still part of it.
- **One prediction row per market.** The feed probability is frozen, so re-recording it every 3 h adds no information and inflates the gate's contract counts (the 2b concern).
- **Every edge ≥ `min_edge_pct` goes to `kalshi_edges`**, tiered `top_pick | flagged | unreviewed | filtered`, with `reject_reasons`. Only candidates are sent to the LLM. The UI shows the tiers separately, so an unfiltered edge is never presented as a pick.
- **The fact pack has no team form or head-to-head yet.** Those predictor endpoints recompute live (NFL `/teams/{t}/form` loads the full history). The pack carries the frozen distribution, its age, the quote, and the calibration bucket, and the prompt tells the model to flag missing news. Adding form is a follow-up once the predictors expose it cheaply.
- **Source URL:** Sports_Predictor has no per-game route, so `source_url` is `<site>/?sport=<s>&game=<id>`. It lands on the site today, and a Sports_Predictor follow-up (listed in 7a) makes it a deep link.

---

## File Structure

- **Modify** `tradehub/markets.py`: `event_date` reads only the 7-character date prefix; new `kalshi_event_url()`. (Task 1)
- **Modify** `tradehub/config/engines.yaml`: `sports_nfl`, `sports_cfb`, `sports_sources`, `sports_reviewer`. **Create** `tradehub/sports/__init__.py` and `tradehub/sports/config.py`. (Task 2)
- **Create** `tradehub/sports/feed.py` (Task 3).
- **Create** `tradehub/sports/kalshi.py`, `tradehub/sports/mapping.py`, `tradehub/sports/aliases/{nfl,cfb}.json` (Task 4).
- **Create** `tradehub/sports/pricing.py` (Task 5).
- **Create** `tradehub/sports/candidates.py` (Task 6).
- **Create** `tradehub/sports/reviewer.py` and `market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql` (Task 7).
- **Create** `tradehub/sports/scan.py`. **Modify** `tradehub/scripts/scan.py`, `tradehub/scripts/settle_predictions.py`, `tests/test_settle_predictions.py` (Task 8).
- **Create** `tradehub/sports/scorecard.py`. **Modify** `tradehub/api/main.py` (Task 9).
- **Create** `market_sentiment_tool/src/lib/sportsEdges.ts`, `src/lib/sportsEdges.test.ts`, `src/pages/SportsEdges.tsx`. **Modify** `src/App.tsx` (Task 10).
- **Modify** `docs/superpowers/plans/2026-09-24-rollout-tracker.md`. **Create** `docs/superpowers/reports/2026-09-25-sports-edges-llm-reviewer.md` (Task 11).
- **Test fixtures** (`tests/fixtures/sports/`):
  - `nfl_kalshi_feed.json` and `cfb_kalshi_feed.json`: recorded from 7a's local feed on 2026-09-25, trimmed to 3 and 2 games;
  - `nfl_open_markets.json` and `cfb_open_markets.json`: recorded from the public Kalshi `/markets?status=open` on 2026-09-25, trimmed;
  - `openrouter_{ok,flagged,bad}.json`: hand-built.

---

## Task 1: Sports-safe `event_date` and Kalshi event deep links

**Files:**
- Modify: `tradehub/markets.py`
- Test: `tests/test_markets_sports.py` (new)

**Interfaces:**
- Produces:
  - `event_date("KXNFLGAME-26OCT01PITCLE") == date(2026, 10, 1)`; weather tickers are unchanged.
  - `kalshi_event_url(series_ticker: str, series_title: str, event_ticker: str) -> str`.

- [ ] **Step 1: Write the failing test**: `tests/test_markets_sports.py`:

```python
from datetime import date

from tradehub.markets import event_date, kalshi_event_url


def test_event_date_reads_only_the_date_prefix_of_sports_event_tickers():
    assert event_date("KXNFLGAME-26OCT01PITCLE") == date(2026, 10, 1)
    assert event_date("KXNCAAFSPREAD-26SEP26GTSTAN") == date(2026, 9, 26)
    assert event_date("KXHIGHNY-26SEP25") == date(2026, 9, 25)   # weather unchanged


def test_kalshi_event_url_uses_series_title_slug():
    # Format checked in a browser on 2026-09-25: this URL opens the PIT vs CLE event page.
    assert kalshi_event_url("KXNFLGAME", "Professional Football Game", "KXNFLGAME-26OCT01PITCLE") == (
        "https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26oct01pitcle"
    )
    assert kalshi_event_url("KXNCAAFSPREAD", "College Football Spread", "KXNCAAFSPREAD-26SEP26GTSTAN") == (
        "https://kalshi.com/markets/kxncaafspread/college-football-spread/kxncaafspread-26sep26gtstan"
    )
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_markets_sports.py`
Expected: `1 error` (`ImportError: cannot import name 'kalshi_event_url'`).

- [ ] **Step 3: Implement** in `tradehub/markets.py`:

Replace this block:

```python
import math
from dataclasses import dataclass
```

with:

```python
import math
import re
from dataclasses import dataclass
```

Replace this block:

```python
def event_date(event_ticker: str) -> date:
    """'KXHIGHNY-26SEP25' -> date(2026, 9, 25)."""
    return datetime.strptime(event_ticker.split("-")[1], "%y%b%d").date()
```

with:

```python
def event_date(event_ticker: str) -> date:
    """'KXHIGHNY-26SEP25' -> date(2026, 9, 25); 'KXNFLGAME-26OCT01PITCLE' -> date(2026, 10, 1).

    The date is always the first 7 characters after the series; sports events append team codes.
    """
    return datetime.strptime(event_ticker.split("-")[1][:7], "%y%b%d").date()
```

Replace this block:

```python
def market_url(market: KalshiMarket) -> str:
    return f"https://kalshi.com/markets/{market.series_ticker.lower()}"
```

with:

```python
def market_url(market: KalshiMarket) -> str:
    return f"https://kalshi.com/markets/{market.series_ticker.lower()}"


def kalshi_event_url(series_ticker: str, series_title: str, event_ticker: str) -> str:
    """Deep link to one event page: kalshi.com/markets/<series>/<series-title-slug>/<event>."""
    slug = re.sub(r"[^a-z0-9]+", "-", series_title.lower()).strip("-")
    return f"https://kalshi.com/markets/{series_ticker.lower()}/{slug}/{event_ticker.lower()}"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_markets_sports.py tests/test_markets.py` → Expected: `9 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/markets.py tests/test_markets_sports.py
git commit -m "feat(markets): sports-safe event_date and Kalshi event deep links

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Sports configuration (thresholds, predictor URLs, reviewer model)

**Files:**
- Modify: `tradehub/config/engines.yaml`
- Create: `tradehub/sports/__init__.py`, `tradehub/sports/config.py`
- Test: `tests/test_sports_config.py` (new)

**Interfaces:**
- Consumes: `tradehub.engine_config.load_engine_config`, `CONFIG_PATH`, `EngineConfig`.
- Produces:
  - `SERIES: dict[sport, {"winner","spread","total"} -> series ticker]` and `SERIES_TITLES`.
  - `SportConfig(sport, engine, base_url, site_url, series, series_titles, edge: EngineConfig)`, where `engine` is `"sports_nfl"`/`"sports_cfb"`.
  - `load_sport_config(sport, path=CONFIG_PATH)`, with env overrides `SPORTS_<SPORT>_BASE_URL` / `SPORTS_<SPORT>_SITE_URL`.
  - `ReviewerConfig(model, daily_budget, timeout_seconds, price_bucket_cents)` and `load_reviewer_config(path=CONFIG_PATH)`.
  - `edge.params` keys: `max_quote_spread, min_resting_size, min_volume, min_hours_to_start, max_hours_to_start, calibration_max_dev, calibration_min_n`.

- [ ] **Step 1: Write the failing test**: `tests/test_sports_config.py`:

```python
from tradehub.engine_config import load_engine_config
from tradehub.sports.config import load_reviewer_config, load_sport_config

AZURE_NFL = "https://nfl-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io"


def test_nfl_config_defaults_to_the_azure_predictor(monkeypatch):
    monkeypatch.delenv("SPORTS_NFL_BASE_URL", raising=False)
    cfg = load_sport_config("nfl")
    assert cfg.engine == "sports_nfl"
    assert cfg.base_url == AZURE_NFL
    assert cfg.site_url == "https://sports-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io"
    assert cfg.series == {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}
    assert cfg.series_titles["KXNFLGAME"] == "Professional Football Game"
    assert cfg.edge.min_edge_pct > 0 and cfg.edge.params["calibration_max_dev"] == 0.10


def test_base_and_site_urls_can_be_moved_by_env(monkeypatch):
    monkeypatch.setenv("SPORTS_CFB_BASE_URL", "https://cfb.example.com/")
    monkeypatch.setenv("SPORTS_CFB_SITE_URL", "https://sports.example.com")
    cfg = load_sport_config("cfb")
    assert cfg.base_url == "https://cfb.example.com"
    assert cfg.site_url == "https://sports.example.com"
    assert cfg.series["winner"] == "KXNCAAFGAME"


def test_sports_engine_blocks_stay_numeric_for_load_engine_config():
    assert load_engine_config("sports_cfb").params["min_resting_size"] > 0


def test_reviewer_config():
    cfg = load_reviewer_config()
    assert cfg.model.endswith(":free")
    assert cfg.daily_budget == 40
    assert cfg.price_bucket_cents == 5
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_config.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports'`).

- [ ] **Step 3: Implement**

Append the sports blocks to `tradehub/config/engines.yaml`:

Replace this block:

```yaml
gas:
  min_edge_pct: 3.0
  prefer_maker: true
```

with:

```yaml
gas:
  min_edge_pct: 3.0
  prefer_maker: true
# Sports edges (rollout step 7): suggestions only, from the predictor sites' frozen pre-game feeds.
# Numeric only, so load_engine_config() works on these blocks too.
sports_nfl:
  min_edge_pct: 4.0            # net edge after fees, percentage points
  prefer_maker: true
  max_quote_spread: 0.04       # dollars between best YES bid and ask
  min_resting_size: 100        # contracts resting at both the best bid and the best ask
  min_volume: 1000             # contracts traded in the market so far
  min_hours_to_start: 1
  max_hours_to_start: 72
  calibration_max_dev: 0.10    # predictor's |mean prob - hit rate| in this prob bucket (spec §3.2)
  calibration_min_n: 20        # graded pre-game snapshots needed in the bucket
sports_cfb:
  min_edge_pct: 4.0
  prefer_maker: true
  max_quote_spread: 0.04
  min_resting_size: 100
  min_volume: 500
  min_hours_to_start: 1
  max_hours_to_start: 72
  calibration_max_dev: 0.10
  calibration_min_n: 20
# Where each predictor lives. Azure today; override per host with
# SPORTS_<SPORT>_BASE_URL / SPORTS_<SPORT>_SITE_URL after the VPS cutover
# (https://nfl.<domain>, https://cfb.<domain>, https://sports.<domain>).
sports_sources:
  nfl:
    base_url: https://nfl-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io
    site_url: https://sports-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io
  cfb:
    base_url: https://cfb-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io
    site_url: https://sports-predictor.proudbay-f56b8dfa.eastus2.azurecontainerapps.io
# LLM reviewer (spec §3.2): OpenRouter free model, strict JSON, never touches a probability.
sports_reviewer:
  model: nvidia/nemotron-3-super-120b-a12b:free
  daily_budget: 40             # calls/day; the free tier allows 50 (1,000 after a one-time $10 credit)
  timeout_seconds: 60
  price_bucket_cents: 5        # cache key granularity for the entry price
```

`tradehub/sports/__init__.py`:

```python
"""Sports edges: read-only consumers of the predictor sites' pre-game feeds (spec §3.2)."""
```

`tradehub/sports/config.py`:

```python
"""Per-sport settings: predictor URLs, Kalshi series, edge/candidate thresholds, LLM reviewer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from tradehub.engine_config import CONFIG_PATH, EngineConfig, load_engine_config

# Kalshi series per sport and market kind, with the series titles Kalshi uses in
# its event URLs (GET /series/{ticker}, checked 2026-09-25).
SERIES: dict[str, dict[str, str]] = {
    "nfl": {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"},
    "cfb": {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
}
SERIES_TITLES: dict[str, str] = {
    "KXNFLGAME": "Professional Football Game",
    "KXNFLSPREAD": "Pro Football Spread",
    "KXNFLTOTAL": "Pro Football Total Points",
    "KXNCAAFGAME": "College Football Game",
    "KXNCAAFSPREAD": "College Football Spread",
    "KXNCAAFTOTAL": "College Football Total Points",
}


@dataclass(frozen=True)
class SportConfig:
    sport: str
    engine: str
    base_url: str
    site_url: str
    series: Mapping[str, str]
    series_titles: Mapping[str, str]
    edge: EngineConfig


@dataclass(frozen=True)
class ReviewerConfig:
    model: str
    daily_budget: int
    timeout_seconds: float
    price_bucket_cents: int


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_sport_config(sport: str, path: Path = CONFIG_PATH) -> SportConfig:
    sources = _yaml(path)["sports_sources"][sport]
    prefix = f"SPORTS_{sport.upper()}_"
    base_url = os.getenv(prefix + "BASE_URL") or sources["base_url"]
    site_url = os.getenv(prefix + "SITE_URL") or sources["site_url"]
    series = SERIES[sport]
    return SportConfig(
        sport=sport,
        engine=f"sports_{sport}",
        base_url=base_url.rstrip("/"),
        site_url=site_url.rstrip("/"),
        series=series,
        series_titles={s: SERIES_TITLES[s] for s in series.values()},
        edge=load_engine_config(f"sports_{sport}", path),
    )


def load_reviewer_config(path: Path = CONFIG_PATH) -> ReviewerConfig:
    raw = _yaml(path)["sports_reviewer"]
    return ReviewerConfig(
        model=str(raw["model"]),
        daily_budget=int(raw["daily_budget"]),
        timeout_seconds=float(raw["timeout_seconds"]),
        price_bucket_cents=int(raw["price_bucket_cents"]),
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_config.py tests/test_engine_config.py` → Expected: `7 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/config/engines.yaml tradehub/sports/__init__.py tradehub/sports/config.py tests/test_sports_config.py
git commit -m "feat(sports): per-sport config, predictor URLs and reviewer model in engines.yaml

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Predictor feed client

**Files:**
- Create: `tradehub/sports/feed.py`, `tests/fixtures/sports/nfl_kalshi_feed.json`, `tests/fixtures/sports/cfb_kalshi_feed.json`
- Test: `tests/test_sports_feed.py` (new)

**Interfaces:**
- Consumes: 7a's `GET /api/kalshi-feed` contract.
- Produces:
  - `FeedGame(sport, game_id, home, away, start_utc: datetime, p_home, margin_mu, sigma, total_mu, total_sigma, model_version, snapshotted_at: datetime, season=None, week=None)`.
  - `Feed(sport, generated_at, games, calibration: {"winner"|"spread"|"total": [bucket]}, rejected: [{"game_id","reason"}])`.
  - `parse_feed(raw) -> Feed`.
  - `fetch_feed(base_url, *, get=requests.get, sleep=time.sleep, timeout=60.0) -> Feed`, with one retry after 2 s; raises `FeedUnavailable`.

- [ ] **Step 1: Add the recorded fixtures** (7a's local feed, 2026-09-25, trimmed):

`tests/fixtures/sports/nfl_kalshi_feed.json`:

```json
{
 "sport": "nfl",
 "generated_at": "2026-09-25T06:14:50.951252+00:00",
 "lead_hours": 96.0,
 "games": [
  {
   "game_id": "2026_03_CIN_PIT",
   "season": 2026,
   "week": 3,
   "home": "PIT",
   "away": "CIN",
   "start_utc": "2026-09-27T17:00:00+00:00",
   "p_home": 0.5331896007560653,
   "margin_mu": 1.1013590097427368,
   "sigma": 13.223153618916728,
   "total_mu": 42.64759826660156,
   "total_sigma": 12.486688413234214,
   "home_spread_line": -3.5,
   "total_line": 42.5,
   "model_version": "ridge@2026-09-04T22:12:49.750941+00:00",
   "snapshotted_at": "2026-09-25T06:14:44.664929+00:00",
   "backfilled": false
  },
  {
   "game_id": "2026_03_HOU_IND",
   "season": 2026,
   "week": 3,
   "home": "IND",
   "away": "HOU",
   "start_utc": "2026-09-27T17:00:00+00:00",
   "p_home": 0.2954260889601903,
   "margin_mu": -7.108787536621094,
   "sigma": 13.223153618916728,
   "total_mu": 45.890987396240234,
   "total_sigma": 12.486688413234214,
   "home_spread_line": -1.5,
   "total_line": 42.5,
   "model_version": "ridge@2026-09-04T22:12:49.750941+00:00",
   "snapshotted_at": "2026-09-25T06:14:44.664929+00:00",
   "backfilled": false
  },
  {
   "game_id": "2026_03_LA_DEN",
   "season": 2026,
   "week": 3,
   "home": "DEN",
   "away": "LA",
   "start_utc": "2026-09-28T00:20:00+00:00",
   "p_home": 0.5826741935023921,
   "margin_mu": 2.7601943016052246,
   "sigma": 13.223153618916728,
   "total_mu": 40.21767044067383,
   "total_sigma": 12.486688413234214,
   "home_spread_line": -2.5,
   "total_line": 44.5,
   "model_version": "ridge@2026-09-04T22:12:49.750941+00:00",
   "snapshotted_at": "2026-09-25T06:14:44.664929+00:00",
   "backfilled": false
  }
 ],
 "calibration": {
  "n_buckets": 10,
  "winner": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ],
  "spread": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ],
  "total": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ]
 }
}
```

`tests/fixtures/sports/cfb_kalshi_feed.json`:

```json
{
 "sport": "cfb",
 "generated_at": "2026-09-25T06:18:43.348709+00:00",
 "lead_hours": 48.0,
 "games": [
  {
   "game_id": "401862779",
   "season": 2026,
   "week": 4,
   "home": "Temple",
   "away": "Army",
   "start_utc": "2026-09-25T20:00:00+00:00",
   "p_home": 0.26327296776199627,
   "margin_mu": -10.75693200847774,
   "sigma": 16.98585958519707,
   "total_mu": 55.95640182495117,
   "total_sigma": 15.998238941965075,
   "home_spread_line": null,
   "total_line": null,
   "model_version": "ridge@2026-09-05T19:08:40.988453+00:00",
   "snapshotted_at": "2026-09-25T06:17:18.468857+00:00",
   "backfilled": false
  },
  {
   "game_id": "401858240",
   "season": 2026,
   "week": 4,
   "home": "Stanford",
   "away": "Georgia Tech",
   "start_utc": "2026-09-27T02:30:00+00:00",
   "p_home": 0.38168081520659514,
   "margin_mu": -5.113921305005669,
   "sigma": 16.98585958519707,
   "total_mu": 50.13958740234375,
   "total_sigma": 15.998238941965075,
   "home_spread_line": null,
   "total_line": null,
   "model_version": "ridge@2026-09-05T19:08:40.988453+00:00",
   "snapshotted_at": "2026-09-25T06:17:18.468857+00:00",
   "backfilled": false
  }
 ],
 "calibration": {
  "n_buckets": 10,
  "winner": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ],
  "spread": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ],
  "total": [
   {
    "lo": 0.0,
    "hi": 0.1,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.1,
    "hi": 0.2,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.2,
    "hi": 0.3,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.3,
    "hi": 0.4,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.4,
    "hi": 0.5,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.5,
    "hi": 0.6,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.6,
    "hi": 0.7,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.7,
    "hi": 0.8,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.8,
    "hi": 0.9,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   },
   {
    "lo": 0.9,
    "hi": 1.0,
    "n": 0,
    "mean_prob": null,
    "hit_rate": null
   }
  ]
 }
}
```

- [ ] **Step 2: Write the failing test**: `tests/test_sports_feed.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from tradehub.sports.feed import FeedUnavailable, fetch_feed, parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "sports"


def _raw(sport="nfl"):
    return json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())


def test_parse_recorded_nfl_feed():
    feed = parse_feed(_raw("nfl"))
    assert feed.sport == "nfl"
    assert [g.game_id for g in feed.games] == ["2026_03_CIN_PIT", "2026_03_HOU_IND", "2026_03_LA_DEN"]
    hou = feed.games[1]
    assert (hou.home, hou.away) == ("IND", "HOU")
    assert hou.start_utc == datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    assert hou.p_home == pytest.approx(0.2954260889601903)
    assert hou.sigma == pytest.approx(13.223153618916728)
    assert hou.snapshotted_at < hou.start_utc
    assert feed.rejected == []
    assert len(feed.calibration["winner"]) == 10


def test_parse_drops_backfilled_and_post_kickoff_rows():
    raw = _raw("nfl")
    raw["games"][0]["backfilled"] = True
    raw["games"][1]["snapshotted_at"] = "2026-09-27T17:05:00+00:00"   # after kickoff
    raw["games"][2]["p_home"] = 1.7
    feed = parse_feed(raw)
    assert feed.games == []
    assert sorted(r["reason"] for r in feed.rejected) == ["backfilled", "bad_probability", "snapshot_not_pregame"]


def test_parse_recorded_cfb_feed_has_no_lines_but_a_distribution():
    feed = parse_feed(_raw("cfb"))
    stanford = next(g for g in feed.games if g.home == "Stanford")
    assert stanford.away == "Georgia Tech"
    assert stanford.margin_mu is not None and stanford.total_sigma is not None


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_fetch_retries_once_after_a_cold_start_timeout():
    calls = []

    def get(url, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise requests.Timeout("scale-to-zero cold start")
        return _Resp(200, _raw("nfl"))

    feed = fetch_feed("https://nfl.example.com/", get=get, sleep=lambda s: None)
    assert len(feed.games) == 3
    assert calls == [("https://nfl.example.com/api/kalshi-feed", 60.0)] * 2


def test_fetch_gives_up_after_the_retry():
    def get(url, timeout):
        return _Resp(404)

    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example.com", get=get, sleep=lambda s: None)
```

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_feed.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.feed'`).

- [ ] **Step 3: Implement** `tradehub/sports/feed.py`:

```python
"""Client for a predictor's GET /api/kalshi-feed (frozen pre-game snapshots + calibration)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import requests

FEED_PATH = "/api/kalshi-feed"
TIMEOUT_SECONDS = 60.0
RETRY_PAUSE_SECONDS = 2.0


class FeedUnavailable(RuntimeError):
    """The predictor could not serve its feed (down, cold, or not deployed yet)."""


@dataclass(frozen=True)
class FeedGame:
    sport: str
    game_id: str
    home: str
    away: str
    start_utc: datetime
    p_home: float
    margin_mu: float | None
    sigma: float | None
    total_mu: float | None
    total_sigma: float | None
    model_version: str | None
    snapshotted_at: datetime
    season: int | None = None
    week: int | None = None


@dataclass(frozen=True)
class Feed:
    sport: str
    generated_at: datetime
    games: list[FeedGame]
    calibration: dict[str, list[dict[str, Any]]]
    rejected: list[dict[str, str]] = field(default_factory=list)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _opt(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_feed(raw: dict[str, Any]) -> Feed:
    """Validate the feed. Rows that are backfilled or not strictly pre-kickoff are
    dropped here too (defense in depth: the predictor already filters them)."""
    sport = raw["sport"]
    games: list[FeedGame] = []
    rejected: list[dict[str, str]] = []
    for row in raw.get("games") or []:
        game_id = str(row.get("game_id"))
        try:
            start, snapshotted = _utc(row["start_utc"]), _utc(row["snapshotted_at"])
            p_home = float(row["p_home"])
        except (KeyError, TypeError, ValueError):
            rejected.append({"game_id": game_id, "reason": "malformed"})
            continue
        if row.get("backfilled"):
            rejected.append({"game_id": game_id, "reason": "backfilled"})
        elif snapshotted >= start:
            rejected.append({"game_id": game_id, "reason": "snapshot_not_pregame"})
        elif not 0.0 <= p_home <= 1.0:
            rejected.append({"game_id": game_id, "reason": "bad_probability"})
        else:
            games.append(FeedGame(
                sport=sport, game_id=game_id, home=row["home"], away=row["away"], start_utc=start,
                p_home=p_home, margin_mu=_opt(row.get("margin_mu")), sigma=_opt(row.get("sigma")),
                total_mu=_opt(row.get("total_mu")), total_sigma=_opt(row.get("total_sigma")),
                model_version=row.get("model_version"), snapshotted_at=snapshotted,
                season=row.get("season"), week=row.get("week"),
            ))
    calibration = raw.get("calibration") or {}
    return Feed(
        sport=sport,
        generated_at=_utc(raw["generated_at"]),
        games=games,
        calibration={k: calibration.get(k) or [] for k in ("winner", "spread", "total")},
        rejected=rejected,
    )


def fetch_feed(
    base_url: str, *, get: Callable[..., Any] = requests.get, sleep: Callable[[float], None] = time.sleep,
    timeout: float = TIMEOUT_SECONDS,
) -> Feed:
    """GET the feed with one retry: scale-to-zero predictors can time out on the first request."""
    url = base_url.rstrip("/") + FEED_PATH
    last_error: Exception | None = None
    for attempt in range(2):
        if attempt:
            sleep(RETRY_PAUSE_SECONDS)
        try:
            resp = get(url, timeout=timeout)
            resp.raise_for_status()
            return parse_feed(resp.json())
        except (requests.RequestException, ValueError, KeyError) as exc:
            last_error = exc
    raise FeedUnavailable(f"{url}: {last_error}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_feed.py` → Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/feed.py tests/test_sports_feed.py tests/fixtures/sports/nfl_kalshi_feed.json tests/fixtures/sports/cfb_kalshi_feed.json
git commit -m "feat(sports): predictor pre-game feed client with leakage re-check and warm-up retry

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Kalshi sports markets and game-to-event mapping

**Files:**
- Create: `tradehub/sports/kalshi.py`, `tradehub/sports/mapping.py`, `tradehub/sports/aliases/nfl.json`, `tradehub/sports/aliases/cfb.json`, `tests/fixtures/sports/nfl_open_markets.json`, `tests/fixtures/sports/cfb_open_markets.json`
- Test: `tests/test_sports_kalshi.py`, `tests/test_sports_mapping.py` (new)

**Interfaces:**
- Consumes: `KalshiHistoryClient._paginate`, `quote_from_market_raw`, `parse_market`; `FeedGame` (Task 3).
- Produces:
  - `SportsMarket(market: KalshiMarket, quote: Quote, volume: float, suffix: str)`, `parse_sports_market(raw)`, `team_code(sm) -> str | None`, and `SportsKalshi(...).open_markets(series) -> list[SportsMarket]`.
  - `Aliases(version, teams)` and `load_aliases(sport)`.
  - `kalshi_date(start_utc) -> "26OCT01"`.
  - `MatchedGame(game, home_code, away_code, suffix, markets: {kind: [SportsMarket]}, date_shift_days=0)`.
  - `MatchReport(matched, unmatched_games: [(game_id, reason)], unmatched_events: [event_ticker])`.
  - `match_games(games, markets_by_series, series, aliases) -> MatchReport`.

**Kalshi facts** (public API, 2026-09-25):
- Event = `<SERIES>-<ET date %y%b%d><AWAY><HOME>`, e.g. `KXNFLGAME-26SEP27LARDEN`. Kickoff 00:15Z Friday is dated Thursday.
- Market suffix: team code (winner), code + ceil(strike) (spread: `IND8` = "wins by over 7.5"), or ceil(strike) (total).
- Codes differ from the predictors: NFL `JAX→JAC`, `LA→LAR`. CFB uses full school names, e.g. `South Alabama→USA`, `Miami→MIA`, `Miami (OH)→MOH`. That last one was `M-OH` in 2025, so codes drift and the alias table is versioned.
- Kalshi codes are not unique across seasons (`WSU` = Washington St. and Winona State), so matching always needs both teams and the date.
- `cfb.json` maps all **235** team names that appear in CFB_Predictor weeks 1–5, including FCS opponents. It was built from 2026 `KXNCAAFGAME` markets by normalized name (221 automatically, 14 by hand), and every code was seen in a 2026 market.

- [ ] **Step 1: Add the data files and fixtures**

`tradehub/sports/aliases/nfl.json`:

```json
{
 "version": "2026-09-25",
 "source": "Kalshi KXNFLGAME open markets 2026-09-25; predictor codes are nflverse",
 "teams": {
  "ARI": "ARI",
  "ATL": "ATL",
  "BAL": "BAL",
  "BUF": "BUF",
  "CAR": "CAR",
  "CHI": "CHI",
  "CIN": "CIN",
  "CLE": "CLE",
  "DAL": "DAL",
  "DEN": "DEN",
  "DET": "DET",
  "GB": "GB",
  "HOU": "HOU",
  "IND": "IND",
  "JAX": "JAC",
  "KC": "KC",
  "LA": "LAR",
  "LAC": "LAC",
  "LV": "LV",
  "MIA": "MIA",
  "MIN": "MIN",
  "NE": "NE",
  "NO": "NO",
  "NYG": "NYG",
  "NYJ": "NYJ",
  "PHI": "PHI",
  "PIT": "PIT",
  "SEA": "SEA",
  "SF": "SF",
  "TB": "TB",
  "TEN": "TEN",
  "WAS": "WAS"
 }
}
```

`tradehub/sports/aliases/cfb.json`:

```json
{
 "version": "2026-09-25",
 "source": "Kalshi KXNCAAFGAME 2026 markets (yes_sub_title -> ticker suffix); predictor names from CFB_Predictor /api/games weeks 1-5",
 "teams": {
  "Abilene Christian": "AC",
  "Air Force": "AFA",
  "Akron": "AKR",
  "Alabama": "ALA",
  "Alabama State": "ALST",
  "Alcorn State": "ALCN",
  "App State": "APP",
  "Arizona": "ARIZ",
  "Arizona State": "ASU",
  "Arkansas": "ARK",
  "Arkansas State": "ARST",
  "Arkansas-Pine Bluff": "ARPB",
  "Army": "ARMY",
  "Auburn": "AUB",
  "Austin Peay": "PEAY",
  "BYU": "BYU",
  "Ball State": "BALL",
  "Baylor": "BAY",
  "Bethune-Cookman": "COOK",
  "Boise State": "BSU",
  "Boston College": "BC",
  "Bowling Green": "BGSU",
  "Bryant": "BRY",
  "Bucknell": "BUCK",
  "Buffalo": "BUFF",
  "Cal Poly": "CP",
  "California": "CAL",
  "Campbell": "CAMP",
  "Central Arkansas": "CARK",
  "Central Connecticut": "CCSU",
  "Central Michigan": "CMU",
  "Charleston Southern": "CHSO",
  "Charlotte": "CHAR",
  "Cincinnati": "CIN",
  "Clemson": "CLEM",
  "Coastal Carolina": "CCAR",
  "Colgate": "COLG",
  "Colorado": "COLO",
  "Colorado State": "CSU",
  "Delaware": "DEL",
  "Delaware State": "DSU",
  "Duke": "DUKE",
  "Duquesne": "DUQ",
  "East Carolina": "ECU",
  "East Tennessee State": "ETSU",
  "East Texas A&M": "ETAM",
  "Eastern Illinois": "EIU",
  "Eastern Kentucky": "EKY",
  "Eastern Michigan": "EMU",
  "Eastern Washington": "EWU",
  "Florida": "FLA",
  "Florida A&M": "FAMU",
  "Florida Atlantic": "FAU",
  "Florida International": "FIU",
  "Florida State": "FSU",
  "Fordham": "FOR",
  "Fresno State": "FRES",
  "Furman": "FUR",
  "Gardner-Webb": "WEBB",
  "Georgia": "UGA",
  "Georgia Southern": "GASO",
  "Georgia State": "GAST",
  "Georgia Tech": "GT",
  "Grambling": "GRAM",
  "Hampton": "HAMP",
  "Hawai'i": "HAW",
  "Holy Cross": "HC",
  "Houston": "HOU",
  "Houston Christian": "HCU",
  "Howard": "HOW",
  "Idaho": "IDHO",
  "Idaho State": "IDST",
  "Illinois": "ILL",
  "Illinois State": "ILST",
  "Incarnate Word": "IW",
  "Indiana": "IND",
  "Indiana State": "INST",
  "Iowa": "IOWA",
  "Iowa State": "ISU",
  "Jacksonville State": "JVST",
  "James Madison": "JMU",
  "Kansas": "KU",
  "Kansas State": "KSU",
  "Kennesaw State": "KENN",
  "Kent State": "KENT",
  "Kentucky": "UK",
  "LSU": "LSU",
  "Lafayette": "LAF",
  "Lamar": "LAM",
  "Liberty": "LIB",
  "Lindenwood": "LINW",
  "Long Island University": "LIU",
  "Louisiana": "ULL",
  "Louisiana Tech": "LT",
  "Louisville": "LOU",
  "Maine": "ME",
  "Marshall": "MRSH",
  "Maryland": "MD",
  "Massachusetts": "MASS",
  "McNeese": "MCNS",
  "Memphis": "MEM",
  "Mercer": "MER",
  "Mercyhurst": "MHU",
  "Merrimack": "MRMK",
  "Miami": "MIA",
  "Miami (OH)": "MOH",
  "Michigan": "MICH",
  "Michigan State": "MSU",
  "Middle Tennessee": "MTU",
  "Minnesota": "MINN",
  "Mississippi State": "MSST",
  "Mississippi Valley State": "MVSU",
  "Missouri": "MIZZ",
  "Missouri State": "MOSU",
  "Monmouth": "MONM",
  "Montana": "MONT",
  "Montana State": "MTST",
  "Morgan State": "MORG",
  "Murray State": "MURR",
  "NC State": "NCST",
  "Navy": "NAVY",
  "Nebraska": "NEB",
  "Nevada": "NEV",
  "New Hampshire": "UNH",
  "New Mexico": "UNM",
  "New Mexico State": "NMSU",
  "Nicholls": "NICH",
  "Norfolk State": "NORF",
  "North Alabama": "UNA",
  "North Carolina": "UNC",
  "North Carolina A&T": "NCAT",
  "North Carolina Central": "NCCU",
  "North Dakota": "UND",
  "North Dakota State": "NDSU",
  "North Texas": "UNT",
  "Northern Arizona": "NAU",
  "Northern Colorado": "UNCO",
  "Northern Illinois": "NIU",
  "Northern Iowa": "UNI",
  "Northwestern": "NW",
  "Northwestern State": "NWST",
  "Notre Dame": "ND",
  "Ohio": "OHIO",
  "Ohio State": "OSU",
  "Oklahoma": "OKLA",
  "Oklahoma State": "OKST",
  "Old Dominion": "ODU",
  "Ole Miss": "MISS",
  "Oregon": "ORE",
  "Oregon State": "ORST",
  "Penn State": "PSU",
  "Pittsburgh": "PITT",
  "Portland State": "PRST",
  "Prairie View A&M": "PV",
  "Purdue": "PUR",
  "Rhode Island": "URI",
  "Rice": "RICE",
  "Richmond": "RICH",
  "Robert Morris": "RMU",
  "Rutgers": "RUTG",
  "SE Louisiana": "SELA",
  "SMU": "SMU",
  "Sacramento State": "SAC",
  "Sacred Heart": "SHU",
  "Sam Houston": "SHSU",
  "Samford": "SAM",
  "San Diego State": "SDSU",
  "San Jos\u00e9 State": "SJSU",
  "South Alabama": "USA",
  "South Carolina": "SCAR",
  "South Dakota": "SDAK",
  "South Dakota State": "SDST",
  "South Florida": "USF",
  "Southeast Missouri State": "SEMO",
  "Southern": "SOU",
  "Southern Illinois": "SIU",
  "Southern Miss": "USM",
  "Southern Utah": "SUU",
  "Stanford": "STAN",
  "Stonehill": "STNH",
  "Stony Brook": "STON",
  "Syracuse": "SYR",
  "TCU": "TCU",
  "Tarleton State": "TARL",
  "Temple": "TEM",
  "Tennessee": "TENN",
  "Tennessee State": "TNST",
  "Texas": "TEX",
  "Texas A&M": "TXAM",
  "Texas Southern": "TXSO",
  "Texas State": "TXST",
  "Texas Tech": "TTU",
  "The Citadel": "CIT",
  "Toledo": "TOL",
  "Towson": "TOWS",
  "Troy": "TROY",
  "Tulane": "TULN",
  "Tulsa": "TLSA",
  "UAB": "UAB",
  "UAlbany": "ALBY",
  "UC Davis": "UCD",
  "UCF": "UCF",
  "UCLA": "UCLA",
  "UConn": "CONN",
  "UL Monroe": "ULM",
  "UNLV": "UNLV",
  "USC": "USC",
  "UT Martin": "UTM",
  "UT Rio Grande Valley": "UTRGV",
  "UTEP": "UTEP",
  "UTSA": "UTSA",
  "Utah": "UTAH",
  "Utah State": "USU",
  "Utah Tech": "UTU",
  "VMI": "VMI",
  "Vanderbilt": "VAN",
  "Villanova": "VILL",
  "Virginia": "UVA",
  "Virginia Tech": "VT",
  "Wagner": "WAG",
  "Wake Forest": "WAKE",
  "Washington": "WASH",
  "Washington State": "WSU",
  "Weber State": "WEB",
  "West Georgia": "UWGA",
  "West Virginia": "WVU",
  "Western Carolina": "WCU",
  "Western Illinois": "WIU",
  "Western Kentucky": "WKU",
  "Western Michigan": "WMU",
  "William & Mary": "WM",
  "Wisconsin": "WIS",
  "Wofford": "WOF",
  "Wyoming": "WYO",
  "Youngstown State": "YSU"
 }
}
```

`tests/fixtures/sports/nfl_open_markets.json` (recorded, trimmed):

```json
{
 "KXNFLGAME": [
  {
   "ticker": "KXNFLGAME-26SEP27CINPIT-CIN",
   "event_ticker": "KXNFLGAME-26SEP27CINPIT",
   "title": "Cincinnati wins",
   "yes_sub_title": "Cincinnati",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.6200",
   "yes_ask_dollars": "0.6300",
   "yes_bid_size_fp": "160450.21",
   "yes_ask_size_fp": "681682.98",
   "volume_fp": "202012.72",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27CINPIT-PIT",
   "event_ticker": "KXNFLGAME-26SEP27CINPIT",
   "title": "Pittsburgh wins",
   "yes_sub_title": "Pittsburgh",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.3700",
   "yes_ask_dollars": "0.3800",
   "yes_bid_size_fp": "70872.13",
   "yes_ask_size_fp": "975774.07",
   "volume_fp": "62095.51",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27HOUIND-HOU",
   "event_ticker": "KXNFLGAME-26SEP27HOUIND",
   "title": "Houston wins",
   "yes_sub_title": "Houston",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.5400",
   "yes_ask_dollars": "0.5500",
   "yes_bid_size_fp": "29205.71",
   "yes_ask_size_fp": "1402590.49",
   "volume_fp": "65188.63",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27HOUIND-IND",
   "event_ticker": "KXNFLGAME-26SEP27HOUIND",
   "title": "Indianapolis wins",
   "yes_sub_title": "Indianapolis",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.4500",
   "yes_ask_dollars": "0.4600",
   "yes_bid_size_fp": "193146.08",
   "yes_ask_size_fp": "22552.45",
   "volume_fp": "68812.96",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27KCMIA-KC",
   "event_ticker": "KXNFLGAME-26SEP27KCMIA",
   "title": "Kansas City wins",
   "yes_sub_title": "Kansas City",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:15:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.8500",
   "yes_ask_dollars": "0.8600",
   "yes_bid_size_fp": "974818.48",
   "yes_ask_size_fp": "6230796.22",
   "volume_fp": "805175.95",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27KCMIA-MIA",
   "event_ticker": "KXNFLGAME-26SEP27KCMIA",
   "title": "Miami wins",
   "yes_sub_title": "Miami",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:15:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.1400",
   "yes_ask_dollars": "0.1500",
   "yes_bid_size_fp": "136694.50",
   "yes_ask_size_fp": "474126.31",
   "volume_fp": "246784.70",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27LARDEN-DEN",
   "event_ticker": "KXNFLGAME-26SEP27LARDEN",
   "title": "Denver wins",
   "yes_sub_title": "Denver",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-30T00:20:00Z",
   "yes_bid_dollars": "0.4400",
   "yes_ask_dollars": "0.4500",
   "yes_bid_size_fp": "290762.93",
   "yes_ask_size_fp": "25387.21",
   "volume_fp": "104315.03",
   "status": "active"
  },
  {
   "ticker": "KXNFLGAME-26SEP27LARDEN-LAR",
   "event_ticker": "KXNFLGAME-26SEP27LARDEN",
   "title": "Los Angeles R wins",
   "yes_sub_title": "Los Angeles R",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-15T16:16:00Z",
   "close_time": "2026-09-30T00:20:00Z",
   "yes_bid_dollars": "0.5500",
   "yes_ask_dollars": "0.5600",
   "yes_bid_size_fp": "26051.34",
   "yes_ask_size_fp": "1149060.37",
   "volume_fp": "76727.64",
   "status": "active"
  }
 ],
 "KXNFLSPREAD": [
  {
   "ticker": "KXNFLSPREAD-26SEP27HOUIND-HOU3",
   "event_ticker": "KXNFLSPREAD-26SEP27HOUIND",
   "title": "HOU Texans wins by over 2.5 points?",
   "yes_sub_title": "HOU Texans wins by over 2.5 points",
   "strike_type": "greater",
   "floor_strike": 2.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.4700",
   "yes_ask_dollars": "0.4800",
   "yes_bid_size_fp": "377833.37",
   "yes_ask_size_fp": "307223.73",
   "volume_fp": "48468.08",
   "status": "active"
  },
  {
   "ticker": "KXNFLSPREAD-26SEP27HOUIND-HOU7",
   "event_ticker": "KXNFLSPREAD-26SEP27HOUIND",
   "title": "HOU Texans wins by over 6.5 points?",
   "yes_sub_title": "HOU Texans wins by over 6.5 points",
   "strike_type": "greater",
   "floor_strike": 6.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.3100",
   "yes_ask_dollars": "0.3300",
   "yes_bid_size_fp": "1484.51",
   "yes_ask_size_fp": "868.73",
   "volume_fp": "182.84",
   "status": "active"
  },
  {
   "ticker": "KXNFLSPREAD-26SEP27HOUIND-IND3",
   "event_ticker": "KXNFLSPREAD-26SEP27HOUIND",
   "title": "IND Colts wins by over 2.5 points?",
   "yes_sub_title": "IND Colts wins by over 2.5 points",
   "strike_type": "greater",
   "floor_strike": 2.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.4000",
   "yes_ask_dollars": "0.4200",
   "yes_bid_size_fp": "14541.60",
   "yes_ask_size_fp": "36012.76",
   "volume_fp": "724.26",
   "status": "active"
  },
  {
   "ticker": "KXNFLSPREAD-26SEP27HOUIND-IND8",
   "event_ticker": "KXNFLSPREAD-26SEP27HOUIND",
   "title": "IND Colts wins by over 7.5 points?",
   "yes_sub_title": "IND Colts wins by over 7.5 points",
   "strike_type": "greater",
   "floor_strike": 7.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.2000",
   "yes_ask_dollars": "0.2100",
   "yes_bid_size_fp": "1875.77",
   "yes_ask_size_fp": "1265.00",
   "volume_fp": "19.86",
   "status": "active"
  }
 ],
 "KXNFLTOTAL": [
  {
   "ticker": "KXNFLTOTAL-26SEP27HOUIND-43",
   "event_ticker": "KXNFLTOTAL-26SEP27HOUIND",
   "title": "Full Game: over 42.5 points scored?",
   "yes_sub_title": "Over 42.5 points scored",
   "strike_type": "greater",
   "floor_strike": 42.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.5100",
   "yes_ask_dollars": "0.5200",
   "yes_bid_size_fp": "4088.06",
   "yes_ask_size_fp": "18631.39",
   "volume_fp": "1577.98",
   "status": "active"
  },
  {
   "ticker": "KXNFLTOTAL-26SEP27HOUIND-46",
   "event_ticker": "KXNFLTOTAL-26SEP27HOUIND",
   "title": "Full Game: over 45.5 points scored?",
   "yes_sub_title": "Over 45.5 points scored",
   "strike_type": "greater",
   "floor_strike": 45.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.4000",
   "yes_ask_dollars": "0.4100",
   "yes_bid_size_fp": "25290.97",
   "yes_ask_size_fp": "61.60",
   "volume_fp": "63.60",
   "status": "active"
  },
  {
   "ticker": "KXNFLTOTAL-26SEP27HOUIND-49",
   "event_ticker": "KXNFLTOTAL-26SEP27HOUIND",
   "title": "Full Game: over 48.5 points scored?",
   "yes_sub_title": "Over 48.5 points scored",
   "strike_type": "greater",
   "floor_strike": 48.5,
   "cap_strike": null,
   "open_time": "2026-09-21T07:05:00Z",
   "close_time": "2026-09-29T17:00:00Z",
   "yes_bid_dollars": "0.3200",
   "yes_ask_dollars": "0.3400",
   "yes_bid_size_fp": "1606.75",
   "yes_ask_size_fp": "1.00",
   "volume_fp": "2.00",
   "status": "active"
  }
 ]
}
```

`tests/fixtures/sports/cfb_open_markets.json` (recorded, trimmed):

```json
{
 "KXNCAAFGAME": [
  {
   "ticker": "KXNCAAFGAME-26SEP25ARMYTEM-ARMY",
   "event_ticker": "KXNCAAFGAME-26SEP25ARMYTEM",
   "title": "Army wins",
   "yes_sub_title": "Army",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-11T22:07:00Z",
   "close_time": "2026-09-27T20:00:00Z",
   "yes_bid_dollars": "0.5800",
   "yes_ask_dollars": "0.5900",
   "yes_bid_size_fp": "57647.35",
   "yes_ask_size_fp": "119581.41",
   "volume_fp": "28504.63",
   "status": "active"
  },
  {
   "ticker": "KXNCAAFGAME-26SEP25ARMYTEM-TEM",
   "event_ticker": "KXNCAAFGAME-26SEP25ARMYTEM",
   "title": "Temple wins",
   "yes_sub_title": "Temple",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-11T22:07:00Z",
   "close_time": "2026-09-27T20:00:00Z",
   "yes_bid_dollars": "0.4100",
   "yes_ask_dollars": "0.4200",
   "yes_bid_size_fp": "5809.00",
   "yes_ask_size_fp": "399855.72",
   "volume_fp": "10744.19",
   "status": "active"
  },
  {
   "ticker": "KXNCAAFGAME-26SEP26GTSTAN-GT",
   "event_ticker": "KXNCAAFGAME-26SEP26GTSTAN",
   "title": "Georgia Tech wins",
   "yes_sub_title": "Georgia Tech",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-13T04:08:00Z",
   "close_time": "2026-09-29T02:30:00Z",
   "yes_bid_dollars": "0.6100",
   "yes_ask_dollars": "0.6200",
   "yes_bid_size_fp": "83.00",
   "yes_ask_size_fp": "273667.27",
   "volume_fp": "1201.63",
   "status": "active"
  },
  {
   "ticker": "KXNCAAFGAME-26SEP26GTSTAN-STAN",
   "event_ticker": "KXNCAAFGAME-26SEP26GTSTAN",
   "title": "Stanford wins",
   "yes_sub_title": "Stanford",
   "strike_type": "structured",
   "floor_strike": null,
   "cap_strike": null,
   "open_time": "2026-09-13T04:08:00Z",
   "close_time": "2026-09-29T02:30:00Z",
   "yes_bid_dollars": "0.3800",
   "yes_ask_dollars": "0.3900",
   "yes_bid_size_fp": "100541.49",
   "yes_ask_size_fp": "41.00",
   "volume_fp": "1493.87",
   "status": "active"
  }
 ],
 "KXNCAAFSPREAD": [],
 "KXNCAAFTOTAL": []
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_sports_kalshi.py`:

```python
import json
from pathlib import Path

import pytest

from tradehub.sports.kalshi import SportsKalshi, parse_sports_market, team_code

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
OPEN = json.loads((FIXTURES / "nfl_open_markets.json").read_text())


def test_parse_winner_market():
    raw = next(m for m in OPEN["KXNFLGAME"] if m["ticker"] == "KXNFLGAME-26SEP27LARDEN-LAR")
    sm = parse_sports_market(raw)
    assert sm.market.series_ticker == "KXNFLGAME"
    assert sm.suffix == "LAR"
    assert team_code(sm) == "LAR"
    assert sm.quote.yes_bid is not None and sm.quote.yes_ask is not None
    assert sm.volume > 0


def test_parse_spread_and_total_suffixes():
    spread = parse_sports_market(next(m for m in OPEN["KXNFLSPREAD"] if m["ticker"].endswith("-IND8")))
    total = parse_sports_market(OPEN["KXNFLTOTAL"][0])
    assert (spread.suffix, team_code(spread), spread.market.floor_strike) == ("IND8", "IND", 7.5)
    assert total.market.strike_type == "greater" and team_code(total) is None


def test_open_markets_pages_through_the_public_api():
    pages = {None: {"markets": OPEN["KXNFLGAME"][:2], "cursor": "c1"}, "c1": {"markets": OPEN["KXNFLGAME"][2:], "cursor": ""}}
    seen = []

    def get_json(url, params):
        seen.append((url, params.get("series_ticker"), params.get("status")))
        return pages[params.get("cursor")]

    markets = SportsKalshi(get_json=get_json).open_markets("KXNFLGAME")
    assert len(markets) == len(OPEN["KXNFLGAME"])
    assert seen[0] == ("https://api.elections.kalshi.com/trade-api/v2/markets", "KXNFLGAME", "open")


@pytest.mark.parametrize("suffix,expected", [("HOU10", "HOU"), ("M-OH", "M-OH"), ("67", None)])
def test_team_code_strips_the_strike(suffix, expected):
    sm = parse_sports_market(dict(OPEN["KXNFLTOTAL"][0], ticker=f"KXNFLTOTAL-26SEP27HOUIND-{suffix}"))
    assert team_code(sm) == expected
```

`tests/test_sports_mapping.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.mapping import kalshi_date, load_aliases, match_games

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
SERIES = {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}


def _markets(sport):
    raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
    return {series: [parse_sports_market(m) for m in ms] for series, ms in raw.items()}


def test_kalshi_date_is_the_eastern_date_of_kickoff():
    # Thursday night kickoff 00:15Z Friday is still Thursday in New York.
    assert kalshi_date(datetime(2026, 10, 2, 0, 15, tzinfo=timezone.utc)) == "26OCT01"
    assert kalshi_date(datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)) == "26SEP27"


def test_alias_tables_are_versioned_and_cover_known_code_mismatches():
    nfl, cfb = load_aliases("nfl"), load_aliases("cfb")
    assert nfl.version == "2026-09-25" and len(nfl.teams) == 32
    assert (nfl.teams["JAX"], nfl.teams["LA"]) == ("JAC", "LAR")
    assert len(cfb.teams) >= 233
    assert cfb.teams["Miami"] == "MIA" and cfb.teams["Miami (OH)"] == "MOH"
    assert cfb.teams["South Alabama"] == "USA" and cfb.teams["New Mexico State"] == "NMSU"


def test_match_nfl_fixture_games_including_the_rams_alias():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    report = match_games(feed.games, _markets("nfl"), SERIES, load_aliases("nfl"))
    assert {m.game.game_id: m.suffix for m in report.matched} == {
        "2026_03_CIN_PIT": "26SEP27CINPIT", "2026_03_HOU_IND": "26SEP27HOUIND", "2026_03_LA_DEN": "26SEP27LARDEN",
    }
    la = next(m for m in report.matched if m.game.game_id == "2026_03_LA_DEN")
    assert (la.home_code, la.away_code) == ("DEN", "LAR")
    hou = next(m for m in report.matched if m.game.game_id == "2026_03_HOU_IND")
    assert sorted(m.market.ticker for m in hou.markets["spread"]) == [
        "KXNFLSPREAD-26SEP27HOUIND-HOU3", "KXNFLSPREAD-26SEP27HOUIND-HOU7",
        "KXNFLSPREAD-26SEP27HOUIND-IND3", "KXNFLSPREAD-26SEP27HOUIND-IND8",
    ]
    assert len(hou.markets["total"]) == 3 and len(hou.markets["winner"]) == 2
    assert report.unmatched_games == []
    assert report.unmatched_events == ["KXNFLGAME-26SEP27KCMIA"]   # no feed game for it


def test_unknown_team_and_missing_event_are_reported_not_guessed():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    games = [g.__class__(**{**g.__dict__, "home": "XXX"}) if g.game_id == "2026_03_CIN_PIT" else g for g in feed.games]
    markets = _markets("nfl")
    markets["KXNFLGAME"] = [m for m in markets["KXNFLGAME"] if "LARDEN" not in m.market.ticker]
    report = match_games(games, markets, SERIES, load_aliases("nfl"))
    assert sorted(report.unmatched_games) == [
        ("2026_03_CIN_PIT", "no_alias:XXX"), ("2026_03_LA_DEN", "no_kalshi_event:26SEP27LARDEN"),
    ]
    assert [m.game.game_id for m in report.matched] == ["2026_03_HOU_IND"]


def test_match_cfb_fixture_by_full_school_names():
    feed = parse_feed(json.loads((FIXTURES / "cfb_kalshi_feed.json").read_text()))
    report = match_games(feed.games, _markets("cfb"),
                         {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
                         load_aliases("cfb"))
    assert {m.game.home: m.suffix for m in report.matched} == {"Stanford": "26SEP26GTSTAN", "Temple": "26SEP25ARMYTEM"}


def test_placeholder_kickoff_times_match_the_adjacent_kalshi_date():
    """ESPN lists TBD late kickoffs as 03:59Z (23:59 ET the day before); Kalshi dates the event by the
    real kickoff. The same two teams one day apart is the same game, so +-1 day is accepted and reported."""
    feed = parse_feed(json.loads((FIXTURES / "cfb_kalshi_feed.json").read_text()))
    stanford = next(g for g in feed.games if g.home == "Stanford")
    moved = stanford.__class__(**{**stanford.__dict__, "start_utc": datetime(2026, 9, 26, 3, 59, tzinfo=timezone.utc)})
    report = match_games([moved], _markets("cfb"),
                         {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
                         load_aliases("cfb"))
    assert [(m.suffix, m.date_shift_days) for m in report.matched] == [("26SEP26GTSTAN", 1)]
```

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_kalshi.py tests/test_sports_mapping.py`
Expected: `2 errors` (`ModuleNotFoundError: No module named 'tradehub.sports.kalshi'`).

- [ ] **Step 3: Implement**

`tradehub/sports/kalshi.py`:

```python
"""Open Kalshi sports markets (public API) with quote, volume and the ticker suffix after the event."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from tradehub.backtest.kalshi_history import PAGE_LIMIT, KalshiHistoryClient
from tradehub.data.kalshi_live import quote_from_market_raw
from tradehub.edges import Quote
from tradehub.markets import KalshiMarket, parse_market


@dataclass(frozen=True)
class SportsMarket:
    market: KalshiMarket
    quote: Quote
    volume: float
    suffix: str   # after "<event>-": team code (winner), team code + strike (spread), strike (total)


def parse_sports_market(raw: dict[str, Any]) -> SportsMarket:
    ticker, event = raw["ticker"], raw["event_ticker"]
    return SportsMarket(
        market=parse_market(raw),
        quote=quote_from_market_raw(raw),
        volume=float(raw.get("volume_fp") or 0.0),
        suffix=ticker[len(event) + 1:],
    )


def team_code(sm: SportsMarket) -> str | None:
    """'LAR' -> 'LAR', 'IND8' -> 'IND', '67' (a total) -> None."""
    code = re.sub(r"\d+$", "", sm.suffix)
    return code or None


class SportsKalshi(KalshiHistoryClient):
    def open_markets(self, series_ticker: str) -> list[SportsMarket]:
        raws = self._paginate("/markets", "markets", {"series_ticker": series_ticker, "status": "open", "limit": PAGE_LIMIT})
        return [parse_sports_market(r) for r in raws]
```

`tradehub/sports/mapping.py`:

```python
"""Game -> Kalshi event mapping: versioned alias tables, ET-date event suffixes, honest unmatched reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tradehub.sports.feed import FeedGame
from tradehub.sports.kalshi import SportsMarket

ALIASES_DIR = Path(__file__).resolve().parent / "aliases"
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Aliases:
    version: str
    teams: dict[str, str]   # predictor team name/code -> Kalshi code


@dataclass(frozen=True)
class MatchedGame:
    game: FeedGame
    home_code: str
    away_code: str
    suffix: str                                   # e.g. "26SEP27HOUIND"
    markets: dict[str, list[SportsMarket]]        # kind -> markets of this game's event
    date_shift_days: int = 0                      # Kalshi event date minus the feed's ET kickoff date


@dataclass
class MatchReport:
    matched: list[MatchedGame] = field(default_factory=list)
    unmatched_games: list[tuple[str, str]] = field(default_factory=list)   # (game_id, reason)
    unmatched_events: list[str] = field(default_factory=list)              # winner events with no feed game


def load_aliases(sport: str) -> Aliases:
    raw = json.loads((ALIASES_DIR / f"{sport}.json").read_text(encoding="utf-8"))
    return Aliases(version=raw["version"], teams=dict(raw["teams"]))


def kalshi_date(start_utc: datetime) -> str:
    """Kalshi dates game events by the US Eastern calendar day of kickoff: '26OCT01'."""
    return start_utc.astimezone(EASTERN).strftime("%y%b%d").upper()


def _by_suffix(markets: list[SportsMarket]) -> dict[str, list[SportsMarket]]:
    grouped: dict[str, list[SportsMarket]] = {}
    for sm in markets:
        grouped.setdefault(sm.market.event_ticker.split("-", 1)[1], []).append(sm)
    return grouped


def match_games(
    games: list[FeedGame], markets_by_series: dict[str, list[SportsMarket]], series: dict[str, str], aliases: Aliases,
) -> MatchReport:
    """Build each game's event suffix (ET date + away + home; home-first accepted too) and look it up
    in the open markets. Anything that doesn't line up exactly is reported, never guessed."""
    grouped = {kind: _by_suffix(markets_by_series.get(s, [])) for kind, s in series.items()}
    report = MatchReport()
    claimed: set[str] = set()
    for game in games:
        home, away = aliases.teams.get(game.home), aliases.teams.get(game.away)
        missing = [name for name, code in ((game.home, home), (game.away, away)) if code is None]
        if missing:
            report.unmatched_games.append((game.game_id, f"no_alias:{missing[0]}"))
            continue
        # Same ET day first; then +-1 day, because placeholder kickoff times (ESPN's 03:59Z "TBD")
        # can land on the wrong day. The same two teams a day apart are the same game.
        candidates = [
            (shift, f"{kalshi_date(game.start_utc + timedelta(days=shift))}{a}{b}")
            for shift in (0, 1, -1) for a, b in ((away, home), (home, away))
        ]
        found = next(((shift, c) for shift, c in candidates if any(c in g for g in grouped.values())), None)
        if found is None:
            report.unmatched_games.append((game.game_id, f"no_kalshi_event:{candidates[0][1]}"))
            continue
        shift, suffix = found
        claimed.add(suffix)
        report.matched.append(MatchedGame(
            game=game, home_code=home, away_code=away, suffix=suffix,
            markets={kind: grouped[kind].get(suffix, []) for kind in series}, date_shift_days=shift,
        ))
    feed_days = {kalshi_date(g.start_utc + timedelta(days=d)) for g in games for d in (0, 1, -1)}
    report.unmatched_events = sorted(
        f"{series['winner']}-{s}" for s in grouped["winner"] if s not in claimed and s[:7] in feed_days
    )
    return report
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_kalshi.py tests/test_sports_mapping.py` → Expected: `12 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/kalshi.py tradehub/sports/mapping.py tradehub/sports/aliases tests/test_sports_kalshi.py tests/test_sports_mapping.py tests/fixtures/sports/nfl_open_markets.json tests/fixtures/sports/cfb_open_markets.json
git commit -m "feat(sports): Kalshi sports markets and versioned game-to-event mapping

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: Pricing Kalshi markets from the predictor's distribution

**Files:**
- Create: `tradehub/sports/pricing.py`
- Test: `tests/test_sports_pricing.py` (new)

**Interfaces:**
- Consumes: `prob_in_interval(mu, sigma, (lo, hi))`, `team_code`, `MatchedGame`.
- Produces:
  - `price_market(kind, sm, mg) -> float | None`, the YES probability. It returns `None` when the distribution is missing or the strike is not `greater`.
  - `home_oriented(kind, sm, mg, yes_prob) -> float`: away-team winner/spread markets flip to the home view that the calibration buckets use.

- [ ] **Step 1: Write the failing test**: `tests/test_sports_pricing.py`:

```python
import json
from pathlib import Path

import pytest

from tradehub.markets import prob_in_interval
from tradehub.sports.feed import parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.mapping import load_aliases, match_games
from tradehub.sports.pricing import home_oriented, price_market

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
SERIES = {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}


@pytest.fixture
def hou_ind():
    feed = parse_feed(json.loads((FIXTURES / "nfl_kalshi_feed.json").read_text()))
    raw = json.loads((FIXTURES / "nfl_open_markets.json").read_text())
    markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}
    report = match_games(feed.games, markets, SERIES, load_aliases("nfl"))
    return next(m for m in report.matched if m.game.game_id == "2026_03_HOU_IND")


def _market(mg, kind, suffix):
    return next(m for m in mg.markets[kind] if m.suffix == suffix)


def test_winner_prices_are_the_predictors_own_probability(hou_ind):
    g = hou_ind.game
    assert price_market("winner", _market(hou_ind, "winner", "IND"), hou_ind) == pytest.approx(g.p_home)
    assert price_market("winner", _market(hou_ind, "winner", "HOU"), hou_ind) == pytest.approx(1 - g.p_home)


def test_spread_uses_the_margin_distribution_at_kalshis_strike(hou_ind):
    g = hou_ind.game   # IND home, margin_mu about -7.1
    ind8 = price_market("spread", _market(hou_ind, "spread", "IND8"), hou_ind)
    hou7 = price_market("spread", _market(hou_ind, "spread", "HOU7"), hou_ind)
    assert ind8 == pytest.approx(prob_in_interval(g.margin_mu, g.sigma, (7.5, float("inf"))))
    assert hou7 == pytest.approx(prob_in_interval(g.margin_mu, g.sigma, (float("-inf"), -6.5)))
    assert hou7 > 0.5 > ind8


def test_total_uses_the_total_distribution(hou_ind):
    g = hou_ind.game
    over46 = price_market("total", _market(hou_ind, "total", "46"), hou_ind)
    assert over46 == pytest.approx(prob_in_interval(g.total_mu, g.total_sigma, (45.5, float("inf"))))


def test_no_distribution_means_no_price(hou_ind):
    game = hou_ind.game.__class__(**{**hou_ind.game.__dict__, "sigma": None, "total_sigma": None})
    mg = hou_ind.__class__(**{**hou_ind.__dict__, "game": game})
    assert price_market("spread", _market(mg, "spread", "IND8"), mg) is None
    assert price_market("total", _market(mg, "total", "46"), mg) is None
    assert price_market("winner", _market(mg, "winner", "IND"), mg) == pytest.approx(game.p_home)


def test_home_oriented_flips_away_team_markets(hou_ind):
    assert home_oriented("winner", _market(hou_ind, "winner", "HOU"), hou_ind, 0.7) == pytest.approx(0.3)
    assert home_oriented("spread", _market(hou_ind, "spread", "IND8"), hou_ind, 0.2) == pytest.approx(0.2)
    assert home_oriented("total", _market(hou_ind, "total", "46"), hou_ind, 0.6) == pytest.approx(0.6)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_pricing.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.pricing'`).

- [ ] **Step 3: Implement** `tradehub/sports/pricing.py`:

```python
"""YES probability for each Kalshi sports market from the predictor's frozen distribution.

The hub never models sports: winner markets use the predictor's own p_home; spread and
total markets evaluate its Normal(margin_mu, sigma) / Normal(total_mu, total_sigma) at
Kalshi's half-point strikes (so no continuity correction is needed).
"""

from __future__ import annotations

import math

from tradehub.markets import prob_in_interval
from tradehub.sports.kalshi import SportsMarket, team_code
from tradehub.sports.mapping import MatchedGame


def price_market(kind: str, sm: SportsMarket, mg: MatchedGame) -> float | None:
    game = mg.game
    code = team_code(sm)
    if kind == "winner":
        if code == mg.home_code:
            return game.p_home
        if code == mg.away_code:
            return 1.0 - game.p_home
        return None
    strike = sm.market.floor_strike
    if sm.market.strike_type != "greater" or strike is None:
        return None
    if kind == "spread":
        if game.margin_mu is None or not game.sigma:
            return None
        if code == mg.home_code:   # home wins by more than the strike
            return prob_in_interval(game.margin_mu, game.sigma, (strike, math.inf))
        if code == mg.away_code:   # away wins by more than the strike
            return prob_in_interval(game.margin_mu, game.sigma, (-math.inf, -strike))
        return None
    if kind == "total":
        if game.total_mu is None or not game.total_sigma:
            return None
        return prob_in_interval(game.total_mu, game.total_sigma, (strike, math.inf))
    return None


def home_oriented(kind: str, sm: SportsMarket, mg: MatchedGame, yes_prob: float) -> float:
    """The YES probability restated the way the predictor's calibration buckets are keyed:
    home win / home cover / over. Away-team markets flip."""
    if kind in ("winner", "spread") and team_code(sm) == mg.away_code:
        return 1.0 - yes_prob
    return yes_prob
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_pricing.py` → Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/pricing.py tests/test_sports_pricing.py
git commit -m "feat(sports): price winner/spread/total markets from the predictor distribution

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Deterministic candidate filter

**Files:**
- Create: `tradehub/sports/candidates.py`
- Test: `tests/test_sports_candidates.py` (new)

**Interfaces:**
- Consumes: `EdgeSuggestion` (from `evaluate_edge`), `SportsMarket`, `MatchedGame`, `home_oriented`, the feed's `calibration`, `SportConfig.edge.params`.
- Produces:
  - `CandidateCheck(ok: bool, reasons: tuple[str, ...], bucket: dict | None)`.
  - `bucket_for(buckets, prob)`.
  - `check_candidate(kind, sm, mg, edge, calibration, params, now) -> CandidateCheck`.
  - The reasons, in this order: `wide_quote`, `thin_book`, `low_volume`, `starts_too_soon` or `starts_too_late`, then `calibration_insufficient` or `calibration_off`.

- [ ] **Step 1: Write the failing test**: `tests/test_sports_candidates.py`:

```python
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from tradehub.edges import EdgeSuggestion, Quote
from tradehub.markets import parse_market
from tradehub.sports.candidates import bucket_for, check_candidate
from tradehub.sports.feed import FeedGame
from tradehub.sports.kalshi import SportsMarket
from tradehub.sports.mapping import MatchedGame

NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)
PARAMS = {"max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000, "min_hours_to_start": 1,
          "max_hours_to_start": 72, "calibration_max_dev": 0.10, "calibration_min_n": 20}


def _buckets(n=30, mean=0.35, hit=0.33):
    return [{"lo": i / 10, "hi": (i + 1) / 10, "n": n if i == 3 else 0,
             "mean_prob": mean if i == 3 else None, "hit_rate": hit if i == 3 else None} for i in range(10)]


GAME = FeedGame(sport="nfl", game_id="2026_03_HOU_IND", home="IND", away="HOU",
                start_utc=NOW + timedelta(hours=29), p_home=0.35, margin_mu=-4.0, sigma=13.0, total_mu=45.0,
                total_sigma=12.0, model_version="ridge@t", snapshotted_at=NOW - timedelta(hours=10))
MARKET = SportsMarket(
    market=parse_market({"ticker": "KXNFLGAME-26SEP27HOUIND-IND", "event_ticker": "KXNFLGAME-26SEP27HOUIND",
                         "strike_type": "structured", "open_time": "2026-09-15T16:00:00Z",
                         "close_time": "2026-09-29T17:00:00Z", "title": "IND wins"}),
    quote=Quote(yes_bid=0.27, yes_ask=0.28, yes_bid_size=5000.0, yes_ask_size=4000.0), volume=50000.0, suffix="IND")
MG = MatchedGame(game=GAME, home_code="IND", away_code="HOU", suffix="26SEP27HOUIND", markets={})
EDGE = EdgeSuggestion("KXNFLGAME-26SEP27HOUIND-IND", "yes", 0.27, True, 7.5, 0.35, 0.275)


def test_a_liquid_calibrated_market_is_a_candidate():
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _buckets()}, PARAMS, NOW)
    assert check.ok is True and check.reasons == ()
    assert check.bucket["lo"] == 0.3


def test_every_failed_rule_is_named():
    thin = replace(MARKET, quote=Quote(yes_bid=0.20, yes_ask=0.28, yes_bid_size=5.0, yes_ask_size=4000.0), volume=10.0)
    late = replace(MG, game=replace(GAME, start_utc=NOW + timedelta(minutes=30)))
    check = check_candidate("winner", thin, late, EDGE, {"winner": _buckets(mean=0.35, hit=0.20)}, PARAMS, NOW)
    assert check.ok is False
    assert check.reasons == ("wide_quote", "thin_book", "low_volume", "starts_too_soon", "calibration_off")


def test_too_few_graded_snapshots_is_not_calibrated():
    check = check_candidate("winner", MARKET, MG, EDGE, {"winner": _buckets(n=5)}, PARAMS, NOW)
    assert check.reasons == ("calibration_insufficient",)


def test_away_team_market_uses_the_home_oriented_bucket():
    away = replace(MARKET, suffix="HOU")
    edge = replace(EDGE, our_prob=0.65)       # P(HOU wins) = 1 - 0.35
    check = check_candidate("winner", away, MG, edge, {"winner": _buckets()}, PARAMS, NOW)
    assert check.ok and check.bucket["lo"] == 0.3


def test_bucket_for_edges():
    buckets = _buckets()
    assert bucket_for(buckets, 1.0)["lo"] == 0.9
    assert bucket_for(buckets, 0.3)["lo"] == 0.3
    assert bucket_for([], 0.5) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_candidates.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.candidates'`).

- [ ] **Step 3: Implement** `tradehub/sports/candidates.py`:

```python
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
    elif abs(bucket["mean_prob"] - bucket["hit_rate"]) > params["calibration_max_dev"]:
        reasons.append("calibration_off")
    return CandidateCheck(ok=not reasons, reasons=tuple(reasons), bucket=bucket)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_candidates.py` → Expected: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/candidates.py tests/test_sports_candidates.py
git commit -m "feat(sports): deterministic candidate filter (liquidity, timing, calibration bucket)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 7: LLM reviewer and the `sports_reviews` cache table

**Files:**
- Create: `tradehub/sports/reviewer.py`, `market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql`, `tests/fixtures/sports/openrouter_ok.json`, `tests/fixtures/sports/openrouter_flagged.json`, `tests/fixtures/sports/openrouter_bad.json`
- Test: `tests/test_sports_reviewer.py`, `tests/test_sports_reviews_migration.py` (new)

**Interfaces:**
- Produces:
  - `REVIEW_SCHEMA`.
  - `Review(status, explainable, drivers, red_flags, model)`, where `status` is one of `ok|invalid|error|skipped_budget|no_key`. It has no probability field.
  - `ReviewRequest(key, sport, game_id, market_ticker, side, entry_price, price_bucket, our_prob, net_edge_pct, fact_pack)`.
  - `parse_review(content, model=None)`, `tier(review) -> "top_pick"|"flagged"|"unreviewed"`, `price_bucket(price, cents)`, `cache_key(...)`.
  - `OpenRouterReviewer(api_key, model, timeout, post=requests.post).review(fact_pack) -> Review`.
  - The `ReviewStore` protocol, `SupabaseReviewStore(supa, now=...)` and `MemoryReviewStore()`.
  - `review_candidates(reqs, store, reviewer | None, *, budget, now) -> {key: Review}`.
- The migration number `20260416000008` follows 2b's `20260416000007`.

- [ ] **Step 1: Add the fixtures.** These are **hand-built** in OpenRouter's documented chat-completion shape; no key was available to record real ones. Task 11 Step 3 records one live.

`tests/fixtures/sports/openrouter_ok.json`:

```json
{
 "id": "gen-fixture-ok",
 "provider": "fixture",
 "model": "nvidia/nemotron-3-super-120b-a12b:free",
 "object": "chat.completion",
 "created": 1790000000,
 "choices": [
  {
   "index": 0,
   "finish_reason": "stop",
   "message": {
    "role": "assistant",
    "content": "{\"explainable\": true, \"drivers\": [\"Predictor margin -7.1 vs a market pricing IND near a pick'em\", \"Predictor calibrated within 2pp in the 0.2-0.3 bucket\"], \"red_flags\": []}"
   }
  }
 ],
 "usage": {"prompt_tokens": 612, "completion_tokens": 58, "total_tokens": 670}
}
```

`tests/fixtures/sports/openrouter_flagged.json`:

```json
{
 "id": "gen-fixture-flagged",
 "model": "nvidia/nemotron-3-super-120b-a12b:free",
 "choices": [
  {
   "index": 0,
   "finish_reason": "stop",
   "message": {
    "role": "assistant",
    "content": "{\"explainable\": true, \"drivers\": [\"Large predicted margin\"], \"red_flags\": [\"Snapshot is 40h old; a late quarterback injury would not be in it\"]}"
   }
  }
 ]
}
```

`tests/fixtures/sports/openrouter_bad.json`:

```json
{
 "id": "gen-fixture-bad",
 "model": "nvidia/nemotron-3-super-120b-a12b:free",
 "choices": [
  {
   "index": 0,
   "finish_reason": "stop",
   "message": {"role": "assistant", "content": "Sure! Here is my review: {\"explainable\": true, \"probability\": 0.61"}
  }
 ]
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_sports_reviewer.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from tradehub.sports.reviewer import (
    REVIEW_SCHEMA, OpenRouterReviewer, Review, ReviewRequest, SupabaseReviewStore, cache_key, parse_review,
    price_bucket, review_candidates, tier,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)


def _content(name):
    return json.loads((FIXTURES / name).read_text())["choices"][0]["message"]["content"]


def _request(ticker="KXNFLGAME-26SEP27HOUIND-IND", price=0.27):
    bucket = price_bucket(price, 5)
    return ReviewRequest(
        key=cache_key("nfl", "2026_03_HOU_IND", ticker, "yes", bucket), sport="nfl", game_id="2026_03_HOU_IND",
        market_ticker=ticker, side="yes", entry_price=price, price_bucket=bucket, our_prob=0.35, net_edge_pct=7.5,
        fact_pack={"sport": "nfl", "market": {"ticker": ticker}},
    )


def test_schema_is_strict_and_has_no_probability_field():
    assert REVIEW_SCHEMA["additionalProperties"] is False
    assert set(REVIEW_SCHEMA["required"]) == {"explainable", "drivers", "red_flags"}
    assert "probability" not in json.dumps(REVIEW_SCHEMA)


def test_parse_recorded_reviews():
    ok = parse_review(_content("openrouter_ok.json"))
    flagged = parse_review(_content("openrouter_flagged.json"))
    assert ok.status == "ok" and ok.explainable is True and len(ok.drivers) == 2 and ok.red_flags == ()
    assert flagged.status == "ok" and flagged.red_flags
    assert (tier(ok), tier(flagged)) == ("top_pick", "flagged")


@pytest.mark.parametrize("content", [
    "not json",
    '{"explainable": true, "drivers": []}',                                        # missing red_flags
    '{"explainable": "yes", "drivers": [], "red_flags": []}',                      # wrong type
    '{"explainable": true, "drivers": [], "red_flags": [], "probability": 0.7}',   # tries to add a number
    '{"explainable": true, "drivers": [1], "red_flags": []}',
])
def test_malformed_output_falls_back_to_unreviewed(content):
    review = parse_review(content)
    assert review.status == "invalid"
    assert tier(review) == "unreviewed"


def test_price_bucket_and_cache_key():
    assert price_bucket(0.27, 5) == 5 and price_bucket(0.30, 5) == 6 and price_bucket(0.994, 5) == 19
    assert cache_key("nfl", "g", "T", "no", 5) == "nfl:g:T:no:5"


class _Resp:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def test_openrouter_request_shape_and_parse():
    sent = {}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json, timeout=timeout)
        return _Resp(200, __import__("json").loads((FIXTURES / "openrouter_ok.json").read_text()))

    reviewer = OpenRouterReviewer(api_key="test-key-not-real", model="m:free", timeout=60, post=post)
    review = reviewer.review({"sport": "nfl"})
    assert review.status == "ok" and review.model == "m:free"
    assert sent["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-key-not-real"
    body = sent["body"]
    assert body["model"] == "m:free" and body["temperature"] == 0
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["provider"] == {"require_parameters": True}
    assert '"sport": "nfl"' in body["messages"][1]["content"]


def test_openrouter_errors_never_raise():
    def post(url, headers, json, timeout):
        return _Resp(429, {"error": {"message": "rate limited"}})

    review = OpenRouterReviewer(api_key="k", model="m", timeout=5, post=post).review({})
    assert review.status == "error" and tier(review) == "unreviewed"


class _FakeStore:
    def __init__(self, cached=None, used=0):
        self.cached_reviews = cached or {}
        self.used = used
        self.saved = []

    def cached(self, key):
        return self.cached_reviews.get(key)

    def calls_since(self, since):
        return self.used

    def save(self, request, review):
        self.saved.append((request.key, review.status))


class _FakeReviewer:
    model = "m:free"

    def __init__(self):
        self.calls = 0

    def review(self, fact_pack):
        self.calls += 1
        return parse_review(_content("openrouter_ok.json"))


def test_cache_hit_skips_the_call():
    req = _request()
    hit = Review(status="ok", explainable=True, drivers=("cached",), red_flags=(), model="m")
    reviewer = _FakeReviewer()
    out = review_candidates([req], _FakeStore(cached={req.key: hit}), reviewer, budget=40, now=NOW)
    assert out[req.key] == hit and reviewer.calls == 0


def test_daily_budget_is_enforced_and_every_call_is_saved():
    reqs = [_request(f"T{i}") for i in range(3)]
    store, reviewer = _FakeStore(used=39), _FakeReviewer()
    out = review_candidates(reqs, store, reviewer, budget=40, now=NOW)
    assert reviewer.calls == 1
    assert [out[r.key].status for r in reqs] == ["ok", "skipped_budget", "skipped_budget"]
    assert store.saved == [(reqs[0].key, "ok")]


def test_no_api_key_means_unreviewed_not_blocked():
    req = _request()
    out = review_candidates([req], _FakeStore(), None, budget=40, now=NOW)
    assert out[req.key].status == "no_key" and tier(out[req.key]) == "unreviewed"


def test_reviewing_never_changes_the_probability():
    req = _request()
    before = req.our_prob
    review_candidates([req], _FakeStore(), _FakeReviewer(), budget=40, now=NOW)
    assert req.our_prob == before
    assert not any("prob" in f for f in Review.__dataclass_fields__)


class _Query:
    def __init__(self, table):
        self.table, self.filters, self.inserted = table, [], None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.filters.append(("eq", col, val))
        return self

    def gte(self, col, val):
        self.filters.append(("gte", col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, _n):
        return self

    def insert(self, row):
        self.inserted = row
        self.table.rows.append(row)
        return self

    def execute(self):
        if self.inserted is not None:
            return type("R", (), {"data": [self.inserted]})()
        rows = [r for r in self.table.rows if all(
            (r.get(c) == v) if op == "eq" else (r.get(c) >= v) for op, c, v in self.filters)]
        return type("R", (), {"data": rows})()


class _Table:
    def __init__(self):
        self.rows = []


class _Supa:
    def __init__(self):
        self.t = _Table()

    def table(self, name):
        assert name == "sports_reviews"
        return _Query(self.t)


def test_supabase_store_round_trip():
    supa = _Supa()
    store = SupabaseReviewStore(supa, now=lambda: NOW)
    req = _request()
    store.save(req, Review(status="invalid", explainable=None, drivers=(), red_flags=(), model="m"))
    assert store.cached(req.key) is None                    # failures are counted, never served
    store.save(req, parse_review(_content("openrouter_ok.json")))
    assert store.cached(req.key).explainable is True
    assert store.calls_since(datetime(2026, 9, 26, tzinfo=timezone.utc)) == 2
    assert supa.t.rows[0]["created_at"] == NOW.isoformat()
```

`tests/test_sports_reviews_migration.py`:

```python
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql"
)


def test_sports_reviews_migration():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS sports_reviews" in sql
    for column in ("cache_key", "market_ticker", "side", "price_bucket", "entry_price", "our_prob", "model",
                   "status", "explainable", "drivers", "red_flags", "created_at"):
        assert column in sql
    assert "CHECK (status IN ('ok', 'invalid', 'error'))" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FOR SELECT" in sql and "FOR ALL" not in sql      # writes come only from the service-role scan
    assert "sports_reviews_cache_key_idx" in sql and "sports_reviews_created_at_idx" in sql
```

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_reviewer.py tests/test_sports_reviews_migration.py`
Expected: `1 failed, 1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.reviewer'`; `FileNotFoundError` for the migration).

- [ ] **Step 3: Implement**

`tradehub/sports/reviewer.py`:

```python
"""LLM reviewer (spec §3.2 stage 2): an OpenRouter free model reads a public fact pack for each
candidate and answers strict JSON {explainable, drivers, red_flags}. It never produces or changes
a probability; any failure leaves the edge "unreviewed" and never blocks it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import requests

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REVIEWS_TABLE = "sports_reviews"

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explainable": {"type": "boolean"},
        "drivers": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "red_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["explainable", "drivers", "red_flags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You review a sports prediction-market edge for a human trader. You get a fact pack: a predictor's "
    "frozen pre-game probability and point distribution, the Kalshi price, and how well calibrated the "
    "predictor has been in this probability range. Decide whether the gap between the predictor and the "
    "market is explainable from these facts. List the concrete drivers from the fact pack. List red flags: "
    "anything that could make the predictor stale or wrong that the fact pack cannot show (injuries, "
    "lineup news, weather, how old the snapshot is). Never give a probability or a number of your own. "
    "Answer with JSON only."
)


@dataclass(frozen=True)
class Review:
    status: str                    # ok | invalid | error | skipped_budget | no_key
    explainable: bool | None
    drivers: tuple[str, ...]
    red_flags: tuple[str, ...]
    model: str | None = None


@dataclass(frozen=True)
class ReviewRequest:
    key: str
    sport: str
    game_id: str
    market_ticker: str
    side: str
    entry_price: float
    price_bucket: int
    our_prob: float
    net_edge_pct: float
    fact_pack: dict[str, Any]


def _unreviewed(status: str, model: str | None = None) -> Review:
    return Review(status=status, explainable=None, drivers=(), red_flags=(), model=model)


def parse_review(content: str, model: str | None = None) -> Review:
    """Validate the model's answer against REVIEW_SCHEMA by hand (never trust the provider)."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return _unreviewed("invalid", model)
    if not isinstance(data, dict) or set(data) != {"explainable", "drivers", "red_flags"}:
        return _unreviewed("invalid", model)
    explainable, drivers, flags = data["explainable"], data["drivers"], data["red_flags"]
    if not isinstance(explainable, bool):
        return _unreviewed("invalid", model)
    for items in (drivers, flags):
        if not isinstance(items, list) or len(items) > 5 or not all(isinstance(i, str) for i in items):
            return _unreviewed("invalid", model)
    return Review(status="ok", explainable=explainable, drivers=tuple(drivers), red_flags=tuple(flags), model=model)


def tier(review: Review | None) -> str:
    """Top Pick only when reviewed, explainable and free of red flags (spec §3.2)."""
    if review is None or review.status != "ok":
        return "unreviewed"
    if review.explainable and not review.red_flags:
        return "top_pick"
    return "flagged"


def price_bucket(entry_price: float, cents: int) -> int:
    return int(round(entry_price * 100)) // cents


def cache_key(sport: str, game_id: str, market_ticker: str, side: str, bucket: int) -> str:
    return f"{sport}:{game_id}:{market_ticker}:{side}:{bucket}"


class OpenRouterReviewer:
    def __init__(self, api_key: str, model: str, timeout: float, post: Callable[..., Any] = requests.post):
        self._key, self.model, self._timeout, self._post = api_key, model, timeout, post

    def review(self, fact_pack: dict[str, Any]) -> Review:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(fact_pack, sort_keys=True)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "sports_edge_review", "strict": True, "schema": REVIEW_SCHEMA},
            },
            # Only route to providers that honour response_format; the free router may otherwise ignore it.
            "provider": {"require_parameters": True},
        }
        try:
            resp = self._post(OPENROUTER_URL, headers={"Authorization": f"Bearer {self._key}"}, json=body,
                              timeout=self._timeout)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
            return _unreviewed("error", self.model)
        return parse_review(content, self.model)


class ReviewStore(Protocol):
    def cached(self, key: str) -> Review | None: ...
    def calls_since(self, since: datetime) -> int: ...
    def save(self, request: ReviewRequest, review: Review) -> None: ...


class SupabaseReviewStore:
    """Append-only `sports_reviews` table: every API call is one row (so the daily count is exact);
    only status='ok' rows are served from the cache. Supabase, not a local file, because the VPS
    scan runs in a throwaway container with no volume."""

    def __init__(self, supa, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._supa, self._now = supa, now

    def cached(self, key: str) -> Review | None:
        rows = (self._supa.table(REVIEWS_TABLE).select("*").eq("cache_key", key).eq("status", "ok")
                .order("created_at", desc=True).limit(1).execute().data or [])
        if not rows:
            return None
        row = rows[0]
        return Review(status="ok", explainable=bool(row["explainable"]), drivers=tuple(row["drivers"] or []),
                      red_flags=tuple(row["red_flags"] or []), model=row.get("model"))

    def calls_since(self, since: datetime) -> int:
        return len(self._supa.table(REVIEWS_TABLE).select("id").gte("created_at", since.isoformat()).execute().data or [])

    def save(self, request: ReviewRequest, review: Review) -> None:
        self._supa.table(REVIEWS_TABLE).insert({
            "cache_key": request.key, "sport": request.sport, "game_id": request.game_id,
            "market_ticker": request.market_ticker, "side": request.side, "entry_price": request.entry_price,
            "price_bucket": request.price_bucket, "our_prob": round(request.our_prob, 4),
            "model": review.model, "status": review.status, "explainable": review.explainable,
            "drivers": list(review.drivers), "red_flags": list(review.red_flags),
            "created_at": self._now().isoformat(),
        }).execute()


def review_candidates(
    reqs: list[ReviewRequest], store: ReviewStore, reviewer: OpenRouterReviewer | None, *, budget: int, now: datetime,
) -> dict[str, Review]:
    """Cache first, then call the model for the largest edges until today's UTC budget is spent."""
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = store.calls_since(day_start) if reviewer is not None else 0
    out: dict[str, Review] = {}
    for req in sorted(reqs, key=lambda r: r.net_edge_pct, reverse=True):
        if req.key in out:
            continue
        hit = store.cached(req.key)
        if hit is not None:
            out[req.key] = hit
        elif reviewer is None:
            out[req.key] = _unreviewed("no_key")
        elif used >= budget:
            out[req.key] = _unreviewed("skipped_budget")
        else:
            review = reviewer.review(req.fact_pack)
            used += 1
            store.save(req, review)
            out[req.key] = review
    return out


class MemoryReviewStore:
    """In-process store for dry runs and tests: nothing is persisted."""

    def __init__(self):
        self._rows: list[tuple[str, datetime, Review]] = []

    def cached(self, key: str) -> Review | None:
        return next((r for k, _, r in reversed(self._rows) if k == key and r.status == "ok"), None)

    def calls_since(self, since: datetime) -> int:
        return sum(1 for _, at, _ in self._rows if at >= since)

    def save(self, request: ReviewRequest, review: Review) -> None:
        self._rows.append((request.key, datetime.now(timezone.utc), review))
```

`market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql`:

```sql
-- LLM reviewer cache and call log for sports edges (rollout step 7, spec section 3.2).
-- Append-only: one row per OpenRouter call, so the daily budget count is exact.
-- Only status='ok' rows are served as cached reviews (key: sport:game:market:side:price bucket).
-- Idempotent, like the earlier migrations. Apply after 20260416000007.

CREATE TABLE IF NOT EXISTS sports_reviews (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  cache_key     text NOT NULL,
  sport         text NOT NULL,
  game_id       text NOT NULL,
  market_ticker text NOT NULL,
  side          text NOT NULL CHECK (side IN ('yes', 'no')),
  price_bucket  integer NOT NULL,
  entry_price   numeric(5,4) NOT NULL,
  our_prob      numeric(5,4) NOT NULL,
  model         text,
  status        text NOT NULL CHECK (status IN ('ok', 'invalid', 'error')),
  explainable   boolean,
  drivers       jsonb NOT NULL DEFAULT '[]'::jsonb,
  red_flags     jsonb NOT NULL DEFAULT '[]'::jsonb,
  created_at    timestamptz NOT NULL DEFAULT now(),
  user_id       uuid REFERENCES auth.users(id)
);
CREATE INDEX IF NOT EXISTS sports_reviews_cache_key_idx ON sports_reviews (cache_key, status);
CREATE INDEX IF NOT EXISTS sports_reviews_created_at_idx ON sports_reviews (created_at);

-- The scan job writes with the service role (bypasses RLS); the War Room reads through the API.
ALTER TABLE sports_reviews ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "sports_reviews_owner_read" ON sports_reviews;
CREATE POLICY "sports_reviews_owner_read" ON sports_reviews FOR SELECT
  USING (auth.uid() = user_id);
```

- [ ] **Step 4: Run the tests to verify they pass, and apply the migration twice**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_reviewer.py tests/test_sports_reviews_migration.py` → Expected: `16 passed`

Idempotency check on a throwaway Postgres (needs Docker; skip it and say so in the report if Docker is unavailable):

```bash
docker run -d --rm --name pg7 -e POSTGRES_PASSWORD=x postgres:16 >/dev/null
until docker exec pg7 pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec -i pg7 psql -q -v ON_ERROR_STOP=1 -U postgres <<'EOF'
CREATE SCHEMA auth; CREATE TABLE auth.users (id uuid PRIMARY KEY);
CREATE FUNCTION auth.uid() RETURNS uuid LANGUAGE sql AS 'select null::uuid';
EOF
for n in 1 2; do docker exec -i pg7 psql -q -v ON_ERROR_STOP=1 -U postgres < market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql && echo "applied $n"; done
docker exec pg7 psql -U postgres -c "select polname, polcmd from pg_policy where polrelid='sports_reviews'::regclass"
docker stop pg7
```
Expected: `applied 1`, `applied 2` (the second pass only prints "already exists, skipping" notices), then one policy, `sports_reviews_owner_read | r`.

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/reviewer.py market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql tests/test_sports_reviewer.py tests/test_sports_reviews_migration.py tests/fixtures/sports/openrouter_ok.json tests/fixtures/sports/openrouter_flagged.json tests/fixtures/sports/openrouter_bad.json
git commit -m "feat(sports): OpenRouter reviewer with strict JSON, per-market cache and daily budget

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 8: Sports scan, predictions ledger, cron wiring, settlement engines

**Files:**
- Create: `tradehub/sports/scan.py`
- Modify: `tradehub/scripts/scan.py`, `tradehub/scripts/settle_predictions.py`, `tests/test_settle_predictions.py`
- Test: `tests/test_sports_scan.py` (new)

**Interfaces:**
- Consumes: everything from Tasks 1–7, plus `evaluate_edge`, `build_prediction_row`, `upsert_opportunities` (which already accepts `SPORTS` and `source_url`) and `record_predictions`.
- Produces:
  - `SportScan(predictions, edges, review_requests, report)` and `scan_sport(cfg, markets_by_series, feed, now)`.
  - `apply_reviews(edges, reviews)`.
  - `SportsRun(predictions, edges, reports)` and `run_sports_scan(now, kalshi, *, fetch=fetch_feed, store=None, reviewer=None, budget=0, sports=("nfl","cfb"))`.
  - `unrecorded(supa, rows)`, `sports_due(now)` and `run_sports_for_cron(now, supa) -> (predictions, edges, summary)`.
  - The dry-run CLI, `python -m tradehub.sports.scan --dry-run [--sport nfl]`.
  - Edge rows (which `upsert_opportunities` stores whole as `raw_payload`) carry: `market_ticker, market_title, market_price, model_probability, edge, edge_type="SPORTS", market_url, source_url, side, entry_price, maker, sport, kind, game_id, home, away, start_utc, snapshotted_at, model_version, candidate, reject_reasons, calibration_bucket, tier, review`, and `review_key` for candidates only.
  - `settle_predictions.ENGINES` gains `("sports_nfl", "daily")` and `("sports_cfb", "daily")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_sports_scan.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tradehub.sports import scan as sports_scan
from tradehub.sports.config import load_sport_config
from tradehub.sports.feed import FeedUnavailable, parse_feed
from tradehub.sports.kalshi import parse_sports_market
from tradehub.sports.reviewer import Review

FIXTURES = Path(__file__).parent / "fixtures" / "sports"
NOW = datetime(2026, 9, 26, 12, 0, tzinfo=timezone.utc)   # Sunday 17:00Z games are 29h out


def _feed(sport, calibrated=True):
    raw = json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())
    if calibrated:   # the recorded feed has no graded pre-game history yet; pretend it is calibrated
        for kind in ("winner", "spread", "total"):
            for b in raw["calibration"][kind]:
                mid = round(b["lo"] + 0.05, 2)
                b.update(n=40, mean_prob=mid, hit_rate=mid)
    return parse_feed(raw)


class FakeKalshi:
    def __init__(self, sport):
        raw = json.loads((FIXTURES / f"{sport}_open_markets.json").read_text())
        self.markets = {s: [parse_sports_market(m) for m in ms] for s, ms in raw.items()}
        self.asked = []

    def open_markets(self, series):
        self.asked.append(series)
        return self.markets.get(series, [])


def test_scan_sport_predicts_matched_markets_and_flags_edges():
    cfg = load_sport_config("nfl")
    kalshi = FakeKalshi("nfl")
    result = sports_scan.scan_sport(cfg, kalshi.markets, _feed("nfl"), NOW)

    assert result.report["matched"] == 3 and result.report["unmatched_events"] == ["KXNFLGAME-26SEP27KCMIA"]
    tickers = {p["market_ticker"] for p in result.predictions}
    assert "KXNFLGAME-26SEP27HOUIND-IND" in tickers and "KXNFLSPREAD-26SEP27HOUIND-IND8" in tickers
    assert "KXNFLGAME-26SEP27KCMIA-KC" not in tickers
    pred = next(p for p in result.predictions if p["market_ticker"] == "KXNFLGAME-26SEP27HOUIND-IND")
    assert pred["engine"] == "sports_nfl"
    assert pred["engine_version"] == "feed:ridge@2026-09-04T22:12:49.750941+00:00"
    assert pred["our_prob"] == pytest.approx(0.2954, abs=1e-4)
    assert pred["raw_payload"]["game_id"] == "2026_03_HOU_IND" and pred["raw_payload"]["kind"] == "winner"

    assert result.edges, "the recorded HOU@IND prices leave an edge against the predictor"
    for edge in result.edges:
        assert edge["edge_type"] == "SPORTS"
        assert edge["market_url"].startswith("https://kalshi.com/markets/kxnfl")
        assert edge["source_url"] == (f"{cfg.site_url}/?sport=nfl&game={edge['game_id']}")
        assert edge["tier"] in ("filtered", "unreviewed")
        assert edge["candidate"] == (edge["reject_reasons"] == [])
    assert len(result.review_requests) == sum(e["candidate"] for e in result.edges)


def test_uncalibrated_feed_produces_edges_but_no_candidates():
    result = sports_scan.scan_sport(load_sport_config("nfl"), FakeKalshi("nfl").markets, _feed("nfl", calibrated=False), NOW)
    assert result.edges and result.review_requests == []
    assert all("calibration_insufficient" in e["reject_reasons"] for e in result.edges)


def test_apply_reviews_sets_tiers_without_touching_probabilities():
    result = sports_scan.scan_sport(load_sport_config("nfl"), FakeKalshi("nfl").markets, _feed("nfl"), NOW)
    assert result.review_requests
    before = [e["model_probability"] for e in result.edges]
    key = result.review_requests[0].key
    reviews = {key: Review(status="ok", explainable=True, drivers=("margin",), red_flags=(), model="m")}
    sports_scan.apply_reviews(result.edges, reviews)
    reviewed = next(e for e in result.edges if e.get("review_key") == key)
    assert reviewed["tier"] == "top_pick" and reviewed["review"]["drivers"] == ["margin"]
    assert [e["model_probability"] for e in result.edges] == before


def test_run_sports_scan_reports_a_down_predictor_and_keeps_going():
    kalshi = FakeKalshi("cfb")

    def fetch(base_url):
        if "nfl" in base_url:
            raise FeedUnavailable("404")
        return _feed("cfb")

    out = sports_scan.run_sports_scan(NOW, kalshi, fetch=fetch)
    assert out.reports["nfl"] == {"feed_error": "404"}
    assert out.reports["cfb"]["matched"] == 2
    assert all(p["engine"] == "sports_cfb" for p in out.predictions)
    assert all(e["tier"] != "top_pick" for e in out.edges)   # no reviewer configured


def test_unrecorded_drops_markets_already_in_the_ledger():
    class Q:
        def __init__(self, parent):
            self.parent, self.tickers = parent, []

        def select(self, *_a):
            return self

        def eq(self, col, val):
            assert (col, val) == ("engine", "sports_nfl")
            return self

        def in_(self, col, values):
            self.tickers = list(values)
            self.parent.chunks.append(len(values))
            return self

        def execute(self):
            return type("R", (), {"data": [{"market_ticker": t} for t in self.tickers if t.endswith("-OLD")]})()

    class Supa:
        chunks = []

        def table(self, name):
            assert name == "predictions"
            return Q(self)

    rows = [{"market_ticker": f"T{i}", "engine": "sports_nfl"} for i in range(150)] + [
        {"market_ticker": "X-OLD", "engine": "sports_nfl"}]
    supa = Supa()
    kept = sports_scan.unrecorded(supa, rows)
    assert len(kept) == 150 and all(not r["market_ticker"].endswith("-OLD") for r in kept)
    assert supa.chunks == [100, 51]


@pytest.mark.parametrize("hour,due", [(0, True), (3, True), (4, False), (23, False)])
def test_sports_run_every_third_hour(hour, due, monkeypatch):
    monkeypatch.delenv("SPORTS_SCAN_EVERY_RUN", raising=False)
    assert sports_scan.sports_due(NOW.replace(hour=hour)) is due


def test_sports_due_env_override(monkeypatch):
    monkeypatch.setenv("SPORTS_SCAN_EVERY_RUN", "1")
    assert sports_scan.sports_due(NOW.replace(hour=4)) is True


def test_scan_main_includes_sports_when_due(monkeypatch, capsys):
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    import tradehub.predictions as predictions

    written = {}
    monkeypatch.setattr(scan, "KalshiLive", lambda: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([{"engine": "weather"}], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "sports_due", lambda now: True)
    monkeypatch.setattr(scan, "run_sports_for_cron", lambda now, supa: (
        [{"engine": "sports_nfl"}], [{"edge_type": "SPORTS"}], {"nfl": {"matched": 1}}))
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: written.setdefault("preds", rows))
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: written.setdefault("edges", rows))

    assert scan.main() == 0
    assert [r["engine"] for r in written["preds"]] == ["weather", "sports_nfl"]
    assert written["edges"] == [{"edge_type": "SPORTS"}]
    assert json.loads(capsys.readouterr().out)["sports"] == {"nfl": {"matched": 1}}


def test_scan_main_survives_a_sports_crash(monkeypatch, capsys):
    from tradehub.core import supabase_client
    from tradehub.scripts import scan
    import tradehub.predictions as predictions

    monkeypatch.setattr(scan, "KalshiLive", lambda: object())
    monkeypatch.setattr(scan, "scan_weather", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(scan, "sports_due", lambda now: True)

    def boom(now, supa):
        raise RuntimeError("kalshi down")

    monkeypatch.setattr(scan, "run_sports_for_cron", boom)
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(predictions, "record_predictions", lambda supa, rows: rows)
    monkeypatch.setattr(supabase_client, "upsert_opportunities", lambda rows: None)

    assert scan.main() == 0
    assert "kalshi down" in json.loads(capsys.readouterr().out)["sports"]["error"]
```

Extend the engine-set test in `tests/test_settle_predictions.py`:

Replace this block:

```python
        "crypto": "daily",
    }
```

with:

```python
        "crypto": "daily",
        "sports_nfl": "daily",
        "sports_cfb": "daily",
    }
```

- [ ] **Step 2: Run them to verify they fail**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_scan.py tests/test_settle_predictions.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.scan'`). Once `sports/scan.py` exists but before `settle_predictions.py` is edited, `test_engines_match_spec_engine_set_and_cadences` fails on the dict comparison.

- [ ] **Step 3: Implement**

`tradehub/sports/scan.py`:

```python
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
```

`tradehub/scripts/scan.py`, import:

Replace this block:

```python
from tradehub.predictions import build_prediction_row
```

with:

```python
from tradehub.predictions import build_prediction_row
from tradehub.sports.scan import run_sports_for_cron, sports_due
```

and in `main()`:

Replace this block:

```python
    gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
    record_predictions(get_client(), weather_preds + gas_preds)
    upsert_opportunities(weather_edges + gas_edges)
    print(json.dumps({
        "as_of": now.isoformat(),
        "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
    }))
```

with:

```python
    gas_preds, gas_edges = scan_gas(live, now, load_engine_config("gas"))
    sports_preds: list[dict] = []
    sports_edges: list[dict] = []
    sports_summary: dict[str, Any] = {"skipped": "not due (every third UTC hour)"}
    if sports_due(now):
        try:
            sports_preds, sports_edges, sports_summary = run_sports_for_cron(now, get_client())
        except Exception as exc:  # a predictor or Kalshi outage must not cost the weather/gas run
            sports_summary = {"error": repr(exc)}
    record_predictions(get_client(), weather_preds + gas_preds + sports_preds)
    upsert_opportunities(weather_edges + gas_edges + sports_edges)
    print(json.dumps({
        "as_of": now.isoformat(),
        "weather": {"predictions": len(weather_preds), "edges": len(weather_edges)},
        "gas": {"predictions": len(gas_preds), "edges": len(gas_edges)},
        "sports": sports_summary,
    }, default=str))
```

`tradehub/scripts/settle_predictions.py`:

Replace this block:

```python
    ("crypto", "daily"),
]
```

with:

```python
    ("crypto", "daily"),
    ("sports_nfl", "daily"),
    ("sports_cfb", "daily"),
]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_scan.py tests/test_settle_predictions.py tests/test_scan.py` → Expected: `18 passed`
Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q` → Expected: `341 passed`
Run: `.venv/bin/ruff check --select F401,F811,F821 tradehub tests` → Expected: `All checks passed!`

If 2b has changed `settle_predictions.main()`'s loop, only the `ENGINES` list edit applies; don't touch the loop.

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/scan.py tradehub/scripts/scan.py tradehub/scripts/settle_predictions.py tests/test_sports_scan.py tests/test_settle_predictions.py
git commit -m "feat(sports): 3-hourly sports scan writes predictions, SPORTS edges and review tiers

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 9: Reviewer keep-or-drop scorecard and `GET /api/sports-edges`

**Files:**
- Create: `tradehub/sports/scorecard.py`
- Modify: `tradehub/api/main.py`
- Test: `tests/test_sports_scorecard_api.py` (new)

**Interfaces:**
- Consumes: `get_supabase` (the service role; returns `None` when unconfigured), `kalshi_fee_cents`, and the `kalshi_edges`, `sports_reviews` and `predictions` tables.
- Produces:
  - `MIN_SETTLED = 100`.
  - `reviewer_scorecard(reviews, results) -> {"n_settled", "min_settled", "approved": {n, brier, pnl_per_contract}, "rejected": {...}, "verdict": "insufficient"|"keep"|"drop"}`.
  - `GET /api/sports-edges → {"as_of", "edges": [...flattened, Top Picks first...], "reviewer_scorecard"}`. It returns 503 without Supabase.

- [ ] **Step 1: Write the failing test**: `tests/test_sports_scorecard_api.py`:

```python
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from tradehub.api.dependencies import get_supabase
from tradehub.api.main import app
from tradehub.sports.scorecard import MIN_SETTLED, reviewer_scorecard


def _review(ticker, side="yes", price=0.40, prob=0.55, explainable=True, flags=(), at="2026-09-26T12:00:00+00:00"):
    return {"market_ticker": ticker, "side": side, "entry_price": price, "our_prob": prob, "status": "ok",
            "explainable": explainable, "red_flags": list(flags), "created_at": at}


def test_scorecard_is_insufficient_below_the_spec_threshold():
    card = reviewer_scorecard([_review("A")], {"A": "yes"})
    assert card["n_settled"] == 1 and card["verdict"] == "insufficient" and MIN_SETTLED == 100


def test_scorecard_compares_approved_and_rejected():
    reviews, results = [], {}
    for i in range(60):   # approved picks win
        reviews.append(_review(f"A{i}"))
        results[f"A{i}"] = "yes"
    for i in range(60):   # flagged picks lose
        reviews.append(_review(f"R{i}", flags=("late injury news unknown",)))
        results[f"R{i}"] = "no"
    card = reviewer_scorecard(reviews, results)
    assert card["n_settled"] == 120
    assert card["approved"]["n"] == 60 and card["rejected"]["n"] == 60
    assert card["approved"]["brier"] == pytest.approx(0.2025)          # (0.55 - 1)^2
    assert card["approved"]["pnl_per_contract"] > 0 > card["rejected"]["pnl_per_contract"]
    assert card["verdict"] == "keep"


def test_scorecard_says_drop_when_approval_does_not_help():
    reviews = [_review(f"A{i}") for i in range(60)] + [_review(f"R{i}", explainable=False) for i in range(60)]
    results = {r["market_ticker"]: "no" for r in reviews}
    assert reviewer_scorecard(reviews, results)["verdict"] == "drop"


def test_scorecard_uses_the_latest_review_per_market_side_and_skips_unsettled():
    reviews = [_review("A", explainable=False, at="2026-09-26T09:00:00+00:00"),
               _review("A", explainable=True, at="2026-09-26T12:00:00+00:00"), _review("B")]
    card = reviewer_scorecard(reviews, {"A": "yes"})
    assert card["approved"]["n"] == 1 and card["rejected"]["n"] == 0 and card["n_settled"] == 1


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self.rows = [r for r in self.rows if r.get(col) == val]
        return self

    def in_(self, col, vals):
        self.rows = [r for r in self.rows if r.get(col) in vals]
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Q(list(self.tables[name]))


def _edge(market_id, tier, edge_pct, hours):
    start = (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()
    return {"market_id": market_id, "title": market_id, "edge_type": "SPORTS", "our_prob": 0.3, "market_prob": 0.25,
            "edge_pct": edge_pct, "market_url": "https://kalshi.com/markets/x", "source_url": "https://sports/x",
            "raw_payload": {"sport": "nfl", "kind": "winner", "side": "yes", "entry_price": 0.25, "maker": True,
                            "home": "IND", "away": "HOU", "start_utc": start, "tier": tier, "candidate": True,
                            "reject_reasons": [], "review": None, "game_id": "g"}}


def test_sports_edges_endpoint_orders_by_tier_and_hides_started_games():
    supa = _Supa({
        "kalshi_edges": [_edge("U", "unreviewed", 0.20, 5), _edge("T", "top_pick", 0.05, 5),
                         _edge("F", "flagged", 0.30, 5), _edge("OLD", "top_pick", 0.5, -1),
                         {**_edge("W", "top_pick", 0.9, 5), "edge_type": "WEATHER"}],
        "sports_reviews": [], "predictions": [],
    })
    app.dependency_overrides[get_supabase] = lambda: supa
    try:
        body = TestClient(app).get("/api/sports-edges").json()
    finally:
        app.dependency_overrides.clear()
    assert [e["market_id"] for e in body["edges"]] == ["T", "F", "U"]
    first = body["edges"][0]
    assert first["tier"] == "top_pick" and first["home"] == "IND" and first["source_url"] == "https://sports/x"
    assert body["reviewer_scorecard"]["verdict"] == "insufficient"


def test_sports_edges_endpoint_503_without_supabase():
    app.dependency_overrides[get_supabase] = lambda: None
    try:
        assert TestClient(app).get("/api/sports-edges").status_code == 503
    finally:
        app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_scorecard_api.py`
Expected: `1 error` (`ModuleNotFoundError: No module named 'tradehub.sports.scorecard'`).

- [ ] **Step 3: Implement**

`tradehub/sports/scorecard.py`:

```python
"""Keep-or-drop test for the LLM reviewer (spec §3.2): do approved picks beat rejected ones?"""

from __future__ import annotations

from typing import Any

from shared.kalshi_fees import kalshi_fee_cents

MIN_SETTLED = 100


def _summary(picks: list[tuple[float, int, float]]) -> dict[str, Any]:
    if not picks:
        return {"n": 0, "brier": None, "pnl_per_contract": None}
    return {
        "n": len(picks),
        "brier": sum(b for b, _, _ in picks) / len(picks),
        "pnl_per_contract": sum(p for _, _, p in picks) / len(picks),
    }


def reviewer_scorecard(reviews: list[dict[str, Any]], results: dict[str, str]) -> dict[str, Any]:
    """`reviews`: ok rows from sports_reviews; `results`: market_ticker -> 'yes'/'no' for settled markets.
    P&L is per contract at the reviewed entry price, as a taker (conservative fee)."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for r in sorted(reviews, key=lambda r: r["created_at"]):
        if r.get("status") == "ok":
            latest[(r["market_ticker"], r["side"])] = r
    approved: list[tuple[float, int, float]] = []
    rejected: list[tuple[float, int, float]] = []
    for (ticker, side), r in latest.items():
        result = results.get(ticker)
        if result not in ("yes", "no"):
            continue
        y = 1 if result == "yes" else 0
        price = float(r["entry_price"])
        won = (side == "yes") == (y == 1)
        pnl = (1.0 - price if won else -price) - kalshi_fee_cents(price * 100.0) / 100.0
        pick = ((float(r["our_prob"]) - y) ** 2, y, pnl)
        (approved if r["explainable"] and not r["red_flags"] else rejected).append(pick)
    a, rj = _summary(approved), _summary(rejected)
    n = a["n"] + rj["n"]
    if n < MIN_SETTLED or not a["n"] or not rj["n"]:
        verdict = "insufficient"
    elif a["brier"] < rj["brier"] or a["pnl_per_contract"] > rj["pnl_per_contract"]:
        verdict = "keep"
    else:
        verdict = "drop"
    return {"n_settled": n, "min_settled": MIN_SETTLED, "approved": a, "rejected": rj, "verdict": verdict}
```

`tradehub/api/main.py`, import:

Replace this block:

```python
from tradehub.scripts.shadow_performance import build_shadow_timeline_response
```

with:

```python
from tradehub.scripts.shadow_performance import build_shadow_timeline_response
from tradehub.sports.scorecard import reviewer_scorecard
```

and the endpoint, inserted above the dev entrypoint. **If step 5's `mount_frontend(app, FRONTEND_DIST)` call exists** (check with `grep -n mount_frontend tradehub/api/main.py`), put the block **above that call** instead, so the SPA mount stays last:

Replace this block:

```python
# ── Dev entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
```

with:

```python
# ════════════════════════════════════════════════════════════════════════════
# Sports edges (rollout step 7): candidate edges with review verdicts and links
# ════════════════════════════════════════════════════════════════════════════
_TIER_ORDER = {"top_pick": 0, "flagged": 1, "unreviewed": 2, "filtered": 3}
_EDGE_FIELDS = ("sport", "kind", "side", "entry_price", "maker", "home", "away", "start_utc", "game_id",
                "tier", "candidate", "reject_reasons", "review")


@app.get("/api/sports-edges", tags=["Sports"])
def get_sports_edges(supabase=Depends(get_supabase)):
    """Upcoming SPORTS edges (Top Picks first) plus the reviewer keep-or-drop scorecard."""
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    now = datetime.now(timezone.utc)
    rows = supabase.table("kalshi_edges").select("*").eq("edge_type", "SPORTS").execute().data or []
    edges = []
    for row in rows:
        raw = row.get("raw_payload") or {}
        start = raw.get("start_utc")
        if not start or datetime.fromisoformat(start) <= now:
            continue
        edges.append({
            "market_id": row["market_id"], "title": row.get("title"), "our_prob": row.get("our_prob"),
            "market_prob": row.get("market_prob"), "edge_pct": row.get("edge_pct"),
            "market_url": row.get("market_url"), "source_url": row.get("source_url"),
            **{k: raw.get(k) for k in _EDGE_FIELDS},
        })
    edges.sort(key=lambda e: (_TIER_ORDER.get(e["tier"], 9), -float(e["edge_pct"] or 0)))
    reviews = supabase.table("sports_reviews").select("*").eq("status", "ok").execute().data or []
    settled = (supabase.table("predictions").select("market_ticker,result")
               .in_("engine", ["sports_nfl", "sports_cfb"]).eq("status", "SETTLED").execute().data or [])
    results = {r["market_ticker"]: r["result"] for r in settled}
    return {"as_of": now.isoformat(), "edges": edges, "reviewer_scorecard": reviewer_scorecard(reviews, results)}


# ── Dev entrypoint ───────────────────────────────────────────────────────────
if __name__ == "__main__":
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q tests/test_sports_scorecard_api.py` → Expected: `6 passed`
Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest -q` → Expected: `347 passed`
Run: `.venv/bin/ruff check --select F401,F811,F821 tradehub tests` → Expected: `All checks passed!`

- [ ] **Step 5: Commit**

```bash
git add tradehub/sports/scorecard.py tradehub/api/main.py tests/test_sports_scorecard_api.py
git commit -m "feat(api): /api/sports-edges with reviewer keep-or-drop scorecard

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 10: War Room "Sports" page

**Files:**
- Create: `market_sentiment_tool/src/lib/sportsEdges.ts`, `market_sentiment_tool/src/lib/sportsEdges.test.ts`, `market_sentiment_tool/src/pages/SportsEdges.tsx`
- Modify: `market_sentiment_tool/src/App.tsx`

**Interfaces:**
- Consumes: `GET /api/sports-edges` (Task 9) and `buildApiUrl` (`src/lib/api.ts`).
- Produces:
  - `SportsEdge`, `SportsEdgesResponse`, `groupByTier`, `formatEdgePct` and `rejectReasonLabel`.
  - The route `/sports` with a sidebar link, "Sports".

Work from `market_sentiment_tool/`. If `node_modules` is missing, run `npm ci`.

- [ ] **Step 1: Write the failing test**: `src/lib/sportsEdges.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { formatEdgePct, groupByTier, rejectReasonLabel, type SportsEdge } from "@/lib/sportsEdges";

const base: SportsEdge = {
  market_id: "KXNFLGAME-26SEP27HOUIND-IND", title: "IND wins", our_prob: 0.3, market_prob: 0.25, edge_pct: 0.075,
  market_url: "https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26sep27houind",
  source_url: "https://sports.example.com/?sport=nfl&game=2026_03_HOU_IND", sport: "nfl", kind: "winner",
  side: "yes", entry_price: 0.25, maker: true, home: "IND", away: "HOU", start_utc: "2026-09-27T17:00:00+00:00",
  game_id: "2026_03_HOU_IND", tier: "top_pick", candidate: true, reject_reasons: [], review: null,
};

describe("sports edges", () => {
  it("groups edges into the four tiers in display order", () => {
    const groups = groupByTier([
      { ...base, market_id: "f", tier: "filtered" },
      { ...base, market_id: "t", tier: "top_pick" },
      { ...base, market_id: "u", tier: "unreviewed" },
      { ...base, market_id: "x", tier: "flagged" },
    ]);
    expect(groups.map((g) => g.tier)).toEqual(["top_pick", "flagged", "unreviewed", "filtered"]);
    expect(groups[0].edges.map((e) => e.market_id)).toEqual(["t"]);
  });

  it("drops empty tiers", () => {
    expect(groupByTier([base]).map((g) => g.tier)).toEqual(["top_pick"]);
  });

  it("formats edges as percentage points", () => {
    expect(formatEdgePct(0.075)).toBe("+7.5 pp");
  });

  it("labels reject reasons in plain words", () => {
    expect(rejectReasonLabel("calibration_insufficient")).toBe("predictor not yet calibrated here");
    expect(rejectReasonLabel("something_new")).toBe("something_new");
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/lib/sportsEdges.test.ts`
Expected: `Test Files 1 failed` (`Failed to resolve import "@/lib/sportsEdges"`).

- [ ] **Step 3: Implement**

`src/lib/sportsEdges.ts`:

```ts
export type SportsTier = "top_pick" | "flagged" | "unreviewed" | "filtered";

export interface SportsReview {
  status: string;
  explainable: boolean | null;
  drivers: string[];
  red_flags: string[];
  model: string | null;
}

export interface SportsEdge {
  market_id: string;
  title: string | null;
  our_prob: number;
  market_prob: number;
  edge_pct: number;
  market_url: string;
  source_url: string;
  sport: string;
  kind: string;
  side: "yes" | "no";
  entry_price: number;
  maker: boolean;
  home: string;
  away: string;
  start_utc: string;
  game_id: string;
  tier: SportsTier;
  candidate: boolean;
  reject_reasons: string[];
  review: SportsReview | null;
}

export interface ScorecardSide {
  n: number;
  brier: number | null;
  pnl_per_contract: number | null;
}

export interface SportsEdgesResponse {
  as_of: string;
  edges: SportsEdge[];
  reviewer_scorecard: {
    n_settled: number;
    min_settled: number;
    approved: ScorecardSide;
    rejected: ScorecardSide;
    verdict: "insufficient" | "keep" | "drop";
  };
}

export const TIER_LABELS: Record<SportsTier, string> = {
  top_pick: "Top Picks",
  flagged: "Flagged by reviewer",
  unreviewed: "Unreviewed candidates",
  filtered: "Edges that failed the candidate filter",
};

const TIER_ORDER: SportsTier[] = ["top_pick", "flagged", "unreviewed", "filtered"];

export function groupByTier(edges: SportsEdge[]): { tier: SportsTier; edges: SportsEdge[] }[] {
  return TIER_ORDER.map((tier) => ({ tier, edges: edges.filter((e) => e.tier === tier) })).filter(
    (group) => group.edges.length > 0,
  );
}

export function formatEdgePct(edge: number): string {
  return `${edge >= 0 ? "+" : ""}${(edge * 100).toFixed(1)} pp`;
}

const REASONS: Record<string, string> = {
  calibration_insufficient: "predictor not yet calibrated here",
  calibration_off: "predictor miscalibrated here",
  wide_quote: "wide bid/ask",
  thin_book: "thin order book",
  low_volume: "low volume",
  starts_too_soon: "starts too soon",
  starts_too_late: "starts too far out",
};

export function rejectReasonLabel(reason: string): string {
  return REASONS[reason] ?? reason;
}
```

`src/pages/SportsEdges.tsx`:

```tsx
import { useEffect, useState } from "react";

import { buildApiUrl } from "@/lib/api";
import {
  TIER_LABELS,
  formatEdgePct,
  groupByTier,
  rejectReasonLabel,
  type SportsEdge,
  type SportsEdgesResponse,
} from "@/lib/sportsEdges";

function EdgeRow({ edge }: { edge: SportsEdge }) {
  return (
    <tr className="border-t border-slate-800 align-top">
      <td className="py-2 pr-3">
        <div className="font-medium text-slate-100">{edge.away} @ {edge.home}</div>
        <div className="text-xs text-slate-500">{new Date(edge.start_utc).toLocaleString()}</div>
      </td>
      <td className="py-2 pr-3 text-slate-300">{edge.title}</td>
      <td className="py-2 pr-3 uppercase text-slate-300">{edge.side} @ {Math.round(edge.entry_price * 100)}¢</td>
      <td className="py-2 pr-3 text-slate-300">{Math.round(edge.our_prob * 100)}% vs {Math.round(edge.market_prob * 100)}%</td>
      <td className="py-2 pr-3 font-semibold text-emerald-400">{formatEdgePct(edge.edge_pct)}</td>
      <td className="py-2 pr-3 text-xs text-slate-400">
        {edge.review?.drivers.map((d) => <div key={d}>• {d}</div>)}
        {edge.review?.red_flags.map((f) => <div key={f} className="text-amber-400">⚠ {f}</div>)}
        {edge.reject_reasons.map((r) => <div key={r}>{rejectReasonLabel(r)}</div>)}
      </td>
      <td className="py-2 text-xs">
        <a className="text-emerald-400 hover:underline" href={edge.market_url} target="_blank" rel="noreferrer">Kalshi</a>
        {" · "}
        <a className="text-sky-400 hover:underline" href={edge.source_url} target="_blank" rel="noreferrer">Predictor</a>
      </td>
    </tr>
  );
}

export default function SportsEdges() {
  const [data, setData] = useState<SportsEdgesResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetch(buildApiUrl("/api/sports-edges"))
      .then(async (response) => {
        const payload = await response.json();
        if (!response.ok) throw new Error(payload?.detail || `Request failed with status ${response.status}`);
        setData(payload as SportsEdgesResponse);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Unknown error"));
  }, []);

  if (error) return <div className="p-8 text-red-400">Sports edges unavailable: {error}</div>;
  if (!data) return <div className="p-8 text-slate-400">Loading sports edges…</div>;

  const card = data.reviewer_scorecard;
  return (
    <div className="p-8 space-y-8">
      <header>
        <h1 className="text-2xl font-bold text-white">Sports edges</h1>
        <p className="text-sm text-slate-400">
          Suggestions only. Probabilities come from the NFL/CFB predictor sites' frozen pre-game snapshots; the
          reviewer never changes them. Reviewer check: {card.approved.n} approved vs {card.rejected.n} rejected settled
          picks ({card.n_settled}/{card.min_settled} needed), verdict <b>{card.verdict}</b>.
        </p>
      </header>
      {groupByTier(data.edges).map((group) => (
        <section key={group.tier}>
          <h2 className="mb-2 text-lg font-semibold text-slate-200">{TIER_LABELS[group.tier]} ({group.edges.length})</h2>
          <table className="w-full text-sm">
            <tbody>{group.edges.map((edge) => <EdgeRow key={edge.market_id} edge={edge} />)}</tbody>
          </table>
        </section>
      ))}
      {data.edges.length === 0 && <p className="text-slate-400">No upcoming sports edges.</p>}
    </div>
  );
}
```

`src/App.tsx`, imports:

Replace this block:

```tsx
import ShadowBacktester from "@/pages/ShadowBacktester";
```

with:

```tsx
import ShadowBacktester from "@/pages/ShadowBacktester";
import SportsEdges from "@/pages/SportsEdges";
```

Replace this block:

```tsx
import { LayoutDashboard, Activity, Wallet, Brain, LineChart } from "lucide-react";
```

with:

```tsx
import { LayoutDashboard, Activity, Wallet, Brain, LineChart, Trophy } from "lucide-react";
```

The sidebar link, after the Shadow link:

Replace this block:

```tsx
          <LineChart className="w-5 h-5 text-amber-400" /> Shadow
        </NavLink>
```

with:

```tsx
          <LineChart className="w-5 h-5 text-amber-400" /> Shadow
        </NavLink>
        <NavLink
          to="/sports"
          className={({isActive}) => `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors ${isActive ? 'bg-emerald-500/10 text-emerald-400 font-medium' : 'hover:bg-slate-900 text-slate-400 hover:text-slate-200'}`}
        >
          <Trophy className="w-5 h-5 text-sky-400" /> Sports
        </NavLink>
```

The route:

Replace this block:

```tsx
          <Route path="/shadow" element={<ShadowBacktester />} />
```

with:

```tsx
          <Route path="/shadow" element={<ShadowBacktester />} />
          <Route path="/sports" element={<SportsEdges />} />
```

- [ ] **Step 4: Run the tests and the build**

Run: `npx vitest run` → Expected: `Test Files 3 passed`, `Tests 9 passed`
Run: `npx tsc --noEmit -p tsconfig.app.json` → Expected: no output
Run: `npm run build` → Expected: `✓ built in …` (the existing chunk-size warning is fine)

- [ ] **Step 5: Commit**

```bash
git add market_sentiment_tool/src/lib/sportsEdges.ts market_sentiment_tool/src/lib/sportsEdges.test.ts market_sentiment_tool/src/pages/SportsEdges.tsx market_sentiment_tool/src/App.tsx
git commit -m "feat(web): War Room Sports page with Top Picks, review verdicts and links

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 11: Live dry run, tracker row, evidence report, Kevin's checklist

**Files:**
- Modify: `docs/superpowers/plans/2026-09-24-rollout-tracker.md`
- Create: `docs/superpowers/reports/2026-09-25-sports-edges-llm-reviewer.md`

- [ ] **Step 1: Live dry run** (public Kalshi plus the predictors; no Supabase, no LLM, writes nothing):

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m tradehub.sports.scan --dry-run > /tmp/sports_dry_run.json; head -c 1500 /tmp/sports_dry_run.json
```
Expected:
- Before 7a is deployed: `"feed_error": "...: 404 Client Error..."` for both sports, with `predictions: 0`.
- After 7a is deployed: each sport reports `matched` equal to `feed_games` (15/15 NFL and 70/70 CFB on the 2026-09-25 replay), `unmatched_games: []`, and `candidates: 0` until the predictors have ≥ 20 graded pre-game snapshots per bucket.
- Paste the `reports` block into the evidence report. Any non-empty `unmatched_games` entry is either an alias gap (fix it in `aliases/<sport>.json` and bump `version`) or a real no-market game. Say which.

- [ ] **Step 2: Update the tracker.** Set the step 7 row in `docs/superpowers/plans/2026-09-24-rollout-tracker.md` to:

```markdown
| 7 | Sports adapters + LLM reviewer (NFL + CFB) | 🟢 plans written + verified: 7a predictor pre-game feed, then 7b hub | [2026-09-25-predictor-pregame-feed.md](2026-09-25-predictor-pregame-feed.md) (NFL_Predictor, CFB_Predictor) → [2026-09-25-sports-edges-llm-reviewer.md](2026-09-25-sports-edges-llm-reviewer.md) |
```

and replace the `## Step 7 — Sports adapters + LLM reviewer (outline)` heading line with `## Step 7 — Sports adapters + LLM reviewer (planned: 7a 2026-09-25-predictor-pregame-feed.md, 7b 2026-09-25-sports-edges-llm-reviewer.md; original outline below)`. Copy both plan files into `docs/superpowers/plans/` if they are not there yet.

- [ ] **Step 3: Write the evidence report** `docs/superpowers/reports/2026-09-25-sports-edges-llm-reviewer.md`, with, per task, the RED/GREEN commands and output tails, the dry-run `reports`, and any deviations.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/plans/2026-09-24-rollout-tracker.md docs/superpowers/reports/2026-09-25-sports-edges-llm-reviewer.md
git commit -m "docs: step 7b evidence report and tracker row

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Kevin's checklist (not the agent's):**
  1. Apply migration `20260416000008_sports_reviews.sql` to Supabase after `000003`–`000007`, in filename order.
  2. Put `OPENROUTER_API_KEY` in `/opt/stack/.env`. In `vps-stack/compose.yml`, add `OPENROUTER_API_KEY: ${OPENROUTER_API_KEY:-}` and the four `SPORTS_*_URL` variables to the `tradehub` service environment. Use `https://nfl.<domain>`, `https://cfb.<domain>` and `https://sports.<domain>` once the predictors are on the VPS.
  3. Record one real review, and keep it as a regression fixture in place of `openrouter_ok.json`'s hand-built content:
     ```bash
     OPENROUTER_API_KEY=... .venv/bin/python - <<'EOF'
     import json
     from tradehub.sports.config import load_reviewer_config
     from tradehub.sports.reviewer import OpenRouterReviewer
     cfg = load_reviewer_config()
     print(OpenRouterReviewer(__import__("os").environ["OPENROUTER_API_KEY"], cfg.model, cfg.timeout_seconds).review(
         json.load(open("tests/fixtures/sports/nfl_kalshi_feed.json"))["games"][0]))
     EOF
     ```
     Expected: `Review(status='ok', …)`. If it's `invalid` or `error`, try `qwen/qwen3.8-27b:free` or `nex-agi/nex-n2.5-pro:free` in `engines.yaml`.
  4. Sports run on the existing hourly scan timer every third UTC hour; no new timer is needed. `SPORTS_SCAN_EVERY_RUN=1` forces a run.
  5. After ≥ 100 settled reviewed picks, read `reviewer_scorecard.verdict` on `/api/sports-edges`. If it says `drop`, set `daily_budget: 0` (which disables calls) and remove the reviewer in a follow-up.

## Open questions and spec conflicts (for Kevin)

- **Huge model-vs-market gaps.** In the replay, 3,176 of 4,023 priced markets showed ≥ 4 pp edges. There were 50–60 pp gaps on FBS-vs-FCS spreads and NYG −7.5 at 72% vs 28%. That is far more than a real edge, and it points to model limits (FCS opponents; stale features).
  - The calibration gate blocks all of them today.
  - Once buckets fill, consider a sanity cap in the candidate filter, e.g. drop candidates with `|our_prob − mid| > 25 pp`. The spec's filter has only three rules, so this needs your call.
- **Calibration will take weeks.** A per-bucket `n ≥ 20` of genuine pre-game snapshots means NFL (about 16 games/week, spread over 10 buckets) needs most of the season before any winner bucket qualifies. CFB, with about 60 FBS games a week, gets there sooner.
- **Spread/total calibration is a proxy.** Buckets are graded at the sportsbook line recorded with the snapshot, while Kalshi strikes differ. CFB lines are mostly null (the odds key is out of quota), so CFB spread and total buckets stay empty.
- **Top Pick volume vs budget.** 40 reviews/day is enough once candidates are filtered. Large CFB Saturdays might need the one-time $10 credit (1,000/day), as the spec already notes.
- **Spec §5 says Azure scale-to-zero;** the tracker's step 5 moved to the VPS. The "every 3h" schedule rides the VPS hourly timer.
