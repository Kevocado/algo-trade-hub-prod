# Every Sports Predictor's Record on the Models Page

> **Status: design plan.** Plan-first: post your task list as a PR comment, then build test-first. Reviewer merges. The hub only DISPLAYS what each predictor already publishes; it never re-scores a game.

**Goal:** one place on the hub (the Models page) where a visitor sees how each sports predictor (NFL, college football, NBA, Premier League, F1) has actually done, in the same plain terms, with the sample size beside every number.

**Why:** today the hub journals only NFL and college football against the Kalshi price. NBA, PL and F1 results live on their own sites. Kevin wants the whole picture on one page. The paper-trading tracker (predictor-hub `data/paper/report.json`, public on raw GitHub) is the money verdict for sports; this page is the accuracy record.

## What each predictor serves today (checked live 2026-10-23)
| Sport | URL (all on `*.40-160-91-131.sslip.io`) | Shape |
|---|---|---|
| NFL | `nfl.` `/api/track-record` | `{games:{n_resolved,pct_moneyline_correct,pct_ats_correct,pct_totals_correct,weekly,vs_market,pre_kickoff,all_picks,...}, player_props:{...}, calibration:{...}}` |
| College football | `cfb.` `/api/track-record` | `{games:{n_resolved,pct_moneyline_correct,pct_ats_correct,pct_totals_correct,weekly_trend,pre_kickoff,n_pre_kickoff,per_pick}, player_props, calibration}` |
| NBA | `nba.` `/hub/track-record` (NOT `/api/...`: that returns the SPA page) | list of `{market:"h2h",total_predictions,correct_predictions,hit_rate,n_pre_tip,n_rebuilt,pre_tip:{...},settled}` |
| Premier League | `pl.` `/api/hub/track-record` | `{summary:{n_resolved_fixtures,pct_correct_overall,by_market:{match_result:{pct_correct,n_resolved},exact_score,over_under_2.5...}}}` |
| F1 | `f1.` `/api/track-record` | `{n_resolved,by_market:[...],pre_session:{n_resolved,by_market},calibration,per_pick}` |
Shapes differ; do not assume. Capture each live response into a fixture file first and write the adapters against those real bodies (the last two hub bugs came from invented fixtures).

## Rules (from earlier decisions, do not re-litigate)
- All recorded picks count; show the pre-kickoff / pre-tip / pre-session subset beside the headline, labelled. (Kevin, 2026-10-01.)
- Hit rate is not skill against the market. Only NFL and CFB have a Kalshi comparison (the Journal's gap). For NBA, PL and F1 the card says "no market comparison" in plain words, never an implied one.
- Under 100 resolved picks a number is "too early" (grey), same display rule as the Journal.
- Never compute a score in the hub: pass through the predictor's numbers; the hub may only normalise names and units.
- No change to any Predictor repo. A missing field renders as a dash plus a line in a "what each predictor still owes" list in the PR description (for the Predictor team).
- No secrets, no new dependency, no migration. A predictor that is down or slow shows "unavailable" for that sport only; the page and the other sports still render.

## Tasks

### Task 1: Fixtures and adapters (backend)
**Files:** create `tradehub/sports_record.py`, `tests/fixtures/sports_record/{nfl,cfb,nba,pl,f1}.json`, `tests/test_sports_record.py`.
- Save one real response per sport into the fixtures (curl the URLs above; trim long lists such as `per_pick` to 5 rows but keep every key).
- Define one row shape: `{sport, market, label, n, hit_rate, n_pre, hit_rate_pre, vs_market (only if the predictor serves one, else null), note}`.
- One pure adapter per sport: `adapt_nfl(body)`, `adapt_cfb`, `adapt_nba`, `adapt_pl`, `adapt_f1` -> `list[row]`. Missing keys give `None`, never 0 and never a guess.
- Tests: each adapter against its fixture asserts exact n and hit-rate values copied from the fixture; a body with a key missing yields None; an empty body yields an empty list.

### Task 2: Endpoint with fail-soft fetch
**Files:** modify `tradehub/api/main.py` (+ `tradehub/api/schemas.py`), create `tests/test_api_sports_record.py`.
- `GET /api/sports-record` returns `{as_of, sports:[{sport, status:"ok"|"unavailable", error?, rows:[...]}]}`.
- Fetch the five URLs server-side with a 6 s timeout and a 5-minute in-memory cache (copy the cache pattern used by the other sports endpoint; do not add a library). Base URLs from env: reuse `SPORTS_NFL_BASE`/`SPORTS_CFB_BASE` if they point at these hosts, add `SPORTS_NBA_BASE`, `SPORTS_PL_BASE`, `SPORTS_F1_BASE`; defaults to the sslip hosts above only if the env var is unset.
- Tests: all ok; one sport raising a timeout marks only that sport unavailable (others still ok); a non-JSON body (the NBA SPA page) is "unavailable", not a crash.

### Task 3: Models page section
**Files:** modify `market_sentiment_tool/src/pages/Models.tsx`; create `components/SportsRecord.tsx` + test; `lib/sportsRecord.ts` types.
- A "Sports predictors" section under the existing content: one card per sport. Each card: sport name, per-market rows as `hit rate` as a big number with a thin bar, `n` beside it, the pre-kickoff figure on a second small line, a "too early" chip under 100, and "no market comparison" or the Kalshi gap line (from the Journal data the page already has) for NFL/CFB.
- Numbers first, as few words as possible; keep the page word budget tests green (raise nothing: report exact numbers if a budget breaks).
- Unavailable sport: one grey sentence in its card.
- Tests with the real fixture shapes: ok card, too-early chip, unavailable card, no-market-comparison text.

### Task 4: Real-data check, then ship
- Run the page against the live API (vite dev with `DEV_API_PROXY=https://algo.40-160-91-131.sslip.io`, or after deploy) at 1280px and 375px; screenshots; confirm each sport's `n` equals what that sport's own site shows.
- Reviewer sets the three new env vars in `/opt/stack/compose.yml` on the VPS before merge (not the worker).
- Full gate on the merged tree: pytest at monotonic 5.0 and 1e7, ruff --select F, vitest, tsc, eslint, vite build.

## Out of scope (later)
- A "Sports money record" number from the paper tracker (`predictor-hub/data/paper/report.json` on raw GitHub): a second small PR once this page exists.
- Backfilling NBA/PL/F1 into the Kalshi-gap journal: blocked on their `/api/kalshi-feed` (NBA returns the SPA page, PL and F1 return 404), which the Predictor team owns.
- Any model change.
