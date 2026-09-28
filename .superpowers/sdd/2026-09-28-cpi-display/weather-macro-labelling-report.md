---
title: "Weather and Macro are labelled as stopped, not quiet"
type: report
domain: engine-health
status: proposed
settlement_source: n/a
tags: [kalshi, engine-health, truthfulness, schema-drift, prediction-lab]
summary: >-
  The WEATHER and MACRO tabs used to render "No high-confidence edges detected", which is a
  finding, for engines that had not looked at anything. They now say the engine is not running and
  why. The engines are NOT repaired and NOT activated; whether to publish them again is the
  owner's decision.
---

# Weather and Macro: the engine that found nothing, and the engine that did not look

## What a reader sees now

Click **WEATHER** in the Prediction Lab and the empty board now reads, in a red dashed frame:

> **Weather is not running — this is not a finding about the market**
>
> Not running. This is the Tier-1 real-edge weather engine, and it prices every market against
> `yes_ask`. Kalshi's API no longer sends the legacy cent field `yes_ask`. It sends
> `yes_ask_dollars` as a 0-1 string ("0.6200") and omits the old key entirely, so a read of
> `yes_ask` with a `0` default returns 0 for a market that is quoting right now. The engine treats
> that 0 as an unpriceable market and skips it, so it looks at every market it fetched and finds
> nothing, publishes nothing, and raises nothing. It is stopped rather than repaired because
> repairing it starts this engine publishing to the edge ledger again, and whether to publish it
> is a decision that has not been made.

**MACRO** reads the same, naming `macro_engine.py` and the same mechanism. Below the tabs, in every
case, a panel reads:

> **2 of 5 boards are fed by an engine that is not running**
> An engine on this list did not run. An empty board for it is not a finding about the market, and
> it is never reported as a count of zero.
>
> **WEATHER · Weather · not running** — *Opportunities found:* **—** — No count, because nothing
> ran. The engine did not execute, so there is no opportunity count to report — not a count of
> zero.
> `WeatherEngine` · on the scan path · `tradehub/engines/weather_engine.py:214`
> `WeatherMaker` · not wired to any scanner, so not a cause of an empty board ·
> `tradehub/engines/weather_maker.py:258`
>
> **MACRO · Macro · not running** — *Opportunities found:* **—**
> `MacroEngine` · on the scan path · `tradehub/engines/macro_engine.py:453`

### How that differs from an engine that ran and found nothing

A **SPORTS** tab with no qualifying opportunity still says exactly what it always said:

> **No high-confidence edges detected in sports**
> This engine ran. It looked at the markets it covers and no opportunity qualified, which is a
> measurement of this scan rather than a gap in the evidence.

The two are separated along four axes, and the tests pin all four:

| | ran, found nothing | could not run |
|---|---|---|
| headline | "No high-confidence edges detected in `<tab>`" | "`<Label>` is not running — this is not a finding about the market" |
| body | "This engine ran… which is a measurement of this scan" | the cause: which field moved, which file, which line |
| notice panel | not rendered at all — a healthy product says nothing | rendered, naming module and line |
| opportunities found | a dash, worded "not counted here" | a dash, worded "no count, because nothing ran" |

The two branches also fail differently, which is the property that makes the label worth having. A
rule that only ever rendered the failure would be its own kind of lie, so `TestRanAndFoundNothingIs
StillQuiet` asserts the quiet sentence is still printed when nothing is stopped, and
`does not mention a stopped engine on a tab the ruling says ran` asserts SPORTS is unaffected by
WEATHER being broken.

### The third state, which is the one that used not to exist

If `/api/engine-health` cannot be read, the empty board says:

> Nothing on the weather board, and which engines are running has not been read
> The board is empty, and this could not be read, so which engine state that is has not been
> established. An empty tab here is not yet a finding either way: it may be an engine that ran and
> found nothing, or an engine that did not run at all. (The read failed: 503 from
> /api/engine-health)

Without it, a 500 on the ruling endpoint is a quiet market for the length of the outage — a label a
server error can switch off is not a label.

## How the states are distinguished

Not inferred from the data. A heuristic — "this tab is empty, so the engine is broken" — would
relabel a merely quiet engine the first time a market was thin, and relabel a broken engine quiet
whenever the breakage happened to coincide with a real lull.

It is a **written ruling in Python**, `tradehub/engine_health.py`, served by `GET
/api/engine-health`, following the idiom of the prior art at
`market_sentiment_tool/src/lib/displayOnlyEngines.ts`:

- **A named list, not an inference.** `STOPPED_SITES` is a ruling somebody made on purpose, with
  the module, the line and the cause attached. It is a ruling and not a repair, deliberately.
- **Conservation.** `partition_edge_types` puts every input in exactly one of two buckets and the
  test pins `ran + could_not_run == len(input)`. A state that quietly drops an engine is how "no
  edge today" becomes true of a board nobody looked at.
- **A reason, never a bare flag.** "could_not_run" on a screen is a word nobody outside this repo
  knows, and the reason is checkable: the reader can open the file and the line.
