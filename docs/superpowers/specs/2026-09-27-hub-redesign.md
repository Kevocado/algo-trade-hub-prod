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

**The inversion (approved) — but on its own it does not open this gate, and I should have checked that
before asking for it.**

`check_candidate` takes its `calibration` argument from **the predictor's own feed payload**, and the
inversion was to admit on that payload rather than on the hub's settled ledger. But it is the *same
payload with the same n check*, so changing who gates does not change the arithmetic. Measured from the
live VPS feeds:

| | settled, winner | spread | total | largest single bucket |
| --- | --- | --- | --- | --- |
| NFL | **0** | 0 | 0 | 0 |
| CFB | 42 | 33 | 32 | **11** |

`calibration.n_buckets` is **10** (it comes from the predictor, not the hub) and the hub requires
`calibration_min_n: 20`. Clearing the gate in *every* bucket therefore needs **10 × 20 = 200** settled
contracts. There are **42** for CFB winner and **zero buckets reach 20**. NFL has no settled history at
all, so it cannot clear at any threshold until it has graded games.

**And the two thresholds contradict each other.** The reviewer's own bar is `MIN_SETTLED = 100`
(`sports/scorecard.py:9`) — at 100 settled it renders a verdict. The candidate filter implicitly demands
**200**. The product must be *twice as strict* about admitting an edge as its own reviewer is about
judging one, so it cannot surface a candidate until roughly twice as long after launch as the point at
which the reviewer could already have declared an engine good or bad.

That is the real defect, and it is arithmetic rather than design. The settings encode an intent of ~100
settled — that is the reviewer's number — while `10 buckets × min_n 20` encodes 200. Aligning them
(**5 buckets × min_n 20 = 100**, or 10 buckets × min_n 10 = 100) makes the gate internally coherent and
reachable in a season rather than two.

To be plain about what this does and does not buy: even at a coherent 100, CFB's 42 settled contracts
fall short, so **the gate does not open today under any threshold consistent with the reviewer's bar**.
What the numbers buy is an honest, reachable target instead of an unreachable one. Any claim that the
gate is "a few more settlements away" would be false.

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

### A second correction: the feed does not ship the fields this design assumed

I wrote that "the predictors' `model_version` now reaches the feed". **It does not.** Probing
`/api/kalshi-feed` on both predictors at 2026-09-27T02:36Z:

| Feed | games | `p_home` | `sigma` | `margin_mu` | `model_version` |
| --- | --- | --- | --- | --- | --- |
| NFL | 1 | 1 | **0** | **0** | **0** |
| CFB | 60 | 60 | **0** | **0** | **0** |

**61 of 61 games have `sigma`, `margin_mu` and `model_version` null.** `p_home` is populated on all of
them. So:

