# SYSTEM_ARCH.md — Algo-Trade-Hub Master Architecture Reference

> **This is the single source of truth for this entire codebase.**
> Read this before touching any sub-system. Every rule here is enforced.

---

## Overview

Algo-Trade-Hub is a unified quantitative trading and sports analytics platform split into three cooperating sub-systems:

1. **SP500 Predictor** — A Python ML backend that ingests market data, weather, and macroeconomic signals to detect arbitrage edges in Kalshi prediction markets. It also runs paper-trading backtests for SPX/BTC/ETH/Nasdaq using LightGBM and FinBERT.
2. **Market Sentiment Tool** — A production-grade autonomous paper trading platform. A React/Supabase dashboard governs a local Python AI swarm (LangGraph + FastMCP) that executes paper trades on Alpaca by fusing quantitative order flow analysis with LLM-based macro sentiment.
3. **FPL Optimizer** — A Python sports analytics backend that optimizes Fantasy Premier League, F1, and NBA lineups using PuLP linear programming, exposes REST API endpoints, and provides a Gemini-powered chatbot.

All three sub-systems share a **central Supabase PostgreSQL database** as the cross-system state layer.

---

## Directory Map

```
Algo-Trade-Hub/                          ← Root monorepo (one git repo)
│
├── SP500 Predictor/                     ← Sub-System 1: Kalshi Edge Finder (Python)
│   ├── src/                             ← Core library modules
│   │   ├── data_loader.py               ← Alpaca API data fetching (replaces yfinance)
│   │   ├── feature_engineering.py       ← Technical indicators (RSI, MACD, BB, GEX, Amihud)
│   │   ├── sentiment.py                 ← FinBERT news sentiment pipeline
│   │   ├── sentiment_filter.py          ← HuggingFace pre-filter (FinBERT → BART → Gemini)
│   │   ├── kalshi_feed.py               ← Kalshi REST API client + opportunity scanner
│   │   ├── kalshi_portfolio.py          ← Position tracking + Kelly sizing
│   │   ├── market_scanner.py            ← Cross-engine edge aggregator
│   │   ├── weather_model.py             ← NWS API weather arbitrage engine
│   │   ├── fred_model.py                ← FRED API macro/CPI prediction engine
│   │   ├── microstructure_engine.py     ← L2 volume profile + order flow imbalance
│   │   ├── model_daily.py               ← LightGBM daily directional predictor
│   │   ├── backtester.py                ← Strategy backtesting with Brier Score
│   │   ├── evaluation.py                ← Model evaluation metrics
│   │   ├── ai_validator.py              ← Gemini Flash AI scrutinizer (value-trap detection)
│   │   ├── supabase_client.py           ← Shared Supabase write client
│   │   ├── telegram_notifier.py         ← Telegram alerts for edge opportunities
│   │   ├── discord_notifier.py          ← Discord alerts
│   │   ├── news_analyzer.py             ← News headline parser
│   │   ├── predictit_engine.py          ← PredictIt market integration
│   │   └── utils.py                     ← Shared helpers
│   ├── scripts/                         ← Automation & one-off scripts
│   │   ├── engines/                     ← Standalone edge-finding engines
│   │   │   ├── quant_engine.py          ← Paper trading ML engine (EDUCATIONAL ONLY)
│   │   │   ├── weather_engine.py        ← NWS → Kalshi weather arbitrage
│   │   │   ├── macro_engine.py          ← FRED → Kalshi CPI/macro arbitrage
│   │   │   └── fed_engine.py            ← CME FedWatch → Kalshi rate arbitrage
│   │   ├── background_scanner.py        ← Continuous 10-min market scan daemon
│   │   ├── weather_auto_sell.py         ← Automated weather position closer
│   │   ├── market_alerts.py             ← Alert dispatcher
│   │   ├── generate_market_snapshot.py  ← On-demand market snapshot tool
│   │   ├── train_all_models.py          ← Batch model retraining
│   │   ├── train_daily_models.py        ← Daily model refresh
│   │   └── supabase_setup.sql           ← Database schema for SP500 tables
│   ├── api/
│   │   ├── main.py                      ← FastAPI server (exposes edges as JSON for frontend)
│   │   ├── schemas.py                   ← Pydantic response models
│   │   └── dependencies.py              ← Shared FastAPI deps
│   ├── config/                          ← YAML config files
│   ├── streamlit_app.py                 ← Local Streamlit dashboard (standalone)
│   ├── market_scanner_app.py            ← Market scanner Streamlit page
│   ├── f1_model_lab.ipynb               ← F1 race prediction notebook
│   └── .env                             ← LOCAL ONLY — never commit
│
├── market_sentiment_tool/               ← Sub-System 2: Autonomous Paper Trader
│   ├── backend/                         ← Local Python intelligence engine
│   │   ├── orchestrator.py              ← LangGraph 3-agent swarm (MASTER BRAIN)
│   │   ├── quant_engine.py              ← Volume Profile + Order Flow Divergence analyzer
│   │   ├── ingestion.py                 ← Alpaca WebSocket tick streamer → SQLite WAL
│   │   ├── mcp_server.py                ← FastMCP ASGI server (Alpaca paper trade bridge)
│   │   ├── news_rag.py                  ← ChromaDB news ingestion for RAG context
│   │   ├── local_ticks.sqlite3          ← Local tick buffer (WAL mode, high throughput)
│   │   ├── chroma_db/                   ← ChromaDB vector store (financial news embeddings)
│   │   └── requirements.txt             ← Backend Python deps
│   ├── src/                             ← React app source
│   │   ├── components/                  ← UI components
│   │   ├── pages/                       ← Route pages
│   │   ├── hooks/                       ← Supabase real-time hooks
│   │   ├── contexts/                    ← React contexts
│   │   ├── integrations/                ← Supabase client config
│   │   └── types/                       ← TypeScript types
│   ├── supabase/                        ← Supabase migrations + edge functions
│   ├── index.html                       ← Vite entry
│   ├── vite.config.ts
│   ├── package.json                     ← Node deps (React, Lovable, Supabase JS)
│   └── .env                             ← LOCAL ONLY — Supabase + Alpaca keys
│
├── FPL_Optimizer/                       ← Sub-System 3: Sports Optimization Backend
│   ├── fpl_optimizer.py                 ← FPL lineup optimizer (PuLP LP solver)
│   ├── optimizer.py                     ← Generic multi-sport optimizer
│   ├── ml_engine.py                     ← LightGBM player performance predictor
│   ├── data_manager.py                  ← FPL/NBA/F1 API data fetchers
│   ├── market_scanner_app.py            ← Streamlit market scanner integration
│   ├── streamlit_app.py                 ← Main FPL Streamlit dashboard
│   ├── chatbot.py                       ← Gemini-powered sports chatbot
│   ├── ai_utils.py                      ← Gemini API utilities
│   ├── app.py                           ← Flask REST API server
│   ├── controller.py                    ← Route controller
│   ├── models.py                        ← SQLAlchemy ORM models
│   ├── train_model.py                   ← Model training script
│   ├── utils.py                         ← Shared helpers
│   └── .env                             ← LOCAL ONLY
│
├── SYSTEM_ARCH.md                       ← You are here
├── README.md                            ← Monorepo quick-start guide
└── .gitignore                           ← Root gitignore (covers all sub-systems)
```

