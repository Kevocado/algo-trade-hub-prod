# Trade Hub v2 — Prediction Journal (spec)

Date: 2026-09-29. Status: draft for Kevin's review — amended twice (review findings, then a second pass checked against production and `main`).
Sources: `trade-hub-critique-and-roadmap.md` (2026-09-28), `tradehub-v2-direction-draft.md`
(Kevin, 2026-09-29), brainstorming sessions 2026-09-28/29 (scope: Phases 1+2, Approach B:
journal pipeline first, CPI/labor first content, sentiment + quant as new forecasters on a
proven pipe).

## 1. Positioning

Not a trading system. A **public prediction journal / measurement lab**: every forecaster
publishes timestamped forecasts, outcomes settle against free public data, the site scores
calibration and model-vs-market disagreement. It places no orders; the ledger is the product.

Site-wide banner, not a footnote: every page carries the "places no orders — the ledger is
the product" line. Hero copy leads with settled-ledger stats (N settled, Brier skill vs
market), never with projected returns.

Resume line it enables: *"Built a measurement lab grading N forecasters across macro,
equities, and sports against realized outcomes — frozen forecasts, settled ledger,
Brier-scored calibration, full audit trail."*

## 2. Scope: v1 roster and rollout waves

v1 ships the forecasters below. They all implement the single contract in §3, so each is a
repeatable unit; waves are rollout order within v1, each independently shippable and
verifiable. Nothing in a later wave blocks an earlier wave's deploy.

| Wave | Forecasters | Why this order |
|---|---|---|
| 1 | Journal pipeline itself; CPI m/m (existing engine, zero new modeling); FOMC decision (mapped from existing CPI/labor nowcast inputs at implementation); labor prints (§5); sentiment meter (§6); walk-forward quant (§7) | Pipeline graded on existing models before anything new is built (Approach B) |
| 2 | VIX direction, gold daily direction, EUR/USD daily direction | Same daily-cadence settle job as SPY; no new modeling pattern, just new targets |
| 3 | Housing (Case-Shiller), earnings surprises, Kalshi-vs-model pseudo-forecaster, sports consumers | New settlement shapes (monthly lag, quarterly, external feeds) |

Crypto (BTC daily direction) is deferred to v1.x pending a venue-lead-lag justification —
measurement first, per the critique. Rates (10Y) is deferred to v1.x (in the domain table,
not in the v1 ship list). A real macro-probability model is future work (§12), not built here.

Prior backtest history (CPI/labor PIT runs, oracle decompositions) is displayed on the
journal as labeled pre-journal context. It is never counted in journal N — the no-backfill
rule (§4) is absolute.

## 3. The forecaster contract (the unit everything implements)

Every forecaster, existing or new, implements the same four-step contract:

1. **Freeze.** Write one row per target to `journal_forecasts` — `(forecaster, target,
   horizon, probability, frozen_at, source_hash)` — strictly before the target's cutoff
   (BLS print time, FOMC decision time, 08:00 CT for daily directionals, market close for
   Kalshi-linked). Late writes are refused by a database trigger, not by convention and not
   by RLS (see §4: the jobs write as the service role, which bypasses RLS).
2. **Settle.** The settle job (§4) reconciles frozen rows against actuals into
   `journal_settlements` — `(target, realized_value, settled_at, source)`.
3. **Score.** Brier per row; Murphy decomposition, reliability buckets, and Brier Skill
   Score vs the market baseline per forecaster. Scores are idempotent recomputes from
   frozen rows + settlements.
4. **Render.** The frontend reads precomputed scores through the REST contract. It never
   recomputes a number.

New-forecaster checklist (enforced in review, not just documented): cutoff defined, freeze
test (late write refused), settlement source named with free-access evidence, scored from
first row, provisional label until the calibration gate (§9).

## 4. Core pipeline

One scheduled batch run per instrument calendar (CPI monthly, payrolls monthly, FOMC 8×/yr,
daily directionals once per morning), not per-ticker cron spam — ported from the sports
stack's load-once batch pattern. Each run executes freeze → settle → score in order.

- **One ledger of record.** The journal tables replace, not sit beside, the step-2
  `predictions`/`track_record` ledger: every engine that moves onto the §3 contract stops
  writing `predictions`, and the gate code (`tradehub/track_record.py`,
  `tradehub/gate_status.py`) is repointed at the journal in the same wave. `predictions` stays
  readable as pre-journal history (it is the "pre-journal context" of §2 — shown, never
  counted). Two live ledgers with two headline numbers is the failure this rule prevents.
