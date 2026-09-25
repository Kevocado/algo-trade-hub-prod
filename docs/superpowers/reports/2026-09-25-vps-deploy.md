# VPS Deploy — evidence report

**Plan:** [docs/superpowers/plans/2026-09-25-vps-deploy.md](../plans/2026-09-25-vps-deploy.md)
**Branch:** `plan/2026-09-25-vps-deploy`
**Base:** `98432bc` (Claude's reconciled PR #4 head; PR #4 is still open and was explicitly authorised as the starting point)
**Tasks implemented here:** 1–4. Task 5 is Kevin's operational checklist — recorded below, **not executed**.

Every pytest run is prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` and uses
`/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python`.

## Baseline (before Task 1)

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
........................................................................ [ 21%]
........................................................................ [ 42%]
........................................................................ [ 63%]
........................................................................ [ 84%]
.....................................................                    [100%]
341 passed in 4.50s

$ /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests shared
All checks passed!
```

Baseline confirmed: **341 passed**, scoped Ruff clean (`F401,F811,F821` over `tradehub tests shared`,
the same scope used by the previous plans' reports).

### Tool availability (recorded honestly, not assumed)

| Tool | State |
|---|---|
| `docker` | available — `/Users/sigey/.docker/bin/docker`, Docker version 29.7.2 |
| `actionlint` | **not installed** on this machine (`command not found`); Task 3's actionlint check is therefore reported as not run, and the Docker-based actionlint container was not used (see Task 3) |
| `npm` / `node` | available — npm 11.6.2, node v24.11.1 |

---

## Task 1 — Same-origin SPA mount + `/api/track-record`

**Files:** created `tradehub/api/frontend.py`, `tests/test_api_frontend.py`; modified `tradehub/api/main.py`.
No deviation from the brief: the supplied code applied as-is (PR #4's head had not touched
`tradehub/api/main.py` around the dev entrypoint, so the insertion point was unchanged).

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest tests/test_api_frontend.py -q
==================================== ERRORS ====================================
_________________ ERROR collecting tests/test_api_frontend.py __________________
ImportError while importing test module '.../tests/test_api_frontend.py'.
Traceback:
tests/test_api_frontend.py:4: in <module>
    from tradehub.api.frontend import mount_frontend
E   ModuleNotFoundError: No module named 'tradehub.api.frontend'
=========================== short test summary info ============================
ERROR tests/test_api_frontend.py
!!!!!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!!!!!
1 error in 0.25s
```

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_api_frontend.py tests/test_kalshi_edge_system.py -q
........................                                                 [100%]
24 passed in 1.71s
```

Full suite + scoped Ruff (regression check):

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
341 → 345 passed in 4.12s   (4 new tests in tests/test_api_frontend.py)

$ .../.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests shared
All checks passed!
```

### Implementation summary

- `tradehub/api/frontend.py`: `SPAStaticFiles` (a `StaticFiles` subclass whose `get_response` falls
  back to `index.html` on a 404 for non-`api` paths, and re-raises for `api/*`) and
  `mount_frontend(app, dist) -> bool`, which mounts `dist` at `/` only when `dist/index.html` exists.
- `tradehub/api/main.py`: added `from tradehub.api.frontend import mount_frontend`; added
  `GET /api/track-record` (503 when `get_supabase` returns `None`, otherwise
  `track_record.select("*").order("engine")`); then, last of all route definitions, resolved
  `FRONTEND_DIST` from `$FRONTEND_DIST` (default `<repo>/market_sentiment_tool/dist`) and called
  `mount_frontend(app, FRONTEND_DIST)`.
- Verified behaviours (from the tests): `/shadow` returns the SPA, `/api/missing` returns 404 and
  never the SPA, the endpoint orders by `engine`, and 503 (not 500) when Supabase is unconfigured.
- Locally no `market_sentiment_tool/dist` exists, so nothing is mounted at import time — the
  existing `TestFastAPIEndpoints` suite keeps passing.

**Commit:** `feat: serve the War Room SPA and track record from the API`

## Task 2 — Dockerfile + .dockerignore

**Files:** created `Dockerfile`, `.dockerignore`; modified `tests/test_repo_layout.py` (appended
`test_dockerfile_and_dockerignore`) and `market_sentiment_tool/package-lock.json` (regenerated only).
No deviation from the brief: the supplied Dockerfile, `.dockerignore` and test applied as-is.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py::test_dockerfile_and_dockerignore -q
E       FileNotFoundError: [Errno 2] No such file or directory:
        '.../algo-trade-hub-2026-09-25-vps-deploy/Dockerfile'
FAILED tests/test_repo_layout.py::test_dockerfile_and_dockerignore - FileNotF...
1 failed in 0.06s
```

### GREEN (layout tests)

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest tests/test_repo_layout.py -q
...................                                                      [100%]
19 passed in 0.34s
```

### Frontend lockfile sync (Step 3a) — only the lockfile was regenerated, no packages upgraded

```
$ (cd market_sentiment_tool && npm install --package-lock-only --no-audit --no-fund)
up to date in 1s
```

```
$ (cd market_sentiment_tool && npm ci --dry-run --no-audit --no-fund >/dev/null && echo "lockfile in sync")
lockfile in sync
```

`market_sentiment_tool/package.json` was **not** touched; only `package-lock.json` changed
(`354 insertions(+), 69 deletions(-)`). The drift is exactly the one the plan describes — the committed
lockfile carried `eslint@10.0.1`, which does not satisfy the `^9.39.0` range in `package.json`, so
`npm ci` failed with `EUSAGE`. Regenerating restored the whole eslint toolchain to in-range versions:

| package | before | after |
|---|---|---|
| `eslint` | 10.0.1 | **9.39.5** (down, back inside `^9.39.0`) |
| `@eslint/js` | 9.32.0 | 9.39.5 |
| `@eslint/config-array` | 0.23.2 | 0.21.2 |
| `@eslint/config-helpers` | 0.5.2 | 0.4.2 |
| `@eslint/core` | 1.1.0 | 0.17.0 |
| `@eslint/object-schema` | 3.0.2 | 2.1.7 |
| `@eslint/plugin-kit` | 0.6.0 | 0.4.1 |
| `eslint-scope` | 9.1.1 | 8.4.0 |
| `espree` | 11.1.1 | 10.4.0 |

Every other added/removed entry is an eslint transitive dependency. **No runtime dependency
(`dependencies` block) version changed** — the change is confined to lint/dev tooling, so it is a
correction, not an upgrade.

`npm ci` now installs cleanly from the regenerated lockfile:

```
$ (cd market_sentiment_tool && npm ci --no-audit --no-fund)
added 530 packages in 9s
npm ci exit=0
```

### Frontend build and test suite (required for this task because it touches `market_sentiment_tool`)

```
$ (cd market_sentiment_tool && npm run build)
> vite_react_shadcn_ts@0.0.0 build
> vite build
vite v5.4.21 building for production...
✓ 2451 modules transformed.
dist/index.html                   1.13 kB │ gzip:   0.48 kB
dist/assets/index-Bw0lLs-p.css   71.39 kB │ gzip:  12.51 kB
dist/assets/index-DD4TNtOS.js   828.05 kB │ gzip: 232.28 kB
✓ built in 4.20s
```

```
$ (cd market_sentiment_tool && npm test)     # repository script is `vitest run`
> vitest run
 RUN  v3.2.4 .../market_sentiment_tool
 ✓ src/test/example.test.ts (1 test) 1ms
 ✓ src/lib/shadowPerformance.test.ts (4 tests) 2ms
 ✓ src/lib/edgeGate.test.ts (3 tests) 2ms
 Test Files  3 passed (3)
      Tests  8 passed (8)
   Duration  1.34s
```

### Real Docker build and image smoke checks (Step 4) — all run, nothing simulated

```
$ docker build -t tradehub:local .
...
#19 17.14 dist/index.html                   1.13 kB │ gzip:   0.48 kB
#19 17.14 dist/assets/index-Bw0lLs-p.css   71.39 kB │ gzip:  12.51 kB
#19 17.14 dist/assets/index-DD4TNtOS.js   828.05 kB │ gzip: 232.28 kB
#19 DONE 17.5s
#21 [stage-1 9/9] COPY --from=frontend-build /app/market_sentiment_tool/dist ./market_sentiment_tool/dist
#22 DONE 9.2s
 2 warnings found (use docker --debug to expand):
 - SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data (ARG "VITE_SUPABASE_PUBLISHABLE_KEY") (line 9)
 - SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data (ENV "VITE_SUPABASE_PUBLISHABLE_KEY") (line 10)
```

The two build warnings are expected and accepted: the Supabase **publishable** key is a public,
browser-side value by design (the runtime secret `SUPABASE_SERVICE_ROLE_KEY` is never a build arg
and never enters the image). No source change was made for them.

```
$ docker images tradehub:local --format '{{.Size}}'
889MB

$ docker run --rm tradehub:local python -c "import tradehub.api.main, tradehub.scripts.scan, tradehub.scripts.settle_predictions; print('imports ok')"
imports ok

$ docker run --rm tradehub:local sh -c "python -c 'import importlib.util as u; print(\"torch present:\", u.find_spec(\"torch\") is not None)'"
torch present: False

$ docker run --rm tradehub:local sh -c "ls -a /app; ls /app/market_sentiment_tool/dist | head -3; ls /app/.env /app/*.pem /app/models 2>&1 | head -3"
.
..
market_sentiment_tool
pyproject.toml
shared
tradehub
assets
favicon.ico
index.html
ls: cannot access '/app/.env': No such file or directory
ls: cannot access '/app/*.pem': No such file or directory
ls: cannot access '/app/models': No such file or directory
```

Runtime smoke test (Task 1's mount and endpoint verified inside the real image):

```
$ docker run --rm -d -p 8000:8000 --name tradehub-smoke tradehub:local && sleep 6 && \
  curl -s localhost:8000/api/health | head -c 200 && echo && \
  curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/shadow && \
  curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/api/missing && \
  curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/api/track-record && \
  docker stats --no-stream --format '{{.Name}} {{.MemUsage}}' tradehub-smoke
{"status":"ok","timestamp":"2026-09-25T19:49:37.823641Z","version":"1.0.0"}
200        # /shadow          → SPA fallback
404        # /api/missing     → 404 JSON, never the SPA
503        # /api/track-record → 503, Supabase unset in the container
tradehub-smoke 100.7MiB / 7.748GiB
container removed
```

Every plan expectation is met: 889 MB image (plan: ~0.9 GB), `imports ok`, `dist` present with
`index.html`/`assets`, no `.env`/`*.pem`/`models`, no `torch`, `/api/health` JSON, `/shadow` 200,
and ~100 MB idle memory (well under the 700 MB `mem_limit` in `vps-stack`).

### Regression check

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
345 → 346 passed in 3.88s
```

(346 = 345 + the new `test_dockerfile_and_dockerignore`. Note that after `npm run build` a local
`market_sentiment_tool/dist/` now exists, so `mount_frontend` is active during local pytest runs;
the full suite still passes, which additionally exercises the mounted SPA path. `dist/` and
`node_modules/` are gitignored and are not part of any commit.)

### Implementation summary

- `Dockerfile`: two stages. Stage 1 (`node:20-slim`) does `npm ci` from the regenerated lockfile and
  `npm run build` with `VITE_SUPABASE_URL` / `VITE_SUPABASE_PUBLISHABLE_KEY` as build args and
  `VITE_API_BASE_URL=""` (same-origin API). Stage 2 (`python:3.12-slim`) installs only
  `pyproject.toml` — **no `scanner` extra, so no torch/transformers** — sets `PYTHONPATH=/app` so
  `python -m tradehub.scripts.scan` / `...settle_predictions` work as the systemd job commands, and
  copies the built `dist` to `/app/market_sentiment_tool/dist`. `CMD` runs
  `uvicorn tradehub.api.main:app` on `${PORT:-8000}`.
- `.dockerignore`: excludes `.env*`, `*.pem`, `*.key`, `_attic`, `.venv*`, `node_modules`, `models`,
  `*.pkl`, plus caches, `docs`, `archive`, `research` and the local `dist`/chroma/sqlite artifacts.

**Commit:** `build: add multi-stage image for API, War Room and scheduled jobs; sync frontend lockfile`
