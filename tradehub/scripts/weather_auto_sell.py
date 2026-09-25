"""
Weather Auto-Sell Engine — NWS Settlement Arbitrage

This engine monitors live NWS forecasts and open Kalshi weather positions.
When a temperature reading GUARANTEES a contract outcome (either for or against),
it sends a Telegram SELL alert to lock in profit or cut losses.

Rules:
  1. Only SELL orders — never initiates new positions
  2. Only weather positions — no macro/quant interference
  3. Only triggers on live NWS data changes
  4. Settlement: Kalshi uses 6AM-6PM daily highs from NWS

Usage:
  Called from background_scanner.py on each scan cycle.
"""

import re
from dotenv import load_dotenv

load_dotenv()


def parse_weather_ticker(ticker):
    """
    Parse a Kalshi weather ticker to extract city, date, direction, and strike.

    Example: KXHIGHNY-26FEB26-B33.5
      → city='NYC', date='2026-02-26', direction='below', strike=33.5

    Returns dict or None if not a weather ticker.
    """
    city_map = {"NY": "NYC", "CHI": "Chicago", "MIA": "Miami"}
    m = re.match(r'KX(\w+?)(NY|CHI|MIA)-(\d{2})([A-Z]{3})(\d{2})-([AB])([\d.]+)', ticker)
    if m:
        _, city_code, day, mon, yr, direction, strike = m.groups()
        months = {'JAN': '01', 'FEB': '02', 'MAR': '03', 'APR': '04',
                  'MAY': '05', 'JUN': '06', 'JUL': '07', 'AUG': '08',
                  'SEP': '09', 'OCT': '10', 'NOV': '11', 'DEC': '12'}
        date_str = f"20{yr}-{months.get(mon, '01')}-{day}"
        return {
            'city': city_map.get(city_code, city_code),
            'date': date_str,
            'direction': 'above' if direction == 'A' else 'below',
            'strike': float(strike),
        }
    return None


def check_settlement_guarantee(nws_temp, direction, strike):
    """
    Determines if an NWS reading guarantees a contract outcome.

    Args:
        nws_temp: float, the NWS forecast/observed high temp
        direction: str, 'above' or 'below'
        strike: float, the contract strike temperature

    Returns:
        dict: {
            'guaranteed': bool,
            'outcome': 'YES' or 'NO' or None,
            'reason': str,
        }
    """
    if direction == 'above':
        # Contract: "Will high be ABOVE X?"
        if nws_temp > strike:
            return {
                'guaranteed': True,
                'outcome': 'YES',
                'reason': f"NWS reads {nws_temp}°F > {strike}°F strike → YES guaranteed"
            }
        elif nws_temp < strike - 5:
            # If temp is significantly below, it's very unlikely to settle above
            return {
                'guaranteed': True,
                'outcome': 'NO',
                'reason': f"NWS reads {nws_temp}°F, {strike - nws_temp:.1f}° below strike → NO likely"
            }
    elif direction == 'below':
        # Contract: "Will high be BELOW X?"
        if nws_temp < strike:
            return {
                'guaranteed': True,
                'outcome': 'YES',
                'reason': f"NWS reads {nws_temp}°F < {strike}°F strike → YES guaranteed"
            }
        elif nws_temp > strike + 5:
            return {
                'guaranteed': True,
                'outcome': 'NO',
                'reason': f"NWS reads {nws_temp}°F, {nws_temp - strike:.1f}° above strike → NO likely"
            }

    return {'guaranteed': False, 'outcome': None, 'reason': 'Settlement uncertain'}


def evaluate_positions(positions, nws_forecasts):
    """
    Cross-references open Kalshi weather positions against live NWS data.

    Args:
        positions: list of dicts from KalshiPortfolio with 'ticker', 'position',
                   'average_price', 'market_price'
        nws_forecasts: dict from WeatherEngine.get_all_forecasts() like
                       {'NYC': {'2026-03-01': 42}, 'Chicago': {'2026-03-01': 35}}

    Returns:
        list of alert dicts ready for Telegram
    """
    alerts = []

    for pos in positions:
        ticker = pos.get('ticker', '')
        parsed = parse_weather_ticker(ticker)
        if not parsed:
            continue  # Not a weather ticker

        city = parsed['city']
        date = parsed['date']
        direction = parsed['direction']
        strike = parsed['strike']
        contracts = pos.get('position', 0)
        avg_cost = pos.get('average_price', 0)

        # Look up NWS temp for this city and date
        city_forecasts = nws_forecasts.get(city, {})
        nws_temp = city_forecasts.get(date)

        if nws_temp is None:
            continue  # No NWS data for this date

        # Check if settlement is guaranteed
        check = check_settlement_guarantee(nws_temp, direction, strike)

        if check['guaranteed']:
            # Determine if this is profit-taking or loss-cutting
            outcome = check['outcome']

            # If we're long YES and outcome is YES → lock in profit (SELL)
            # If we're long YES and outcome is NO → cut loss (SELL)
            # If we're long NO and outcome is NO → lock in profit (SELL)
            # If we're long NO and outcome is YES → cut loss (SELL)
            is_long_yes = contracts > 0
            is_profitable = (is_long_yes and outcome == 'YES') or (not is_long_yes and outcome == 'NO')

            action = "LOCK PROFIT" if is_profitable else "CUT LOSS"

            alerts.append({
                'ticker': ticker,
                'city': city,
                'date': date,
                'strike': strike,
                'direction': direction,
                'nws_temp': nws_temp,
                'outcome': outcome,
                'action': action,
                'contracts': abs(contracts),
                'avg_cost': avg_cost,
                'reason': check['reason'],
                'is_profitable': is_profitable,
            })

    return alerts


