---
title: "Weather and Macro quarantined: what they measure, and how little of it is an opportunity"
type: report
domain: engine-health
status: proposed
settlement_source: n/a
tags: [kalshi, engine-health, quarantine, truthfulness, schema-drift, prediction-lab, units]
summary: >-
  The Weather and Macro real-edge engines are repaired and running, and their output is measured and
  shown. 295 rows a scan, of which 26 are independent opportunities: 82 are units artefacts and 187
  restate a forecast another row already made. Nothing reaches kalshi_edges. The headline is 26,
  not 295, and the surface is built so it cannot say otherwise.
---

# Weather and Macro: the engines now run, and 26 of 295 rows are worth anything

## The real numbers

Measured on 2026-09-28 against a live capture from Kalshi's public API: **441 economics markets**
and **30 daily-high temperature markets**, with the NWS and FRED layers stubbed to fixed values so
the run is reproducible. The market lists are real and unmodified; the forecast inputs are not, and
that is the only concession to determinism.

| | before | after |
|---|---|---|
| Weather rows | **0** | **30** |
| Macro rows | **0** | **265** |
| Total rows per scan | **0** | **295** |
| Economics markets with no tradeable YES ask | 110, all read as 0c | 110, **correctly skipped** |
| Rows reaching `kalshi_edges` | 0 | **0** |

The 110 skipped markets are not a defect and not a loss. They quote 0c, 100c, or nothing at all,
and a market you cannot price has no edge. The old code skipped them for the wrong reason — every
market read as 0c — and the fix is what makes the distinction real: `quote_cents` returns `None`
for an unpriceable quote, and the engines test `is None` rather than a falsy check. Getting that
second half wrong is not hypothetical: with a falsy check, normalising alone hands `None` to
`model_probability - yes_ask` and raises `TypeError` on each of the 110, which `scan_real_edge`
swallows back to a zero. The symptom is the pre-repair symptom wearing a new cause.

### How many of the 295 are genuine opportunities: 26

This is the answer to the question the labelling was not answering, and it is not 295.

| | count | what it is |
|---|---|---|
| Rows the scan produced | **295** | what the engines emitted |
| Not a units artefact | **213** | the price is on the side the row recommends |
| **Independent opportunities** | **26** | **separate statements the engines actually made** |
| Units artefacts | **82** | the headline edge is a difference between the wrong two quantities |
| Restatements of another row's forecast | **187** | the same model probability on a different market |
| `BUY NO` rows carrying a YES-side price | **141** | wider than the artefacts; see below |

Per engine: Weather is 30 rows, 0 artefacts, **18 independent**; Macro is 265 rows, 82 artefacts,
**8 independent**. Macro is nearly all repetition, and the reason is structural rather than bad luck
— see the GDP finding below.

**The headline is 26, and the ratio is the finding.** 26 out of 295 is under one in ten. A surface
that reported "295 opportunities" would be a number on screen that looks authoritative and is not —
the same failure as PR #38's "No high-confidence edges detected in weather", reached from the
opposite direction. That is why the headline is the independent count, why the row total is labelled
`rows` and never `opportunities`, and why the component has no fallback: `headlineCount` reads
`independent_opportunities` and returns a dash if the measurement is missing, so there is no key in
the payload it could be talked into reading instead.

### The 99¢ rows: 66 at 99¢, of which 25 carry the full 84-point edge

Both engines compute `edge = model_probability - yes_ask` and then pick their side from the sign. So
the price on the row is always the YES ask, whatever the recommendation. On a `BUY NO` at a 99¢ YES
ask the trade described costs the far side of that book — about a cent — and the "edge" is a gap
between the model's YES probability and a YES quote. The row reads "BUY NO, 99¢, 84 points" and no
such trade exists: you would be buying NO at 99¢ while YES is also 99¢.

The spread is itself diagnostic. The reported edge takes exactly four values — 14, 39, 59, 84 —
because it is `99 − model_probability` off a four-way lookup table `{85, 60, 35, 10}`. It has nothing
to do with the market being quoted. 25 rows report the full 84 points; the brief's figure of 25 is
the 84-point subset, and the honest reading is 66 degenerate quotes of which 25 carry the headline.

