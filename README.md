# Algo-Trade-Hub

A unified quantitative trading and sports analytics monorepo. Three sub-systems work together — a prediction market edge-finder, an autonomous paper trading platform, and a sports optimization engine — all sharing a central Supabase database.

> **Full architecture reference:** [`SYSTEM_ARCH.md`](./SYSTEM_ARCH.md)

---

## Repository Structure

```
Algo-Trade-Hub/
├── SP500 Predictor/        # Python ML & Kalshi edge-finding backend
├── market_sentiment_tool/  # React frontend + LangGraph orchestration engine
├── FPL_Optimizer/          # Python sports optimization backend (FPL, F1, NBA)
├── SYSTEM_ARCH.md          # ← Master architecture reference (read this first)
└── README.md
```

---

## Sub-Systems at a Glance

| Sub-System | Stack | Role |
|---|---|---|
| `SP500 Predictor` | Python, LightGBM, FinBERT, Alpaca, FRED | Finds edge in Kalshi prediction markets via weather/macro/quant engines |
| `market_sentiment_tool` | React/Vite, Python, LangGraph, FastMCP, Supabase | Autonomous paper trading dashboard with 3-agent AI swarm |
| `FPL_Optimizer` | Python, PuLP, Streamlit, Gemini | Sports lineup optimization (FPL, F1, NBA) and chatbot |

---

## Quick Start

### SP500 Predictor (Kalshi Edge Finder)
```bash
cd "SP500 Predictor"
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

### Market Sentiment Tool (Trading Dashboard)
```bash
# Terminal 1 — Data ingestion
cd market_sentiment_tool/backend
python ingestion.py

# Terminal 2 — LangGraph orchestrator
python orchestrator.py

# Terminal 3 — FastMCP execution bridge
python mcp_server.py

# Terminal 4 — React frontend
cd market_sentiment_tool
npm install && npm run dev
```

### FPL Optimizer
```bash
cd FPL_Optimizer
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

---

## Environment Variables

Each sub-system has its own `.env`. See `SYSTEM_ARCH.md § Environment Variables` for a full key inventory.

**Never commit `.env` files or `.pem` keys.**
