# VPS Deploy — evidence report

**Plan:** [docs/superpowers/plans/2026-09-25-vps-deploy.md](../plans/2026-09-25-vps-deploy.md)
**Branch:** `plan/2026-09-25-vps-deploy`
**Base:** `98432bc` (Claude's reconciled PR #4 head; PR #4 is still open and was explicitly authorised as the starting point)
**Tasks implemented here:** 1–4. Task 5 is Kevin's operational checklist — recorded below, **not executed**.

Every pytest run is prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder` and uses
`/Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python`.

## Merge notes — this branch vs. `plan/2026-09-25-docs-vps-and-gate`

This branch **starts from Claude's PR #4 head `98432bc`**, not from `origin/main` and not from the
sibling docs branch. The plan document and the docs that accompany it were authored on the sibling
branch:

- **Commit `59b4062`** ("docs: VPS deploy plan replaces Azure; add step 2b gate-hardening plan") on
  branch **`plan/2026-09-25-docs-vps-and-gate`** adds
  `docs/superpowers/plans/2026-09-25-vps-deploy.md` (670 lines),
  `docs/superpowers/plans/2026-09-25-gate-hardening.md`, the **Azure superseded banner** at the top
  of `docs/superpowers/plans/2026-09-24-azure-deploy.md`, and the tracker/spec updates.
- **`59b4062` is not an ancestor of this branch** (`git merge-base --is-ancestor 59b4062
  plan/2026-09-25-vps-deploy` → false). The two branches diverged at `8ebf0f4`: the docs branch is
  one commit on top of the PR #2 merge (`b6c4f8e`), while this branch is on top of the ~70 PR #3/#4
  commits that end at `98432bc`.
- The **tracker Step 5 section header** — `## Step 5 — Deploy (now the VPS plan,
  2026-09-25-vps-deploy.md; original Azure scope notes below, kept for history)` — also lives only
  on the docs branch. This branch still carries the old `## Step 5 — Azure deploy (planned:
  2026-09-24-azure-deploy.md; …)` header. It is a line this branch never touched, so Git applies the
  docs branch's version without a conflict, but a human should confirm the merged file reads
  correctly.
- The Azure superseded banner likewise arrives with `59b4062`; see Task 4's residual inventory for
  why no source change was made for it here.
- **This branch now carries a byte-identical copy of the plan file**
  (`docs/superpowers/plans/2026-09-25-vps-deploy.md`, sha256
  `ad7b118d6c862334d7179afe0e2a01d694812178f3e020e2f275951d012bfa77`, identical to the source
  `.superpowers/sdd/2026-09-25-vps-deploy/plan.md` and to `59b4062`'s blob) so the tracker's step 5
  row and this report's header link resolve on this branch in isolation.

### Expected conflicts, for manual merge reconciliation

Only `docs/superpowers/plans/2026-09-24-rollout-tracker.md` conflicts. Both branches edited the same
two regions; `git merge-tree 8ebf0f4 59b4062 plan/2026-09-25-vps-deploy` (read-only) shows exactly
two `<<<<<<<` hunks, at the status table and at the Step 7 scope bullet:

1. **Status table, step rows 2–5.** The docs branch rewrote rows 2/2b/3/4/5 (PR status, gate-hardening
   row, "supersedes the Azure plan" note); this branch rewrote only row 5. Take the docs branch's
   rows and keep **this branch's row 5 status cell** — `✅ implemented, pending Kevin's first deploy
   (Task 5)` — because Tasks 1–4 are now actually done. Its "What"/"Plan" cells are identical in
   both sides apart from the "(supersedes …)" parenthetical, which the docs branch has.
2. **Step 7 scope bullet.** Both branches replaced the Azure `*.azurecontainerapps.io` URLs with the
   VPS URLs, in slightly different wording. Both are semantically equivalent; pick one (the docs
   branch's is the more explicit — it says the Azure URLs "go away with the cutover").

`docs/superpowers/plans/2026-09-25-vps-deploy.md` is an add/add on both sides, but because the two
blobs are **byte-identical** Git's `ort` strategy resolves it silently and it is **not** a conflict
(verified twice: by the matching sha256 above, and by a scratch-repo `add/add` merge with identical
blobs, which reported "Merge made by the 'ort' strategy" with a clean `git status`).

Also expect a benign one-sided change: this branch leaves the tracker's "Implementation order" line
and its Step 5 validation bullets at their `98432bc` text, while the docs branch rewrote them
(including the "Step 5 (VPS), validated 2026-09-25" bullet). No conflict is possible, because this
branch never edited those lines — but the merged tracker's step 5 status and the validation bullets
should be read together once, since both branches now describe the same plan from different angles.

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
| `actionlint` | **not installed as a host binary** (`command not found`); the plan's own container-based command was used instead and **passed** — see Task 3, "actionlint — actually run" |
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

### Complete residual PM2 / `Procfile` / `ecosystem.config.js` inventory (recorded, not touched)

The first version of this section claimed a "case-insensitive sweep for `pm2` over tracked
`*.md`/`*.py`" left only four files. **That claim was wrong**: the sweep was restricted to `*.md`
and `*.py`, so it could not see a `.json` file, and its result list also omitted the `.md` files
that do contain the strings. The sweep below is over **every tracked file** and every one of the
three tokens, and its result is the complete inventory:

```
$ git ls-files -z | xargs -0 grep -inE '(^|[^A-Za-z0-9+/=_-])(pm2|Procfile|ecosystem\.config)' \
    | grep -viE '\.ipynb:'
 35 docs/superpowers/reports/2026-09-25-vps-deploy.md      # this report (incl. the section below)
 20 docs/superpowers/plans/2026-09-25-vps-deploy.md        # this plan's retirement requirements
 11 docs/superpowers/plans/2026-09-24-azure-deploy.md      # superseded plan
  3 tests/test_repo_layout.py                             # the test asserting the retirement
  3 archive/legacy/root/STATE.md                          # archived historical state notes
  1 README.md                                             # the sentence this task wrote
  1 market_sentiment_tool/backend/orchestrator.py         # parked worker, error-message string
  1 docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md
  1 docs/superpowers/plans/2026-09-24-rollout-tracker.md
  1 docs/superpowers/plans/2026-09-24-repo-cleanup.md
  1 .agent/index/notes_manifest.json
