# Kalshi quote zeros — fabricate-a-zero fix

**Status:** fixed, 18 regression tests, full suite green. **Not merged** (merge = production deploy).

**Branch:** `fix/kalshi-quote-zeros` off `origin/main` (`676b2dc`)
**Worktree:** `/Users/sigey/Documents/Projects.nosync/algo-trade-hub-2026-09-28-kalshi-quotes`
(isolated so the concurrent frontend agent's uncommitted work on `feat/models-page` was untouched)

---

## 1. Before / after, for a market that is quoting right now

`KXHIGHNY-26SEP28-T64`, live payload pulled from
`GET /markets?series_ticker=KXHIGHNY&status=open` on 2026-09-28:

```json
{"ticker": "KXHIGHNY-26SEP28-T64",
 "yes_bid_dollars": "0.6200", "yes_ask_dollars": "0.6300",
 "no_bid_dollars": "0.3700", "no_ask_dollars": "0.3800"}
```

The legacy keys are **absent** from the object, so `.get('yes_ask', 0)` did not fall back to a
quote — it invented one.

| | yes_bid | yes_ask | no_bid | no_ask |
|---|---|---|---|---|
| before | `0` | `0` | `0` | `0` |
| after | `62.0` | `63.0` | `37.0` | `38.0` |

End-to-end through the real chain (raw payload → `process_markets` → `scan_quant_ml`), with a
70% model probability:

| field | before | after |
|---|---|---|
| `market_yes_ask` | `0` | `63.0` |
| `calculated_edge` | **`70.0`** (the entire probability) | **`7.0`** (70 − 63) |
| `kelly_bet` | `0` | `0.95` |
| `abs(edge) > EDGE_THRESHOLD` | `True` | `True` |

Site 2, `KalshiPortfolio.get_portfolio_summary`, same market, 10 contracts:
`current_price` was `0` and `market_exposure_dollars` `0`; now `62.5` and `6.25`. The exposure
formula was correct all along — only its input was fabricated.

---

## 2. Mutation output

Reverted both sites to the pre-fix code (`process_markets` back to `m.get('yes_ask', 0)`, and the
scanner's guard removed) and re-ran the new file:

```
FAILED tests/test_kalshi_quote_cents.py::test_process_markets_carries_the_real_quote
FAILED tests/test_kalshi_quote_cents.py::test_process_markets_does_not_fabricate_a_zero_price
FAILED tests/test_kalshi_quote_cents.py::test_quant_engine_never_fabricates_an_edge_without_a_price[no price fields at all]
FAILED tests/test_kalshi_quote_cents.py::test_quant_engine_never_fabricates_an_edge_without_a_price[explicit None]
FAILED tests/test_kalshi_quote_cents.py::test_quant_engine_never_fabricates_an_edge_without_a_price[zero ask is a price of nothing]
FAILED tests/test_kalshi_quote_cents.py::test_quant_engine_skips_only_the_unpriced_market
FAILED tests/test_kalshi_quote_cents.py::test_end_to_end_prices_the_edge_from_the_dollar_quote
FAILED tests/test_kalshi_quote_cents.py::test_end_to_end_unpriced_market_is_skipped_not_credited_with_an_edge
8 failed, 10 passed in 2.02s
```

with the diagnostic being the bug itself:

```
E       assert 0 == 63.0
E       assert (0, 0, 0, 0) == (62.0, 63.0, 37.0, 38.0)
```

and, running the mutated chain directly, the published record for the live market:

```
{'market_id': 'KXHIGHNY-26SEP28-T64', 'model_prob': 70.0,
 'market_yes_ask': 0, 'calculated_edge': 70.0, 'kelly_bet': 0}
```

The mutation was then reverted; the fixed run below is the tree as committed.

---

## 3. Test summary

Interpreter confirmed before believing any of it:
`/Users/sigey/.../algo-trade-hub-prod/.venv/bin/python` → `3.12.14`.

| run | result |
|---|---|
| baseline, pristine `origin/main` | **1102 passed, 0 failed** |
| baseline with `time.monotonic` = `1e7` | **1102 passed, 0 failed** |
| with the fix, full suite | **1120 passed, 0 failed** |
| with the fix, `time.monotonic` = `1e7` | **1120 passed, 0 failed** |
| new file alone | **18 passed** |
| `ruff check --select F401,F811,F821 tradehub tests` | `All checks passed!` |

**Baseline discrepancy:** the briefed 1099/3-failed baseline does not reproduce on a pristine
`origin/main` checkout — it is 1102/0. The 3 `test_alfred_vintages.py` failures are an artifact of
the main working tree, where the other agent's in-flight files are present; they do not appear
here and were not touched.

`tests/test_kalshi_quote_cents.py`, 18 tests:

- `yes_ask_dollars: "0.6200"` → `yes_ask == 62.0` — explicitly `!= 0.62` and `!= 0`
- rescale pinned **both directions**: dollars ×100 up, legacy cents left alone, and the two
  generations produce the identical dict so no caller can tell which schema it got
- rescale is exact: `"0.2900"` → `29.0`, `"0.0700"` → `7.0` (`repr` checked)
- no price fields → all four `None`, and `0 not in values`
- dollars win when both generations are present; `""`/garbage → `None`
- **site 1**: `process_markets` on the live payload → 62/63/37/38; with the price keys removed →
  all `None`; a legacy-only market still resolves
- **site 1 consumer**: a real 63c ask gives `calculated_edge == 7.0` and `kelly_bet > 0`; a market
  with no price (parametrised: absent / explicit `None` / `0`) yields **no snapshot record and no
  paper trade**, so `calculated_edge` cannot be emitted at all
- **end to end** through the real `process_markets`: edge priced at 63c, and the unpriced market
  skipped rather than credited with a 70-point edge
- **site 2**: `current_price == 62.5`, `market_exposure_dollars == 6.25`; unpriced market leaves
  the position with **no** `current_price` key rather than persisting `0`

---

## 4. The shared-normaliser decision

One function, `quote_cents(raw) -> dict[str, float | None]`, in
**`tradehub/markets.py`** — the existing pure raw-dict → typed parsing module, already the home of
`parse_market`, and importable from `tradehub/core/*` with no cycle (`markets.py` imports only
`tradehub.backtest.kalshi_history`). Both sites call it, so the rescale cannot drift again.

Contract, per field:

1. `"{field}_dollars"` present → `round(float(v) * 100)`, cent scale. It wins when both
   generations are present, because it is the live schema.
2. else legacy `"{field}"` **genuinely present** → used as-is, never rescaled.
3. else → `None`.

`None` — never `0` — for absent, empty, unparseable, NaN, and the degenerate 0/100 ends.

**Two things the briefing did not spell out, both load-bearing:**

- **`round()` is required.** `0.29 * 100 == 28.999999999999996` and `0.07 * 100 == 7.000000000000001`
  in IEEE 754 (verified in the venv). A naive `* 100` publishes those artefacts into
  `market_yes_ask` and `calculated_edge`. Pinned by a test.
- **A quoted `"0.0000"` is not the same as an absent field.** Kalshi quotes the degenerate ends
  rather than omitting them — live `KXHIGHNY-26SEP28-T71` carries `yes_bid_dollars: "0.0000"` and
  `no_ask_dollars: "1.0000"`. The most literal reading of "read the `_dollars` strings" maps that
  to `0.0`, and *that* still fabricates an edge at the consumer (`my_prob - 0`). The normaliser
  reports 0c and 100c as `None` as well, matching the existing modern sibling
  `quote_from_market_raw` (`tradehub/data/kalshi_live.py:25-26`) and the `if yes_ask == 0` guard
  every consumer in this repo already uses. **This is the one place I deliberately went beyond the
  literal spec; a wrong rescale here would produce plausible wrong numbers, so it is called out
  and tested.**

A **liquidity/price guard** was added in `background_scanner.py` before the Kelly call, so the
scanner does not rely on `process_markets` normalisation alone: `if yes_ask is None or yes_ask <= 0`
→ count, print, `continue`. No record, no `calculated_edge`, no bet. Skips are now visible in the
scanner log instead of being silent.

---

## 5. Findings that contradict or extend the briefed blast radius

**a) The Quant engine never placed a bet at all — and the briefing's "sizes a Kelly bet at price 0"
is imprecise.** `kelly_criterion` has its own `if price >= 1.0 or price <= 0: return 0` guard, so
the fabricated `0` made it return `0`. With `bet_size == 0` the `and bet_size > 0` conjunct was
false, so **no paper-trade row was ever appended**, despite `abs(edge) > 5.0` being true. The bug
did two opposite things: it published a fabricated `calculated_edge: 70.0` into the snapshot
record, *and* it silently muted the whole paper-trading engine. Confirmed: the mutated end-to-end
run above produced `kelly_bet: 0` and no opportunity.

**b) Three more sites carry the identical drift, two of them on the Tier 1 real-edge path.** Not in
the briefed blast radius, and I did **not** fix them:

