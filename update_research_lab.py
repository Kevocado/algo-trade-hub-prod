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
    "    df['ret_12h'] = df['Close'].pct_change(12)\n",
    "    \n",
    "    # 1. Mean Reversion Context\n",
    "    df['ema_200'] = df['Close'].ewm(span=200, adjust=False).mean()\n",
    "    df['dist_ema_200'] = (df['Close'] / df['ema_200']) - 1\n",
    "    \n",
    "    # 2. Temporal Features\n",
    "    df['hour'] = df.index.hour\n",
    "    df['dayofweek'] = df.index.dayofweek\n",
    "    \n",
    "    # 3. Volatility-Adjusted Returns\n",
    "    atr = ta.volatility.average_true_range(df['High'], df['Low'], df['Close'], window=14)\n",
    "    df['vol_adj_ret'] = df['ret_1h'] / (atr / df['Close'])\n",
    "    \n",
    "    # 4. Volume Conviction\n",
    "    df['vol_rel_mean'] = df['Volume'] / df['Volume'].rolling(window=24).mean()\n",
    "    \n",
    "    # 5. NEW: Relative Strength & Momentum (Enhanced)\n",
    "    df['rsi'] = ta.momentum.rsi(df['Close'], window=14)\n",
    "    df['rsi_7'] = ta.momentum.rsi(df['Close'], window=7)\n",
    "    macd = ta.trend.MACD(df['Close'])\n",
    "    df['macd_diff'] = macd.macd_diff()\n",
    "    df['roc_6h'] = ta.momentum.roc(df['Close'], window=6)\n",
    "    \n",
    "    # 6. NEW: Volatility & Mean Reversion (Enhanced)\n",
    "    bb = ta.volatility.BollingerBands(df['Close'], window=20, window_dev=2)\n",
    "    df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / bb.bollinger_mavg()\n",
    "    df['z_score_24h'] = (df['Close'] - df['Close'].rolling(window=24).mean()) / df['Close'].rolling(window=24).std()\n",
    "    \n",
    "    # 7. NEW: Trend Quality\n",
    "    df['adx'] = ta.trend.adx(df['High'], df['Low'], df['Close'], window=14)\n",
    "    \n",
    "    df['target'] = (df['Close'].shift(-1) > df['Close']).astype(int)\n",
    "    return df.dropna()\n",
    "\n",
    "df_features = add_technical_features(df_raw)\n",
    "print(f\"✅ Features generated. Shape: {df_features.shape}\")\n"
]