```

(The two `research/quant_lab/*.ipynb` notebooks also match a naive substring search, but only as
`Pm2` inside base64 image payloads — e.g. `.../369e3cc8+1OXPm2J9/...`. The regex above requires a
non-base64 character before the token, which excludes them; they contain no real reference.)

| Tracked file | Lines | What it is | Why it is still there |
|---|---|---|---|
| `docs/superpowers/plans/2026-09-24-azure-deploy.md` | 58, 567, 572, 578–580, 591, 593, 597, 606, 664 | The **superseded** Azure plan. Line 58 and Step 3 (593–606) are *live-sounding* instructions: "Modify `Procfile` and `ecosystem.config.js` to keep only the crypto orchestrator", and they show the replacement contents. Line 572 says the VPS runs the orchestrator via `pm2 … --name crypto-sniper`. | **Marked superseded by `59b4062`** ("VPS deploy plan replaces Azure"), which adds the banner *"Superseded 2026-09-25 by 2026-09-25-vps-deploy.md … Don't implement this plan. Its Tasks 1–2 are carried over word for word."* The live instruction is therefore **not to implement it**, and **no source change is needed on this branch** — the banner arrives with the sibling docs branch (see "Merge notes"). Touching the plan from here would duplicate that commit and collide with it. |
| `docs/superpowers/plans/2026-09-25-vps-deploy.md` | 20 | The implementation plan whose requirements, tests and review focus name the retired files. | Current plan text, not a run instruction. It must stay in the tree so the tracker link resolves; no source change is needed. |
| `.agent/index/notes_manifest.json` | 201 | A generated index entry — the heading string `"Or launch as a background daemon using PM2:"`, captured from a `README.md` snapshot (`modified_utc: 2026-09-24T15:59:30Z`) that predates Task 4. | Not an instruction to anyone: it is a machine-generated index of a *past* heading, and the heading no longer exists in `README.md` (Task 4 deleted that section). It is outside the plan's Task 4 file list, so it was not regenerated. **It is stale** and should be regenerated by whatever re-indexes `.agent/`; flagging it for the reviewer rather than hand-editing a generated file. |
| `docs/superpowers/reports/2026-09-25-vps-deploy.md` | 19, incl. this section | **This report** — it names the retired files, the sweep, and the Task 5 checklist. | Unavoidable and correct: an evidence report has to name what it removed. These are descriptions of the retirement, not run instructions. |
| `docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md` | 116 | Spec line: "The VPS (`Procfile`, `ecosystem.config.js`, `requirements.vps.txt`) … **are retired**." | Already correct — it is the authority that says they are retired. The plan's handoff contract also forbids editing the spec. |
| `docs/superpowers/plans/2026-09-24-rollout-tracker.md` | 109 | Step 5 scope line: "Retire the VPS: `Procfile`, `ecosystem.config.js`, the VPS runbook section of `README.md`." | Correct as written — it is the instruction that was carried out by this commit. |
| `docs/superpowers/plans/2026-09-24-repo-cleanup.md` | 26 | Executed-plan line: "Don't touch `Procfile` or `ecosystem.config.js` (the VPS is retired in a later rollout step)". | Correct and historical — it records the scope constraint of step 1, which this task's later retirement then honoured. |
| `archive/legacy/root/STATE.md` | 11, 40, 48 | Archived state notes: the `ta`/`yfinance` **PM2 venv** requirements, the orchestrator booting "under PM2 as `crypto-sniper`", and a "restart PM2" deploy line. | Deliberately archived historical state, outside the plan's Task 4 file list. Not instructions; left untouched to keep the commit to the specified scope. |
| `market_sentiment_tool/backend/orchestrator.py` | 698 | An error-message string: "… into the PM2 interpreter environment." | The **parked** crypto orchestrator (spec §7). It is not matched by the plan's grep, which names neither `Procfile` nor `ecosystem.config.js`, and it is outside the Task 4 file list. It affects no running system. |
| `README.md` | 84 | "their old PM2 files are in git history (removed in this commit)". | The sentence this task wrote; it is the replacement text, not an instruction. |
| `tests/test_repo_layout.py` | 3 | `test_pm2_process_files_are_retired` and its assertion strings. | The regression test that keeps them retired. |

**Corrected completeness claim.** The earlier wording — "Nothing in the repo still tells a reader to
run PM2 processes ✔" — overstated what was checked. What is actually true: **no tracked file that is
still *current* guidance tells a reader to run a PM2 process.** The exceptions are all historical or
inert: the superseded Azure plan (which now carries a "don't implement this" banner, from the sibling
docs branch), a stale generated index heading, an archived state file, a parked worker's error string,
and the descriptions/assertions in the spec, tracker, report and test. None of them is a live
deployment instruction, and no PM2 process config remains on disk.

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
- Nothing that is still *current* guidance tells a reader to run a PM2 process ✔ (the complete
  all-files inventory, including the superseded Azure plan and one stale generated index heading,
  is in Task 4's residual-inventory table — it supersedes the narrower claim made in the first
  version of this report)
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

---

## Review fix round 1

Four approved findings (F1–F4) were fixed. F5–F11 were **not** implemented — they remain open for
the reviewer. Everything below was actually run; no result is assumed.

### F1 — `.dockerignore` secret/model patterns were root-anchored (TDD)

Docker matches `.dockerignore` patterns against the context-root-relative path, so the plan's
`*.pem`, `*.key`, `models`, `model`, `*.pkl` only excluded the **top level**. A nested
`subdir/keys/private.pem`, `subdir/.env` or `subdir/models/` would still be sent to the daemon in the
build context. The existing `**/node_modules`, `**/__pycache__` and `**/.pytest_cache` lines show the
intent was per-depth; the secret/model block just never got the same treatment.

**Files changed:** `tests/test_repo_layout.py` (assertions appended to
`test_dockerfile_and_dockerignore`), `.dockerignore`. `Dockerfile` and
`market_sentiment_tool/package-lock.json` were **not** touched.

#### RED — assertions first, run before touching `.dockerignore`

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py::test_dockerfile_and_dockerignore -q
    for pattern in ("**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/models", "**/model", "**/*.pkl"):
>           assert pattern in ignore, f".dockerignore must exclude {pattern} at any depth"
E           AssertionError: .dockerignore must exclude **/.env at any depth
E           assert '**/.env' in ['.git', '.github', '.venv', '.venv-*', '**/node_modules', '**/__pycache__', ...]
tests/test_repo_layout.py:203: AssertionError
1 failed in 0.06s
```