`buy_no_rows` (141) is reported separately from `units_artefacts` (82) rather than folded in. At a
sane price the wrong-side price is arithmetically harmless — in a frictionless book NO costs
`100 − YES`, so the same difference comes out the other way. At 99¢ it is a headline nobody could act
on. Reporting only the narrower number would be choosing the flattering denominator.

### The GDP rows: 138 rows, 4 forecasts, 11 year-events

Neither engine has a per-market model. Each fetches **one scalar per asset** and quantises it into a
handful of constants, so a GDP reading of 1.9% produces `model_probability` 10 for every strike
above 2.8, 30 for every strike in the 2.0–2.4 band, and so on — across every year-event Kalshi
lists for the series. The largest single group is 84 rows of one opinion.

This is the same units error as the 99¢ rows, one level up: a count of ROWS where a count of
STATEMENTS was meant. It is also the single clearest argument against publishing, because the GDP
rows alone outnumber the whole independent count five times over.

## What the owner sees

A marked panel on the Prediction Lab, below the tabs and directly under the engine-state notice,
because a reader who sees "quarantined" and no numbers will assume the product has nothing to show
and that the label is an excuse. It reads:

> **QUARANTINED — what Weather and Macro would have published**
> QUARANTINED. These engines run and compute their real output, and none of it is published: no row
> reaches kalshi_edges, so no trade can be proposed from anything on this surface. The counts below
> are a measurement, not a live board.
>
> **Independent opportunities: 26**  ·  **Rows measured: 295**
> Independent opportunities, not rows. The scan produced 295 rows: 187 of the 213 non-artefact rows
> restate a forecast another row already made, and 82 carry an edge measured in the wrong units. The
> remaining 26 are separate statements.
>
> 26 independent opportunities · 295 rows · 187 restated · 82 artefacts
> Weather: 18 independent of 30 rows
> Macro: 8 independent of 265 rows
>
> **Rows written to kalshi_edges: 0 · sink: kalshi_quarantine_edges**

Then, for the first page of rows, each in its own card with a QUARANTINED badge, its classification
(artefact / restatement / independent), and its `forecast_key` so the restatement count can be
checked from the page.

The marker is on the heading, on every row card, in the note, and in the database row itself —
`quarantined BOOLEAN`, `marker TEXT`, `note TEXT`, plus a `CHECK (quarantined)` constraint so a
partial insert cannot produce a row that reads as a live edge while sitting in the quarantine ledger.
A quarantined number that travels alone is indistinguishable from a published one, which is the whole
failure this exists to prevent, so a reader who screenshots any single figure still has the word
QUARANTINED in the image.

**Nothing in this UI can compute a figure.** The 95¢ artefact threshold is a written ruling in
`tradehub/quarantine.py`; the independent/restatement split is resolved in Python over the whole scan
(whether 138 rows are one forecast is a fact about the *set*, and a client counting a subset of it is
a number nobody can audit); and every count is the server's. `lib/quarantine.ts` holds wording and
three lookups, on the same terms as `lib/scoreboard.ts`.

## Quarantined reads as quarantined, not as stopped and not as quiet

`engine_health.py` now resolves three states instead of two, and the middle one is the point:

- `ran` — ran, looked, nothing qualified. A measurement; the empty board is the finding.
- `quarantined` — **ran, measured, and the measurement was withheld by ruling.**
- `could_not_run` — did not run. Nothing measured.

The middle state is easy to get wrong in both directions and neither is survivable. Calling it
`could_not_run` is a lie — these engines measured 295 rows. Calling it `ran` beside an empty board
tells the reader the market was quiet, which is PR #38's defect restated. So the WEATHER and MACRO
tabs now read:

> **Weather is quarantined — this board is empty by decision, not by a quiet market**

and the notice below counts the two states **separately** rather than summing them. "2 of 5 boards
are not working" is true and useless when one of the two is working perfectly well and merely
withheld; a reader who has to pick a count out of a sentence carrying two of them will read the wrong
one, and the wrong one here is the healthy-looking summary the panel exists to stop showing.