---

## Sub-System 1: SP500 Predictor (Kalshi Edge Finder)

### Purpose
Find arbitrage edges in Kalshi prediction markets using official data sources that settle those contracts. NOT a general stock-price predictor — the financial markets component is explicitly labeled **Paper Trading / Educational Only**.

### Architecture Principle: Three-Tier Edge Finding

```
REAL EDGE (real money OK)          PAPER TRADING (educational only)
────────────────────────           ──────────────────────────────────
Weather Engine (NWS API)           Quant Engine (LightGBM on SPX/BTC)
Macro Engine (FRED API)            — Competes vs HFT, no real edge —
Fed Engine (CME FedWatch)          — 50% directional accuracy         
```

### Data Sources & Their Role

| Source | API | What It Drives |
|---|---|---|
| National Weather Service | `api.weather.gov` (free) | Weather Kalshi markets (NYC, Chicago, Miami, Austin temps) |
| FRED (Federal Reserve) | `fred.stlouisfed.org` | CPI prediction → Kalshi macro markets |
| CME FedWatch | Public scrape | Fed rate decisions → Kalshi rate markets |
| Alpaca Paper API | `alpaca.markets` | OHLCV data for ML paper trading |
| Kalshi REST API | `trading-api.kalshi.com` | Market prices, execution |
| FinBERT (HuggingFace) | Local model | News sentiment for trade validation |
| BART MNLI (HuggingFace) | Local model | Zero-shot news headline classification |
| DistilBERT NER | Local model | Entity extraction from Fed statements |
| Gemini Flash | Google AI API | Final AI scrutinizer (value-trap detection) |
| Tiingo | `tiingo.com` | 2-3yr hourly historical data for model training |

