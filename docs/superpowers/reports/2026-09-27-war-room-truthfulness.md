# War Room tells the truth — evidence report

Branch `fix/war-room-renders-and-numbers`, from `origin/main` at `ce148ef`.
One PR. Two commits: the API/schema layer, then the frontend.

**This is not a UI redesign.** It fixes five API endpoints that could not work, one number the page
presented wrongly, and a sidebar that claimed a live balance. The redesign (sigma-ranked "available
now" list, the model work per engine) is the next plan and is not in here.

## How it was found

An audit of the live site in a browser, not from the source. All five routes were opened and the DOM
read. The finding that reframed everything: **only `/sports` renders anything.** The other four sit
on a loading string forever, reproducibly, with zero network failures on repeat loads.

| Page | Rendered |
| --- | --- |
| `/` | nav + `LIVE BALANCE $0.00`, nothing else |
| `/lab` | `Refreshing Alpha...` |
| `/jobs` | `Loading scorecard` |
| `/shadow` | `LOADING SHADOW BACKTESTER` |
| `/sports` | one section: "Edges that failed the candidate filter (50)" |

## Task 1: five tables the code reads and writes that no migration creates

### RED

The guard found them, and found **five**, not the one the audit suggested:

```text
AssertionError: these names are passed to supabase.table(...) but no migration creates them:
['live_opportunities', 'paper_signals', 'paper_trades', 'scanner_runs', 'trade_history']
```

Live symptoms: `/api/positions` and `/api/pnl_summary` → HTTP 500 (PGRST205);
`/api/shadow-performance` → HTTP 500 with a raw PostgREST dump. And `/api/opportunities` returning
`[]` is the same defect seen from the other side: `tradehub/core/supabase_client.py` has been
**writing** to four of these since the hub was deployed, into tables that do not exist.

### GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q tests/test_war_room_api_truthfulness.py
8 passed
```

Two different fixes, because there were two different bugs:

- **`signal_events` is not a code bug.** `20260415090000_signal_events_unification.sql` renames
  `crypto_signal_events` into place and was never applied to the live project. The code is right, so
  the response now names the migration instead of forwarding PGRST205:

  ```text
  table 'signal_events' is not in the database. Apply
  market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql and
  redeploy. The database still has crypto_signal_events under its old name.
  ```

- **`paper_trades` never existed.** Its only definition is `research/legacy/supabase_setup.sql`, and
  **nothing in the codebase writes it** — correct, because this is a suggest-only product. Migration
  `20260416000011_war_room_tables.sql` creates it (with the other four) and it starts empty, which is
  the honest state.

The durable part is the guard, `test_no_code_references_a_table_no_migration_creates`: it walks every
`supabase.table(...)` name in `tradehub/` and fails the build if no migration creates it. That is the
test that would have caught all five before deploy.

A missing ledger now **503s with the migration to apply** rather than reading as an empty book — and
`PnLSummary` carries `suggest_only` so the UI can say "no orders are placed" instead of rendering a
confident `$0.00`.

## Task 2: the sports row presented a spread artifact as an opportunity

### The defect, exactly

```text
UConn wins     YES @ 18¢   78% vs 33%   +59.3 pp
Syracuse wins  NO  @ 20¢   22% vs 65%   +57.3 pp
```

Both sides of one game claiming ~58pp is arithmetically impossible, which is what made it look like
a calculation bug. It is not. `edge_pct` is the after-fee edge against the **entry price**
(`net_edge_pct(78.25, 18) = 59.25` ✓) and `market_prob` is the quote **mid**. Worked backwards, each
quote is ~30¢ wide (bid 0.18 / ask 0.48 → mid 0.33 ✓), which is exactly why **all 100 live rows**
carry `wide_quote` as a reject reason. The "edge" was the spread.

So the filter was right and the page was the defect.

### RED → GREEN

```text
# RED
E   AssertionError: assert 0.5925 is None      # a rejected row was leading with the number
# GREEN
8 passed  (tests/test_sports_edge_row_honesty.py)
```

`sports.scan.edge_row` now owns the row shape and three rules:

1. **A rejected row carries no headline edge** — regardless of what `candidate` or `tier` say, since
   they can disagree after a re-scan. A row that failed on `wide_quote` has no edge worth showing.
2. **The comparison is labelled**: "after fees vs 18¢ entry", and `quote_spread` travels so the page
   shows the thing that explains the number.
3. **A `feed:unknown` version is blanked**, not printed as the word "unknown" — which the live page
   showed under all 100 rows. The gate badge survives, because SHADOW is the honest label.

Ranking keeps the number as an explicitly-named `rank_edge_pct`: within-tier ordering across page
boundaries is a real guarantee, so the number cannot simply be dropped — but it is not the headline.
That split is why `tests/test_sports_api_range_paging.py` was updated to read the ordering field
rather than have the invariant removed.

## Task 3: the frontend stops reading the database and stops claiming a balance

`usePortfolio` queried `kalshi_portfolio` and `portfolio_metrics` **directly from the browser** with
the publishable Supabase key and subscribed to a realtime channel. That put the database in the
browser's data path — the key shipped in the bundle, RLS had to be open to the anon role for it to
read anything, and the sidebar rendered `$0.00` from an empty table plus a row of zeros last touched
in March 2026. It now reads `/api/pnl_summary` and `/api/positions`, with no Supabase import and no
realtime channel.

```text
# RED -> GREEN, src/lib/portfolioTruth.test.ts
✓ src/lib/portfolioTruth.test.ts (5 tests) 36ms
```

- `portfolioHeadline()` returns **"Suggest-only · No orders placed"**, not `$0.00`. A zero balance is
  a claim, and it was false.
- An unreadable payload reads as *unknown*, never as zero.
- `describePortfolio()` must never contain a win/loss word when nothing has been traded — asserted,
  because that is exactly the misreading a zero P&L invites.
- The positions table rendered `pos.position`, `pos.average_price`, `pos.current_price`,
  `pos.total_traded` — an ad-hoc JSON blob's fields that **exist in no migration**. It now renders the
  `paper_trades` columns that do, and the empty state says "This product places no orders" rather
  than "No active positions detected in Kalshi account", which claimed an account that does not exist.
- The sports table had **no `<thead>` at all**, so every column was unnamed to a screen reader. Added
  a header row, a caption, and `scope="row"` on the row label.

## Verification

```text
# pytest, three clocks
time.monotonic = 5.0   ->  738 passed in 25.74s
time.monotonic = 1e7   ->  738 passed in 24.19s
normal                 ->  738 passed in 24.92s      # 698 baseline + 40 new

# ruff
.../python -m ruff check --select F401,F811,F821 tradehub tests market_sentiment_tool/src
All checks passed!

# frontend
npx vitest run          ->  8 files, 37 passed
npm run typecheck       ->  clean
npm run build           ->  built in 3.07s
```

## Not verified, and why

**The running site is unchanged until this deploys.** The browser audit is evidence about the
*current* deployment; nothing here has been checked in a browser after the change, because the
change is not deployed. The claim this PR makes is a test-level claim: 738 pytest, 37 vitest, clean
typecheck and build. Someone should open `/sports` and `/` after the deploy and confirm the empty
state and the "Suggest-only" label.

## Left alone deliberately

`impeccable detect` flags one **pre-existing** finding: `Home.tsx:113` `border-l-4`, a thick
side-accent border — the most recognizable tell of a generated UI. It is not mine and fixing it is
visual work, so it is recorded here for the redesign rather than smuggled into a correctness PR.

## Kevin's checklist

1. **Apply `20260416000011_war_room_tables.sql`** (five new tables, no data, no change to any
   existing table) **and** `20260415090000_signal_events_unification.sql`, which has been outstanding.
   Until the second is applied, `/shadow` keeps returning a 503 that names it.
2. Merge, then the VPS deploy runs from `main` via `.github/workflows/deploy-tradehub.yml`.
3. After deploy, check `/api/positions` and `/api/pnl_summary` return 200, `/api/shadow-performance`
   returns 200, and `/sports` shows the honest empty state rather than 50 rejected rows.
4. No `.env` or secret changes. `suggest_only` needs no configuration.
