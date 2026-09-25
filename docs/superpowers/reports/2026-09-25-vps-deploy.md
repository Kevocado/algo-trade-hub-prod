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

## Task 3 — Build + deploy workflow (`.github/workflows/deploy-tradehub.yml`)

**Files:** created `.github/workflows/deploy-tradehub.yml`; modified `tests/test_repo_layout.py`
(appended `test_deploy_workflow_builds_then_deploys_to_vps`). No deviation from the brief: the
supplied workflow applied verbatim.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py::test_deploy_workflow_builds_then_deploys_to_vps -q
        path = REPO / ".github/workflows/deploy-tradehub.yml"
>       assert path.is_file(), "deploy workflow missing"
E       AssertionError: deploy workflow missing
tests/test_repo_layout.py:205: AssertionError
FAILED tests/test_repo_layout.py::test_deploy_workflow_builds_then_deploys_to_vps
1 failed in 0.08s
```

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest tests/test_repo_layout.py -q
....................                                                     [100%]
20 passed in 0.41s
```

### actionlint — actually run (via the plan's Docker command)

`actionlint` is not installed as a host binary, but Docker is available, so the plan's own
container-based command was executed for real — this is not a substitute or an assumed result:

```
$ docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -shellcheck= .github/workflows/deploy-tradehub.yml
actionlint ok
```

No findings, exit 0.

### Azure check (Kevin's ruling: the workflow must contain no Azure references)

The test asserts the absence of `az login`, `containerapp` and `AZURE_`. A broader case-insensitive
sweep was run as well:

```
$ grep -in "azure\|az login\|containerapp\|ACR_\|ARM_" .github/workflows/deploy-tradehub.yml
(no output; grep exit 1)
```

The workflow contains no Azure reference of any kind.

### Regression check

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
346 → 347 passed in 4.89s

$ .../.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests shared
All checks passed!
```

### Implementation summary

- `.github/workflows/deploy-tradehub.yml` — the first root-level workflow in this repo, three jobs in
  a strict chain enforced by `needs`:
  1. `test` — checkout, Python 3.12, `uv pip install --system -r pyproject.toml --extra dev --extra scanner`
     (the scanner extra is needed for the test suite only; it is deliberately **not** in the image),
     then `python -m pytest -q` with `SUPABASE_SERVICE_ROLE_KEY: dummy-baseline-placeholder`;
  2. `build` — `needs: test`, GHCR login with `GHCR_PAT`, `docker build` with the two public Vite build
     args, pushing both `$IMAGE:${{ github.sha }}` (full 40-char sha, which `bin/deploy` requires) and
     `$IMAGE:latest`;
  3. `vps` — `needs: build`, `if: vars.VPS_HOST != ''`, `concurrency: vps-deploy-tradehub`, writes
     `VPS_SSH_KEY` / `VPS_KNOWN_HOSTS` to `~/.ssh` and runs exactly
     `ssh deploy@${{ vars.VPS_HOST }} deploy tradehub ${{ github.sha }}` (the VPS key's forced command
     only permits `/opt/stack/bin/deploy`).
- `permissions`: `contents: read`, `packages: write` — the minimum needed.
- `env.IMAGE: ghcr.io/kevocado/tradehub` at workflow level, reused by the build job.
- Triggers: `push` to `main` filtered to the app paths plus `Dockerfile`/`.dockerignore`/the workflow
  itself, and `workflow_dispatch` for Kevin's manual first deploy (Task 5).

**Commit:** `ci: build the trade hub image and deploy it to the VPS`

## Task 4 — Retire the PM2 processes + document the VPS deployment

**Files:** deleted `Procfile` and `ecosystem.config.js` (`git rm`; git history keeps them, and
`_attic/` is gitignored so a move there would not survive a fresh checkout); modified
`README.md`, `SYSTEM_ARCH.md`, `shared/config.py`, `shared/fast_scanner.py`,
`shared/background_scanner.py` (docstrings only) and
`docs/superpowers/plans/2026-09-24-rollout-tracker.md`; appended
`test_pm2_process_files_are_retired` to `tests/test_repo_layout.py`.
No deviation from the brief: every specified edit applied as written.

### RED

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py::test_pm2_process_files_are_retired -q
>       assert not (REPO / "Procfile").exists()
E       AssertionError: assert not True
E        +  where True = exists()
tests/test_repo_layout.py:225: AssertionError
FAILED tests/test_repo_layout.py::test_pm2_process_files_are_retired
1 failed in 0.05s
```

### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest tests/test_repo_layout.py -q
.....................                                                    [100%]
21 passed in 0.46s
```

### The plan's required grep — one honest deviation

The plan's verification command is:

```
$ grep -rn 'ecosystem.config.js\|Procfile' --include='*.md' --include='*.py' . \
    | grep -v -e _attic -e docs/superpowers -e node_modules -e tests/test_repo_layout.py
```

It does print lines — but **only** from `.superpowers/sdd/2026-09-25-vps-deploy/plan.md` and the
`task-*-brief.md` files, i.e. the plan and briefs themselves, which quote the old filenames in
their own instructions. Those files are not part of the repository: `git check-ignore -v` reports
they are ignored by `.superpowers/sdd/.gitignore` (`*`), and `git ls-files .superpowers` is empty, so
they can never enter a commit. The plan's filter list predates the existence of the SDD ledger
directory and does not exclude it.

The equivalent check over **tracked** files — the real intent, "no live reference remains in the repo" —
is clean:

```
$ git ls-files '*.md' '*.py' | grep -v -e '^docs/superpowers/' -e '^tests/test_repo_layout.py$' \
    | while read -r f; do grep -l -e 'ecosystem\.config\.js' -e 'Procfile' "$f" >/dev/null 2>&1 && echo "HIT: $f"; done
(no output — no tracked live reference)

$ grep -rln 'ecosystem.config\.js\|Procfile' --include='*.md' --include='*.py' . \
    | grep -v -e '^\./\.superpowers/' -e node_modules -e '^\./docs/superpowers' -e '^\./tests/test_repo_layout.py'
(no output — clean)
```

No source file was changed to satisfy this; the exclusion of the SDD ledger is a property of the
working copy, not an edit.

### Residual "PM2" strings outside this task's scope (recorded, not touched)

A case-insensitive sweep for `pm2` over tracked `*.md`/`*.py` leaves only:

- `README.md:84` — the new sentence written by this task ("their old PM2 files are in git history").
- `archive/legacy/root/STATE.md` (3 lines) — deliberately archived historical state notes, not
  instructions. Outside the plan's Task 4 file list.
- `market_sentiment_tool/backend/orchestrator.py:698` — an error-message string in the **parked**
  crypto orchestrator ("...into the PM2 interpreter environment"). Outside the plan's Task 4 file
  list, and not matched by the plan's grep (it names neither `Procfile` nor `ecosystem.config.js`).
- `tests/test_repo_layout.py` — the test that asserts the retirement.

Neither `archive/` nor `orchestrator.py` is in the plan's Task 4 file list, and both were left
untouched to keep this commit to the specified scope. Flagging them here so the reviewer can decide
whether a follow-up cleanup is wanted; neither affects the running system (the crypto orchestrator
is parked per spec §7, and no process config remains on disk).

### Regression check

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
347 → 348 passed in 4.47s

$ .../.venv/bin/python -m ruff check --select F401,F811,F821 tradehub tests shared
All checks passed!
```

### Implementation summary

- Deleted `Procfile` and `ecosystem.config.js` via `git rm` (their 5 PM2 apps — `api_server`,
  `mcp_server`, `orchestrator`, `scanner_slow`, `scanner_fast` — are all superseded: the API and SPA
  are now the image from Task 2, the scan/settle work is the hourly timers, and the crypto worker is
  parked).
- `README.md`: dropped `├── ecosystem.config.js # PM2 Orchestrator config` from the repo tree;
  deleted the whole `### Crypto Orchestrator VPS Runbook` section (the last section in the file),
  which held the `pm2 start` / `pm2 restart` instructions; appended the new `## VPS deployment`
  section with the container + `tradehub-scan.timer` (:05) + `tradehub-settle.timer` (:35) table, the
  push-to-`main` deploy path, the on-VPS operator commands, and the rollback command.