### Edge Detection Pipeline

```
1. [weather/macro/fed engine] → fetch official data
2. [market_scanner.py]        → fetch Kalshi market prices
3. [opportunity finder]       → compare model probability vs market price
                               → flag if edge > 8-15%
4. [sentiment_filter.py]      → FinBERT pre-screens news (free, local)
                               → if uncertain → escalate to Gemini
5. [ai_validator.py]          → Gemini Flash validates (blocks value traps)
6. [kalshi_feed.py]           → present to user / optionally auto-fill
7. [telegram_notifier.py]     → push Telegram alert (max 10/hr rate limit)
```

### Key Files to Know

- **`src/kalshi_feed.py`** — All Kalshi auth (RSA key) + market data fetching. The only file that should touch the Kalshi API directly.
- **`src/market_scanner.py`** — Aggregates output from all engines into one ranked opportunity list.
- **`src/ai_validator.py`** — Gemini Flash call. Only invoked post-FinBERT if confidence < 80%.
- **`scripts/background_scanner.py`** — Long-running daemon. Polls every 10 min, writes edges to Supabase.
- **`api/main.py`** — FastAPI server. The frontend reads edges from here (or directly from Supabase).

---

## Sub-System 2: Market Sentiment Trading Tool (Autonomous Paper Trader)

### Purpose
A production-grade autonomous paper trading platform. The React UI is a **display layer only**. All intelligence runs locally on your machine. Data persistence is routed through Supabase.

### Boot Order (CRITICAL — must follow this sequence)

```
Step 1: python backend/ingestion.py      ← Streams Alpaca ticks → local SQLite WAL
Step 2: python backend/news_rag.py       ← Ingests news → ChromaDB vector store
Step 3: python backend/orchestrator.py   ← LangGraph swarm starts polling
Step 4: python backend/mcp_server.py     ← FastMCP ASGI server starts (port 8080)
Step 5: npm run dev                      ← React dev server starts (port 5173)
```

### LangGraph 3-Agent Swarm Architecture

```
                    ┌─────────────────────────────────────┐
                    │          orchestrator.py             │
                    │     (LangGraph State Machine)        │
                    └──────────────┬──────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              ▼                                          ▼
   ┌─────────────────────┐              ┌───────────────────────┐
   │  Agent 1: QUANT     │              │  Agent 2: MACRO       │
   │  (Deterministic)    │              │  (Stochastic LLM)     │
   │                     │              │                       │
   │ quant_engine.py:    │              │ Local LLM (GLM-5,     │
   │ - Volume Profile    │              │  Kimi K2.5, etc.)     │
   │ - Point of Control  │              │ ChromaDB RAG context  │
   │ - Flow Divergence   │              │ → macro_signal float  │
   │ → quant_signal float│              └───────────────────────┘
   └─────────────────────┘                          │
              │                                     │
              └──────────────┬──────────────────────┘
                             ▼
              ┌──────────────────────────────────┐
              │  Agent 3: CIO SUPERVISOR          │
              │  (Final decision maker)           │
              │                                  │
              │  combined = (quant + macro) / 2  │
              │  Checks: kill switch, divergence │
              │  Outputs: BUY / SELL / HOLD      │
              └──────────────┬───────────────────┘
                             ▼
              ┌──────────────────────────────────┐
              │  execute_trade()                  │
              │  → writes to Supabase trades     │
              │  → FastMCP → Alpaca Paper API    │
              └──────────────────────────────────┘
```

### Data Flow (Detailed)

