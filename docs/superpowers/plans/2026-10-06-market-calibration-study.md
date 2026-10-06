# Market Calibration Study (Is Kalshi Right?)

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (or subagent-driven-development). This is a research plan: the deliverable is an answer with error bars, not a model. Plan-first: post your concrete task list as a PR comment on the docs PR before building, test first.

**Goal:** Find out, with enough independent markets to trust the answer, whether Kalshi prices are miscalibrated in a way that survives fees and spread, by category, price and time to close.

**Why this first:** it needs no model. If cheap contracts resolve YES less often than their price says (the favorite-longshot pattern common in betting markets), a rule as simple as "sell the longshots" might beat every model we have built, and the journal could grade that rule like any forecaster.

## First cut (reviewer, 2026-10-06, from our own settled rows, one row per market, earliest scan, 1,221 markets over 10 days)

| Market price | Markets | Priced | Happened | Gap | Standard error |
|---|---|---|---|---|---|
| under 10% | 217 | 5.0% | 1.4% | -3.6 pts | 1.5 |
| 10-30% | 359 | 19.5% | 15.6% | -3.9 pts | 2.1 |
| 30-70% | 449 | 47.6% | 45.9% | -1.7 pts | 2.4 |
| 70-90% | 126 | 80.0% | 82.5% | +2.6 pts | 3.6 |
| over 90% | 70 | 95.3% | 98.6% | +3.3 pts | 2.5 |

Every bucket leans the same way (longshots overpriced, favorites underpriced), but only the under-10% bucket is about 2.4 standard errors out. By engine: gas and weather longshots (under 30%) resolved 5 points below their price (about 1.8 SE each); weather mid-priced contracts resolved 18 points above (34 markets, 2.2 SE, almost certainly a few correlated days); NFL favorites +6 points (1.7 SE).

**Do not trust this yet:** 10 days; markets on the same day and same series are correlated, so the real standard errors are larger; our scanned markets are not a random sample of Kalshi; and no fee or spread has been applied. The study exists to replace this with a proper answer.

## Method (all of this is specified so two people get the same answer)

1. **Universe.** All settled Kalshi markets, from the public history API (`tradehub.backtest.kalshi_history.KalshiHistoryClient.settled_markets`, `candles`, `trades`), for as many series and as far back as the API serves, starting with the series we already scan (weather highs, gas, CPI, payrolls, KXNFL/KXNCAAF game, spread, total) and then the largest others by volume. Store raw fetches under `artifacts/calibration/` (git-ignored) so reruns do not refetch.
2. **One observation per market per horizon.** For each market take the price (last trade, else mid) at fixed horizons before close: 1 hour, 6 hours, 1 day, 3 days. Never a price after the outcome was knowable. A market with no trade near a horizon has no observation at that horizon (a gap, not a guess).
3. **Grouping.** Price buckets (under 5, 5-10, 10-20, 20-40, 40-60, 60-80, 80-90, 90-95, over 95%), by category (weather, energy, macro, sports, other) and by horizon.
4. **Uncertainty that is not naive.** Cluster by event (all strikes of one event are one cluster) and by calendar day; report cluster-robust standard errors or a block bootstrap (1,000 resamples, clusters as blocks). Every table shows n markets, n clusters, gap and a 95% interval. A cell with fewer than 30 clusters is labelled "too thin" and not interpreted.
5. **Out of sample.** Fit nothing on the whole history. Split by time: find patterns in the earlier 70%, report only on the later 30%. Say how many patterns were looked at (a multiple-comparisons count) next to any "significant" cell.
6. **Does it survive costs?** For each cell with a gap, simulate the trade it implies (buy NO on overpriced longshots, buy YES on underpriced favorites) at the horizon price with Kalshi's taker fee (`shared/kalshi_fees.kalshi_fee_cents`) and the observed half spread (use the candle bid/ask, not the mid), and also the maker case (quarter fee, but only count fills that the trade tape shows could have happened). Report expected profit per contract, per dollar risked, and the 95% interval. A gap smaller than fee plus half spread is "not tradeable", whatever its significance.
7. **Capacity and honesty checks.** Show volume per market so a result that only exists in markets nobody trades is flagged; show results with and without the single largest cluster.

## Deliverables

- `tradehub/research/calibration_study.py` (pure functions with unit tests on synthetic markets where the miscalibration is known, including a case with no miscalibration that must report none, and a clustered case that proves the clustered error is larger than the naive one).
- `scripts/` entry point that fetches, caches and writes `docs/research/2026-10-calibration-study.md` with the tables and a plain-language verdict: where Kalshi is wrong, by how much, whether it survives costs, and what the study could not tell us.
- If, and only if, a cell is significant out of sample after costs: a simple rule forecaster (for example "NO on contracts priced under 10% in category X at horizon H") registered in the prediction journal beside its Kalshi baseline, so it is judged live like every other model. No money moves; the site does not trade.

## Constraints

- Never write or print secrets; the history API is public, so none are needed.
- Respect the API's rate limits and cache aggressively; stop and report if the API refuses.
- A negative result ("Kalshi is well calibrated; nothing survives costs") is a complete and valuable answer. Do not search until something is significant; report the count of cells examined.
- Never push to `main`; one PR; paste the verification output; stop and report in 6 lines.
