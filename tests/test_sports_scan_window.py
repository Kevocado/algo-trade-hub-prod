"""The scan must not price a game it can never trade.

`scan.py:183` filtered only `start_utc <= now` -- games already under way -- with no upper bound. So
the scan priced every upcoming game, stored it, and `check_candidate` then rejected it for
`starts_too_late`. CFB week 5 sits 120-168h out against a 72h window, which is why 86 of the 100 live
rows carried `starts_too_late`: they were dead on arrival by construction.

This is the fix at the source rather than in the filter, so the work is never done and the rows are
never written.
"""
from datetime import datetime, timedelta, timezone

from tradehub.sports import scan as scan_mod
from tradehub.sports.mapping import MatchedGame, MatchReport
from tradehub.sports.scan import scan_sport

NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


class _Game:
    def __init__(self, start_utc):
        self.game_id = "g1"
        self.start_utc = start_utc
        self.home = "UConn"
        self.away = "Syracuse"
        self.p_home = 0.55          # what `price_market` reads for a winner market
        self.model_version = "xgb@2026-09-04"
        self.snapshotted_at = start_utc - timedelta(hours=6)


class _Market:
    def __init__(self, ticker="KXNCAAFGAME-26OCT03SYRCONN-CONN"):
        self.ticker = ticker
        self.title = "UConn wins"
        self.event_ticker = "KXNCAAFGAME-26OCT03SYRCONN"
        self.close_time = NOW + timedelta(days=10)


class _Quote:
    yes_bid, yes_ask = 0.40, 0.44
    no_bid, no_ask = 0.56, 0.60
    yes_bid_size = yes_ask_size = no_bid_size = no_ask_size = 500


class _SportMarket:
    def __init__(self, market, quote):
        self.market = market
        self.quote = quote
        self.suffix = "CONN"       # `team_code` strips trailing digits off this
        self.volume = 5000.0


def _cfg(**params):
    """A SportConfig built fresh on every call, so the window itself can be varied.

    This was a module-level PARAMS dict handed to every EngineConfig by reference: an override
    applied in one test would have mutated the dict every later test in the session read. A factory
    also does the thing the boundary test needs and a constant cannot -- vary the bound and watch
    the edge move with it.
    """
    from tradehub.engine_config import EngineConfig
    from tradehub.sports.config import SportConfig
    p = {
        "max_quote_spread": 0.04, "min_resting_size": 100, "min_volume": 1000,
        "min_hours_to_start": 1, "max_hours_to_start": 72,
        "calibration_max_dev": 0.10, "calibration_min_n": 20,
    }
    p.update(params)
    return SportConfig(
        sport="cfb", engine="sports_cfb", base_url="http://x", site_url="http://y",
        series={"winner": "KXNCAAFGAME"}, series_titles={"KXNCAAFGAME": "NCAAF"},
        edge=EngineConfig(min_edge_pct=4.0, prefer_maker=True, params=p),
    )


def _feed():
    class _Feed:
        games = []
        calibration = {}
        rejected = []
    return _Feed()


def _scan(hours_out, monkeypatch, **params):
    game = _Game(NOW + timedelta(hours=hours_out))
    sm = _SportMarket(_Market(), _Quote())
    report = MatchReport(matched=[MatchedGame(
        game=game, home_code="CONN", away_code="SYR", suffix="CONN", markets={"winner": [sm]},
    )])
    # `monkeypatch`, not a bare `scan_mod.match_games = ...`: match_games and load_aliases are module
    # globals, so a permanent assignment leaks this fake into every later test in the session. The
    # real load_aliases is left alone, since scan_sport reads aliases.version off it for the report.
    monkeypatch.setattr(scan_mod, "match_games", lambda *a, **k: report)
    return scan_sport(_cfg(**params), {}, _feed(), NOW)


def test_a_game_beyond_the_window_is_never_priced(monkeypatch):
    """120h out: outside max_hours_to_start=72, so it must not be priced at all."""
    result = _scan(hours_out=120, monkeypatch=monkeypatch)

    assert result.report["markets_priced"] == 0, "a game outside the window must not be priced"
    assert result.edges == [], "and it must not be written as an edge either"
    assert result.too_far == 1, "and it must be counted, so the report can say why nothing appeared"


def test_a_game_inside_the_window_is_still_priced(monkeypatch):
    """24h out: well inside 1-72h, so the bound must not cost us a tradeable game."""
    result = _scan(hours_out=24, monkeypatch=monkeypatch)

    assert result.too_far == 0
    assert result.report["games_started"] == 0
    # `markets_priced` is the counter the pricer itself increments, so this is the claim the test
    # exists for: the bound did not skip a game that sits inside the window.
    assert result.report["markets_priced"] == 1, result.report


def test_the_boundary_is_the_configured_one_not_a_hardcoded_number(monkeypatch):
    """The edge is where the config puts it, and it moves when the config moves.

    Two halves, because on its own neither half earns the name. The 71h/73h pair pins today's 72h
    setting and is a real boundary check -- it would catch a hardcoded 48 -- but a hardcoded 72
    sails straight through it, which is exactly the drift this test exists to rule out. So the
    window itself is varied: at max_hours_to_start=48 the same 49h game is out and the same 47h game
    is in. 72 written into the source instead of read from cfg fails the 49h line; 48 fails the
    71h line. Only reading the config survives both.
    """
    assert _scan(hours_out=71, monkeypatch=monkeypatch).too_far == 0
    assert _scan(hours_out=73, monkeypatch=monkeypatch).too_far == 1

    narrow = {"max_hours_to_start": 48}
    assert _scan(hours_out=47, monkeypatch=monkeypatch, **narrow).too_far == 0
    assert _scan(hours_out=49, monkeypatch=monkeypatch, **narrow).too_far == 1, (
        "a 49h game is outside a 48h window, so the bound is not being read from cfg"
    )


def test_an_already_started_game_is_still_counted_as_started_not_too_far(monkeypatch):
    """The two exclusions must not be conflated: a started game is not 'too far'."""
    result = _scan(hours_out=-3, monkeypatch=monkeypatch)

    assert result.report["games_started"] == 1
    assert result.too_far == 0