```
Alpaca WebSocket (L2 ticks)
        │
        ▼
ingestion.py  ───────────────────────── writes ──▶ local_ticks.sqlite3 (WAL)
                                                           │
                                              poll every 10s
                                                           │
                                                           ▼
                                              orchestrator.py
                                           ┌──────────────────────────┐
                                           │ poll_latest_ticks()      │
                                           │ aggregate_market_snapshot│
                                           │                          │
                                           │ Graph.stream(state):     │
                                           │  → quant_analyst node    │ ← quant_engine.py
                                           │  → macro_analyst node    │ ← local LLM + ChromaDB
                                           │  → cio_supervisor node   │
                                           │  → execute node          │
                                           └──────────────────────────┘
                                                           │
                                                           ▼
                                              Supabase PostgreSQL
                                              ┌────────────────────┐
                                              │ trades             │
                                              │ agent_logs         │
                                              │ portfolio_state    │
                                              │ user_settings      │
                                              └────────────────────┘
                                                           │
                                               WebSocket subscription
                                                           │
                                                           ▼
                                              React Frontend (Vite)
                                              - Live portfolio equity
                                              - Trade history table
                                              - Order Flow widget
                                              - Kill Switch toggle
```

### Quantitative Engine Details (`quant_engine.py`)

The quant engine processes raw tick arrays and outputs two primary signals:

| Signal | Method | Output |
|---|---|---|
| **Volume Profile** | Build price histogram from tick data; find Point of Control (POC), Value Area High/Low, volume skewness | `poc`, `skewness`, `regime` (BULLISH/BEARISH/NEUTRAL) |
| **Flow Divergence** | Compare buy delta vs sell delta across time windows; detect buyer/seller exhaustion | `divergence_warning`, `divergence_reason`, `delta` |
| **Aggregate Signal** | Weighted average of all symbol signals | `signal` float (-1 to +1), `regime` string |

### Local LLM Stack

| Model | Quantization | Role |
|---|---|---|
| GLM-5 | MXFP4 | Primary reasoning + CIO debate |
| Kimi K2.5 | NVFP4 | Agent swarm strategy debates |
| DeepSeek V3.2 Speciale | MXFP4 | Structured execution logic |

All models run via `llama.cpp` or `vLLM` on local GPU. The LLM endpoint is `http://127.0.0.1:8080/v1` (Ollama-compatible format). **Never expose this to 0.0.0.0.**

### FastMCP Execution Bridge

`mcp_server.py` runs a local ASGI server that wraps Alpaca Paper Trading API calls as `@mcp.tool()` decorators. Before any trade executes, the tool:
1. Checks `user_settings.auto_trade_enabled` from Supabase (Kill Switch)
2. Validates against hard-coded risk constraints (max drawdown, position limits)
3. Only then POSTs to Alpaca

### Kill Switch Protocol

The **Kill Switch** is a boolean toggle in the Supabase `user_settings` table. The React UI writes it; the Python orchestrator reads it every 10 seconds before approving any trade. If `auto_trade_enabled = false`, the CIO will always return `HOLD`.

---

## Sub-System 3: FPL Optimizer (Sports Backend)

### Purpose
Optimize sports lineups and provide AI-powered sports analytics. Exposes both a Streamlit dashboard and a Flask REST API. Writes optimization results to Supabase for the frontend to display.

### Architecture

```
External APIs (FPL, NBA, F1) 
        │
        ▼
data_manager.py ──────────────────────▶ fetches raw player/race data
        │
        ▼
ml_engine.py (LightGBM) ─────────────▶ predicts player performance scores
        │
        ▼
optimizer.py / fpl_optimizer.py ─────▶ PuLP LP solver
  (Linear Programming)                  constraints: budget, position limits,
                                         team caps, captain multiplier
        │
        ├─▶ streamlit_app.py ──────────▶ Streamlit UI (local)
        ├─▶ app.py (Flask REST) ────────▶ JSON API → market_sentiment_tool frontend
        └─▶ chatbot.py (Gemini) ────────▶ Natural language Q&A about lineups
```

### Data Sources

