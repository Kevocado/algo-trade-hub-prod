"""
Backtester — Replay historical predictions and simulate P&L.
Uses Azure Blob prediction logs from azure_logger.py.

Fixed payout math:
  - WIN:  Bought at market_price¢, payout = 100¢. Profit = (100 - price) / price × bet
  - LOSS: Lose the bet amount. Profit = -bet

Edge threshold: Only trade when edge > 10%.
"""

import pandas as pd
import numpy as np
from datetime import datetime


def fetch_historical_data():
    """
    Pulls historical prediction logs from Azure Blob Storage.
    Returns a DataFrame or empty DataFrame if unavailable.
    """
    try:
        from src.azure_logger import fetch_all_logs
        df = fetch_all_logs()
        return df if df is not None else pd.DataFrame()
    except Exception as e:
        print(f"    ❌ Could not fetch Azure logs: {e}")
        return pd.DataFrame()


def simulate_backtest(logs_df, bankroll=100, kelly_fraction=0.25, min_edge=10):
    """
    Replays historical predictions and simulates Kelly-sized P&L
    using actual Kalshi binary option payout math.

    Kalshi payout:
      - You buy a contract at `market_price` cents (e.g. 35¢)
      - If you WIN: payout = 100¢. Profit = 100 - 35 = 65¢ per contract
      - If you LOSE: you lose your 35¢ per contract

    So for a $2 bet on a 35¢ contract:
      - Contracts = $2.00 / $0.35 = 5.7 contracts
      - WIN profit  = 5.7 × $0.65 = $3.71
      - LOSS        = -$2.00

    Args:
        logs_df: DataFrame from azure_logger.fetch_all_logs()
        bankroll: Starting bankroll ($)
        kelly_fraction: Kelly fraction (0.25 = quarter Kelly)
        min_edge: Minimum edge % required to place a bet (default 10%)

    Returns:
        dict with trades, metrics, equity_curve, and accuracy stats
    """
    if logs_df.empty:
        return _empty_result()

    required = ['timestamp_utc', 'current_price', 'predicted_price', 'best_edge_val', 'best_action']
    available = set(logs_df.columns)
    if not all(c in available for c in required):
        return _empty_result()

    trades = []
    equity = bankroll
    equity_curve = []
    direction_correct = 0
    direction_total = 0

    df = logs_df.sort_values('timestamp_utc').reset_index(drop=True)

    for i in range(len(df) - 1):
        row = df.iloc[i]
        next_row = df.iloc[i + 1]

        edge = row.get('best_edge_val', 0)
        predicted = row['predicted_price']
        actual_next = next_row['current_price']
        current = row['current_price']

        # Track direction accuracy (all predictions, not just bets)
        predicted_up = predicted > current
        actual_up = actual_next > current
        direction_total += 1
        if predicted_up == actual_up:
            direction_correct += 1

        # ── FILTER: only bet when edge is meaningful ──
        if edge < min_edge:
            equity_curve.append((row['timestamp_utc'], equity))
            continue

        # ── DID WE WIN? ──
        won = predicted_up == actual_up

        # ── KALSHI PAYOUT MATH ──
        # Simulate market price from edge: if our prob = 70% and edge = 20%, 
        # then market_price = 70% - 20% = 50¢
        # We approximate market_price from best_action
        market_price_cents = max(5, min(95, 50))  # Approximate mid-market
        # Better: use the logged data if available
        if 'market_price' in row.index and not pd.isna(row.get('market_price', None)):
            market_price_cents = row['market_price']
        elif 'kalshi_price' in row.index and not pd.isna(row.get('kalshi_price', None)):
            market_price_cents = row['kalshi_price']

        market_price = market_price_cents / 100  # Convert to dollars

        # Kelly bet size
        p = min(0.95, max(0.05, edge / 100 + market_price))  # Our probability
        q = 1 - p
        b = (1 - market_price) / market_price if market_price > 0 else 0  # Odds

        if b > 0:
            f = p - (q / b)
            safe_f = max(0, f * kelly_fraction)
        else:
            safe_f = 0

        bet_size = min(equity * safe_f, 20, equity)  # Cap at $20 and available bankroll

        if bet_size < 0.01:
            equity_curve.append((row['timestamp_utc'], equity))
            continue

        # ── PROFIT CALCULATION (actual Kalshi math) ──
        if won:
            # Payout = (1 - market_price) / market_price × bet_size
            # e.g. buy at 35¢ → win 65¢ per 35¢ → 1.857x profit
            pnl = bet_size * ((1 - market_price) / market_price)
        else:
            pnl = -bet_size

        equity += pnl
        equity = max(0, equity)

        trades.append({
            'timestamp': row['timestamp_utc'],
            'ticker': row.get('ticker', 'Unknown'),
            'predicted': predicted,
            'actual': actual_next,
            'current': current,
            'edge': edge,
            'market_price': market_price_cents,
            'bet_size': round(bet_size, 2),
            'pnl': round(pnl, 2),
            'won': won,
            'equity_after': round(equity, 2)
        })

        equity_curve.append((row['timestamp_utc'], round(equity, 2)))

    metrics = calculate_metrics(trades, bankroll, equity)

    # Model accuracy
    accuracy = {
        'direction_correct': direction_correct,
        'direction_total': direction_total,
        'direction_accuracy': round(direction_correct / direction_total * 100, 1) if direction_total > 0 else 0,
        'trades_filtered': direction_total - len(trades),
        'min_edge_used': min_edge
    }

    return {
        'trades': trades,
        'metrics': metrics,
        'equity_curve': equity_curve,
        'accuracy': accuracy
    }


