# FRED API vintages (queue item 4) — evidence report

- Origin: queue item 4 of the rollout. It answers **Kevin's follow-up 2** in
  `docs/superpowers/reports/2026-09-25-labor-nowcast-jobs-scorecard.md` — "ALFRED from the VPS, still
  unverified, and now the blocking item" — with an answer that does not depend on the network.
- Branch: `plan/2026-09-26-fred-api-vintages`
- Base: `origin/main` at `ce148ef` (PR #13 merged, plus #14)

## Why

Step 8's labor nowcast reads point-in-time FRED vintages through `alfredgraph.csv`, which is keyless
and therefore unauthenticated — and also unreachable from some networks. **This machine cannot reach
it**: `curl --http1.1 'https://alfred.stlouisfed.org/graph/alfredgraph.csv?id=PAYEMS&vintage_date=2025-01-31'`
returns `000` (connection failure), over both HTTP/2 and HTTP/1.1, while
`https://api.stlouisfed.org/fred/...` answers normally (an unauthenticated request returns FRED's own
`{"error_code":400,"error_message":"Bad Request.  Variable api_key is not set."}`).

So the choice was: fix egress, or stop depending on the one host that needs it. This branch does the
latter. `FRED_API_KEY` set → `fred/series/observations`. Unset → the keyless CSV, untouched.

## Baseline

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
685 passed in 5.79s
```

## RED

```text
# git stash push tradehub/data/alfred_vintages.py, then:
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q tests/test_alfred_vintages.py
ImportError: cannot import name 'FRED_SERIES_OBSERVATIONS' from 'tradehub.data.alfred_vintages'
1 error in 0.09s
```

## GREEN

```text
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q tests/test_alfred_vintages.py
19 passed in 15.10s          # 6 pre-existing + 13 new

SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder ... -m pytest -q
698 passed in 21.66s         # 685 baseline + 13 new

.../python -m ruff check --select F401,F811,F821 tradehub tests
All checks passed!
```

## Equivalence, measured rather than assumed

`fred/series/observations` answers with the single realtime window it is asked for, so a vintage date
`D` is `realtime_start=D&realtime_end=D`. That is the same thing `alfredgraph.csv` returns as the
column `S_YYYYMMDD` for `vintage_date=D`.

Two real payloads were recorded on 2026-09-26 (`fred/series/observations?series_id=PAYEMS&file_type=json&observation_start=2024-09-01`,
one request per vintage) and stored as `tests/fixtures/labor/payems_2024{1231,1231}_fred_api.json`. The
CSV side of the comparison is the repo's existing recording, `payems_2024_2025.csv`. The API was
called with the key from the local `.env`; the key appears in no fixture (FRED returns it only in the
request URL, never in a body — asserted by a test).

| observation | ALFRED CSV `PAYEMS_20241231` | FRED API `realtime=2024-12-31` | ALFRED CSV `PAYEMS_20250131` | FRED API `realtime=2025-01-31` |
| --- | --- | --- | --- | --- |
| 2024-09-01 | 159025 | 159025 | 159025 | 159025 |
| 2024-10-01 | 159061 | 159061 | 159068 | 159068 |
| 2024-11-01 | 159288 | 159288 | 159280 | 159280 |
| 2024-12-01 | *(not published)* | *(absent)* | 159536 | 159536 |

Identical, including the absence of the December observation on the 2024-12-31 vintage. The tests
assert both that the two paths return equal dicts and that the month-end values themselves are
`159536.0` and `159288.0`, so an equal-but-wrong pair cannot pass.

## The leak, and why the exception chain had to go

A FRED key is a query parameter, so it lands in `requests`' `PreparedRequest.url`, and requests
rebuilds `HTTPError.__str__` from that URL. Redacting only the message is not enough: `raise ... from
exc` keeps the original exception object, so `logger.exception(...)` of the failure prints the key
anyway. A test caught exactly this — the message came out `api_key=***` while `repr(__cause__)` still
carried the key in plain text.

So when a `secret` is in play the re-raise is `raise RuntimeError(redacted) from None`: the redacted
text already carries the status code and the URL, and the original is dropped rather than leaked. With
no key, the keyless CSV path keeps `from exc` exactly as before, because there is nothing to leak.

Four tests pin this: a rejected request (400), a transport failure, a retry-exhausted failure that
also emits the scan-budget warning (asserted present, so the log path really ran), and an
already-expired deadline. Each asserts the key is in no raised message, no chained cause and no log
record — while the params the request is built from still carry the real key.

## What did not change

- Deadline, retry, backoff and clamping: `default_get_text` is the same function, now with a
  `secret` parameter that is only ever used to redact. The API path passes `deadline` through it, and
  a test asserts a scan whose budget is already gone makes **no** request.
- The on-disk cache: same format, same `repr(float)` precision rule, same "past vintages only". A
  cache written by either path satisfies the other, asserted by a test that re-runs a keyed fetch
  keyless with a server that raises if touched.
- The keyless CSV path: same URL, same `VINTAGES_PER_REQUEST = 12` batching, same params.

## Cost: more requests when a key is set

The API returns one window per request, so there is nothing to batch: a keyed cold fetch is one
request per uncached vintage, where the keyless path did 12 per request. A full labor scan asks for
~40 month-ends across 7 series, so a cold keyed run is ~280 small JSON requests instead of ~24 CSVs.
That is the price of the reachable host, and it is why the persistent cache matters more than before.

## Kevin's checklist (nothing here is deployed or configured by the agent)

1. **Review and merge.** No merge is done by the agent.
2. **`/opt/stack/.env`**: add `FRED_API_KEY=<your key>`. It is already in your local
   `algo-trade-hub-prod/.env`; this branch does not read, write or commit that file.
3. **`vps-stack/compose.yml`**: the `tradehub` service needs
   `FRED_API_KEY: ${FRED_API_KEY:-}` in its `environment:` list, or the key in `/opt/stack/.env` never
   reaches the container and this branch silently keeps using the keyless path. **This line is the
   reviewer's to add** — `vps-stack` is a separate repo and is not in this branch.
4. **Verify the key reached the container** (prints only whether it is set, never the value):
   `docker compose run --rm tradehub python -c "import os;print('FRED_API_KEY set:', bool(os.getenv('FRED_API_KEY')))"`
5. **Mount the vintage cache** (already step 8's follow-up 3, but more important now): a host dir
   such as `/opt/stack/data/alfred` into the `tradehub` service with `TRADEHUB_ALFRED_CACHE` pointing
   at it. The job containers are throwaway (`docker compose run --rm`), so without this every scan
   re-downloads every vintage — and a keyed scan re-downloads ~280 of them.
6. **Confirm the keyed path in a real scan**: `docker compose run --rm tradehub python -m
   tradehub.scripts.scan_labor` and confirm `labor_nowcast` is not an error. This cannot be verified
   from the dev machine, which is the whole reason this branch exists.
7. **Existing open item, still open**: whether the VPS can reach `alfred.stlouisfed.org` at all.
   With a key this no longer matters for labor; it is still worth knowing before anything else depends
   on that host.

## Deviations

- The plan's wording was "keyed FRED API fallback"; implemented as **keyed preferred, keyless kept as
  the fallback**, i.e. the key decides which host is asked. There is no error-path fallback from the
  API to the CSV: a scan that silently switched data sources mid-run would be far worse than one that
  fails loudly, and the report above shows the two agree anyway.
- `.env.example` does not exist in this repo, so `FRED_API_KEY` is documented in the module docstring
  and here rather than in a sample env file. No new file was created for it.
- No change to `tradehub/data/labor_inputs.py`: it already passes through `**kwargs`-free arguments
  and picks up the key from the environment inside `fetch_vintages`, so the scan, the backtest and
  the scorecard builder all get the fallback with no call-site change.
