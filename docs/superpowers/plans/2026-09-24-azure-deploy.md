# Azure Deploy (Scale-to-Zero) Implementation Plan

> **Superseded 2026-09-25 by [2026-09-25-vps-deploy.md](2026-09-25-vps-deploy.md).** The Azure for Students credit ends around 2026-10-27, and every site is moving to one VPS. Don't implement this plan. Its Tasks 1–2 are carried over word for word.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the trade hub on Azure Container Apps in the existing `predictor-hub-rg`, using the same GHCR → `az containerapp` pattern as the predictor sites. It consists of:
- an hourly `tradehub-scan` job (step 4) and an hourly `tradehub-settle` job (step 2), both Container Apps **Jobs** that exist only while they run;
- one `tradehub-app` container that serves the API and the built War Room at the same origin, scaling to zero.

**Architecture:**
- **One Docker image** (multi-stage: Vite build, then a Python 3.12 slim runtime installed from `pyproject.toml`) serves three roles. The two jobs run the same image with a different command.
- **The API gains** a same-origin SPA mount and a `/api/track-record` endpoint. The War Room reads the track record through the API's service-role client, so the owner-only RLS on `track_record` stays untouched.
- **A root-level GitHub Actions workflow** tests, builds, pushes, and creates or updates all three Azure resources.
- **The VPS keeps only the crypto orchestrator** (the only process it actually runs today) until a scheduled crypto job replaces it. That is a later rollout item.

**Tech Stack:** Docker (BuildKit), GitHub Actions, Azure CLI `containerapp` + `containerapp job` (flags verified against `azure-cli 2.90.0`), FastAPI/Starlette `StaticFiles`, `pytest`.

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md), §5 "Hosting: Azure, scale to zero" and §7 (no always-on worker until the "pays for itself" trigger). Rollout step 5 in [2026-09-24-rollout-tracker.md](2026-09-24-rollout-tracker.md).

## Global Constraints

- **Prerequisites:** steps 2 and 4 are merged to `main`. The jobs run `python -m tradehub.scripts.settle_predictions` (step 2) and `python -m tradehub.scripts.scan` (step 4).
- **Azure facts (verified 2026-09-24 via read-only `az` queries):**
  - subscription **Azure for Students** (credit-limited);
  - resource group `predictor-hub-rg`;
  - Container Apps environment **`predictor-hub-env`** (default domain `proudbay-f56b8dfa.eastus2.azurecontainerapps.io`);
  - existing apps `f1-predictor`, `pl-predictor`, `nfl-predictor`, `cfb-predictor`, `sports-predictor`, `nba-predictor`;
  - no jobs yet.
- **No always-on compute (spec §5, §7):**
  - `tradehub-app` runs with `--min-replicas 0`;
  - scan and settle are `--trigger-type Schedule` jobs;
  - no Kalshi WebSocket listener.
- **Secrets never go into the image or the repo.**
  - Runtime secrets are Container Apps secrets referenced with `secretref:`.
  - The frontend's public Supabase URL and publishable key are **build args**; they are public by design.
  - `.dockerignore` excludes `.env*`, `*.pem`, `*.key`, `_attic/`, `.venv*`, models, and `node_modules`.