def calculate_metrics(trades, start_bankroll, end_equity):
    """Calculates backtest performance metrics."""
    if not trades:
        return _empty_metrics()

    wins = [t for t in trades if t['won']]
    losses = [t for t in trades if not t['won']]
    pnls = [t['pnl'] for t in trades]

    win_rate = len(wins) / len(trades) * 100
    total_return = (end_equity - start_bankroll) / start_bankroll * 100

    if len(pnls) > 1 and np.std(pnls) > 0:
        sharpe = (np.mean(pnls) / np.std(pnls)) * np.sqrt(252)
    else:
        sharpe = 0

    # Max Drawdown
    peak = start_bankroll
    max_dd = 0
    for t in trades:
        peak = max(peak, t['equity_after'])
        dd = (peak - t['equity_after']) / peak * 100
        max_dd = max(max_dd, dd)

    # Profit Factor
    gross_profit = sum(t['pnl'] for t in wins) if wins else 0
    gross_loss = abs(sum(t['pnl'] for t in losses)) if losses else 0.01
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0

    avg_win = np.mean([t['pnl'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl'] for t in losses]) if losses else 0

    return {
        'total_trades': len(trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': round(win_rate, 1),
        'total_return': round(total_return, 1),
        'total_pnl': round(sum(pnls), 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_dd, 1),
        'profit_factor': round(profit_factor, 2),
        'avg_win': round(avg_win, 2),
        'avg_loss': round(avg_loss, 2),
        'start_bankroll': start_bankroll,
        'end_equity': round(end_equity, 2)
    }


def _empty_metrics():
    return {k: 0 for k in [
        'total_trades', 'wins', 'losses', 'win_rate', 'total_return',
        'total_pnl', 'sharpe', 'max_drawdown', 'profit_factor',
        'avg_win', 'avg_loss', 'start_bankroll', 'end_equity'
    ]}


def _empty_result():
    return {
        'trades': [],
        'metrics': _empty_metrics(),
        'equity_curve': [],
        'accuracy': {
            'direction_correct': 0, 'direction_total': 0,
            'direction_accuracy': 0, 'trades_filtered': 0, 'min_edge_used': 0
        }
    }
