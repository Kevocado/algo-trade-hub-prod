# Project State: Algo-Trade-Hub

## 🗓️ Last Updated: 2026-04-09
**Current Status:** Crypto Demo Runtime Live on VPS; validation stack implemented locally and pending commit/push

---

## ✅ Accomplished Today
- **Runtime Bootstrap Hardening**: Consolidated the backend onto a single canonical root `.env`, added explicit validation/fail-fast startup, and enforced canonical Kalshi hosts.
- **Kalshi Demo Auth Debugged**: Fixed the auth probe path-signing bug, validated a working demo API key + PEM pair, and brought the VPS onto authenticated demo REST + WS.
- **Crypto Inference Last-Mile**: Aligned live crypto inference to the 30-feature notebook schema, added Alpaca→`yfinance` historical backfill, and documented the `ta`/`yfinance` PM2 venv requirements.
- **Crypto Demo Execution Path**: The `crypto-sniper` worker now reaches Kalshi demo WS, evaluates signals, resolves markets, and submits demo trades through the Kalshi REST bridge.
- **Async Telegram Operator Plane**: Replaced the old threaded Telegram notifier with an async `aiohttp` implementation, added operator commands (`/crypto_status`, `/balance`, `/positions`, `/trades`, `/crypto_scan`), and launched it alongside the crypto worker.
- **Decoupled Operator State**: Added Supabase-backed crypto operator persistence (`crypto_signal_events`, crypto-specific trading control flags, enriched trade metadata) so Telegram reads durable state instead of worker memory.
- **Insufficient-Funds Safeguard**: Kalshi insufficient-funds rejections now disable further crypto trading in Supabase and generate operator alerts instead of repeatedly retrying.
- **Feature Parity / Calibration Fixed**: BTC and ETH live feature parity now passes the calibration targets; ETH volume calibration stays live-only in `shared/crypto_features.py`.
- **Closed-Hour Live Inference**: Live Alpaca crypto inference now excludes the still-forming current hour, which fixed the false zero-volume critical alerts.
- **Telegram `/cryptoscan` Cleanup**: The scan view now shows only recent actionable crypto events instead of stale historical rows.
- **Local Validation Stack Implemented (Not Yet Deployed)**:
  - `SP500 Predictor/scripts/force_demo_trade.py`
  - `SP500 Predictor/scripts/shadow_performance.py`
  - `SP500 Predictor/scripts/auto_retrain_regime.py`
  - Telegram `/stats` and `/accuracy`
  - Removal of temporary Telegram force-trade commands

## ⚠️ Current Deployment Gap
- The VPS `git pull` says **Already up to date**, but the new files are missing there.
- Root cause: the latest validation-stack work exists only in the **local working tree** and has **not been committed/pushed yet**.
- Local unpushed changes currently include:
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/SP500 Predictor/src/telegram_notifier.py`
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/market_sentiment_tool/backend/orchestrator.py`
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/SP500 Predictor/scripts/force_demo_trade.py`
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/SP500 Predictor/scripts/shadow_performance.py`
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/SP500 Predictor/scripts/auto_retrain_regime.py`
  - `/Users/sigey/Documents/Projects/algo-trade-hub-prod/SP500 Predictor/tests/test_crypto_shadow_and_scripts.py`

## 🟢 Currently Working / Stable

## 🟢 Currently Working / Stable
- **Crypto VPS Runtime**: `/root/kalshibot/market_sentiment_tool/backend/orchestrator.py` boots cleanly under PM2 as `crypto-sniper`, authenticates to Kalshi demo, and streams ticker data.
- **Signal Pipeline**: The BTC/ETH LightGBM models now receive the expected live feature frame, including long-window indicators via historical backfill.
- **Execution Bridge**: Kalshi demo order submission is wired through `market_sentiment_tool/backend/mcp_server.py` with Supabase-backed kill-switch controls.
- **Operator Visibility**: Supabase now holds trade attempts, crypto signal events, portfolio snapshots, and operator logs; Telegram commands read from Supabase/Kalshi directly.
- **Frontend**: The React/Vite dashboard and existing Supabase-backed UI remain intact.

## 🚀 Next Immediate Task
- **Commit and Push Validation Stack**: Publish the local validation-stack changes so the VPS can receive the new scripts and Telegram `/stats` command.
- **Deploy on VPS**: `git pull`, restart PM2, verify the three new scripts exist, and run `shadow_performance.py`.
- **Demo Order Plumbing Check**: Use `force_demo_trade.py` with a real demo ticker found via manual market lookup to verify end-to-end demo order placement without relying on auto-resolution.
- **Live Strategy Validation**: Use `/stats` or the CLI scorecard tomorrow morning to inspect hit rate, Brier Score, and virtual PnL before enabling any automated retraining schedule.
