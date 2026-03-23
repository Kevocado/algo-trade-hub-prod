# Algo-Trade-Hub

A unified, production-grade quantitative trading and sports analytics monorepo. This system continuously discovers arbitrage edges in prediction markets (Kalshi) by crunching weather data, macroeconomic indicators, crypto momentum, and sports statistics.

> **Full architecture reference:** [`SYSTEM_ARCH.md`](./SYSTEM_ARCH.md)

---

## Quick Overview: The Hybrid Architecture

Algo-Trade-Hub operates on a separated hybrid model to maximize VPS performance while delivering a lightning-fast React UI.

1. **The Core Engines (VPS / Local):** Python data pipelines running on a continuous daemon (`background_scanner.py`). They pull from NWS, FRED, Kalshi, and Tiingo APIs, calculate mathematical edges, and write heavily normalized JSON data directly to a Supabase PostgreSQL database via a secure Service Role Key.
2. **The Terminal UI (Vercel):** A dynamic React frontend that acts as a read-only terminal dashboard. Built on modern Vite, it queries Supabase directly without relying on a continuously open Python FastAPI server, separating rendering limits from deep machine learning computation.

---

## Repository Structure

```text
Algo-Trade-Hub/
├── SP500 Predictor/        # Python ML & Backend Engines (Run via PM2 VPS)
├── market_sentiment_tool/  # React/Vite Frontend (Hosted on Vercel)
├── FPL_Optimizer/          # Legacy Python sports models
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