- **Scan and settle use only public Kalshi endpoints,** so the only runtime secrets are `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- **Never push, merge, or run the workflow on Kevin's behalf.** Creating the GitHub secrets and the first deploy are Kevin's actions (Task 5 has the checklist).
- **Test runs:** `.venv/bin/python` from the repo root, each pytest run prefixed with `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder`.
- Every commit ends with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Follow the handoff contract in the rollout tracker: branch `plan/2026-09-24-azure-deploy`, one commit per task, evidence report at `docs/superpowers/reports/2026-09-24-azure-deploy.md`.

## Review Focus

- The SPA fallback returns `index.html` for client-side routes (`/lab`, `/shadow`), but an unknown `/api/...` path must still return 404 JSON, never the SPA. (Task 1)
- `/api/track-record` returns 503 (not 500) when Supabase isn't configured. (Task 1)
- The image contains no `.env`, `.pem`, or model files. (Task 2: checked in the built image)
- The workflow's create path and update path both apply the image, the secrets, and the env vars, so re-deploys are idempotent. (Task 3)
- Monthly compute fits the Container Apps free grant. (Task 5 cost check)

---

## File Structure

- **Create** `tradehub/api/frontend.py`: `SPAStaticFiles`, `mount_frontend(app, dist) -> bool`.
- **Modify** `tradehub/api/main.py`: add the `/api/track-record` endpoint and call `mount_frontend` last.
- **Create** `Dockerfile` and `.dockerignore` at the repo root.
- **Create** `.github/workflows/deploy-azure-tradehub.yml` (the first root-level workflow in this repo).
- **Modify** `Procfile` and `ecosystem.config.js` to keep only the crypto orchestrator.
- **Modify** `README.md` to add an "Azure deployment" section and point the VPS runbook at the crypto worker only.
- **Modify** `docs/superpowers/plans/2026-09-24-rollout-tracker.md`: mark step 5 and add the crypto-job/VPS-decommission follow-up.
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

## Task 3: Deploy workflow (`.github/workflows/deploy-azure-tradehub.yml`)

**Files:**
- Create: `.github/workflows/deploy-azure-tradehub.yml`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Consumes these GitHub **repository secrets** (Kevin creates them; Task 5): `GHCR_PAT`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`.
- Produces three resources in `predictor-hub-rg`/`predictor-hub-env`:
  - `tradehub-app`: external ingress on 8000, min 0 / max 2, 0.5 CPU / 1Gi;
  - `tradehub-scan`: Schedule `15 * * * *`, timeout 900 s, runs `python -m tradehub.scripts.scan`;
  - `tradehub-settle`: Schedule `45 * * * *`, timeout 600 s, runs `python -m tradehub.scripts.settle_predictions`.

  All three get the secrets `supabase-url`/`supabase-key` and the env vars `SUPABASE_URL=secretref:supabase-url` and `SUPABASE_SERVICE_ROLE_KEY=secretref:supabase-key`.

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_deploy_workflow_targets_scale_to_zero_resources():
    import yaml

    path = REPO / ".github/workflows/deploy-azure-tradehub.yml"
    assert path.is_file(), "deploy workflow missing"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"test", "deploy"}
    assert workflow["jobs"]["deploy"]["needs"] == "test"
    assert workflow["env"]["ACA_ENVIRONMENT"] == "predictor-hub-env"
    assert workflow["env"]["RESOURCE_GROUP"] == "predictor-hub-rg"
    for needle in (
        "--min-replicas 0",
        "--trigger-type Schedule",
        '--cron-expression "$cron"',
        'deploy_job tradehub-scan "15 * * * *" 900 tradehub.scripts.scan',
        'deploy_job tradehub-settle "45 * * * *" 600 tradehub.scripts.settle_predictions',
        "secretref:supabase-key",
        "SUPABASE_SERVICE_ROLE_KEY: dummy-baseline-placeholder",
    ):
        assert needle in text, f"workflow missing {needle}"
    assert "--min-replicas 1" not in text
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_deploy_workflow_targets_scale_to_zero_resources -q`
Expected: FAIL, "deploy workflow missing".

- [ ] **Step 3: Create the workflow**

```yaml
name: Deploy Trade Hub to Azure Container Apps

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
      - ".github/workflows/deploy-azure-tradehub.yml"
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  IMAGE: ghcr.io/kevocado/tradehub
  RESOURCE_GROUP: predictor-hub-rg
  ACA_ENVIRONMENT: predictor-hub-env

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

  deploy:
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

      - name: Log in to Azure
        run: |
          az login --service-principal -u "${{ secrets.AZURE_CLIENT_ID }}" -p "${{ secrets.AZURE_CLIENT_SECRET }}" --tenant "${{ secrets.AZURE_TENANT_ID }}"
          az account set --subscription "${{ secrets.AZURE_SUBSCRIPTION_ID }}"

      - name: Deploy API + War Room (scale to zero)
        run: |
          SECRETS="supabase-url=${{ secrets.SUPABASE_URL }} supabase-key=${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
          ENVVARS="SUPABASE_URL=secretref:supabase-url SUPABASE_SERVICE_ROLE_KEY=secretref:supabase-key"
          if az containerapp show -n tradehub-app -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
            az containerapp secret set -n tradehub-app -g "$RESOURCE_GROUP" --secrets $SECRETS
            az containerapp update -n tradehub-app -g "$RESOURCE_GROUP" \
              --image "$IMAGE:${{ github.sha }}" --min-replicas 0 --max-replicas 2 --set-env-vars $ENVVARS
          else
            az containerapp create -n tradehub-app -g "$RESOURCE_GROUP" --environment "$ACA_ENVIRONMENT" \
              --image "$IMAGE:${{ github.sha }}" \
              --registry-server ghcr.io --registry-username "${{ github.actor }}" --registry-password "${{ secrets.GHCR_PAT }}" \
              --target-port 8000 --ingress external --min-replicas 0 --max-replicas 2 --cpu 0.5 --memory 1Gi \
              --secrets $SECRETS --env-vars $ENVVARS
          fi
          az containerapp show -n tradehub-app -g "$RESOURCE_GROUP" --query properties.configuration.ingress.fqdn -o tsv

      - name: Deploy scheduled jobs (scan hourly at :15, settle hourly at :45)
        run: |
          SECRETS="supabase-url=${{ secrets.SUPABASE_URL }} supabase-key=${{ secrets.SUPABASE_SERVICE_ROLE_KEY }}"
          ENVVARS="SUPABASE_URL=secretref:supabase-url SUPABASE_SERVICE_ROLE_KEY=secretref:supabase-key"
          deploy_job() {
            local name="$1" cron="$2" timeout="$3" module="$4"
            if az containerapp job show -n "$name" -g "$RESOURCE_GROUP" >/dev/null 2>&1; then
              az containerapp job secret set -n "$name" -g "$RESOURCE_GROUP" --secrets $SECRETS
              az containerapp job update -n "$name" -g "$RESOURCE_GROUP" \
                --image "$IMAGE:${{ github.sha }}" --cron-expression "$cron" --set-env-vars $ENVVARS
            else
              az containerapp job create -n "$name" -g "$RESOURCE_GROUP" --environment "$ACA_ENVIRONMENT" \
                --trigger-type Schedule --cron-expression "$cron" \
                --replica-timeout "$timeout" --replica-retry-limit 1 --replica-completion-count 1 --parallelism 1 \
                --image "$IMAGE:${{ github.sha }}" \
                --registry-server ghcr.io --registry-username "${{ github.actor }}" --registry-password "${{ secrets.GHCR_PAT }}" \
                --cpu 0.5 --memory 1Gi \
                --command python --args -m "$module" \
                --secrets $SECRETS --env-vars $ENVVARS
            fi
          }
          deploy_job tradehub-scan "15 * * * *" 900 tradehub.scripts.scan
          deploy_job tradehub-settle "45 * * * *" 600 tradehub.scripts.settle_predictions