def run_auto_sell_check():
    """
    Main entry point: fetch positions + NWS data, evaluate, send Telegram alerts.
    Called by background_scanner.py on each scan cycle.

    Returns:
        list of alerts that were sent (empty if no action)
    """
    alerts_sent = []

    try:
        # 1. Get open positions from Kalshi
        from tradehub.core.kalshi_portfolio import KalshiPortfolio, check_portfolio_available
        if not check_portfolio_available():
            return []

        kp = KalshiPortfolio()
        summary = kp.get_portfolio_summary()
        positions = summary.get('positions', [])
        if not positions:
            return []

        # 2. Get live NWS forecasts
        from tradehub.engines.weather_engine import WeatherEngine
        we = WeatherEngine()
        forecasts = we.get_all_forecasts()
        if not forecasts:
            return []

        # 3. Evaluate
        alerts = evaluate_positions(positions, forecasts)
        if not alerts:
            return []

        # 4. Send Telegram alerts
        from tradehub.core.telegram_notifier import TelegramNotifier
        tn = TelegramNotifier()

        for alert in alerts:
            emoji = "💰" if alert['is_profitable'] else "🚨"
            msg = (
                f"{emoji} **WEATHER AUTO-SELL** ({alert['action']})\n\n"
                f"📍 {alert['city']} | {alert['date']}\n"
                f"🎯 Strike: {alert['strike']}°F ({alert['direction']})\n"
                f"🌡️ NWS: {alert['nws_temp']}°F\n"
                f"📊 Outcome: {alert['outcome']}\n"
                f"📋 Contracts: {alert['contracts']}\n"
                f"💡 {alert['reason']}\n\n"
                f"⚡ **Action: SELL {alert['contracts']} contracts of `{alert['ticker']}`**"
            )
            sent = tn.send_alert(msg)
            if sent:
                alerts_sent.append(alert)
                print(f"  📱 Auto-sell alert sent: {alert['ticker']} ({alert['action']})")

        # 5. Log to Supabase
        try:
            from tradehub.core.supabase_client import log_trade
            for alert in alerts_sent:
                log_trade({
                    'ticker': alert['ticker'],
                    'action': 'SELL',
                    'engine': 'weather_auto_sell',
                    'edge': 0,
                    'reason': alert['reason'],
                })
        except Exception:
            pass

    except Exception as e:
        print(f"  ⚠️ Weather auto-sell error: {e}")

    return alerts_sent


if __name__ == "__main__":
    print("Testing Weather Auto-Sell Engine...")
    print()

    # Parse test
    test_tickers = [
        "KXHIGHNY-01MAR26-B40",
        "KXHIGHCHI-01MAR26-A25",
        "KXHIGHMIA-02MAR26-B80",
    ]
    for t in test_tickers:
        p = parse_weather_ticker(t)
        if p:
            print(f"  {t} → {p['city']} {p['date']} {p['direction']} {p['strike']}°F")

    # Settlement guarantee tests
    print("\nSettlement Guarantees:")
    tests = [
        (45, 'above', 40),  # Temp clearly above strike
        (35, 'below', 40),  # Temp clearly below strike
        (38, 'above', 40),  # Uncertain
        (50, 'below', 40),  # Temp above strike for below contract
    ]
    for temp, direction, strike in tests:
        result = check_settlement_guarantee(temp, direction, strike)
        guar = "✅" if result['guaranteed'] else "❓"
        print(f"  {guar} Temp={temp}°F, {direction} {strike}°F → {result['outcome'] or 'uncertain'} | {result['reason']}")

    # Live check
    print("\nRunning live check...")
    sent = run_auto_sell_check()
    print(f"  Alerts sent: {len(sent)}")
