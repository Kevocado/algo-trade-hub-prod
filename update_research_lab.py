import json
import os

# --- SHARED CONSTANTS ---
LAB_DIR = '/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab'
BACKTEST_NB = os.path.join(LAB_DIR, 'lightgbm_backtest.ipynb')
WEATHER_NB = os.path.join(LAB_DIR, 'kalshi_weather_research.ipynb')

def apply_notebook_updates(notebook_path, cell_updates, markdown_inserts=None):
    """
    Generalized function to apply source code replacements and markdown insertions to a notebook.
    
    Args:
        notebook_path (str): Path to the .ipynb file.
        cell_updates (dict): Mapping of 'marker string' -> list of source code lines.
        markdown_inserts (list): List of dicts {'index': int, 'source': list} to insert markdown cells.
    """
    if not os.path.exists(notebook_path):
        print(f"⚠️ Warning: {notebook_path} not found. Skipping.")
        return False

    with open(notebook_path, 'r') as f:
        nb = json.load(f)

    # 1. Apply Source Code Updates (Replacing existing code cells based on markers)
    for cell in nb['cells']:
        if cell['cell_type'] == 'code':
            source_str = ''.join(cell['source'])
            for marker, new_source in cell_updates.items():
                if marker in source_str:
                    # Apply update: ensuring newlines are correct
                    cell['source'] = [s if s.endswith('\n') else s + '\n' for s in new_source]
                    print(f"  ✅ Updated code cell with marker: '{marker}' in {os.path.basename(notebook_path)}")

    # 2. Apply Markdown Inserts (Adding new documentation cells)
    if markdown_inserts:
        # Sort inserts by index descending so we don't invalidate indices while inserting
        for insert in sorted(markdown_inserts, key=lambda x: x['index'], reverse=True):
            idx = insert['index']
            content = insert['source']
            new_cell = {
                "cell_type": "markdown",
                "metadata": {},
                "source": [s if s.endswith('\n') else s + '\n' for s in content]
            }
            # Check if this exact markdown already exists to avoid duplicates
            already_exists = any(cell['cell_type'] == 'markdown' and ''.join(cell['source']) == ''.join(new_cell['source']) for cell in nb['cells'])
            if not already_exists:
                nb['cells'].insert(idx, new_cell)
                print(f"  ✅ Inserted markdown cell at index {idx} in {os.path.basename(notebook_path)}")

    with open(notebook_path, 'w') as f:
        json.dump(nb, f, indent=1)
    
    return True

# --- UPDATE CONTENT: BTC BACKTEST ---
btc_cell_2_source = [
    "# Cell 2 & 3 (Enhanced: Data Ingestion & Features)\n",
    "import os, requests, time, yfinance as yf\n",
    "import sys\n",
    "import pandas as pd\n",
    "import numpy as np\n",
    "from datetime import datetime, timezone\n",
    "from pathlib import Path\n",
    "\n",
    "REPO_ROOT = Path.cwd()\n",
    "if str(REPO_ROOT) not in sys.path:\n",
    "    sys.path.insert(0, str(REPO_ROOT))\n",
    "from shared.crypto_features import build_features, CANONICAL_CRYPTO_FEATURES\n",
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
    "symbol = 'BTC-USD'\n",
    "df_raw = yf.download(symbol, period='2y', interval='1h')\n",
    "if isinstance(df_raw.columns, pd.MultiIndex):\n",
    "    df_raw.columns = df_raw.columns.get_level_values(0)\n",
    "\n",
    "df_kalshi = fetch_kalshi_history()\n",
    "\n",
    "df_features = build_features(df_raw, is_live_inference=False, include_target=True)\n",
    "feature_cols = list(CANONICAL_CRYPTO_FEATURES)\n",
    "print(f\"✅ Features generated. Shape: {df_features.shape}\")\n"
]

