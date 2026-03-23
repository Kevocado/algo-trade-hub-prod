"""
quant_engine.py — Institutional Order Flow & Volume Profile Analytics
=====================================================================
High-performance vectorized quant module using numpy, pandas, and scipy.
Provides two core analytical pillars:

  Pillar 1: Volume Profile Skew (Statistical Distribution)
    – POC, VAH/VAL, VWMP, Skewness → Regime classification

  Pillar 2: Flow Divergence (Dominance vs. Pressure)
    – Tick-rule buy/sell classification, Delta, Divergence detection

Designed for the 10-second heartbeat loop — all operations are vectorized.
"""

import logging
import numpy as np
import pandas as pd
from scipy import stats

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Pillar 1: Volume Profile Skew
# ═══════════════════════════════════════════════════════════════════

def compute_volume_profile(df: pd.DataFrame, n_bins: int = 20) -> dict:
    """
    Treat the volume profile as a statistical distribution.

    Args:
        df: DataFrame with columns ['price', 'size'] (one row per tick).
        n_bins: Number of price bins to divide the range into.

    Returns:
        dict with: poc, vah, val, vwmp, skewness, regime, bin_edges, bin_volumes
    """
    if df.empty or len(df) < 2:
        return _empty_profile()

    prices = df["price"].values.astype(np.float64)
    volumes = df["size"].values.astype(np.float64)

    # ── Price bins ──
    price_min, price_max = prices.min(), prices.max()
    if price_max - price_min < 1e-9:
        # All ticks at the same price — degenerate case
        return {
            "poc": float(price_min),
            "vah": float(price_min),
            "val": float(price_min),
            "vwmp": float(price_min),
            "skewness": 0.0,
            "regime": "NEUTRAL",
            "total_volume": int(volumes.sum()),
        }

    bin_edges = np.linspace(price_min, price_max, n_bins + 1)
    bin_indices = np.digitize(prices, bin_edges) - 1
    bin_indices = np.clip(bin_indices, 0, n_bins - 1)

    # ── Accumulate volume per bin ──
    bin_volumes = np.zeros(n_bins, dtype=np.float64)
    np.add.at(bin_volumes, bin_indices, volumes)

    # ── Point of Control (POC): price bin with highest volume ──
    poc_idx = int(np.argmax(bin_volumes))
    poc = float((bin_edges[poc_idx] + bin_edges[poc_idx + 1]) / 2)

    # ── Value Area (70% of total volume, expanding from POC) ──
    total_vol = bin_volumes.sum()
    value_area_target = total_vol * 0.70

    va_low_idx, va_high_idx = poc_idx, poc_idx
    accumulated = bin_volumes[poc_idx]

    while accumulated < value_area_target:
        expand_down = bin_volumes[va_low_idx - 1] if va_low_idx > 0 else 0
        expand_up = bin_volumes[va_high_idx + 1] if va_high_idx < n_bins - 1 else 0

        if expand_down == 0 and expand_up == 0:
            break

        if expand_up >= expand_down:
            va_high_idx += 1
            accumulated += expand_up
        else:
            va_low_idx -= 1
            accumulated += expand_down

    vah = float(bin_edges[va_high_idx + 1])  # upper edge of high bin
    val = float(bin_edges[va_low_idx])        # lower edge of low bin

    # ── Volume-Weighted Mean Price (VWMP) ──
    vwmp = float(np.average(prices, weights=volumes))

    # ── Skewness of the volume distribution ──
    # Build a weighted sample: each price contributes proportionally to its volume
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    # Create a pseudo-distribution by repeating bin centers weighted by volume
    # Use scipy.stats.skew on the weighted distribution
    if total_vol > 0:
        weights_norm = bin_volumes / total_vol
        mean = np.sum(weights_norm * bin_centers)
        variance = np.sum(weights_norm * (bin_centers - mean) ** 2)
        std = np.sqrt(variance) if variance > 0 else 1e-9
        skewness = float(np.sum(weights_norm * ((bin_centers - mean) / std) ** 3))
    else:
        skewness = 0.0

    # ── Regime classification ──
    if skewness > 0.25:
        regime = "ACCUMULATION"   # Volume leaning toward lower prices
    elif skewness < -0.25:
        regime = "DISTRIBUTION"   # Volume leaning toward higher prices
    else:
        regime = "NEUTRAL"

    return {
        "poc": round(poc, 4),
        "vah": round(vah, 4),
        "val": round(val, 4),
        "vwmp": round(vwmp, 4),
        "skewness": round(skewness, 4),
        "regime": regime,
        "total_volume": int(total_vol),
    }


def _empty_profile() -> dict:
    return {
        "poc": 0.0, "vah": 0.0, "val": 0.0, "vwmp": 0.0,
        "skewness": 0.0, "regime": "NO_DATA", "total_volume": 0,
    }


# ═══════════════════════════════════════════════════════════════════
# Pillar 2: Flow Divergence (Dominance vs. Pressure)
# ═══════════════════════════════════════════════════════════════════

