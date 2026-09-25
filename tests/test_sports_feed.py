import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

from tradehub.sports.feed import FeedUnavailable, fetch_feed, parse_feed

FIXTURES = Path(__file__).parent / "fixtures" / "sports"


def _raw(sport="nfl"):
    return json.loads((FIXTURES / f"{sport}_kalshi_feed.json").read_text())


def test_parse_recorded_nfl_feed():
    feed = parse_feed(_raw("nfl"))
    assert feed.sport == "nfl"
    assert [g.game_id for g in feed.games] == ["2026_03_CIN_PIT", "2026_03_HOU_IND", "2026_03_LA_DEN"]
    hou = feed.games[1]
    assert (hou.home, hou.away) == ("IND", "HOU")
    assert hou.start_utc == datetime(2026, 9, 27, 17, 0, tzinfo=timezone.utc)
    assert hou.p_home == pytest.approx(0.2954260889601903)
    assert hou.sigma == pytest.approx(13.223153618916728)
    assert hou.snapshotted_at < hou.start_utc
    assert feed.rejected == []
    assert len(feed.calibration["winner"]) == 10


def test_parse_drops_backfilled_and_post_kickoff_rows():
    raw = _raw("nfl")
    raw["games"][0]["backfilled"] = True
    raw["games"][1]["snapshotted_at"] = "2026-09-27T17:05:00+00:00"   # after kickoff
    raw["games"][2]["p_home"] = 1.7
    feed = parse_feed(raw)
    assert feed.games == []
    assert sorted(r["reason"] for r in feed.rejected) == ["backfilled", "bad_probability", "snapshot_not_pregame"]


def test_parse_recorded_cfb_feed_has_no_lines_but_a_distribution():
    feed = parse_feed(_raw("cfb"))
    stanford = next(g for g in feed.games if g.home == "Stanford")
    assert stanford.away == "Georgia Tech"
    assert stanford.margin_mu is not None and stanford.total_sigma is not None


class _Resp:
    def __init__(self, status, payload=None):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


def test_fetch_retries_once_after_a_cold_start_timeout():
    calls = []

    def get(url, timeout):
        calls.append((url, timeout))
        if len(calls) == 1:
            raise requests.Timeout("scale-to-zero cold start")
        return _Resp(200, _raw("nfl"))

    feed = fetch_feed("https://nfl.example.com/", get=get, sleep=lambda s: None)
    assert len(feed.games) == 3
    assert calls == [("https://nfl.example.com/api/kalshi-feed", 60.0)] * 2


def test_fetch_gives_up_after_the_retry():
    def get(url, timeout):
        return _Resp(404)

    with pytest.raises(FeedUnavailable):
        fetch_feed("https://nfl.example.com", get=get, sleep=lambda s: None)