#### GREEN

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py::test_dockerfile_and_dockerignore -q
.                                                                        [100%]
1 passed in 0.01s
```

The plan's original token assertions (`.env`, `.env.*`, `*.pem`, `*.key`, `_attic`, `.venv`,
`**/node_modules`, `models`, `*.pkl`) are still present and still pass: every root-anchored line was
**kept**, and the seven `**/`-prefixed lines were **added** below them.

#### Proof the fix is real, not just a string match

A throwaway context directory was built with the committed `.dockerignore` vs. the fixed one,
containing `root.pem`, `sub/keys/private.pem`, `sub/.env`, `sub/deep/.env.prod`, `sub/models/` and
`sub/model/`, and an `alpine` Dockerfile that `COPY . /ctx` then lists:

```
=== BEFORE the fix (git show HEAD:.dockerignore) ===
/ctx/.dockerignore
/ctx/Dockerfile
/ctx/sub/.env
/ctx/sub/deep/.env.prod
/ctx/sub/keys/private.pem
/ctx/sub/model/thing.pkl
/ctx/sub/models/weights.pkl

=== AFTER the fix (working tree .dockerignore) ===
/ctx/.dockerignore
/ctx/Dockerfile
```

Five secret/model paths in the context before (the root `root.pem` and root `.env` were already
excluded by the original root-anchored lines, so only the nested ones leaked), zero after. The probe
directory was deleted; no scratch file remains in the repo.

The real image still builds and still imports with the stricter ignore file, so nothing needed by the
build was over-excluded:

```
$ docker build --no-cache -t tradehub:reviewfix .
 2 warnings found (use docker --debug to expand):
  - SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data (ENV "VITE_SUPABASE_PUBLISHABLE_KEY") (line 10)
  - SecretsUsedInArgOrEnv: Do not use ARG or ENV instructions for sensitive data (ARG "VITE_SUPABASE_PUBLISHABLE_KEY") (line 9)