PR #38's labelling is not weakened. The reason text still names the moved field, the file, the line
and the mechanism, and the two repaired sites stay on the ruling with `disposition =
repaired_quarantined` and the **repaired** read pinned in their place. Removing them because the bug
is fixed would delete the record of what the bug was, and a ruling that only remembers the present
cannot explain why a board is empty. The staleness canary survived the repair: PR #38's test pinned
`market.get('yes_ask', 0)` and fired the moment the fix landed, which is what told this change the
ruling had to be rewritten rather than deleted; it now pins the repaired read instead, and a revert
of the fix is caught by the same mechanism that caught this one.

## The proof that nothing is written

Three independent things, because one would be a promise:

1. **Structural separation.** `run_scan` builds its publish list from the paper tier alone
   (`all_opps = list(paper_ops)`). The quarantine list's only destination is `upsert_quarantined`.
2. **The sink refuses.** `upsert_opportunities` drops any row carrying `quarantined` before building
   a payload, prints the refusal, and returns the count dropped. The flag is written in exactly one
   place, so it can only be set by the path that is meant to be quarantined.
3. **A different table.** `upsert_quarantined` opens `kalshi_quarantine_edges` and nothing else. Not
   `kalshi_edges` with a column: a row in the trade-proposal sink is a row something downstream can
   act on, and a `quarantined` boolean is one refactor from not being read.

The flag, not the edge type, is the identity test — and that is load-bearing rather than incidental.
`tradehub/scripts/scan.py` publishes measured rows under both `WEATHER` and `MACRO` every hour, so a
sink that refused those edge types would refuse the product's working engines to enforce a ruling
about two other engines that share their boards. The edge type is the ruling's *scope*; the flag is
the row's *identity*. `test_the_edge_type_alone_never_identifies_a_quarantined_row` pins both halves.

Two things that are deliberately NOT wired up, and would each be a way to leak a number that cannot be
un-seen: **Discord alerts are handed an empty list.** A push notification carries a headline and
nothing else, so "84-point edge" with no QUARANTINED word on it would land in someone's phone where
the only context is the message. And `/api/engine-health` still reports `opportunities_found: null`
for a quarantined engine even though it *has* a count of 295 — the figure lives on `/api/quarantine`
with the split, because a bare total would throw away the only part of it anybody could act on.

**A missing figure is never a number.** An empty `kalshi_quarantine_edges` returns `measured: false`
and `totals: null` with the reason — either no scan has written to it or the migration is not applied
— and the panel shows a dash. Not 0. `0` there would be a measurement of a search that never
happened, which is the identical defect in an identical shape.

## Scope: a table, an API response, and a page

A migration, `upsert_quarantined`, `/api/quarantine`, `useQuarantine`, `lib/quarantine.ts`, and
`QuarantineNotice`. No pipeline, no queue, no reconciliation, no shadow-trading ledger. Nothing reads
the table to place an order, nothing settles it, it feeds no scoreboard. That it is small is
deliberate: anything larger would start accruing state that somebody later mistakes for a track
record. It is a measurement surface and it stays one.

## Mutations

Four run, four reverted. The two that matter are the first and the second.

**(a) Make the quarantine write one row.** Done in two halves, because the two halves are independent
and the result is the finding.

*A1 — break only the structural separation* (`all_opps = list(paper_ops) + list(quarantined_ops)`),
leaving the sink's refusal intact:

```
48 passed, 0 failed
```

**Nothing fails, and that is the point.** The quarantined rows are handed to the trade sink and the
sink drops all 77 of them. Defence in depth working as designed: a refactor that concatenates the
two lists — the single most likely way to break this — writes nothing.

*A2 — break both*, as a real "just turn the quarantine off" change would:

```
2 failed, 46 passed
```

including `test_the_quarantine_writes_nothing_to_the_trade_sink`:

```
AssertionError: the quarantined path wrote to the trade-proposal sink. Everything in this PR
exists so this cannot happen; the writes were to ['kalshi_edges', 'kalshi_quarantine_edges']
```

and `test_upsert_opportunities_refuses_a_quarantined_row_even_when_handed_one` (which also carries a
legitimate crypto row, so a writer that dropped everything would fail it too — one test for both
halves is the only version that says anything).

**(b) Hide the quarantine marker** — `QUARANTINE_MARK` emptied to `""`, the way a "tidy up the shared
constant" edit would:

```
5 failed, 421 passed
```

across `lib/quarantine.test.ts` and `QuarantineNotice.test.tsx`.