- **`wired_to_a_scanner` is load-bearing.** `WeatherMaker` carries the same drift and is on the
  ruling so a maintainer sees all four sites at once — but no scanner calls it, so it cannot be the
  reason a live board is empty, and the notice says so on the same line it names it. A ruling that
  let an unwired helper explain an empty board would be blaming a dead branch for a live tab.

**No calculated value in a React component.** The state, the counts and the unfiltered board's own
state are all resolved in Python and arrive in the response. `lib/engineHealth.ts` holds wording and
three lookups, on the same terms as `lib/scoreboard.ts` and `lib/models.ts`: how a resolved fact is
worded, and the fail-safe presentation of a figure nobody measured. `edgeTypesText` reads the
server's counts rather than subtracting a set in a component.

**No count, where a count would be a lie.** `opportunities_found` is present and `null` on every
entry, and the test `test_no_entry_anywhere_in_the_response_carries_a_numeric_zero` walks the whole
response asserting no numeric zero appears anywhere. It is a dash on screen. This is the requirement
that mattered most in practice: `0` is the single most damaging value this product could print about
a broken engine, because it reads as a search that ran and found nothing.

## The tension this surfaced — the actual finding

The scoreboard's Brier comparison is **not** affected, and I did not touch it. `market_prob` comes
from `_mid()` at `tradehub/scripts/scan.py:105-108`, which returns `None` and never `0`, and the
backtest path already reads a source using the modern names. Weather's measured 0.14509 against the
market's 0.09991 is real and correct.

**That is the finding.** The product simultaneously reports:

- on **Models** (`/api/scoreboard`): Weather is a *measured* engine, 672 settled, 1.45x behind the
  market — a real, evidence-backed verdict; and
- on **Prediction Lab**: the Weather *real-edge* path emits nothing at all, and did not emit
  anything for the entire period the backtest was measuring.

A reader has no way to reconcile those, and neither did the product, because they are two different
engines that share a name and an edge type:

| | measured `weather` | stopped `WeatherEngine` |
|---|---|---|
| code | `tradehub/engines/weather.py` + `tradehub/scripts/scan.py` | `tradehub/engines/weather_engine.py` |
| driver | the hourly scan | `tradehub/scripts/background_scanner.py` |
| writes | `engine="weather"`, `edge_type="WEATHER"` | `engine: 'Weather'`, lower-cased by the writer to `engine="weather"` |
| status | runs, publishes, settles, scores | **skips every market, publishes nothing** |

They collide on the `kalshi_edges.engine` key. That collision is why the ruling names the **class
and module**, never the `engine` column: joining on `engine` would put "stopped" beside a real
Brier on the Models page and make a false claim about an engine that demonstrably runs.
`test_weather_the_measured_engine_is_not_the_stopped_site` pins the collision at both ends so nobody
later "fixes" the ruling by joining on the column that looks tidier.

The honest reading is uncomfortable and worth stating plainly: **the engine we have evidence about
is not the engine that was looking for live opportunities.** The backtest measures a model that
publishes; the Tier-1 scanner that shares its name and its tab publishes nothing. A reader shown
"1.45x behind" and an empty tab is being shown two true facts about two different things, with
nothing on screen to tell them apart. That is the same defect as the original one, one layer up and
in a different direction.

## What I did not do

- **Did not repair the drift.** Fixing the two live sites is a one-line change each
  (`quote_cents` already exists in `tradehub/markets.py` and is the shared normaliser;
  `kalshi_feed.process_markets` already uses it), but it makes these engines publish **295 rows per
  scan** (Weather 30, Macro 265) into `kalshi_edges`. Whether to publish them is the owner's call.
- **Did not deactivate or gate them.** Adding a display-only ruling on top would be a second ruling
  about the same engines and would make the two states harder to tell apart, not easier.
- **Did not touch the scoreboard**, the Brier comparison, or any threshold.
- **Did not remove them from the catalogue.** They are still real engines with a real claim.

## One test I had to change, and why

`tests/test_cpi_display.py::test_the_endpoint_is_registered_after_every_other_api_route` asserted
that `/api/cpi-display` was the *last* `/api/` route. It enforced the SPA-shadowing rule by naming
one route, so adding an honest endpoint to the same file failed it, and the only available fixes
were to weaken the test or bury the new route below the SPA mount. It now asserts the property
itself — every `/api/` route is above the catch-all, driven from a temp dist so the mount happens
whether or not this machine has built the SPA. That is strictly stronger: the old version would have
passed with a second route registered *after* the mount, as long as CPI happened to be last.

`PredictionLab.cpiDisplay.test.tsx` needed the ruling stubbed, because a page that stubs only the
board has a board read that succeeded and a ruling that has not arrived — and the honest rendering of
that is "not established", not the quiet sentence. Its failed-read tests are unaffected.

## Verification

- `pytest -q` — **1240 passed, 0 failed** (baseline was 1208; +32 new). Also **1240 passed** with
  `time.monotonic` forced to `1e7`.
- `ruff check --select F401,F811,F821 tradehub tests` — clean.
- `npm run typecheck`, `npx vitest run` (**380 passed**, baseline 325), `npm run build` — all pass.

### Mutation

Two mutations, both run and both reverted.

