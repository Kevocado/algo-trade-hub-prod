# Algo-Trade-Hub

A unified, production-grade Kalshi trading and analytics monorepo. The canonical product surface is the `tradehub` engine/operator package plus the `market_sentiment_tool` backend/frontend surface, with shared infrastructure living in `shared/` and `.agent/`.

> **Canonical references:** [`SYSTEM_ARCH.md`](./SYSTEM_ARCH.md), [`.agent/index/SYSTEM_MAP.md`](./.agent/index/SYSTEM_MAP.md), and [`AGENTS.md`](./AGENTS.md)

---

## Quick Overview: The Hybrid Architecture

Algo-Trade-Hub operates on a separated hybrid model to maximize VPS performance while delivering a lightning-fast React UI.

1. **The Core Engines (VPS / Local):** Python data pipelines running on a continuous daemon (`background_scanner.py`). They pull from NWS, FRED, Kalshi, and Tiingo APIs, calculate mathematical edges, and write heavily normalized JSON data directly to a Supabase PostgreSQL database via a secure Service Role Key.
2. **The Terminal UI (Vercel):** A dynamic React frontend that acts as a read-only terminal dashboard. Built on modern Vite, it queries Supabase directly without relying on a continuously open Python FastAPI server, separating rendering limits from deep machine learning computation.

---

## Repository Structure

```text
Algo-Trade-Hub/
├── tradehub/                # Canonical Python engine/operator package
├── market_sentiment_tool/  # Canonical backend/frontend service surface
├── shared/                 # Universal shared contracts and utilities
├── research/               # parked research, not imported by runtime (see research/README.md)
├── archive/                # Archived legacy docs and duplicate prompt material
├── SYSTEM_ARCH.md          # ← Master architecture reference (read this first)
└── README.md
```

---

## Quick Start

### 1. Launching the Backend (VPS or Local)
Ensure you have created a `.env` in the root mapping your API connections and `SUPABASE_SERVICE_ROLE_KEY`.

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner
.venv/bin/python -m pytest            # run from the repo root
.venv/bin/python -m tradehub.scripts.background_scanner
```

### 2. Launching the Frontend Dashboard (Local Dev)
If you want to view the React "Terminal UI" locally before deploying to Vercel. Ensure `market_sentiment_tool/.env` contains your `VITE_SUPABASE_URL` and `VITE_SUPABASE_ANON_KEY`.

```bash
cd market_sentiment_tool
npm install
npm run dev
# The Dashboard will load at http://localhost:5173 
```

---

## Environment Variables

The system relies on a strict split of secrets.
- **Backend Secrets:** `Algo-Trade-Hub/.env` contains your high-clearance provider tokens and the Supabase Service role key.
- **Frontend Config:** `Algo-Trade-Hub/market_sentiment_tool/.env` strictly requires public/anon variables (prefixed with `VITE_`).

**Never commit `.env` files.**

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