- `journal_forecasts` — immutable freeze ledger. New Supabase migration, numbered after the
  highest migration on `main` at implementation time (currently `20260428000013`).
  `target` is a generic key (`kalshi:<ticker>`, `fred:UNRATE:2026-10:up`,
  `stooq:SPY:2026-09-30:up`) so non-Kalshi targets need no fake ticker; `market_prob` is
  nullable. `frozen_at` is server-generated. A `journal_calendars` table maps each target
  family to its cutoff rule (tz-aware). **Enforcement is by trigger, because the scan/settle
  jobs write as the service role and the service role bypasses RLS:**
  - `BEFORE INSERT`: overwrite `frozen_at := now()` (a client value is ignored) and
    `RAISE EXCEPTION` when `now() >= cutoff(target)` from `journal_calendars`, or when the
    target has no calendar row.
  - `BEFORE UPDATE OR DELETE`: `RAISE EXCEPTION`, with the one exception of flipping
    `rebuilt` from false to true. Also `REVOKE UPDATE, DELETE` from `anon` and
    `authenticated`; clients get SELECT at most.
  - The freeze-refusal, no-update and no-delete tests run against a real Postgres (a
    throwaway `postgres:16` container, as the migration checks already do), not only
    against the Python fakes. A trigger that exists only in a mock is not a guarantee.

  No updates, no deletes. `rebuilt` boolean column; rows with
  `rebuilt=true` are excluded from every stat by rule (see below). All timestamps are
  tz-aware (`America/Chicago` for freeze/cutoff display, UTC in storage) — naive-local
  time rotted the quarantine fixtures in #46, and the ledger must not repeat it.
- `journal_settlements` — actuals plus per-row Brier, written only by the settle job.
- The two existing sinks keep their meanings untouched: `kalshi_edges` (trade proposals,
  still gated) and `kalshi_quarantine_edges` (quarantined rows). The journal's quarantine
  section reads from the quarantine sink — quarantine now means *"scored in public,
  excluded from trade proposals and headline stats,"* and the existing safety invariant
  plus its tests pass unchanged.
- REST contract in the `/kalshi-feed` shape: frozen snapshots + calibration buckets served
  straight from the journal tables for downstream consumers.

**Failure rules (all pinned by tests):** a missed freeze is a gap in the ledger, never a
backfill — the run logs the miss and moves on. Post-event "rebuilt" rows are displayed but
never counted. A failed settle retries on the next run; scoring is idempotent.

**Retention:** freeze rows are the audit trail and are never deleted. At 24 months they
move to partitioned archive tables — still queryable, still counted, out of the hot path.

**Assumptions (verified 2026-09-29 against production):** both `signal_events` and
`kalshi_quarantine_edges` exist in production; `/shadow` remains Alpaca-credential-gated independently of this spec;
FRED key is present on the VPS.

## 5. Migrated and extended engines (wave 1)

**CPI + FOMC.** The existing CPI nowcast (Cleveland Fed PIT vintages,
`Normal(nowcast + bias, sigma)`, Kalshi KXCPI bucket mapping) publishes through the §3
contract with no model changes: its probabilities are already real. FOMC decisions have no
standalone engine — the wave-1 FOMC forecaster maps the existing CPI/labor nowcast inputs
to a decision probability at implementation time (small new mapping, not a new model).
Expect it to lose: FOMC decisions are usually priced near-certain days out. So it ships
alongside the Kalshi pseudo-forecaster (§8) from its first row, labelled experimental, and it is
the first candidate for `retired` if it can't beat that baseline.
First journal content; the pipeline is proven graded before new modeling lands.

**Labor.** Payrolls-threshold probabilities publish as-is — the ridge nowcast in
`labor.py` already emits them. UNRATE direction and JOLTS quits direction are new fits on
the same ridge pattern: small new work, wave 1, same contract and tests. All three settle
against FRED vintages (PAYEMS, UNRATE, JTSQUL); there is no consensus feed anywhere in the
journal. "Surprise" is defined as model-nowcast vs actual. Rationale: a paid or scraped
consensus feed would be the spec's weakest dependency; direction-vs-prior plus
nowcast-vs-actual is self-settling and free forever.

## 6. Sentiment meter v1 (wave 1)

Daily composite predicting **next-day SPY direction**, frozen at **08:00 CT** (pre-open).
Components, all free (FRED needs the free key the VPS already has): VIX (FRED VIXCLS), put/call ratio (delayed; exact
endpoint named with free-access evidence at plan time — no HTML scraping), CNN Fear &
Greed internal JSON (cached; stale values flagged `stale=true`, never silent), HY spread
(FRED BAMLH0A0HYM2), market breadth (Stooq advancers/decliners), GDELT DOC 2.1 news tone
via the `vaderSentiment` PyPI package (ships its own lexicon — no NLTK data download on
the VPS; the `sentiment_filter.py` lesson stays learned), vendor-pinned in the repo. Each component z-scored vs its trailing-252-day history, combined by fixed
weights documented in the repo.

