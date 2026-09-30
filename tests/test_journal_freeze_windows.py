"""Tests for journal freeze window logic (reviewer instruction: watch first real freezes).

These tests verify that the freeze window calculations are correct for each forecaster type,
so that when the first real freezes occur, we can confirm the system is working as expected.
"""

from datetime import UTC, datetime, timedelta

from tradehub.journal.spx import next_target_day, freeze_at, spx_target
from tradehub.journal.kalshi_linked import in_freeze_window, FREEZE_LEAD


def test_spx_freeze_window_opens_at_10_utc():
    """S&P freeze window opens at 10:00 UTC (05:00 CT, 3h lead before 08:00 CT freeze)."""
    # At 10:00 UTC, the next target day should be today (freeze at 13:00 UTC)
    now = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    day = next_target_day(now)
    assert day is not None
    assert freeze_at(day) == datetime(2026, 9, 30, 13, 0, tzinfo=UTC)


def test_spx_freeze_window_closes_at_13_utc():
    """After 13:00 UTC, the freeze window for today has closed.

    next_target_day returns None because the next session's freeze is beyond the 3-hour lead.
    """
    now = datetime(2026, 9, 30, 13, 1, tzinfo=UTC)
    day = next_target_day(now)
    # After 13:00 UTC, the next session's freeze is > 3h away, so None
    assert day is None


def test_kalshi_freeze_window_24h():
    """Kalshi markets freeze 24h before close."""
    from tradehub.data.kalshi_live import LiveMarket
    from tradehub.edges import Quote
    from tradehub.markets import parse_market

    # Market closing in 12h should be in freeze window
    close = datetime(2026, 10, 14, 12, 25, tzinfo=UTC)
    market = parse_market({
        "ticker": "KXCPI-26SEP-T3.0",
        "event_ticker": "KXCPI-26SEP",
        "strike_type": "greater",
        "floor_strike": 3.0,
        "open_time": "2026-09-01T00:00:00Z",
        "close_time": close.isoformat(),
        "title": "CPI > 3.0%",
    })
    lm = LiveMarket(market, Quote(yes_bid=0.5, yes_ask=0.52, yes_bid_size=100.0, yes_ask_size=100.0))

    now = close - timedelta(hours=12)
    assert in_freeze_window(lm, now) is True

    # Market closing in 48h should NOT be in freeze window
    now = close - timedelta(hours=48)
    assert in_freeze_window(lm, now) is False


def test_no_freezes_outside_window():
    """No targets should be returned when no markets are in freeze window."""
    from tradehub.journal.forecasters.sentiment import SentimentMeter
    from tradehub.journal.spx import SpxCloses

    # At 07:32 UTC (before 10:00 UTC window), no S&P targets
    now = datetime(2026, 9, 30, 7, 32, tzinfo=UTC)
    spx = SpxCloses()
    meter = SentimentMeter(spx)
    targets = meter.targets(now)
    # Should be empty because we're before the freeze window
    assert targets == []


def test_freeze_window_boundary():
    """Test exact boundary of freeze window (3h lead)."""
    from tradehub.data.kalshi_live import LiveMarket
    from tradehub.edges import Quote
    from tradehub.markets import parse_market

    close = datetime(2026, 10, 14, 12, 25, tzinfo=UTC)
    market = parse_market({
        "ticker": "KXCPI-26SEP-T3.0",
        "event_ticker": "KXCPI-26SEP",
        "strike_type": "greater",
        "floor_strike": 3.0,
        "open_time": "2026-09-01T00:00:00Z",
        "close_time": close.isoformat(),
        "title": "CPI > 3.0%",
    })
    lm = LiveMarket(market, Quote(yes_bid=0.5, yes_ask=0.52, yes_bid_size=100.0, yes_ask_size=100.0))

    # Exactly 24h before close: should be in window
    now = close - FREEZE_LEAD
    assert in_freeze_window(lm, now) is True

    # Just after 24h before close: should NOT be in window
    now = close - FREEZE_LEAD - timedelta(seconds=1)
    assert in_freeze_window(lm, now) is False
