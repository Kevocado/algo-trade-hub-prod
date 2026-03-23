# SP500 Predictor — Architecture Overhaul Spec (Final)

> **Execution Model**: Human-in-the-Loop via Telegram (Kalshi API is read-only)
> **ML Focus**: SPY/QQQ as proxies for SPX/Nasdaq directional prediction
> **Data Stack**: Tiingo (historical) + Alpaca (real-time) + yfinance (GEX)
> **Crypto**: All BTC/ETH models and UI permanently removed

---

### Phase 1: Database Restructuring & Telegram Infrastructure

* **Migrate to Supabase (Deprecate Azure Tables):** Transition all live app state, order flow data, and logging from Azure Table Storage to Supabase PostgreSQL. Keep Azure Blob Storage only as optional backup for large unstructured dumps.
* **The "Hard Reset" Script (`scripts/db_hard_reset.py`):** Truncate polluted historical tables in Supabase. Record wipe timestamp for UI transparency.
* **Telegram Notifier (`src/telegram_notifier.py`):** Build bot utility using `t.me/KevsWeatherBot`. Since Kalshi write-access is disabled, all "auto-execution" logic (Kill Switch, Weather Arb, GEX Flips) routes through formatted, actionable Telegram alerts.

### Phase 2: Streamlit UI Overhaul (Strict 4-Tab Layout)

* **Persistent Header:**
  * Pin "Daily AI Market Sentiment" at the top right as a regime tag (e.g., `AI Regime: ACCUMULATION`) with `st.expander` for the full narrative.
  * **CSS Fix:** `NEUTRAL` state renders with grey background/text instead of unstyled white.
  * **Footer:** `st.caption("Historical Data Coverage: [Wipe Date] → Present")`
* **Tab 1 — My Portfolio:** Live Kalshi positions, Unrealized PnL, "Market Context" badge per trade. Kill Switch → "Send Telegram Alert" button.
* **Tab 2 — Quant Lab (SPY & QQQ):** Hourly directional models for SPX/Nasdaq (via SPY/QQQ proxies). Display live GEX, Amihud Illiquidity, and Corwin-Schultz spread metrics natively. No crypto UI.
* **Tab 3 — Weather Markets:** Weather screener + Telegram take-profit alert thresholds. Live NWS integration for real-time settlement tracking.
* **Tab 4 — Macro Markets:** Live FRED data (CPI, Unemployment, Fed Rate). PnL backtest of model rate-cut predictions vs Kalshi contract outcomes. No opportunity counting.
* **Removed:** Cross-Venue Arb tab, all BTC/ETH UI elements.

### Phase 3: Quant Engine Rebuild (Microstructure & Derivatives Fusion)

* **Data Acquisition:**
  * **Tiingo:** Historical 1-min OHLCV bars (accurate volume ground truth).
  * **Alpaca WebSockets:** Real-time tick + news stream only.
  * **yfinance:** Nearest-term option chains for SPY/QQQ GEX calculation.
* **Feature Cluster 1 — Momentum & Sentiment:**
  * RSI, MACD, Price Acceleration (2nd derivative of price).
  * Alpaca live news → local `ProsusAI/finbert` → `hourly_news_sentiment` score (-1 to +1).
* **Feature Cluster 2 — Market Microstructure (Liquidity):**
  * Amihud Illiquidity Ratio: `|log_return| / dollar_volume`
  * Corwin-Schultz Spread: Synthetic bid-ask from daily High/Low prices.
  * RVOL: `current_volume / SMA(volume, 20)`
* **Feature Cluster 3 — Derivatives Positioning (GEX):**
  * Black-Scholes Gamma → aggregate Total GEX: `Σ(OI × γ × S² × 0.01)`
  * Fallback (yfinance rate-limited): Gamma Pressure Proxy = `normalized_range × acceleration × normalized_volume`
* **Model:** LightGBM on unified 3-cluster vector. Quarter-Kelly (0.25×) sizing enforced.
* **Backtesting:** Brier Score for probabilistic accuracy. Simulated PnL with Kalshi bid/ask spreads.
  * backtesting should also be done for weather markets but only for temperature markets as those are trackable with yes/no and precise values

### Phase 4: Alerting & Human-in-the-Loop Execution

All alerts routed through `src/telegram_notifier.py` (`t.me/KevsWeatherBot`):

| Trigger            | Alert                                                         |
| ------------------ | ------------------------------------------------------------- |
| Weather settlement | `🌤️ NWS printed 72°F. Sell Chicago High Temp at $0.92`   |
| GEX flip (+ → −) | `⚠️ Gamma Flip: SPY GEX negative. Expect expanded range.` |
| Amihud spike       | `🚨 Liquidity Cascade: Amihud 3σ above mean.`              |
| VIX > 45           | `🔴 VIX Emergency: Liquidate all positions.`                |
| Kill Switch        | `🚨 Kill Switch: Liquidate SPX YES positions.`              |

### Phase 5: Self-Healing Infrastructure (The AI Optimizer)

* **Optimizer Script (`src/optimizer.py`):** Weekly Brier Score + PSI drift + PnL → Gemini → rewrite `config/settings.yaml` hyperparameters.
* **GitHub Action (`.github/workflows/ai_optimizer.yml`):** Sunday midnight cron → optimizer → `peter-evans/create-pull-request` (never pushes to main).
* **Model Retraining:** Merged PR triggers `scripts/train_daily_models.py` → pushes `.pkl` to HuggingFace Hub.