```

- [ ] **Step 4: Run to verify it passes**

```bash
SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q
.venv/bin/python -c "import yaml; yaml.safe_load(open('.github/workflows/deploy-azure-tradehub.yml')); print('yaml ok')"
```
Expected: all pass and `yaml ok` prints. If `actionlint` is installed, `actionlint .github/workflows/deploy-azure-tradehub.yml` should report nothing.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/deploy-azure-tradehub.yml tests/test_repo_layout.py
git commit -m "ci: deploy trade hub API and hourly scan/settle jobs to Azure Container Apps

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Trim the VPS to the crypto worker + docs

**Files:**
- Modify: `Procfile`, `ecosystem.config.js`, `README.md`, `docs/superpowers/plans/2026-09-24-rollout-tracker.md`
- Modify: `tests/test_repo_layout.py` (append)

**Interfaces:** none (docs and process config only).

The VPS runbook in `README.md` shows the VPS only runs the crypto orchestrator (`pm2 … --name crypto-sniper`). The API, scanners, and MCP bridge lines in `Procfile`/`ecosystem.config.js` are superseded by Azure (API + scan) or unused (the MCP bridge; the orchestrator imports `submit_kalshi_order` directly).

- [ ] **Step 1: Write the failing test** — append to `tests/test_repo_layout.py`:

```python
def test_vps_process_files_only_run_the_crypto_worker():
    procfile = [l for l in (REPO / "Procfile").read_text(encoding="utf-8").splitlines() if l and not l.startswith("#")]
    assert procfile == ["orchestrator: PYTHONPATH=. python market_sentiment_tool/backend/orchestrator.py"]
    eco = (REPO / "ecosystem.config.js").read_text(encoding="utf-8")
    assert "orchestrator.py" in eco
    for gone in ("api_server", "mcp_server", "background_scanner", "fast_scanner"):
        assert gone not in eco
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## Azure deployment" in readme and "tradehub-scan" in readme
```

- [ ] **Step 2: Run to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py::test_vps_process_files_only_run_the_crypto_worker -q`
Expected: FAIL (the Procfile still has 5 processes).

