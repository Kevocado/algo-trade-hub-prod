# ==========================================================
# Algo-Trade-Hub — Root Procfile
# PYTHONPATH=. is injected into every process so that
# `from shared.config import ...` resolves without sys.path hacks.
# ==========================================================

# React frontend API: FPL optimizations + Kalshi scanner status
api: PYTHONPATH=. uvicorn shared.api_server:app --host 0.0.0.0 --port 8000

# FastMCP Alpaca bridge: strictly internal, bound to 127.0.0.1:5100
# The LangGraph orchestrator calls this to execute / close paper trades.
mcp: PYTHONPATH=. python market_sentiment_tool/backend/mcp_server.py

# LangGraph swarm: continuous Quant → Macro → CIO → Execute pipeline
orchestrator: PYTHONPATH=. python market_sentiment_tool/backend/orchestrator.py

# Slow scanner: FRED macro data + Kalshi market discovery (every 10 min)
scanner_slow: PYTHONPATH=. python shared/background_scanner.py

# Fast scanner: NWS weather alerts + Kalshi weather-market arbitrage (every 60-90 s)
# This process is intentionally separate so slow FRED/API calls never block it.
scanner_fast: PYTHONPATH=. python shared/fast_scanner.py
