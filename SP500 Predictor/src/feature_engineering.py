"""
Feature Engineering — 3-Cluster Microstructure + Derivatives Pipeline

Cluster 1: Momentum & Sentiment (RSI, MACD, Price Acceleration, FinBERT)
Cluster 2: Market Microstructure (Amihud, Corwin-Schultz, RVOL)
Cluster 3: Derivatives Positioning (Black-Scholes GEX + fallback proxy)

All math is implemented directly using numpy/scipy — no placeholders.
"""

import pandas as pd
import numpy as np
import ta
import warnings

warnings.filterwarnings('ignore')


# ═══════════════════════════════════════════════════════════════
# CLUSTER 1: MOMENTUM & SENTIMENT
# ═══════════════════════════════════════════════════════════════

def add_momentum_features(df):
    """
    RSI, MACD, Price Acceleration (2nd derivative of price).
    """
    df = df.copy()

    # RSI
    df['rsi'] = ta.momentum.RSIIndicator(close=df['Close'], window=14).rsi()

    # MACD
    macd = ta.trend.MACD(close=df['Close'])
    df['macd'] = macd.macd()
    df['macd_signal'] = macd.macd_signal()
    df['macd_diff'] = macd.macd_diff()

    # Bollinger Band Width (volatility proxy)
    bb = ta.volatility.BollingerBands(close=df['Close'], window=20, window_dev=2)
    df['bb_width'] = (bb.bollinger_hband() - bb.bollinger_lband()) / df['Close']

    # Log Returns
    df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))

    # Price Velocity (1st derivative) — rate of price change
    df['price_velocity'] = df['Close'].diff()

    # Price Acceleration (2nd derivative) — rate of change of rate of change
    df['price_acceleration'] = df['price_velocity'].diff()

    # Rolling volatility (30-bar)
    df['volatility_30'] = df['log_ret'].rolling(window=30).std()

    # Lag features
    for lag in [1, 5, 15, 30, 60]:
        df[f'lag_ret_{lag}'] = df['Close'].pct_change(periods=lag)

    return df


def add_finbert_sentiment(df, ticker="SPY"):
    """
    Pipes Alpaca news stream through local FinBERT model.
    Returns hourly_news_sentiment score (-1 to +1).
    Falls back to 0.0 if models unavailable.
    """
    try:
        from src.sentiment_filter import SentimentFilter
        sf = SentimentFilter()

        # Try fetching recent Alpaca news
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import NewsRequest
            import os

            api_key = os.getenv("ALPACA_API_KEY", "")
            secret_key = os.getenv("ALPACA_SECRET_KEY", "")

            if api_key and secret_key:
                client = StockHistoricalDataClient(api_key, secret_key)
                # Fetch recent news for the ticker
                news_req = NewsRequest(symbols=[ticker], limit=10)
                news = client.get_news(news_req)

                if news:
                    sentiments = []
                    for article in news:
                        headline = article.headline if hasattr(article, 'headline') else str(article)
                        result = sf.analyze_fed_statement(headline)
                        # Map: positive=+1, negative=-1, neutral=0
                        score = result.get('confidence', 0.5)
                        if result.get('sentiment') == 'negative':
                            score = -score
                        elif result.get('sentiment') == 'neutral':
                            score = 0
                        sentiments.append(score)

                    avg_sentiment = np.mean(sentiments) if sentiments else 0.0
                    df['hourly_news_sentiment'] = avg_sentiment
                    return df
        except Exception:
            pass

        # Fallback: set to neutral
        df['hourly_news_sentiment'] = 0.0
        return df

    except Exception:
        df['hourly_news_sentiment'] = 0.0
        return df


# ═══════════════════════════════════════════════════════════════
# CLUSTER 2: MARKET MICROSTRUCTURE (LIQUIDITY)
# ═══════════════════════════════════════════════════════════════

def amihud_illiquidity(log_returns, dollar_volume, window=20):
    """
    Amihud Illiquidity Ratio (2002):
        ILLIQ = (1/N) × Σ(|R_t| / DVOL_t)

    Higher values = less liquid = more price impact per dollar traded.

    Args:
        log_returns: pd.Series of log returns
        dollar_volume: pd.Series of dollar volume (price × volume)
        window: rolling window for averaging

    Returns:
        pd.Series of rolling Amihud ratio
    """
    # Avoid division by zero
    safe_dvol = dollar_volume.replace(0, np.nan)
    daily_illiq = np.abs(log_returns) / safe_dvol
    return daily_illiq.rolling(window=window, min_periods=5).mean()


