---
title: Kalshi Market Scanner
emoji: 📊
colorFrom: green
colorTo: gray
sdk: streamlit
app_file: streamlit_app.py
pinned: false
---

# Prediction Market Edge Finder

> [!WARNING]
> **⚠️ DISCLAIMER: RESEARCH AND EDUCATION TOOL ONLY**
> - ✋ **This Streamlit app remains read-only.**
> - 📊 All market data is read-only (view-only).
> - 🧪 Quant signals are **experimental** and for backtesting/operator monitoring only.
> - 💰 Do NOT rely on this app alone for actual trading decisions.
> - The repo now also contains a separate VPS-only crypto demo trading runtime and Telegram operator plane under `market_sentiment_tool/backend`, but that is not this Streamlit UI.

**Prediction Market Edge Finder** is a professional-grade analytics dashboard that identifies statistical edges in Kalshi prediction markets for SPX, Nasdaq, BTC, and ETH. It combines real-time market data, AI-powered probability models (LightGBM), multi-source sentiment analysis, and a "Bloomberg Terminal" style interface. The repo also now includes a separate async crypto demo execution runtime with Telegram operator commands, but this README describes the Streamlit analytics surface.

## ⚡ Key Features

- **Real-Time Market Scanner**: Fetches and categorizes live Kalshi markets into Hourly, End of Day, and Range opportunities.
- **AI-Driven Probability**: LightGBM regressors for hourly (1-min data) and daily (1-hr data) predictions with auto-retraining on feature drift.
- **Cloud Model Delivery**: Dynamically loads and caches the latest ML `.pkl` weights directly from the **Hugging Face Hub** (`huggingface_hub`) for seamless updates.
- **Kalshi Market Scanner**: Dedicated tab that scans all assets, calculates edge and Kelly sizing, and renders signal cards.
- **Institutional Risk & Backtesting**: Includes historical equity curve simulations with **Sharpe Ratio** and **Max Drawdown** metrics based on exact Kalshi payout math.
- **Smart Exit Alerts**: Active portfolio monitoring with dynamic warnings for decaying edge (<2%) or macroeconomic **FEAR** regime spikes.
- **Sentiment Analysis**: Composite sentiment scoring from 3 free sources — Crypto Fear & Greed Index, VIX-derived sentiment, and price momentum — with averages display.
- **Cross-Venue Intelligence**: Monitors Kalshi vs. PredictIt to surface low-risk arbitrage discrepancies (>5% delta).
- **Dark-mode "Bloomberg" aesthetic** with asset pills, integrated PnL simulator, and live market context.

## 🏗 Architecture

**Frontend:** Streamlit web app (default port 8501)
**Backend:** Python 3.9+
**Scanner:** Background terminal process (runs independently via cron or daemon)
**Storage:** Supabase (trades / agent logs / portfolio state) and Hugging Face Model Hub
**APIs:** Kalshi (Markets), FRED (Macro), Alpaca (Paper Data)
**Data Flow:** Scanner / backend engines → Supabase + model artifacts → Streamlit reads current state → UI renders

## 📂 Project Structure

```
.
├── streamlit_app.py          # Main dashboard (2 tabs: Edge Finder + Scanner)
├── config/
│   └── settings.yaml         # Centralized configuration
├── src/
│   ├── data_loader.py        # YFinance data fetching
│   ├── feature_engineering.py # Technical indicators (RSI, MACD, etc.)
│   ├── model.py              # LightGBM hourly model logic
│   ├── model_daily.py        # Daily model logic
│   ├── kalshi_feed.py        # Kalshi API integration
│   ├── market_scanner.py     # Market scanner (scan, signals, UI)
│   ├── sentiment.py          # Multi-source sentiment analysis
│   ├── signals.py            # Trading signal generation
│   ├── evaluation.py         # Model performance metrics
│   ├── utils.py              # Helper functions
│   └── supabase_client.py    # Supabase logging / history helpers
├── pages/
│   └── 1_Performance.py      # Performance analytics page
├── scripts/                  # Utility scripts
├── tests/                    # Test pipeline
├── model/                    # Saved .pkl models (gitignored)
└── CODEBASE_OVERVIEW.md      # Detailed codebase documentation
```

## 🚀 Setup & Installation

### Prerequisites

- Python 3.9+

### Installation

```bash
git clone <repository-url>
cd <repository-directory>
pip install -r requirements.txt
```

## ⚙️ Configuration (.env)

Create a `.env` file in the root directory before running the app. You must populate these variables:

```env
# Kalshi Trading API (Required for Portfolio Tab)
KALSHI_API_KEY_ID=your_kalshi_api_key_id_here
KALSHI_PRIVATE_KEY_PATH=/absolute/path/to/kalshi_demo_key.pem
KALSHI_ENV=demo

# Alpaca Paper Trading (Required for Backtesting Quant Trades)
APCA_API_KEY_ID=your_alpaca_key
APCA_API_SECRET_KEY=your_alpaca_secret

# AI & Infrastructure
FRED_API_KEY=your_fred_api_key
HF_TOKEN=your_hugging_face_token
SUPABASE_URL=your_supabase_url
SUPABASE_SERVICE_ROLE_KEY=your_supabase_service_role_key
```

## 🚀 Getting Started

### Step 1: Start the Background Scanner
The UI reads from pre-computed data and Supabase. You must run the scanner in the background to fetch new markets and update backend state.
```bash
python scripts/background_scanner.py
```
*(Keep this running. It updates markets every 30 seconds)*

### Step 2: Start the Web UI
```bash
streamlit run streamlit_app.py
```

## 🖥️ Usage

- **📁 Portfolio**: Monitor your live Kalshi positions, calculate unrealized P&L, and track Smart Exit alerts on decaying edges.
- **⛈️ Weather Arb**: View extreme weather predictions matched against official NWS forecasts.
- **🏛️ Macro/Fed**: Explore macroeconomic markets (Interest Rates, CPI YoY, GDP) modeled with live FRED data.
- **🧪 Quant Lab (Paper)**: View hourly probabilistic forecasts for SPX, QQQ, and Crypto options automatically trained on price tick data.
- **📊 Backtesting**: Analyze the historical performance of the Quantitative ML engines (Sharpe Ratio, Max Drawdown).
