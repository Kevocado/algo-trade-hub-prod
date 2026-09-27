# Decision-lead tests: gas and CPI — evidence

Branch `analysis/gas-decision-lead`, from `origin/main` at `603c931`. Adds `--gas-lead-hours` to the
gas backtest, and uses it — plus the existing `--lead-days` for CPI — to test two of the four §5
hypotheses.

Both are "does deciding earlier help?" and both are answered **no**, but for opposite reasons, and
the difference is the useful part.

## The hypothesis

The gas engine loses to the market badly — Brier 0.1148 vs 0.0268 on `KXAAAGASD`. The §5 diagnosis was
that this is not "the model is slightly worse at the same task" but "the model is asked the question
too late": a market Brier of 0.0268 means Kalshi prices that morning's AAA print almost exactly two
hours before close, so there may be no signal left to extract at that lead.

If that diagnosis is right, **deciding earlier should help.** That is falsifiable, so I ran it.

## The measurement

Same window the prior report used (2026-06-01 → 2026-09-20), taker mode, point-in-time. The model was
not re-tuned; only the decision time moved.

| decision lead | decisions | fills | Brier (ours) | Brier (market) | ours ÷ market |
| --- | --- | --- | --- | --- | --- |
| **2h (production)** | 1982 | 274 | **0.1148** | **0.02676** | **4.29×** |
| 12h | 1944 | 405 | 0.11216 | 0.0519 | 2.16× |
| 24h | 0 | 0 | — | — | no quotes |
| 48h | 0 | 0 | — | — | no quotes |

Sanity check that matters: **the 2h row reproduces the published 0.1148 / 0.0268 exactly.** The harness
is unchanged in behaviour, so these numbers are comparable with every gas figure already in the repo.

## Reading it

**The model gets no better. The market gets worse.**

- Model Brier: 0.1148 → 0.11216. Essentially flat — it predicts from the previous settlement plus the
  RBOB change, and that information is available at either lead, so moving the decision buys it
  nothing.
- Market Brier: 0.02676 → 0.0519. It **doubles**, because 12h before close the AAA print is
  genuinely less certain.

So the ratio improves from 4.29× to 2.16×, and it would be easy to report that as progress. It isn't.
**The model is not getting closer to the market on merit — the market is getting further from the
truth.** The gate compares against the market *at the same lead*, and at 12h we are still 2.16× worse.
Moving the goalpost is not the same as closing the gap, and a 2.16× deficit is not an edge.

**And "earlier" is bounded by where the market exists.** At 24h and 48h, `n_unquoted` equals the full
decision count — every contract is dropped for having no quote at decision time. Kalshi has not priced
`KXAAAGASD` for the next morning's print that far out, so there is nothing to be better than. The
hypothesis's own prescription ("decide the previous evening") is therefore not executable on this
series at all.

## Conclusion

**The first half of the §5 gas hypothesis is refuted by measurement.** Gas has no edge at any lead
where a market exists, and no market exists beyond ~12h. The spec already said what this implies:

> *"If neither does, gas has no edge at any lead and the product should say so rather than keep
> scanning it."*

On the evidence, gas should be **retired as an edge engine** rather than kept scanning — it consumes
scan work, writes SHADOW rows, and dilutes the pages with a market the model cannot approach. The
honest presentation is as a **display** engine: it publishes a view of the AAA/RBOB picture without
claiming an edge, which is the same conclusion I reached independently for CPI.

What remains untested is the hypothesis' *other* half — **"or use intraday AAA."** That is a different
claim requiring an intraday AAA feed, and AAA is a weekly EIA publication, so I cannot test it with
what is available. It should be recorded as untested rather than folded into the conclusion above.

## What this does not change

- The 2h production behaviour. `--gas-lead-hours` defaults to 2h, and two tests pin that default, so
  every recorded backtest number stays valid.
- The gate. Gas stays SHADOW on its own merits, which it does by a wide margin.
- Weather, CPI and labor. Only gas was tested here.

## Reproducing

```bash
for h in 2 6 12 24 48; do
  python -m tradehub.scripts.backtest_engines --engine gas \
    --start 2026-06-01 --end 2026-09-20 --gas-lead-hours "$h"
done
```

Each run prints its own `decision_lead_hours`, and the value is recorded in the run config for
`--record`, so a stored row cannot be read without the lead it was measured at. That provenance is the
other reason this flag is in the repo: the 2h assumption was previously implicit in a module constant,
which is how it ended up baked into every gas number in the reports without anyone re-deriving it.

## Verification

