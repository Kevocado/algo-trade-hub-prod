# Project State: Algo-Trade-Hub

## 🗓️ Last Updated: 2026-04-08
**Current Status:** Crypto Demo Runtime Live on VPS

---

## ✅ Accomplished Today
- **Runtime Bootstrap Hardening**: Consolidated the backend onto a single canonical root `.env`, added explicit validation/fail-fast startup, and enforced canonical Kalshi hosts.
- **Kalshi Demo Auth Debugged**: Fixed the auth probe path-signing bug, validated a working demo API key + PEM pair, and brought the VPS onto authenticated demo REST + WS.
- **Crypto Inference Last-Mile**: Aligned live crypto inference to the 30-feature notebook schema, added Alpaca→`yfinance` historical backfill, and documented the `ta`/`yfinance` PM2 venv requirements.
- **Crypto Demo Execution Path**: The `crypto-sniper` worker now reaches Kalshi demo WS, evaluates signals, resolves markets, and submits demo trades through the Kalshi REST bridge.
- **Async Telegram Operator Plane**: Replaced the old threaded Telegram notifier with an async `aiohttp` implementation, added operator commands (`/crypto_status`, `/balance`, `/positions`, `/trades`, `/crypto_scan`), and launched it alongside the crypto worker.
- **Decoupled Operator State**: Added Supabase-backed crypto operator persistence (`crypto_signal_events`, crypto-specific trading control flags, enriched trade metadata) so Telegram reads durable state instead of worker memory.
- **Insufficient-Funds Safeguard**: Kalshi insufficient-funds rejections now disable further crypto trading in Supabase and generate operator alerts instead of repeatedly retrying.

## 🟢 Currently Working / Stable
- **Crypto VPS Runtime**: `/root/kalshibot/market_sentiment_tool/backend/orchestrator.py` boots cleanly under PM2 as `crypto-sniper`, authenticates to Kalshi demo, and streams ticker data.
- **Signal Pipeline**: The BTC/ETH LightGBM models now receive the expected live feature frame, including long-window indicators via historical backfill.
- **Execution Bridge**: Kalshi demo order submission is wired through `market_sentiment_tool/backend/mcp_server.py` with Supabase-backed kill-switch controls.
- **Operator Visibility**: Supabase now holds trade attempts, crypto signal events, portfolio snapshots, and operator logs; Telegram commands read from Supabase/Kalshi directly.
- **Frontend**: The React/Vite dashboard and existing Supabase-backed UI remain intact.

## 🚀 Next Immediate Task
- **Apply Migration on VPS Supabase**: Run `market_sentiment_tool/supabase/migrations/20260408224000_crypto_operator_plane.sql` so the async Telegram/operator-plane tables and user-settings columns exist in prod.
- **End-to-End Demo Validation**: Confirm a full threshold-crossing opportunity, Telegram alert, trade submission, and `/balance` + `/trades` Telegram command responses against the funded demo account.
- **Threshold/Signal Tuning**: If the worker connects but rarely emits actionable predictions, log or tune threshold-crossing behavior without weakening the model feature contract.
- **Operator Controls**: Add explicit Telegram or admin-path controls for re-enabling crypto trading after an insufficient-funds lockout, if needed.