**Python** — `edge_type_state` hardcoded to `STATE_RAN` and `opportunities_found` to `0`, i.e. the
stopped engine reporting as a normal zero:

```
11 failed, 21 passed
```

including `test_weather_is_reported_as_could_not_run`,
`test_a_stopped_edge_type_publishes_no_opportunity_count`,
`test_no_entry_anywhere_in_the_response_carries_a_numeric_zero` and
`test_partition_keeps_every_input_exactly_once`.

**TypeScript** — the same defect reintroduced in the client, forcing a `could_not_run` entry down
the quiet branch:

```
6 failed, 36 passed
```

including `says the engine is not running rather than that nothing was found` and the page-level
`does not print the quiet sentence for a stopped engine's tab`.

Both directions matter. The Python mutation proves the ruling is what decides; the TypeScript one
proves the client cannot be talked out of it.

## A caveat on the tab-switch tests

`selectTab` uses `fireEvent.mouseDown`, not `click`. The tab strip is a Radix `TabsTrigger`, which
selects on pointer down; a `fireEvent.click` leaves the board on "all" and the assertion silently
reads the unfiltered view. That produced three *green tests measuring nothing* while I was writing
this — the same class of failure the page exists to prevent, arrived at through the test harness
rather than through the product. Worth knowing before anyone "simplifies" that helper.

## Is labelling the wrong answer?

Labelling is what I built, so here is the case against it, as strongly as I can put it.

**The strongest argument for fixing the drift instead.** The label is a way of describing a fault
that is one line long and already has a tested answer sitting in the repo. `quote_cents` in
`tradehub/markets.py` exists precisely for this, `kalshi_feed.process_markets` already calls it, and
PR #33 fixed two other readers with it. Leaving two readers unfixed means the product keeps two
engines that cost an NWS fetch and a FRED pull per scan, return nothing, and must now be described in
prose on every page that shows them. The label is a permanent, hand-maintained list with four
entries that will drift — when someone repairs `macro_engine.py`, nothing fails; a human has to
remember to delete a line from a Python file, and the only thing that complains is a test pinning
the offending source line, which reads as a test about line numbers. We have now added: a module, an
endpoint, a hook, a component, a lib, 32 Python tests, 55 frontend tests, and three branches to an
existing component — all to describe a condition that should not exist. The test
`test_a_stopped_engine_is_named_by_a_greppable_module_and_line` is a canary for staleness, but a
canary that only fires when someone thinks to look at the numbers.

**The case for removing them from the catalogue.** `weather_engine.py` and `macro_engine.py` predate
the current architecture: they are the Tier-1 path of a `background_scanner.py` that
`weather_auto_sell.py` and `market_alerts.py` also hang off, and their opportunity dictionaries use
a different shape from everything the modern scan writes. They are not measured, not gated, and not
on the promotion path. An engine with no measurement, no gate and no output is not an engine in this
product's sense — and the catalogue is meant to be authoritative about which engines *exist*.
Labelling them keeps them in the reader's view as things that might come back, which is a form of
hope the product has not earned. Deleting them removes the ambiguity rather than describing it.

**What actually argues for labelling anyway**, which is why I think it is right for now but not
forever:

1. **The activation decision is a product decision, and it has not been made.** Fixing the drift
   makes these engines publish 295 rows per scan of unvalidated, un-gated, un-backtested
   opportunities to the one table a reader trusts. Labelling is the reversible half of that; the
   repair is not. The owner is away. Labelling changes no behaviour and removes a false statement
   from the screen; it forecloses nothing.
2. **The two failures are not the same cost.** A missing label is a wrong sentence on a page. A
   premature repair is 295 rows per scan of output from a model that has never been measured, which
   the scoreboard would then have to explain. One is a bug report; the other is a data-quality
   incident.
3. **The label is a ledger for the decision.** The report now names every drifted site, whether it
   is on a scan path, and what repairing it would cost in rows. That is the artefact the activation
   decision needs, and it does not exist anywhere else. Whoever decides can read the ruling and act.

So: labelling is the right call *given that the decision is unmade*, and it is the wrong call the
moment it is made. If the owner rules "fix and activate", this PR becomes a small deletion —
`STOPPED_SITES` empties, the notice renders nothing, and the tests that pin a clean board
(`test_a_board_with_nothing_stopped_says_so_rather_than_carrying_a_reason`) start doing the work
instead. If the ruling is "these engines are retired", the deletion is bigger and I would argue for
removing them from `background_scanner.py` and the catalogue rather than labelling them forever.

**The case I think is strongest and nobody should skip:** there is a third option, and it is the one
this PR has not done. Repair the drift into a *quarantine* — the engines compute, the results are
counted and displayed, and nothing is written to `kalshi_edges` until the owner rules. That gives
the owner the measurement ("this engine would have published 30 weather opportunities today, here
they are, with here are their edges") without publishing a single one, and it converts the decision
from a judgement about unseen code into a judgement about real output. It needs a real second sink,
so it is a bigger change than this one — but it is strictly better than either labelling or repairing
if the owner's real question is "should these be on?", and I would rather name it than let labelling
be mistaken for having answered it.
