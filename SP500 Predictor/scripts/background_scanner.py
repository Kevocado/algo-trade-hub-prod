"""
Background Scanner — Multi-Engine Compute-on-Write
Runs from GitHub Actions (or locally). Executes Weather + Macro engines first (real edge),
then Quant engine (paper trading). All real-edge ops go through AI Validator.

ARCHITECTURE:
  Tier 1 (Real Edge): Weather Engine + Macro Engine → AI Validator → LiveOpportunities table
  Tier 2 (Paper):     Quant Engine → PaperTradingSignals table (no AI validation)
"""

import os
import sys
import re
import json
from datetime import datetime, timezone
from dotenv import load_dotenv

# Add project root to path so we can import src modules
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from azure.data.tables import TableClient
from azure.storage.blob import BlobServiceClient

from scripts.engines.weather_engine import WeatherEngine
from scripts.engines.macro_engine import MacroEngine
from scripts.engines.tsa_engine import TSAEngine
from scripts.engines.eia_engine import EIAEngine
from scripts.engines.nba_engine import NBAEngine
from scripts.engines.f1_engine import F1Engine
from scripts.engines.ncaa_engine import NCAAEngine
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
import pandas as pd

# ─── Environment ─────────────────────────────────────────────────────
load_dotenv()
CONN_STR = os.getenv("AZURE_CONNECTION_STRING", "").strip('"').strip("'")

if not CONN_STR:
    print("❌ AZURE_CONNECTION_STRING not set. Exiting.")
    sys.exit(1)

EDGE_THRESHOLD = 5.0


# ═════════════════════════════════════════════════════════════════════
# TIER 1: REAL EDGE — Weather + Macro
# ═════════════════════════════════════════════════════════════════════

def scan_real_edge():
    """
    Run Weather and Macro engines.
    Returns raw math-based opportunities (NO AI validation — that's on-demand in UI).
    """
    all_ops = []

    # ── Weather Engine (fetches KXHIGHNY, KXHIGHCHI, KXHIGHMIA) ──
    print("\n⛈️ Running Weather Engine...")
    try:
        weather_engine = WeatherEngine()
        weather_ops = weather_engine.find_opportunities()
        for op in weather_ops: op["edge_type"] = "WEATHER"
        print(f"  Found {len(weather_ops)} weather opportunities")
        all_ops.extend(weather_ops)
    except Exception as e:
        print(f"  ⚠️ Weather Engine failed: {e}")

    # ── Macro Engine (fetches KXLCPIMAXYOY, KXFED, KXGDPYEAR, etc) ──
    print("\n🏛️ Running Macro Engine...")
    try:
        macro_engine = MacroEngine()
        macro_ops = macro_engine.find_opportunities()
        for op in macro_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(macro_ops)} macro opportunities")
        all_ops.extend(macro_ops)
    except Exception as e:
        print(f"  ⚠️ Macro Engine failed: {e}")

    # ── TSA Travel Engine (TSA Passenger Volumes) ──
    print("\n✈️ Running TSA Engine...")
    try:
        tsa_engine = TSAEngine()
        tsa_ops = tsa_engine.find_opportunities()
        for op in tsa_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(tsa_ops)} TSA opportunities")
        all_ops.extend(tsa_ops)
    except Exception as e:
        print(f"  ⚠️ TSA Engine failed: {e}")

    # ── EIA Energy Engine (Natural Gas / Crude Storage) ──
    print("\n⛽ Running EIA Engine...")
    try:
        eia_engine = EIAEngine()
        eia_ops = eia_engine.find_opportunities()
        for op in eia_ops: op["edge_type"] = "MACRO"
        print(f"  Found {len(eia_ops)} EIA opportunities")
        all_ops.extend(eia_ops)
    except Exception as e:
        print(f"  ⚠️ EIA Engine failed: {e}")

    # ── Sports Schedule Fetchers (Pre-Kalshi Calendar Data) ──
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
        
    print("\n🏀 Running NCAA March Madness Fetcher (Keyless API)...")
    try:
        ncaa_ops = NCAAEngine().fetch_upcoming_march_madness()
        all_ops.extend(ncaa_ops)
        print(f"  Found {len(ncaa_ops)} NCAA tournament games")
    except Exception as e:
        print(f"  ⚠️ NCAA fetcher failed: {e}")

    print(f"\n📊 Total real-edge opportunities: {len(all_ops)} (AI validation available on-demand in UI)")
    return all_ops


