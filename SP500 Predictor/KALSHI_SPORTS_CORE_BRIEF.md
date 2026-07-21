# Kalshi Sports Core: Critique of the 7/19 Memo + Build Brief for Football & NBA Engines

Prepared 2026-07-19. Scope: narrow the platform down to Kalshi sports markets, with `football_engine.py` (soccer) and `nba_engine.py` as the two predicting engines to build into the real core, per your direction. This doc is meant to be pasted into Claude Code as the working brief — Part 1 is critique, Part 2 is what I verified by reading the actual code, Part 3 is research that changes the plan, Part 4 is the phased build brief.

---

## Part 1 — Critique of the original memo

**What holds up.** The architecture praise (VPS + Supabase Realtime + Vercel), the security find (the three `Demo Api Key.txt` files), and the general framing of `shadow_performance.py` as the most valuable file in the repo are all accurate — I re-verified the security finding below. The Kelly-criterion-as-connective-tissue idea is sound and still applies once you narrow scope to two sports engines instead of eight domains.

**Where it's wrong, specifically about the two engines you want to keep.** The memo rates `football_engine.py` **"Keep"** and lists `nba_engine.py` as **"Not audited."** Both calls undersell the actual problem. I read both files end to end (see Part 2). `football_engine.py` is not keep-as-is: its live Kalshi price is a hardcoded constant, so every edge it has ever flagged is fake. `nba_engine.py` is more sophisticated than the memo assumed, but it is dead code — it's not imported anywhere the live scanner runs, and its own Kalshi cross-reference can never succeed given how the shared Kalshi client is written. Neither of these is a "some engines are stubs" footnote — for the two engines you've decided are the core, they're the whole story.

**What the memo missed entirely.** It never looked at `shared/background_scanner.py` or `SP500 Predictor/src/kalshi_feed.py` — the actual data plumbing both sports engines depend on. That plumbing has a category filter that throws out Sports by design. The memo's "keep the hosting model, it's clean" verdict is about compute/serving, not about this specific gap, so it's not wrong, just silent on the thing that actually blocks your stated priority.

**What's now stale.** The memo frames prediction markets as "consolidating toward incumbents" and treats sports as one vertical among many. Current Kalshi volume data (Part 3) shows sports is no longer one vertical among many — it's the majority of the platform's trading volume. That reframes your instinct to focus here as the more, not less, defensible call versus the memo's implied "watch weather/macro" default.

---

## Part 2 — What I verified by reading the code (not the docstrings)

### `shared/.../kalshi_feed.py` — the structural blocker for both engines
`get_all_active_markets()` fetches events, then filters to a `TARGET_CATEGORIES` allowlist that explicitly excludes `Sports` — the code comment says it's "to bypass the 15k sports parlay flood." This is the one shared Kalshi client both sports engines are supposed to use. As long as this filter stands, no sports engine in this repo can ever get a real Kalshi price through the normal path. This is the single highest-leverage fix — everything else is downstream of it.

### `football_engine.py` (EPL/La Liga soccer)
The Understat xG fetch and Poisson goal-simulation are real, non-trivial modeling work — keep that part. But `find_opportunities()` sets `live_price = 45.0  # Placeholder for retail sentiment` and diffs the model's home-win probability against that fixed number for every match, every run. It also only ever scores the `HOME_WIN` outcome — draw and away-win edges are computed (`calculate_poisson_edge` returns all three) but never evaluated or acted on. `evaluate_market()`'s `if True:` gate means the 8% edge threshold it claims to enforce is checked *after* the function already decided to return a payload — the threshold only actually gates in `find_opportunities()`, not in the method whose docstring says it does the gating. None of this is a "stub" the way `eia_engine.py` is a stub — it looks fully wired, which makes it more dangerous, not less.

### `nba_engine.py`
This is the better-built of the two: rolling-average + opponent-DRTG-adjusted Gaussian model, ESPN injury monitoring, back-to-back fatigue penalty. But:
- It is **never imported by `background_scanner.py`**. I grepped the whole `shared/` tree — zero references. It doesn't run live today, at all.
- Its Kalshi cross-reference (`_find_kalshi_market`) filters `get_all_active_markets()` output for `"NBA"` in the ticker — but per the finding above, that function never returns Sports-category markets in the first place. `kalshi_price` is always `None`; the only way a signal is ever emitted is via the injury-flag fallback path, never via a real priced edge.
- `is_home = True` is hardcoded for every player in every game — a real bug, not a placeholder comment.
- The dict keys are inconsistent across the file: `get_signals()` builds opportunities with keys `edge`, `confidence`, `asset`; the sort call and the `__main__` demo block reference `edge_pct`, `model_prob_over`, `player`, `line`, `injury_flag` as top-level keys that don't exist on that dict. The `__main__` block would throw `KeyError` if run. This means the demo path has never been executed successfully post-refactor.

