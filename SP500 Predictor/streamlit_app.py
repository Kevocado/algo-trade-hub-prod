"""
Kalshi Edge Finder — v8 (Premium Dark Terminal)
6-Tab Layout: Portfolio → Quant Lab → Weather → Macro → Backtesting → Quant Glossary
Execution: Human-in-the-Loop via Telegram | Weather auto-sell via NWS settlement
"""

import streamlit as st
import pandas as pd
import numpy as np
import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv
from huggingface_hub import hf_hub_download

load_dotenv()


# ─── AUTO-PULL MODELS FROM HF HUB ─────────────────────────────
def ensure_models_exist():
    REPO_ID = "Kevocado/sp500-predictor-models"
    for f in ["lgbm_model_SPX.pkl", "features_SPX.pkl",
              "lgbm_model_Nasdaq.pkl", "features_Nasdaq.pkl"]:
        try:
            hf_hub_download(repo_id=REPO_ID, filename=f, cache_dir="model", force_filename=f)
        except Exception:
            pass

ensure_models_exist()


# ─── HELPERS ───────────────────────────────────────────────────

def parse_kalshi_ticker(ticker):
    import re
    city_map = {"NY": "NYC", "CHI": "Chicago", "MIA": "Miami"}
    m = re.match(r'KX(\w+?)(NY|CHI|MIA)-(\d{2})([A-Z]{3})(\d{2})-([AB])([\d.]+)', ticker)
    if m:
        metric, city_code, day, mon, yr, direction, strike = m.groups()
        city = city_map.get(city_code, city_code)
        dir_text = "above" if direction == "A" else "below"
        return f"{city} daily high {dir_text} {strike}°F ({day} {mon})"
    m2 = re.match(r'(KX\w+?)-([\dA-Z]+)', ticker)
    if m2:
        series, contract = m2.groups()
        series_map = {
            "KXLCPIMAXYOY": "CPI Max YoY", "KXFED": "Fed Rate",
            "KXGDPYEAR": "GDP", "KXRECSSNBER": "Recession",
            "KXFEDDECISION": "Fed Decision", "KXU3MAX": "Unemployment",
        }
        return f"{series_map.get(series, series)}: {contract}"
    return ticker


# ─── DATA LAYER ────────────────────────────────────────────────

@st.cache_data(ttl=30)
def fetch_opportunities():
    live_opps, paper_opps, last_update = [], [], None
    try:
        from src.supabase_client import get_latest_opportunities
        rows = get_latest_opportunities(limit=100)
        if rows:
            for r in rows:
                entry = {
                    'Engine': r.get('engine', ''), 'Asset': r.get('asset', ''),
                    'Market': r.get('market_title', ''), 'MarketTicker': r.get('market_ticker', ''),
                    'EventTicker': r.get('event_ticker', ''), 'Action': r.get('action', ''),
                    'ModelProb': r.get('model_prob', 0), 'MarketPrice': r.get('market_price', 0),
                    'Edge': r.get('edge', 0), 'Reasoning': r.get('reasoning', ''),
                    'DataSource': r.get('data_source', ''), 'KalshiURL': r.get('kalshi_url', ''),
                    'MarketDate': r.get('market_date', ''), 'Expiration': r.get('expiration', ''),
                }
                if entry['Engine'].lower() in ('weather', 'macro', 'tsa', 'eia'):
                    live_opps.append(entry)
                else:
                    paper_opps.append(entry)
            last_update = datetime.now(timezone.utc).strftime("%H:%M UTC")
            return live_opps, paper_opps, last_update
    except Exception:
        pass
    # Azure fallback
    try:
        from azure.data.tables import TableClient
        conn_str = os.getenv("AZURE_CONNECTION_STRING", "").strip('"')
        if not conn_str:
            return [], [], None
        try:
            lc = TableClient.from_connection_string(conn_str, "LiveOpportunities")
            live_opps = sorted(list(lc.query_entities("")), key=lambda x: float(x.get('Edge', 0)), reverse=True)
        except Exception:
            pass
        try:
            pc = TableClient.from_connection_string(conn_str, "PaperTradingSignals")
            paper_opps = sorted(list(pc.query_entities("")), key=lambda x: float(x.get('Edge', 0)), reverse=True)
        except Exception:
            pass
        all_e = live_opps + paper_opps
        if all_e:
            ts = all_e[0].get('_metadata', {}).get('timestamp') or all_e[0].get('Timestamp')
            last_update = (ts.strftime("%H:%M UTC") if not isinstance(ts, str) else pd.to_datetime(ts).strftime("%H:%M UTC")) if ts else datetime.now(timezone.utc).strftime("%H:%M UTC")
        return live_opps, paper_opps, last_update
    except Exception:
        return [], [], None


def run_ai_validation(sig):
    try:
        from src.ai_validator import AIValidator
        v = AIValidator()
        opp = {'engine': sig.get('Engine', ''), 'asset': sig.get('Asset', ''),
               'market_title': sig.get('Market', ''), 'action': sig.get('Action', ''),
               'edge': float(sig.get('Edge', 0)), 'reasoning': sig.get('Reasoning', ''),
               'data_source': sig.get('DataSource', '')}
        return v.validate_trade(opp)
    except Exception as e:
        return {'approved': None, 'ai_reasoning': f'Error: {e}', 'confidence': 0}


@st.cache_data(ttl=86400)
def get_ai_sentiment_cache():
    snippets = []
    try:
        from scripts.engines.macro_engine import MacroEngine
        me = MacroEngine()
        for label, fn in [("CPI YoY", me.get_latest_cpi_yoy), ("Fed Rate", me.get_fed_rate_prediction),
                          ("GDP Growth", me.get_gdp_prediction), ("Unemployment", me.get_unemployment_rate)]:
            try:
                v = fn()
                if v is not None:
                    snippets.append(f"{label}: {v}%")
            except Exception:
                pass
    except Exception:
        pass
    if not snippets:
        snippets = ["No macro data available."]
    try:
        from src.news_analyzer import NewsAnalyzer
        return NewsAnalyzer().get_general_sentiment(vix_value=15.0, macro_news_snippets=snippets)
    except Exception:
        return {"heat_score": 0, "label": "Neutral", "summary": "Sentiment engine offline."}


