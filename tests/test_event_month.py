from datetime import date

from tradehub.markets import event_month


def test_event_month_handles_current_and_legacy_tickers():
    assert event_month("KXPAYROLLS-26AUG") == date(2026, 8, 1)
    assert event_month("KXU3-26AUG") == date(2026, 8, 1)
    assert event_month("PAYROLLS-24FEB") == date(2024, 2, 1)
    assert event_month("PROLLS-23DECB") == date(2023, 12, 1)  # odd legacy suffix
    assert event_month("U3-21JUL") == date(2021, 7, 1)