| Source | What |
|---|---|
| FPL API (`fantasy.premierleague.com/api`) | Player stats, prices, fixtures, ownership |
| NBA stats API | Player game logs, advanced stats |
| FastF1 Python library | F1 lap times, race results, telemetry |
| Gemini Pro | Chatbot responses + lineup reasoning |

### Optimization Constraints (FPL)

- Budget: 100.0 (FPL units)
- Squad: 15 players (2 GKP, 5 DEF, 5 MID, 3 FWD)
- Starting XI: 11 players from squad
- Max 3 players from same Premier League club
- Captain: 2× points multiplier applied to predicted score
- Objective: Maximize expected points (xP)

---

## Shared Database (Supabase PostgreSQL)

All three sub-systems share one Supabase project. Row Level Security (RLS) is enabled on all tables.

### Schema

```sql
-- ════════════════════════════════════════════
-- TABLE 1: Trades (paper trade executions)
-- ════════════════════════════════════════════
CREATE TABLE trades (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp        TIMESTAMPTZ DEFAULT NOW(),
    symbol           VARCHAR(10) NOT NULL,
    side             VARCHAR(4) CHECK (side IN ('BUY', 'SELL')),
    qty              NUMERIC NOT NULL,
    execution_price  NUMERIC,
    entry_price      NUMERIC,               -- For M2M PnL calculation
    status           VARCHAR(20) DEFAULT 'PENDING',  -- PENDING | OPEN | CLOSED
    pnl              NUMERIC DEFAULT 0.0,   -- Updated live by orchestrator (M2M)
    agent_confidence NUMERIC CHECK (agent_confidence >= 0 AND agent_confidence <= 1),
    user_id          UUID REFERENCES auth.users(id)
);

-- ════════════════════════════════════════════
-- TABLE 2: Agent Logs (full observability)
-- ════════════════════════════════════════════
CREATE TABLE agent_logs (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp         TIMESTAMPTZ DEFAULT NOW(),
    module            VARCHAR(50) NOT NULL,  -- 'orchestrator.quant' | 'orchestrator.macro' | 'orchestrator.cio'
    log_level         VARCHAR(10) DEFAULT 'INFO',
    message           TEXT NOT NULL,
    reasoning_context JSONB,                -- Full quant_context dict for debugging
    user_id           UUID REFERENCES auth.users(id)
);

-- ════════════════════════════════════════════
-- TABLE 3: Portfolio State (live snapshot)
-- ════════════════════════════════════════════
CREATE TABLE portfolio_state (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp       TIMESTAMPTZ DEFAULT NOW(),
    total_equity    NUMERIC NOT NULL,         -- Base ($100k) + unrealized PnL
    available_cash  NUMERIC NOT NULL,
    open_positions  JSONB NOT NULL,           -- OrderFlowContext: {regime, skew, poc, divergence}
    user_id         UUID REFERENCES auth.users(id)
);

-- ════════════════════════════════════════════
-- TABLE 4: User Settings (Kill Switch + risk params)
-- ════════════════════════════════════════════
CREATE TABLE user_settings (
    user_id              UUID PRIMARY KEY REFERENCES auth.users(id),
    auto_trade_enabled   BOOLEAN DEFAULT FALSE,    -- THE KILL SWITCH
    max_daily_drawdown   NUMERIC DEFAULT 0.05,     -- 5% hard stop
    updated_at           TIMESTAMPTZ DEFAULT NOW()
);
```

### RLS Access Rules

| Actor | Key | Access |
|---|---|---|
| Python backends | `SUPABASE_SERVICE_ROLE_KEY` | Full read/write, bypasses RLS |
| React frontend | `SUPABASE_ANON_KEY` | Read-only on trades/portfolio; write-only on user_settings |

### Real-Time Subscriptions (React)

The React frontend uses Supabase's WebSocket real-time channel to subscribe to:
- `trades` table → updates ActivePositions widget
- `portfolio_state` table → updates equity chart + OrderFlowContext widget
- `agent_logs` table → updates the live reasoning feed

---

## API Contracts (Inter-System JSON)

### SP500 Predictor → Frontend (via FastAPI or Supabase)

