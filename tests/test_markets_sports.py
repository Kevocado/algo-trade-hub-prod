from datetime import date

from tradehub.markets import event_date, kalshi_event_url


def test_event_date_reads_only_the_date_prefix_of_sports_event_tickers():
    assert event_date("KXNFLGAME-26OCT01PITCLE") == date(2026, 10, 1)
    assert event_date("KXNCAAFSPREAD-26SEP26GTSTAN") == date(2026, 9, 26)
    assert event_date("KXHIGHNY-26SEP25") == date(2026, 9, 25)   # weather unchanged


def test_kalshi_event_url_uses_series_title_slug():
    # Format checked in a browser on 2026-09-25: this URL opens the PIT vs CLE event page.
    assert kalshi_event_url("KXNFLGAME", "Professional Football Game", "KXNFLGAME-26OCT01PITCLE") == (
        "https://kalshi.com/markets/kxnflgame/professional-football-game/kxnflgame-26oct01pitcle"
    )
    assert kalshi_event_url("KXNCAAFSPREAD", "College Football Spread", "KXNCAAFSPREAD-26SEP26GTSTAN") == (
        "https://kalshi.com/markets/kxncaafspread/college-football-spread/kxncaafspread-26sep26gtstan"
    )
