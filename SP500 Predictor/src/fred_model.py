"""
FRED Economic Analysis — Federal Reserve Economic Data
Uses FRED API to pull macro indicators and compare against Kalshi economic markets.
"""

import os
import requests
import pandas as pd
from datetime import datetime, timezone
from dotenv import load_dotenv
from pathlib import Path

# Load .env
root_dir = Path(__file__).parent.parent
load_dotenv(dotenv_path=root_dir / '.env', override=True)

FRED_API_KEY = os.getenv("FRED_API_KEY")
FRED_BASE_URL = "https://api.stlouisfed.org/fred"

# ─── Key FRED Series for Kalshi Markets ──────────────────────────────
FRED_SERIES = {
    "fed_rate":     {"id": "DFEDTARU", "name": "Fed Funds Target Rate (Upper)", "unit": "%"},
    "cpi":          {"id": "CPIAUCSL", "name": "CPI (All Urban)", "unit": "Index"},
    "cpi_yoy":      {"id": "CPIAUCNS", "name": "CPI Year-over-Year", "unit": "%"},
    "unemployment": {"id": "UNRATE", "name": "Unemployment Rate", "unit": "%"},
    "gdp":          {"id": "GDP", "name": "GDP (Nominal)", "unit": "Billions $"},
    "gdp_growth":   {"id": "A191RL1Q225SBEA", "name": "Real GDP Growth Rate", "unit": "%"},
    "treasury_10y": {"id": "DGS10", "name": "10-Year Treasury Yield", "unit": "%"},
    "treasury_2y":  {"id": "DGS2", "name": "2-Year Treasury Yield", "unit": "%"},
    "inflation_exp":{"id": "T5YIE", "name": "5-Year Breakeven Inflation", "unit": "%"},
    "sp500":        {"id": "SP500", "name": "S&P 500 Index", "unit": "Index"},
    "vix":          {"id": "VIXCLS", "name": "VIX Volatility Index", "unit": "Index"},
    "consumer_sent":{"id": "UMCSENT", "name": "U of Michigan Consumer Sentiment", "unit": "Index"},
    "housing_starts":{"id": "HOUST", "name": "Housing Starts", "unit": "Thousands"},
    "jobs_nonfarm": {"id": "PAYEMS", "name": "Nonfarm Payrolls", "unit": "Thousands"},
    "pce":          {"id": "PCE", "name": "Personal Consumption Expenditures", "unit": "Billions $"},
    "debt_gdp":     {"id": "GFDEGDQ188S", "name": "Federal Debt to GDP Ratio", "unit": "%"},
}


def _fred_get(endpoint, params):
    """Makes a FRED API request."""
    if not FRED_API_KEY:
        return None
    params["api_key"] = FRED_API_KEY
    params["file_type"] = "json"
    try:
        r = requests.get(f"{FRED_BASE_URL}/{endpoint}", params=params, timeout=10)
        if r.status_code == 200:
            return r.json()
    except Exception as e:
        print(f"    ❌ FRED API Error: {e}")
    return None


def get_fred_series(series_key, limit=60):
    """
    Fetches recent observations for a FRED series.
    
    Args:
        series_key: Key from FRED_SERIES dict (e.g., "fed_rate")
        limit: Number of observations to fetch
        
    Returns:
        pd.DataFrame with columns ['date', 'value'] or None
    """
    if series_key not in FRED_SERIES:
        return None
    
    series_id = FRED_SERIES[series_key]["id"]
    data = _fred_get("series/observations", {
        "series_id": series_id,
        "sort_order": "desc",
        "limit": limit
    })
    
    if not data or 'observations' not in data:
        return None
    
    rows = []
    for obs in data['observations']:
        try:
            val = float(obs['value'])
            rows.append({
                'date': obs['date'],
                'value': val
            })
        except (ValueError, TypeError):
            continue
    
    if not rows:
        return None
    
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date')
    return df


def get_macro_dashboard():
    """
    Fetches latest values for key macro indicators.
    Returns a dict suitable for display in the UI.
    """
    dashboard = {}
    
    key_series = [
        "fed_rate", "unemployment", "cpi_yoy", "gdp_growth",
        "treasury_10y", "treasury_2y", "vix", "consumer_sent",
        "debt_gdp", "inflation_exp"
    ]
    
    for key in key_series:
        series_info = FRED_SERIES[key]
        df = get_fred_series(key, limit=5)
        
        if df is not None and not df.empty:
            latest = df.iloc[-1]
            prev = df.iloc[-2] if len(df) >= 2 else None
            
            change = None
            if prev is not None:
                change = latest['value'] - prev['value']
            
            dashboard[key] = {
                "name": series_info["name"],
                "value": latest['value'],
                "unit": series_info["unit"],
                "date": latest['date'].strftime("%Y-%m-%d"),
                "change": change,
                "series_id": series_info["id"]
            }
        else:
            dashboard[key] = {
                "name": series_info["name"],
                "value": None,
                "unit": series_info["unit"],
                "date": None,
                "change": None,
                "series_id": series_info["id"]
            }
    
    return dashboard


