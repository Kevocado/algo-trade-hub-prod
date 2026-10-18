# Improving the Models (with a protocol that cannot fool us)

> **Status: design plan, not code-verified.** Kevin wants the weak models improved. Improving a forecaster is allowed; fooling ourselves is not. Every item follows the same protocol.

## The protocol (applies to every item)
1. **Frozen before looking:** state the change and the metric (Brier gap vs the Kalshi price on the same contracts, with a standard error) before running anything.
2. **Time split:** develop on the earlier 70% of history, judge once on the later 30%. The judged number is reported once.
3. **Count the variants you tried** and report the count next to the result.
4. **New version beside the old:** ships as a new version string in the journal and runs live next to the old one. The live journal, not the backtest, is the verdict. Never edit or delete an old version's scorecard.
5. **Stop rule:** if the out-of-sample gap does not clear two standard errors better than the old version, say so and stop. No further tuning of that model.
6. **Free data only.**

## Candidates, by expected payoff and what is wrong with each
| Model | Live skill vs Kalshi | What is likely wrong | Try |
|---|---|---|---|
| College football winners / totals | -0.135 / -0.091 (about 120 and 100 settled) | Overconfident: the cautious copy loses far less. Predictions are too extreme | Shrink by a learned weight per kind (fit on earlier data, not fixed 0.25); try isotonic or Platt calibration on the predictor's outputs |
| NFL totals | -0.237 (41) | Same overconfidence on the over/under | Same calibration; check the sigma the pricing uses |
| NFL winners / spreads | +0.039 / +0.034 (31 / 37, positive and tiny) | Not a problem; too early | Do nothing; re-check at 200 |
| Weather (new) | not scored yet | Raw ensemble, no bias fix | Weather v2 at 200 settled: per-city bias, learned kernel width, blend with the Kalshi price |
| ERCOT peak | -22% vs the Kalshi mid (replay, 47 events) | The market reads the same weather plus intraday load | Add the day-ahead load forecast that ERCOT publishes as a feature; blend with the market mid |
| S&P 500 sentiment / quant | worse than the usual rate over 3 years | No signal in these inputs | Retire from the home page (keep recording); do not tune |
| Daily VIX | +0.012 vs usual rate, about 1.5 standard errors | Possible small signal | Leave running; judge at 200 live days |

## Order
1. **Calibration layer for all sports models** (the cheapest and most general fix): a per-model post-hoc calibration fitted walk-forward on settled journal results, shipped as `<name>_cal` versions beside the originals. Report the Brier gap vs the old version and the market with intervals.
2. **Weather v2** once a family has 200 settled contracts.
3. **ERCOT with the day-ahead forecast** as an extra feature, graded like the first version.
4. Retire the S&P 500 sentiment and quant models from the headline (keep recording them as baselines).

## Not in scope
New forecaster families, anything needing a secret, and any claim that a model beats the market unless the live journal shows it past two standard errors with at least 200 settled contracts.
