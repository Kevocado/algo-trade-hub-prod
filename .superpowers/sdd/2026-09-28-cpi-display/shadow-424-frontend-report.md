# The 424, on the client

PR #44. Follows #43 (`f856fb3`), which gave `/api/shadow-performance` three distinguishable failures
and left the frontend reading two.

---

## What a reader now sees, for each of the three statuses

All three are the same panel with the same three parts — a heading, a lead-in, and the server's own
sentence quoted in monospace — and no figure of any kind. Only the words and the colour change.

### 503 / `missing_table` — amber, unchanged

> ### 🔧 Waiting on a database migration
>
> This page is not broken and nothing is wrong with the charts. The table it reads was renamed by a
> migration that has not been applied to the live database, so there is nothing to read yet. Only an
> operator can finish this, and the step is:
>
> `table 'signal_events' is not in the database. Apply
> market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql and
> redeploy. The database still has crypto_signal_events under its old name.`

`border-amber-500/30 bg-amber-500/10` · wrench icon. **Byte for byte what it rendered before this
change.** Its test, and the three assertions on the panel's digits, are untouched.

### 424 / `missing_credentials` — amber, **new**

> ### 🔧 Waiting on environment variables
>
> This page is not broken, and nothing is wrong with the charts or with the database. The shadow
> timeline reads market data from a service this deployment has no credentials for, so there is
> nothing to read yet. Only an operator can finish this, and the step is:
>
> `This service has no Alpaca API credentials, so the shadow timeline cannot be read. The database is
> fine -- this is not a migration. Set ALPACA_API_KEY and ALPACA_SECRET_KEY in the stack's .env file,
> beside vps-stack/compose.yml. Then add 'ALPACA_API_KEY: ${ALPACA_API_KEY:-}' and
> 'ALPACA_SECRET_KEY: ${ALPACA_SECRET_KEY:-}' to the tradehub service's environment: block, and
> redeploy.`

`border-amber-500/30 bg-amber-500/10` · wrench icon. **Before this change: a red rose panel headed
"The shadow timeline could not be read"** — because `shadowUnavailable` tested the `detail` for
`supabase/migrations/`, and a 424 body has no path in it. It says *this is not a migration*. The one
state that is a person setting two environment variables was the one state with no presentation.

### 500 / `internal_error` — rose, unchanged

> ### ⚠️ The shadow timeline could not be read
>
> The read failed and this page has nothing to show. The server said:
>
> `unsupported operand type(s) for +: 'int' and 'NoneType'`

`border-rose-500/30 bg-rose-500/10` · alert-triangle icon. A broken-code 500 looks like one, names
no file and no variable, and is the only state no operator step closes.

Side by side: **two ambers with different instructions, one rose.** The two ambers are the same kind
of fact — a person has a step to take on this deployment — so they share a colour and an icon, which
is what `StoppedEnginesNotice` and `QuarantineNotice` already do for their non-fault states. The
rose is the only one that is a fact about the code.

---

## The one that used to be a fault

It is worth being concrete about how bad the old rendering was, because it is the argument for the
whole change. `vps-stack/compose.yml` passes no `ALPACA_*` to the tradehub service, so this is the
live state, not a hypothetical:

1. Owner applies `20260415090000_signal_events_unification.sql`.
2. The 503 stops firing. The 424 starts.
3. `/shadow` renders **red**, headed "The shadow timeline could not be read", quoting a sentence
   that says *"The database is fine -- this is not a migration."*
4. The reader has just applied the migration the panel's own text disclaims. They have no way to tell
   that the next step is a different act entirely, in a different file, on a different machine.

PR #43 fixed the server's half of that. Nothing had changed on this side, so step 3 was still what
happened. The backend change was necessary and not sufficient.

---

## Branching on status, not on message

`shadowUnavailable` now takes a third argument, `errorCode`, and consults evidence in one fixed
order. `market_sentiment_tool/src/lib/shadowPerformance.ts`:

| order | evidence | why there |
|---|---|---|
| 1 | `X-Error-Code` | the narrowest claim, and a name rather than a number |
| 2 | `status` | what decides when a proxy did not forward the header |
| 3 | a `supabase/migrations/` **path** in the body | last resort, and only when 1 and 2 are both absent |

