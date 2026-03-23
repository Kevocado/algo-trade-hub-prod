# SYSTEM_ARCH.md — Algo-Trade-Hub Master Architecture Reference

> **This is the single source of truth for this entire codebase.**
> Read this before touching any sub-system. Every rule here is enforced.

---

## Overview

Algo-Trade-Hub is a unified quantitative trading and sports analytics platform operating on a modern **Hybrid Architecture**:

1. **Frontend (Vercel)** — A React/Vite web application (`market_sentiment_tool`) serving as the unified "Kalshi Terminal" and "War Room" dashboard.
2. **Backend Compute (Custom VPS)** — Diverse Python engines (Quant, Weather, Macro, Sports) running autonomously separated from the frontend to optimize resources. Orchestrated via PM2 (`ecosystem.config.js`).
3. **Data Bridge (Supabase PostgreSQL)** — The central state layer bridging the Vercel UI and the VPS Daemons. 

---

## Directory Map

```
Algo-Trade-Hub/                          ← Root monorepo (one git repo)
│
├── SP500 Predictor/                     ← Backend Python Compute Engines
│   ├── src/                             ← Core library modules & shared tools
│   │   ├── supabase_client.py           ← Unified Supabase write client (upsert_opportunities)
│   │   └── ...
│   ├── scripts/                         
│   │   ├── engines/                     ← Standalone specialized edge models
│   │   │   ├── quant_engine.py          ← Paper trading ML engine (Crypto/SPX)
│   │   │   ├── weather_engine.py        ← NWS → Kalshi weather arbitrage
│   │   │   ├── macro_engine.py          ← FRED → Kalshi CPI/macro arbitrage
│   │   │   ├── football_engine.py       ← Understat xPTS Poisson prediction
│   │   │   └── tsa_engine.py            ← TSA Passenger volume metrics
│   │   └── background_scanner.py        ← Central Daemon (runs all engines, pushes to Supabase)
│   └── .env                             ← BACKEND SECRETS (Role Keys, APIs)
│
├── market_sentiment_tool/               ← Frontend Unified Web Dashboard (Vercel)
│   ├── src/                             ← React app source
│   │   ├── pages/                       ← Dynamic Routing
│   │   │   ├── Index.tsx                ← 'War Room' (AI Swarm Activity Console)
│   │   │   ├── KalshiLab.tsx            ← 'Kalshi Lab' (Filters WEATHER, MACRO, CRYPTO)
│   │   │   └── SportsDesk.tsx           ← 'Sports Desk' (Filters SPORTS - EPL/F1/NBA)
│   │   ├── components/                  ← Reusable UI & strict ErrorBoundary wrappers
│   │   ├── hooks/                       ← Supabase useSupabaseData hooks
│   │   └── types/                       ← TypeScript interfaces matching Supabase schema
│   ├── package.json                     ← Node deps (React, Tailwind, Supabase JS)
│   └── .env                             ← FRONTEND CONFIG (VITE_ API URLs & Anon Keys)
│
├── FPL_Optimizer/                       ← Legacy standalone FPL tools (Merged pending full port)
│
├── ecosystem.config.js                  ← PM2 Daemon configuration
├── SYSTEM_ARCH.md                       ← You are here
├── README.md                            ← Monorepo quick-start guide
└── .gitignore                           ← Root gitignore
```

---

## The Hybrid Hosting Model

The system separates concerns to heavily optimize the $5/mo VPS server limit while maintaining a highly responsive, high-volume data dashboard.

### 1. The VPS Backend (Data Generation & Orchestration)
The VPS focuses entirely on running heavy machine learning inference (LightGBM/FinBERT) and data scraping (NWS, FRED, Understat).