- `SYSTEM_ARCH.md`: line 13 now says the backend is "Scheduled as hourly systemd timers on the VPS
  (see README, VPS deployment)"; the `ecosystem.config.js` tree line is gone; the key-flow step 1 is
  now "The hourly `tradehub-scan` timer runs `python -m tradehub.scripts.scan` (weather + gas,
  suggest-only)."
- `shared/config.py`: "(with PYTHONPATH=. set in Procfile)" → "(with PYTHONPATH=. set)".
- `shared/fast_scanner.py`, `shared/background_scanner.py`: deleted the `Procfile: ...` docstring
  line each.
- `docs/superpowers/plans/2026-09-24-rollout-tracker.md`: the step 5 row now reads "VPS deploy: API +
  War Room container, hourly scan/settle timers (replaces the Azure plan) | ✅ implemented, pending
  Kevin's first deploy (Task 5)" pointing at this plan; the Step 7 scope line now uses the VPS
  predictor URLs instead of the Azure Container Apps hostname.

**Commit:** `docs: document the VPS deployment; retire the PM2 process files`

---

## Task 5 — First deploy: **Kevin's checklist, NOT executed**

The agent deliberately stopped after Task 4. Nothing below was run: no push, no PR, no merge, no
workflow run, no GitHub secrets/variables set, no SSH to the VPS, no Caddy edit, no timer enabled.
Every step below is **pending, for Kevin.**

### Step 1 — GitHub secrets (Kevin). ☐ PENDING
In `Kevocado/algo-trade-hub-prod`: secrets `GHCR_PAT` (same as the predictor repos),
`VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`. For `VPS_HOST`, `VPS_SSH_KEY`,
`VPS_KNOWN_HOSTS`, add `Kevocado/algo-trade-hub-prod` to the `REPOS` list in
`vps-stack/bin/set-github-secrets.sh` and re-run it.

### Step 2 — Apply migrations (Kevin). ☐ PENDING
Apply steps 2–4's migrations (`20260416000003`–`20260416000005`, plus the `signal_events` migration
noted in `task.md`) to Supabase before the first scan/settle run, otherwise the inserts fail.

### Step 3 — VPS env (Kevin). ☐ PENDING
Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `/opt/stack/.env`.

### Step 4 — First deploy (Kevin). ☐ PENDING
Merge to `main` and push, or run the workflow via "Run workflow". After the first push, make the
GHCR package public (github.com/users/Kevocado/packages/container/tradehub/settings → Change
visibility → Public), the same as the predictor images, so the VPS can pull it without a registry
login. Then re-run the `vps` job.

### Step 5 — Turn on HTTPS and the timers (Kevin, on the VPS). ☐ PENDING
**Only enable the timers after step 2b (promotion-gate fixes) is merged and deployed.** Until then,
run `/opt/stack/bin/tradehub-job scan` by hand if you want data.

First, as `deploy`, open `/opt/stack/Caddyfile` (`nano /opt/stack/Caddyfile`) and uncomment the four
lines of the `trade.{$DOMAIN}` block at the bottom (remove the leading `# `). Then:

```bash
# as deploy
docker compose -f /opt/stack/compose.yml restart caddy   # restart, not reload: editors can swap the file's inode under the bind mount
/opt/stack/bin/tradehub-job scan                                       # one manual run first
# as root
systemctl enable --now tradehub-scan.timer tradehub-settle.timer
```

Add a DNS A record for `trade.<domain>` if you don't use a wildcard record.

### Step 6 — Verify (the agent, read-only, after Kevin deploys). ☐ PENDING

```bash
ssh deploy@$VPS_HOST 'cd /opt/stack && docker compose --profile tradehub ps tradehub && systemctl list-timers "tradehub-*" && journalctl -u tradehub-scan.service -n 20 --no-pager && docker stats --no-stream'
curl -s https://trade.$DOMAIN/api/health
curl -s -o /dev/null -w '%{http_code}\n' https://trade.$DOMAIN/lab
```

