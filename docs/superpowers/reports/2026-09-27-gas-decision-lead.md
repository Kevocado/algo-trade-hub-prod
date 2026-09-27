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