# --- Cell 3: Optuna Optimization & Regularized Training ---
cell_3_source = [
    "# Cell 3 (Optimized: Optuna EV Search with Strict OOS CV)\n",
    "import optuna\n",
    "import lightgbm as lgb\n",
    "from sklearn.model_selection import TimeSeriesSplit\n",
    "\n",
    "X = df_features.drop(columns=['target'])\n",
    "y = df_features['target']\n",
    "win_payout, loss_payout = 0.43, -0.57\n",
    "\n",
    "def objective(trial):\n",
    "    params = {\n",
    "        'n_estimators': trial.suggest_int('n_estimators', 50, 150),\n",
    "        'learning_rate': trial.suggest_float('learning_rate', 0.01, 0.1, log=True),\n",
    "        'max_depth': trial.suggest_int('max_depth', 3, 4), # SHALLOW TREES ONLY\n",
    "        'lambda_l1': trial.suggest_float('lambda_l1', 1e-3, 10.0, log=True), # HIGH REGULARIZATION\n",
    "        'lambda_l2': trial.suggest_float('lambda_l2', 1e-3, 10.0, log=True), # HIGH REGULARIZATION\n",
    "        'min_data_in_leaf': trial.suggest_int('min_data_in_leaf', 50, 200),\n",
    "        'feature_fraction': trial.suggest_float('feature_fraction', 0.5, 1.0),\n",
    "        'random_state': 42,\n",
    "        'verbosity': -1\n",
    "    }\n",
    "    threshold = trial.suggest_float('threshold', 0.55, 0.70)\n",
    "    \n",
    "    tscv = TimeSeriesSplit(n_splits=3)\n",
    "    fold_evs = []\n",
    "    \n",
    "    for train_idx, test_idx in tscv.split(X):\n",
    "        X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]\n",
    "        y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]\n",
    "        \n",
    "        model = lgb.LGBMClassifier(**params)\n",
    "        model.fit(X_train, y_train)\n",
    "        probs = model.predict_proba(X_test)[:, 1]\n",
    "        \n",
    "        signals = np.where(probs > threshold, 1, np.where(probs < (1-threshold), -1, 0))\n",
    "        trade_mask = (signals != 0)\n",
    "        \n",
    "        if trade_mask.sum() < 20:\n",
    "            return -1.0\n",
    "            \n",
    "        trades_y = y_test[trade_mask]\n",
    "        trades_sig = signals[trade_mask]\n",
    "        win_rate = ((trades_y == 1) & (trades_sig == 1) | (trades_y == 0) & (trades_sig == -1)).mean()\n",
    "        ev = (win_rate * win_payout) + ((1 - win_rate) * loss_payout)\n",
    "        fold_evs.append(ev)\n",
    "        \n",
    "    return np.mean(fold_evs)\n",
    "\n",
    "print(\"Phase 1: Optuna EV-Optimization (Strict OOS Evaluation)...\")\n",
    "study = optuna.create_study(direction='maximize')\n",
    "study.optimize(objective, n_trials=50)\n",
    "\n",
    "best_params = study.best_params\n",
    "best_threshold = best_params.pop('threshold')\n",
    "print(f\"✅ Best EV: {study.best_value:.4f} | Best Threshold: {best_threshold:.3f}\")\n",
    "\n",
    "# Train Final Model on all data with best params\n",
    "final_model = lgb.LGBMClassifier(**best_params)\n",
    "final_model.fit(X, y)\n",
    "\n",
    "# Generate OOS results using TimeSeriesSplit to mirror real performance\n",
    "tscv = TimeSeriesSplit(n_splits=5)\n",
    "all_probs = []\n",
    "all_targets = []\n",
    "for train_idx, test_idx in tscv.split(X):\n",
    "    X_train, X_test = X.iloc[train_idx], X.iloc[test_idx]\n",
    "    y_train, y_test = y.iloc[train_idx], y.iloc[test_idx]\n",
    "    m = lgb.LGBMClassifier(**best_params)\n",
    "    m.fit(X_train, y_train)\n",
    "    all_probs.extend(m.predict_proba(X_test)[:, 1])\n",
    "    all_targets.extend(y_test)\n",
    "\n",
    "results_df = pd.DataFrame({'Prob': all_probs, 'Target': all_targets})\n",
    "results_df['Signal'] = np.where(results_df['Prob'] > best_threshold, 1, \n",
    "                               np.where(results_df['Prob'] < (1-best_threshold), -1, 0))\n"
]

