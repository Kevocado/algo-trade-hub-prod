# Algo-Trade-Hub

A unified, production-grade Kalshi trading and analytics monorepo. The canonical product surface is the `SP500 Predictor` engine/operator package plus the `market_sentiment_tool` backend/frontend surface, with shared infrastructure living in `shared/`, `Weather/`, `quant_research_lab/`, and `.agent/`.

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
├── SP500 Predictor/        # Canonical Python engine/operator package
├── market_sentiment_tool/  # Canonical backend/frontend service surface
├── Weather/                # Weather settlement research and contracts
├── shared/                 # Universal shared contracts and utilities
├── quant_research_lab/     # Active research notebooks and model experiments
├── archive/                # Archived legacy docs and duplicate prompt material
├── FPL_Optimizer/          # Legacy auxiliary content
├── ecosystem.config.js     # PM2 Orchestrator config
├── SYSTEM_ARCH.md          # ← Master architecture reference (read this first)
└── README.md
```

---

## Quick Start

### 1. Launching the Backend (VPS or Local)
Ensure you have created a `.env` in the root mapping your API connections and `SUPABASE_SERVICE_ROLE_KEY`.

```bash
cd "SP500 Predictor"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Run a single manual scan:
python scripts/background_scanner.py

# Or launch as a background daemon using PM2:
pm2 start ../ecosystem.config.js
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

### Crypto Orchestrator VPS Runbook

- The crypto runtime reads the canonical backend env from repo root: `Algo-Trade-Hub/.env`. `market_sentiment_tool/.env` is only a fallback if the root file is missing.
- Required backend vars: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `KALSHI_ENV`, `KALSHI_API_KEY_ID`, `KALSHI_PRIVATE_KEY_PATH`, `BTC_MODEL_PATH`, `ETH_MODEL_PATH`.
- Telegram operator-plane vars: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`.
- Before restarting the VPS worker after operator-plane changes, apply the Supabase migrations `market_sentiment_tool/supabase/migrations/20260408224000_crypto_operator_plane.sql` and `market_sentiment_tool/supabase/migrations/20260415090000_signal_events_unification.sql` so the canonical `signal_events` table and the `crypto_signal_events` compatibility view exist.
- Install the crypto backend runtime dependencies into the PM2 interpreter environment before starting the worker:
- Prefer the lean VPS/runtime dependency set in `requirements.vps.txt` for servers. It excludes offline research and unused local tooling so the VPS only installs what the live stack and validation path need.

```bash
cd /root/kalshibot
/root/kalshibot/.venv/bin/pip install -r requirements.vps.txt
/root/kalshibot/.venv/bin/python -c "import yfinance; print(yfinance.__version__)"
/root/kalshibot/.venv/bin/python -c "import ta; print(ta.__version__ if hasattr(ta, '__version__') else 'ta-ok')"
```

- `KALSHI_ENV=demo` uses `https://demo-api.kalshi.co/trade-api/v2` and `wss://demo-api.kalshi.co/trade-api/ws/v2`.
- `KALSHI_ENV=live` uses `https://api.elections.kalshi.com/trade-api/v2` and `wss://api.elections.kalshi.com/trade-api/ws/v2`.
- The Kalshi private key file must exist on the VPS filesystem and match `KALSHI_PRIVATE_KEY_PATH`.
- Live/latest crypto bars come from Alpaca; `yfinance` is used only to backfill older hourly bars when Alpaca does not yet have enough history for the long-window model features.
- The crypto feature builder also requires the `ta` package inside the same PM2 interpreter environment; if it is missing, inference will fail after backfill.

Start or restart on VPS:

```bash
cd /root/kalshibot
PYTHONPATH=/root/kalshibot pm2 start /root/kalshibot/market_sentiment_tool/backend/orchestrator.py --name crypto-sniper --interpreter /root/kalshibot/.venv/bin/python
pm2 restart crypto-sniper --update-env
pm2 logs crypto-sniper --lines 80
```

Apply the latest code + runtime dependencies on VPS:

```bash
cd /root/kalshibot
git pull
/root/kalshibot/.venv/bin/pip install -r requirements.vps.txt
pm2 restart crypto-sniper --update-env
pm2 logs crypto-sniper --lines 120 --nostream
```

Healthy startup should show:
- repo-root `.env` loaded,
- Supabase service-role client initialized,
- Kalshi WS listener using the canonical host for the selected `KALSHI_ENV`,
- `Kalshi WS connected; subscribing to ticker`,
- either direct inference or a yfinance backfill log instead of repeated `Need at least 205 hourly bars...` errors,
- `[CRYPTO EDGE] ... P(YES)=...` once markets begin streaming,
- Telegram operator plane started if Telegram env vars are present,
- `/balance`, `/positions`, `/trades`, and `/crypto_status` returning data from Telegram after the bot sees at least one chat message from the configured chat.

Telegram commands:
- `/crypto_status`
- `/balance`
- `/positions`
- `/trades`
- `/scan crypto`
- `/performance crypto`
- `/crypto_scan` *(alias)*
- `/cryptoscan` *(alias)*
- `/stats` *(alias)*
- `/accuracy` *(alias)*

Operator-plane behavior:
- Telegram alerts are async and must never block the crypto LangGraph loop.
- Telegram reads from Supabase and direct Kalshi REST reads; it does not share in-memory state with the worker.
- Threshold-crossing opportunity alerts are deduped for 5 minutes per market.
- Actual execution outcomes always alert.
- Insufficient-funds Kalshi rejections disable further crypto trading in Supabase until an operator re-enables it.
