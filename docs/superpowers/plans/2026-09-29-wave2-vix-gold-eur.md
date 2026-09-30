# Wave 2 – VIX, Gold, EUR/USD (Daily Direction)

**Goal:** Add three new daily-direction forecasters to the prediction journal:
1. **VIX next-day direction** – binary (up/down) for the next trading day
2. **Gold daily direction** – binary (up/down) for the next trading day, based on Stooq XAUUSD
3. **EUR/USD daily direction** – binary (up/down) for the next trading day, based on Stooq EURUSD

All three share the same infrastructure:
- Freeze at **08:00 CT** (3‑hour lead before market close)
- Settle on the next close (market close time)
- Scored identically to SPY (Brier score comparison)
- Naive baseline: simple persistence + climatology (pre‑announcement period)
- Must beat baseline's Brier to graduate from provisional

**Architecture:**
- Plumbing: `tradehub/data/fred_daily.py` (keyed FRED current vintage), `tradehub/journal/nyse.py` (session calendar), `tradehub/journal/spx.py` (SPX-like daily close target)
- Forecastors: `tradehub/journal/forecasters/vix.py`, `gold.py`, `eurusd.py`
- API: `tradehub/api/main.py` adds new endpoints for each forecaster
- Tests: `tests/test_journal_vix.py`, `tests/test_journal_gold.py`, `tests/test_journal_eurusd.py`

**Tech Stack:** Python 3.12, FRED API (key on VPS), GDELT DOC 2.1 (keyless), pytest

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§6 – Daily direction forecasters)

**Dependencies:** Plan (a) merged (PR #48) – journal pipeline, APIs, and scoring are ready.

**Testing:**
- Unit tests for each forecaster's `targets()` method (freeze window, calibration)
- Integration tests for the journal API endpoints
- Mutation tests for constants (e.g., `MIN_BUCKET_TARGETS`)
- End-to-end smoke test: all three forecasters register, produce scores, and appear in `/journal`

**Verification:**
- All 1384 Python tests pass (including new Wave 2 tests)
- Frontend vitest passes (462 tests)
- Build succeeds (tsc, eslint, vitest)
- Live API endpoints respond correctly
- Journal UI shows new forecasters with correct gate status (SHADOW until first freeze)