### Test coverage gives false confidence here specifically
`test_sports_data_quality.py` exists and does check real things (Poisson probabilities sum to ~100%, edge math on `evaluate_market`). But `test_nba_sanity_checks` only unit-tests `_estimate_prob_over()` with a hand-built features dict, then builds its own **mock signal dict** with keys `player`, `model_prob_over`, `kalshi_yes_ask` — the same wrong keys the buggy `__main__` block uses, not the real keys `get_signals()` actually produces. The test passes because it's testing a schema that doesn't exist in the real code path, not because the real pipeline works. There is no test anywhere that calls `NBAEngine().get_signals()` or `FootballKalshiEngine().find_opportunities()` end to end. The "98 pytest tests, real CI discipline" praise in the memo is accurate as a general statement and does not extend to these two engines.

### Security — re-verified, memo was right and complete here
`git ls-files | grep -i "\.pem$\|key"` confirms only the three `.txt` demo key files are tracked; the various `.pem` files in the repo (`kalshi_private.pem`, `kalshi_ed25519.pem`, etc.) are correctly excluded by `.gitignore`'s `*.pem`/`*.key` rules. Nothing new to add here — just confirming the memo's fix-this-week item is real and doesn't need expanding.

---

## Part 3 — Research that should change the plan

**Kalshi sports is not a side vertical anymore.** The week spanning the NBA Finals and World Cup group stage was Kalshi's largest ever — $8.99B in volume, 86.9% of it sports. Kalshi's contract categories include a first-class `Sports` category (NFL, NBA, MLB, golf, MMA, tennis, soccer) with moneyline, spread, total, and futures market types. `kalshi_feed.py` throwing this category away isn't a minor oversight given your stated priority — it's excluding the majority of the platform.

**Kalshi's fee formula (current, exact).** Taker fee = `ceil(0.07 × contracts × P × (1−P))`; maker fee is 25% of that. Fee peaks at 50¢ (1.75% of notional) and shrinks toward the extremes (0.7% at 90¢). This replaces the memo's vague "fee death zone" language (which was about weather specifically) with a formula you can put directly into an edge-net-of-fees calculation for both engines — a real edge threshold should be edge-after-fees, not gross edge, especially since your soccer engine's 8% and NBA engine's 12% thresholds were both picked before either engine had a working price feed to test them against.

**BallDontLie has repriced since this engine was likely written.** Free tier is now 5 req/min with "Basic" data access only (teams/players/games). Player stats, injuries, and props are separately gated: All-Star ($9.99/mo per sport) for extended data, GOAT ($39.99/mo per sport) for full access including injuries and props. `nba_engine.py`'s `_fetch_recent_stats()` hits the stats endpoint the free tier likely no longer covers at the granularity the code assumes — worth confirming against current docs before assuming the free path still works. Separately: BallDontLie now ships **BDL Lab** — a hosted backtesting product with 50+ prebuilt factors, historical odds, and moneyline/spread/total backtesting against real opening lines. Given the original memo's own complaint that this repo has three disconnected, weaker backtesting systems, it's worth deciding whether to build NBA backtesting in-house or lean on BDL Lab and keep `shadow_performance.py` as the live forward-validator on top of it.

**Understat is still active** — 2025/26 season EPL/La Liga/Serie A xG tables are live and updating as of this research. `understatapi>=0.6.1` in `requirements.txt` is a reasonable pin to keep. This isn't a data-source risk the way the eia/weather findings were.

**Dixon-Coles over plain Poisson.** Independent Poisson measurably underestimates draws and narrow-margin outcomes (in one large sample, 0-0 was 8.4% actual vs. 7.1% Poisson-predicted). Dixon-Coles adds team attack/defense parameters, a home-advantage term, and a correlation parameter that corrects specifically the 0-0/1-0/0-1/1-1 scorelines. Since `football_engine.py` currently only trades `HOME_WIN` and ignores draw/away edges entirely, moving to Dixon-Coles and actually pricing all three outcomes (Kalshi soccer markets typically list separate Yes/No contracts per outcome) is a bigger unlock than it sounds — it roughly triples the addressable market per fixture.

**Devig against a real line, not a constant.** Standard practice among sharp bettors is to devig a broad multi-book consensus (or a sharp single book like Pinnacle) rather than compare a model to one book's raw price — a wider consensus produces a materially sharper fair line than any single source. This is directly relevant here: even once `kalshi_feed.py` is fixed to return sports markets, Kalshi's own YES/NO prices already have a small built-in spread; the model probability should be compared to Kalshi's midpoint or a devigged fair price, not the raw ask, the way `evaluate_market()` currently does with a bare price diff.

**Open scope question — "football engines," plural.** The repo has exactly one football engine and it's soccer (EPL/La Liga), not NFL. If you actually meant American football/NFL is in scope too: `nfl_data_py` is deprecated as of this year in favor of **`nflreadpy`**, the current maintained package for play-by-play, rosters, and schedules from the nflverse project. NFL is also one of Kalshi's largest sports by volume alongside NBA, so it's a defensible addition — but it's a new engine, not a fix to an existing one, and would extend the timeline below. Flagging this rather than assuming either way.