Step 3 is the pre-existing migration check, kept and deliberately **not** widened. It exists because
`_missing_table_message` forwards any non-PGRST runtime error through the same 503, so 503 alone
cannot promise a migration — and because the migration lead claims the table was renamed, which a
body reading "cannot read the timeline: 42" would contradict on screen. It is a file path, not a
sentence, so reading one is checking the claim the panel is about to make rather than parsing prose.

Step 3 is **not** extended to credentials. With no status and no code, a sentence naming a variable
is English, and this client has nothing machine-readable to stand on. Pinned by a test.

The header is read once, in the hook, where the `Response` is still in scope
(`useShadowPerformance.ts`, `errorCodeOf`), and attached to the error. It was previously discarded
entirely — which is why the test suite could not have noticed that nothing was reading it.

**A client that receives only a 424 with no header still classifies correctly**, from the status
alone. A gateway that does not forward custom headers is an ordinary thing and must not turn an
operator step back into a red panel.

---

## What I did *not* do, and why

- **No copy of the instruction in the component.** The 424 lead does not name `ALPACA_API_KEY`. The
  server's sentence already does, and the migration lead does not restate the migration filename
  either — same reasoning, same rule: a second copy of a table→file mapping is a second place to be
  wrong. The title is "Waiting on environment variables", with no count, because a third credentialed
  service is a one-line change in `CREDENTIAL_SOURCES` and a printed "two" would become a lie.
- **No Python test reading the frontend source.** `tests/test_repo_layout.py` sets that precedent, and
  the backend already has `test_a_missing_credential_does_not_read_as_a_migration_to_the_frontend`
  guarding the one direction it could. This file is a frontend change and the behaviour is frontend
  behaviour; a second copy of the assertion in Python would be a second place to be wrong.
- **No digit on the new panel.** The 424 assertion is `toEqual([])` on every digit in the panel, not
  "none of the summary cards" — the server's instruction happens to contain none, so it is exact, and
  it catches a `0.00h` freshness line or a stray `424` printed as a figure.
- **No new pattern.** `StoppedEnginesNotice` and `QuarantineNotice` are the prior art and the shape
  is theirs: a heading naming the state, a sentence saying the absence is not a finding about the
  market, and the server's words rather than a paraphrase. A red frame is reserved for a failed read
  in both of them too.

---

## Mutations

Both run against the real suite, reverted immediately after. Interpreter confirmed present
(`Python 3.12.14`, `.venv/bin/python` → cpython-3.12-macos-aarch64) before any result was believed.

### M1 — make a 424 render the fault panel

`if (false && failure === "missing_credentials")` in `shadowUnavailable`.

```
Tests  12 failed | 41 passed (53)
```

Failing, with `expected 'fault' to be 'operator_step'`:

- lib: *presents a 424 as an operator step, not as a fault*
- lib: *classifies on the status when the response carried no X-Error-Code*
- lib: *prefers X-Error-Code over the status, because it is the narrower claim*
- lib: *says something on a 424 that arrived with no body at all*
- lib: *calls a 424 an operator step even when its detail says nothing about credentials*
- lib: *calls a 424 an operator step even when its detail names a migration*
- page: *renders the operator step, not the fault panel, and names both variables*
- page: *prints no figure and no figure-shaped zero, exactly as the migration panel does not*
- page: *reads the status alone when the proxy drops the X-Error-Code header*
- page: *gives each status its own heading and its own frame, and collapses no two of them*
- page: *calls a 424 an operator step when its detail names nothing but a dependency*
- page: *calls a 424 an operator step when its detail names a migration*

The 41 that still passed are the point: **every 503 and 500 test survived**, so the mutation was
surgical and the 503 is not riding on the 424.

### M2 — classify by string-matching `detail`

Prose check hoisted above the status and the header, in the classifier:

```ts
if (body !== null && /alpaca|api[_ ]?key|credential/i.test(body)) return "missing_credentials";
```

```
Tests  3 failed | 50 passed (53)
```

Failing, with `expected 'operator_step' to be 'fault'`:

- lib: *keeps a 500 a fault even when its detail is the credential sentence word for word*
- lib: *keeps the migration path as a last resort, and does not widen it to credentials*
- page: *keeps a 500 a fault when its detail is the credential sentence word for word*

