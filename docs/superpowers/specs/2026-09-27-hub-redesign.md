# Trade Hub product redesign — what the product is for, and what it admits

**Status:** design only. No implementation in this PR. Branch `spec/2026-09-27-hub-redesign`.
Follows the audit of the live site on 2026-09-27 and the approvals given on it.

---

## 1. The finding that shapes everything

Every engine loses to the market. Not narrowly:

| Engine | Brier (ours) | Brier (market) | Verdict |
| --- | --- | --- | --- |
| gas `KXAAAGASD` | 0.1148 | **0.0268** | ~4× worse |
| weather `KXHIGHCHI` | 0.1347 | 0.1124 | worse; 60–70% bucket miscalibrated by 20.6pp |
| weather `KXHIGHNY` | 0.1242 | 0.0971 | worse; 60–70% bucket off by 12.2pp |
| weather `KXHIGHMIA` | 0.1112 | 0.0993 | worse |
| CPI headline | 0.099 | 0.071 | worse |
| labor `KXPAYROLLS` | 0.1792 | 0.1659 | worse |

The gas row is the informative one. A market Brier of **0.0268** means Kalshi prices that morning's AAA
print almost exactly two hours before close. There is no signal left to extract at that decision
time — the model is not slightly worse at the same task, it is being asked the question too late.

So the product cannot honestly say *"bet this"*. What it can honestly say is: **here is what the
model thinks, here is how sure it is, here is the record, and here is exactly how far it is from
being good enough.** That is a real product. The redesign makes it legible instead of disguising it
behind a wall of rejected rows.

## 2. What each page must answer

| Page | One sentence | What it answers today |
| --- | --- | --- |
| `/` | *What is worth a look right now, and is the model any good?* | Nothing. No headline, no edges; `$0.00` from an empty table. |
| `/sports` | *Which game should I look at, and why that side?* | 134 edges, **0 candidates**, all SHADOW, all filtered, one per page of rejection reasons. |
| `/lab` | *Let me audit the maths myself.* | Stuck on `Refreshing Alpha...`. Reads the database from the browser. |
| `/shadow` | *Does any engine beat the market after fees?* | HTTP 500. The one page that answers the question that matters is the one that is down. |
| `/jobs` | *How did the payrolls nowcast do against the market and the first print?* | Empty, pending #19. |

## 3. The gate deadlock, and the inversion

`candidates.py` admits an edge only if its price bucket holds `n ≥ calibration_min_n` settled
contracts. The reviewer needs 100 settled. The track record needs settled predictions. **Zero have
settled** — the system is 8 days old and the nearest games are CFB week 5 on 2 October. So every edge
fails `calibration_insufficient` (100/100), nothing is a candidate, no reviews run, and nothing
settles. The page that would prove the product works is gated on the product already working.

**The inversion (approved).** Admit an edge when it is tradeable *and* the publishing predictor is
calibrated in that price bucket **by the predictor's own published record** — NFL and CFB now ship
`calibration` buckets and a pre-kickoff track record via `/api/kalshi-feed`. The hub's own settled
ledger becomes the *second* gate once it has data, not the first. Every row states which gate it
passed.

### A correction to the audit that preceded this spec

I reported that `sports_cfb:` had **no parameters** in `config/engines.yaml` and therefore inherited
NFL's window, and that this was why 86 of 100 rows said "starts too far out". **That was wrong.** I
misread a two-line `grep -A 2` as an empty block. Both engines carry all nine parameters:

```yaml
sports_nfl:  min_edge_pct 4.0, prefer_maker true, max_quote_spread 0.04, min_resting_size 100,
             min_volume 1000, min_hours_to_start 1, max_hours_to_start 72,
             calibration_max_dev 0.10, calibration_min_n 20
sports_cfb:  identical, except min_volume 500
```

So the window is genuinely 72h for CFB, and the "widen `max_hours_to_start` to ~168h" decision I
previously put to you rested on a false premise. **The evidence now points the other way**, and §4
is rewritten accordingly.

The real cause is in the scan, not the config. `tradehub/sports/scan.py:121` filters only
`start_utc <= now` — games already under way. There is **no upper bound**, so the scan prices every
upcoming game no matter how far out, writes it to `kalshi_edges`, and `check_candidate` then rejects
it for `starts_too_late`. CFB week 5 is 2–3 October, roughly 120–144h out, so **86 of 100 rows were
dead on arrival by construction**: the work was done, the rows were stored, and the page rendered
them as rejects. That is a waste of scan work and the direct cause of the wall of rejections.

The other supporting fix stands, and is real:

- `engine_version` is the placeholder `feed:unknown`, and the promotion gate is keyed on
  `(engine, engine_version)` — so settled contracts can never accumulate against a real version. The
  predictors' `model_version` now reaches the feed; the scan must stamp it rather than defaulting.

## 4. Sports: "available now", heavily filtered

**Available now (approved).** The ranked list contains only picks inside the tradeable window —
1 h to 72 h before kickoff, which is what `min_hours_to_start: 1` / `max_hours_to_start: 72` already
encode. Far-out games are not in it, under any label. It is refreshed by the scan and the page shows
`as_of`. **Today it is empty**, and the page says why and when the first window opens. An empty list
that explains itself beats a full one that lies.

