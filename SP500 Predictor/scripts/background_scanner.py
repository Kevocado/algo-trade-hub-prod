"""
Background Scanner — Multi-Engine Compute-on-Write
Runs from GitHub Actions (or locally). Executes Weather + Macro engines first (real edge),
then Quant engine (paper trading). All real-edge ops go through AI Validator.

ARCHITECTURE:
  Tier 1 (Real Edge): Weather Engine + Macro Engine → AI Validator → Supabase kalshi_edges
  Tier 2 (Paper):     Quant Engine → Supabase paper_trading_signals
"""

import os
import sys
import re
import json
from datetime import datetime, timezone
from dotenv import load_dotenv
import pandas as pd

# Add project root to path so we can import src modules and shared
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(os.path.join(os.path.dirname(__file__), '../..'))
sys.path.append(os.getcwd())

from scripts.engines.weather_engine import WeatherEngine
from scripts.engines.macro_engine import MacroEngine
from scripts.engines.tsa_engine import TSAEngine
from scripts.engines.eia_engine import EIAEngine
from scripts.engines.nba_engine import NBAEngine
from scripts.engines.f1_engine import F1Engine
from scripts.engines.ncaa_engine import NCAAEngine
from scripts.engines.football_engine import FootballKalshiEngine
from src.data_loader import fetch_data
from src.feature_engineering import create_features
from src.discord_notifier import DiscordNotifier
from scripts.engines.quant_engine import (
    load_model,
    predict_next_hour,
    calculate_probability,
    get_market_volatility,
    kelly_criterion,
)
from src.ai_validator import AIValidator
from src.news_analyzer import NewsAnalyzer
from src.predictit_engine import PredictItEngine
from src.kalshi_feed import get_real_kalshi_markets
from src.supabase_client import get_client, insert_paper_signal, upsert_opportunities, upsert_portfolio_metrics
from src.kalshi_portfolio import KalshiPortfolio

# ─── Environment ─────────────────────────────────────────────────────
load_dotenv()
EDGE_THRESHOLD = 5.0

# ─── Portfolio Sync ──────────────────────────────────────────────────

def update_live_portfolio():
    """Fetch live Kalshi balance and sync to Supabase."""
    print("\n💰 Syncing Live Kalshi Portfolio...")
    try:
        kp = KalshiPortfolio()
        summary = kp.get_portfolio_summary()
        
        if summary.get('error'):
            print(f"  ⚠️ Kalshi Portfolio Error: {summary['error']}")
            return

        metrics = {
            "total_value": summary.get("portfolio_value", 0),
            "daily_pnl": summary.get("total_pnl", 0),
            "cash_balance": summary.get("balance", 0)
        }
        
        upsert_portfolio_metrics(metrics)
        print(f"  ✅ Portfolio Updated: ${metrics['total_value']:.2f} (PnL: ${metrics['daily_pnl']:.2f})")
    except Exception as e:
        print(f"  ⚠️ Portfolio Sync failed: {e}")

# ═════════════════════════════════════════════════════════════════════
# TIER 1: REAL EDGE — Weather + Macro
# ═════════════════════════════════════════════════════════════════════