def compute_flow_divergence(df: pd.DataFrame) -> dict:
    """
    Measure aggressive order flow using the Tick Rule.

    Tick Rule: If price[i] > price[i-1] → classified as a buy tick (buyer
    lifted the offer). If price[i] < price[i-1] → sell tick (seller hit the bid).
    Equal prices inherit the previous classification.

    Returns:
        dict with: buy_volume, sell_volume, delta, delta_pct,
                   dominance, pressure, divergence_warning, divergence_reason
    """
    if df.empty or len(df) < 2:
        return _empty_divergence()

    prices = df["price"].values.astype(np.float64)
    volumes = df["size"].values.astype(np.float64)

    # ── Tick rule classification ──
    price_diff = np.diff(prices)
    # Propagate zero-diffs forward (inherit previous direction)
    tick_direction = np.zeros(len(price_diff), dtype=np.float64)
    last_dir = 0.0
    for i in range(len(price_diff)):
        if price_diff[i] > 0:
            last_dir = 1.0
        elif price_diff[i] < 0:
            last_dir = -1.0
        tick_direction[i] = last_dir

    # Volumes from index 1 onward (aligned with diffs)
    tick_volumes = volumes[1:]

    buy_mask = tick_direction > 0
    sell_mask = tick_direction < 0

    buy_volume = float(tick_volumes[buy_mask].sum())
    sell_volume = float(tick_volumes[sell_mask].sum())
    total_classified = buy_volume + sell_volume

    # ── Delta (net aggressive flow) ──
    delta = buy_volume - sell_volume
    delta_pct = (delta / total_classified * 100) if total_classified > 0 else 0.0

    # ── Dominance: Who finished stronger in the price range? ──
    # Compare close (last price) vs open (first price)
    open_price = prices[0]
    close_price = prices[-1]
    if close_price > open_price:
        dominance = "BULL"
    elif close_price < open_price:
        dominance = "BEAR"
    else:
        dominance = "NEUTRAL"

    # ── Pressure: Who was more aggressive by volume? ──
    if buy_volume > sell_volume * 1.5:
        pressure = "BUY"
    elif sell_volume > buy_volume * 1.5:
        pressure = "SELL"
    else:
        pressure = "NEUTRAL"

    # ── Divergence Detection ──
    divergence_warning = False
    divergence_reason = ""

    if total_classified > 1000:
        if dominance == "BULL" and pressure == "SELL":
            divergence_warning = True
            divergence_reason = (
                "BEARISH DIVERGENCE: Price finished higher (Bull dominance) "
                "but aggressive sell pressure is rising — sellers absorbing the move."
            )
        elif dominance == "BEAR" and pressure == "BUY":
            divergence_warning = True
            divergence_reason = (
                "BULLISH DIVERGENCE: Price finished lower (Bear dominance) "
                "but aggressive buy pressure is rising — buyers absorbing the dip."
            )

    return {
        "buy_volume": int(buy_volume),
        "sell_volume": int(sell_volume),
        "delta": int(delta),
        "delta_pct": round(delta_pct, 2),
        "dominance": dominance,
        "pressure": pressure,
        "divergence_warning": divergence_warning,
        "divergence_reason": divergence_reason,
    }


def _empty_divergence() -> dict:
    return {
        "buy_volume": 0, "sell_volume": 0, "delta": 0, "delta_pct": 0.0,
        "dominance": "NO_DATA", "pressure": "NO_DATA",
        "divergence_warning": False, "divergence_reason": "",
    }


# ═══════════════════════════════════════════════════════════════════
# Combined Analysis per Symbol
# ═══════════════════════════════════════════════════════════════════

def analyze_symbol(df: pd.DataFrame) -> dict:
    """
    Full institutional analysis for a single symbol's tick data.

    Args:
        df: DataFrame with at minimum ['price', 'size'] columns,
            sorted chronologically (oldest first).

    Returns:
        Combined dict of volume profile + flow divergence metrics.
    """
    profile = compute_volume_profile(df)
    flow = compute_flow_divergence(df)

    # ── Composite directional signal ──
    # Combines regime bias + delta direction into a single float [-1, 1]
    regime_score = {"ACCUMULATION": 0.7, "DISTRIBUTION": -0.7, "NEUTRAL": 0.0}.get(
        profile["regime"], 0.0
    )
    delta_score = np.clip(flow["delta_pct"] / 25.0, -1.0, 1.0)  # normalize with higher sensitivity
    composite = float(np.clip((regime_score + delta_score) / 1.5, -1.0, 1.0))

    return {
        "volume_profile": profile,
        "flow_divergence": flow,
        "composite_signal": round(composite, 4),
    }


# ═══════════════════════════════════════════════════════════════════
# Multi-Symbol Aggregator (for the orchestrator)
# ═══════════════════════════════════════════════════════════════════

def analyze_all_symbols(ticks: list[dict]) -> dict:
    """
    Analyze all symbols from a batch of raw tick dicts.

    Args:
        ticks: list of dicts with keys [symbol, price, size, timestamp, ...]

    Returns:
        dict keyed by symbol → analyze_symbol() output,
        plus an "aggregate" key with the portfolio-level summary.
    """
    if not ticks:
        return {"symbols": {}, "aggregate": {"signal": 0.0, "regime": "NO_DATA"}}

    df_all = pd.DataFrame(ticks)
    # Ensure chronological order
    if "id" in df_all.columns:
        df_all = df_all.sort_values("id")

    results: dict[str, dict] = {}
    signals: list[float] = []
    regimes: list[str] = []

    for symbol, group in df_all.groupby("symbol"):
        analysis = analyze_symbol(group.reset_index(drop=True))
        results[str(symbol)] = analysis
        signals.append(analysis["composite_signal"])
        regimes.append(analysis["volume_profile"]["regime"])

    # ── Portfolio-level aggregate ──
    avg_signal = float(np.mean(signals)) if signals else 0.0
    # Majority regime vote
    if regimes:
        regime_counts = pd.Series(regimes).value_counts()
        dominant_regime = str(regime_counts.index[0])
    else:
        dominant_regime = "NO_DATA"

    return {
        "symbols": results,
        "aggregate": {
            "signal": round(avg_signal, 4),
            "regime": dominant_regime,
            "n_symbols": len(results),
        },
    }
