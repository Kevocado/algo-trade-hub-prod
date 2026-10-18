# Visual Journal and a Jobs Page That Makes Sense

> **Status: design plan (impeccable-guided), not code-verified.** Mode: **Operate** (the visitor is checking whether the forecasters are any good). Plan-first: post your task list as a PR comment, then build test-first. Recharts 2.15 is already installed: use it, add no dependency.

## Critique of today (live pages, 2026-10-18; inline review, no sub-agent run)

**/journal**
- Four stat tiles then a table. Nothing is drawn. The reader cannot see *whether a forecaster is improving*, *where it is wrong*, or *how it compares with the market*: the three questions the page exists for.
- The tile "0.00 Brier skill vs market" is the pooled skill of market-linked forecasters and reads 0.00 by construction (the Kalshi baselines are in the pool). It looks like a result and is a tautology. Remove it from the top row.
- The table repeats "vs the Kalshi price" on every row and uses "Behind / Ahead" with no scale: -0.01 and -0.04 are both "Behind". The size of the gap and its uncertainty are the information.

**/jobs**
- Tiles read "72.6 / 69.4", "0.160 / 0.145", "42 / 42", "20": a pair with no labels saying which number is ours. "Ladder Brier", "Mean abs error vs first print", "Months our estimate was closer" are analyst jargon.
- "PAYROLLS (KXPAYROLLS) / UNEMPLOYMENT (KXU3)" mixes a plain word with a ticker. The shadow chip and `labor_nowcast@labor-v1` are internal names.
- One chart, "Nowcast vs Kalshi vs first print vs latest", with a y-axis scale that starts far from the data on first paint.
- The question a visitor actually has, "for each jobs report, who was closer, us or Kalshi, and by how much?", is never answered in a glance.

## Design direction (Operate: scanability and honesty over expression)
- **Chart first, number second.** Every page opens with the one picture that answers its question; numbers sit beside it as annotations.
- **One visual language:** the Kalshi price is always the same neutral line/colour (the reference), our forecaster is the accent, the naive baseline is a dashed grey. Skill is always drawn as a distance from zero with an uncertainty band; zero is a labelled line. Never a bare percentage.
- **Honest marks:** a gap inside two standard errors is drawn as a band that straddles zero and labelled "No signal"; a missing figure is a gap in the line and a word, never 0. No chart extrapolates.
- **Colour:** semantic only (ahead = one hue, behind = another, noise = neutral), validated for light/dark and colour-blind safety; the existing dark theme tokens are the authority. Read the `dataviz` guidance before choosing colours.
- Readable at 375px; every chart has a text equivalent (a table behind a "Data" toggle) and keyboard-reachable tooltips.

## /journal: what to build
1. **Hero chart: "Skill against the Kalshi price, by forecaster."** A dot-and-whisker (forest) plot: one row per market-linked forecaster, x = Brier gap vs the Kalshi price (negative is better) with a 95% interval whisker, a labelled zero line, sorted by gap, rows with under 30 settled shown hollow ("too early"). This replaces the table as the first thing seen. Data: the standings the front page already uses (`tradehub/journal/standings.py`); add the interval for live (non-replay) forecasters using the paired-Brier columns (`brier_on_baseline`, `n_baseline`) and a per-contract standard error computed server-side.
2. **Skill over time:** small multiples (one tiny line chart per forecaster, shared axes): cumulative Brier gap vs the market as contracts settle, with the band. This is how a reader sees "improving, flat, or luck". New API: `/api/journal/series?forecaster=` returning the running gap per settlement day (computed in Python, not TSX).
3. **Per-forecaster detail (on click, lazy):** the existing calibration curve, redrawn with the 45-degree reference and bin counts as bar heights under it, plus "forecast vs outcome" strip: the last 30 frozen forecasts as dots on 0-100% coloured by whether they happened.
4. **Weather and ERCOT row:** a small panel per family: our probability vs Kalshi's on each contract for the latest settled day (scatter on a 45-degree line, point colour = outcome).
5. **Keep:** the word budget test (intro under 15 words, copyWords cap), chips as one or two words, the "not counted" backtests section, a dash for any missing figure.

## /jobs: rebuild for a person
Rename it **"Jobs reports: us vs Kalshi"** and answer one question per report.
1. **Hero chart:** one row per monthly report (payrolls and unemployment as two tabs with plain labels, no tickers in view): the BLS first print as a marker, our forecast and Kalshi's as two dots, the closer one ringed. A reader sees at once who was nearer, every month.
2. **Three plain stats, labelled with who is who:** "We were closer in 20 of 42 reports", "Our typical miss: 72.6k jobs, Kalshi's: 69.4k" (units shown), "Probability score: ours 0.160, Kalshi's 0.145 (lower is better)". Hide the ladder-Brier jargon behind "How this is scored".
3. **Trend:** our miss minus Kalshi's miss per month as bars (above zero = Kalshi closer), so a streak is visible.
4. Internal names (shadow chip, `labor_nowcast@labor-v1`) move to a "details" disclosure.
5. Loading and error states say what is being fetched and what to do (no endless "Loading scorecard").

## Acceptance
- Each page: screenshot at 1280px and 375px attached to the PR; the detector run once (`impeccable detect --json <changed files>`) with findings fixed in one batch.
- Tests: a rendering test per chart that asserts the zero line and the "no signal" label appear when a gap is inside two standard errors, that a missing value renders a dash and no point, and that no chart receives a computed score from TSX.
- No new dependency; vitest, tsc, eslint and build green; backend suite at both clocks for any API change.
- API additions are read-only and need no migration; if one is needed, stop and tell Kevin.