def analyze_fed_markets(kalshi_markets, dashboard=None):
    """
    Analyzes Kalshi Economics markets using FRED data.
    
    Compares FRED indicators (Fed rate, CPI, unemployment) against
    Kalshi market prices to find edges.
    
    Returns list of analysis dicts.
    """
    if dashboard is None:
        dashboard = get_macro_dashboard()
    
    analysis = []
    
    econ_markets = [m for m in kalshi_markets if m.get('category') == 'Economics']
    
    for m in econ_markets:
        title = m['title'].lower()
        
        # Fed Rate Markets
        if any(kw in title for kw in ['fed', 'rate', 'fomc', 'interest']):
            fed_data = dashboard.get('fed_rate')
            if fed_data and fed_data['value'] is not None:
                analysis.append({
                    "market": m['title'],
                    "category": "Fed Rate",
                    "current_indicator": f"{fed_data['value']:.2f}%",
                    "indicator_name": fed_data['name'],
                    "kalshi_price": m['price'],
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                    "insight": _generate_fed_insight(title, fed_data['value'])
                })
        
        # Unemployment Markets  
        elif any(kw in title for kw in ['unemployment', 'jobs', 'payroll', 'nonfarm']):
            unemp = dashboard.get('unemployment')
            if unemp and unemp['value'] is not None:
                analysis.append({
                    "market": m['title'],
                    "category": "Jobs",
                    "current_indicator": f"{unemp['value']:.1f}%",
                    "indicator_name": unemp['name'],
                    "kalshi_price": m['price'],
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                    "insight": _generate_unemployment_insight(title, unemp['value'])
                })
        
        # Debt/GDP Markets
        elif any(kw in title for kw in ['debt', 'gdp', 'deficit']):
            debt = dashboard.get('debt_gdp')
            gdp = dashboard.get('gdp_growth')
            indicator = debt if debt and debt['value'] else gdp
            if indicator and indicator['value'] is not None:
                analysis.append({
                    "market": m['title'],
                    "category": "Fiscal",
                    "current_indicator": f"{indicator['value']:.1f}{indicator['unit']}",
                    "indicator_name": indicator['name'],
                    "kalshi_price": m['price'],
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                    "insight": f"Current: {indicator['value']:.1f}{indicator['unit']}"
                })
        
        # CPI/Inflation Markets
        elif any(kw in title for kw in ['cpi', 'inflation']):
            infl = dashboard.get('inflation_exp')
            if infl and infl['value'] is not None:
                analysis.append({
                    "market": m['title'],
                    "category": "Inflation",
                    "current_indicator": f"{infl['value']:.2f}%",
                    "indicator_name": infl['name'],
                    "kalshi_price": m['price'],
                    "volume": m.get('volume', 0),
                    "ticker": m.get('ticker', ''),
                    "insight": f"Breakeven: {infl['value']:.2f}%"
                })
    
    return analysis


def _generate_fed_insight(title, current_rate):
    """Generates insight text for Fed rate markets."""
    if 'cut' in title:
        return f"Current rate: {current_rate:.2f}%. Market expects cuts."
    elif 'hike' in title:
        return f"Current rate: {current_rate:.2f}%. Market expects hikes."
    return f"Fed Funds rate at {current_rate:.2f}%"


def _generate_unemployment_insight(title, current_rate):
    """Generates insight text for unemployment markets."""
    import re
    strike_match = re.search(r'(\d+(?:\.\d+)?)\s*%?', title)
    if strike_match:
        strike = float(strike_match.group(1))
        diff = current_rate - strike
        if diff > 0:
            return f"Currently at {current_rate:.1f}% (already above {strike}%)"
        else:
            return f"Currently at {current_rate:.1f}% ({abs(diff):.1f}% below {strike}%)"
    return f"Unemployment at {current_rate:.1f}%"


def get_yield_curve():
    """
    Fetches 2Y and 10Y Treasury yields for yield curve analysis.
    Returns spread (10Y - 2Y) — negative = inverted = recession signal.
    """
    t10 = get_fred_series("treasury_10y", limit=30)
    t2 = get_fred_series("treasury_2y", limit=30)
    
    if t10 is None or t2 is None:
        return None
    
    # Merge on date
    merged = pd.merge(t10, t2, on='date', suffixes=('_10y', '_2y'))
    merged['spread'] = merged['value_10y'] - merged['value_2y']
    
    return {
        "latest_10y": merged['value_10y'].iloc[-1],
        "latest_2y": merged['value_2y'].iloc[-1],
        "spread": merged['spread'].iloc[-1],
        "inverted": merged['spread'].iloc[-1] < 0,
        "history": merged[['date', 'spread']].to_dict('records')
    }