def corwin_schultz_spread(high, low, window=20):
    """
    Corwin-Schultz (2012) bid-ask spread estimator from High/Low prices.

    Derivation:
        β = E[ln(H_t/L_t)]²
        γ = [ln(H_{t,t+1}/L_{t,t+1})]²  (2-period high/low)
        α = (√(2β) - √(β)) / (3 - 2√2) - √(γ / (3 - 2√2))
        S = 2(e^α - 1) / (1 + e^α)

    Args:
        high: pd.Series of high prices
        low: pd.Series of low prices
        window: rolling window for β estimation

    Returns:
        pd.Series of estimated bid-ask spread (0.0 = no spread, 0.01 = 1%)
    """
    # Single-period log range squared
    log_hl = np.log(high / low)
    beta = log_hl ** 2

    # Rolling mean of beta
    beta_mean = beta.rolling(window=window, min_periods=5).mean()

    # 2-period high and low (max of consecutive highs, min of consecutive lows)
    high_2d = high.rolling(window=2).max()
    low_2d = low.rolling(window=2).min()

    # Gamma: squared log range of 2-period window
    gamma = np.log(high_2d / low_2d) ** 2

    # Constants
    k = 3 - 2 * np.sqrt(2)  # ≈ 0.1716

    # Alpha
    alpha = (np.sqrt(2 * beta_mean) - np.sqrt(beta_mean)) / k - np.sqrt(gamma / k)

    # Clamp alpha to prevent extreme values
    alpha = alpha.clip(lower=-1, upper=1)

    # Spread
    spread = 2 * (np.exp(alpha) - 1) / (1 + np.exp(alpha))

    # Spread must be non-negative
    spread = spread.clip(lower=0)

    return spread


def relative_volume(volume, window=20):
    """
    Relative Volume (RVOL):
        RVOL = Current Volume / SMA(Volume, N)

    RVOL > 1 = above average activity
    RVOL > 2 = significant activity spike

    Args:
        volume: pd.Series of volume
        window: SMA window for average volume

    Returns:
        pd.Series of RVOL
    """
    avg_vol = volume.rolling(window=window, min_periods=5).mean()
    return volume / avg_vol.replace(0, np.nan)


def add_microstructure_features(df):
    """Adds all Cluster 2 features to the dataframe."""
    df = df.copy()

    # Dollar volume = Close × Volume
    df['dollar_volume'] = df['Close'] * df['Volume']

    # Amihud Illiquidity Ratio
    if 'log_ret' not in df.columns:
        df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
    df['amihud'] = amihud_illiquidity(df['log_ret'], df['dollar_volume'])

    # Corwin-Schultz Spread
    df['cs_spread'] = corwin_schultz_spread(df['High'], df['Low'])

    # Relative Volume
    df['rvol'] = relative_volume(df['Volume'])

    # ── Per-bar Gamma Pressure Proxy ──
    # Formula: (High-Low)/ATR(14) × Price_Acceleration × Volume/SMA(Volume,20)
    # Positive = mean-reversion regime (dealers sell rallies/buy dips)
    # Negative = directional cascade (dealers amplify moves)
    tr = pd.concat([
        df['High'] - df['Low'],
        (df['High'] - df['Close'].shift(1)).abs(),
        (df['Low'] - df['Close'].shift(1)).abs()
    ], axis=1).max(axis=1)
    atr_14 = tr.rolling(14, min_periods=5).mean()

    norm_range = (df['High'] - df['Low']) / atr_14.replace(0, np.nan)
    velocity = df['Close'].diff()
    acceleration = velocity.diff()
    vol_sma = df['Volume'].rolling(20, min_periods=5).mean()
    norm_vol = df['Volume'] / vol_sma.replace(0, np.nan)

    df['gamma_pressure'] = norm_range * acceleration * norm_vol
    # Clamp extreme values to prevent model distortion
    df['gamma_pressure'] = df['gamma_pressure'].clip(
        lower=df['gamma_pressure'].quantile(0.01) if len(df) > 50 else -100,
        upper=df['gamma_pressure'].quantile(0.99) if len(df) > 50 else 100
    )

    return df


# ═══════════════════════════════════════════════════════════════
# CLUSTER 3: DERIVATIVES POSITIONING (GEX)
# ═══════════════════════════════════════════════════════════════