| site | shape | effect |
|---|---|---|
| `tradehub/engines/weather_engine.py:214,220` | `yes_ask = market.get('yes_ask', 0)`; `if yes_ask == 0: continue` | every weather market skipped |
| `tradehub/engines/macro_engine.py:453,461` | same | every macro market skipped |
| `tradehub/core/kalshi_feed.py:281-306` (`clean_market_data`) | same, plus `'no_price': m.get('no_ask', 0)` and `'spread': abs(yes_ask - m.get('yes_bid', 0))` → a fabricated 0 spread | every market dropped |

I verified the schema absence is universal, not series-specific: **156 markets across
KXHIGHNY/KXHIGHCHI/KXHIGHMIA/KXCPI/KXINX/KXBTC, zero carrying the legacy keys, 100% carrying
`*_dollars`.** So all three sites currently drop everything, and the Weather and Macro
"real edge" engines have been returning **zero** opportunities. These fail *closed* — they skip
rather than fabricate — so nothing wrong is being published, which is why this is a different
(and lower) severity than site 1. I left them alone deliberately: fixing them would **activate two
real-edge engines** that emit trade proposals through the AI Validator, which is a product
decision, not a bug fix. Recommend a separate, deliberate PR.

The briefing's other claims checked out and were left alone: `weather_auto_sell.py` never reads
price; `scan.py`/`_mid` are untouched and were already `None`-safe; `tradehub/edges.py:43` is
correct.

**c) One dead downstream consumer, worth a note not a fix.** `research/tools/generate_market_snapshot.py`
reads `m.get('yes_ask', 0)` off `process_markets` output and would now raise `TypeError` on `None`
(`if cost <= 0`). It imports `from src.kalshi_feed import ...` and `src/` does not exist in the
repo, so it cannot run at all — already dead before this change. Left alone.

## Files changed

- `tradehub/markets.py` — `quote_cents()` / `_tradeable_cents()` (+48)
- `tradehub/core/kalshi_feed.py` — `process_markets` uses the normaliser
- `tradehub/core/kalshi_portfolio.py` — `get_portfolio_summary` uses it, no longer persists a 0 price
- `tradehub/scripts/background_scanner.py` — price guard before edge and Kelly, visible skip count
- `tests/test_kalshi_quote_cents.py` — 18 tests (new)

No frontend file touched: no `market_sentiment_tool/`, no `market_sentiment_tool/src/`, no
`Scoreboard.tsx`, no `App.tsx`, no `tests/test_scoreboard_api.py`, no `tradehub/api/main.py`.
