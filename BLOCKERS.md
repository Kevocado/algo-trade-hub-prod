# Blockers and open decisions

Written 2026-09-28. Everything here is something an agent could not finish, or a
decision the owner has not made. Nothing on this list is a code defect awaiting a
fix — the code defects found this session were fixed and merged.

**Read this before reviewing the repo.** Several items change how a review should
be judged: some failing tests are real, some endpoints are 503 *by design*, and
one number on the scoreboard is known to be stale.

---

## 1. Two migrations need applying. Only the owner can do this.

Both are additive-or-reversible and both files are already on `main`. The API
names the exact file in its 503, so no guessing is required.

| endpoint | migration | effect once applied |
|---|---|---|
| `GET /api/shadow-performance` | `market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql` | `/shadow` works |
| `GET /api/quarantine` | `market_sentiment_tool/supabase/migrations/20260428000012_kalshi_quarantine_edges.sql` | quarantine surface populates |

**`20260415090000` is half-applied and this matters.** It was run against
production and failed partway:

```
ERROR: 42P01: relation "crypto_signal_events" does not exist
CONTEXT: ALTER PUBLICATION supabase_realtime DROP TABLE crypto_signal_events
```

Root cause is a wrong PL/pgSQL exception name in the migration: the guard catches
`undefined_object` (**42704**, undefined function/operator) when a missing
relation raises `undefined_table` (**42P01**). The guard can therefore never fire,
so the migration aborts on precisely the fresh database it was written for.

Known state: the rename at line 1 committed. Everything from the publication
`DO` block (~line 48) onward did **not** run — including
`ALTER TABLE signal_events ENABLE ROW LEVEL SECURITY` and the signal-events
policy. **Verify this with a read before assuming it.**

Do not trust the migration file's own comments about what is applied. Read the
schema.

**Applying the migration will not make `/shadow` work.** It has a second,
independent blocker. `orchestrator.py:741` needs Alpaca hourly bars to produce
*any* crypto signal, so with no `ALPACA_*` key there are no `signal_events` rows
with `model_probability_yes` and nothing for the timeline to grade. A price
fallback would not help: the dependency is in the input, not the page. Kalshi is
the wrong instrument — its candles are probability cents, not BTC/USD, so
`virtual_pnl_pct` would silently become return-on-a-contract.

To fix: set `ALPACA_API_KEY` and `ALPACA_SECRET_KEY` in the stack `.env`
**and** name them in the `tradehub` service's `environment:` block in
`vps-stack/compose.yml`. **Setting them in `.env` alone does nothing** — compose
forwards only what it names, and today it names no `ALPACA_*` at all. Optionally
`ALPACA_DATA_API_BASE` too.

**Expect `/shadow` to look unavailable after the migration.** Until compose is
fixed, the amber "Waiting on environment variables" panel is the correct and
intended rendering — not a new fault.

## 2. A Supabase MCP is registered but unauthenticated

`~/.config/opencode/opencode.json` registers
`@supabase/mcp-server-supabase@0.13.0` with `SUPABASE_ACCESS_TOKEN` set. The
server returns `Unauthorized` because the process was spawned before the token
was written to the config. A full quit (⌘Q, not window close) and reopen should
fix it.

This is the only route by which an agent can apply these migrations. Until it
works, migrations are the owner's manual step. The MCP also removes the need to
infer schema state from a 503, which is how the half-applied state above went
unnoticed.

## 3. Four live API keys need rotating. Owner only.

`PL_Predictor/.env` was read by an agent while locating a database path; its
contents are in that session's transcript. The file has since been destroyed
(§4), **which does not un-expose the keys.** They must be rotated at the
provider. A separate, quieter exposure of the same kind was fixed in code: PR
#37 removed `load_dotenv()` from module scope, which had been injecting a real
`FRED_API_KEY` into every test process.

## 4. The developer-local `.env` no longer exists. Intentional.

Destroyed by an agent's shell `restore()` trap. Not recoverable from git or any
worktree. Nothing depends on it: production gets config from compose, and the
test suite is hermetic since PR #37. Only local-dev convenience is lost.

## 5. Weather and Macro: recommendation is to leave them quarantined.

Both real-edge engines were dead by schema drift, and are now repaired and
running under a **quarantine** that writes nothing to `kalshi_edges`. The
measurement argues against enabling them:

- **295 rows/scan, of which 26 are independent opportunities.** Weather 18 of 30;
  **Macro 8 of 265.**
- **82 are units artefacts** — BUY NO against a YES ask ≥95¢, 66 at exactly 99¢.
  The reported edge takes only four values because it is `99 − probability` off a
  four-way lookup table, independent of the market.
- **187 are restatements.** Neither engine has a per-market model, so one FRED
  scalar is quantised across every strike on every event — 138 GDP rows over 11
  year-events.
- The 26 remaining are distinct statements from models with **no measurement, no
  gate and no backtest.** They are not 26 good ones.

Activating them is a product decision, not a bug fix. It has not been made.

## 6. Open product decision: where the models table lives.

`/models` exists and is reachable from the nav. The open question is whether the
table belongs at the top of `/` instead, beside three plain sentences about what
the product is — on the reasoning that a reader lost among seven sidebar items is
still lost, and "I don't understand what this website is doing" is a different
question from "what are the models doing".

## 7. Known-untrue things on screen. Not bugs; do not "fix" them.

- **The scoreboard's `0.1792` for labor is stale and was measured on a leaky
  input.** Commit `12a6924` (point-in-time ALFRED vintages) landed the day *after*
  it was recorded. The market's `0.16586` reproduces exactly, so the entire
  `0.0053` improvement is model-side. The honest figure is **`0.17391`, i.e. 1.048×
  behind the market, not 1.080×.**
- **Labor is the closest of the four engines, and the difference is not
  established.** The 95% month-clustered CI on the observed gap is
  **[−0.032, +0.048], p = 0.68**. What *is* firm: perfect calibration cannot
  rescue it (oracle ceiling 0.17092 vs market 0.16586), so the residual is
  discrimination, not calibration.
- **`/api/shadow-performance` and `/api/quarantine` returning 503 is correct
  behaviour**, not a fault. Each names the migration to apply.
- **`/shadow` has three failure modes, and they are not all faults.**
  503 = migration, 424 = missing credentials (an *operator step*, rendered amber),
  500 = the code is broken (the only red one). Classify on `X-Error-Code`, or on
  status. **Do not string-match `detail`** — the same sentence must render as an
  operator step at 424 and a fault at 500, so a prose matcher gets it backwards.
  There is one narrow exception: the 503 branch reads `detail` to separate a
  missing table from other runtime errors the 503 also forwards. Do not widen it.
- **`main.py`'s "The database still has crypto_signal_events under its old name"
  is now false** — the rename committed. It only fires when the table is genuinely
  absent, so it is inert, but it is stale copy.
- **The "not running" label for Weather/Macro is a hand-maintained list.** If
  those engines are repaired, it must be removed by a human or it will go stale.
- **`current_runs` keys on `(engine, mode)`**, so `cpi-v1` and `cpi-core-v1` under
  the same fill mode collapse to one row. Pinned by a test; a one-line fix would
  change the meaning of every existing row.
- **`kalshi_quarantine_edges` accumulates and nothing prunes it.** It is a
  measurement surface. The day something reads it for a second purpose it stops
  being one.

## 8. Verification notes — read before trusting a test result

- The suite is **hermetic** since PR #37. "3 pre-existing `test_alfred_vintages`
  failures" is a **retired claim**: those failures were caused by this machine's
  untracked `.env` injecting `FRED_API_KEY`, so the suite was returning a
  different answer per machine and had never been a check on any of them. Do not
  reintroduce that as an excuse.
- **Clean baseline is 1296 passed / 0 failed** on both clocks (normal, and
  `time.monotonic` forced to `1e7`). Run it twice.
- Run the Python suite with a **verified interpreter path**. A mistyped venv path
  piped to `tail` has printed "All checks passed!" for a run that never happened
  in this repo.
- **The VPS fills up fast** — ~5GB per few deploys, no automatic reclaim until
  PR #40. A full disk presents as a red `vps` job against a green build, which
  reads exactly like a code regression. Check `df -h /` before believing one.
- **A test that cannot be satisfied is a test nobody trusts.** In PR #40 the
  correct `::warning::` contains the incorrect `:warning:`, so the negative needed
  a lookbehind, not `not in`.