**Point-in-time rule for the 08:00 CT freeze.** Every component value carries its observation
date *and* its publish time, and the meter uses only values published before the freeze. FRED
series such as VIXCLS and BAMLH0A0HYM2 typically land a day late, so at 08:00 CT on day t the
freshest value is usually t−1 or t−2. The backtest must apply the same rule via FRED
`realtime_start` vintages, or it is scoring information the live meter never had.

**Weakest-dependency rule, applied evenly.** CNN Fear & Greed's JSON is an undocumented
internal endpoint, and Stooq "breadth" (advancers/decliners) is not a confirmed free series.
Both are *optional* components:
- when missing or stale, their weight is renormalised across the rest and the row records
  which components were present;
- the meter is required to run on the FRED components alone.

Every source is reachability-checked **from the VPS** at plan time. The keyless ALFRED/FRED
web hosts already refuse connections from it, so a source verified from a laptop is not
verified. Deferred to v2: AAII weekly, Kalshi tail-odds positioning
proxy, StockTwits (license unverified as of Sep 2026).

Output is both score and probability: **score (−100/+100)** for display, **logistic-mapped
probability** for scoring. Cold start: fixed prior-slope logistic with documented constants,
probabilities labeled `provisional` until 60 settled days, then isotonic fit on walk-forward
history — never re-fit on the scored period. Settlement: SPY daily bars (Stooq, adjusted
close). **Target, exactly:** `up` iff adjusted close(t) > adjusted close(t−1), where t is the
first NYSE session opening after the freeze. There is no freeze on non-session days (NYSE
holiday calendar in `journal_calendars`), and an unchanged close counts as not-up. Wave-2
directionals use the same definition on their own session calendar (FX: the Stooq daily close
convention, stated on the tile). v1 covers SPY only; no BTC forecaster until §12's lead-lag study justifies one.

## 7. Walk-forward quant replacement (wave 1)

Target: **SPY next-day direction** — shares the meter's settlement source and daily cadence,
so one settle job grades both. Training lives in-repo (`tradehub/models/spy_direction/`):
walk-forward expanding window, monthly refit, never trained on the scored period; versioned
artifacts with SHA hashes plus a manifest (params, train window, feature list); the loader
refuses any artifact whose hash is not in the manifest. Features are price/volume/breadth
derived only. No remote downloads; no pickles from outside this repo. Enters the journal
under the §3 contract, gated like everything else.

## 8. Wave 2–3 forecasters

**Wave 2 (one pattern, three targets):** VIX next-day direction (direction scored; level
shown as context), gold daily direction (Stooq XAUUSD daily close; all Stooq symbols
verified at plan time — `GC=F` is Yahoo notation), EUR/USD daily direction
(Stooq daily close). All freeze 08:00 CT, settle on the next close, scored identically to
SPY. No new modeling: naive baselines (previous-day persistence + climatology) publish
first so the journal has honest company for any later model — and baselines implement the
full §3 contract including freeze tests, no unscored decoration. A fancier wave-2 model
must beat its baseline's posted Brier to graduate from `provisional`.

**Wave 3:** Housing — Case-Shiller national HPI m/m direction, frozen monthly on the FRED
release calendar with the ~2-month data lag stated on the tile (no intra-month nowcasting
in v1). Earnings — sign of (reported EPS vs year-ago quarter) for a watchlist defined in
repo config, self-settling from filings with no consensus feed (deliberately: §5's
weakest-dependency rule applies here too — no Yahoo scraping). Frozen pre-announcement, method a walk-forward event
model continuous with the BDI 513 earnings-call/event-returns work. Kalshi-vs-model —
the market baseline scored as a pseudo-forecaster (Kalshi-implied probability entered as
the forecast) on every market-linked target, so Brier Skill Scores are apples-to-apples
rather than model-vs-constant. Sports — predictors plug in as *consumed graded outputs* via the
`/api/kalshi-feed` contract; the journal never re-settles games. Today only NFL and CFB serve
that feed (step 7a). NBA, PL and F1 join only after each ships the same frozen pre-game feed,
so wave 3 lists NFL + CFB, and the other three are a named follow-up, not an assumption.
PR #27's ranking, window and inversion logic is the sports consumer's input, so it is kept,
not superseded.

## 9. Cuts

- `/lab` removed; route redirects to `/journal` (no 404s). `PredictionLab.tsx` plus its API
  scaffolding deleted, including the MACRO-tab sports-parlay cards.
- `macro_engine.py` deleted with its tests and references (git history keeps it).
- `quant_engine.py` remote-pickle loader deleted; replaced by §7.
- `sentiment_filter.py` lazy FinBERT/zero-shot path deleted on meter launch.
- The engine catalogue (`engine_health.py` + `/models`) gains a third verdict, **retired**:
  deleted engines leave a tombstone (removed date, reason, replaced-by) instead of
  vanishing. The truthfulness story stays intact through deletions.

## 10. Gates

