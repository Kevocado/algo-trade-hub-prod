"""
Sentiment Analysis Module
Fetches market sentiment data from free sources (Fear & Greed Index, VIX-based sentiment,
put/call ratio proxy) and exposes sentiment scores for the dashboard and feature engineering.

NOTE: yfinance has been removed. VIX sentiment now uses a CBOE VIX proxy via requests,
and price momentum uses the project's Alpaca-based data_loader.
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime, timedelta
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)


class SentimentAnalyzer:
    """
    Multi-source sentiment analyzer.
    Sources:
      1. CNN Fear & Greed Index (via alternative.me API — free)
      2. VIX-derived sentiment (via CBOE VIX proxy)
      3. Put/Call proxy via market breadth
      4. Price momentum sentiment (via Alpaca data_loader)
    """

    def __init__(self):
        self.cache_ttl = timedelta(minutes=15)
        self._cache: Dict[str, dict] = {}

    def _is_cached(self, key: str) -> bool:
        if key in self._cache:
            ts = self._cache[key].get('timestamp')
            if ts and datetime.now() - ts < self.cache_ttl:
                return True
        return False

    # ------------------------------------------------------------------
    # Source 1: Crypto Fear & Greed Index (works for BTC/ETH sentiment)
    # ------------------------------------------------------------------
    def get_fear_greed_index(self) -> Dict:
        """Fetch the Crypto Fear & Greed Index from alternative.me (free, no key)."""
        if self._is_cached('fear_greed'):
            return self._cache['fear_greed']['data']

        try:
            resp = requests.get(
                "https://api.alternative.me/fng/?limit=30&format=json",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get('data', [])
                if data:
                    current = int(data[0]['value'])
                    label = data[0]['value_classification']

                    # Calculate 7-day and 30-day averages
                    values = [int(d['value']) for d in data]
                    avg_7d = np.mean(values[:7]) if len(values) >= 7 else np.mean(values)
                    avg_30d = np.mean(values[:30]) if len(values) >= 30 else np.mean(values)

                    result = {
                        'current': current,
                        'label': label,
                        'avg_7d': round(avg_7d, 1),
                        'avg_30d': round(avg_30d, 1),
                        'trend': 'improving' if current > avg_7d else 'declining',
                        'history': values,
                        'source': 'alternative.me'
                    }
                    self._cache['fear_greed'] = {'data': result, 'timestamp': datetime.now()}
                    return result
        except Exception as e:
            logger.warning(f"Fear & Greed fetch failed: {e}")

        return {'current': 50, 'label': 'Neutral', 'avg_7d': 50, 'avg_30d': 50,
                'trend': 'neutral', 'history': [], 'source': 'fallback'}

    # ------------------------------------------------------------------
    # Source 2: VIX-based sentiment (equity markets)
    # ------------------------------------------------------------------
    def get_vix_sentiment(self) -> Dict:
        """Derive sentiment from VIX levels and trend."""
        if self._is_cached('vix_sentiment'):
            return self._cache['vix_sentiment']['data']

        try:
            # Use CBOE VIX data via a public JSON endpoint
            resp = requests.get(
                "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VIX.json",
                timeout=10
            )
            if resp.status_code == 200:
                data = resp.json().get('data', [])
                if data and len(data) > 0:
                    closes = [d[1] for d in data[-30:] if d[1] is not None]  # last 30 entries
                    if closes:
                        current_vix = closes[-1]
                        avg_7d = np.mean(closes[-7:]) if len(closes) >= 7 else np.mean(closes)
                        avg_30d = np.mean(closes)

                        score = max(0, min(100, 100 - ((current_vix - 10) / 30) * 100))

                        if current_vix < 15:
                            label = "Extreme Greed"
                        elif current_vix < 20:
                            label = "Greed"
                        elif current_vix < 25:
                            label = "Neutral"
                        elif current_vix < 30:
                            label = "Fear"
                        else:
                            label = "Extreme Fear"

                        result = {
                            'current_vix': round(current_vix, 2),
                            'score': round(score, 1),
                            'label': label,
                            'avg_7d_vix': round(avg_7d, 2),
                            'avg_30d_vix': round(avg_30d, 2),
                            'trend': 'improving' if current_vix < avg_7d else 'declining',
                            'source': 'CBOE VIX'
                        }
                        self._cache['vix_sentiment'] = {'data': result, 'timestamp': datetime.now()}
                        return result
        except Exception as e:
            logger.warning(f"VIX sentiment fetch failed: {e}")

        return {'current_vix': 20, 'score': 50, 'label': 'Neutral',
                'avg_7d_vix': 20, 'avg_30d_vix': 20, 'trend': 'neutral', 'source': 'fallback'}

    # ------------------------------------------------------------------
    # Source 3: Momentum sentiment (price-derived)
    # ------------------------------------------------------------------
    def get_momentum_sentiment(self, ticker: str = "SPX") -> Dict:
        """Calculate momentum-based sentiment from price returns using Alpaca."""
        cache_key = f"momentum_{ticker}"

        if self._is_cached(cache_key):
            return self._cache[cache_key]['data']

        try:
            from src.data_loader import fetch_data
            df = fetch_data(ticker, period="3mo", interval="1d")
            if not df.empty and len(df) > 20:
                close = df['Close']
                ret_1d = (close.iloc[-1] / close.iloc[-2] - 1) * 100
                ret_5d = (close.iloc[-1] / close.iloc[-5] - 1) * 100 if len(close) >= 5 else 0
                ret_20d = (close.iloc[-1] / close.iloc[-20] - 1) * 100 if len(close) >= 20 else 0

                # Composite momentum score (0-100)
                raw = (ret_1d * 0.3 + ret_5d * 0.4 + ret_20d * 0.3)
                score = max(0, min(100, 50 + raw * 5))

                if score > 70:
                    label = "Strong Bullish"
                elif score > 55:
                    label = "Bullish"
                elif score > 45:
                    label = "Neutral"
                elif score > 30:
                    label = "Bearish"
                else:
                    label = "Strong Bearish"

                result = {
                    'score': round(score, 1),
                    'label': label,
                    'ret_1d': round(ret_1d, 2),
                    'ret_5d': round(ret_5d, 2),
                    'ret_20d': round(ret_20d, 2),
                    'ticker': ticker,
                    'source': 'Alpaca Price Momentum'
                }
                self._cache[cache_key] = {'data': result, 'timestamp': datetime.now()}
                return result
        except Exception as e:
            logger.warning(f"Momentum sentiment failed for {ticker}: {e}")

        return {'score': 50, 'label': 'Neutral', 'ret_1d': 0, 'ret_5d': 0,
                'ret_20d': 0, 'ticker': ticker, 'source': 'fallback'}

    # ------------------------------------------------------------------
    # Composite: Aggregate sentiment across all sources
    # ------------------------------------------------------------------
    def get_composite_sentiment(self, ticker: str = "SPX") -> Dict:
        """
        Aggregate all sentiment sources into a composite score.
        Weights: VIX (40%), Momentum (40%), Fear & Greed (20% - crypto bias).
        """
        vix = self.get_vix_sentiment()
        momentum = self.get_momentum_sentiment(ticker)
        fg = self.get_fear_greed_index()

        is_crypto = ticker in ("BTC", "ETH")

        if is_crypto:
            # Fear & Greed is more relevant for crypto
            composite = (vix['score'] * 0.2 + momentum['score'] * 0.3 + fg['current'] * 0.5)
        else:
            composite = (vix['score'] * 0.4 + momentum['score'] * 0.4 + fg['current'] * 0.2)

        if composite > 70:
            label = "Bullish"
        elif composite > 55:
            label = "Slightly Bullish"
        elif composite > 45:
            label = "Neutral"
        elif composite > 30:
            label = "Slightly Bearish"
        else:
            label = "Bearish"

        return {
            'composite_score': round(composite, 1),
            'label': label,
            'vix': vix,
            'momentum': momentum,
            'fear_greed': fg,
            'ticker': ticker,
            'timestamp': datetime.now().isoformat()
        }


def get_sentiment_features(ticker: str = "SPX") -> Dict[str, float]:
    """
    Return sentiment features suitable for adding to a feature DataFrame.
    These can be integrated into feature_engineering.py later.
    """
    analyzer = SentimentAnalyzer()
    composite = analyzer.get_composite_sentiment(ticker)

    return {
        'sentiment_composite': composite['composite_score'],
        'sentiment_vix_score': composite['vix']['score'],
        'sentiment_momentum': composite['momentum']['score'],
        'sentiment_fear_greed': composite['fear_greed']['current'],
        'sentiment_fg_avg_7d': composite['fear_greed']['avg_7d'],
        'sentiment_fg_avg_30d': composite['fear_greed']['avg_30d'],
        'sentiment_ret_1d': composite['momentum']['ret_1d'],
        'sentiment_ret_5d': composite['momentum']['ret_5d'],
        'sentiment_ret_20d': composite['momentum']['ret_20d'],
    }


def render_sentiment_panel(ticker: str = "SPX"):
    """
    Renders a sentiment dashboard panel inside Streamlit.
    Shows composite score, individual source breakdowns, and averages.
    """
    analyzer = SentimentAnalyzer()

    with st.spinner("Loading sentiment data..."):
        composite = analyzer.get_composite_sentiment(ticker)

    # --- Composite Score Header ---
    score = composite['composite_score']
    label = composite['label']

    # Color based on score
    if score > 60:
        color = "#00ff88"
        bg = "rgba(0, 255, 136, 0.1)"
    elif score > 40:
        color = "#ffaa00"
        bg = "rgba(255, 170, 0, 0.1)"
    else:
        color = "#ff5555"
        bg = "rgba(255, 85, 85, 0.1)"

    st.markdown(f"""
    <div style="background: {bg}; border: 1px solid {color}; border-radius: 12px; padding: 20px; text-align: center; margin-bottom: 16px;">
        <h2 style="margin: 0; color: {color};">{score:.0f}/100</h2>
        <p style="margin: 4px 0 0; color: #bbb; font-size: 1.1em;">{label} • {ticker}</p>
    </div>
    """, unsafe_allow_html=True)

    # --- Source Breakdown ---
    c1, c2, c3 = st.columns(3)

    # VIX Sentiment
    vix = composite['vix']
    with c1:
        st.metric(
            "🌪️ VIX Sentiment",
            f"{vix['score']:.0f}/100",
            f"VIX: {vix['current_vix']:.1f}",
            delta_color="inverse",
            help=f"VIX-derived. 7d avg: {vix['avg_7d_vix']:.1f}, 30d avg: {vix['avg_30d_vix']:.1f}"
        )
        st.caption(f"{vix['label']} • Trend: {vix['trend']}")

    # Momentum Sentiment
    mom = composite['momentum']
    with c2:
        delta_str = f"1d: {mom['ret_1d']:+.2f}%"
        st.metric(
            "📈 Momentum",
            f"{mom['score']:.0f}/100",
            delta_str,
            help=f"5d: {mom['ret_5d']:+.2f}%, 20d: {mom['ret_20d']:+.2f}%"
        )
        st.caption(f"{mom['label']}")

    # Fear & Greed
    fg = composite['fear_greed']
    with c3:
        delta_fg = fg['current'] - fg['avg_7d']
        st.metric(
            "😱 Fear & Greed",
            f"{fg['current']}/100",
            f"{delta_fg:+.0f} vs 7d avg",
            help=f"Source: {fg['source']}. 30d avg: {fg['avg_30d']:.0f}"
        )
        st.caption(f"{fg['label']} • Trend: {fg['trend']}")

    # --- Sentiment Averages ---
    st.markdown("---")
    st.markdown("#### 📊 Sentiment Averages")

    avg_data = {
        "Source": ["VIX Sentiment", "Momentum", "Fear & Greed", "**Composite**"],
        "Current": [
            f"{vix['score']:.0f}",
            f"{mom['score']:.0f}",
            f"{fg['current']}",
            f"**{score:.0f}**"
        ],
        "7-Day Avg": [
            f"VIX {vix['avg_7d_vix']:.1f}",
            f"{mom['ret_5d']:+.2f}% (5d)",
            f"{fg['avg_7d']:.0f}",
            "—"
        ],
        "30-Day Avg": [
            f"VIX {vix['avg_30d_vix']:.1f}",
            f"{mom['ret_20d']:+.2f}% (20d)",
            f"{fg['avg_30d']:.0f}",
            "—"
        ],
        "Signal": [
            vix['label'],
            mom['label'],
            fg['label'],
            f"**{label}**"
        ]
    }
    st.dataframe(pd.DataFrame(avg_data), use_container_width=True, hide_index=True)
