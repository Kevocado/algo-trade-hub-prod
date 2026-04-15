---
title: Kalshi Trading System Map
type: system_map
domain: universal
status: active
settlement_source: kalshi_and_domain_specific_authorities
tags:
  - graphify
  - architecture
  - kalshi
summary: Graph-backed map of the Kalshi trading system from model signal to market resolution, execution, operator monitoring, shadow visualization, and settlement observation.
---

# Kalshi Trading System Map

## Graph Baseline
- Source graph: `graphify-out/graph.json`
- Source report: `graphify-out/GRAPH_REPORT.md`
- Graph snapshot date: `2026-04-13`
- Graph size: `1520` nodes, `2357` edges, `163` communities
- Primary runtime hub discovered by graphify: `TelegramNotifier`

## Normalized High-Value Edges

### `Model_Inference -> depends_on -> Feature_Contract`
- Concrete graph anchors:
  - `market_sentiment_tool/backend/orchestrator.py::evaluate_crypto_edge()`
  - `market_sentiment_tool/backend/orchestrator.py::_latest_crypto_feature_row()`
  - `shared/crypto_features.py::build_features()`
- Meaning:
  - Live model inference is downstream from the canonical feature contract.
  - Any domain engine must expose a stable feature builder before inference is safe.

### `Market_Ticker -> resolves_via -> Settlement_Rules`
- Concrete graph anchors:
  - `market_sentiment_tool/backend/orchestrator.py::market_resolution()`
  - `market_sentiment_tool/backend/orchestrator.py::resolve_kalshi_market()`
  - `SP500 Predictor/src/kalshi_portfolio.py::KalshiPortfolio.get_settlements()`
  - `market_sentiment_tool/backend/signal_events.py`
- Meaning:
  - A raw signal does not become executable until it resolves to a concrete Kalshi market ticker.
  - Final truth is closed by Kalshi settlement records and the domain authority that underlies that market.
  - Weather settlement remains tied to NWS authority; crypto settlement is observed through Kalshi portfolio settlement history.
  - Canonical operator event storage now lives in `signal_events`, with `crypto_signal_events` retained only as a crypto compatibility view.

### `Strategy_Logic -> calls -> Kalshi_Execution_Bridge`
- Concrete graph anchors:
  - `market_sentiment_tool/backend/orchestrator.py::market_resolution()`
  - `market_sentiment_tool/backend/mcp_server.py::submit_kalshi_order()`
- Meaning:
  - Strategy logic must not submit orders directly.
  - The execution bridge is the choke point for kill-switch enforcement, signed Kalshi order submission, and execution logging.

### `Shadow_Visualization -> reads_from -> Signal_Timeline`
- Concrete graph anchors:
  - `SP500 Predictor/api/main.py::get_shadow_performance()`
  - `SP500 Predictor/scripts/shadow_performance.py::build_shadow_timeline_response()`
  - `market_sentiment_tool/src/pages/ShadowBacktester.tsx`
- Meaning:
  - Visual backtesting is a read-only surface built on canonical `signal_events` plus realized next-hour price moves.
  - FastAPI remains the computed-data transport layer; the React dashboard renders the timeline without querying Supabase directly.

## Single Trade Flow
1. `evaluate_crypto_edge()` ingests a live ticker update and pulls the latest canonical feature row via `_latest_crypto_feature_row()`.
2. `_latest_crypto_feature_row()` depends on `shared/crypto_features.py::build_features()` to produce the model-ready feature contract.
3. `evaluate_crypto_edge()` computes `P(YES)`, records inference telemetry, and emits a trade signal only when the domain thresholds are satisfied.
4. `market_resolution()` resolves the trade signal into a concrete Kalshi market via `resolve_kalshi_market()`, using live spot data and active market metadata.
5. `market_resolution()` checks trade controls, cooldown rules, best bid/offer, and minimum edge before allowing execution.
6. If the edge survives, `market_resolution()` calls the Kalshi execution bridge in `market_sentiment_tool/backend/mcp_server.py::submit_kalshi_order()`.
7. The runtime persists execution state through `write_trade_to_supabase()` and signal telemetry through the canonical `signal_events` store.
8. Operators inspect the live state through `SP500 Predictor/src/telegram_notifier.py` using `/scan {domain}` and post-trade accuracy through `SP500 Predictor/scripts/shadow_performance.py` using `/performance {domain}`.
9. The visual backtester consumes the same computed shadow series through `SP500 Predictor/api/main.py::get_shadow_performance()` and renders it in `market_sentiment_tool/src/pages/ShadowBacktester.tsx` at `/shadow`.
10. The trade reaches terminal truth when Kalshi closes the market and settlement is observable through `KalshiPortfolio.get_settlements()` plus the relevant domain settlement authority.

## Discovery Order Going Forward
1. Read `graphify-out/GRAPH_REPORT.md` for god nodes and major communities.
2. Use `graphify explain` and `graphify path` against `graphify-out/graph.json` before broad file search.
3. Use this note as the universal entry point for cross-domain system traversal.