def scan_real_edge():
    """
    Run Weather and Macro engines.
    Returns raw math-based opportunities.
    """
    all_ops = []

    # ── Weather Engine ──
    print("\n⛈️ Running Weather Engine...")
    try:
        weather_engine = WeatherEngine()
        weather_ops = weather_engine.find_opportunities()
        for op in weather_ops: op["edge_type"] = "WEATHER"
        print(f"  Found {len(weather_ops)} weather opportunities")
        all_ops.extend(weather_ops)
    except Exception as e:
        print(f"  ⚠️ Weather Engine failed: {e}")

    # ── Macro Engine ──
    print("\n🏛️ Running Macro Engine...")
    try:
        macro_engine = MacroEngine()
        macro_ops = macro_engine.find_opportunities()
        for op in macro_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(macro_ops)} macro opportunities")
        all_ops.extend(macro_ops)
    except Exception as e:
        print(f"  ⚠️ Macro Engine failed: {e}")

    # ── TSA Travel Engine ──
    print("\n✈️ Running TSA Engine...")
    try:
        tsa_engine = TSAEngine()
        tsa_ops = tsa_engine.find_opportunities()
        for op in tsa_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(tsa_ops)} TSA opportunities")
        all_ops.extend(tsa_ops)
    except Exception as e:
        print(f"  ⚠️ TSA Engine failed: {e}")

    # ── EIA Energy Engine ──
    print("\n⛽ Running EIA Engine...")
    try:
        eia_engine = EIAEngine()
        eia_ops = eia_engine.find_opportunities()
        for op in eia_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(eia_ops)} EIA opportunities")
        all_ops.extend(eia_ops)
    except Exception as e:
        print(f"  ⚠️ EIA Engine failed: {e}")

    # ── Sports Schedule Fetchers ──
    print("\n🏀 Running NBA Schedule Fetcher...")
    try:
        nba_ops = NBAEngine().fetch_upcoming_games()
        all_ops.extend(nba_ops)
        print(f"  Found {len(nba_ops)} NBA upcoming games")
    except Exception as e:
        print(f"  ⚠️ NBA fetcher failed: {e}")
        
    print("\n🏎️ Running F1 Schedule Fetcher...")
    try:
        f1_ops = F1Engine().fetch_upcoming_races()
        all_ops.extend(f1_ops)
        print(f"  Found {len(f1_ops)} F1 upcoming races")
    except Exception as e:
        print(f"  ⚠️ F1 fetcher failed: {e}")
        
    print("\n🏀 Running NCAA March Madness Fetcher...")
    try:
        ncaa_ops = NCAAEngine().fetch_upcoming_march_madness()
        all_ops.extend(ncaa_ops)
        print(f"  Found {len(ncaa_ops)} NCAA tournament games")
    except Exception as e:
        print(f"  ⚠️ NCAA fetcher failed: {e}")

    print("\n⚽ Running Soccer Engine...")
    try:
        soccer_ops = FootballKalshiEngine().find_opportunities()
        all_ops.extend(soccer_ops)
        print(f"  Found {len(soccer_ops)} Soccer upcoming opportunities")
    except Exception as e:
        print(f"  ⚠️ Soccer engine failed: {e}")

    print(f"\n📊 Total real-edge opportunities: {len(all_ops)}")
    return all_ops


# ═════════════════════════════════════════════════════════════════════
# TIER 2: PAPER TRADING — Quant ML
# ═════════════════════════════════════════════════════════════════════

def scan_quant_ml():
    """
    Quant ML scanner for BTC-USD (Walk-Forward).
    """
    from scripts.engines.quant_engine import fetch_live_btc_alpaca, create_walk_forward_features
    
    tickers = ["BTC-USD"]
    snapshot_records = []
    paper_opportunities = []

    data_cache = {}
    for ticker in tickers:
        try:
            print(f"    📡 Fetching live {ticker} from Alpaca API...")
            df = fetch_live_btc_alpaca()
            if df.empty:
                continue
                
            model, needs_retrain = load_model(ticker)

            if model:
                df_feat = create_walk_forward_features(df)
                pred_val = predict_next_hour(model, df_feat, ticker)
                curr_price = df['Close'].iloc[-1]
                vol = get_market_volatility(df, window=24)

                data_cache[ticker] = {
                    "df": df, "model": model, "vol": vol,
                    "price": curr_price, "pred": pred_val,
                }
                print(f"    ✅ {ticker}: Price={curr_price:.2f}, Pred UP={pred_val*100:.1f}%, Vol={vol:.6f}")
        except Exception as e:
            print(f"    ⚠️ Skipping {ticker}: {e}")

    for ticker in tickers:
        if ticker not in data_cache:
            continue

        d = data_cache[ticker]
        markets, method, debug = get_real_kalshi_markets(ticker)
        print(f"    📡 {ticker}: {len(markets)} markets via {method}")

        for m in markets:
            try:
                strike_match = re.search(r'(\d{1,3}(?:,\d{3})*(?:\.\d+)?)', m.get('title', ''))
                if not strike_match:
                    continue
                strike = float(strike_match.group(1).replace(',', ''))
            except Exception:
                continue

            hours_left = 1.0
            exp_str = m.get('expiration')
            if exp_str:
                try:
                    exp = pd.to_datetime(exp_str)
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=timezone.utc)
                    hours_left = max(0.1, (exp - datetime.now(timezone.utc)).total_seconds() / 3600)
                except Exception:
                    pass

            title = m.get('title', '')
            is_above = ">" in title or "above" in title.lower()
            my_prob = d['pred'] * 100
            if not is_above:
                my_prob = 100 - my_prob

            yes_ask = m.get('yes_ask', 0)
            edge = my_prob - yes_ask
            bet_size = kelly_criterion(my_prob, yes_ask, bankroll=20, fractional=0.25)

            record = {
                "ticker": ticker, "market_title": title,
                "market_id": m.get('market_id', ''), "strike": strike,
                "expiration": exp_str, "current_price": round(d['price'], 2),
                "model_pred": round(d['pred'], 2), "volatility": round(d['vol'], 6),
                "hours_left": round(hours_left, 1), "model_prob": round(my_prob, 2),
                "market_yes_ask": yes_ask, "calculated_edge": round(edge, 2),
                "kelly_bet": round(bet_size, 2),
            }
            snapshot_records.append(record)

            if abs(edge) > EDGE_THRESHOLD and bet_size > 0:
                action = "BUY YES" if edge > 0 else "BUY NO"
                edge_type = "CRYPTO"
                paper_opportunities.append({
                    "edge_type": edge_type,
                    "Asset": ticker, "Market": title[:200], "Strike": str(strike),
                    "Confidence": float(round(my_prob, 1)),
                    "Edge": float(round(edge, 1)), "Action": action,
                    "KellySuggestion": float(round(bet_size, 2)),
                    "CurrentPrice": float(round(d['price'], 2)),
                    "ModelPred": float(round(d['pred'], 2)),
                    "Volatility": float(round(d['vol'], 6)),
                    "HoursLeft": float(round(hours_left, 1)),
                    "MarketYesAsk": int(yes_ask),
                    "Expiration": exp_str or "",
                    "MarketId": m.get('market_id', ''),
                    "Status": "PAPER TRADE ONLY",
                    "Engine": "Quant",
                })

    return snapshot_records, paper_opportunities


