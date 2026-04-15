**SYSTEM CONTEXT & ARCHITECTURE DIRECTIVE**

**Project:** 2026 Autonomous Agentic Paper Trading Platform (Quantitative Order Flow & Sentiment Dashboard)**Role:** Lead MLOps Engineer & Quantitative Systems Architect**Design Philosophy:** Local-First Inference, Decoupled Cloud State, Strict Division of Intelligence, and "Paper-First" execution.

**1. Core Technology Stack**

**This platform utilizes a highly decoupled, production-grade 2026 tech stack to separate heavy local compute from real-time cloud states and user interfaces.**

**• ****The Frontend (React / Lovable.dev):** A lightweight React-based web dashboard that subscribes to Supabase's real-time Postgres tables via WebSockets. It displays live portfolio updates, trade history, performance calendars (P&L tracking), and governs the crucial "Agent Kill Switch" toggle.

**• ****The Database & Backend (Supabase):** A cloud-hosted PostgreSQL instance acting as the central state manager. It synchronizes the local Python engine's outputs (executions, logs, P&L) with the React frontend using the `supabase-py` client and Row Level Security (RLS).

**• ****The Intelligence Engine (Local Python):** A background trading daemon running on dedicated local hardware.

**    ◦ ****Orchestration:****LangGraph** models the agentic workflow as a deterministic state machine, ensuring predictable decision routing.

**    ◦ ****Execution Bridge:****FastMCP** (Model Context Protocol) runs a local ASGI server to securely bridge the LangGraph reasoning engine to the Alpaca Paper Trading API via `@mcp.tool()` decorators**.**

**    ◦ ****Quantitative Engine (Deterministic):****LightGBM** and Time-Series Transformers process dense L2 tick arrays, Cumulative Volume Delta, and Order Flow imbalances (Point of Control, Value Area) to detect mathematical edges**.**

**    ◦ ****Qualitative Engine (Stochastic):** Open-weight Large Language Models process unstructured data (financial news, FOMC transcripts, sentiment) via **llama.cpp** or  **vLLM** **.**

**2. Model Selection & Quantization (2026 Standards)**

**The platform relies strictly on state-of-the-art open-source models, utilizing extreme quantization to run efficiently on consumer/edge GPUs without catastrophic KV Cache bloat.**

**• ****Target Models:**

**    ◦ ****GLM-5 (Reasoning):** Ranked as a top open-source reasoning model, excelling at complex logic and coding tasks**.**

**    ◦ ****Kimi K2.5:** Utilized for "Agent Swarm" workflows where multiple sub-agents debate strategies**.**

**    ◦ ****DeepSeek V3.2 Speciale:** Used for highly structured logic and coding execution**.**

**• ****Quantization:** The system leverages **MXFP4** (Microscaling 4-bit Floating Point) and **NVFP4** formats. This microscaling technique significantly reduces VRAM footprint and increases token generation throughput by up to 35% while maintaining lower perplexity and near-lossless precision compared to older Q4 formats**.**

**3. Data Flow & Concurrency Strategy**

**Because **`llama.cpp` inference and LightGBM processing are CPU/GPU-bound, the system uses a strict **Multi-Process Decoupling Strategy** so reasoning does not block live market data ingestion.

**The Pipeline:**

**1. ****Process 1 (Ingestion/Asyncio):** Alpaca WebSocket streams L2/Tick data asynchronously and writes it to a local fast-access queue (Redis or multiprocessing queue). It also listens to Supabase for "Kill Switch" toggles.

**2. ****Process 2 (Intelligence/Sync):** LangGraph polls the queue.

**    ◦ ***Branch A:* LightGBM evaluates order flow (Volume Delta, Value Area High/Low)**.**

**    ◦ ***Branch B:* Local LLM (via llama.cpp) evaluates sentiment using strict Vector DB RAG (Milvus/Qdrant).

**3. ****Process 3 (Execution/FastMCP):** LangGraph synthesizes data and requests an action. It calls the local FastMCP tool server (`127.0.0.1:8080`)**.**

**4. ****Execution & Sync:** FastMCP executes the paper trade on Alpaca, returns the confirmation to LangGraph, and the Python daemon pushes the state update to Supabase via `supabase-py`.

**5. ****Frontend Update:** Supabase broadcasts the update to the Lovable.dev React UI.

**4. Database Schema (Supabase PostgreSQL)**

**State management is normalized into four core tables with Row Level Security (RLS) enabled.**

```
-- Table 1: Trades
CREATE TABLE trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    symbol VARCHAR(10) NOT NULL,
    side VARCHAR(4) CHECK (side IN ('BUY', 'SELL')),
    qty NUMERIC NOT NULL,
    execution_price NUMERIC,
    status VARCHAR(20) DEFAULT 'PENDING',
    pnl NUMERIC DEFAULT 0.0,
    agent_confidence NUMERIC CHECK (agent_confidence >= 0 AND agent_confidence <= 1)
);

-- Table 2: Agent Logs (Observability)
CREATE TABLE agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    module VARCHAR(50) NOT NULL, -- 'LightGBM', 'llama.cpp', 'FastMCP'
    log_level VARCHAR(10) DEFAULT 'INFO',
    message TEXT NOT NULL,
    reasoning_context JSONB 
);

-- Table 3: Portfolio State
CREATE TABLE portfolio_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    total_equity NUMERIC NOT NULL,
    available_cash NUMERIC NOT NULL,
    open_positions JSONB NOT NULL
);

-- Table 4: User Settings (The Kill Switch)
CREATE TABLE user_settings (
    user_id UUID PRIMARY KEY REFERENCES auth.users(id),
    auto_trade_enabled BOOLEAN DEFAULT FALSE,
    max_daily_drawdown NUMERIC DEFAULT 0.05,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**5. Security & Compliance Posture**

**To protect the system from supply chain attacks, indirect prompt injections, and API leaks:**

**1. ****Network Isolation:** All local daemons, the LangGraph orchestrator, and FastMCP servers must explicitly bind strictly to the loopback address (`127.0.0.1`). They must **never** bind to `0.0.0.0` or be exposed to the public internet**.**

**2. ****Zero Cloud Exposure:** Brokerage API keys (Alpaca) are stored entirely in a local `.env` file or local secrets manager on the host machine. They are never pushed to Supabase or the Lovable frontend.

**3. ****Pre-Action Authorization (Kill Switch):** Inside the FastMCP `@mcp.tool()` function, the Python logic physically checks the `auto_trade_enabled` variable synced from Supabase *before* sending a POST request to Alpaca. If disabled, the tool rejects the call.

**4. ****Hard-Coded Risk Constraints:** Max-drawdown limits, daily loss limits, and position sizing rules are hard-coded into the deterministic Python execution loop. The LLM cannot override these limits mathematically.

**5. ****Database Roles:** The Python engine uses the securely stored Supabase Service Role Key to push data. The React frontend strictly uses the public Anon Key to read data and toggle settings.