# --- Cell 6: Evaluation & Peer Comparison ---
cell_6_source = [
    "# Cell 6 (Binary PnL Engine & Benchmark Comparison)\n",
    "import plotly.graph_objects as go\n",
    "\n",
    "win_payout, loss_payout = 0.43, -0.57\n",
    "\n",
    "# 1. Model PnL\n",
    "correct = ((results_df['Signal'] == 1) & (results_df['Target'] == 1)) | \\\n",
    "          ((results_df['Signal'] == -1) & (results_df['Target'] == 0))\n",
    "results_df['PnL'] = np.where(results_df['Signal'] == 0, 0.0, np.where(correct, win_payout, loss_payout))\n",
    "results_df['Cum_PnL'] = results_df['PnL'].cumsum()\n",
    "\n",
    "# 2. Benchmark (Always Long)\n",
    "results_df['Benchmark_PnL'] = np.where(results_df['Target'] == 1, win_payout, loss_payout)\n",
    "results_df['Benchmark_Cum_PnL'] = results_df['Benchmark_PnL'].cumsum()\n",
    "\n",
    "# 3. Benchmark (Random Coin Flip)\n",
    "np.random.seed(42)\n",
    "results_df['Random_Signal'] = np.random.choice([1, -1], size=len(results_df))\n",
    "results_df['Random_PnL'] = np.where(((results_df['Random_Signal'] == 1) & (results_df['Target'] == 1)) | \n",
    "                                    ((results_df['Random_Signal'] == -1) & (results_df['Target'] == 0)), \n",
    "                                    win_payout, loss_payout)\n",
    "results_df['Random_Cum_PnL'] = results_df['Random_PnL'].cumsum()\n",
    "\n",
    "print(f\"--- Backtest Summary (Best Threshold: {best_threshold:.3f}) ---\")\n",
    "print(f\"Total Trades: {len(results_df[results_df['Signal'] != 0])}\")\n",
    "print(f\"Model PnL: ${results_df['PnL'].sum():.2f}\")\n",
    "print(f\"Market Average (Always Long): ${results_df['Benchmark_PnL'].sum():.2f}\")\n",
    "print(f\"Random Strategy PnL: ${results_df['Random_PnL'].sum():.2f}\")\n",
    "print(f\"Model Win Rate: {results_df[results_df['Signal'] != 0]['PnL'].apply(lambda x: x > 0).mean():.2%}\")\n",
    "\n",
    "fig = go.Figure()\n",
    "fig.add_trace(go.Scatter(y=results_df['Cum_PnL'], mode='lines', name='Model Strategy', line=dict(color='cyan', width=3)))\n",
    "fig.add_trace(go.Scatter(y=results_df['Benchmark_Cum_PnL'], mode='lines', name='Always Long', line=dict(color='gray', dash='dash')))\n",
    "fig.add_trace(go.Scatter(y=results_df['Random_Cum_PnL'], mode='lines', name='Random Flip', line=dict(color='orange', dash='dot')))\n",
    "\n",
    "fig.update_layout(title='Model vs. Benchmarks (Equity Curves)',\n",
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
        elif '# Cell 6' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_6_source]
        elif '# Cell 4' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_4_source]

# --- Cell 4: SHAP Analysis ---
cell_4_source = [
    "# Cell 4 (SHAP Analysis)\n",
    "\"\"\"\n",
    "SHAP (SHapley Additive exPlanations) interprets the LightGBM model by calculating the marginal contribution of each feature.\n",
    "\n",
    "--- HOW TO READ THIS PLOT ---\n",
    "1. Feature Importance (Y-Axis): Features are ranked from most impactful (top) to least impactful (bottom).\n",
    "2. Impact (X-Axis): Points to the right increase the probability of a '1' (Price Up/Win); points to the left decrease it.\n",
    "3. Feature Value (Color): RED = High feature value (e.g., high RSI); BLUE = Low feature value.\n",
    "   - Example: If a feature is RED on the right, it means High values of that feature predict a Win.\n",
    "\"\"\"\n",
    "import shap\n",
    "\n",
    "# Use final_model (trained on 21 features) to match the current feature set\n",
    "explainer = shap.TreeExplainer(final_model)\n",
    "shap_values = explainer.shap_values(X)\n",
    "\n",
    "# Handle binary classification SHAP output (check if list or array)\n",
    "if isinstance(shap_values, list):\n",
    "    shap_values_to_plot = shap_values[1] # Use positive class contribution\n",
    "else:\n",
    "    shap_values_to_plot = shap_values\n",
    "\n",
    "print(\"Visualizing Global Feature Importance...\")\n",
    "shap.summary_plot(shap_values_to_plot, X, plot_type='bar', show=True)\n",
    "\n",
    "print(\"Visualizing Beeswarm Plot (Feature Impact)...\")\n",
    "shap.summary_plot(shap_values_to_plot, X, show=True)\n"
]

# Replacement Logic (re-run to include cell_4)
for cell in nb['cells']:
    if cell['cell_type'] == 'code':
        source = ''.join(cell['source'])
        if '# Cell 2 & 3' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_2_source]
        elif '# Cell 3' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_3_source]
        elif '# Cell 6' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_6_source]
        elif '# Cell 4' in source:
            cell['source'] = [s if s.endswith('\n') else s + '\n' for s in cell_4_source]

with open(notebook_path, 'w') as f:
    json.dump(nb, f, indent=1)

print("✅ Research Lab and SHAP interpretation updated.") 
