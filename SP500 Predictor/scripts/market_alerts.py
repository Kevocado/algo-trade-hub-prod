"""
Market Alert System — Telegram triggers for regime changes

Alerts:
  1. GEX Flip: Net gamma exposure crosses zero → regime change
  2. Amihud Spike: Illiquidity suddenly jumps → liquidity cascade risk
  3. VIX Emergency: VIX > 45 → crisis-level fear
  4. Model Drift: Brier score exceeds threshold → retraining needed

Called from background_scanner.py on each scan cycle.
"""

import os
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# State tracking (persists across scan cycles in memory)
_last_gex_sign = None
_last_vix_level = None


def check_gex_flip(current_gex, ticker="SPY"):
    """
    Detects GEX sign change (positive → negative or vice versa).

    Positive GEX = dealers stabilize (sell rallies, buy dips)
    Negative GEX = dealers amplify moves (destabilizing)

    A flip is a major regime change signal.
    """
    global _last_gex_sign
    current_sign = "positive" if current_gex >= 0 else "negative"

    if _last_gex_sign is not None and current_sign != _last_gex_sign:
        _last_gex_sign = current_sign
        return {
            'triggered': True,
            'type': 'gex_flip',
            'from': _last_gex_sign,
            'to': current_sign,
            'value': current_gex,
            'message': (
                f"🔄 **GEX FLIP** → {current_sign.upper()}\n\n"
                f"📊 {ticker} Net Gamma: {current_gex/1e6:+.1f}M\n"
                f"{'⚠️ Dealers now AMPLIFY moves — expect higher vol' if current_sign == 'negative' else '✅ Dealers now STABILIZE — reduced vol expected'}"
            )
        }

    _last_gex_sign = current_sign
    return {'triggered': False}


def check_amihud_spike(current_amihud, threshold_multiplier=3.0, rolling_avg=None):
    """
    Detects Amihud illiquidity spike > threshold_multiplier × rolling average.

    High Amihud = illiquid market = large orders move prices more = cascade risk.
    """
    if rolling_avg is None or rolling_avg == 0:
        return {'triggered': False}

    ratio = current_amihud / rolling_avg
    if ratio > threshold_multiplier:
        return {
            'triggered': True,
            'type': 'amihud_spike',
            'ratio': ratio,
            'value': current_amihud,
            'message': (
                f"⚡ **AMIHUD SPIKE** — Illiquidity {ratio:.1f}× average\n\n"
                f"📊 Current: {current_amihud:.2e}\n"
                f"📊 Average: {rolling_avg:.2e}\n"
                f"⚠️ Liquidity cascade risk — widen stops, reduce position sizes"
            )
        }
    return {'triggered': False}


def check_vix_emergency(current_vix, threshold=45):
    """
    Detects VIX crossing the emergency threshold (default 45).

    VIX > 45 = extreme fear, historically correlates with crashes.
    Only alerts ONCE when crossing up (not on every scan while above).
    """
    global _last_vix_level

    was_below = _last_vix_level is None or _last_vix_level < threshold
    is_above = current_vix >= threshold

    _last_vix_level = current_vix

    if was_below and is_above:
        return {
            'triggered': True,
            'type': 'vix_emergency',
            'value': current_vix,
            'message': (
                f"🚨 **VIX EMERGENCY** — {current_vix:.1f}\n\n"
                f"📊 VIX crossed {threshold} threshold\n"
                f"⚠️ Crisis-level fear detected\n"
                f"💡 Consider: hedging, reducing exposure, or going to cash"
            )
        }
    return {'triggered': False}


def run_all_alerts():
    """
    Runs all alert checks. Called each scan cycle.

    Returns:
        list of alerts sent
    """
    alerts_sent = []

    # 1. GEX Flip
    try:
        from src.feature_engineering import calculate_gex
        gex_data = calculate_gex("SPY")
        gex_alert = check_gex_flip(gex_data.get('gex', 0))
        if gex_alert['triggered']:
            _send_alert(gex_alert['message'])
            alerts_sent.append(gex_alert)
    except Exception as e:
        print(f"  ⚠️ GEX alert check failed: {e}")

    # 2. VIX Emergency
    try:
        from src.data_loader import get_macro_data
        macro = get_macro_data()
        vix = macro.get('vix', 20)
        vix_alert = check_vix_emergency(vix)
        if vix_alert['triggered']:
            _send_alert(vix_alert['message'])
            alerts_sent.append(vix_alert)
    except Exception as e:
        print(f"  ⚠️ VIX alert check failed: {e}")

    # 3. Weather Auto-Sell
    try:
        from scripts.weather_auto_sell import run_auto_sell_check
        wx_alerts = run_auto_sell_check()
        alerts_sent.extend(wx_alerts)
    except Exception as e:
        print(f"  ⚠️ Weather auto-sell check failed: {e}")

    return alerts_sent


def _send_alert(message):
    """Send a Telegram alert."""
    try:
        from src.telegram_notifier import TelegramNotifier
        tn = TelegramNotifier()
        tn.send_alert(message)
        print(f"  📱 Alert sent: {message[:60]}...")
    except Exception as e:
        print(f"  ⚠️ Failed to send alert: {e}")


if __name__ == "__main__":
    print("Testing Market Alert System...")
    print()

    # GEX flip simulation
    print("GEX Flip Tests:")
    r1 = check_gex_flip(1000000)
    print(f"  First call (positive): triggered={r1['triggered']}")
    r2 = check_gex_flip(-500000)
    print(f"  Flip to negative: triggered={r2['triggered']}")
    if r2['triggered']:
        print(f"  Message: {r2['message'][:80]}...")

    # VIX emergency simulation
    print("\nVIX Emergency Tests:")
    r3 = check_vix_emergency(20)
    print(f"  VIX=20: triggered={r3['triggered']}")
    r4 = check_vix_emergency(50)
    print(f"  VIX=50: triggered={r4['triggered']}")
    if r4['triggered']:
        print(f"  Message: {r4['message'][:80]}...")
    r5 = check_vix_emergency(55)
    print(f"  VIX=55 (already above): triggered={r5['triggered']}")

    # Live check
    print("\nRunning all alerts...")
    sent = run_all_alerts()
    print(f"  Total alerts: {len(sent)}")