def get_macro_data():
    data = {'vix': 20, 'yield_curve': 0}
    try:
        from src.sentiment import SentimentAnalyzer
        vix = SentimentAnalyzer().get_vix()
        if vix:
            data['vix'] = vix
    except Exception:
        pass
    try:
        import fredapi
        fk = os.getenv('FRED_API_KEY', '').strip('"')
        if fk:
            t = fredapi.Fred(api_key=fk).get_series('T10Y2Y', observation_start='2024-01-01')
            if len(t) > 0:
                data['yield_curve'] = round(t.iloc[-1], 2)
    except Exception:
        pass
    return data


def render_grid(data, key_suffix, empty_msg="No opportunities found."):
    if not data:
        st.info(empty_msg)
        return
    rows = []
    for item in data:
        if isinstance(item, dict):
            kalshi_url = item.get('KalshiUrl', item.get('kalshi_url', ''))
            market_name = str(item.get('Market', item.get('market_title', '')))[:55]
            rows.append({
                'Engine': item.get('Engine', item.get('engine', '')),
                'Market': market_name,
                'Action': item.get('Action', item.get('action', '')),
                'Edge %': round(float(item.get('Edge', item.get('edge', 0))), 1),
                'Model P': round(float(item.get('ModelProb', item.get('model_prob', 0))), 1),
                'Price ¢': round(float(item.get('MarketPrice', item.get('market_price', 0))), 0),
                'Date': item.get('MarketDate', item.get('market_date', '')),
                'Kalshi': kalshi_url,
            })
    if not rows:
        st.info(empty_msg)
        return
    df = pd.DataFrame(rows).sort_values('Edge %', ascending=False)

    # Render as styled cards with clickable Kalshi links
    for _, row in df.iterrows():
        edge_color = '#34d399' if row['Edge %'] > 0 else '#f87171'
        link_html = f'<a href="{row["Kalshi"]}" target="_blank" style="color: #60a5fa; text-decoration: none; font-size: 0.8rem;">View on Kalshi ↗</a>' if row['Kalshi'] else ''
        st.markdown(f"""
        <div class="quant-card" style="display: flex; justify-content: space-between; align-items: center; padding: 12px 18px; margin-bottom: 8px;">
            <div style="flex: 3;">
                <strong style="color: #e5e7eb;">{row['Market']}</strong><br>
                <span class="stat-pill">{row['Engine']}</span>
                <span class="stat-pill">{row['Action']}</span>
                <span class="stat-pill">{row['Date']}</span>
            </div>
            <div style="flex: 1; text-align: center;">
                <span style="color: {edge_color}; font-family: 'JetBrains Mono', monospace; font-size: 1.2rem; font-weight: 700;">{row['Edge %']:+.1f}%</span><br>
                <span style="color: #6b7280; font-size: 0.75rem;">Model {row['Model P']:.0f}¢ vs Mkt {row['Price ¢']:.0f}¢</span>
            </div>
            <div style="flex: 1; text-align: right;">
                {link_html}
            </div>
        </div>
        """, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# PAGE CONFIG & CSS
# ═══════════════════════════════════════════════════════════════

st.set_page_config(page_title="Kalshi Edge Finder", page_icon="⛈️", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&family=Inter:wght@300;400;500;600;700&display=swap');

    /* ── Base ── */
    .stApp { font-family: 'Inter', sans-serif; background: #0a0e17 !important; color: #c9d1d9 !important; }
    .stApp p, .stApp span, .stApp label, .stApp div, .stMarkdown, .stMarkdown p, .stMarkdown span,
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], .stCaption, .stCaption p { color: #c9d1d9 !important; }
    [data-testid="stMetricDelta"] { color: #3fb950 !important; }

    /* ── Tabs ── */
    .stTabs [data-baseweb="tab-list"] { background: #111827; border-radius: 10px; padding: 4px; gap: 2px; border: 1px solid #1e293b; }
    .stTabs [data-baseweb="tab"] { color: #6b7280 !important; background: transparent; font-size: 0.85rem; padding: 8px 16px; }
    .stTabs [aria-selected="true"] { color: #e5e7eb !important; background: linear-gradient(135deg, #1e293b, #1a1f36) !important; border-radius: 8px; font-weight: 600; }

    /* ── Buttons ── */
    .stButton > button { background: linear-gradient(135deg, #2563eb 0%, #7c3aed 100%) !important; color: white !important; border: none !important; font-weight: 600; border-radius: 8px; transition: all 0.2s; }
    .stButton > button:hover { transform: translateY(-1px); box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3); opacity: 0.95; }

    /* ── Cards ── */
    .quant-card { background: linear-gradient(135deg, rgba(30, 41, 59, 0.8), rgba(15, 23, 42, 0.9)); border: 1px solid #1e293b; border-radius: 12px; padding: 20px 24px; margin-bottom: 16px; backdrop-filter: blur(8px); }
    .quant-card:hover { border-color: #334155; }

    /* ── Accent Colors ── */
    .edge-positive { color: #34d399 !important; font-weight: 700; }
    .edge-negative { color: #f87171 !important; font-weight: 700; }

    /* ── Pills ── */
    .stat-pill { display: inline-block; background: rgba(37, 99, 235, 0.12); border: 1px solid rgba(37, 99, 235, 0.25); border-radius: 20px; padding: 3px 12px; font-size: 0.78rem; color: #60a5fa !important; margin-right: 6px; font-family: 'JetBrains Mono', monospace; }

    /* ── Regime Badges ── */
    .regime-badge { display: inline-flex; align-items: center; gap: 8px; padding: 8px 20px; border-radius: 24px; font-weight: 600; font-size: 0.9rem; letter-spacing: 0.5px; }
    .regime-bullish   { background: rgba(52, 211, 153, 0.1); border: 1px solid rgba(52, 211, 153, 0.3); color: #34d399 !important; }
    .regime-bearish   { background: rgba(248, 113, 113, 0.1); border: 1px solid rgba(248, 113, 113, 0.3); color: #f87171 !important; }
    .regime-neutral   { background: rgba(107, 114, 128, 0.15); border: 1px solid rgba(107, 114, 128, 0.35); color: #9ca3af !important; }
    .regime-greedy    { background: rgba(251, 191, 36, 0.1); border: 1px solid rgba(251, 191, 36, 0.3); color: #fbbf24 !important; }
    .regime-fearful   { background: rgba(167, 139, 250, 0.1); border: 1px solid rgba(167, 139, 250, 0.3); color: #a78bfa !important; }

    /* ── AI Opinion Panel ── */
    .ai-panel { background: linear-gradient(135deg, rgba(30, 41, 59, 0.6), rgba(15, 23, 42, 0.8)); border: 1px solid #1e293b; border-radius: 12px; padding: 16px 20px; margin-top: 8px; font-size: 0.88rem; color: #94a3b8 !important; line-height: 1.6; }

    /* ── Hero ── */
    .hero-wrap { background: linear-gradient(135deg, rgba(37, 99, 235, 0.06) 0%, rgba(124, 58, 237, 0.06) 100%); border: 1px solid rgba(37, 99, 235, 0.15); border-radius: 16px; padding: 28px 36px; margin-bottom: 20px; }
    .hero-wrap h1 { background: linear-gradient(90deg, #60a5fa, #a78bfa); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 1.8rem; font-weight: 700; margin: 0; }
    .hero-wrap p { color: #6b7280 !important; margin: 6px 0 0 0; font-size: 0.88rem; }

    /* ── Metric Cards ── */
    .metric-strip { display: flex; gap: 12px; margin: 16px 0; }
    .metric-card { flex: 1; background: linear-gradient(135deg, #111827, #0f172a); border: 1px solid #1e293b; border-radius: 10px; padding: 14px 18px; text-align: center; }
    .metric-card .label { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 1px; color: #6b7280; margin-bottom: 4px; }
    .metric-card .value { font-size: 1.4rem; font-weight: 700; font-family: 'JetBrains Mono', monospace; }

    /* ── Weather Auto-Sell Box ── */
    .auto-sell-box { background: linear-gradient(135deg, rgba(52, 211, 153, 0.06), rgba(16, 185, 129, 0.03)); border: 1px solid rgba(52, 211, 153, 0.2); border-radius: 12px; padding: 16px 20px; margin: 12px 0; }
    .auto-sell-box h5 { color: #34d399 !important; margin: 0 0 8px 0; font-size: 0.95rem; }

    /* ── Data table ── */
    .stDataFrame { border-radius: 8px; overflow: hidden; }
</style>
""", unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════════
# HEADER: Hero + AI Regime (always visible)
# ═══════════════════════════════════════════════════════════════

sentiment = get_ai_sentiment_cache()
s_label = sentiment.get('label', 'Neutral')
s_summary = sentiment.get('summary', '')
regime_map = {
    'Bullish': ('ACCUMULATION', 'regime-bullish'),
    'Greedy': ('EUPHORIA', 'regime-greedy'),
    'Bearish': ('DISTRIBUTION', 'regime-bearish'),
    'Fearful': ('CAPITULATION', 'regime-fearful'),
    'Neutral': ('RANGING', 'regime-neutral'),
}
regime_name, regime_css = regime_map.get(s_label, ('RANGING', 'regime-neutral'))

hcol1, hcol2 = st.columns([3, 2])
with hcol1:
    st.markdown("""
    <div class="hero-wrap">
        <h1>⛈️ Kalshi Edge Finder</h1>
        <p>Weather Arbitrage • FRED Economics • ML Directional Prediction</p>
    </div>
    """, unsafe_allow_html=True)
with hcol2:
    st.markdown(f"""
    <div style="padding: 12px 0;">
        <div style="text-align: right; margin-bottom: 10px;">
            <span class="regime-badge {regime_css}">🧠 AI Regime: {regime_name}</span>
        </div>
        <div class="ai-panel">
            {s_summary}
        </div>
    </div>
    """, unsafe_allow_html=True)

# ── Market Heat Metrics ──
macro_data = get_macro_data()
vix = macro_data.get('vix', 20)
yc = macro_data.get('yield_curve', 0)
heat = max(-100, min(100, ((vix - 15) * 5) - (yc * 50)))
heat_color = "#f87171" if heat > 30 else ("#34d399" if heat < -30 else "#fbbf24")

st.markdown(f"""
<div class="metric-strip">
    <div class="metric-card">
        <div class="label">VIX</div>
        <div class="value" style="color: {'#f87171' if vix > 25 else '#34d399'}">{vix:.1f}</div>
    </div>
    <div class="metric-card">
        <div class="label">10Y-2Y Spread</div>
        <div class="value" style="color: {'#f87171' if yc < 0 else '#34d399'}">{yc:+.2f}</div>
    </div>
    <div class="metric-card">
        <div class="label">Heat Score</div>
        <div class="value" style="color: {heat_color}">{heat:+.0f}</div>
    </div>
    <div class="metric-card">
        <div class="label">Last Sync</div>
        <div class="value" style="color: #60a5fa; font-size: 1rem;">{'—' if not (fetch_opportunities()[2]) else fetch_opportunities()[2]}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# ── Data Coverage ──
try:
    from src.supabase_client import get_wipe_date
    wd = get_wipe_date()
    if wd:
        st.caption(f"📊 Historical Data Coverage: {wd[:10]} → Present")
except Exception:
    pass

if st.button("🔄 Refresh Data", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

live_opps, paper_opps, last_updated = fetch_opportunities()
live_opps = live_opps or []
paper_opps = paper_opps or []
weather_opps = [o for o in live_opps if o.get('Engine', '').lower() == 'weather']
macro_opps = [o for o in live_opps if o.get('Engine', '').lower() == 'macro']

st.markdown("---")


# ═══════════════════════════════════════════════════════════════
# 6-TAB LAYOUT
# ═══════════════════════════════════════════════════════════════

tab_port, tab_quant, tab_wx, tab_macro, tab_bt, tab_gloss = st.tabs([
    "📁 Portfolio",
    "🧪 Quant Lab",
    "⛈️ Weather",
    "🏛️ Macro",
    "📊 Backtesting",
    "📖 Quant Glossary",
])


# ═══════════════════════ TAB 1: PORTFOLIO ═════════════════════
with tab_port:
    st.markdown("### 📁 My Kalshi Portfolio")
    try:
        from src.kalshi_portfolio import KalshiPortfolio, check_portfolio_available

        if not check_portfolio_available():
            st.warning("**Setup**: Add `KALSHI_API_KEY_ID` to `.env` → [Kalshi API Keys](https://kalshi.com)")
        else:
            @st.cache_data(ttl=30)
            def fetch_portfolio():
                return KalshiPortfolio().get_portfolio_summary()

            summary = fetch_portfolio()
            if summary.get('error'):
                st.error(f"Portfolio error: {summary['error']}")
            else:
                # Balance strip
                b1, b2, b3, b4 = st.columns(4)
                if summary['balance'] is not None:
                    b1.metric("💰 Cash", f"${summary['balance']:,.2f}")
                b2.metric("📊 Positions", len(summary.get('positions', [])))
                b3.metric("📈 Settlements", len(summary.get('settlements', [])))
                unrealized = sum(
                    ((p.get('market_price', 0) - p.get('average_price', 0)) * p.get('position', 0)) / 100
                    for p in summary.get('positions', []) if p.get('market_price')
                )
                b4.metric("💹 Unrealized PnL", f"{'+'if unrealized>=0 else ''}{unrealized:,.2f}")

                # ── Weather Auto-Sell Engine Status ──
                st.markdown("---")
                st.markdown("""
                <div class="auto-sell-box">
                    <h5>🌤️ Weather Auto-Sell Engine</h5>
                    <span style="color: #94a3b8; font-size: 0.85rem;">
                        Monitors NWS for settlement-guaranteeing temperatures. When triggered, auto-sends a
                        <strong style="color:#34d399">SELL</strong> alert to Telegram to lock in max profit or protect from loss.
                        <br>• Only weather positions • Only SELL orders • Only on live NWS data changes
                    </span>
                </div>
                """, unsafe_allow_html=True)

                # ── Open Positions with Market Context ──
                st.markdown("---")
                positions = summary.get('positions', [])
                if positions:
                    st.markdown("#### 📊 Open Positions")

                    ctx_lookup = {}
                    for opp in live_opps:
                        tk = opp.get('MarketTicker', opp.get('market_ticker', ''))
                        if tk:
                            ctx_lookup[tk] = {
                                'edge': float(opp.get('Edge', opp.get('edge', 0))),
                                'action': opp.get('Action', opp.get('action', '')),
                                'engine': opp.get('Engine', opp.get('engine', '')),
                            }

                    for pos in positions:
                        raw_ticker = pos.get('ticker', 'Unknown')
                        readable = parse_kalshi_ticker(raw_ticker)
                        contracts = pos.get('position', 0)
                        avg_cost = pos.get('average_price', 0)
                        current = pos.get('market_price')
                        pnl = ((current - avg_cost) * contracts) / 100 if current else 0

                        ctx = ctx_lookup.get(raw_ticker)
                        ctx_html = ""
                        if ctx:
                            ec = "#34d399" if ctx['edge'] > 0 else "#f87171"
                            ctx_html = f'<span class="stat-pill" style="color:{ec}!important;border-color:{ec}33">{ctx["engine"]}: {ctx["edge"]:+.1f}%</span>'

                        with st.container(border=True):
                            c1, c2 = st.columns([3, 1])
                            with c1:
                                st.markdown(f"**{readable}**")
                                st.caption(f"`{raw_ticker}` · {contracts} contracts @ {avg_cost}¢")
                                if ctx_html:
                                    st.markdown(ctx_html, unsafe_allow_html=True)
                            with c2:
                                st.metric("PnL", f"${pnl:+.2f}" if current else "N/A",
                                          f"{current:.0f}¢" if current else None)
                else:
                    st.info("No open positions.")

                # ── Settlement History ──
                settlements = summary.get('settlements', [])
                if settlements:
                    st.markdown("---")
                    st.markdown("#### 📜 Recent Settlements")
                    for s in settlements[:10]:
                        rev = s.get('revenue', 0) / 100
                        tk = s.get('ticker', '?')
                        when = s.get('settled_time', '')[:10] if s.get('settled_time') else ''
                        icon = "✅" if rev > 0 else ("❌" if rev < 0 else "➖")
                        st.markdown(f"{icon} **{tk}** — ${rev:+.2f} {'(' + when + ')' if when else ''}")
    except Exception as e:
        st.warning(f"Portfolio unavailable: {e}")


# ═══════════════════════ TAB 2: QUANT LAB ═════════════════════
with tab_quant:
    st.markdown("### 🧪 Quant Lab — SPY/QQQ Directional Intelligence")
    st.caption("Hourly predictions via Alpaca + FinBERT + market microstructure. Models SPX/Nasdaq direction using SPY/QQQ proxies.")

    st.info("⚠️ **Paper Trading Only** — Quantitative research platform. All signals require manual Kalshi execution.")

    if paper_opps:
        render_grid(paper_opps, "quant")
    else:
        st.info("🔬 No quant signals. Run the background scanner to generate predictions.")

    st.markdown("---")
    st.markdown("#### 📊 Live Market Microstructure")
    try:
        from src.feature_engineering import calculate_gex, add_microstructure_features
        from src.data_loader import fetch_data

        # GEX (cached as scalar, no dataframe needed)
        @st.cache_data(ttl=300)
        def get_live_gex():
            return calculate_gex("SPY")

        gex_data = get_live_gex()

        # Microstructure from recent data
        @st.cache_data(ttl=300)
        def get_live_micro():
            df = fetch_data("SPY", period="5d", interval="1h")
            if df.empty or len(df) < 5:
                return {"amihud": None, "cs_spread": None, "rvol": None}
            import numpy as np
            df['log_ret'] = np.log(df['Close'] / df['Close'].shift(1))
            df = add_microstructure_features(df)
            last = df.iloc[-1]
            return {
                "amihud": last.get("amihud"),
                "cs_spread": last.get("cs_spread"),
                "rvol": last.get("rvol"),
            }

        micro = get_live_micro()

        m1, m2, m3, m4 = st.columns(4)
        gex_val = gex_data.get('gex', 0)
        gex_fmt = f"{gex_val/1e6:+.1f}M" if abs(gex_val) > 1e5 else f"{gex_val:+,.0f}"
        m1.metric("GEX (SPY)", gex_fmt, help=f"Source: {gex_data.get('source', '?')}")
        m2.metric("Amihud", f"{micro['amihud']:.2e}" if micro.get('amihud') else "—",
                  help="Illiquidity: |return|/$vol")
        m3.metric("CS Spread", f"{micro['cs_spread']:.4f}" if micro.get('cs_spread') else "—",
                  help="Corwin-Schultz estimated spread")
        m4.metric("RVOL", f"{micro['rvol']:.2f}" if micro.get('rvol') else "—",
                  help="Relative volume vs 20-bar SMA")
    except Exception as e:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("GEX (SPY)", "—")
        m2.metric("Amihud", "—")
        m3.metric("CS Spread", "—")
        m4.metric("RVOL", "—")
        st.caption(f"⚠️ Microstructure unavailable: {e}")


# ═══════════════════════ TAB 3: WEATHER ═══════════════════════
with tab_wx:
    st.markdown("### ⛈️ Weather Markets — NWS Climate Arbitrage")
    st.caption("NWS is the official settlement source for all Kalshi weather markets. Showing today & tomorrow.")

    today_str = datetime.now().strftime("%Y-%m-%d")
    tmrw_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # Filter weather opps to today/tomorrow only
    wx_today_tmrw = []
    for o in weather_opps:
        md = o.get('MarketDate', o.get('market_date', ''))
        if md and (md[:10] == today_str or md[:10] == tmrw_str):
            wx_today_tmrw.append(o)
        elif not md:
            wx_today_tmrw.append(o)

    col_w1, col_w2 = st.columns([3, 1])
    with col_w1:
        if wx_today_tmrw:
            render_grid(wx_today_tmrw, "weather", empty_msg="🌤️ No weather edges for today/tomorrow.")

            # Edge reasoning section
            st.markdown("---")
            st.markdown("##### 💡 Why These Markets?")
            st.markdown("""
            <div class="quant-card">
                <span style="color: #94a3b8; font-size: 0.85rem;">
                Markets are selected when our NWS-based model probability diverges from the Kalshi market price
                by more than <strong>10%</strong>. The NWS API is the official settlement source, so when their
                forecast data disagrees with market pricing, that's a real statistical edge.<br><br>
                <strong>Edge = |NWS Probability - Market Price|</strong><br>
                We compute NWS probability using the hourly forecast: if the forecast high is well above/below
                the strike, confidence is high. Markets within 2°F of the strike get lower confidence.
                </span>
            </div>
            """, unsafe_allow_html=True)
        else:
            st.info("🌤️ No weather edges for today or tomorrow. Markets may not be open yet.")
            st.markdown("""
            <div class="quant-card">
                <span style="color: #94a3b8; font-size: 0.85rem;">
                <strong>How weather arbitrage works:</strong> Kalshi offers daily markets on temperature,
                snowfall, wind speed, and precipitation across NYC, Chicago, and Miami. The NWS API provides
                official forecasts that are the actual settlement source. When NWS data disagrees with market
                pricing, we flag the edge.<br><br>
                <strong>Market Types:</strong> Temperature highs (6AM-6PM), snowfall accumulation,
                max wind speed, and precipitation totals.
                </span>
            </div>
            """, unsafe_allow_html=True)

    with col_w2:
        st.markdown("##### 📡 NWS Climate Dashboard")
        try:
            from scripts.engines.weather_engine import WeatherEngine
            we = WeatherEngine()
            forecasts = we.get_all_forecasts()
            full = getattr(we, '_full_forecasts', {})

            for city in ['NYC', 'Chicago', 'Miami']:
                cn = {'NYC': 'New York', 'Chicago': 'Chicago', 'Miami': 'Miami'}.get(city, city)
                temp_data = forecasts.get(city, {})
                climate = full.get(city, {})

                today_temp = temp_data.get(today_str)
                tmrw_temp = temp_data.get(tmrw_str)
                today_clim = climate.get(today_str, {})
                tmrw_clim = climate.get(tmrw_str, {})

                if today_temp or tmrw_temp:
                    with st.expander(f"📍 {cn}", expanded=True):
                        if today_temp:
                            wind = today_clim.get('max_wind', '?')
                            precip = today_clim.get('max_precip_pct', 0)
                            snow = '❄️ Snow' if today_clim.get('snow_likely') else ''
                            st.markdown(f"**Today:** {today_temp}°F · 💨{wind}mph · 🌧️{precip}% {snow}")
                        if tmrw_temp:
                            wind = tmrw_clim.get('max_wind', '?')
                            precip = tmrw_clim.get('max_precip_pct', 0)
                            snow = '❄️ Snow' if tmrw_clim.get('snow_likely') else ''
                            st.markdown(f"**Tomorrow:** {tmrw_temp}°F · 💨{wind}mph · 🌧️{precip}% {snow}")
        except Exception:
            st.caption("NWS forecast unavailable.")

    st.markdown("---")
    st.markdown("""
    <div class="auto-sell-box">
        <h5>📱 Telegram Alert Thresholds</h5>
        <span style="color: #94a3b8; font-size: 0.85rem;">
            <strong>Take-Profit:</strong> NWS prints temperature guaranteeing contract outcome → auto SELL alert<br>
            <strong>Loss Protection:</strong> NWS forecast shifts against position → SELL alert to cut losses<br>
            <strong>New Edge:</strong> Edge > 15% on any weather market → BUY alert for manual execution
        </span>
    </div>
    """, unsafe_allow_html=True)


# ═══════════════════════ TAB 4: MACRO ═════════════════════════
with tab_macro:
    st.markdown("### 🏛️ Macro Markets — FRED Economic Intelligence")

    if macro_opps:
        st.markdown("#### Active Opportunities")
        render_grid(macro_opps, "macro")
        st.markdown("---")

    st.markdown("#### 📈 Live Economic Indicators")
    try:
        import fredapi
        fk = os.getenv('FRED_API_KEY', '').strip('"')
        if fk:
            fred = fredapi.Fred(api_key=fk)
            fc1, fc2 = st.columns(2)
            with fc1:
                try:
                    cpi = fred.get_series('CPIAUCSL', observation_start='2023-01-01')
                    if len(cpi) >= 13:
                        cpi_yoy = (((cpi / cpi.shift(12)) - 1) * 100).dropna()
                        st.markdown("**CPI Year-over-Year (%)**")
                        st.line_chart(cpi_yoy, use_container_width=True, height=200)
                        st.metric("Current CPI YoY", f"{cpi_yoy.iloc[-1]:.2f}%")
                except Exception as e:
                    st.caption(f"CPI unavailable: {e}")
            with fc2:
                try:
                    fed = fred.get_series('DFEDTARU', observation_start='2023-01-01')
                    if len(fed) > 0:
                        st.markdown("**Fed Funds Rate (%)**")
                        st.line_chart(fed, use_container_width=True, height=200)
                        st.metric("Current Rate", f"{fed.iloc[-1]:.2f}%")
                except Exception as e:
                    st.caption(f"Fed Rate unavailable: {e}")

            st.markdown("---")
            fc3, fc4 = st.columns(2)
            with fc3:
                try:
                    un = fred.get_series('UNRATE', observation_start='2023-01-01')
                    if len(un) > 0:
                        st.markdown("**Unemployment Rate (%)**")
                        st.line_chart(un, use_container_width=True, height=200)
                        st.metric("Unemployment", f"{un.iloc[-1]:.1f}%")
                except Exception as e:
                    st.caption(f"Unemployment unavailable: {e}")
            with fc4:
                try:
                    gdp = fred.get_series('A191RL1Q225SBEA', observation_start='2022-01-01')
                    if len(gdp) > 0:
                        st.markdown("**GDP Growth Rate (%)**")
                        st.line_chart(gdp, use_container_width=True, height=200)
                        st.metric("GDP Growth", f"{gdp.iloc[-1]:.1f}%")
                except Exception as e:
                    st.caption(f"GDP unavailable: {e}")
        else:
            st.warning("FRED_API_KEY not configured.")
    except Exception as e:
        st.error(f"FRED error: {e}")

    # PnL backtest
    st.markdown("---")
    st.markdown("#### 📊 Model PnL Backtest")
    st.caption("Compares model rate predictions against Kalshi contract outcomes.")
    try:
        from src.supabase_client import get_trade_history
        trades = get_trade_history(limit=100)
        if trades:
            df_t = pd.DataFrame(trades)
            if 'pnl_cents' in df_t.columns and df_t['pnl_cents'].notna().any():
                df_t['cumulative_pnl'] = df_t['pnl_cents'].cumsum() / 100
                st.line_chart(df_t['cumulative_pnl'], use_container_width=True, height=200)
                st.metric("Total PnL", f"${df_t['pnl_cents'].sum()/100:+.2f}")
            else:
                st.info("No PnL data yet.")
        else:
            st.info("No trade history yet. Run scanner to populate.")
    except Exception:
        st.info("Trade history populates after scanner writes to Supabase.")


# ═══════════════════════ TAB 5: BACKTESTING ═══════════════════
with tab_bt:
    st.markdown("### 📊 Backtesting — Engine Performance")

    bt_weather, bt_quant = st.tabs(["⛈️ Weather Accuracy", "🧪 Quant ML"])

    # ── Weather Prediction Accuracy ──
    with bt_weather:
        st.markdown("#### ⛈️ Weather Prediction Accuracy")
        st.caption("Tracks whether our model's predicted outcome matched the actual NWS-reported settlement.")

        try:
            from src.supabase_client import get_trade_history
            trades = get_trade_history(limit=200)
            wx_trades = [t for t in (trades or []) if t.get('engine', '').lower() == 'weather']

            if wx_trades:
                correct = sum(1 for t in wx_trades if t.get('resolved_outcome') is not None and
                              ((t.get('action', '').upper() == 'BUY YES' and t.get('resolved_outcome') == True) or
                               (t.get('action', '').upper() == 'BUY NO' and t.get('resolved_outcome') == False)))
                total_resolved = sum(1 for t in wx_trades if t.get('resolved_outcome') is not None)
                total_pending = len(wx_trades) - total_resolved

                m1, m2, m3 = st.columns(3)
                m1.metric("Total Predictions", len(wx_trades))
                if total_resolved > 0:
                    acc = (correct / total_resolved) * 100
                    m2.metric("Accuracy", f"{acc:.1f}%", f"{correct}/{total_resolved} correct")
                    m3.metric("Pending", total_pending)

                    # Daily accuracy breakdown
                    st.markdown("---")
                    st.markdown("##### 📅 Daily Accuracy")
                    daily_data = {}
                    for t in wx_trades:
                        if t.get('resolved_outcome') is None:
                            continue
                        day = str(t.get('market_date', t.get('created_at', '')))[:10]
                        if day not in daily_data:
                            daily_data[day] = {'correct': 0, 'total': 0}
                        daily_data[day]['total'] += 1
                        was_correct = (t.get('action', '').upper() == 'BUY YES' and t['resolved_outcome'] == True) or \
                                      (t.get('action', '').upper() == 'BUY NO' and t['resolved_outcome'] == False)
                        if was_correct:
                            daily_data[day]['correct'] += 1

                    if daily_data:
                        daily_df = pd.DataFrame([
                            {'Date': d, 'Accuracy %': (v['correct']/v['total'])*100, 'Trades': v['total']}
                            for d, v in sorted(daily_data.items())
                        ])
                        daily_df['Date'] = pd.to_datetime(daily_df['Date'], errors='coerce')
                        daily_df = daily_df.dropna(subset=['Date'])
                        if not daily_df.empty:
                            st.bar_chart(daily_df.set_index('Date')['Accuracy %'], use_container_width=True, height=200)
                            st.dataframe(daily_df.sort_values('Date', ascending=False), use_container_width=True, hide_index=True)
                else:
                    m2.metric("Accuracy", "—")
                    m3.metric("Pending", total_pending)
                    st.info("No resolved weather predictions yet. Outcomes populate after market settlement.")
            else:
                st.info("No weather trades logged yet. Run the scanner during market hours to generate predictions.")
        except Exception as e:
            st.info(f"Weather accuracy data will populate after the scanner runs: {e}")

    # ── Quant ML Backtesting ──
    with bt_quant:
        st.markdown("#### 🧪 Quant ML — Directional Accuracy & Kelly P&L")
        st.caption("Tests how well the model predicts hourly market direction using historical data with Quarter-Kelly position sizing.")

        # Model info box
        st.markdown("""
        <div class="quant-card">
            <strong style="color: #60a5fa;">How This Works</strong><br>
            <span style="color: #94a3b8; font-size: 0.85rem;">
            Our LightGBM model uses <strong>20 features</strong> across 3 clusters (Momentum, Microstructure, Derivatives)
            to predict the next-hour close price. A prediction is "correct" if the model predicts the right <em>direction</em>
            (up or down). We then simulate P&L using <strong>Quarter-Kelly sizing</strong> (0.25× optimal bet fraction)
            on each correct/incorrect call.<br><br>
            <strong>Auto-Retraining:</strong> The Self-Healing Optimizer runs weekly (<code>ai_optimizer.yml</code>),
            checks the Brier score, and automatically retrains if accuracy drifts below threshold (0.35).
            </span>
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")

        c1, c2 = st.columns(2)
        bankroll = c1.number_input("Starting Bankroll ($)", value=1000, min_value=100, max_value=100000)
        lookback = c2.selectbox("Lookback Period", ["1 Week", "2 Weeks", "1 Month"], index=1)

        lookback_map = {"1 Week": "5d", "2 Weeks": "5d", "1 Month": "1mo"}
        period = lookback_map.get(lookback, "5d")

        if st.button("🚀 Run Backtest", use_container_width=True):
            with st.spinner("Fetching data & running predictions..."):
                try:
                    from src.data_loader import fetch_data
                    from src.model_daily import load_daily_model, quarter_kelly
                    from src.feature_engineering import create_features, FEATURE_COLUMNS
                    import lightgbm as lgb

                    df = fetch_data("SPY", period=period, interval="1h")
                    if df.empty or len(df) < 10:
                        st.warning("Not enough historical data. Try again during market hours.")
                    else:
                        model = load_daily_model("SPY")
                        if model is None:
                            st.warning("No trained model found for SPY. Run the optimizer to train one.")
                        else:
                            df_feat, gex_data = create_features(df, "SPY")

                            # Dynamically get the model's expected features
                            if isinstance(model, lgb.Booster):
                                model_features = model.feature_name()
                            elif hasattr(model, 'feature_names_in_'):
                                model_features = list(model.feature_names_in_)
                            elif hasattr(model, 'booster_'):
                                model_features = model.booster_.feature_name()
                            else:
                                model_features = FEATURE_COLUMNS

                            # Add raw OHLCV columns if model expects them (old model compatibility)
                            for col in ['Close', 'High', 'Low', 'Open', 'Volume', 'minute']:
                                if col in model_features and col not in df_feat.columns:
                                    if col == 'minute':
                                        df_feat['minute'] = df_feat.index.minute
                                    # Close/High/Low/Open/Volume should already exist from original df

                            # Only keep rows where we have enough data
                            avail = [c for c in model_features if c in df_feat.columns]
                            df_clean = df_feat.dropna(subset=[c for c in avail if c in df_feat.columns])

                            if len(df_clean) < 5:
                                st.warning(f"Only {len(df_clean)} valid rows after features. Need 5+. Try '1 Month'.")
                            else:
                                # Align to model's features, fill missing with 0
                                X = df_clean.reindex(columns=model_features, fill_value=0)

                                if isinstance(model, lgb.Booster):
                                    preds = model.predict(X)
                                else:
                                    preds = model.predict(X)

                                actuals = df_clean['Close'].values

                                # Directional accuracy: did we predict the right direction?
                                results = []
                                equity = bankroll
                                equity_curve = []
                                daily_accuracy = {}

                                for i in range(1, len(actuals)):
                                    actual_dir = 1 if actuals[i] > actuals[i-1] else -1
                                    pred_dir = 1 if preds[i] > actuals[i-1] else -1
                                    correct = actual_dir == pred_dir

                                    # Expected move size
                                    actual_pct = abs(actuals[i] - actuals[i-1]) / actuals[i-1]

                                    # Kelly sizing
                                    edge = actual_pct  # approximate edge from move
                                    prob = 0.55  # base assumption
                                    kelly_pct = quarter_kelly(edge, prob, max_kelly_pct=6)
                                    bet_size = equity * (kelly_pct / 100)

                                    if correct:
                                        pnl = bet_size * actual_pct * 10  # leverage-adjusted
                                    else:
                                        pnl = -bet_size * actual_pct * 10

                                    equity += pnl
                                    ts = df_clean.index[i]
                                    equity_curve.append({'Time': ts, 'Equity': round(equity, 2)})

                                    day = str(ts.date())
                                    if day not in daily_accuracy:
                                        daily_accuracy[day] = {'correct': 0, 'total': 0}
                                    daily_accuracy[day]['total'] += 1
                                    if correct:
                                        daily_accuracy[day]['correct'] += 1

                                    results.append({
                                        'Time': ts,
                                        'Actual': round(actuals[i], 2),
                                        'Predicted': round(preds[i], 2),
                                        'Direction': '✅' if correct else '❌',
                                        'PnL': round(pnl, 2),
                                    })

                                total_correct = sum(1 for r in results if r['Direction'] == '✅')
                                total_trades = len(results)
                                win_rate = (total_correct / total_trades * 100) if total_trades > 0 else 0
                                total_pnl = equity - bankroll
                                total_return = (total_pnl / bankroll * 100) if bankroll > 0 else 0

                                # Max drawdown
                                peak = bankroll
                                max_dd = 0
                                for pt in equity_curve:
                                    if pt['Equity'] > peak:
                                        peak = pt['Equity']
                                    dd = (peak - pt['Equity']) / peak * 100
                                    if dd > max_dd:
                                        max_dd = dd

                                # Compute Brier score if direction classifier available
                                brier_score = None
                                try:
                                    from src.model_daily import load_direction_model
                                    dir_model = load_direction_model("SPY")
                                    if dir_model is not None:
                                        dir_probs = dir_model.predict_proba(X)[:, 1]
                                        actual_dirs = (df_clean['Close'].shift(-1) > df_clean['Close']).astype(int).values
                                        # Only compute on rows where we have the next bar
                                        valid = ~np.isnan(actual_dirs.astype(float))
                                        if valid.sum() > 5:
                                            brier_score = np.mean((dir_probs[valid] - actual_dirs[valid]) ** 2)
                                except Exception:
                                    pass

                                # Metrics strip
                                st.markdown("#### 📊 Results")
                                m1, m2, m3, m4, m5, m6 = st.columns(6)
                                m1.metric("Predictions", total_trades)
                                m2.metric("Win Rate", f"{win_rate:.1f}%")
                                m3.metric("Total P&L", f"${total_pnl:+,.2f}")
                                m4.metric("Return", f"{total_return:+.1f}%")
                                m5.metric("Max Drawdown", f"-{max_dd:.1f}%")
                                if brier_score is not None:
                                    brier_delta = "Edge ✓" if brier_score < 0.25 else "No edge"
                                    m6.metric("Brier Score", f"{brier_score:.4f}", brier_delta)
                                else:
                                    m6.metric("Brier Score", "—", "No classifier")

                                # Equity curve
                                st.markdown("---")
                                st.markdown("##### 📈 Equity Curve (Quarter-Kelly)")
                                eq_df = pd.DataFrame(equity_curve)
                                if not eq_df.empty:
                                    eq_df['Time'] = pd.to_datetime(eq_df['Time'], errors='coerce')
                                    eq_df = eq_df.dropna(subset=['Time'])
                                    if not eq_df.empty:
                                        st.line_chart(eq_df.set_index('Time')['Equity'], use_container_width=True, height=250)

                                # Daily accuracy
                                st.markdown("---")
                                st.markdown("##### 📅 Daily Directional Accuracy")
                                if daily_accuracy:
                                    day_df = pd.DataFrame([
                                        {'Date': d, 'Correct': v['correct'], 'Total': v['total'],
                                         'Accuracy %': round(v['correct']/v['total']*100, 1)}
                                        for d, v in sorted(daily_accuracy.items())
                                    ])
                                    st.dataframe(day_df, use_container_width=True, hide_index=True)

                                # Trade log
                                st.markdown("---")
                                with st.expander(f"📋 Full Trade Log ({total_trades} predictions)"):
                                    st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

                except Exception as e:
                    st.error(f"Backtest error: {e}")
                    import traceback
                    st.caption(traceback.format_exc())


# ═══════════════════════ TAB 6: QUANT GLOSSARY ════════════════
with tab_gloss:
    st.markdown("### 📖 The Quant Glossary")
    st.caption("Professional trading terminology used throughout this platform.")

    st.markdown("---")
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### 📈 Alpha & Math")
        with st.expander("⭐ Edge %", expanded=True):
            st.markdown("""
            **Edge = Model Probability − Market Price**

            If our model says a weather contract has a 75% chance of settling YES
            but Kalshi prices it at 50¢ (50%), our edge is +25%. This is the core
            alpha signal driving every trade recommendation.
            """)
        with st.expander("📐 Kelly Criterion (Quarter-Kelly)"):
            st.markdown("""
            **Kelly % = (edge × probability) / (1 − probability)**

            We enforce **Quarter-Kelly (0.25×)** sizing to manage risk. If full Kelly says
            bet 20% of bankroll, we bet 5%. This dramatically reduces drawdowns while
            capturing ~75% of the theoretical growth rate.
            """)
        with st.expander("📊 Brier Score"):
            st.markdown("""
            **Brier = (1/N) × Σ(forecast − outcome)²**

            Measures probabilistic accuracy. Range: 0 (perfect) to 1 (worst).
            A score < 0.25 indicates the model outperforms naive coin-flip prediction.
            Used to detect model drift and trigger retraining.
            """)
        with st.expander("📉 Amihud Illiquidity Ratio"):
            st.markdown("""
            **Amihud = |Return| / Dollar Volume**

            Measures price impact per unit of dollar volume traded. High values
            indicate illiquid markets where large orders move prices significantly.
            Spikes signal potential liquidity cascades.
            """)

    with col_b:
        st.markdown("#### 🛡️ Risk & Execution")
        with st.expander("↔️ Bid-Ask Spread", expanded=True):
            st.markdown("""
            The difference between the best buy and sell prices. A 3¢ spread on a
            50¢ contract means you pay 51.5¢ to buy and receive 48.5¢ to sell.
            Tighter spreads = more liquid market = better execution.
            """)
        with st.expander("📊 Corwin-Schultz Spread"):
            st.markdown("""
            **Synthetic bid-ask spread estimated from daily High/Low prices.**

            Uses the statistical relationship between price range and volatility to
            estimate the effective spread without needing tick-level data. A key input
            to our microstructure feature cluster.
            """)
        with st.expander("🎯 GEX (Gamma Exposure)"):
            st.markdown("""
            **GEX = Σ(Open Interest × Gamma × Spot² × 0.01)**

            Aggregate gamma across all strikes. **Positive GEX** = dealers sell into
            rallies and buy dips (stabilizing). **Negative GEX** = dealers amplify
            moves (destabilizing). GEX flips are major regime changes.
            """)
        with st.expander("⏱️ Annualized EV"):
            st.markdown("""
            **AEV = Edge% × (365 / Days-to-Resolution)**

            Normalizes edge across different contract durations. A 5% edge on a
            1-day contract (AEV = 1,825%) is far more attractive than 20% edge
            on a 90-day contract (AEV = 81%).
            """)

    st.markdown("---")
    st.caption("Kalshi Edge Finder • Quantitative Infrastructure for Event Markets")