- **`feed:unknown` is not a hub bug.** `scan.py:83` stamps
  `f"feed:{mg.game.model_version or 'unknown'}"` — it faithfully reports an upstream null. The scan has
  nothing to stamp. Blanking the placeholder in the UI (PR #20) remains correct, but the *cause* is
  that no predictor publishes a version, and no amount of hub-side work fixes that.
- **The sigma ranking in §4 has no input.** `sigma` is null on every game, so `edge_pct / sigma` is
  undefined across the board. Ranking on raw edge is the honest fallback until this is fixed — which
  is what the hub does today.

### The cause is a stale deployment, not missing code

I expected this to be unimplemented work. It isn't. Tracing it back through the predictor:

| Layer | File | Behaviour |
| --- | --- | --- |
| feed read | `tracking/store.py:352-358` | maps `predicted_margin`→`margin_mu`, `sigma`→`sigma`, `model_version` faithfully |
| snapshot write | `tracking/store.py:149-150` | `game.get(...)`, so a missing key lands as NULL |
| tick | `api/routes.py:685` | splats `**pred` from `_predict_game_from_models` |
| predict | `api/routes.py:163-168` | sets all three from the model bundle: `models["sigma"]`, `models["total_sigma"]`, `models.get("model_version")` |
| bundle | `models/manifest.py:157-159` | `model_version(manifest)`, `manifest["sigma"]`, `manifest["total_sigma"]` |
| version fn | `models/manifest.py:140` | `f"{manifest['chosen_candidate']}@{manifest['trained_at']}"` — **always a non-empty string** |

So the current code has no path to a null `model_version`, and `origin/main` (`2296af3`) carries all of
it. The chain above is NFL's, cited because I traced it there first; **CFB is identical link for
link**, which matters because all 100 rows in the original audit were CFB:

| Layer | NFL (`2296af3`) | CFB (`695290e`) |
| --- | --- | --- |
| version fn | `models/manifest.py:140` | `models/manifest.py:141` |
| bundle | `models/manifest.py:157-159` | `models/manifest.py:159-161` |
| manifest written | `models/manifest.py:118-119` | `models/manifest.py:127-128` |
| snapshot write | `tracking/store.py:149-150` | `tracking/store.py:147-148` |
| feed read | `tracking/store.py:352-358` | `tracking/store.py:348` |

CFB's `model_version()` is the same `f"{manifest['chosen_candidate']}@{manifest['trained_at']}"`, so it
likewise cannot return null. Both feeds return null on all three fields, so the deployment gap is
symmetric and **both** images need redeploying — not just the one that first exposed it.

**The deployed NFL and CFB images predate step 7a.** The argument is tight rather than inferred from
one bad row:

- If the deployed build had the sigma code and a valid manifest, `sigma` would be a float. It is null.
- If it had the sigma code and a manifest *lacking* the key, `manifest["sigma"]` is bracket access, so
  `load_models()` would raise `KeyError` and the feed would not serve 61 games at all. It does serve
  them, with `p_home` populated.
- Therefore the deployed build does not contain the sigma/version code — and `p_home` predates it,
  which is why the older build still works.

**So this is operational, not development: redeploy the predictor images, and retrain so the manifest
carries `sigma`.** No new predictor code is needed. That is a much cheaper fix than approval item 4
reads like, and it is the highest-leverage thing in this whole spec — until it lands, the
`(engine, engine_version)` promotion gate can never accumulate a track record, because every row is
keyed `feed:unknown`.

### Which threshold actually admits anything

The arithmetic above says 200 is unreachable in a reasonable time and incoherent with the reviewer's
100. It does not say which alternative works, so I scaled CFB's real per-bucket settled distribution
to a future total and measured the share of edges each setting would admit (bucket mass is the proxy
for where edges land):

| setting | required | vs reviewer | admits at 100 settled (winner / spread / total) |
| --- | --- | --- | --- |
| **10 × 20 (current)** | 200 | **incoherent** | **0% / 46% / 66%** |
| 10 × 10 | 100 | coherent | 64% / 73% / 84% |
| 5 × 20 | 100 | coherent | 64% / 82% / 84% |
| **4 × 20** | **80** | **coherent** | **95% / 82% / 97%** |

**`4 buckets × min_n 20 = 80` is the setting I recommend.** It is the only one that both respects the
reviewer's bar and admits most of the edge mass at 100 settled. At the current 10 × 20 the winner gate
admits **nothing at all** at 100 settled, and only 64% even at 200.

Two caveats, because this is a projection and not a measurement:

- It scales the **observed** distribution — 42 (winner) / 33 (spread) / 32 (total) settled — and assumes
  that distribution's *shape* holds as the sample grows. If settled games concentrate differently
  later, these percentages move.
- Some buckets are **empty** (`spread` has two, `total` has three, at n = 0). Those are **inert, not
  blocking**: a bucket is only consulted when an edge's own probability falls inside it, and the model
  does not predict those price ranges, so no edge is ever rejected by one. The binding constraint is
  the thinnest *edge-bearing* bucket — winner's 0.3–0.4 at n = 3, which needs roughly 280 settled to
  reach 20. Still ~2.8× the reviewer's bar, which is the same conclusion from the other direction.

So the honest summary is not "lower the threshold and the gate opens". It is: **at 10 × 20 the gate is
both incoherent with the reviewer's own bar and, on the real distribution, admits nothing for winner
markets at 100 settled.** 4 × 20 is the smallest change that fixes the incoherence and actually opens
the gate within a season.

### Why they are stale: neither predictor has a deploy path on `main`

This is the part I had wrong, and it is worse than "the images need a push". On `origin/main`:

| | NFL | CFB |
| --- | --- | --- |
| Azure deploy | `deploy-azure-nfl.yml`, **`workflow_dispatch` only** | same, manual |
| VPS deploy | **absent from `main`** | **absent from `main`** |
| Auto-deploy PR | **#6 open, unmerged** (`ci/vps-auto-deploy`) | **#6 open, unmerged** |

The Azure workflow says so in its own trigger: *"Everything runs on the VPS now: this Azure deploy no
longer fires on push or PR. Run it by hand from the Actions tab only if Azure is ever needed."* So
Azure is frozen **by policy**. And the VPS deploy that would replace it lives in PR #6, unmerged — and
it is well-built, triggering on merge to `main` with a paths filter that keeps scheduled data refreshes
from redeploying the service, pinned by `tests/test_deploy_workflow.py`.

**So neither predictor has a push-triggered deploy path on `main`, and both deployments are running
pre-step-7a builds.** That is the same class of defect as the hub's five unbacked tables: a hole in the
pipeline that lets staleness persist with nothing failing.

The VPS is stale too, which the first probe missed. Counting non-null fields on both hosts:

| Host | NFL games | CFB games | `sigma` | `model_version` |
| --- | --- | --- | --- | --- |
| Azure (configured in `engines.yaml`) | 1 | 60 | 0 | 0 |
| VPS | 15 | 59 | 0 | 0 |

The game counts differ (NFL 1 vs 15), so these are different builds at different commits — Azure is the
staler of the two. **Pointing the hub at the VPS is necessary but not sufficient**; the VPS needs
redeploying too.

Three ordered steps, and the first is the one that stops this recurring:

1. **Merge predictor PR #6 on both repos** so a merge to `main` reaches the VPS. Without it, every
   future predictor fix silently stays in `main` — which is exactly what happened to step 7a.
2. **Redeploy both predictors and retrain**, so the manifest carries `sigma`.
3. **Point `engines.yaml` at the VPS** (`nfl.` / `cfb.40-160-91-131.sslip.io`) instead of the Azure
   hosts that are frozen by policy. This is the standing misconfiguration: the hub is wired to a
   deployment that by design never receives updates.

I parked #6 earlier in this session on the note that the auto-deploy was not wanted yet. That decision
is now implicated in a live data defect, so I am re-surfacing it rather than leaving it parked.

I could not read the deployed image's commit from outside: there is no version or health endpoint
(`/api/health`, `/health`, `/api/model-info`, `/api/manifest`, `/api/status` all 404). The conclusion
rests on the code plus observed behaviour, so the operator should confirm it by redeploying and
re-probing `/api/kalshi-feed` for a non-null `sigma`.

Two structural facts fall out of the same probe, and they explain the rest of the audit:

- **The NFL feed publishes 1 game.** NFL week 3 opens 2026-09-28 and only PHI @ CHI qualifies. The
  available-now NFL list can hold at most one row, and that row still fails `calibration_insufficient`
  until n≥20 have settled. NFL is empty by construction, not by filter accident.
- **CFB publishes 60 games, mostly starting 10-02/10-03** — 120–168h out, against a 72h hub window.
  This is the direct confirmation of the scan-bound diagnosis above: the feed publishes games the hub
  should never price, and the hub prices all of them.

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

**Rank by edge ÷ sigma (approved) — but blocked on the predictor publishing `sigma`.** This is the
design the ranking should converge on, because when a feed *does* ship `margin_mu` with `sigma`, two
+10pp edges stop being the same claim:

| | our | market | edge | sigma | edge ÷ sigma |
| --- | --- | --- | --- | --- | --- |
| confident | 0.55 | 0.45 | +10pp | 1.5pp | **6.7** |
| same edge, vague | 0.55 | 0.45 | +10pp | 15pp | **0.7** |

Ranking on raw edge puts the vague one first. Sigma is floored so a degenerate distribution cannot
divide by ~0, and the score is capped so one absurd ratio cannot own the top. The raw edge stays
visible: sigma adjusts rank, it never hides the number.

**Today `sigma` is null on 61/61 games** (§3), so this cannot ship before a predictor publishes it.
The sequence is: predictor publishes `sigma` and `model_version` → hub ranks on `edge/sigma` with the
floor and cap → raw edge stays alongside. Until step one lands, ranking is on raw edge and the page
says which of the two it is using. Silently substituting a constant sigma would manufacture the
precision this ranking exists to express.

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

### What the design tooling does *not* find

`impeccable detect` over the whole frontend (`market_sentiment_tool/src`) returns **three findings, all
cosmetic**: Inter at `index.css:1` and `:73` as an overused face, and `border-l-4` on the Daily PnL card
at `Home.tsx:113`.

Worth stating because it should change what the redesign spends money on. Every one of those is a
finish-level detail, and **none of them is why the product is hard to use.** What actually made it
hard to use was found by reading the live pages, and none of it is on that list:

- a spread artifact rendered as a `+59.3 pp` opportunity next to an unrelated mid (§3)
- a `LIVE BALANCE $0.00` that was a claim rather than a measurement
- four of five routes never leaving a loading string
- a data table with no `<thead>`, so its columns were unnamed to a screen reader
- "No active positions detected in Kalshi account", naming an account that does not exist

Those are truthfulness and information-architecture failures, not craft failures, and a pattern matcher
cannot see any of them — it matches strings, not claims. So the redesign budget belongs in §6's page
purposes and in the labelling work, **not** in swapping the typeface or thinning a border. Treating the
detector's three warnings as a to-do list would be the wrong lesson to draw from a clean scan.

## 7. What I need approved

1. **The inversion, plus a threshold correction it does not subsume** (§3). Approving the inversion
   alone does not open the gate: it reorders *who* gates on the same predictor payload with the same
   `n < 20` check. The blocker is arithmetic — `10 buckets × min_n 20 = 200` required, against 42 settled
   (CFB) and 0 (NFL), while the reviewer's own bar is `MIN_SETTLED = 100`. Two parts: keep the inversion
   (predictor's calibration first, hub's settled ledger second) **and** align the candidate gate with the
   reviewer — my recommendation was 5 buckets × min_n 20 = 100, or 10 buckets × min_n 10.

   **Refined by measuring the real distribution: `4 buckets × min_n 20 = 80`** (§3). It is the only
   setting both coherent with the reviewer's bar and admitting most edge mass at 100 settled — 95% /
   82% / 97% for winner / spread / total, against **0%** / 46% / 66% for today's 10 × 20, which admits
   nothing at all for winner markets at 100 settled. This one needs a predictor-side change too, since
   `n_buckets` is the predictor's. The gate stays
   shut until CFB passes ~100 settled either way, and I would rather the page say that than imply
   otherwise.
2. **The window decision, re-put because the original approval rested on a false premise** (§3). My
   recommendation is now the opposite of what I asked for before: **keep `max_hours_to_start: 72` and
   bound the scan by it**, rather than widening to ~168h. Pricing a 144h-out game buys nothing and
   fills the page with rows that can never pass.
3. **The per-engine hypotheses in §5** — or replacements, particularly for CPI where I suspect the
   answer is "display, don't trade".
4. **Un-park and merge predictor PR #6 (both repos), then redeploy and retrain** (§3). This is new
   since the last round of approvals and it gates the approved ranking. `sigma`, `margin_mu` and
   `model_version` are null on every game from both hosts, because **neither predictor has a
   push-triggered deploy path on `main`** — Azure is `workflow_dispatch`-only by policy, and the VPS
   deploy is unmerged in #6. **No new code**; `origin/main` already has it. Step 1 is the one that stops
   this recurring: without a deploy path, every future predictor fix stays in `main` unnoticed, which
   is precisely what happened to step 7a. I parked #6 earlier this session; that is now implicated and I
   am re-surfacing it.
5. **The shadow scoreboard as a first-class page** (§6). It is the least impressive page and the most
   important one.
Then: one plan per independent piece, each with bite-sized TDD tasks, point-in-time backtests before
and after, and exact commands.

## 8. Carried forward, unresolved

- `/api/sports-edges` still reads Azure predictor hosts in `config/engines.yaml` while the predictors
  are moving to the VPS. If those hosts go dark before the cutover, sports pricing stops silently.
- The `sig:` and lifespan of the two predictor VPS auto-deploy PRs (NFL#6, CFB#6) is parked.
- NBA, PL and F1 predictors have no Kalshi adapter, so "one ranked list across predictors" is
  NFL + CFB only until those are built.