---

## Part 4 — Build brief (paste into Claude Code)

**Phase 0 — Unblock the data layer (do this before touching either engine).**
1. In `kalshi_feed.py`, add `Sports` to `TARGET_CATEGORIES` (or build a parallel `get_active_sports_markets()` that fetches Sports events directly rather than reworking the generic fetcher — the "15k parlay flood" comment suggests Sports events need their own pagination/filtering strategy, likely by league ticker prefix rather than pulling every sports event).
2. Confirm ticker formats for the actual Kalshi soccer and NBA contracts you'll trade (moneyline vs. prop tickers look different — `nba_engine.py`'s assumed `NBAPTS-LEBRON-O29.5` format needs verifying against live Kalshi data, not assumed).
3. Add a fee-aware edge function: `net_edge = model_prob − kalshi_fair_price − fee(contracts, price)`, using the exact fee formula above, shared by both engines instead of each inventing its own threshold.

**Phase 1 — Fix `football_engine.py`.**
4. Replace `live_price = 45.0` with a real Kalshi price pulled through the Phase 0 fetcher; if no live market exists for a fixture, skip it — do not fall back to a constant.
5. Score all three outcomes (home/draw/away) against their respective Kalshi contracts, not just home win.
6. Swap the plain Poisson simulation for Dixon-Coles (team attack/defense params + ρ correlation term) — meaningfully improves draw and narrow-margin pricing, which is exactly where soccer markets cluster.
7. Remove the `if True:` no-op gate in `evaluate_market()`; make the edge threshold check live inside the function whose docstring claims to own it.
8. Write a test that calls `find_opportunities()` end to end against a mocked Kalshi response and a mocked Understat response — not just the Poisson math in isolation.

**Phase 2 — Fix and wire in `nba_engine.py`.**
9. Fix the dict-key mismatch (`edge` vs `edge_pct`, `confidence` vs `model_prob_over`, `asset` vs `player`) so the sort and any downstream consumer actually work.
10. Remove the hardcoded `is_home = True`; pull actual home/away from the games fetch you're already calling.
11. Wire real prop lines from BallDontLie's props endpoint (paid tier) or another props source instead of the fixed placeholder lines (22.5/7.5/5.5) — real lines are the thing you're supposed to be comparing against.
12. Import and register `NBAEngine` in `background_scanner.py` so it actually runs in the live loop — right now it's orphaned.
13. Replace the mock-schema test in `test_sports_data_quality.py` with one that calls `get_signals()` end to end against mocked BDL/ESPN/Kalshi responses, asserting on the real key names.
14. Decide on BDL tier: confirm whether current free tier still serves the stats endpoint this engine needs; budget for All-Star ($9.99/mo) or GOAT ($39.99/mo, adds real injuries/props/odds and removes the separate ESPN scrape) if not.

**Phase 3 — Shared validation layer.**
15. Extend `shadow_performance.py`'s Brier-score/calibration approach to log every football and NBA signal the same way it already logs crypto — this is the "Edge Ledger" idea from the original memo, just scoped to the two engines you actually want, and it's the part of this repo that's genuinely hard to buy off the shelf.
16. Decide build-vs-buy on backtesting for these two engines specifically: BDL Lab now ships prebuilt sports backtesting against historical odds, which may be faster than extending the repo's existing (and per the original memo, disconnected) backtesting code.

**Open item for you, not Claude Code:** confirm whether "football engines" means soccer-only (fix what exists) or NFL is genuinely in scope (new engine, `nflreadpy` as the data source, larger scope).

---

### Sources
- [Kalshi Sports Price Data API — Depth, Results, Injuries | ScoreTape](https://kalshisportsdata.com/)
- [Kalshi booms on sports — SGI Europe](https://www.sgieurope.com/technology/kalshi-booms-on-sports/121847.article)
- [Kalshi Fee Schedule (PDF, July 2026)](https://kalshi.com/docs/kalshi-fee-schedule.pdf)
- [Kalshi Fee Schedule](https://kalshi.com/fee-schedule)
- [BALLDONTLIE — pricing and product pages](https://www.balldontlie.io/)
- [Understat.com — EPL xG table, 2025/26 season](https://understat.com/league/EPL)
- [understatapi on PyPI](https://pypi.org/project/understatapi/)
- [Dixon–Coles model — Grokipedia](https://grokipedia.com/page/DixonColes_model)
- [Dixon-Coles Model Explained — football-bet-prediction.com](https://football-bet-prediction.com/articles/dixoncoles-model-explained-improving-poisson/)
- [No-Vig Fair Odds — ChanceMetrics](https://chancemetrics.com/no-vig-calculator)
- [No Vig Odds — OddsShopper](https://www.oddsshopper.com/articles/betting-101/how-to-remove-the-vig)
- [nfl_data_py — deprecation notice, PyPI](https://pypi.org/project/nfl-data-py/)
- [nflreadpy — GitHub, nflverse](https://github.com/nflverse/nflreadpy)