The window stays at 1–72h. It is also applied on the **scan** side, not only in the candidate
filter: bound the game query by `start_utc` so a 144h-out game is never priced, stored or ranked.
That is the difference between a list that is empty on purpose and a list that is empty because 86
rows were stored first and then rejected.

Admission requires **all** of:

1. quote ≤ 4¢, resting size ≥ 100, volume ≥ 1000;
2. inside the 1–72 h window;
3. the publishing predictor calibrated in that price bucket, by its own record;
4. a minimum edge after fees.

Shadow-labelled, never hidden. Rejected rows summarised **by reason** behind a toggle — "86 too far
out, 73 wide quote" — never as 50 rows of detail.

**Rank by edge ÷ sigma (approved).** The feed ships `margin_mu` with `sigma`, so two +10pp edges are
not the same claim:

| | our | market | edge | sigma | edge ÷ sigma |
| --- | --- | --- | --- | --- | --- |
| confident | 0.55 | 0.45 | +10pp | 1.5pp | **6.7** |
| same edge, vague | 0.55 | 0.45 | +10pp | 15pp | **0.7** |

Ranking on raw edge puts the vague one first. Sigma is floored so a degenerate distribution cannot
divide by ~0, and the score is capped so one absurd ratio cannot own the top. The raw edge stays
visible: sigma adjusts rank, it never hides the number.

**Price from the distribution.** Show a fair price against the market price, not a bare "+23pp".

## 5. What each engine needs, and the test that would prove it

No promise any of these wins. Each is a hypothesis with a falsifiable test, and a negative result is
a real result that gets reported.

- **Gas — decide earlier, or use intraday AAA.** The diagnosis is in the numbers: at 2 h the market
  Brier is 0.0268, so the question is exhausted. Test: re-run the same point-in-time backtest with
  the decision at the previous evening's close, and separately with an intraday AAA feed. Whichever
  beats 0.0268 survives. If neither does, gas has no edge at any lead and the product should say so
  rather than keep scanning it.
- **Weather — sigma at the traded lead.** The 60–70% bucket is off by 12–21pp, which is a
  *calibration* failure, not a discrimination failure: the model ranks fine and states its confidence
  too tightly. Test: recalibrate sigma per bucket per lead time against the same point-in-time
  sample. The bar is the market's 0.0971–0.1124, not zero.
- **CPI — what signal could beat the market.** Cleveland Fed nowcasts are published; the question is
  whether the market has already priced them. Test: regress the market's own price on the nowcast
  publication timestamp and see whether anything remains after it. If nothing does, CPI is a
  *display* engine, not an edge engine.
- **Labor — same shape, plus the ladder.** 0.1792 vs 0.1659 is close, which suggests the signal is
  most of the way there and the loss is in the tail. Test: per-bucket calibration plus a look at
  whether the 2003/2020-style revisions dominate the error.

Every backtest is point-in-time: features known before decision time, ALFRED/FRED vintages, Kalshi
history tiers. No lookahead. The numbers go in the report whether they improve or not.

## 6. The pages, redesigned

- **`/`** — one line: *best available now*, or the reason there is none, and the model's record
  beside it. No `$0.00`, no portfolio framing (fixed in #20).
- **`/sports`** — the available-now list, ranked by edge ÷ sigma, each row with its why. The
  rejected wall behind a toggle, summarised by reason.
- **`/shadow`** — the honest scoreboard: each engine's Brier against the market's, side by side, with
  the gate state. This page answers *should I trust this*, which is the question the whole product
  turns on, and it is currently a 500.
- **`/lab`** — unchanged in purpose, routed through the API, and explicitly the debugging surface
  where the filtered rows are welcome.
- **`/jobs`** — as #19 delivers it.

Every page's empty state names the reason and the next step. An empty page that says "nothing passes
the filter yet, and here is exactly what would" is a product; a page that silently renders nothing is
not.

## 7. What I need approved

1. **The inversion** — predictor's calibration first, the hub's own settled ledger second (§3).
2. **The window decision, re-put because the original approval rested on a false premise** (§3). My
   recommendation is now the opposite of what I asked for before: **keep `max_hours_to_start: 72` and
   bound the scan by it**, rather than widening to ~168h. Pricing a 144h-out game buys nothing and
   fills the page with rows that can never pass.
3. **The per-engine hypotheses in §5** — or replacements, particularly for CPI where I suspect the
   answer is "display, don't trade".
4. **The shadow scoreboard as a first-class page** (§6). It is the least impressive page and the most
   important one.

Then: one plan per independent piece, each with bite-sized TDD tasks, point-in-time backtests before
and after, and exact commands.

## 8. Carried forward, unresolved

- `/api/sports-edges` still reads Azure predictor hosts in `config/engines.yaml` while the predictors
  are moving to the VPS. If those hosts go dark before the cutover, sports pricing stops silently.
- The `sig:` and lifespan of the two predictor VPS auto-deploy PRs (NFL#6, CFB#6) is parked.
- NBA, PL and F1 predictors have no Kalshi adapter, so "one ranked list across predictors" is
  NFL + CFB only until those are built.