$ docker images tradehub:reviewfix --format '{{.Size}}'
889MB

$ docker run --rm tradehub:reviewfix python -c "import tradehub.api.main, tradehub.scripts.scan, tradehub.scripts.settle_predictions; print('imports ok')"
imports ok
```

Same 889 MB, same two expected publishable-key warnings as the original build. The probe directory
was deleted; no scratch file remains in the repo.

### F2 — the tracker row and this report linked a plan file that was not on this branch

`docs/superpowers/plans/2026-09-25-vps-deploy.md` did not exist on this branch, so the step 5 row in
`docs/superpowers/plans/2026-09-24-rollout-tracker.md:15` and the **Plan:** line at the top of this
report were both dead links. The file is now added as a **byte-identical** copy of the source plan:

```
$ cp .superpowers/sdd/2026-09-25-vps-deploy/plan.md docs/superpowers/plans/2026-09-25-vps-deploy.md
$ shasum -a 256 .superpowers/sdd/2026-09-25-vps-deploy/plan.md \
                   docs/superpowers/plans/2026-09-25-vps-deploy.md
ad7b118d6c862334d7179afe0e2a01d694812178f3e020e2f275951d012bfa77  .superpowers/sdd/2026-09-25-vps-deploy/plan.md
ad7b118d6c862334d7179afe0e2a01d694812178f3e020e2f275951d012bfa77  docs/superpowers/plans/2026-09-25-vps-deploy.md