# ═════════════════════════════════════════════════════════════════════
# TIER 2: PAPER TRADING — Quant ML
# ═════════════════════════════════════════════════════════════════════

def scan_quant_ml():
    """
    Quant ML scanner for SPX/Nasdaq/BTC/ETH.
    Returns (snapshot_records, paper_opportunities).
    ⚠️ PAPER TRADING ONLY - no AI validation needed.
    """
    tickers = ["BTC-USD"]
    snapshot_records = []
    paper_opportunities = []

    data_cache = {}
    for ticker in tickers:
        try:
            df = fetch_data(ticker, period="5d", interval="1h")
            df = df[0] if isinstance(df, tuple) else df
            model, needs_retrain = load_model(ticker)

            if model and not df.empty:
                df_feat = create_features(df)
                df_feat_df = df_feat[0] if isinstance(df_feat, tuple) else df_feat
                pred_val = predict_next_hour(model, df_feat_df, ticker)
                curr_price = df['Close'].iloc[-1]
                vol = get_market_volatility(df, window=24)

                data_cache[ticker] = {
                    "df": df, "model": model, "vol": vol,
                    "price": curr_price, "pred": pred_val,
                }
                print(f"    ✅ {ticker}: Price={curr_price:.2f}, Pred={pred_val:.2f}, Vol={vol:.6f}")
        except Exception as e:
            import traceback
            traceback.print_exc()
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
                edge_type = "CRYPTO" if ticker in ["BTC", "ETH"] else "MACRO"
                paper_opportunities.append({
                    "PartitionKey": "Paper",
                    "RowKey": f"{ticker}_{m.get('market_id', strike)}".replace(" ", ""),
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

def calculate_annualized_ev(edge_pct, expiration_str):
    """Calculates Annualized Expected Value."""
    try:
        now_dt = datetime.now(timezone.utc)
        if not expiration_str: return 0
        try:
            exp = pd.to_datetime(expiration_str)
            if exp.tzinfo is None: exp = exp.tz_localize('UTC')
        except Exception: return 0
        days_to_res = (exp - now_dt).days
        if days_to_res <= 0: days_to_res = 1
        return (edge_pct * 365) / days_to_res
    except Exception: return 0

def run_scan():
    """Main scanning logic — prioritizes real edge markets."""
    now = datetime.now(timezone.utc)
    print(f"🚀 Starting Multi-Engine Scan at {now.isoformat()}")

    # ── Initialize Azure clients ──
    try:
        blob_service = BlobServiceClient.from_connection_string(CONN_STR, connection_timeout=10, read_timeout=10)
        live_table = TableClient.from_connection_string(CONN_STR, "LiveOpportunities")
        paper_table = TableClient.from_connection_string(CONN_STR, "PaperTradingSignals")

        for table in [live_table, paper_table]:
            try:
                table.create_table()
            except Exception:
                pass
        try:
            blob_service.create_container("market-snapshots")
        except Exception:
            pass
    except Exception as e:
        print(f"❌ Azure Initialization Failed: {e}")
        return

    # ══════════════ TIER 1: REAL EDGE ══════════════
    # Engines fetch their own Kalshi markets via series_ticker (fastest method)
    real_edge_ops = scan_real_edge()

    # ── Discord Alerts (for high-conviction trades) ──
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

    # ── News Analysis & Arbitrage Discovery (PhD Milestone) ──
    news_analyzer = NewsAnalyzer()
    
    # ── Save snapshot to Blob ──
    try:
        full_snapshot = {
            "timestamp_utc": now.isoformat(),
            "markets_analyzed": len(snapshot_records),
            "live_opportunities": len(real_edge_ops),
            "paper_signals": len(paper_ops),
            "records": snapshot_records,
        }
        blob_name = f"snapshot_{now.strftime('%Y%m%d_%H%M%S')}.json"
        blob_client = blob_service.get_blob_client(container="market-snapshots", blob=blob_name)
        blob_client.upload_blob(json.dumps(full_snapshot, default=str), overwrite=True)
        print(f"\n✅ Saved snapshot: {blob_name} ({len(snapshot_records)} markets)")
    except Exception as e:
        print(f"  ⚠️ Failed to save snapshot: {e}")

    # ── Update LiveOpportunities table ──
    try:
        # Clear old entities (PartitionKey eq 'Live')
        entities = list(live_table.query_entities("PartitionKey eq 'Live'"))
        for e in entities:
            live_table.delete_entity(e['PartitionKey'], e['RowKey'])
    except Exception:
        pass

    # Limit to top 20 opportunities by edge to prevent Gemini API timeouts
    real_edge_ops.sort(key=lambda x: x.get('edge', 0), reverse=True)
    top_ops = real_edge_ops[:20]

    for opp in top_ops:
        try:
            # PhD Intelligence: Bayesian News Scrutiny (Lightweight)
            news_res = news_analyzer.analyze_event_impact(
                opp.get('market_ticker', ''), 
                opp.get('market_title', ''), 
                opp.get('model_probability', 50),
                [opp.get('reasoning', '')] # Pass reasoning as context if no live headlines
            )
            
            row_key = opp.get('market_ticker', f"{opp.get('engine', 'UNK')}_{opp.get('asset', 'UNK')}_{now.strftime('%H%M%S')}")
            row_key = row_key.replace('/', '_').replace('\\', '_').replace('#', '_').replace('?', '_')
            
            entity = {
                "PartitionKey": "Live",
                "RowKey": row_key,
                "Engine": opp.get('engine', ''),
                "Asset": opp.get('asset', ''),
                "Market": str(opp.get('market_title', ''))[:200],
                "Action": opp.get('action', ''),
                "Edge": float(opp.get('edge', 0)),
                "Confidence": float(opp.get('confidence', 0)),
                "Reasoning": str(opp.get('reasoning', ''))[:500],
                "NewsSentiment": news_res.get('sentiment', 'Neutral'),
                "NewsReasoning": news_res.get('reasoning', ''),
                "DataSource": opp.get('data_source', ''),
                "AIValidated": False,  # On-demand in UI
                "KalshiUrl": opp.get('kalshi_url', ''),
                "MarketTicker": opp.get('market_ticker', ''),
                "MarketDate": opp.get('market_date', ''),
                "Expiration": opp.get('expiration', ''),
                "MarketPrice": float(opp.get('market_price', 0)),
                "ModelProb": float(opp.get('model_probability', 0)),
                "Spread": float(opp.get('spread', 5)),
                "AnnualizedEV": calculate_annualized_ev(float(opp.get('edge', 0)), opp.get('expiration', ''))
            }
            if entity["Spread"] <= 20: 
                live_table.create_entity(entity)
        except Exception as e:
            print(f"  ⚠️ Failed to save live op: {e}")

    print(f"✅ Saved {len(real_edge_ops)} math-based opportunities to LiveOpportunities")

    # ── Update PaperTradingSignals table ──
    try:
        entities = list(paper_table.query_entities("PartitionKey eq 'Paper'"))
        for e in entities:
            paper_table.delete_entity(e['PartitionKey'], e['RowKey'])
    except Exception:
        pass

    for op in paper_ops:
        try:
            paper_table.create_entity(op)
        except Exception as e:
            print(f"  ⚠️ Failed to save paper op: {e}")

    print(f"✅ Saved {len(paper_ops)} quant signals to PaperTradingSignals")

    # ── Run Market Alerts (Weather Auto-Sell, GEX Flip, VIX Emergency) ──
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

    # ── Also write to Supabase (dual-write during migration) ──
    try:
        from src.supabase_client import upsert_opportunities
        all_opps = real_edge_ops + (paper_ops if 'paper_ops' in locals() else [])
        
        from collections import Counter
        count_dict = dict(Counter(op.get('edge_type', 'UNKNOWN') for op in all_opps))
        print(f"Pushing to Supabase kalshi_edges: {count_dict}")
        
        upsert_opportunities(all_opps)
        print(f"  ✅ Also saved to Supabase kalshi_edges")
    except Exception as e:
        print(f"  ⚠️ Supabase write skipped: {e}")

    print(f"\n🏁 Scan complete at {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    run_scan()
