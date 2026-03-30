import json
import os

notebook_path = '/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab/lightgbm_backtest.ipynb'

if not os.path.exists(notebook_path):
    print(f"❌ Error: {notebook_path} not found.")
    exit(1)

with open(notebook_path, 'r') as f:
    nb = json.load(f)

# --- Cell 2: Advanced Feature Engineering ---
cell_2_source = [
    "# Cell 2 & 3 (Enhanced: Data Ingestion & Features)\n",
    "import os, requests, time, yfinance as yf\n",
    "import pandas as pd\n",
    "import numpy as np\n",
    "import ta\n",
    "from datetime import datetime, timezone\n",
    "\n",
    "def fetch_kalshi_history(series_ticker='KXBTC', cache_file='kalshi_btc_history.csv', limit=1000):\n",
    "    \"\"\"Fetches settled Kalshi markets with local caching.\"\"\"\n",
    "    if os.path.exists(cache_file):\n",
    "        print(f\"📦 Loading {series_ticker} history from cache: {cache_file}\")\n",
    "        return pd.read_csv(cache_file)\n",
    "    \n",
    "    print(f\"📡 Pinging Kalshi API for {series_ticker} historical settlements...\")\n",
    "    API_KEY = os.getenv('KALSHI_API_KEY')\n",
    "    headers = {'Authorization': f'Bearer {API_KEY}'} if API_KEY else {}\n",
    "    url = 'https://api.elections.kalshi.com/trade-api/v2/markets'\n",
    "    \n",
    "    params = {'series_ticker': series_ticker, 'status': 'settled', 'limit': limit}\n",
    "    try:\n",
    "        r = requests.get(url, params=params, headers=headers)\n",
    "        if r.status_code == 200:\n",
    "            markets = r.json().get('markets', [])\n",
    "            df_kalshi = pd.DataFrame(markets)\n",
    "            df_kalshi.to_csv(cache_file, index=False)\n",
    "            print(f\"✅ Successfully cached {len(df_kalshi)} settled markets.\")\n",
    "            return df_kalshi\n",
    "        else:\n",
    "            print(f\"❌ Kalshi API Error {r.status_code}: {r.text}\")\n",
    "            return pd.DataFrame()\n",
    "    except Exception as e:\n",
    "        print(f\"❌ Connection Error: {e}\")\n",
    "        return pd.DataFrame()\n",
    "\n",
    "# 1. Fetch Price Data\n",
    "symbol = 'BTC-USD'\n",
    "df_raw = yf.download(symbol, period='2y', interval='1h')\n",
    "if isinstance(df_raw.columns, pd.MultiIndex):\n",
    "    df_raw.columns = df_raw.columns.get_level_values(0)\n",
    "\n",
    "# 2. Fetch Kalshi Data\n",
    "df_kalshi = fetch_kalshi_history()\n",
    "\n",
    "# 3. Advanced Feature Engineering\n",
    "def add_technical_features(df):\n",
    "    df = df.copy()\n",
    "    # Returns & Momentum\n",
    "    df['ret_1h'] = df['Close'].pct_change(1)\n",
    "    df['ret_4h'] = df['Close'].pct_change(4)\n",
    "    df['ret_12h'] = df['Close'].pct_change(12)  # Capture Session Transitions\n",
    "    \n",
    "    # 1. Mean Reversion Context (Distance from 200 EMA)\n",
    "    # Measures if price is overextended compared to long term baseline\n",
    "    df['ema_200'] = df['Close'].ewm(span=200, adjust=False).mean()\n",
    "    df['dist_ema_200'] = (df['Close'] / df['ema_200']) - 1\n",
    "    \n",
    "    # 2. Temporal Features (Session Bias)\n",
    "    # Hour captures session cycles; DayOfWeek captures weekend dynamics\n",
    "    df['hour'] = df.index.hour\n",
    "    df['dayofweek'] = df.index.dayofweek\n",
    "    \n",
    "    # 3. Volatility-Adjusted Returns (Signal Quality)\n",
    "    # Distinguishes genuine moves from noise using normalized ATR\n",
    "    atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)\n",
    "    df['vol_adj_ret'] = df['ret_1h'] / (atr / df['Close'])\n",
    "    \n",
    "    # 4. Volume Conviction\n",
    "    # Detects high-volume participation vs. low-volume drift\n",
    "    df['vol_rel_mean'] = df['Volume'] / df['Volume'].rolling(window=24).mean()\n",
    "    \n",
    "    df['rsi'] = ta.momentum.rsi(df['Close'], window=14)\n",
    "    df['target'] = (df['Close'].shift(-1) > df['Close']).astype(int)\n",
    "    \n",
    "    return df.dropna()\n",
    "\n",
    "df_features = add_technical_features(df_raw)\n",
    "print(f\"✅ Features generated. Shape: {df_features.shape}\")\n"
]

