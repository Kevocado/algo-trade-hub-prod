# Algo Trade Hub v2 — Prediction Journal (draft for Kevin's review)

## 1. Positioning

Not a trading system. A **public prediction journal / measurement lab**: every forecaster publishes timestamped forecasts, outcomes settle against free public data, the site scores calibration and model-vs-market disagreement. Places no orders; the ledger is the product.

Resume line it enables: *"Built a measurement lab grading N forecasters across macro, equities, and sports against realized outcomes — frozen forecasts, settled ledger, Brier-scored calibration, full audit trail."* Touches: ACCY 512 (labor econometrics → labor-market prints), FIN 550 (property-value modeling → housing forecaster), FIN 559 (financial time series → gold, rates, FX), BDI 513 (earnings-call strategy + event studies → earnings forecaster), NLP (sentiment meter), data eng (freeze/settle pipelines), and the sports-predictor calibration discipline — one resume line, the whole MSBA.

## 2. What it tracks

| Domain | Target | Cadence | Free source | Settles via | From |
|---|---|---|---|---|---|
| Macro | CPI m/m, FOMC decision, payrolls surprise | Monthly | FRED, BLS | Release prints | — |
| Labor (ACCY 512) | NFP surprise, unemployment-rate direction, JOLTS quits | Monthly | FRED (PAYEMS, UNRATE, JTSQUL) | BLS prints | Tightness Paradox panel work |
| Rates | 10Y yield direction | Daily/weekly | FRED (DGS10) | FRED | FIN coursework |
| Equities | SPY next-day direction | Daily | Stooq | Adjusted close | — |
| Equities | VIX level / direction | Daily | FRED/STOOQ | VIX close | — |
| Commodities (FIN 559) | Gold daily direction | Daily | Stooq (GC=F) | Daily close | FIN 559 used gold data |
| Housing (FIN 550) | Case-Shiller national HPI m/m direction | Monthly | FRED (CSUSHPISA) | S&P/FHFA release | FIN 550 assessed-value prediction project |
| Earnings (BDI 513) | Earnings-day surprise direction, watchlist names | Quarterly | Filings / Yahoo | Earnings prints | EarningsCall_TradingStrategy + event-returns study |
| FX | EUR/USD daily direction | Daily | Stooq | Daily close | — |
| Prediction mkts | Kalshi implied vs model prob | Daily | Kalshi public API | Market resolution | — |
| Sports | Existing 5 predictors as forecasters | Weekly | (existing) | Game results | Sports predictor suite |
| Crypto | BTC daily direction | Daily | CoinGecko/StOOQ | Daily close | — |

v1 ships: SPY direction (sentiment + quant), VIX, gold, EUR/USD, labor prints, housing (Case-Shiller), earnings surprises, Kalshi-vs-model. Crypto forecaster deferred to v1.x pending a venue-lead-lag justification (measurement first).

## 3. Architecture

- `journal_forecasts` — immutable freeze ledger (forecaster, target, horizon, probability, frozen_at, source hash; `rebuilt` rows excluded from stats by rule).
- `journal_settlements` — (target, realized value, settled_at, source).
- One settle job grades everything; the frontend never recomputes a number (REST serves graded forecasts).
- Routes: `/journal` (flagship), `/scoreboard` (engine catalogue), `/models`, `/shadow` (unchanged), `/lab` → redirects to `/journal`.

## 4. Sentiment meter v1

Daily composite predicting next-day SPY direction, **frozen 08:00 CT** (pre-open). Components, all free/keyless: VIX (FRED), put/call ratio, CNN Fear & Greed (cached, stale-flagged never silent), HY spread (FRED), market breadth (Stooq adv/dec), GDELT news tone via VADER (lexicon — no model downloads on the VPS). Each z-scored vs trailing-252d, fixed documented weights. Output: score (−100/+100) for display, logistic-mapped probability for scoring. Cold start: fixed prior-slope logistic, probabilities marked **provisional** until 60 settled days, then isotonic fit on walk-forward history.

## 5. Quant replacement

SPY next-day direction (shares the meter's settlement source and daily cadence — one settle job, one rhythm). Training in-repo (`tradehub/models/spy_direction/`): walk-forward expanding window, monthly refit, versioned artifacts with SHA manifest, refuses unlisted hashes. Features: price/volume/breadth only. No remote downloads, no pickles from outside the repo. Enters the journal under the same freeze/settle/score contract, gated like everything else.

## 6. Cuts

- `/lab` removed → redirect to `/journal` (no 404s).
- `macro_engine.py` deleted (git history keeps it); a real macro model is specced as future work, not built here.
- `quant_engine.py` remote-pickle loader deleted; replaced by §5.
- `sentiment_filter.py` lazy FinBERT/zero-shot path deleted once the meter lands.
- Engine catalogue gains a third verdict — **retired** — so deleted engines leave a tombstone (removed date, reason, replaced-by) instead of vanishing.

## 7. Gates

- **Display gate:** any forecaster appears from its first frozen row; headline stats aggregate only post-calibration forecasters.
- **Calibration gate:** 20+ resolved samples per confidence bucket before joining headline aggregates or any +EV claim (ported from sports). Until then: tile reads *provisional*.
- **Promotion gate:** paper-only until 200+ settled rows **and** positive Brier Skill Score vs market baseline, edge net of Kalshi taker fees — fee modeling in `fills.py` is in this spec (not deferred) so the gate is evaluable. Until then, all Kalshi copy stays "public market-data + demo API client."

## 8. Journal UI

Three blocks: (1) **ledger hero** — N settled, Brier skill vs market, per-forecaster tiles in the sports model-vs-market pattern (model prob large, Kalshi-implied beneath, same units); (2) **calibration curves** — reliability diagrams per forecaster, 50% baseline, bias readouts; (3) **quarantine section** — weather/gas rows from the quarantine sink, visually quarantined, excluded from all headline numbers.

## 9. Testing spine

Every journal number traces to a pinned test: freeze-refusal, settle-idempotency, no-backfill (`rebuilt=true` excluded — test asserts it), fee-schedule pins (any fee-constant mutation fails), quarantine-safety untouched. Standing suite: pytest ×2, ruff, typecheck, vitest, build; mutations shown to fail.

## Appendix: Decisions (approved by Kevin 2026-09-28, no flips)

- D1: `/lab` redirects to `/journal`.
- D2: Delete `macro_engine.py`; preserve history; retired tombstone.
- D3: Sentiment forecast freezes at 08:00 CT.
- D4: Sentiment components = VIX, put/call, CNN Fear & Greed, HY spread, breadth, GDELT/VADER.
- D5: Cold start = documented fixed logistic mapping; provisional until 60 settlements, then walk-forward isotonic calibration.
- D6: Quant target = next-day SPY direction.
- D7: No BTC forecaster in v1.
- D8: `/journal` flagship; `/scoreboard`, `/models`, `/shadow` keep distinct roles.
- D9: Calibration gate = 20+ resolved samples per confidence bucket.
- D10: Kalshi fee/spread modeling included now so the promotion gate is measurable.
- D11: New immutable `journal_forecasts` / `journal_settlements` tables (not `signal_events`).
- D12: Remove lazy transformer fallback from `sentiment_filter.py` after meter launch.