$ git show 59b4062:docs/superpowers/plans/2026-09-25-vps-deploy.md | shasum -a 256
ad7b118d6c862334d7179afe0e2a01d694812178f3e020e2f275951d012bfa77  -
```

All three agree, so the copy matches both the working-copy source and the blob on the sibling docs
branch, and the links now resolve on this branch in isolation.

A **"Merge notes"** section was added near the top of this report. It records commit **`59b4062`** on
branch **`plan/2026-09-25-docs-vps-and-gate`**; that this branch starts from **Claude's PR #4 head
`98432bc`**; that `59b4062` is *not* an ancestor of this branch (merge base `8ebf0f4`); and that the
sibling docs branch carries both the **Azure superseded banner** and the **tracker Step 5 section
header** (`## Step 5 — Deploy (now the VPS plan, …)`), neither of which is on this branch. The
expected conflicts for manual reconciliation are enumerated there and were verified with the
read-only `git merge-tree`: **two** hunks in
`docs/superpowers/plans/2026-09-24-rollout-tracker.md` (the step 2–5 status table, and the Step 7
scope bullet), with the recommended resolution for each, plus the one-sided tracker lines that need a
human read. The identical add/add of the plan file is **not** a conflict — verified by matching
sha256 and by a scratch-repo `add/add` merge of identical blobs, which reported
`Merge made by the 'ort' strategy` with a clean `git status`.

### F3 — the actionlint line contradicted Task 3

The "Tool availability" table said the actionlint check "is therefore reported as not run, and the
Docker-based actionlint container was not used". That was false: Task 3 ran the plan's own container
command and it passed. The row now reads that `actionlint` is **not installed as a host binary**, and
that the plan's container-based command was used instead and **passed** (pointing at Task 3). No
other claim was changed.

Re-run at this head, with the actual observed output recorded (actionlint prints nothing when clean):

```
$ docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -shellcheck= \
    .github/workflows/deploy-tradehub.yml
exit=0        # 0 bytes of output, i.e. no findings
```

The workflow file itself was not modified in this round. (Minor record note: the "actionlint ok"
string quoted in Task 3 and in the earlier "Final verification" block is an echo, not actionlint's
own output; the substantive claim — exit 0, no findings — is correct and re-confirmed above.)

### F4 — the residual PM2 / `Procfile` / `ecosystem.config.js` inventory was incomplete

The old section claimed a sweep over tracked `*.md`/`*.py` "leaves only" four files. That sweep
could not see `.json`, and its result list also omitted `.md` files that do contain the strings, so
the claim was both methodologically and factually wrong. It is replaced by a sweep over **every
tracked file** and all three tokens, with a per-file table covering:

- `docs/superpowers/plans/2026-09-24-azure-deploy.md` (11 lines) — **marked superseded by
  `59b4062`**, whose banner says "Don't implement this plan"; its live-looking Task 3 instructions
  to edit `Procfile`/`ecosystem.config.js` are therefore **not to be implemented**, and **no source
  change is needed on this branch** because the banner arrives with the sibling docs branch.
  Editing it here would duplicate `59b4062` and collide with it.
- `.agent/index/notes_manifest.json:201` — a **stale generated index heading**
  (`"Or launch as a background daemon using PM2:"`) captured from a `README.md` snapshot dated
  2026-09-24, i.e. before Task 4 deleted that section. Not an instruction; flagged for whoever
  re-indexes `.agent/` rather than hand-edited.
- `docs/superpowers/reports/2026-09-25-vps-deploy.md` — **this report**, which necessarily names the
  retired files.
- plus `docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md:116` (already says
  they are retired), `docs/superpowers/plans/2026-09-24-rollout-tracker.md:109` (the retirement
  instruction that was carried out), `docs/superpowers/plans/2026-09-24-repo-cleanup.md:26`
  (historical step-1 scope constraint), `archive/legacy/root/STATE.md` (3 archived lines),
  `market_sentiment_tool/backend/orchestrator.py:698` (error string in the parked worker),
  `README.md:84` (the sentence Task 4 wrote) and `tests/test_repo_layout.py` (the regression test).