Expected: `tradehub` running; both timers listed with a next run; a scan run that ends in success;
`/api/health` returns JSON; `/lab` returns 200 (the SPA); total memory under ~3 GB; new
`predictions` rows in Supabase.

---

## Final verification (after Task 4, whole branch at once)

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
348 passed in 4.62s                       # baseline 341 → +7 new tests, no regressions

$ /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m ruff check \
    --select F401,F811,F821 tradehub tests shared
All checks passed!

$ docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -shellcheck= \
    .github/workflows/deploy-tradehub.yml
actionlint ok

$ (cd market_sentiment_tool && npm run build)
✓ 2451 modules transformed.
✓ built in 3.65s

$ (cd market_sentiment_tool && npm test)
 Test Files  3 passed (3)
      Tests  8 passed (8)
```

New tests added by this plan, all of which were run RED before their implementation:

| Test | Task |
|---|---|
| `tests/test_api_frontend.py` (4 tests) | 1 |
| `test_dockerfile_and_dockerignore` | 2 |
| `test_deploy_workflow_builds_then_deploys_to_vps` | 3 |
| `test_pm2_process_files_are_retired` | 4 |

Review-focus checklist from the plan, all verified above:

- SPA fallback returns `index.html` for `/shadow`, `/api/missing` returns 404 JSON, never the SPA ✔
- `/api/track-record` returns 503 (not 500) when Supabase is unconfigured ✔
- Image contains no `.env`, `*.pem` or model files, and no `torch` ✔
- Deploy job only after `test` → `build` → `vps`, only when `VPS_HOST` is set, sends exactly
  `deploy tradehub <full sha>` ✔
- Nothing in the repo still tells a reader to run PM2 processes ✔ (see the residual-strings note in
  Task 4 for three archived/parked mentions outside this plan's scope)
- Workflow contains no Azure reference ✔

## What was deliberately NOT done

No push, no PR, no merge, no GitHub workflow run, no secrets or variables set, no SSH to the VPS, no
Caddy change, no timer enabled, no GitHub configuration touched, no subagents dispatched, no `.env`
edited, no dependency added, no history rewritten (no amend/reset/rebase/squash), and Task 5 was not
executed. The base `98432bc` was not changed.

### Clean no-cache image rebuild from the final tree (`tradehub:final`)

```
$ docker build --no-cache -t tradehub:final .
#21 naming to docker.io/library/tradehub:final done
#21 DONE 31.2s
 2 warnings found (use docker --debug to expand):
 - SecretsUsedInArgOrEnv: ... (ARG "VITE_SUPABASE_PUBLISHABLE_KEY") (line 9)
 - SecretsUsedInArgOrEnv: ... (ENV "VITE_SUPABASE_PUBLISHABLE_KEY") (line 10)

$ docker images tradehub:final --format '{{.Size}}'
889MB

$ docker run --rm tradehub:final python -c "import tradehub.api.main, tradehub.scripts.scan, tradehub.scripts.settle_predictions; print('imports ok')"
imports ok

$ docker run --rm tradehub:final sh -c "python -c '...find_spec(\"torch\")...'; ls /app/market_sentiment_tool/dist | head -3; ls /app/.env /app/*.pem /app/models 2>&1 | head -3"
torch present: False
assets
favicon.ico
index.html
ls: cannot access '/app/.env': No such file or directory
ls: cannot access '/app/*.pem': No such file or directory
ls: cannot access '/app/models': No such file or directory

$ docker run --rm -d -p 8001:8000 --name tradehub-final-smoke tradehub:final && sleep 6 && ...
$ curl -s localhost:8001/api/health
{"status":"ok","timestamp":"2026-09-25T19:55:30.582995Z","version":"1.0.0"}
shadow=200
api-missing=404
track-record=503
lab=200
tradehub-final-smoke 100.5MiB / 7.748GiB
container removed
```

The final tree builds reproducibly from scratch, and the Task 1 behaviours (SPA fallback on
`/shadow` and `/lab`, 404 JSON for unknown `/api/...`, 503 for an unconfigured Supabase) all hold in
the real image at 889 MB with ~100 MB idle memory.
