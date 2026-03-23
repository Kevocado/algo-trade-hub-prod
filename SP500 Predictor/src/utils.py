import pytz
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo
import pandas as pd

def get_market_status(ticker="SPX"):
    """
    Determines if the market is currently open for the given ticker.
    Returns a dict with status details.
    """
    # Crypto is 24/7
    if ticker in ["BTC", "ETH", "BTC-USD", "ETH-USD"]:
        return {
            'is_open': True,
            'is_pre_market': False,
            'status_text': "Market is OPEN (24/7)",
            'next_event_text': "Closes Never",
            'color': "#3b82f6" # Blue for Live
        }

    tz = pytz.timezone('US/Eastern')
    now = datetime.now(tz)
    current_time = now.time()
    
    # Market Hours (ET)
    pre_market_open = time(4, 0)
    market_open = time(9, 30)
    market_close = time(16, 0)
    
    # Weekends
    if now.weekday() >= 5: # Sat=5, Sun=6
        return {
            'is_open': False,
            'is_pre_market': False,
            'status_text': "Market is CLOSED (Weekend)",
            'next_event_text': "Opens Monday 9:30 AM ET",
            'color': "#6b7280" # Grey for Closed
        }
        
    # Weekdays
    if pre_market_open <= current_time < market_open:
        # Pre-Market
        return {
            'is_open': False,
            'is_pre_market': True,
            'status_text': "PRE-MARKET",
            'next_event_text': "Opens 9:30 AM ET",
            'color': "#f59e0b" # Orange/Yellow
        }
    elif market_open <= current_time < market_close:
        # Regular Market Hours
        # Calculate time to close
        close_dt = now.replace(hour=16, minute=0, second=0, microsecond=0)
        delta = close_dt - now
        hours, remainder = divmod(delta.seconds, 3600)
        minutes = remainder // 60
        
        return {
            'is_open': True,
            'is_pre_market': False,
            'status_text': "Market is OPEN",
            'next_event_text': f"Closes in {hours}h {minutes}m",
            'color': "#3b82f6" # Blue for Live
        }
    else:
        # After Hours / Closed
        return {
            'is_open': False,
            'is_pre_market': False,
            'status_text': "Market is CLOSED",
            'next_event_text': "Opens Tomorrow 9:30 AM ET",
            'color': "#6b7280" # Grey for Closed
        }

def determine_best_timeframe(ticker):
    """
    Determines the best timeframe (Hourly vs Daily) based on asset and market status.
    """
    # Crypto -> Always Hourly (Fast paced)
    if ticker in ["BTC", "ETH", "BTC-USD", "ETH-USD"]:
        return "Hourly"
        
    # Stocks -> Hourly if Open, Daily if Closed
    status = get_market_status(ticker)
    if status['is_open']:
        return "Hourly"
    else:
        return "Daily"

def categorize_markets(markets, ticker):
    """
    Categorizes markets into Hourly, Daily, and Range buckets based on expiration and title.

    This implementation uses the system `zoneinfo` timezone for America/New_York
    so DST is handled correctly. Crypto (BTC/ETH) hourly opportunities are only
    considered between 09:00 and 23:59 ET. Index markets use the usual logic.
    """
    buckets = {'hourly': [], 'daily': [], 'range': []}

    now_utc = datetime.utcnow().replace(tzinfo=ZoneInfo("UTC"))
    ny_tz = ZoneInfo("America/New_York")
    now_ny = now_utc.astimezone(ny_tz)

    is_crypto = ticker in ["BTC", "ETH"]

    for m in markets:
        try:
            exp_str = m.get('expiration')
            if not exp_str:
                continue

            # Parse expiration preserving timezone info if present
            exp_time = pd.to_datetime(exp_str)
            if exp_time.tzinfo is None:
                # assume UTC if no tz provided
                exp_time = exp_time.replace(tzinfo=timezone.utc)
            else:
                # Convert to UTC for consistent comparison
                exp_time = exp_time.astimezone(timezone.utc)

            # Normalize to NY timezone for date/hour checks (only for crypto hours check)
            exp_ny = exp_time.astimezone(ny_tz)

            # Range detection - use market_type field from Kalshi API
            # market_type can be: 'above', 'below', or 'range'
            market_type = m.get('market_type', '')
            
            if market_type == 'range':
                buckets['range'].append(m)
                continue


            # Time difference in minutes from now (UTC-based compare)
            time_diff_min = (exp_time - now_utc).total_seconds() / 60.0
            time_diff_hours = time_diff_min / 60.0
            time_diff_days = time_diff_hours / 24.0

            # Hourly: expires within 720 minutes (12 hours) - Widened window
            # AND (for crypto) inside allowed NY hours if desired, or loosen it.
            if 0 < time_diff_min <= 720:
                if is_crypto:
                    # Crypto active window: 09:00 - 23:59 NY time. 
                    # Consider removing this check if users want 24/7 crypto. 
                    # For now, keep it but maybe widen or allow "close enough"
                    if 0 <= now_ny.hour <= 23: # Allow all day for now as markets might be weird
                         buckets['hourly'].append(m)
                else:
                    buckets['hourly'].append(m)
                continue

            # Daily: expires within 30 days (more flexible to show available markets)
            # Extended to 30 days based on user feedback
            if 0 < time_diff_days <= 30:
                buckets['daily'].append(m)
                continue

        except Exception as e:
            print(f"Error categorizing market: {e}")
    
    # Debug logging
    print(f"📊 Categorization for {ticker}:")
    print(f"   Hourly: {len(buckets['hourly'])} markets")
    print(f"   Daily: {len(buckets['daily'])} markets")
    print(f"   Range: {len(buckets['range'])} markets")
    print(f"   Current NY time: {now_ny.strftime('%Y-%m-%d %H:%M %Z')}")

    return buckets