- The two `research/quant_lab/*.ipynb` hits are noted and explained as `Pm2` inside base64 image
  payloads, not references.

The overstated "Nothing in the repo still tells a reader to run PM2 processes ✔" checklist bullet was
replaced with the accurate, narrower claim: **no tracked file that is still current guidance tells a
reader to run a PM2 process**; every exception is historical, inert, or superseded, and no PM2
process config remains on disk. No source file was changed to satisfy F4 — it is a report correction
only.

### Verification at this head

```
$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest \
  tests/test_repo_layout.py -q
.....................                                                    [100%]
21 passed in 0.39s

$ SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder \
  /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m pytest -q
348 passed in 4.90s

$ /Users/sigey/Documents/Projects.nosync/algo-trade-hub-prod/.venv/bin/python -m ruff check \
    --select F401,F811,F821 tradehub tests shared
All checks passed!

$ docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -shellcheck= \
    .github/workflows/deploy-tradehub.yml
exit=0

$ docker build --no-cache -t tradehub:reviewfix . && docker images tradehub:reviewfix --format '{{.Size}}'
889MB
```

**Test counts are unchanged from the previous round: 348 full, 21 in `tests/test_repo_layout.py`.**
No test was added or removed in this round — F1 appended assertions to an existing test, so the RED
for `test_dockerfile_and_dockerignore` is an assertion failure inside an already-counted test, not a
new test id. There are no regressions against the 348 recorded at `9531b94` and no regressions
against the 341 baseline. Ruff stays clean over `tradehub tests shared`.

### Not done in this round

F5–F11 are **not** implemented. Also not done: no push, no PR, no merge, no workflow run, no secrets
or variables set, no SSH to the VPS, no GitHub configuration change, no subagents dispatched, no
`.env` read or written, no history rewritten (no amend/reset/rebase/squash), and no other worktree,
branch or file touched. `Dockerfile`, `market_sentiment_tool/package-lock.json`, the workflow and
every source file are byte-identical to `9531b94`; the only changes in this round are
`.dockerignore`, `tests/test_repo_layout.py`,
`docs/superpowers/plans/2026-09-25-vps-deploy.md` (new, byte-identical copy) and this report.

## Controller handover — direct review after Claude capacity was exhausted

Kevin reported that no Claude subagent capacity remained on 2026-09-25. The remaining review was
therefore completed inline by the controller against the plan, this report, the handoff contract,
`git diff --check`, and the post-#4 `main`; no further reviewer subagents were dispatched.

### Handover checks

- PR #4 merged as `7e4ca68`; this branch's base `98432bc` is its ancestor, so PR #6 is reported
  mergeable and clean against the current `origin/main`.
- Re-run `npm run build`, vitest, scoped Ruff, actionlint and the container smoke checks after any
  review fix. The last verified values are: 348 Python tests, 8 vitest tests, successful Vite
  build, zero `F401,F811,F821` findings, actionlint exit 0, 889 MB image, ~100 MB idle.
- The nested secret/model exclusions in `.dockerignore` are behaviorally verified: a throwaway
  Docker context admitted five nested sensitive paths before the fix and zero after.
- The sibling docs commit `59b4062` is still not an ancestor. The exact plan file is included here,
  so links resolve, but the two rollout-tracker conflicts documented in "Merge notes" still need
  human reconciliation if that docs branch is merged later.
- Task 5 remains entirely pending for Kevin: secrets, migrations, VPS environment, first deploy,
  Caddy/DNS and timer enablement were not performed. Do not enable timers until step 2b is merged
  and deployed.
- F5–F11 remain deferred follow-ups. Do not fold them into this plan without a recorded ruling.
- Wave B may start only after PR #5 merges. Step 7b and step 8 remain gated by the plan's stated
  prerequisites; do not start them from this branch.