# --- Cell 3: Regularized Training & Thresholding ---
cell_3_source = [
    "# Cell 3 (Optimized: Walk-Forward CV with Regularized LGBM)\n",
    "import numpy as np\n",
    "import pandas as pd\n",
    "from sklearn.model_selection import TimeSeriesSplit\n",
    "import lightgbm as lgb\n",
    "\n",
    "X = df_features.drop(columns=['target'])\n",
    "y = df_features['target']\n",
    "\n",
    "tscv = TimeSeriesSplit(n_splits=5)\n",
    "all_probs = []\n",
    "all_targets = []\n",
    "\n",
    "print(\"Phase 1: Training Regularized Model (min_data_in_leaf=100)...\")\n",
    "for train_index, test_index in tscv.split(X):\n",
    "    X_train, X_test = X.iloc[train_index], X.iloc[test_index]\n",
    "    y_train, y_test = y.iloc[train_index], y.iloc[test_index]\n",
    "    \n",
    "    # Regularization: reduces overfitting to local noise in 1h series\n",
    "    model = lgb.LGBMClassifier(\n",
    "        n_estimators=100, \n",
    "        learning_rate=0.03, \n",
    "        max_depth=4, \n",
    "        min_data_in_leaf=100, \n",
    "        feature_fraction=0.8, \n",
    "        random_state=42\n",
    "    )\n",
    "    model.fit(X_train, y_train)\n",
    "    \n",
    "    probs = model.predict_proba(X_test)[:, 1]\n",
    "    all_probs.extend(probs)\n",
    "    all_targets.extend(y_test)\n",
    "\n",
    "results_df = pd.DataFrame({'Prob': all_probs, 'Target': all_targets})\n",
    "\n",
    "# 2. High-Conviction Threshold Optimizer\n",
    "thresholds = np.linspace(0.55, 0.75, 21)\n",
    "best_threshold = 0.55\n",
    "max_ev = -np.inf\n",
    "win_payout, loss_payout = 0.43, -0.57\n",
    "\n",
    "print(\"Phase 2: Optimizing for >58% Win Rate and Positive EV...\")\n",
    "for t in thresholds:\n",
    "    temp_signals = np.where(results_df['Prob'] > t, 1, np.where(results_df['Prob'] < (1-t), -1, 0))\n",
    "    trades = results_df[temp_signals != 0]\n",
    "    \n",
    "    if len(trades) > 20:\n",
    "        win_rate = ((trades['Target'] == 1) & (temp_signals[temp_signals != 0] == 1) | \n",
    "                    (trades['Target'] == 0) & (temp_signals[temp_signals != 0] == -1)).mean()\n",
    "        ev = (win_rate * win_payout) + ((1 - win_rate) * loss_payout)\n",
    "        \n",
    "        if win_rate > 0.58 and ev > max_ev:\n",
    "            max_ev = ev\n",
    "            best_threshold = t\n",
    "\n",
    "print(f\"Optimal OOS Threshold: {best_threshold:.3f}\")\n",
    "results_df['Signal'] = np.where(results_df['Prob'] > best_threshold, 1, \n",
    "                               np.where(results_df['Prob'] < (1-best_threshold), -1, 0))\n"
]

# --- Cell 6: Evaluation & Peer Comparison ---
cell_6_source = [
    "# Cell 6 (Binary PnL Engine & Benchmark Comparison)\n",
    "import plotly.graph_objects as go\n",
    "from sklearn.calibration import calibration_curve\n",
    "import matplotlib.pyplot as plt\n",
    "\n",
    "win_payout, loss_payout = 0.43, -0.57\n",
    "\n",
    "# 1. Model PnL\n",
    "correct = ((results_df['Signal'] == 1) & (results_df['Target'] == 1)) | \\\n",
    "          ((results_df['Signal'] == -1) & (results_df['Target'] == 0))\n",
    "results_df['PnL'] = np.where(results_df['Signal'] == 0, 0.0, np.where(correct, win_payout, loss_payout))\n",
    "results_df['Cum_PnL'] = results_df['PnL'].cumsum()\n",
    "\n",
    "# 2. Benchmark (Always Long / Average Market Outcome)\n",
    "# This represents taking every \"Yes\" bet at the same price cost.\n",
    "results_df['Benchmark_PnL'] = np.where(results_df['Target'] == 1, win_payout, loss_payout)\n",
    "results_df['Benchmark_Cum_PnL'] = results_df['Benchmark_PnL'].cumsum()\n",
    "\n",
    "print(f\"--- Backtest Summary (Best Threshold: {best_threshold:.3f}) ---\")\n",
    "print(f\"Total Trades: {len(results_df[results_df['Signal'] != 0])}\")\n",
    "print(f\"Model PnL: ${results_df['PnL'].sum():.2f}\")\n",
    "print(f\"Market Average PnL (Always Long): ${results_df['Benchmark_PnL'].sum():.2f}\")\n",
    "print(f\"Model Win Rate: {results_df[results_df['Signal'] != 0]['PnL'].apply(lambda x: x > 0).mean():.2%}\")\n",
    "\n",
    "# 2. Equity Curve Comparison\n",
    "fig = go.Figure()\n",
    "fig.add_trace(go.Scatter(y=results_df['Cum_PnL'], mode='lines', name='Model Strategy', line=dict(color='cyan', width=3)))\n",
    "fig.add_trace(go.Scatter(y=results_df['Benchmark_Cum_PnL'], mode='lines', name='Market Average (Always Long)', line=dict(color='gray', dash='dash')))\n",
    "\n",
    "fig.update_layout(title='Model vs. Market Benchmark Equity Curve',\n",
    "                  xaxis_title='Time Sequence',\n",
    "                  yaxis_title='Accumulated Profit ($)',\n",
    "                  template='plotly_dark')\n",
    "fig.show()\n"
]

# Replacement Logic
for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        source = ''.join(cell['source'])
        if '# Cell 2 & 3' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_2_source]
        elif '# Cell 3' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_3_source]
        elif '# Cell 6' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_6_source]

with open(notebook_path, 'w') as f:
    json.dump(nb, f, indent=1)

print("✅ Research Lab updated with contextual features, regularized training, and market benchmark.")