- **Display gate:** any forecaster appears from its first frozen row; headline stats
  aggregate only post-calibration forecasters.
- **Calibration gate:** buckets are fixed at 50–60 / 60–70 / 70–80 / 80–90 / 90–100
  *confidence* (a 0.30 forecast is 70% confidence in "no", mirrored as in the existing
  `bucketize`), with 20+ resolved samples per bucket before joining headline
  aggregates or any +EV claim (ported from the sports stack). Until then the tile reads
  `provisional`.
- **Counting rule (from the step-2b ruling, unchanged):** counts are *targets*, not rows.
  Repeated forecasts of one target are weighted 1/k, and every (forecaster, version) has its
  own record.
- **Baselines.** "Skill vs market" exists only where a market exists. Kalshi-linked targets
  score BSS against the Kalshi-implied pseudo-forecaster. Non-market targets (SPY/FX/gold
  direction, UNRATE/JOLTS direction, housing) score BSS against climatology, with
  persistence shown beside it, and the tile says which baseline it uses. The headline "Brier
  skill vs market" aggregates market-linked targets only.
- **Promotion gate (unchanged rule, now evaluable):** paper-only until **200+ settled targets
  for daily cadence, or 50+ for monthly/meeting cadence** (CPI, labor, FOMC, housing, the §6
  rule of the original spec; at 200, a monthly engine would need about 16 years), **and**
  positive Brier Skill Score vs its baseline, with edge computed net of
  Kalshi taker fees. Fee modeling in `fills.py` is in this spec (§11) precisely so the gate
  can be evaluated rather than deferred. Until it clears, all Kalshi copy stays "public
  market-data + demo API client."

## 11. Journal UI

New flagship route `/journal`. `/scoreboard` stays as the engine catalogue (claims ×
verdicts, now with `retired` tombstones); `/models` stays; `/shadow` unchanged.
Three blocks: **(1) ledger hero** — N settled, Brier skill vs market, per-forecaster tiles
in the sports model-vs-market pattern (model probability large, Kalshi-implied beneath, same
units — the disagreement is the point); **(2) calibration curves** — reliability diagrams
per forecaster, 50%-baseline markers, bias readouts ("CPI runs hot by ~0.1pp"); **(3)
quarantine section** — weather/gas rows from the quarantine sink, visually quarantined,
excluded from all headline numbers, carrying their artefact/restatement labelling.

## 12. Fees and testing spine

`fills.py` already prices taker fees (`shared.kalshi_fees`, used by `backtest/fills.py`);
this spec pins that schedule with mutation-grade tests (any fee-constant mutation must
fail) and adds spread-cost modeling. Until both land, edge claims stay gross-of-spread
and say so. Every
journal number traces to a pinned test: freeze-refusal (late write refused; mutation
removing the cutoff fails it), settle-idempotency, no-backfill (`rebuilt=true` excluded —
test asserts the exclusion, mutation flipping the flag fails), fee-schedule pins, and the
existing quarantine-safety test untouched. Standing verification: full pytest twice
(including the second clock), `ruff --select F401,F811,F821`, typecheck, vitest, build;
mutations shown to fail.

## 13. Future work (specced, not built)

Real macro-probability model (PIT FRED vintages → calibrated probability, same gates; the
Glasgow tail-thinness hypothesis is the named first experiment). Crypto v1.x (venue
lead-lag measurement first; forecaster only if the study justifies it). Rates (10Y).
Cross-venue lead-lag studies as pure measurement. No OOS re-tuning, ever — publish the null.

## 14. Open questions for Kevin

1. CPI/FOMC in wave 1: included (CPI existing, FOMC mapped from its inputs, §5) —
   confirm, or labor-only launch?
2. Earnings in wave 3 vs v1.x — keep, or defer with crypto?
3. Watchlist names for earnings — your call at implementation time (config file, not spec).
4. **Weather conflicts with your 2026-09-27 ruling.** That ruling was "try new features";
   this spec quarantines weather (scored in public, excluded from headline stats). Both can
   hold: quarantine is where it lives *while* a discrimination hypothesis is tried, and it
   graduates only by beating the market. Confirm that reading, or pick one.
5. FOMC: keep the CPI/labor-mapped model in wave 1 (labelled experimental, next to the
   market pseudo-forecaster), or ship only the pseudo-forecaster + climatology until a real
   rates model exists (§13)?

Resolved by Kevin, 2026-09-29:
- Q4: YES. Weather stays in quarantine (scored in public, out of headline stats) while a
  discrimination hypothesis is tried, and graduates only by beating the market.
- Q5: YES. The CPI/labor-mapped FOMC model ships in wave 1, labelled experimental, alongside
  the Kalshi pseudo-forecaster.

(Resolved in amendment: no consensus feed anywhere — labor and earnings are both
self-settling. Former Q2 retired.)