```
time.monotonic = 5.0   ->  729 passed in 75.46s
time.monotonic = 1e7   ->  729 passed in 23.66s
ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

One existing test needed updating: `test_gas_cli_sizes_rbob_from_backtest_start` monkeypatches
`build_gas_decisions` with a double that did not accept the new keyword, so the signature change broke
it. The double now accepts `decision_lead` and records it.

---

# CPI: also refuted, for the opposite reason

§5's CPI hypothesis was to *"regress the market's own price on the nowcast publication timestamp and see
whether anything remains after it."* That is answerable directly, because `--lead-days` already existed.
2022-01-01 → 2026-08-31, 447 decisions, no code change needed:

| lead | decisions | fills | Brier (ours) | Brier (market) | ours ÷ market | P&L |
| --- | --- | --- | --- | --- | --- | --- |
| 0d (25 min before close) | 447 | 100 | 0.09675 | 0.06766 | 1.43× | −3.87 |
| 1d | 429 | 111 | 0.10004 | 0.07291 | 1.37× | −4.36 |
| 2d | 424 | 106 | 0.09993 | 0.07501 | 1.33× | −4.22 |
| 5d | 438 | 107 | 0.09417 | 0.07103 | 1.33× | −3.31 |

## The answer to the §5 question

**The market does not respond to the nowcast at all.** Its Brier at 5 days out (0.0710) is barely worse
than at 25 minutes (0.0677) — a difference of 0.003, against the 0.028 that separates the market from
our model. CPI contracts are priced about as accurately a week ahead as they are in the last half hour
before release.

So there is nothing for a nowcast-based model to exploit, because the market is not pricing off the
nowcast in the first place. It is pricing from something the nowcast does not contain — professional
forecasts, base effects, or its own aggregation of the same public information. If the market ignores
the nowcast, a model built on the nowcast cannot beat it by being early.

And the direction of the intuition is worth stating, because it is the opposite of gas: a nowcast model
should gain *relative* value the earlier it decides, since the market has more time to incorporate the
nowcast. It gains nothing. At 5 days out we are still 1.33× worse.

## The contrast with gas is the finding

| | market Brier at 2h / 25min | at 5d / 12h | what it means |
| --- | --- | --- | --- |
| **gas** | 0.0268 | 0.0519 | market's information is **exhausted** at the production lead; the question is spent |
| **CPI** | 0.0677 | 0.0710 | market is **flat**: efficient long before release, nothing to catch |

Gas fails because the market is *too good* at the moment we decide. CPI fails because the market is
*equally good at every moment we could decide*. Both produce "we lose", and they need different
explanations — which is why one hypothesis being refuted should not be taken as evidence about the
others.

## Confidence, honestly

**The robust CPI finding is the level, not the lead differences.** 447 decisions span roughly 56 monthly
releases at ~8 strikes each, and strikes within a release are highly correlated — so the effective
sample is ~56 events, not 447. The 0.006 spread in our Brier across leads is well inside what ~56
events can resolve, and I would not claim lead 5d is better than lead 0.

What survives the sample-size caveat is the two things that are large and consistent: we are
**1.33–1.43× worse than the market at every lead**, and the **market's own accuracy barely moves across
five days**. Both hold across two independent windows (2025-01-01→2026-08-31 gave 1.19–1.30×, the same
picture at smaller n).

## Conclusion for CPI

**Refuted as an edge engine, and the most salvageable of the losing engines.** At 1.33× behind the
market it is in the same league, unlike gas at 2.2–4.3×. But the gate requires *strictly better after
fees*, "same league" still fails, and P&L is negative at every lead. The honest presentation is a
**display** engine: a nowcast-derived view of the CPI picture, with no claim of an edge — which is the
conclusion §5 reached by reasoning and this run confirms by measurement.

The untested remainder: §5 also suggested checking whether the market's price correlates with the
nowcast publication *timestamp* specifically. The flat Brier curve is strong evidence it does not, but a
direct regression on publication time would be the cleaner test and is not what I ran.

---

# Weather: the calibration hypothesis is refuted, and provably so

§5's weather hypothesis was that the failure is **calibration, not discrimination**: *"the 60–70% bucket
is off by 12–21pp, which is a calibration failure, not a discrimination failure: the model ranks fine and
states its confidence too tightly."* The prescription was to recalibrate sigma per bucket per lead, with
the bar being the market's 0.0971–0.1124 rather than zero.

This is a testable claim with a clean answer, because the per-bucket calibration data already exists
(`BacktestResult.cal_buckets`) and the CLI simply does not print it. Run on 2026-06-01 → 2026-09-20 —
reproducing the published 0.1242 / 0.09713 on 672 decisions exactly:

| bucket | n | predicted | observed | miss (pp) | SE (pp) | z |
| --- | --- | --- | --- | --- | --- | --- |
| 50-60 | 13 | 0.5568 | 0.5385 | −1.8 | 13.8 | −0.13 |
| 60-70 | 23 | 0.6602 | 0.7826 | **+12.2** | 8.6 | **1.42** |
| 70-80 | 227 | 0.7723 | 0.7489 | −2.3 | 2.9 | −0.81 |
| 80-90 | 227 | 0.8456 | 0.9031 | **+5.8** | 2.0 | **2.93** |
| 90-100 | 182 | 0.9493 | 0.9231 | −2.6 | 2.0 | −1.33 |

## Two findings, and the first one indicts the gate

**1. The gate's stated reason is inside the noise.** `calibration_max_dev: 0.10` rejects weather for
"calibration miss 12.2% in bucket 60-70 (limit 10pp)". That bucket has **n = 23**, giving a standard
error of **8.6pp** — the miss is **z = 1.42**, which is not significant. A 23-sample bucket is vetoing
an engine on a coin-flip.

This is a real defect independent of the model: the calibration check applies a fixed absolute
deviation with **no minimum n and no significance test**, so thin buckets can reject a healthy engine.
CFB's calibration already contains buckets at n = 0. A bucket that thin can reject on any fluctuation.
The fix is a minimum-n or a significance test on the miss, and it belongs in `check_candidate` next to
the existing `calibration_min_n` check.

**2. Recalibrating sigma cannot close the gap, and this is provable rather than inferred.** Take the
model's predictions and replace each one with **its own bucket's observed rate** — that removes
calibration error entirely and leaves only resolution. It is the best Brier any pure recalibration could
ever achieve:

```
model Brier, actual                              = 0.12420
model Brier if PERFECTLY calibrated (oracle)     = 0.12294
market Brier                                     = 0.09713
```

**The oracle is still 0.0258 worse than the market.** Perfect calibration buys 0.0013 of a 0.0271 gap —
about 5%. So the hypothesis is refuted: the weather model's problem on this series is **discrimination**,
and no amount of sigma work touches it.

## A correction to the original diagnosis

The prior report described the 60–70% miss as *sigma being too tight*, i.e. overconfident. The
significant miss is in **80–90** (z = 2.93) and it points the **other way**: the model predicts 84.6%
where the outcome is 90.3%, so it is **under**confident there. And the bucket the gate actually fires
on (60–70) is the one that is not significant. So both the bucket and the direction in the original
diagnosis are wrong.

That does not rescue the engine — the oracle bound is what settles it — but it does mean the calibration
work would have been aimed at the wrong bucket in the wrong direction.

## Conclusion for weather

**Refuted as stated.** Not "recalibrate sigma" but "the model is less accurate than the market on
`KXHIGHNY` over this window, and the residual is discrimination." The right response is the same as gas
and CPI: stop treating it as an edge engine and present it as a display engine, unless someone has a
discrimination hypothesis (better features, a different target) rather than a confidence one.

Separately and independently worth fixing: **the calibration gate should not reject on a thin bucket.**
That one is actionable now, needs no model work, and would apply to every engine behind the same check.

---

# Labor: blocked, not skipped

§5's labor hypothesis — per-bucket calibration plus whether the 2003/2020-style revisions dominate the
error — is the one I **could not test**, and it is the one most worth running. 0.1792 vs 0.1659 is the
closest gap of the four engines, so it is the only one where the shortfall might be real rather than
structural.

The blocker is the same one recorded in `.agent/buffer/session_logs.md` from the FRED work:

```
RuntimeError: ALFRED request failed after retries:
  HTTPSConnectionPool(host='alfred.stlouisfed.org', port=443): Read timed out. (read timeout=60.0)
