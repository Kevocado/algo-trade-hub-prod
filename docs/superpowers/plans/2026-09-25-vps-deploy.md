# VPS Deploy (replaces the Azure plan for rollout step 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the trade hub on the VPS (OVHcloud VPS-1) that already hosts the five predictor sites: the API + War Room as one container behind Caddy at `trade.$DOMAIN`, and the hourly `scan` and `settle` jobs as systemd timers that run the same image.

**Why this replaces [2026-09-24-azure-deploy.md](2026-09-24-azure-deploy.md):** the Azure for Students credit ends around 2026-10-27, and every predictor is moving to one ~$5/month OVHcloud x86 VPS (4 GB) managed by the `vps-stack` folder (`/Users/sigey/Documents/Projects.nosync/vps-stack`, deployed to `/opt/stack`). Tasks 1 and 2 of the Azure plan never depended on Azure and are carried over **word for word**. Tasks 3–5 replace the Azure workflow, the VPS trim and the Azure first-deploy checklist.

**Architecture:**
- **One Docker image** (`ghcr.io/kevocado/tradehub`, multi-stage: Vite build, then Python 3.12 slim from `pyproject.toml`, *without* the `scanner` extra, so no torch/transformers) serves the API + SPA and runs the two batch jobs.
- **`vps-stack` already contains** everything on the server side, verified 2026-09-25:
  - `compose.yml` service `tradehub` under the `tradehub` profile (off until this plan lands), `mem_limit: 700m`, env `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` from `/opt/stack/.env`;
  - `bin/deploy deploy tradehub <sha>`: pulls, restarts, health-checks `GET /api/health` on port 8000, and rolls back on failure;
  - `bin/tradehub-job scan|settle` runs `python -m tradehub.scripts.scan` / `tradehub.scripts.settle_predictions` in a throwaway container;
  - `systemd/tradehub-scan.timer` (hourly at :05) and `tradehub-settle.timer` (hourly at :35), installed by `bin/bootstrap.sh` but **not enabled**;
  - a commented-out `trade.{$DOMAIN}` block in the `Caddyfile`.
- **This repo gains** a root workflow that tests, builds and pushes the image, then SSHes `deploy tradehub <sha>` to the VPS (the same pattern every predictor repo now uses).
- **No always-on trading processes.** Live execution and the crypto shadow worker stay parked (spec §7). The PM2 `Procfile`/`ecosystem.config.js` are deleted (they stay in git history).

**Tech Stack:** Docker (BuildKit), GitHub Actions, OpenSSH forced-command deploys, Docker Compose, Caddy 2, systemd timers, FastAPI/Starlette `StaticFiles`, `pytest`.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md) §5 (hosting; its "Azure, scale to zero" choice is superseded by this plan for cost reasons, the "no always-on compute for trading" intent is kept) and §7. Rollout step 5 in [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md).

## Global Constraints