def black_scholes_gamma(S, K, T, r, sigma):
    """
    Black-Scholes Gamma for a European option.

        d1 = (ln(S/K) + (r + σ²/2)T) / (σ√T)
        Γ  = N'(d1) / (S × σ × √T)

    Where N'(x) is the standard normal PDF.

    Args:
        S: float, spot price
        K: float or array, strike price(s)
        T: float, time to expiration in years
        r: float, risk-free rate (e.g. 0.05 for 5%)
        sigma: float, implied volatility (e.g. 0.20 for 20%)

    Returns:
        float or array: gamma value(s)
    """
    from scipy.stats import norm

    if T <= 0 or sigma <= 0:
        return 0.0

    d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
    gamma = norm.pdf(d1) / (S * sigma * np.sqrt(T))
    return gamma


def calculate_gex(ticker="SPY", risk_free_rate=0.05):
    """
    Calculates Total Gamma Exposure (GEX) from options chains.

    GEX = Σ(OI_calls × Γ × S² × 0.01) - Σ(OI_puts × Γ × S² × 0.01)

    Positive GEX = dealers sell rallies / buy dips (stabilizing)
    Negative GEX = dealers amplify moves (destabilizing)

    Uses yfinance for options data.

    Returns:
        dict: {
            'gex': float (total net gamma exposure),
            'call_gex': float,
            'put_gex': float,
            'spot': float,
            'source': 'yfinance' | 'proxy'
        }
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        spot = tk.info.get('regularMarketPrice')
        if spot is None:
            spot = tk.history(period='1d')['Close'].iloc[-1]

        # Get nearest expiration
        expirations = tk.options
        if not expirations:
            raise ValueError("No option expirations available")

        nearest_exp = expirations[0]
        chain = tk.option_chain(nearest_exp)

        calls = chain.calls
        puts = chain.puts

        # Time to expiration in years
        from datetime import datetime
        exp_dt = datetime.strptime(nearest_exp, '%Y-%m-%d')
        T = max((exp_dt - datetime.now()).days / 365.0, 1/365)

        # Calculate gamma for each strike
        total_call_gex = 0.0
        total_put_gex = 0.0

        for _, row in calls.iterrows():
            strike = row['strike']
            oi = row.get('openInterest', 0) or 0
            iv = row.get('impliedVolatility', 0.3) or 0.3
            if oi > 0 and iv > 0:
                gamma = black_scholes_gamma(spot, strike, T, risk_free_rate, iv)
                total_call_gex += oi * gamma * spot ** 2 * 0.01

        for _, row in puts.iterrows():
            strike = row['strike']
            oi = row.get('openInterest', 0) or 0
            iv = row.get('impliedVolatility', 0.3) or 0.3
            if oi > 0 and iv > 0:
                gamma = black_scholes_gamma(spot, strike, T, risk_free_rate, iv)
                total_put_gex -= oi * gamma * spot ** 2 * 0.01  # puts have negative gamma effect

        net_gex = total_call_gex + total_put_gex

        return {
            'gex': round(net_gex, 2),
            'call_gex': round(total_call_gex, 2),
            'put_gex': round(total_put_gex, 2),
            'spot': round(spot, 2),
            'source': 'yfinance',
        }

    except Exception as e:
        # Fallback: Gamma Pressure Proxy
        return _gamma_proxy_fallback(ticker, str(e))


def _gamma_proxy_fallback(ticker, error_reason=""):
    """
    Gamma Pressure Proxy (when yfinance is rate-limited):
        Proxy = Normalized_Range × Acceleration × Normalized_Volume

    Where:
        Normalized_Range = (High - Low) / ATR(14)
        Acceleration = 2nd derivative of close price
        Normalized_Volume = Volume / SMA(Volume, 20)
    """
    try:
        import yfinance as yf
        df = yf.download(ticker, period='5d', interval='1h', progress=False)
        if df.empty:
            return {'gex': 0, 'call_gex': 0, 'put_gex': 0, 'spot': 0, 'source': 'proxy_failed'}

        # Flatten multi-level columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # ATR(14) approximation
        tr = pd.concat([
            df['High'] - df['Low'],
            (df['High'] - df['Close'].shift(1)).abs(),
            (df['Low'] - df['Close'].shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean()

        # Normalized range
        norm_range = (df['High'] - df['Low']) / atr.replace(0, np.nan)

        # Price acceleration
        velocity = df['Close'].diff()
        acceleration = velocity.diff()

        # Normalized volume
        norm_vol = df['Volume'] / df['Volume'].rolling(20).mean().replace(0, np.nan)

        # Proxy
        proxy = norm_range * acceleration * norm_vol
        proxy_value = proxy.iloc[-1] if not proxy.empty else 0

        return {
            'gex': round(float(proxy_value), 4) if not np.isnan(proxy_value) else 0,
            'call_gex': 0,
            'put_gex': 0,
            'spot': round(float(df['Close'].iloc[-1]), 2),
            'source': f'proxy ({error_reason[:50]})',
        }
    except Exception:
        return {'gex': 0, 'call_gex': 0, 'put_gex': 0, 'spot': 0, 'source': 'proxy_failed'}


def add_gex_feature(df, ticker="SPY"):
    """Adds GEX as a scalar feature column (same value for all rows in batch)."""
    df = df.copy()
    gex_data = calculate_gex(ticker)
    df['gex'] = gex_data['gex']
    df['gex_source'] = gex_data['source']
    return df, gex_data


# ═══════════════════════════════════════════════════════════════
# MASTER PIPELINE
# ═══════════════════════════════════════════════════════════════

FEATURE_COLUMNS = [
    # Cluster 1: Momentum
    'rsi', 'macd', 'macd_diff', 'bb_width', 'log_ret',
    'price_velocity', 'price_acceleration', 'volatility_30',
    'lag_ret_1', 'lag_ret_5', 'lag_ret_15', 'lag_ret_30', 'lag_ret_60',
    'hourly_news_sentiment',
    # Cluster 2: Microstructure
    'amihud', 'cs_spread', 'rvol', 'gamma_pressure',
    # Cluster 3: Derivatives
    'gex',
    # Time features
    'hour', 'dayofweek',
]


def create_features(df, ticker="SPY"):
    """
    Master feature engineering pipeline.
    Runs all 3 clusters + time features.

    Returns:
        (df_with_features, gex_data_dict)
    """
    df = df.copy()

    # Ensure required columns
    for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")

    # Ensure DatetimeIndex (handle mixed sources: yfinance, Tiingo, etc.)
    if not isinstance(df.index, pd.DatetimeIndex):
        df.index = pd.to_datetime(df.index)
    # Strip timezone info for consistency
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)

    # Time features
    df['hour'] = df.index.hour
    df['minute'] = df.index.minute
    df['dayofweek'] = df.index.dayofweek

    # Cluster 1: Momentum
    df = add_momentum_features(df)

    # Cluster 1: Sentiment
    df = add_finbert_sentiment(df, ticker)

    # Cluster 2: Microstructure
    df = add_microstructure_features(df)

    # Cluster 3: GEX
    df, gex_data = add_gex_feature(df, ticker)

    # Target: predict next-hour close
    df['target_next_hour'] = df['Close'].shift(-60)

    return df, gex_data


def prepare_training_data(df, ticker="SPY"):
    """Runs full pipeline and drops NaNs for training."""
    df, gex_data = create_features(df, ticker)
    df = df.dropna(subset=FEATURE_COLUMNS + ['target_next_hour'])
    return df, gex_data


if __name__ == "__main__":
    print("Testing Feature Engineering Pipeline...")
    print(f"Feature columns: {len(FEATURE_COLUMNS)}")
    for i, col in enumerate(FEATURE_COLUMNS, 1):
        print(f"  {i}. {col}")

    # Test GEX calculation
    print("\nTesting GEX for SPY...")
    gex = calculate_gex("SPY")
    print(f"  GEX: {gex['gex']}")
    print(f"  Spot: {gex['spot']}")
    print(f"  Source: {gex['source']}")

    # Test microstructure on sample data
    print("\nTesting microstructure math...")
    np.random.seed(42)
    n = 100
    prices = 100 + np.cumsum(np.random.randn(n) * 0.5)
    sample = pd.DataFrame({
        'Open': prices, 'High': prices + abs(np.random.randn(n)),
        'Low': prices - abs(np.random.randn(n)), 'Close': prices,
        'Volume': np.random.randint(1000, 100000, n).astype(float),
    }, index=pd.date_range('2024-01-01', periods=n, freq='h'))

    sample = add_microstructure_features(sample)
    print(f"  Amihud (last): {sample['amihud'].iloc[-1]:.8f}")
    print(f"  CS Spread (last): {sample['cs_spread'].iloc[-1]:.6f}")
    print(f"  RVOL (last): {sample['rvol'].iloc[-1]:.2f}")