This is the sharp one. The same sentence that renders an operator step under a 424 renders a fault
under a 500, and a prose matcher gets that backwards — which is the exact defect #43's own test
describes ("a 500 whose body said 'Missing Alpaca API credentials' sent a reader to set environment
variables when the code was broken"). Reverted; `grep -c MUTATION` on the file returns 0.

---

## Verification

| check | result |
|---|---|
| `.venv/bin/python -m pytest -q`, clock A | **1325 passed, 0 failed** (88s) |
| same, `time.monotonic = lambda: 1e7` | **1325 passed, 0 failed** (95s) |
| baseline on unmodified `origin/main`, clock A | 1325 passed, 0 failed — matches |
| `ruff check --select F401,F811,F821 tradehub tests` | All checks passed |
| `npm run typecheck` | clean |
| `npx vitest run` | **454 passed / 0 failed**, 28 files (was 426; +28) |
| `npm run build` | built in 3.85s |
| `npm run lint` | 17 problems, all in pre-existing untouched files; **0 in the 3 files I changed** |

Interpreter confirmed before the first pass, per `BLOCKERS.md` §8. Both clocks run, as `BLOCKERS.md`
§8 asks, and the result matches the stated clean baseline. No `.env` read, no SSH, no secrets.
`tradehub/` untouched — the backend is merged and correct.

**Not reported, because it is retired:** there is no "3 pre-existing `test_alfred_vintages`
failures" here. The suite is hermetic and returned 1325/0 twice on both clocks, and that claim is
recorded in `BLOCKERS.md` §8 as caused by this machine's untracked `.env` leaking a real
`FRED_API_KEY` into every test process.

**The `selectTab` trap does not apply here.** It lives in
`PredictionLab.stoppedEngines.test.tsx`, which I did not touch; `ShadowBacktester` uses plain
`<button>` elements for its domain and hours controls and my tests drive no interaction at all — they
stub `fetch` and assert on rendered output. So there is no way for a `click`-vs-`mouseDown` mistake
to have produced a green test that renders nothing.

---

## The case against, as asked

I was asked to argue that a missing credential might be better shown as an unavailable feature with
no instructions, on the reasoning that operators are not the audience for this page. I did not take
that position, for four reasons — but the first is the only one I would call decisive.

**1. The audience for this page is the owner, and the owner is the operator.** This is a
single-operator product: seven sidebar items, one VPS, one `compose.yml` in the repo, and a
`BLOCKERS.md` whose entire purpose is to hand the owner a list of things only they can do. Every
other notice on this product behaves the same way. `StoppedEnginesNotice` names the engine, the
reason, every scan site, and its `disposition`; `QuarantineNotice` names the sink table and prints
`kalshi_edges_written: 0` as a proof. "Show the product's configuration" is not an odd thing for this
product to do — it is the product's editorial voice. A page that hid its own misconfiguration behind
"temporarily unavailable" would be the outlier.

**2. "Unavailable, no instructions" is the state we are already leaving, and it is the state that
cost the owner an afternoon.** The 424 rendered as a red fault with no instructions. Stripping the
instructions and calling it merely unavailable does not fix the diagnosability; it only softens the
colour. The reader still cannot tell whether the migration is unapplied, the credential is unset, or
the code is broken. Softening without naming the step trades accuracy for comfort.

**3. The server already made the decision, and the cost of overriding it is permanent.** `_missing_credential_message`
goes out of its way to name the variables, the `.env` beside `compose.yml`, *and* the
`environment:` block that has to name them too — because `compose.yml` will not pass `ALPACA_*`
through even once they are set. A client that suppressed that sentence would be suppressing the only
copy of a three-part instruction that exists. And the asymmetry runs the other way too: because the
*server* chose 424 over a second 503, `compose.yml` not passing the variables is a real, currently-
true fact about the deployment. Showing it is not showing internal plumbing that happens to exist;
it is showing the one outstanding step.

**4. Where I would concede the argument, and it is a real concession.** A **public** product page
should not print its own environment-variable names at a stranger. There is a defensible world where
`/shadow` is a marketing surface and "Shadow tracking is not yet available" is the whole truth. But
this is not that product, and — the thing that decides it — the same reader is looking at
`Compose Trades 0` figures on the neighbouring page. This audience has been told, on purpose and in
detail, that its own deployment is misconfigured; a page that went quiet about its own half of that
would be the inconsistency, not the norm.

**What I did concede to the argument:** the panel stays an *operator step*, not an *error*. It is
amber, not red. It leads with "This page is not broken" and "nothing is wrong with the charts or with
the database", so a reader who is not the operator is told in the first sentence that there is nothing
wrong with the product. That is as far as the "don't shout about your own configuration" argument can
be honoured without reinstating the undiagnosable state.
