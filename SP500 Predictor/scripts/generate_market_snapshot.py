import os
import sys
import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timezone
import traceback

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from dotenv import load_dotenv
load_dotenv(override=True)

from src.data_loader import fetch_data
from src.feature_engineering import create_features, prepare_training_data
from src.model import load_model, predict_next_hour, train_model, calculate_probability, get_recent_rmse, FeatureMismatchError
from src.utils import categorize_markets, determine_best_timeframe
from src.kalshi_feed import get_real_kalshi_markets
from src.model_daily import load_daily_model, predict_daily_close, prepare_daily_data

def generate_snapshot():
    print(f"🚀 Starting Market Snapshot Generation at {datetime.now(timezone.utc)}")
    
    tickers_to_scan = ["SPX", "Nasdaq", "BTC", "ETH"]
    snapshot_data = {
        "metadata": {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "tickers_scanned": tickers_to_scan
        },
        "opportunities": [],
        "ranges": []
    }
    
    for ticker in tickers_to_scan:
        print(f"\nScanning {ticker}...")
        try:
            # 1. Fetch Kalshi Markets
            real_markets, _, _ = get_real_kalshi_markets(ticker)
            buckets = categorize_markets(real_markets, ticker)
            
            # 2. Hourly Model Logic
            df_hourly = fetch_data(ticker=ticker, period="5d", interval="1m")
            model_hourly, needs_retrain = load_model(ticker=ticker)
            
            if needs_retrain or model_hourly is None:
                print(f"   ⚠️ Retraining hourly model for {ticker}...")
                try:
                    df_train = fetch_data(ticker=ticker, period="7d", interval="1m")
                    df_train = prepare_training_data(df_train)
                    model_hourly = train_model(df_train, ticker=ticker)
                except Exception as e:
                    print(f"   ❌ Retrain failed: {e}")
                    model_hourly = None

            # 3. Daily Model Logic
            df_daily = fetch_data(ticker=ticker, period="60d", interval="1h")
            model_daily = load_daily_model(ticker=ticker)
            
            # 4. Process Hourly Markets
            if not df_hourly.empty and model_hourly and buckets['hourly']:
                try:
                    df_features = create_features(df_hourly)
                    pred = predict_next_hour(model_hourly, df_features, ticker=ticker)
                    rmse = get_recent_rmse(model_hourly, df_hourly, ticker=ticker)
                    curr_price = df_hourly['Close'].iloc[-1]
                    
                    for m in buckets['hourly']:
                        strike = m.get('strike_price')
                        if not strike: continue
                        
                        prob_above = calculate_probability(pred, strike, rmse)
                        market_type = m.get('market_type', 'above')
                        
                        if market_type == 'below':
                            prob_win = 100 - prob_above
                            label = f"< ${strike}"
                            action = "BUY NO" if prob_above > 50 else "BUY YES" # Wait, logic check
                            # If Market is "Below X", buying YES means betting it stays below.
                            # Prob(Price < Strike) = 100 - Prob(Price > Strike)
                            # If Prob(Price > Strike) is 80%, Prob(Below) is 20%.
                            # So prob_win for "Yes" to "Below" is 20%.
                            # If we buy NO to "Below", we are betting it goes ABOVE.
                            
                            # Let's align with app logic:
                            # if market_type == 'below':
                            #    strike_label = f"< ${strike}"
                            #    prob_win = 100 - prob_above
                            # else: ...
                            # if prob_win > 50: Action = BUY YES
                             
                            pass 

                        # Simpler Logic Re-use from App:
                        if market_type == 'below':
                            strike_label = f"< ${strike}"
                            prob_win = 100 - prob_above
                        else:
                            strike_label = f"> ${strike}"
                            prob_win = prob_above
                        
                        if prob_win > 50:
                            action = "BUY YES"
                            conf = prob_win
                        else:
                            action = "BUY NO"
                            conf = 100 - prob_win
                            
                        # Edge Calc
                        # Cost is Ask Price
                        cost = m.get('yes_ask', 0) if "BUY YES" in action else m.get('no_ask', 0)
                        if cost <= 0: cost = 99
                        edge = conf - cost
                        
                        item = {
                            "ticker": ticker,
                            "strike_price": strike,
                            "strike_label": strike_label,
                            "expiration": m['expiration'],
                            "prob_win": round(conf, 1),
                            "action": action,
                            "cost": cost,
                            "edge": round(edge, 1),
                            "timeframe": "Hourly",
                            "market_id": m.get('market_id'),
                             "market_type": market_type
                        }
                        snapshot_data['opportunities'].append(item)

                except Exception as e:
                    print(f"   ❌ Error processing hourly markets: {e}")

            # 5. Process Daily Markets
            if not df_daily.empty and model_daily and buckets['daily']:
                try:
                    df_features_daily, _ = prepare_daily_data(df_daily)
                    pred_daily = predict_daily_close(model_daily, df_features_daily.iloc[[-1]])
                    rmse_daily = df_daily['Close'].iloc[-1] * 0.01
                    
                    for m in buckets['daily']:
                        strike = m.get('strike_price')
                        if not strike: continue
                        
                        prob_above = calculate_probability(pred_daily, strike, rmse_daily)
                        market_type = m.get('market_type', 'above')
                        
                        if market_type == 'below':
                            strike_label = f"< ${strike}"
                            prob_win = 100 - prob_above
                        else:
                            strike_label = f"> ${strike}"
                            prob_win = prob_above
                        
                        if prob_win > 50:
                            action = "BUY YES"
                            conf = prob_win
                        else:
                            action = "BUY NO"
                            conf = 100 - prob_win
                            
                        cost = m.get('yes_ask', 0) if "BUY YES" in action else m.get('no_ask', 0)
                        if cost <= 0: cost = 99
                        edge = conf - cost
                        
                        item = {
                            "ticker": ticker,
                            "strike_price": strike,
                            "strike_label": strike_label,
                            "expiration": m['expiration'],
                            "prob_win": round(conf, 1),
                            "action": action,
                            "cost": cost,
                            "edge": round(edge, 1),
                            "timeframe": "Daily",
                            "market_id": m.get('market_id'),
                            "market_type": market_type
                        }
                        snapshot_data['opportunities'].append(item)
                except Exception as e:
                    print(f"   ❌ Error processing daily markets: {e}")

            # 6. Process Ranges (Simplified)
            # ... (Skipping ranges for MVP or adding if essential. User asked for "remove hardcoded sample data", implying replacement of main table)
            # Let's add basic range logic if easy, otherwise skip. The logic is in app. I'll skip ranges for now to keep script clean unless they are critical.
            # actually app has ranges tab. I'll skip for now to ensure this works first.
            
        except Exception as e:
            print(f"❌ Critical error for {ticker}: {e}")
            traceback.print_exc()

    # Save to JSON
    output_path = "market_data.json"
    with open(output_path, "w") as f:
        json.dump(snapshot_data, f, indent=2)
    
    print(f"\n✅ Snapshot saved to {output_path}")
    print(f"   Total Opportunities: {len(snapshot_data['opportunities'])}")

if __name__ == "__main__":
    generate_snapshot()
