---
type: "query"
date: "2026-04-13T15:39:24.666490+00:00"
question: "How does a Kalshi trade move from signal to settlement in this repo?"
contributor: "graphify"
source_nodes: ["evaluate_crypto_edge()", "_latest_crypto_feature_row()", "build_features()", "market_resolution()", "resolve_kalshi_market()", "submit_kalshi_order()", "write_trade_to_supabase()", "write_crypto_signal_event()", ".get_settlements()"]
---

# Q: How does a Kalshi trade move from signal to settlement in this repo?

## Answer

Signal generation starts at evaluate_crypto_edge(), which depends on _latest_crypto_feature_row() and shared/crypto_features.py::build_features(). market_resolution() resolves the executable market ticker, checks controls, cooldown, and price/edge, then hands execution to market_sentiment_tool/backend/mcp_server.py::submit_kalshi_order(). The runtime persists trade state with write_trade_to_supabase() and signal telemetry with write_crypto_signal_event(). Operators inspect outcomes through TelegramNotifier and shadow_performance.py, and terminal truth is observed through KalshiPortfolio.get_settlements().

## Source Nodes

- evaluate_crypto_edge()
- _latest_crypto_feature_row()
- build_features()
- market_resolution()
- resolve_kalshi_market()
- submit_kalshi_order()
- write_trade_to_supabase()
- write_crypto_signal_event()
- .get_settlements()