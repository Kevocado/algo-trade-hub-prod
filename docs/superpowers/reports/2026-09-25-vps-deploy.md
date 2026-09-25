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
