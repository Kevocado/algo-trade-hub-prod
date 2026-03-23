"""
Hybrid Scanner — Category-Aware Market Scanner with Quant Engine
Split into per-tab methods for independent refresh.
"""

import re
import os
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from src.kalshi_feed import get_all_active_markets

# ─── Import ML pipeline (graceful fallback) ─────────────────────────
try:
    from src.data_loader import fetch_data
    from src.feature_engineering import create_features
    from src.model import (
        load_model, predict_next_hour,
        get_market_volatility, calculate_probability,
        kelly_criterion
    )
    ML_AVAILABLE = True
except ImportError as e:
    ML_AVAILABLE = False
    print(f"⚠️ ML Modules not available: {e}")

# Import Weather Arb
try:
    from src.weather_model import scan_weather_markets
    WEATHER_ARB_AVAILABLE = True
except ImportError:
    WEATHER_ARB_AVAILABLE = False
    print("⚠️ Weather arb module not available.")

# Import FRED Analysis
try:
    from src.fred_model import get_macro_dashboard, analyze_fed_markets, get_yield_curve
    FRED_AVAILABLE = True
except ImportError:
    FRED_AVAILABLE = False
    print("⚠️ FRED analysis module not available.")


def _kalshi_url(event_ticker, market_ticker=None):
    """Builds a direct Kalshi URL using the event_ticker (lowercase)."""
    if not event_ticker:
        if market_ticker:
            # Fallback: try to derive event_ticker from market_ticker
            # e.g. KXBTC-26FEB28-T95000 → kxbtc
            event_ticker = market_ticker.split('-')[0] if '-' in market_ticker else market_ticker
        else:
            return "#"
    return f"https://kalshi.com/markets/{event_ticker.lower()}"


def _generate_reasoning(sig):
    """
    Generates plain-English reasoning for why a quant signal is good.
    Uses the signal dict fields to build a human-readable explanation.
    """
    asset = sig['Asset']
    price = sig['Current_Price']
    pred = sig['Model_Pred']
    strike = sig['Strike']
    edge = sig['Edge']
    my_prob = sig['My_Prob']
    kalshi = sig['Kalshi_Price']
    vol = sig['Volatility']
    hours = sig['Hours_Left']
    action = sig['Action']
    kelly = sig['Kelly_Bet']

    # Direction
    if pred > price:
        direction = "upward"
        pct_move = (pred - price) / price * 100
    else:
        direction = "downward"
        pct_move = (price - pred) / price * 100

    # Distance to strike
    dist_pct = abs(price - strike) / price * 100
    if price > strike:
        position = f"already ${price - strike:,.0f} above"
    else:
        position = f"${strike - price:,.0f} below"

    # Time context
    if hours < 2:
        time_ctx = f"just {hours:.1f}h left — this resolves soon"
    elif hours < 24:
        time_ctx = f"{hours:.0f}h to expiry"
    else:
        days = hours / 24
        time_ctx = f"{days:.0f} days to expiry"

    # Build the reasoning
    parts = []

    # ML prediction context
    parts.append(
        f"The ML model predicts {asset} at ${pred:,.2f} "
        f"({'up' if pred > price else 'down'} {pct_move:.1f}% from ${price:,.2f})."
    )

    # Strike position
    parts.append(
        f"Price is {position} the ${strike:,.0f} strike."
    )

    # Probability + edge
    if edge > 0:
        parts.append(
            f"Our math gives {my_prob:.0f}% probability of finishing above the strike, "
            f"but Kalshi prices this at only {kalshi}¢ — that's a +{edge:.0f}% edge."
        )
    else:
        parts.append(
            f"Our math says only {my_prob:.0f}% chance of being above strike, "
            f"but Kalshi prices YES at {kalshi}¢ — better to {action} for a {abs(edge):.0f}% edge."
        )

    # Time + vol
    parts.append(f"With {time_ctx} and σ={vol:.4f}, Kelly says risk ${kelly:.2f}.")

    return " ".join(parts)