Edge opportunity object:
```json
{
  "engine": "Weather | Macro | Fed | Quant",
  "asset": "NYC | CPI | SPX | BTC",
  "market_title": "NYC High Temp 85-86°F Tomorrow",
  "strike": 85,
  "action": "BUY YES | BUY NO",
  "model_probability": 78.5,
  "market_price": 60.0,
  "edge": 18.5,
  "confidence": 82.0,
  "reasoning": "NWS forecasts 87°F with 82% confidence.",
  "data_source": "NWS Official API (Settlement Source)"
}
```

### Orchestrator → portfolio_state (Supabase JSONB)

The `open_positions` field of `portfolio_state` is a flat JSON dict consumed by the React OrderFlowContext widget:
```json
{
  "regime": "BULLISH | BEARISH | NEUTRAL",
  "skew": 0.42,
  "poc": 448.75,
  "divergence": "BULLISH | BEARISH | WARNING | null"
}
```

### FPL Optimizer → Frontend (Flask REST)

Optimized lineup response:
```json
{
  "sport": "fpl",
  "budget_used": 99.4,
  "expected_points": 68.2,
  "captain": "Salah",
  "starting_xi": [
    { "name": "Raya", "position": "GKP", "price": 5.0, "xP": 4.2 }
  ],
  "bench": []
}
```

---

## Tech Stack Matrix

| Layer | SP500 Predictor | Market Sentiment Tool | FPL Optimizer |
|---|---|---|---|
| **Language** | Python 3.11+ | Python 3.11+ / TypeScript | Python 3.11+ |
| **ML** | LightGBM, FinBERT, BART, DistilBERT | LightGBM (quant_engine), local LLMs | LightGBM |
| **AI/LLM** | Gemini Flash (scrutinizer) | GLM-5, Kimi K2.5, DeepSeek V3.2 (local) | Gemini Pro (chatbot) |
| **Orchestration** | `scripts/background_scanner.py` | LangGraph state machine | Linear Python pipeline |
| **Execution Bridge** | Kalshi REST + RSA auth | FastMCP → Alpaca Paper API | None (manual) |
| **Data Store** | Supabase (remote) + local files | SQLite WAL (local) + Supabase (remote) | Supabase (remote) + in-memory |
| **Vector DB** | None | ChromaDB (`all-MiniLM-L6-v2`) | None |
| **UI** | Streamlit (local) | React/Vite + Lovable.dev | Streamlit (local) |
| **API** | FastAPI | Supabase real-time | Flask |
| **Frontend State** | Supabase direct | Supabase real-time WebSocket | Supabase direct |

---

## Environment Variable Inventory

Each sub-system has its own `.env`. Here is the complete key inventory across all three.

### SP500 Predictor `.env`
```
APCA_API_KEY_ID=          # Alpaca Paper API key
APCA_API_SECRET_KEY=       # Alpaca Paper API secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
KALSHI_API_KEY=            # Kalshi account API key
KALSHI_PRIVATE_KEY_PATH=./kalshi_private_key.pem   # RSA private key path
FRED_API_KEY=              # Federal Reserve FRED API key
GEMINI_API_KEY=            # Google AI Gemini API key
SUPABASE_URL=              # Shared Supabase project URL
SUPABASE_ANON_KEY=         # Supabase anon (read-only)
SUPABASE_SERVICE_ROLE_KEY= # Supabase service role (write)
TELEGRAM_BOT_TOKEN=        # Telegram alert bot
TELEGRAM_CHAT_ID=          # Telegram channel chat ID
DISCORD_WEBHOOK_URL=       # Discord webhook for alerts
TIINGO_API_KEY=            # Tiingo historical data
```

### Market Sentiment Tool `.env`
```
SUPABASE_URL=              # Same Supabase project
SUPABASE_ANON_KEY=         # For React frontend reads
SUPABASE_SERVICE_ROLE_KEY= # For Python backend writes
APCA_API_KEY_ID=           # Alpaca Paper API key
APCA_API_SECRET_KEY=       # Alpaca Paper API secret
ALPACA_BASE_URL=https://paper-api.alpaca.markets
LOCAL_LLM_ENDPOINT=http://127.0.0.1:8080/v1    # Local LLM server
LOCAL_LLM_MODEL_NAME=GLM-5-MXFP4
```