# --- UPDATE CONTENT: WEATHER RESEARCH ---
weather_insights_md = [
    "### 🏛️ Quant Research: Practical Market Dynamics (Alpha Notes)\n",
    "Trading weather on Kalshi requires understanding the physical constraints of the platform:\n",
    "- **Timing & Launch**: Markets typically launch at **10 AM local time the day before** the event. Trading the day before offers a balance between higher liquidity and increased efficiency.\n",
    "- **Liquidity Dynamics**: The 'Day Before' often sees more professional activity from market makers (e.g., SIG) and model-driven bots. **Limit orders** are essential to avoid slippage in lower-liquidity windows.\n",
    "- **Pricing Efficiency**: Contracts resolving in 24-48 hours closely mirror **NWS forecasts**. Edge is often found in ensemble model discrepancies (e.g., GFS vs ECMWF) or abrupt forecast shifts.\n",
    "- **Official Settlement**: All weather markets settle solely based on the final official **NWS Climate Report** (not local news or mobile phone apps)."
]

weather_feature_cell_source = [
    "# Cell 4 (Comprehensive: Data & Feature Engineering)\n",
    "import lightgbm as lgb\n",
    "import shap\n",
    "import pandas as pd\n",
    "import numpy as np\n",
    "from sklearn.metrics import mean_squared_error, log_loss\n",
    "\n",
    "def add_weather_features(df):\n",
    "    df = df.copy()\n",
    "    \n",
    "    # --- LEAKAGE PROTECTION: 1-DAY LAG ---\n",
    "    # We shift the temperature data by 1 day so that at any date 'T',\n",
    "    # we only have access to information from 'T-1' and earlier.\n",
    "    df['t_lag'] = df['tmax_f'].shift(1)\n",
    "    \n",
    "    # 1. Z-Score Normalization (Using lagged data exclusively)\n",
    "    df['rolling_avg_30d'] = df['t_lag'].rolling(30).mean()\n",
    "    df['rolling_std_30d'] = df['t_lag'].rolling(30).std()\n",
    "    df['temp_z_score'] = (df['t_lag'] - df['rolling_avg_30d']) / (df['rolling_std_30d'] + 1e-6)\n",
    "    \n",
    "    # 2. Lags & Momentum (Based on T-1 information)\n",
    "    df['lag_1d'] = df['t_lag']\n",
    "    df['lag_2d'] = df['t_lag'].shift(1)\n",
    "    df['temp_momentum'] = df['t_lag'].diff(1)\n",
    "    \n",
    "    # 3. Cyclical Seasonality\n",
    "    df['day_of_year'] = df.index.dayofyear\n",
    "    df['sin_day'] = np.sin(2 * np.pi * df['day_of_year'] / 365.25)\n",
    "    df['cos_day'] = np.cos(2 * np.pi * df['day_of_year'] / 365.25)\n",
    "    \n",
    "    # 4. Target Generation (Predicted outcome for time T)\n",
    "    # Note: df['tmax_f'] at index T is NOT available to the features above.\n",
    "    TARGET_THRESHOLD = 65.0 \n",
    "    df['target'] = (df['tmax_f'] > TARGET_THRESHOLD).astype(int)\n",
    "    \n",
    "    # Drop NaNs and intermediate leakage-protection column\n",
    "    return df.dropna().drop(columns=['t_lag'])\n",
    "\n",
    "# Fetch 3 years for robust training (2023-2024) and testing (2025)\n",
    "full_weather_df = fetch_historical_weather('NYC', '2023-01-01', '2025-12-31')\n",
    "df_features = add_weather_features(full_weather_df)\n",
    "print(f\"✅ Features generated (Lagged for Leakage Protection). Shape: {df_features.shape}\")\n"
]

# --- EXECUTE UPDATES ---
print("🚀 Launching Modular Research Lab Update...")

# 1. Update BTC Backtest
apply_notebook_updates(
    BACKTEST_NB,
    cell_updates={
        '# Cell 2 (MASTER: Unified Feature Engine)': btc_cell_2_source,
        '# Cell 3 (Isolated: Stability-Weighted Tuning Lab)': [line for line in btc_cell_2_source if 'Optuna' in line], # Placeholder
    }
)

# 2. Update Weather Research
apply_notebook_updates(
    WEATHER_NB,
    cell_updates={
        'def add_weather_features(df):': weather_feature_cell_source,
    },
    markdown_inserts=[
        {'index': 1, 'source': weather_insights_md}
    ]
)

print("\n🏁 Update Sequence Complete.")