**Key Flow:**
1. `ecosystem.config.js` keeps `background_scanner.py` running in a constant loop.
2. The scanner initializes specific engines (`weather_engine`, `macro_engine`, `quant_engine`, `football_engine`, `tsa_engine`, `eia_engine`).
3. **Threshold-Free Discovery:** Engines ingest raw data and compute mathematical edges. Instead of filtering out low-edge markets, engines return *all* strictly tracked live markets (e.g., creating a massive grid of 100+ upcoming weather markets).
4. **Dynamic Data Tagging:** The `background_scanner` assigns a strict `edge_type` string to the payload: `'WEATHER'`, `'MACRO'`, `'CRYPTO'`, or `'SPORTS'`.
5. **Supabase Injection:** `supabase_client.py` uses the `SUPABASE_SERVICE_ROLE_KEY` to securely `UPSERT` normalized records into the `kalshi_edges` database table.

### 2. The Database Bridge (Supabase)
Supabase eliminates the need for a persistent Python API layer holding open local HTTP sockets between the VPS and the world. 

**Database Schema (`kalshi_edges`):**
- `id`: UUID
- `market_id`: Enforced unique identifier (e.g., `WEATHER_MIA_2026-03-23`)
- `title`: Human-readable event description 
- `edge_type`: Hardcoded category enum
- `our_prob`: Computed model percentage probability
- `market_prob`: Current retail bid/ask on the Kalshi exchange
- `edge_pct`: The spread between `our_prob` and `market_prob`
- `raw_payload`: Open JSONB wrapper storing context-specific properties (e.g., `forecast_temp`, `team_xg`, `cpi_actual`).

*Note:* Supabase Row Level Security (RLS) policies permit strictly read-only public access using the `SUPABASE_ANON_KEY`.

### 3. The Vercel Frontend (Data Consumption & UI)
Hosted on Vercel's global edge network, the React application renders the data.

**Dashboard Structure:**
By leveraging the `edge_type` tagged onto every database row, the frontend splits traffic cleanly into specialized views via `react-router-dom`:

- **The Kalshi Lab (`/kalshi-lab`):**
  Uses `useSupabaseData` to pull any row where `edge_type IN ('WEATHER', 'MACRO', 'CRYPTO')`. Features robust data tables allowing the user to scan the entire grid of upcoming markets, quickly identifying pricing inefficiencies dynamically.
- **The Sports Desk (`/sports`):**
  Pulls strictly `edge_type = 'SPORTS'`. Isolates heavier, sports-specific analytical UI components like the `SquadVisualizer`. The implementation forces strict `ErrorBoundary` wrappers to prevent fatal UI crashes if a single game's JSON payload is malformed.
- **The War Room (`/`):**
  Displays overarching paper-trading metrics, AI log streams, and portfolio performance.

---

## Environment Variable Architecture

Environment variables govern security isolation. The backend needs master-write access; the frontend ONLY gets read-access.

**`.env` (VPS Backend - Server Secret)**
```bash
SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="eyJ..."        # MASTER KEY. Writes SQL.
FRED_API_KEY="..."                        # Data Sources
FOOTBALL_DATA_API_KEY="..."
```

**`market_sentiment_tool/.env` (Vercel Build - Public/Anon)**
```bash
VITE_SUPABASE_URL="https://your-project.supabase.co"
VITE_SUPABASE_ANON_KEY="eyJ..."           # READ ONLY KEY. Cannot modify tables.
VITE_API_BASE_URL="..."
```

---

## Integration Rules (Hard Rules — Never Break These)

1. **Frontend is read/display-only.** The React app in `market_sentiment_tool/` **never** executes proprietary business logic, model inference, or writes trading executions to the VPS.
2. **Tuple-Safe Python Extraction.** Ensure all ML feature engineering pipelines safely extract DataFrames. Unpacked model inputs (`df[0] if isinstance(df, tuple)`) are strictly required.
3. **Edge Types Must Map to UI.** Never inject a new data pipeline without strictly labeling the payload's `edge_type` string to match the React Frontend's filters.
4. **Brokerage keys never leave the local machine/VPS.** `APCA_API_SECRET_KEY` and similar tokens are strictly reserved for local/VPS environment files and never uploaded to Vercel or Supabase.

---

*Last updated: 2026-03-23 by Antigravity (automated architecture sync)*
