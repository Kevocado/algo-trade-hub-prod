---
type: "query"
date: "2026-04-13T15:39:24.666829+00:00"
question: "What are the canonical high-value edges for the Kalshi trading system?"
contributor: "graphify"
source_nodes: ["evaluate_crypto_edge()", "_latest_crypto_feature_row()", "build_features()", "market_resolution()", "resolve_kalshi_market()", "submit_kalshi_order()", ".get_settlements()"]
---

# Q: What are the canonical high-value edges for the Kalshi trading system?

## Answer

Model_Inference depends_on Feature_Contract and maps to evaluate_crypto_edge() -> _latest_crypto_feature_row() -> build_features(). Market_Ticker resolves_via Settlement_Rules and maps to market_resolution() -> resolve_kalshi_market() -> KalshiPortfolio.get_settlements(). Strategy_Logic calls Kalshi_Execution_Bridge and maps to market_resolution() -> submit_kalshi_order().

## Source Nodes

- evaluate_crypto_edge()
- _latest_crypto_feature_row()
- build_features()
- market_resolution()
- resolve_kalshi_market()
- submit_kalshi_order()
- .get_settlements()