- [ ] **Step 3: Edit the files.** Replace the whole `Procfile` with:

```
# ==========================================================
# Algo-Trade-Hub — VPS Procfile
# Only the crypto orchestrator (Kalshi WS shadow worker) still runs on the VPS.
# API + War Room, the scan job and the settle job run on Azure Container Apps
# (.github/workflows/deploy-azure-tradehub.yml). The VPS is decommissioned once
# a scheduled crypto job replaces this worker (rollout tracker follow-up).
# ==========================================================
orchestrator: PYTHONPATH=. python market_sentiment_tool/backend/orchestrator.py
```

Replace the whole `ecosystem.config.js` with:

```js
// Only the crypto orchestrator still runs on the VPS; everything else is on Azure.
module.exports = {
  apps: [
    {
      name: 'orchestrator',
      script: 'market_sentiment_tool/backend/orchestrator.py',
      interpreter: 'python3',
      env: {
        PYTHONPATH: '.'
      }
    }
  ]
};
```

In `README.md`, insert this section immediately **before** the line `### Crypto Orchestrator VPS Runbook`:

```markdown
## Azure deployment

Everything except the crypto orchestrator runs on Azure Container Apps in `predictor-hub-rg` (environment `predictor-hub-env`), deployed by `.github/workflows/deploy-azure-tradehub.yml` on every push to `main` that touches the app:

| Resource | What | Schedule / scaling |
|---|---|---|
| `tradehub-app` | FastAPI (`tradehub.api.main`) + the built War Room SPA, same origin | scale to zero (min 0, max 2) |
| `tradehub-scan` | `python -m tradehub.scripts.scan`: weather + gas predictions and edges (suggest-only) | hourly at :15 |
| `tradehub-settle` | `python -m tradehub.scripts.settle_predictions`: settles predictions, refreshes the track record | hourly at :45 |

Required GitHub repository secrets: `GHCR_PAT`, `AZURE_CLIENT_ID`, `AZURE_CLIENT_SECRET`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_PUBLISHABLE_KEY`.

Run a job on demand: `az containerapp job start -n tradehub-scan -g predictor-hub-rg`. List executions: `az containerapp job execution list -n tradehub-scan -g predictor-hub-rg -o table`.
```

Then, in the same file, change the heading `### Crypto Orchestrator VPS Runbook` to `### Crypto Orchestrator VPS Runbook (the only VPS process)`.