# ═════════════════════════════════════════════════════════════════════
# MAIN ORCHESTRATOR
# ═════════════════════════════════════════════════════════════════════

def run_scan():
    """Main scanning logic — prioritizes real edge markets."""
    now = datetime.now(timezone.utc)
    print(f"🚀 Starting Multi-Engine Scan at {now.isoformat()}")

    # ══════════════ TIER 1: REAL EDGE ══════════════
    real_edge_ops = scan_real_edge()

    # ── Discord Alerts ──
    try:
        notifier = DiscordNotifier()
        if notifier.is_enabled():
            notifier.send_alert(real_edge_ops, min_edge=30.0)
    except Exception as e:
        print(f"  ⚠️ Discord alert failed: {e}")

    # ══════════════ TIER 2: PAPER TRADING ══════════════
    print("\n🧪 Running Quant Engine (Paper Trading)...")
    snapshot_records, paper_ops = scan_quant_ml()
    print(f"  Found {len(paper_ops)} quant signals (EDUCATIONAL ONLY)")

    # ── Sync to Supabase Unified Table ──
    print("\nPushing to Supabase kalshi_edges...")
    try:
        from collections import Counter
        all_opps = real_edge_ops + paper_ops
        count_dict = dict(Counter(op.get('edge_type', 'UNKNOWN') for op in all_opps))
        print(f"  Types: {count_dict}")
        
        # Bulk Gemini Logic for Top 3 Edges
        sorted_all = sorted(all_opps, key=lambda x: abs(float(x.get('edge', x.get('Edge', 0)))), reverse=True)
        top_3 = sorted_all[:3]
        
        # Initialize ui_reasoning for all
        for op in all_opps:
            op['ui_reasoning'] = False
            op['ai_summary'] = None

        if top_3:
            print(f"  🧠 Summarizing top 3 edges via Gemini...")
            try:
                validator = AIValidator()
                war_room = validator.validate_top_edges(top_3)
                
                # Assign verdicts to top 3
                for i, op in enumerate(top_3):
                    op['ui_reasoning'] = True
                    verdicts = war_room.get('individual_verdicts', [])
                    if i < len(verdicts):
                        op['ai_summary'] = verdicts[i]
                
                print(f"  ✅ War Room Summary: {war_room.get('summary', '')[:80]}...")
            except Exception as e:
                print(f"  ⚠️ AI Summarization failed: {e}")

        upsert_opportunities(all_opps)
        print(f"  ✅ Successfully synced to Supabase kalshi_edges")
    except Exception as e:
        print(f"  ❌ Failed to sync to Supabase: {e}")

    # ── Run Market Alerts ──
    print("\n📱 Running Market Alerts...")
    try:
        from scripts.market_alerts import run_all_alerts
        alerts = run_all_alerts()
        if alerts:
            print(f"  📱 {len(alerts)} alert(s) sent to Telegram")
        else:
            print("  ✅ No alerts triggered")
    except Exception as e:
        print(f"  ⚠️ Market alerts failed: {e}")

    print(f"\n🏁 Scan complete at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    import time
    while True:
        try:
            update_live_portfolio()
            run_scan()
        except KeyboardInterrupt:
            print("\n👋 Scanner stopped by user")
            break
        except Exception as e:
            print(f"\n❌ Critical Error in scanner loop: {e}")
            
        print("\n⏳ Sleeping 15 minutes...")
        time.sleep(15 * 60)
