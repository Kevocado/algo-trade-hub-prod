# Gas: "decide earlier" is refuted — evidence

Branch `analysis/gas-decision-lead`, from `origin/main` at `603c931`. One commit. Adds
`--gas-lead-hours` to the gas backtest and uses it to test the §5 hypothesis.

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