In `docs/superpowers/plans/2026-09-24-rollout-tracker.md`, change the step 5 status row to:

```
| 5 | Azure deploy: scheduled jobs + API + web (VPS keeps only the crypto worker) | ✅ implemented, pending Kevin's first deploy (Task 5) | [2026-09-24-azure-deploy.md](2026-09-24-azure-deploy.md) |
```

and add this line under the table's "Parked (not scheduled)" paragraph:

```
Follow-up (unscheduled): turn the crypto shadow orchestrator into a one-shot hourly `tradehub-crypto` job, then decommission the VPS (spec §5).
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=dummy-baseline-placeholder .venv/bin/python -m pytest tests/test_repo_layout.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add Procfile ecosystem.config.js README.md docs/superpowers/plans/2026-09-24-rollout-tracker.md tests/test_repo_layout.py
git commit -m "docs: document Azure deployment; VPS keeps only the crypto worker

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 5: First deploy (Kevin runs these; the agent prepares and verifies)

**Files:** none. This is the operational checklist. Record the outcome in the evidence report.

- [ ] **Step 1: Cost check (the agent does this).** Container Apps consumption includes a monthly free grant of 180,000 vCPU-seconds and 360,000 GiB-seconds per subscription.
  - The two hourly jobs, at about 60 s each at 0.5 vCPU / 1 GiB, come to 48 runs/day × 60 s × 0.5 ≈ 1,440 vCPU-s/day, about 43,000 vCPU-s/month (≈ 86,000 GiB-s).
  - `tradehub-app` at min 0 only uses compute while serving requests.
  - Record the measured job durations after the first day: `az containerapp job execution list -n tradehub-scan -g predictor-hub-rg -o table`.
  - If a job runs over 5 minutes on average, flag it in the report before it eats the student credit.
- [ ] **Step 2: GitHub secrets (Kevin).** In the `Kevocado/algo-trade-hub-prod` repo settings, add the nine secrets listed in Task 3. The Azure service principal and `GHCR_PAT` can be the same values already used by the predictor repos. The service principal needs Contributor on `predictor-hub-rg`.
- [ ] **Step 3: Apply migrations (Kevin).** Apply steps 2–4's migrations (`20260416000003`–`20260416000005`) to Supabase before the first scan/settle run, otherwise the inserts fail.
- [ ] **Step 4: First deploy (Kevin).** Merge to `main` and push, or run the workflow via "Run workflow" (`workflow_dispatch`).
- [ ] **Step 5: Verify (the agent, with read-only commands, after Kevin deploys):**

```bash
az containerapp show -n tradehub-app -g predictor-hub-rg --query "{fqdn:properties.configuration.ingress.fqdn, min:properties.template.scale.minReplicas}" -o table
az containerapp job list -g predictor-hub-rg --query "[].{name:name, cron:properties.configuration.scheduleTriggerConfig.cronExpression}" -o table
az containerapp job start -n tradehub-scan -g predictor-hub-rg
az containerapp job execution list -n tradehub-scan -g predictor-hub-rg -o table
curl -s "https://$(az containerapp show -n tradehub-app -g predictor-hub-rg --query properties.configuration.ingress.fqdn -o tsv)/api/health"
```

Expected: `min` = 0; both jobs listed with crons `15 * * * *` and `45 * * * *`; a scan execution reaching `Succeeded`; `/api/health` returns JSON; and new `predictions` rows in Supabase.

## Out of Scope

- **The scheduled crypto job and VPS decommission:** a tracker follow-up.
- **Fixing the NFL workflow's `--environment` value:** in `NFL_Predictor/.github/workflows/deploy-azure-nfl.yml`, `proudbay-f56b8dfa.eastus2` is the environment *domain*, not its name `predictor-hub-env`. Its `create … || true` has been failing silently, and deploys only work because the app already exists. That fix belongs in that repo.
- **Custom domains, auth on the War Room, and live execution** (spec §7).