class HybridScanner:
    def __init__(self):
        self.markets = []
        self.last_fetch = None
        self.fred_dashboard = None

    # ═══════════════════════════════════════════════════════════════
    # STEP 1: Fetch markets (shared across all tabs)
    # ═══════════════════════════════════════════════════════════════
    def fetch_markets(self):
        """
        Fetches all active markets from Kalshi.
        Call this once, then use per-tab scan methods.
        """
        self.markets = get_all_active_markets(limit_pages=10)
        self.last_fetch = datetime.now(timezone.utc)

        cats = {}
        for m in self.markets:
            cats[m['category']] = cats.get(m['category'], 0) + 1
        print(f"📊 Category breakdown: {dict(sorted(cats.items(), key=lambda x: -x[1]))}")
        return len(self.markets)

    # ═══════════════════════════════════════════════════════════════
    # STEP 2: Per-tab scan methods (can be called independently)
    # ═══════════════════════════════════════════════════════════════

    def scan_quant(self):
        """
        Scans SPX, BTC, ETH, Nasdaq with Black-Scholes + Kelly.
        Returns list of signal dicts with Kalshi URL and reasoning.
        """
        if not ML_AVAILABLE or not self.markets:
            return []

        signals = []
        targets = ["SPX", "BTC", "ETH", "Nasdaq"]

        fin_markets = [m for m in self.markets
                       if m['category'] in ['Financials', 'Economics']]

        # Fetch price data + model predictions (once per asset)
        data_cache = {}
        for ticker in targets:
            try:
                df = fetch_data(ticker, period="5d", interval="1h")
                model, _ = load_model(ticker)

                if model and not df.empty:
                    df_feat = create_features(df)
                    pred_val = predict_next_hour(model, df_feat, ticker)
                    curr_price = df['Close'].iloc[-1]
                    vol = get_market_volatility(df, window=24)

                    data_cache[ticker] = {
                        "df": df, "model": model,
                        "vol": vol, "price": curr_price, "pred": pred_val
                    }
                    print(f"    ✅ {ticker}: Price={curr_price:.2f}, Pred={pred_val:.2f}, Vol={vol:.6f}")
            except Exception as e:
                print(f"    ⚠️ Skipping {ticker}: {e}")

        for m in fin_markets:
            asset = None
            for ticker in targets:
                if ticker == "SPX" and "INX" in m.get('ticker', ''):
                    asset = ticker
                elif ticker == "Nasdaq" and "NAS" in m.get('ticker', ''):
                    asset = ticker
                elif ticker in m.get('ticker', '') or ticker in m.get('title', ''):
                    asset = ticker
                if asset:
                    break

            if not asset or asset not in data_cache:
                continue

            d = data_cache[asset]

            try:
                strike_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', m['title'])
                if not strike_match:
                    continue
                strike = float(strike_match.group(1).replace(',', ''))
            except:
                continue

            hours_left = 1.0
            if m.get('expiration'):
                try:
                    exp = pd.to_datetime(m['expiration'])
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    hours_left = max(0.1, (exp - datetime.now(timezone.utc)).total_seconds() / 3600)
                except:
                    pass

            is_above = ">" in m['title'] or "above" in m['title'].lower()
            my_prob = calculate_probability(d['price'], d['pred'], strike, d['vol'], hours_left)
            if not is_above:
                my_prob = 100 - my_prob

            bet_size = kelly_criterion(my_prob, m['price'], bankroll=20, fractional=0.25)
            edge = my_prob - m['price']

            if abs(edge) > 5 and bet_size > 0:
                action = "BUY YES" if edge > 0 else "BUY NO"
                sig = {
                    "Asset": asset,
                    "Market": m['title'],
                    "Model_Pred": round(d['pred'], 2),
                    "Current_Price": round(d['price'], 2),
                    "Strike": strike,
                    "Kalshi_Price": m['price'],
                    "My_Prob": round(my_prob, 1),
                    "Edge": round(edge, 1),
                    "Kelly_Bet": bet_size,
                    "Action": action,
                    "Volatility": round(d['vol'], 6),
                    "Hours_Left": round(hours_left, 1),
                    "Ticker": m.get('ticker', ''),
                    "Kalshi_URL": _kalshi_url(m.get('event_ticker', ''), m.get('ticker', '')),
                }
                sig["Reasoning"] = _generate_reasoning(sig)
                signals.append(sig)

        signals.sort(key=lambda x: abs(x['Edge']), reverse=True)
        return signals

    def scan_weather_arb(self):
        """Runs weather arbitrage model."""
        if not WEATHER_ARB_AVAILABLE or not self.markets:
            return []
        try:
            results = scan_weather_markets(self.markets)
            # Add Kalshi URLs
            for r in results:
                r['kalshi_url'] = _kalshi_url(r.get('event_ticker', ''), r.get('ticker', ''))
            return results
        except Exception as e:
            print(f"    ⚠️ Weather arb scan failed: {e}")
            return []

    def scan_fred(self):
        """Analyzes Kalshi economics markets using FRED data."""
        if not FRED_AVAILABLE:
            return {"dashboard": {}, "analysis": [], "yield_curve": None}
        try:
            if self.fred_dashboard is None:
                print("📈 Fetching FRED macro data...")
                self.fred_dashboard = get_macro_dashboard()
            analysis = analyze_fed_markets(self.markets, self.fred_dashboard)
            yield_curve = get_yield_curve()
            return {
                "dashboard": self.fred_dashboard,
                "analysis": analysis,
                "yield_curve": yield_curve
            }
        except Exception as e:
            print(f"    ⚠️ FRED analysis failed: {e}")
            return {"dashboard": {}, "analysis": [], "yield_curve": None}

    def scan_smart_money(self):
        """Economics + Politics markets."""
        return [m for m in self.markets if m['category'] in ['Economics', 'Politics']]

    def scan_weather_raw(self):
        """All weather markets."""
        return [m for m in self.markets if m['category'] == 'Weather']

    def scan_arbitrage(self):
        """Negative spread detection."""
        opps = []
        for m in self.markets:
            if m['no_price'] > 0:
                cost = m['price'] + m['no_price']
                if cost < 100:
                    opps.append({
                        **m, "cost": cost, "profit": 100 - cost,
                        "kalshi_url": _kalshi_url(m.get('event_ticker', ''), m.get('ticker', ''))
                    })
        opps.sort(key=lambda x: x['profit'], reverse=True)
        return opps

    def scan_yield_farms(self):
        """Safe 92-98¢ bets <48h, excluding Sports."""
        opps = []
        now = datetime.now(timezone.utc)
        for m in self.markets:
            if m['category'] == 'Sports':
                continue
            if 92 <= m['price'] <= 98:
                if not m['expiration']:
                    continue
                try:
                    exp = pd.to_datetime(m['expiration'])
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    hours = (exp - now).total_seconds() / 3600
                    if 0 < hours < 48:
                        roi = (100 - m['price']) / m['price'] * 100
                        opps.append({
                            **m, "hours_left": int(hours), "roi": roi,
                            "kalshi_url": _kalshi_url(m.get('event_ticker', ''), m.get('ticker', ''))
                        })
                except:
                    continue
        opps.sort(key=lambda x: x['roi'], reverse=True)
        return opps

    # ═══════════════════════════════════════════════════════════════
    # PHASE 2: Sports Analytics Engines
    # ═══════════════════════════════════════════════════════════════

    def scan_nba(self):
        """NBA player props — BallDontLie model vs Kalshi NBA markets."""
        try:
            from scripts.engines.nba_engine import NBAEngine
            engine = NBAEngine(min_edge_pct=12.0)
            signals = engine.get_signals()
            for s in signals:
                s.setdefault('engine', 'nba_props')
                s.setdefault('asset', s.get('player', '?'))
                s.setdefault('edge', s.get('edge_pct', 0))
            return signals
        except Exception as e:
            print(f"    ⚠️ NBA scan failed: {e}")
            return []

    def scan_f1(self):
        """F1 telemetry — FastF1 sector z-scores and tyre degradation vs Kalshi F1 markets."""
        try:
            from scripts.engines.f1_engine import F1Engine
            engine = F1Engine(min_edge_pct=10.0)
            signals = engine.get_latest_signals()
            for s in signals:
                s.setdefault('engine', 'f1_telemetry')
                s.setdefault('asset', s.get('driver', '?'))
                s.setdefault('edge', s.get('edge_pct', 0))
            return signals
        except Exception as e:
            print(f"    ⚠️ F1 scan failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # PHASE 4: Crypto Microstructure
    # ═══════════════════════════════════════════════════════════════

    def scan_crypto_microstructure(self, symbols: list = None, validate_with_ai: bool = True):
        """Binance funding rate z-score + order book imbalance + AI scrutinizer."""
        if symbols is None:
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        try:
            from src.microstructure_engine import MicrostructureEngine
            engine = MicrostructureEngine()
            signals = []
            for sym in symbols:
                sig = engine.get_crypto_signal(sym, validate_with_ai=validate_with_ai)
                if sig.get('direction') not in ('FLAT', 'ABORTED'):
                    sig.setdefault('engine', 'crypto_microstructure')
                    sig.setdefault('asset', sym)
                    sig.setdefault('edge', round(sig.get('confidence', 50) - 50, 1))
                    signals.append(sig)
            return signals
        except Exception as e:
            print(f"    ⚠️ Crypto microstructure scan failed: {e}")
            return []

    # ═══════════════════════════════════════════════════════════════
    # CONVENIENCE: Full scan (calls all per-tab methods)
    # ═══════════════════════════════════════════════════════════════
    def run_full_scan(self):
        """Fetches markets + runs all strategies. Returns dict."""
        self.fetch_markets()
        return {
            # Original engines (preserved)
            "quant_financials":      self.scan_quant(),
            "weather_arb":           self.scan_weather_arb(),
            "fred_analysis":         self.scan_fred(),
            "smart_money":           self.scan_smart_money(),
            "weather":               self.scan_weather_raw(),
            "arbitrage":             self.scan_arbitrage(),
            "yield_farming":         self.scan_yield_farms(),
            # Phase 2 — Sports
            "nba_props":             self.scan_nba(),
            "f1_telemetry":          self.scan_f1(),
            # Phase 4 — Crypto
            "crypto_microstructure": self.scan_crypto_microstructure(),
        }