- **Prerequisites:** steps 2, 3 and 4 are merged to `main`, plus the step 2b gate fixes before the timers are enabled (Task 5 Step 5): with an hourly scan, the step-2 gate would otherwise count ~24 rows per daily market. The jobs run `python -m tradehub.scripts.settle_predictions` (step 2) and `python -m tradehub.scripts.scan` (step 4).
- **VPS facts:** Ubuntu 26.04 (OVH image; `bootstrap.sh` falls back to Ubuntu's Docker packages on it), x86-64, stack at `/opt/stack`, user `deploy`, Caddy terminates HTTPS. GitHub Actions reaches it as `deploy@${{ vars.VPS_HOST }}` with the `VPS_SSH_KEY` / `VPS_KNOWN_HOSTS` secrets; that key can only run `/opt/stack/bin/deploy`.
- **Image name:** `ghcr.io/kevocado/tradehub`, tags `${{ github.sha }}` (full 40-char sha; `bin/deploy` rejects anything else) and `latest`.
- **Secrets never go into the image or the repo.** Runtime secrets live only in `/opt/stack/.env` on the VPS. The frontend's public Supabase URL and publishable key are **build args**, public by design. `.dockerignore` excludes `.env*`, `*.pem`, `*.key`, `_attic/`, `.venv*`, models, and `node_modules`.
- **Scan and settle use only public Kalshi endpoints,** so the only runtime secrets are `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. No Kalshi key goes to the VPS.
- **Memory budget:** the five predictors + Caddy use ~1.7 GB (measured 2026-09-25); the `tradehub` container is capped at 700 MB; a batch job adds one more short-lived container of similar size. Keep the `scanner` extra (torch) out of the image.
- **Never push, merge, or run the workflow on Kevin's behalf.** Secrets, the first deploy and enabling the timers are Kevin's actions (Task 5).
- **Test runs:** `.venv/bin/python` from the repo root, each pytest run prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Follow the handoff contract in the rollout tracker: branch `plan/2026-09-25-vps-deploy`, one commit per task, evidence report at `docs/superpowers/reports/2026-09-25-vps-deploy.md`.

## Validation already done (2026-09-25)

Tasks 1–4 were applied on top of PR #4's head (`31b66b1`):
- 287 tests pass, and `actionlint` is OK.
- `npm ci --dry-run` reports "lockfile in sync" after Step 3a.
- The image is 889 MB. It has no torch and no `/app/.env` or `/app/models`, and `imports ok` prints.
- In the container:
  - `/api/health` returns `{"status":"ok",...}`;
  - `/shadow` returns 200, `/api/missing` 404 and `/api/track-record` 503;
  - it idles at ~100 MB;
  - a full scan with stubbed Supabase writes took 3.5 s at a 126 MB peak, giving 24 weather predictions.
- Validation also fixed Task 4, which originally moved the PM2 files into `_attic/`. That fails on a fresh checkout, and `_attic/` is gitignored. The task now deletes the files and fixes every stale reference.

## Review Focus

- The SPA fallback returns `index.html` for client-side routes (`/lab`, `/shadow`), but an unknown `/api/...` path must still return 404 JSON, never the SPA. (Task 1)
- `/api/track-record` returns 503 (not 500) when Supabase isn't configured. (Task 1)
- The image contains no `.env`, `.pem`, or model files, and no `torch`. (Task 2: checked in the built image)
- The deploy job only runs after tests pass, only when `VPS_HOST` is set, and sends exactly `deploy tradehub <full sha>`. (Task 3)
- Nothing in the repo still tells a reader to run PM2 processes. (Task 4)

---

## File Structure

- **Create** `tradehub/api/frontend.py`: `SPAStaticFiles`, `mount_frontend(app, dist) -> bool`. (Task 1)
- **Modify** `tradehub/api/main.py`: add the `/api/track-record` endpoint and call `mount_frontend` last. (Task 1)
- **Create** `Dockerfile` and `.dockerignore` at the repo root. (Task 2)
- **Create** `.github/workflows/deploy-tradehub.yml` (the first root-level workflow in this repo). (Task 3)
- **Delete** `Procfile`, `ecosystem.config.js` (Task 4); fix the stale PM2 references in `README.md`, `SYSTEM_ARCH.md`, `shared/config.py`, `shared/fast_scanner.py`, `shared/background_scanner.py`.
- **Modify** `README.md` (a "VPS deployment" section replaces the PM2 instructions) and `docs/superpowers/plans/2026-09-24-rollout-tracker.md`. (Task 4)
- **Tests:** `tests/test_api_frontend.py`, plus assertions appended to `tests/test_repo_layout.py`.

---

## Task 1: Same-origin SPA mount + `/api/track-record`

**Files:**
- Create: `tradehub/api/frontend.py`
- Modify: `tradehub/api/main.py`
- Test: `tests/test_api_frontend.py`

**Interfaces:**
- Consumes: `tradehub.api.dependencies.get_supabase` (the existing lru-cached service-role client; returns `None` when not configured), and step 2's `track_record` table.
- Produces:
  - `mount_frontend(app: FastAPI, dist: Path) -> bool`: mounts `dist` at `/` with an index.html SPA fallback and returns `False` (mounting nothing) when `dist/index.html` is missing.
  - `GET /api/track-record`: returns the `track_record` rows ordered by `engine`, or 503 if Supabase is unavailable.
  - `FRONTEND_DIST` in `main.py`: the env var `FRONTEND_DIST`, defaulting to `<repo>/market_sentiment_tool/dist`.

- [ ] **Step 1: Write the failing tests** — `tests/test_api_frontend.py`:

```python
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tradehub.api.frontend import mount_frontend


def _dist(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>war room</html>")
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    return tmp_path


def test_mount_frontend_serves_files_and_spa_fallback(tmp_path):
    app = FastAPI()

    @app.get("/api/ping")
    def ping():
        return {"ok": True}

    assert mount_frontend(app, _dist(tmp_path)) is True
    client = TestClient(app)
    assert client.get("/api/ping").json() == {"ok": True}
    assert "war room" in client.get("/").text
    assert client.get("/assets/app.js").text == "console.log(1)"
    assert "war room" in client.get("/shadow").text          # client-side route
    assert client.get("/api/missing").status_code == 404     # never the SPA


def test_mount_frontend_skips_when_not_built(tmp_path):
    assert mount_frontend(FastAPI(), tmp_path) is False


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.ordered_by = None

    def select(self, *_args):
        return self

    def order(self, column, **_kwargs):
        self.ordered_by = column
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Supa:
    def __init__(self, rows):
        self.query = _Query(rows)

    def table(self, name):
        assert name == "track_record"
        return self.query


def test_track_record_endpoint_returns_rows():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    supa = _Supa([{"engine": "gas", "gate_status": "SHADOW"}, {"engine": "weather", "gate_status": "SHADOW"}])
    main.app.dependency_overrides[get_supabase] = lambda: supa
    try:
        response = TestClient(main.app).get("/api/track-record")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 200
    assert [r["engine"] for r in response.json()] == ["gas", "weather"]
    assert supa.query.ordered_by == "engine"


def test_track_record_endpoint_503_without_supabase():
    from tradehub.api import main
    from tradehub.api.dependencies import get_supabase

    main.app.dependency_overrides[get_supabase] = lambda: None
    try:
        response = TestClient(main.app).get("/api/track-record")
    finally:
        main.app.dependency_overrides.clear()
    assert response.status_code == 503
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_api_frontend.py -q`
Expected: collection error, `ModuleNotFoundError: No module named 'tradehub.api.frontend'`.

- [ ] **Step 3: Implement** — `tradehub/api/frontend.py`:

```python
"""Serve the built War Room SPA from the API container (same origin: no CORS, no second app)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.staticfiles import StaticFiles


class SPAStaticFiles(StaticFiles):
    """Static files that fall back to index.html so client-side routes survive a refresh.

    API paths never fall back: an unknown /api/... stays a 404.
    """

    async def get_response(self, path: str, scope):
        try:
            response = await super().get_response(path, scope)
        except StarletteHTTPException as exc:
            if exc.status_code != 404 or path.startswith("api"):
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not path.startswith("api"):
            return await super().get_response("index.html", scope)
        return response


def mount_frontend(app: FastAPI, dist: Path) -> bool:
    if not (dist / "index.html").is_file():
        return False
    app.mount("/", SPAStaticFiles(directory=dist, html=True), name="frontend")
    return True
```

In `tradehub/api/main.py`:
1. Next to the other `from tradehub.api...` imports, add `from tradehub.api.frontend import mount_frontend`.
2. Directly **above** the line `# ── Dev entrypoint ─────…`, insert:

```python
# ════════════════════════════════════════════════════════════════════════════
# ENDPOINT: /api/track-record (served via the service-role client, so the
# owner-only RLS on track_record never has to be opened to the anon key)
# ════════════════════════════════════════════════════════════════════════════
@app.get("/api/track-record", tags=["Track Record"])
async def get_track_record(supabase=Depends(get_supabase)):
    if supabase is None:
        raise HTTPException(status_code=503, detail="Supabase is not configured")
    result = supabase.table("track_record").select("*").order("engine").execute()
    return result.data or []


# ── War Room SPA (mounted last so every /api route above wins) ─────────────
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(Path(__file__).resolve().parents[2] / "market_sentiment_tool" / "dist")))
mount_frontend(app, FRONTEND_DIST)


```

(`Depends`, `HTTPException`, `os`, and `Path` are already imported in `main.py`.)

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_api_frontend.py tests/test_kalshi_edge_system.py -q`
Expected: all pass. The existing `TestFastAPIEndpoints` must keep passing; locally there is usually no `market_sentiment_tool/dist`, so nothing gets mounted.

- [ ] **Step 5: Commit**

```bash
git add tradehub/api/frontend.py tradehub/api/main.py tests/test_api_frontend.py
git commit -m "feat: serve the War Room SPA and track record from the API

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Dockerfile + .dockerignore

**Files:**
- Create: `Dockerfile`, `.dockerignore`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Produces an image that:
  - by default runs `uvicorn tradehub.api.main:app` on `$PORT` (default 8000);
  - has `PYTHONPATH=/app`, so `python -m tradehub.scripts.scan` and `python -m tradehub.scripts.settle_predictions` work as job commands;
  - contains the built SPA at `/app/market_sentiment_tool/dist`.
- Build args: `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY` (both public). `VITE_API_BASE_URL` is empty, so the SPA calls the same origin.

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_dockerfile_and_dockerignore():
    docker = (REPO / "Dockerfile").read_text(encoding="utf-8")
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert "uvicorn tradehub.api.main:app" in docker
    assert "uv pip install --system" in docker and "-r pyproject.toml" in docker
    assert "npm run build" in docker and "ENV PYTHONPATH=/app" in docker
    for pattern in (".env", ".env.*", "*.pem", "*.key", "_attic", ".venv", "**/node_modules", "models", "*.pkl"):
        assert pattern in ignore, f".dockerignore must exclude {pattern}"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_dockerfile_and_dockerignore -q`
Expected: FAIL, `FileNotFoundError` for `Dockerfile`.

- [ ] **Step 3a: Sync the frontend lockfile.** The committed `market_sentiment_tool/package-lock.json` is out of sync with `package.json`: the eslint dev dependencies drifted, so `npm ci` fails with `EUSAGE … lock file's eslint@10.0.1 does not satisfy eslint@9.39.5` (found while validating this plan with a real build on 2026-09-24). Regenerate the lockfile only; don't upgrade anything:

```bash
(cd market_sentiment_tool && npm install --package-lock-only --no-audit --no-fund && npm ci --dry-run --no-audit --no-fund >/dev/null && echo "lockfile in sync")
```
Expected: `lockfile in sync`.

- [ ] **Step 3b: Create the files** — `Dockerfile`:

```dockerfile
# ── Stage 1: build the War Room SPA ─────────────────────────────────────────
FROM node:20-slim AS frontend-build
WORKDIR /app/market_sentiment_tool
COPY market_sentiment_tool/package.json market_sentiment_tool/package-lock.json ./
RUN npm ci
COPY market_sentiment_tool/ ./
# Public by design (browser-side Supabase URL + publishable key). Same-origin API.
ARG VITE_SUPABASE_URL=""
ARG VITE_SUPABASE_PUBLISHABLE_KEY=""
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY \
    VITE_API_BASE_URL=""
RUN npm run build

# ── Stage 2: Python runtime (API + scheduled jobs share this image) ────────
FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml
COPY tradehub/ ./tradehub/
COPY shared/ ./shared/
COPY market_sentiment_tool/backend/ ./market_sentiment_tool/backend/
COPY --from=frontend-build /app/market_sentiment_tool/dist ./market_sentiment_tool/dist
ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
EXPOSE 8000
CMD ["sh", "-c", "uvicorn tradehub.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

`.dockerignore`:

```
.git
.github
.venv
.venv-*
**/node_modules
**/__pycache__
**/.pytest_cache
.ruff_cache
_attic
archive
research
graphify-out
docs
.cleanup
.superpowers
.env
.env.*
*.pem
*.key
models
model
*.pkl
market_sentiment_tool/dist
market_sentiment_tool/backend/chroma_db
market_sentiment_tool/backend/*.sqlite3*
```

- [ ] **Step 4: Verify the test and a real image build**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
docker build -t tradehub:local .
docker run --rm tradehub:local python -c "import tradehub.api.main, tradehub.scripts.scan, tradehub.scripts.settle_predictions; print('imports ok')"
docker run --rm tradehub:local sh -c "ls -a /app; ls /app/market_sentiment_tool/dist | head -3; ls /app/.env /app/*.pem /app/models 2>&1 | head -3"
docker run --rm -d -p 8000:8000 --name tradehub-smoke tradehub:local && sleep 6 && curl -s localhost:8000/api/health | head -c 200 && echo && curl -s -o /dev/null -w "%{http_code}\n" localhost:8000/shadow; docker rm -f tradehub-smoke
```

Expected (as verified on 2026-09-24 against this exact Dockerfile):
- layout tests pass;
- the build succeeds and the image is about 0.9 GB;
- `imports ok` prints;
- `dist` lists `index.html`/`assets`, and the `.env`/`*.pem`/`models` lookups print "No such file";
- `/api/health` returns JSON;
- `/shadow` returns `200` (the SPA fallback).

Paste these outputs into the evidence report.

- [ ] **Step 5: Commit**

```bash
git add Dockerfile .dockerignore tests/test_repo_layout.py market_sentiment_tool/package-lock.json
git commit -m "build: add multi-stage image for API, War Room and scheduled jobs; sync frontend lockfile

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Build + deploy workflow (`.github/workflows/deploy-tradehub.yml`)

**Files:**
- Create: `.github/workflows/deploy-tradehub.yml`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Consumes (Kevin creates them; Task 5):
  - repository **secrets** `GHCR_PAT`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`;
  - repository **variable** `VPS_HOST`.
- Consumes the Task 2 `Dockerfile` (build args `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`).
- Produces the image `ghcr.io/kevocado/tradehub:<sha>` + `:latest`, and runs `deploy tradehub <sha>` on the VPS.

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_deploy_workflow_builds_then_deploys_to_vps():
    import yaml

    path = REPO / ".github/workflows/deploy-tradehub.yml"
    assert path.is_file(), "deploy workflow missing"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"test", "build", "vps"}
    assert workflow["jobs"]["build"]["needs"] == "test"
    assert workflow["jobs"]["vps"]["needs"] == "build"
    assert workflow["jobs"]["vps"]["if"] == "vars.VPS_HOST != ''"
    assert workflow["env"]["IMAGE"] == "ghcr.io/kevocado/tradehub"
    for needle in (
        "deploy tradehub ${{ github.sha }}",
        "SUPABASE_SERVICE_ROLE_KEY: dummy-baseline-placeholder",
        "--build-arg VITE_SUPABASE_URL=",
        "secrets.VPS_KNOWN_HOSTS",
    ):
        assert needle in text, f"workflow missing {needle}"
    for azure in ("az login", "containerapp", "AZURE_"):
        assert azure not in text, f"workflow must not reference Azure ({azure})"
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_deploy_workflow_builds_then_deploys_to_vps -q`
Expected: FAIL, "deploy workflow missing".

- [ ] **Step 3: Create the workflow**

```yaml
name: Build and deploy Trade Hub

on:
  push:
    branches: [main]
    paths:
      - "tradehub/**"
      - "shared/**"
      - "market_sentiment_tool/**"
      - "pyproject.toml"
      - "Dockerfile"
      - ".dockerignore"
      - ".github/workflows/deploy-tradehub.yml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  IMAGE: ghcr.io/kevocado/tradehub

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: |
          pip install uv
          uv pip install --system -r pyproject.toml --extra dev --extra scanner
      - name: Run tests
        env:
          SUPABASE_SERVICE_ROLE_KEY: dummy-baseline-placeholder
        run: python -m pytest -q

  build:
    needs: test
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GHCR_PAT }}

      - name: Build and push image
        run: |
          docker build \
            --build-arg VITE_SUPABASE_URL="${{ secrets.VITE_SUPABASE_URL }}" \
            --build-arg VITE_SUPABASE_PUBLISHABLE_KEY="${{ secrets.VITE_SUPABASE_PUBLISHABLE_KEY }}" \
            -t "$IMAGE:${{ github.sha }}" -t "$IMAGE:latest" .
          docker push "$IMAGE:${{ github.sha }}"
          docker push "$IMAGE:latest"

  # Deploys the image to the VPS stack (/opt/stack; see the vps-stack README).
  # Switched on by the VPS_HOST repo variable.
  vps:
    needs: build
    if: vars.VPS_HOST != ''
    runs-on: ubuntu-latest
    concurrency: vps-deploy-tradehub
    steps:
      - name: Deploy to VPS
        env:
          SSH_KEY: ${{ secrets.VPS_SSH_KEY }}
          KNOWN_HOSTS: ${{ secrets.VPS_KNOWN_HOSTS }}
        run: |
          install -m 700 -d ~/.ssh
          printf '%s\n' "$SSH_KEY" > ~/.ssh/id_ed25519 && chmod 600 ~/.ssh/id_ed25519
          printf '%s\n' "$KNOWN_HOSTS" > ~/.ssh/known_hosts
          ssh deploy@${{ vars.VPS_HOST }} deploy tradehub ${{ github.sha }}
```

- [ ] **Step 4: Run to verify it passes**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest -shellcheck= .github/workflows/deploy-tradehub.yml && echo "actionlint ok"
```
Expected: all pass and `actionlint ok` prints.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-tradehub.yml tests/test_repo_layout.py
git commit -m "ci: build the trade hub image and deploy it to the VPS

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Retire the PM2 processes + document the VPS deployment

**Files:**
- Delete: `Procfile`, `ecosystem.config.js` (`_attic/` is gitignored and absent in a fresh checkout, so the files are removed rather than moved; git history keeps them)
- Modify: `SYSTEM_ARCH.md`, `shared/config.py`, `shared/fast_scanner.py`, `shared/background_scanner.py` (docstrings only)
- Modify: `README.md`, `docs/superpowers/plans/2026-09-24-rollout-tracker.md`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:** none (docs and process config only).

Nothing runs under PM2 any more: the API and the scan/settle work move into the image (Tasks 1–3), and the crypto shadow worker is parked with live execution (spec §7).

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_pm2_process_files_are_retired():
    assert not (REPO / "Procfile").exists()
    assert not (REPO / "ecosystem.config.js").exists()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## VPS deployment" in readme
    assert "tradehub-scan.timer" in readme and "deploy tradehub" in readme
    assert "pm2 start" not in readme
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_pm2_process_files_are_retired -q`
Expected: FAIL (`Procfile` still exists).

- [ ] **Step 3: Move the files and edit the docs.**

```bash
git rm Procfile ecosystem.config.js
```

In `README.md`, delete the whole `### Crypto Orchestrator VPS Runbook` section (from that heading to the end of the section; it is the last section in the file) and append:

```markdown
## VPS deployment

The trade hub runs on the same VPS as the predictor sites, managed by the `vps-stack` folder (deployed to `/opt/stack`; see its README).

| Piece | What | When |
|---|---|---|
| `tradehub` container | FastAPI (`tradehub.api.main`) + the built War Room SPA, same origin, at `trade.<domain>` | always on (compose profile `tradehub`) |
| `tradehub-scan.timer` | `python -m tradehub.scripts.scan`: weather + gas predictions and edges (suggest-only) | hourly at :05 |
| `tradehub-settle.timer` | `python -m tradehub.scripts.settle_predictions`: settles predictions, refreshes the track record | hourly at :35 |

Every push to `main` that touches the app runs `.github/workflows/deploy-tradehub.yml`: tests, then build and push `ghcr.io/kevocado/tradehub`, then `ssh deploy@$VPS_HOST deploy tradehub <sha>`, which health-checks `/api/health` and rolls back on failure.

On the VPS (as `deploy`):

    /opt/stack/bin/tradehub-job scan                 # run a scan now
    journalctl -u tradehub-scan.service -n 100       # last scan logs
    systemctl list-timers 'tradehub-*'               # next runs
    /opt/stack/bin/deploy deploy tradehub <old-sha>  # roll back

Live execution and the crypto shadow worker are parked (spec §7); their old PM2 files are in git history (removed in this commit).
```

In `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, replace the step 5 status row with:

```
| 5 | VPS deploy: API + War Room container, hourly scan/settle timers (replaces the Azure plan) | ✅ implemented, pending Kevin's first deploy (Task 5) | [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md) |
```

and in the "Step 7" section, replace the line starting `- **Scope:** read-only adapters for the NFL/CFB predictor APIs first` with:

```
- **Scope:** read-only adapters for the NFL/CFB predictor APIs first (`https://nfl.<domain>/api`, `https://cfb.<domain>/api` on the VPS), then NBA/PL/F1 (`https://nba.<domain>`, `https://pl.<domain>`, `https://f1.<domain>`).
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q`
Expected: all pass. Then fix the remaining live references (found while validating this plan on 2026-09-25):
- `README.md`: delete the `├── ecosystem.config.js     # PM2 Orchestrator config` line from the repo tree near the top.
- `SYSTEM_ARCH.md`: line 13, replace "Orchestrated via PM2 (`ecosystem.config.js`)." with "Scheduled as hourly systemd timers on the VPS (see README, VPS deployment)."; delete the `├── ecosystem.config.js ...` tree line; replace the sentence starting "`ecosystem.config.js` keeps `background_scanner.py` running" with "The hourly `tradehub-scan` timer runs `python -m tradehub.scripts.scan` (weather + gas, suggest-only)."
- `shared/config.py` line 8: `(with PYTHONPATH=. set in Procfile)` becomes `(with PYTHONPATH=. set)`.
- `shared/fast_scanner.py` line 9 and `shared/background_scanner.py` line 8: delete the `Procfile: ...` line.

Then this must print nothing: `grep -rn 'ecosystem.config.js\|Procfile' --include='*.md' --include='*.py' . | grep -v -e _attic -e docs/superpowers -e node_modules -e tests/test_repo_layout.py`

- [ ] **Step 5: Commit**

```bash
git add README.md SYSTEM_ARCH.md shared/config.py shared/fast_scanner.py shared/background_scanner.py docs/superpowers/plans/2026-09-24-rollout-tracker.md tests/test_repo_layout.py
git commit -m "docs: document the VPS deployment; retire the PM2 process files

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: First deploy (Kevin runs these; the agent prepares and verifies)

**Files:** none. This is the operational checklist. Record the outcome in the evidence report.

- [ ] **Step 1: GitHub secrets (Kevin).** In `Kevocado/algo-trade-hub-prod`: secrets `GHCR_PAT` (same as the predictor repos), `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`. For `VPS_HOST`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`, add `Kevocado/algo-trade-hub-prod` to the `REPOS` list in `vps-stack/bin/set-github-secrets.sh` and re-run it.
- [ ] **Step 2: Apply migrations (Kevin).** Apply steps 2–4's migrations (`20260416000003`–`20260416000005`, plus the `signal_events` migration noted in `task.md`) to Supabase before the first scan/settle run, otherwise the inserts fail.
- [ ] **Step 3: VPS env (Kevin).** Set `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in `/opt/stack/.env`.
- [ ] **Step 4: First deploy (Kevin).** Merge to `main` and push, or run the workflow via "Run workflow". After the first push, make the GHCR package public (github.com/users/Kevocado/packages/container/tradehub/settings → Change visibility → Public), the same as the predictor images, so the VPS can pull it without a registry login. Then re-run the `vps` job.
- [ ] **Step 5: Turn on HTTPS and the timers (Kevin, on the VPS):**

**Only enable the timers after step 2b (promotion-gate fixes) is merged and deployed.** Until then, run `/opt/stack/bin/tradehub-job scan` by hand if you want data.

First, as `deploy`, open `/opt/stack/Caddyfile` (`nano /opt/stack/Caddyfile`) and uncomment the four lines of the `trade.{$DOMAIN}` block at the bottom (remove the leading `# `). Then:

```bash
# as deploy
docker compose -f /opt/stack/compose.yml restart caddy   # restart, not reload: editors can swap the file's inode under the bind mount
/opt/stack/bin/tradehub-job scan                                       # one manual run first
# as root
systemctl enable --now tradehub-scan.timer tradehub-settle.timer
```

Add a DNS A record for `trade.<domain>` if you don't use a wildcard record.

- [ ] **Step 6: Verify (the agent, read-only, after Kevin deploys):**

```bash
ssh deploy@$VPS_HOST 'cd /opt/stack && docker compose --profile tradehub ps tradehub && systemctl list-timers "tradehub-*" && journalctl -u tradehub-scan.service -n 20 --no-pager && docker stats --no-stream'
curl -s https://trade.$DOMAIN/api/health
curl -s -o /dev/null -w '%{http_code}\n' https://trade.$DOMAIN/lab
```

Expected: `tradehub` running; both timers listed with a next run; a scan run that ends in success; `/api/health` returns JSON; `/lab` returns 200 (the SPA); total memory under ~3 GB; new `predictions` rows in Supabase.

## Out of Scope

- **Live execution and the crypto shadow worker** (spec §7), and any Kalshi private key on the VPS.
- **Auth on the War Room.** It is read-only and public like the predictor sites; add Caddy `basic_auth` on `trade.{$DOMAIN}` later if wanted.
- **Moving static frontends to a CDN** (Cloudflare Pages): a later cost/latency improvement for the whole stack, not specific to the trade hub.
