# Remaining Work (2026-10-16)

Order, each its own PR, plan-first where the plan says "design plan":

1. `2026-10-08-weather-ensemble-forecasters.md` (verified; in progress).
2. `2026-10-16-ercot-peak-demand.md` (design plan; a real Kalshi market exists).
3. `2026-10-16-retire-old-weather-engine.md` (small; after weather has 2+ days of results).
4. `2026-10-16-attention-vs-markets-study.md` (from 2026-11-01).
5. `2026-10-16-maker-fill-study.md` (from 2026-11-08).
6. Disk: the order-book recorder adds about 38 MB a day; add a retention rule (delete files older than 60 days) in the same PR as the maker-fill study, or earlier if the VPS passes 80% full.

Watch, do not build: NFL winners and spreads show small positive skill vs the Kalshi price on 31 to 37 scored contracts. Re-check on 2026-11-01. A forecaster only counts as promising at 200 scored contracts with a positive interval.