This one changed how the tests are written. The first attempt failed only **one** test, and for the
wrong reason: every other assertion compared against the imported constant, so `getByText("")` matched
every element and the row-marking test passed by accident. Three assertions now pin the literal
`"QUARANTINED"` with no reference to the constant, and `quarantine.test.ts` says why in a comment. A
green test that measured nothing is the exact class of bug this page is about, arrived at through the
test harness — the same trap as the `selectTab`/`fireEvent.click` one from PR #38.

**(c) Fold a quarantined engine into `ran`** — the most likely way this regresses, somebody tidying
`edge_type_state` back to two states:

```
14 failed, 70 passed
```

including `test_weather_is_reported_as_quarantined_and_not_as_could_not_run`,
`test_a_quarantined_edge_type_publishes_no_opportunity_count`,
`test_no_entry_anywhere_in_the_response_carries_a_numeric_zero` and the three-way conservation tests.

## Verification

- `pytest -q` — **1292 passed, 0 failed** (baseline 1240; +52). Also **1292 passed** with
  `time.monotonic` forced to `1e7`. The interpreter was confirmed to exist and run before either
  result was believed.
- `ruff check --select F401,F811,F821 tradehub tests` — clean.
- `npm run typecheck`, `npx vitest run` (**426 passed**, baseline 380), `npm run build` — all pass.

### One existing test I had to rewrite, and why

`test_engine_health.py` had twelve tests asserting the wired engines read as `could_not_run`. Both
engines are repaired, so those assertions were asserting something false about engines that
demonstrably run. They were rewritten rather than deleted, and the `could_not_run` branch is still
tested — by clearing the dispositions and checking the same sites land there, so it stays reachable
code rather than dead code a future drifting engine would be the first to exercise. The two
`OFFENDING_READS` pins for the *unrepaired* sites (`weather_maker.py:258`, `kalshi_feed.py:284`) are
kept and still asserted: those defects are real and this PR does not fix them.

## What I did not do

- **Did not activate.** Turning the quarantine off is deleting two names from
  `QUARANTINED_EDGE_TYPES`, and it is the owner's call with the counts in front of them.
- **Did not fix `weather_maker.py:258` or `clean_market_data`.** They carry the same drift. Neither is
  on a scan path, so neither is why a board is empty, and both stay on the ruling marked
  `unrepaired`.
- **Did not add a normaliser.** The rescale is `quote_cents` in `tradehub/markets.py`, and an answer to
  "what is a 29c quote" in two modules is a second answer waiting to disagree with the first.
- **Did not touch the scoreboard**, the Brier comparison, or any threshold.
- **Did not build a pipeline.** See the scope note above.

## Concerns

**The 26 independent opportunities are not 26 good ones.** They are 26 distinct model statements, and
the models behind them have no measurement, no gate and no backtest. Weather's 18 come from a
five-value lookup on an NWS point forecast; Macro's 8 from four scalars fetched once per scan. The
quarantine makes the *count* honest and says nothing about whether any of the 26 is worth taking. The
right reading of this PR is "here is what the engines think, and here is how little thinking that is",
not "here are 26 opportunities".

**The fixtures are a snapshot, so the counts will drift.** The pinned 30 / 265 / 26 are a record of
2026-09-28, not a live assertion — a different market day produces different numbers and the test
does not fail on it, by design. A reader in a month should re-measure rather than trust them. The
`tests/fixtures/quarantine/measured_rows.json` `_note` says so.

**The `forecast_key` definition is a judgement.** `(engine, asset, model_probability)` treats two rows
sharing those three as one statement. That is right for these engines, which have no per-market model,
and it would be wrong for an engine that does. If one is ever added, the key has to change with it,
and nothing in the code would notice.

**The quarantine adds a table that will accumulate.** Nothing prunes it, deliberately, and nothing
reads it for anything but a count. The day something reads it for a second purpose — a chart, a
scoreboard, a reconciliation — it stops being a measurement surface and starts accruing state that
will be read as a track record. Worth writing down now, while the reason for it is fresh.

**Most of all: the honest answer is that these engines produce very little worth quarantining.** 26 out
of 295, mostly two engines agreeing with a four-value lookup table. The quarantine is the right size of
answer to that — a marked measurement surface, nothing published — and it is worth saying plainly that
the measurement did not argue for switching them on.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