### FPL Optimizer `.env`
```
GEMINI_API_KEY=            # Gemini Pro for chatbot
SUPABASE_URL=              # Same Supabase project
SUPABASE_ANON_KEY=
SUPABASE_SERVICE_ROLE_KEY=
```

---

## Integration Rules (Hard Rules — Never Break These)

1. **Frontend is display-only.** The React app in `market_sentiment_tool/` **never** contains business logic, model inference, or API keys for brokerage accounts. It only reads from Supabase and writes the kill switch.

2. **Write business logic in the Python backends first.** If adding a new feature (e.g., NBA props), the sequence is always:
   - Write data pipeline in `FPL_Optimizer/` or `SP500 Predictor/`  
   - Define the JSON schema the Python backend will write to Supabase
   - THEN update the React frontend to display it

3. **Local LLMs never bind to 0.0.0.0.** All local daemons (LangGraph, FastMCP, llama.cpp) bind strictly to `127.0.0.1`.

4. **Brokerage keys never leave the local machine.** Alpaca and Kalshi keys live only in local `.env` files. They are never written to Supabase, never committed to git.

5. **Kill Switch must be checked before every execution.** The FastMCP `execute_paper_trade` tool reads `user_settings.auto_trade_enabled` from Supabase on every invocation. No exceptions.

6. **quant_engine.py is paper trading only.** The LightGBM financial price predictor (SPX/BTC/ETH/QQQ) is explicitly marked educational. It should never receive real-money execution paths.

7. **Kalshi edge threshold: 8% minimum.** No weather, macro, or fed trade should be presented unless the edge exceeds 8%. Weather trades require NWS confidence > 70%. Macro trades require FRED alignment + FinBERT confirmation.

8. **FinBERT before Gemini.** The sentiment pipeline always runs FinBERT locally first. Only if FinBERT confidence < 80% does it escalate to the Gemini API call. This saves API credits.

---

## Security Posture

| Threat | Mitigation |
|---|---|
| Brokerage key leak | Keys in local `.env` only; never in Supabase or git |
| LLM prompt injection | All LLM inputs are structured prompts with strict output format (JSON); parsed deterministically |
| Unauthorized trade execution | Kill switch checked in FastMCP tool before every Alpaca POST |
| Runaway losses | Hard-coded max daily drawdown (5%) enforced in CIO logic; LLM cannot override |
| Database RLS bypass | Python uses service role key (server only); React uses anon key (read-only) |
| Network exposure | All local daemons bind to 127.0.0.1 only |

---

## AI Models in Use — Roles & Placement

| Model | Type | Where | Role |
|---|---|---|---|
| LightGBM | Tree ensemble | SP500 Predictor `src/model_daily.py` | SPX/BTC directional price prediction (paper trading) |
| LightGBM | Tree ensemble | FPL Optimizer `ml_engine.py` | FPL/NBA player performance prediction |
| LightGBM | Tree ensemble | Market Sentiment `backend/quant_engine.py` | Volume profile signal scoring |
| FinBERT (ProsusAI) | Transformer | SP500 Predictor `src/sentiment_filter.py` | Fed speech hawkish/dovish sentiment (local, free) |
| BART MNLI (Facebook) | Transformer | SP500 Predictor `src/sentiment_filter.py` | Zero-shot news headline classification (local, free) |
| DistilBERT NER | Transformer | SP500 Predictor `src/sentiment_filter.py` | Named entity extraction from Fed statements (local, free) |
| all-MiniLM-L6-v2 | Sentence Transformer | Market Sentiment `backend/chroma_db/` | News embedding for RAG vector store |
| GLM-5 (MXFP4) | Local LLM | Market Sentiment orchestrator | Primary macro reasoning + CIO swarm debate |
| Kimi K2.5 (NVFP4) | Local LLM | Market Sentiment orchestrator | Agent swarm strategy debate |
| DeepSeek V3.2 Speciale | Local LLM | Market Sentiment orchestrator | Structured execution logic |
| Gemini Flash | Cloud API | SP500 Predictor `src/ai_validator.py` | Trade value-trap detection (only called if FinBERT uncertain) |
| Gemini Pro | Cloud API | FPL Optimizer `chatbot.py` | Natural language sports chatbot |

---

*Last updated: 2026-03-23 by Antigravity (automated architecture sync)*
