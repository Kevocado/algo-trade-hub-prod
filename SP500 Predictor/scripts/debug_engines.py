import os
import sys
import time
import pprint
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Add root project path so we can import modules properly
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

# Import shared configs and engines
from shared import config
from scripts.engines.weather_engine import WeatherEngine
from scripts.engines.macro_engine import MacroEngine
from scripts.engines.tsa_engine import TSAEngine
from scripts.engines.eia_engine import EIAEngine
from scripts.engines.football_engine import FootballKalshiEngine
from scripts.engines.quant_engine import load_model, predict_next_hour, get_market_volatility
from src.data_loader import fetch_data
from src.feature_engineering import create_features

console = Console()

def create_debug_table(title: str) -> Table:
    """Helper to create a unified Rich Table."""
    table = Table(title=title, show_header=True, header_style="bold magenta")
    table.add_column("Market / Asset", style="cyan", min_width=25)
    table.add_column("Model Prob", justify="right", style="blue")
    table.add_column("Kalshi ASK", justify="right", style="yellow")
    table.add_column("Edge %", justify="right")
    table.add_column("Details/Action", style="dim")
    return table

def add_edge_row(table: Table, market: str, model_prob: float, kalshi_ask: float, action_or_details: str):
    """Safely calculates edge and color codes it."""
    # Convert probabilities to standard percentages if they are decimals
    mp = model_prob * 100 if model_prob <= 1.0 else model_prob
    kp = kalshi_ask * 100 if kalshi_ask <= 1.0 else kalshi_ask
    
    edge = mp - kp
    
    # Format edge with color
    edge_str = f"{edge:+.1f}%"
    if edge > 0:
        edge_text = Text(edge_str, style="bold green")
    else:
        edge_text = Text(edge_str, style="bold red")
        
    table.add_row(
        str(market)[:45],
        f"{mp:.1f}%",
        f"{kp:.1f}%",
        edge_text,
        str(action_or_details)[:45]
    )

def test_weather():
    console.print(Panel("[bold bright_blue]Testing Weather Engine[/bold bright_blue]"))
    try:
        engine = WeatherEngine()
        opportunities = engine.find_opportunities()
        table = create_debug_table("🌤️ Weather Edges (Top 3)")
        
        # Sort by absolute edge percentage and pick top 3
        ops = sorted(opportunities, key=lambda x: abs(x.get('edge_pct', 0)), reverse=True)[:3]
        
        if not ops:
            console.print("[yellow]No active weather markets found or API rate limited.[/yellow]")
            return

        for op in ops:
            add_edge_row(table, op.get('title', op.get('market_ticker')),
                         op.get('our_prob', 0),
                         op.get('market_prob', 0),
                         op.get('action', 'N/A'))
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]❌ WeatherEngine Error: {e}[/bold red]")

def test_macro():
    console.print(Panel("[bold bright_blue]Testing Macro & Govt Engines (FRED/TSA/EIA)[/bold bright_blue]"))
    try:
        macro_engine = MacroEngine()
        macro_ops = macro_engine.find_opportunities()
        
        tsa_engine = TSAEngine()
        tsa_ops = tsa_engine.find_opportunities()
        
        eia_engine = EIAEngine()
        eia_ops = eia_engine.find_opportunities()
        
        all_ops = macro_ops + tsa_ops + eia_ops
        ops = sorted(all_ops, key=lambda x: abs(x.get('edge_pct', 0)), reverse=True)[:5]
        
        table = create_debug_table("🏛️ Macro & Government Edges (Top 5)")
        if not ops:
            console.print("[yellow]No active macro markets found.[/yellow]")
            return
            
        for op in ops:
            add_edge_row(table, op.get('title', op.get('market_ticker')),
                         op.get('our_prob', 0),
                         op.get('market_prob', 0),
                         op.get('action', 'N/A'))
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]❌ MacroEngine Error: {e}[/bold red]")

def test_sports():
    console.print(Panel("[bold bright_blue]Testing Sports Calendar Fetchers (NBA, F1, NCAA)[/bold bright_blue]"))
    try:
        from scripts.engines.nba_engine import NBAEngine
        from scripts.engines.f1_engine import F1Engine
        from scripts.engines.ncaa_engine import NCAAEngine
        
        table = create_debug_table("🏀🏎️ Sports Calendars")

        nba_ops = NBAEngine().fetch_upcoming_games()
        for op in nba_ops[:3]:
            add_edge_row(table, op.get('title', ''), 0, 0, op.get('market_id', ''))
            
        f1_ops = F1Engine().fetch_upcoming_races()
        if f1_ops:
            add_edge_row(table, f1_ops[0].get('title', ''), 0, 0, f1_ops[0].get('market_id', ''))
            
        ncaa_ops = NCAAEngine().fetch_upcoming_march_madness()
        for op in ncaa_ops[:3]:
            add_edge_row(table, op.get('title', ''), 0.5, 0, "March Madness")
            
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]❌ Sports Engine Error: {e}[/bold red]")

def test_crypto_quant():
    console.print(Panel("[bold bright_blue]Testing Quant Engine (BTC & ETH)[/bold bright_blue]"))
    try:
        tickers = ["BTC-USD"]
        table = create_debug_table("📈 Crypto Paper Trading ML")
        
        for ticker in tickers:
            df = fetch_data(ticker, period="5d", interval="1h")
            # Tuple unwrap protection
            df_cleaned = df[0] if isinstance(df, tuple) else df
            
            if df_cleaned.empty:
                continue
                
            model, needs_retrain = load_model(ticker)
            if not model:
                continue
                
            df_feat = create_features(df_cleaned)
            df_feat_cleaned = df_feat[0] if isinstance(df_feat, tuple) else df_feat
            
            pred_val = predict_next_hour(model, df_feat_cleaned, ticker)
            curr_price = float(df_cleaned['Close'].iloc[-1])
            vol = get_market_volatility(df_cleaned, window=24)
            
            implied_prob = pred_val * 100
            
            # Mock Kalshi Ask for educational crypto (usually 50/50 standard deviation)
            kalshi_mock_ask = 50.0
            
            add_edge_row(table, f"{ticker} (ML Directional)", implied_prob, kalshi_mock_ask, f"Price: ${curr_price:.2f} Pred: ${pred_val:.2f}")
            
        console.print(table)
    except Exception as e:
        console.print(f"[bold red]❌ QuantEngine Error: {e}[/bold red]")

if __name__ == "__main__":
    console.print("\n[bold white on black] 🚀 ALGO-TRADE-HUB TERMINAL DEBUGGER [/bold white on black]")
    console.print("Isolating backend math from React parsing to verify prediction accuracy.\n")
    
    test_weather()
    test_macro()
    test_crypto_quant()
    test_sports()
    
    console.print("\n[bold green]✅ Debug Scan Complete.[/bold green]\n")
