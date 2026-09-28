"""The scan must not price a game it can never trade.

`scan_sport` filtered only `start_utc <= now` -- games already under way -- with no upper bound. So
the scan priced every upcoming game, stored it, and `check_candidate` then rejected it for
`starts_too_late`. CFB week 5 sits 120-168h out against a 72h window, which is why 86 of the 100 live
rows carried `starts_too_late`: they were dead on arrival by construction.

The approved window is TWO bounds (§9 approval 2: "games outside 1-72h are never priced"), and for a
while only the far one existed. A game 0.5h out was priced, stored, and rejected for
`starts_too_soon` -- the same waste, the same "dead on arrival by construction", and the same
unanswerable report, because the summary showed `too_far: 0` beside a stored reject carrying
`starts_too_soon`. Nothing said which end of the window did the dropping.

This is the fix at the source rather than in the filter, so the work is never done and the rows are
never written -- for BOTH ends.
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
        # The rest of `feed.FeedGame`'s published fields. `_edge_row` reads `sigma` -- it writes
        # `raw_payload["sigma"]`, the value the ranking scores -- and a fake that leaves it off is
        # not a stricter fake, it is a different game type. The first thing it did was turn a window
        # assertion into an `AttributeError` in a file about windows.
        self.margin_mu = 3.0
        self.sigma = 0.015
        self.total_mu, self.total_sigma = 55.0, 12.0


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
    """24h out: well inside 1-72h, so neither bound may cost us a tradeable game."""
    result = _scan(hours_out=24, monkeypatch=monkeypatch)

    assert result.too_far == 0
    assert result.too_soon == 0
    assert result.report["games_started"] == 0
    # `markets_priced` is the counter the pricer itself increments, so this is the claim the test
    # exists for: the bound did not skip a game that sits inside the window.
    assert result.report["markets_priced"] == 1, result.report


def test_a_game_inside_the_near_bound_is_never_priced(monkeypatch):
    """0.5h out: inside min_hours_to_start=1, so it must not be priced at all.

    The mirror of the far bound and the same defect. `check_candidate` rejects this for
    `starts_too_soon`, so pricing it here is precisely the "priced and then rejected" waste the far
    bound was added to remove -- and the row is STORED before it is rejected, which is the half
    that reaches a reader.
    """
    result = _scan(hours_out=0.5, monkeypatch=monkeypatch)

    assert result.report["markets_priced"] == 0, "a game inside the near bound must not be priced"
    assert result.edges == [], "and it must not be written as an edge either"
    assert result.too_soon == 1, "and it must be counted under its own name"
    # The load-bearing half: the OTHER counter must be zero. One shared count would satisfy the
    # assertion above and leave the report unable to say which end of the window dropped the game,
    # which is the half of this the report exists for.
    assert result.too_far == 0, "a too-soon game is not too far; the two are different facts"


def test_the_near_boundary_is_the_configured_one_not_a_hardcoded_number(monkeypatch):
    """The same treatment the far bound got, for the same reason: a hardcoded 1 must fail.

    The 1.01h/0.99h pair pins today's 1h setting and would catch a hardcoded 6, but a hardcoded 1
    sails straight through it -- which is the whole reason the far-bound test varies its config
    rather than only its hours. So this one varies the config too: at min_hours_to_start=6 the same
    7h game is inside and the same 5h game is out. A 1 written into the source instead of read from
    cfg fails the 5h line; a 6 fails the 1.01h line. Only reading the config survives both.
    """
    assert _scan(hours_out=1.01, monkeypatch=monkeypatch).too_soon == 0
    assert _scan(hours_out=0.99, monkeypatch=monkeypatch).too_soon == 1

    wide = {"min_hours_to_start": 6}
    assert _scan(hours_out=7, monkeypatch=monkeypatch, **wide).too_soon == 0
    assert _scan(hours_out=5, monkeypatch=monkeypatch, **wide).too_soon == 1, (
        "a 5h game is inside a 6h near bound, so the near bound is not being read from cfg"
    )


def test_both_ends_of_the_window_land_in_their_own_counter(monkeypatch):
    """One game per end of the same window, so a reader of the report learns which bound fired.

    The two counters are only worth having if they are independent facts. A fold of the near bound
    into `too_far` would pass every "a 0.5h game is not priced" assertion in this file and leave the
    report claiming a far-out game was dropped when a nearly-started one was.
    """
    near = _scan(hours_out=0.5, monkeypatch=monkeypatch)
    assert (near.too_soon, near.too_far) == (1, 0), near.report

    far = _scan(hours_out=80, monkeypatch=monkeypatch)
    assert (far.too_soon, far.too_far) == (0, 1), far.report


def test_the_window_bounds_are_the_filter_s_bounds_and_are_read_by_name():
    """The scan and the filter must read the same two config keys, or the scan re-creates the waste.

    Not a duplication test in the usual sense -- it is why the numbers above hold. If either side
    renames a key, invents a different one, or reads the bound from somewhere else, the two windows
    disagree while both still pass their own tests, and the disagreement is a game priced and stored
    for nothing. Pinned by name because the failure is a silent divergence, not a crash.
    """
    import inspect

    from tradehub.sports import candidates

    filter_src = inspect.getsource(candidates.check_candidate)
    assert 'params["min_hours_to_start"]' in filter_src
    assert 'params["max_hours_to_start"]' in filter_src

    scan_src = inspect.getsource(scan_mod.scan_sport)
    assert 'cfg.edge.params["min_hours_to_start"]' in scan_src, (
        "the scan reads the near bound from a different source than the filter does"
    )
    assert 'cfg.edge.params["max_hours_to_start"]' in scan_src, (
        "the scan reads the far bound from a different source than the filter does"
    )


def test_an_already_started_game_is_counted_as_started_and_not_as_either_bound(monkeypatch):
    """The three exclusions must not be conflated: a started game is neither too far nor too soon.

    A game 3h in the past is outside BOTH ends of the window on the number, so if the started check
    came after the window bounds it would be tallied `too_soon` and the report would blame the near
    bound for a game that had already kicked off. It counts as started, and only that.
    """
    result = _scan(hours_out=-3, monkeypatch=monkeypatch)

    assert result.report["games_started"] == 1
    assert result.too_far == 0
    assert result.too_soon == 0, (
        "a started game was tallied as too soon, so the report blames the near bound for a game "
        "that had already kicked off"
    )


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
