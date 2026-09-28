# `/api/shadow-performance` — the blocker behind the migration

2026-09-28 · branch `fix/shadow-alpaca-credential-vs-table` · base `origin/main` @ `893251e` (PR #42)

---

## 1. Can `/shadow` work without Alpaca credentials? **No.**

Not "not without Alpaca's data API" — **no, not at all, and not even with a perfect fallback**, because
the dependency is not in the page. It is in the *input*.

The shadow timeline grades signals that the crypto engine produced. The crypto engine cannot produce
a signal without Alpaca. `market_sentiment_tool/backend/orchestrator.py:892`:

```
_latest_crypto_feature_row(asset, model)
  -> _fetch_alpaca_crypto_bars(asset)
       orchestrator.py:741   if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
                                raise RuntimeError("Missing Alpaca API credentials for crypto feature fetch.")
```

That is on the path to every crypto signal, because the model's features *are* Alpaca hourly bars.
So with no `ALPACA_*`:

- no crypto features → no crypto inference → no rows in `signal_events` with
  `model_probability_yes` set → **nothing for the timeline to grade**;
- and the timeline's own price read would fail anyway.

`fetch_recent_signal_events` filters on exactly that column being non-null
(`tradehub/scripts/shadow_performance.py:189`). So on the VPS today, applying the migration gives you
an empty timeline **and** a credential error. A fallback price source would change the second problem
and leave the first untouched.

**The exact variables, and where they go:**

| | |
|---|---|
| Variables | `ALPACA_API_KEY`, `ALPACA_SECRET_KEY` |
| Value | read from `os.getenv`; a free paper key is enough — this only reads bars |
| File | the stack's `.env`, beside `vps-stack/compose.yml` (that is where compose reads its `${VAR:-}` defaults from) |
| Also required | `vps-stack/compose.yml` must name them in the **`tradehub` service's `environment:` block**, which today has no `ALPACA_*` at all |

The compose half is the part that is easy to miss and it is a real trap: setting the variables alone
changes nothing, because compose does not forward what it does not name. The existing precedent is
line 171, `FRED_API_KEY: ${FRED_API_KEY:-}`. The new lines are identical in shape.

**Optional, worth setting at the same time:** `ALPACA_DATA_API_BASE` (defaults to
`https://data.alpaca.markets`, so it is not required).

### Fallbacks I looked at, and why each is wrong

The prompt suggested Kalshi, which other engines already read. **Kalshi is the wrong instrument
here**, and I checked rather than assumed:

- **Kalshi candlesticks** (`tradehub/backtest/kalshi_history.py`, `merged_candles`) return
  `yes_bid`/`yes_ask` — a contract price in *cents of probability*, not BTC/USD dollars. The series
  feeds `current_price` and `next_hour_price`, and those feed
  `virtual_return_pct = (next − current) / current`. Feed it contract prices and `virtual_pnl_pct`
  silently becomes return-on-a-prediction-market-contract instead of return-on-BTC. Same number, same
  column, different meaning, no error raised. That is exactly the "invent a data source that changes
  what the page means" failure.
- **`signal_events.spot_price_dollars`** is a real BTC/USD dollar price, written at signal time. But
  there is no stored *next*-hour close anywhere in the schema, so it can supply `current_close` and
  nothing else — and the rows carrying it were written by the engine that needs Alpaca. Not a
  fallback; the same dependency by a different route.
- **Binance** (`tradehub/core/microstructure_engine.py`) is futures funding rates and order-book
  depth, live-only, never persisted, and a different instrument again.
- **yfinance** (`tradehub/scripts/calibrate_crypto_sources.py`) *is* a genuine second source of
  BTC-USD hourly bars, and `yfinance` is already an import in the tree. It is the only technically
  viable fallback I found. I did not wire it in, because it is a rate-limited Yahoo scrape with no
  SLA and this is a request path — and because of the first section: it would not make the page work,
  since the *signals* still would not exist. If the owner wants a belt-and-braces price source, this
  is the one, and it should be a separate decision.

### Should `/shadow` be removed as unsupportable? **No — and this is the strongest argument against.**

"Delete the page" is wrong here for a reason that is specific and checkable: **the blocker is a
missing key, not a missing capability.** Nothing about the timeline is impossible. The engine already
runs on Alpaca; the same credentials the crypto engine needs would make the page work, and the
crypto engine's own value depends on Alpaca anyway. If Alpaca is worth having for inference — it
demonstrably is, or the crypto engine would already be dead — then it is worth having for grading
those inferences, which is the cheapest possible use of the same key.

The page is a **measurement surface** for a running engine, and it is the only view of per-signal
outcomes in the product. Deleting it would remove the thing that tells the owner whether the crypto
engine is any good. The honest cost of the missing credential is one red page, and after this PR that
red page says precisely what to do about it.

---

## 2. The three cases are now distinguishable by status, not by prose

The old handler had one `except RuntimeError` that assumed every `RuntimeError` was a missing table.
That assumption was wrong the moment Alpaca raised one, and it will be wrong again the next time
something new raises a `RuntimeError` in that builder.

All three answers now come out of the one shared helper, `_table_fault`, which is the same place the
missing-table 503 already lived — so the War Room scoreboard and the CPI nowcast get it for free,
which is the point of one helper rather than a fourth handler to get wrong.

| Case | Status | `X-Error-Code` | Detail |
|---|---|---|---|
| table missing | **503** | `missing_table` | names the migration file |
| credential missing | **424** | `missing_credentials` | names the variables + the file + the compose block |
| code is broken | **500** | `internal_error` | the exception text, and nothing else |

**Why a different status and not a second 503.** The status is the only field a client can branch on
without parsing English. Two operator-actionable problems that share a status are one problem as far
as a client is concerned, and that is precisely what made this undiagnosable. 424 *Failed Dependency*
(RFC 4918) is used nowhere else in this repo, and it describes the situation accurately: the Alpaca
market-data API is a dependency of this endpoint and this deployment cannot reach it. It is not a
memorable code, which is why the `X-Error-Code` header exists — a client that wants a name rather than
a number has one, and a client that only looks at numbers has the status. **Neither depends on
remembering 424.**

`detail` stays a plain **string** on all three. The frontend reads `payload.detail` and hands it
straight to a person (`market_sentiment_tool/src/hooks/useShadowPerformance.ts:79`), so turning the
body into an object would have broken the page. That constraint is *why* classification has to live in
the status: the body is prose, and prose is what this endpoint had been reduced to.

### One detail that is load-bearing and easy to lose

`build_shadow_timeline_response` used to re-raise `RuntimeError(str(report["errors"][0]))`. That
re-wrap took a typed `MissingCredentialError` — which carries `("ALPACA_API_KEY",
"ALPACA_SECRET_KEY")` as attributes — and flattened it into an undifferentiated string. Every
downstream classification was therefore working from a substring. The original exception now survives
the wrapping (`tests/test_shadow_credential_faults.py::test_the_credential_type_survives_the_builders_error_wrapping`).

There is also a text fallback in `_is_missing_credential`, because
`market_sentiment_tool`'s orchestrator raises its *own* `RuntimeError` for the same two variables. A
classifier that only understood one module's class would go back to guessing the moment a second
caller appeared — the same failure mode as the dead `except RuntimeError`. The typed check is tried
first and is exact; the text is the backstop. I verified honestly that the backstop alone is enough
to keep the endpoint at 424, so the typed path is precision, not the only thing holding it up.

---

## 3. Mutations

Both required mutations, run against `tests/test_shadow_credential_faults.py` (14 tests).

**Mutation 1 — credential error returns the same 503 as missing-table:**

```
status_code=_STATUS_MISSING_TABLE,  headers={"X-Error-Code": _CODE_MISSING_TABLE}

FAILED test_a_missing_credential_is_not_reported_as_a_missing_table
FAILED test_each_failure_case_has_its_own_status_and_its_own_code[missing_credential]
FAILED test_the_three_cases_are_three_distinct_answers
FAILED test_the_other_two_table_readers_get_the_same_three_way_decision
FAILED test_a_credential_error_from_another_module_is_still_classified
5 failed, 9 passed
```

**Mutation 2 — credential error returns 500:**

```
status_code=_STATUS_INTERNAL_ERROR,  headers={"X-Error-Code": _CODE_INTERNAL_ERROR}

FAILED test_each_failure_case_has_its_own_status_and_its_own_code[missing_credential]
FAILED test_the_three_cases_are_three_distinct_answers
FAILED test_the_other_two_table_readers_get_the_same_three_way_decision
FAILED test_a_credential_error_from_another_module_is_still_classified
4 failed, 10 passed
```

**Mutation 3, not requested, run because it is the deepest change** — restore
`raise RuntimeError(str(report["errors"][0]))`:

```
FAILED test_the_credential_type_survives_the_builders_error_wrapping
1 failed, 13 passed
```

Only the type is lost by mutation 3; the endpoint still returns 424 via the text backstop, so this
test is pinning precision rather than behaviour. I would rather say that than let the green result
imply more than it does.

---

## 4. RLS: `"Anon can view signal events"` — owner's decision, not changed

**This is a real exposure and it is not new. I have not touched it and recommend it not be changed
blind.** It needs the owner, because the blast radius is unknown from inside this repo.

```sql
-- 20260428000013_signal_events_publication_and_rls.sql:122
CREATE POLICY "Anon can view signal events"
ON signal_events FOR SELECT TO anon USING (true);
```

### What it exposes

Every row of `signal_events`, to anyone, with no per-user predicate. `USING (true)` is unconditional.
That includes, per column:

- `user_id` — every user's identity linkage, cross-referenced against `auth.users`;
- `model_probability_yes`, `edge` — **the model's own probabilities and its claimed edge.** This is
  the product's intellectual property, and it is the thing an unauthorised reader would want: a
  replayable record of how confidently the engine called each market, with timestamps.
- `signal_price_dollars`, `kalshi_price_dollars`, `spot_price_dollars`, `strike_price`,
  `event_close_time` — the book and the strike, per signal.
- `payload` (`jsonb`) — free-form, contents vary by writer.
- `domain` — so a reader can filter, and the `idx_signal_events_created_at` index makes the read
  cheap.

Every domain, not just crypto: the policy is on the unified table, and the table is multi-tenant by
`user_id`.

### Who can read it today

**Anyone who loads the website.** Supabase's anon key is designed to be public and is not treated as
a secret: `market_sentiment_tool/src/lib/supabase.ts:4` reads
`VITE_SUPABASE_ANON_KEY` and passes it to `createClient`, so the key is compiled into the public JS
bundle. No breach, no credential theft, no privileged access is required — read the bundle, call
`GET /rest/v1/signal_events?select=*`, get every row.

Note what makes it *worse* than a typical anon policy: migration `20260428000013` runs
`ALTER TABLE signal_events ENABLE ROW LEVEL SECURITY`. RLS being on is what makes this policy the
*only* thing standing between the anon key and the data. Without it the anon key would get zero rows.
The policy is the door.

### The risk

Confidentiality of every user's signal ledger, and of the model's edge, to the public. Secondary but
real: it is a free, no-auth, unmetered read surface on a production table, and it enumerates
`user_id` values, which is user enumeration and an input for correlation against any other
exposure.

### Why I did not change it

Removing an RLS policy can break a client I cannot see, and tightening it is a security decision with
a blast radius that is not mine to spend. Concretely:

- **No client in this repo reads it.** I grepped the frontend for `signal_events`: the only hits are
  test fixtures and a docstring. The one real reader is
  `tradehub/scripts/shadow_performance.py`, which goes through the **service role** and bypasses RLS
  entirely. So the case for keeping it is *not* in this repo — which is exactly why I cannot rule it
  out.
- **It is not an isolated policy.** Nine other anon `USING (true)` policies exist across these
  migrations (`20260223223000` on `agent_logs`, `portfolio_state`, `trades`, `user_settings`;
  `20260416000000` on `kalshi_portfolio`, `portfolio_metrics`; `20260416000010` on `news`; and
  `20260408224000` on the old `crypto_signal_events` name). Dropping this one alone leaves the
  posture incoherent, and several of those look worse than this. **The systemic question is the
  real one, and it is bigger than this PR.**
- It predates this work. Created `20260408224000:79` as `"Anon can view crypto signal events"`,
  carried through the rename by `20260415090000:99`, re-created by `20260428000013:122`.

### What I recommend, in order

1. **Today, before or alongside the migration:** rotate nothing, change nothing — but confirm with
   the owner that nothing outside this repo reads `signal_events` with the anon key. That is the one
   question gating the rest, and only the owner can answer it.
2. **Then, if nothing reads it:** `DROP POLICY "Anon can view signal events" ON signal_events;`.
   Service-role readers are unaffected, and the table becomes anon-invisible.
3. **Worth its own pass:** audit all nine. `user_settings` and `trades` under an anon `USING (true)`
   — and `user_settings` additionally has an anon `UPDATE` — are more alarming than this table, and I
   have not been asked about them.

**After this PR, the page will also stop *saying* the wrong thing:** the credential detail
deliberately contains no `supabase/migrations/` path, so the frontend's
`shadowUnavailable` (`MIGRATION_PATH = /supabase\/migrations\//`) headlines "Waiting on a database
migration" only for an actual missing table. Pinned by
`test_a_missing_credential_does_not_read_as_a_migration_to_the_frontend`, because the frontend is out
of scope and cannot defend itself.

---

## 5. Notes, stale text, and what I did not touch

- **`main.py:187` is stale and left alone as instructed:** *"The database still has
  `crypto_signal_events` under its old name."* It is now false — after `20260428000013` there is one
  `signal_events` and a `crypto_signal_events` **view**. It only fires when the table is genuinely
  absent, so it cannot mislead about a present table, and the frontend is out of scope. Worth
  deleting when someone next touches the frontend.
- **The frontend will still headline this as a fault, not an operator step.** `shadowUnavailable`
  classifies `waiting_on_operator` by matching a migration path in the detail, so a 424 renders as
  *"The shadow timeline could not be read"* with the server's sentence quoted underneath. That is
  honest and not false, but it under-sells a problem an operator can fix in one minute. With a
  distinct status in the response, the frontend can now branch on `status === 424` and say "set these
  two variables" — a small, separate frontend PR. **Out of scope here; flagging it as the follow-up
  this enables.**
- **The `supabase is None` 503s** (five handlers: "Supabase not configured") are a fourth,
  already-clear shape — different status, different message, already distinguishable. Left alone: not
  the reported bug, and folding them into `_table_fault` would change five endpoints' responses for no
  gain. (No test currently pins them, so they are also the most likely place for a future
  inconsistency to creep in.)
- `errors` in `build_shadow_report` is unchanged as a list of strings, same order, same dedup, so the
  Telegram cron (`tradehub.core.telegram_notifier`) is unaffected. Pinned by
  `test_the_telegram_path_still_gets_its_strings`, because that path renders a text report and would
  have been the quiet casualty of a typed rewrite.
- No frontend files touched. No `.env` read. No SSH. Nothing committed to `main`.

---

## 6. Verification

Interpreter confirmed present before any result was believed:
`/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python` → CPython 3.12.14.

```
# baseline, clean origin/main @ 893251e
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  .venv/bin/python -m pytest -q
  → 1311 passed in 95.85s

# with this branch
  → 1325 passed in 99.43s          (normal clock)
  → 1325 passed in 90.08s          (time.monotonic forced to 1e7)

.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests
  → All checks passed!
```

The second clock was produced with a `sitecustomize.py` **outside the repo** that rebases
`time.monotonic` to `1e7`; the harness was verified to actually move the clock (it read
`9999999.999…` against an unpatched `835294.74…`) before the suite was run under it, because a
verification harness that silently does nothing is the same failure as a mistyped venv path.

**1311 → 1325 is +14, all of them the new tests. No existing test was modified, relaxed or deleted.**