```

With `FRED_API_KEY` unset, `alfred_vintages.py` uses the keyless `alfredgraph.csv` host, which this
machine cannot reach. Verified there is no way around it locally:

- `TRADEHUB_ALFRED_CACHE` is unset
- no cache directory exists at `.cache/alfred`, `./cache/alfred`, or `~/Library/Caches/tradehub-alfred`
- the only alternative path is `api.stlouisfed.org` via `fred/series/observations`, which requires
  `FRED_API_KEY` — a secret I must not read or set

**This is a blocker, not a negative result.** No claim is made about labor here.

## How to run it

On the VPS, where `vps-stack/compose.yml` already provides both the ALFRED cache and the
`api.stlouisfed.org` path:

```bash
# inside the tradehub container, which has TRADEHUB_ALFRED_CACHE=/cache/alfred and a volume on it
python -m tradehub.scripts.backtest_labor --start 2023-03 --end 2026-08 --mode taker
```

Or from a machine that can reach `alfred.stlouisfed.org`, with `FRED_API_KEY` exported.

## What to check first, given the weather result

Labor's hypothesis is partly a **calibration** claim, and weather is the cautionary case: there, perfect
calibration could only close ~5% of the gap, so the calibration work would have been wasted. The
cheapest first step is the same oracle bound — replace each prediction with its bucket's observed rate
and compare against the market's 0.1659. If the oracle is still worse, the hypothesis is refuted the
same way, and the revision-tail question becomes the only one worth pursuing.

`backtest_labor.py` imports the same `run_backtest` as the other engines, so `result.cal_buckets` is
available there too — it is simply not printed, exactly as with weather.

---

# The calibration test fires on noise, by construction — and it conflicts with the admission gate

The weather analysis produced a fix I then had to take back. I wrote that the thin-bucket rejection was
"actionable now, needs no model work". On checking the arithmetic, it does not: it is the *same* class of
threshold incoherence as the 200-vs-42 finding, and fixing it naively makes things worse.

## The false-positive rate

`check_candidate` applies two different tests off one parameter, and the second is not meaningful at the
first one's sample size:

1. `bucket["n"] < calibration_min_n` → `calibration_insufficient` (admission)
2. `abs(mean_prob - hit_rate) > calibration_max_dev` → `calibration_off` (quality)

With `calibration_min_n: 20` and `calibration_max_dev: 10pp`, the widest a correctly-calibrated bucket
can be tripped by pure chance:

| bucket n | SD of the observed rate | 10pp is | P(false trip) |
| --- | --- | --- | --- |
| 20 | 11.2pp | 0.89 SD | **37.1%** |
| 23 | 10.4pp | 0.96 SD | **33.7%** |
| 30 | 9.1pp | 1.10 SD | 27.3% |
| 50 | 7.1pp | 1.41 SD | 15.7% |
| 100 | 5.0pp | 2.00 SD | 4.6% |
| 200 | 3.5pp | 2.83 SD | 0.5% |

**A perfectly calibrated engine trips `calibration_off` about 37% of the time at n=20.** Weather's
z = 1.42 on n = 23 is that expected behaviour, not bad luck. The check is a coin flip wearing a
threshold.

For the test to fire on fewer than 5% of well-calibrated buckets it needs **n ≥ 97**.

## The conflict, which is the actual finding

So the two tests want opposite things from the same parameter:

- **Admission** wants a *small* `calibration_min_n`, because the aggregate requirement is
  `n_buckets × min_n` and it must stay ≤ the reviewer's 100. At 10 buckets that means `min_n ≤ 10`.
- **The calibration test** wants `min_n ≥ 97` for its own 10pp comparison to mean anything.

**There is no value of `calibration_min_n` that satisfies both at 10 buckets.** Widening the buckets
does not rescue it either: at 4 buckets and 100 settled, each bucket holds ~25, still far short of 97.
Reaching 97 per bucket at 4 buckets needs roughly **390 settled**, which is nearly four times the
reviewer's own bar.

This also revises my own earlier recommendation. **`4 buckets × min_n 20 = 80` fixes the aggregate but
makes this worse**, not better: it keeps `min_n` at 20, so the calibration test stays a ~34% coin flip.
I presented it as the fix for the gate arithmetic, which it is — but I had not checked what the same
parameter does to the *other* test, and it is worth being explicit that the two cannot both be had.

## All three thresholds want the same number

| setting | value | what it implies |
| --- | --- | --- |
| reviewer's `MIN_SETTLED` | **100** | when the product is willing to judge an engine |
| candidate aggregate, coherent | **≤ 100** | `n_buckets × min_n` |
| `min_n` for a 10pp test at ≤5% false positives | **≥ 97** | when the calibration check means anything |

**100 is the number the design keeps arriving at.** The two settings that disagree with it are 20 and
200 — and `min_n: 20` is simultaneously too small to test calibration and, multiplied by 10 buckets,
too large to admit anything.

## What follows

**Recommendation: drop the per-bucket `calibration_off` test and let the reviewer make the call.**

- The candidate gate then does what it can do honestly: is this tradeable, is the window open, and is
  there *any* settled history in the bucket. That is testable at small n.
- The reviewer's scorecard is the thing designed to judge keep-or-drop, it already requires
  `n_settled ≥ 100`, and §6 of the redesign makes it a first-class page. Duplicating a noisier version
  of that judgement inside the admission filter is what produces the 37% coin flip.
- This is the same conclusion the weather oracle reached from the other side: the per-bucket test was
  never going to be the thing that separates a good engine from a bad one, because it is measuring a
  quantity too noisy at the sample sizes available.

I am **not** implementing this. It is a threshold decision, it changes which edges are candidates, and
it belongs with approval item 1 on #21 rather than arriving as a drive-by. What I would not do is leave
it described as "actionable immediately" in a PR comment, because it is not — it is the same
incoherence as the 200-vs-42 finding, viewed from the other side.

