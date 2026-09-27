"""Keyed FRED path: a vintage from before the series existed, and pacing so a builder does not 429.

`build_jobs_scorecard --since 2023-01` walks back before JTSHIL, JTSJOL and ADPMNUSNERSA begin, and
FRED answers each of those realtime windows with a 400. Separately, the API path issues one request
per uncached vintage per series -- seven series over ~40 month-ends -- with no pacing, against a
~120 requests/minute limit.

Both are recorded behaviour, not speculation: the 400 body in
`fixtures/labor/fred_prehistory_400.json` is a real `fred/series/observations` response, and the
existence probe uses the request FRED's own error message recommends.
"""
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests

from tradehub.data.alfred_vintages import (
    FRED_MIN_INTERVAL_SECONDS,
    FRED_SERIES_OBSERVATIONS,
    SeriesNotFound,
    VintageNotPublished,
    default_get_text,
    fetch_vintages,
    fred_min_interval,
    parse_fred_observations_json,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS_CSV = (FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8")
PREHISTORY_400 = (FIXTURES / "fred_prehistory_400.json").read_text(encoding="utf-8")
FRED_JSON_20250131 = (FIXTURES / "payems_20250131_fred_api.json").read_text(encoding="utf-8")
FAKE_KEY = "abcdef0123456789abcdef0123456789"


class _Clock:
    """A monotonic clock that only moves when something sleeps, so waits are observable."""

    def __init__(self, t: float = 1000.0):
        self.t = t
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.t += seconds


def _requests_looking_get(responses, resp_headers=None):
    """A `requests.get` stand-in that builds error messages the way requests does: with the FULL url,
    query string and all, which is where a FRED key would leak.

    `resp_headers`, not `headers`: the real signature's `headers` is the REQUEST headers, and naming
    this one that would silently shadow them.
    """

    def get(url, params=None, headers=None, timeout=None):
        full = url + ("?" + urlencode(params) if params else "")
        status, body = responses.pop(0)
        response_headers = (resp_headers or {}) if status == 429 else {}

        class _Resp:
            status_code = status
            headers = response_headers
            text = body

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code} Client Error: for url: {full}")

        return _Resp()

    return get


# ── a vintage from before the series existed ──────────────────────────────────


def test_a_vintage_before_the_series_existed_is_empty_rather_than_an_error(tmp_path):
    """JTSHIL has no ALFRED coverage in 2009. That is a fact about the past, not a failure, and the
    labor inputs already read an empty vintage as "not known yet"."""
    def server(url, params, **kwargs):
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        return FRED_JSON_20250131  # the existence probe: the series is real

    out = fetch_vintages("JTSHIL", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=tmp_path,
                         today=date(2026, 1, 1), get_text=server)

    assert out == {date(2009, 12, 31): {}}


def test_a_series_that_does_not_exist_at_all_still_fails_loudly(tmp_path):
    """The 400 body is the SAME for a pre-history vintage and for a series id that does not exist --
    a nonsense id gets "does not exist in ALFRED" too. So the message alone cannot be trusted, and
    treating it as an empty vintage would turn a typo into a permanently cached, permanently silent
    hole in the feature set. The series is confirmed with the probe FRED's own error message
    suggests: the same request without the realtime window."""
    def server(url, params, **kwargs):
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        raise SeriesNotFound(params["series_id"])

    with pytest.raises(RuntimeError, match="NOTASERIES123"):
        fetch_vintages("NOTASERIES123", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=tmp_path,
                       today=date(2026, 1, 1), get_text=server)


def test_a_400_body_from_a_real_response_is_classified_as_prehistory():
    """The classification runs on the recorded body, not on a hand-built one: a wrong marker would
    make every pre-history vintage a hard failure again."""
    from tradehub.data.alfred_vintages import _classify_fred_400

    assert _classify_fred_400(PREHISTORY_400) is VintageNotPublished
    # "does not exist in ALFRED" contains "does not exist", so the ALFRED case must be tested first or
    # a pre-history vintage would be reported as a missing series -- and vice versa.
    assert _classify_fred_400('{"error_code":400,"error_message":"Bad Request.  The series does not exist."}') is SeriesNotFound
    assert _classify_fred_400('{"error_code":400,"error_message":"Bad Request.  Variable api_key is not set."}') is None
    assert _classify_fred_400("<html>nope</html>") is None


def test_the_existence_probe_is_paid_for_once_per_series_not_once_per_vintage(tmp_path):
    calls = []

    def server(url, params, **kwargs):
        calls.append(params)
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        return FRED_JSON_20250131

    days = [date(2009, 12, 31), date(2009, 11, 30), date(2009, 10, 31)]
    fetch_vintages("JTSHIL", days, api_key=FAKE_KEY, cache_dir=tmp_path, today=date(2026, 1, 1),
                   get_text=server)

    probes = [c for c in calls if "realtime_start" not in c]
    assert len(probes) == 1, f"the series was re-probed {len(probes)} times for one answer"


def test_an_empty_prehistory_vintage_is_cached_so_it_is_not_refetched(tmp_path):
    """Past vintages never change and ALFRED coverage only extends forwards, so a confirmed-empty past
    vintage is cached like any other. Otherwise every scan pays a 400 -- and a paced slot -- for every
    month before the series began, three times a day, forever."""
    def server(url, params, **kwargs):
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        return FRED_JSON_20250131

    cache = tmp_path / "alfred"
    first = fetch_vintages("JTSHIL", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=cache,
                           today=date(2026, 1, 1), get_text=server)
    assert first == {date(2009, 12, 31): {}}

    def no_network(url, params, **kwargs):
        raise AssertionError(f"a cached empty vintage still hit the network: {params}")

    assert fetch_vintages("JTSHIL", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=cache,
                          today=date(2026, 1, 1), get_text=no_network) == first


def test_the_prehistory_path_never_logs_the_key(caplog):
    def server(url, params, **kwargs):
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        return FRED_JSON_20250131

    with caplog.at_level("WARNING"):
        fetch_vintages("JTSHIL", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=None,
                       today=date(2026, 1, 1), get_text=server)

    assert [r for r in caplog.records if "JTSHIL" in r.getMessage()], "the empty vintage was silent"
    assert FAKE_KEY not in caplog.text, caplog.text


# ── pacing, so a keyed builder does not 429 ───────────────────────────────────


def _fred_server(calls):
    def get_text(url, params, **kwargs):
        calls.append(params)
        name = f"payems_{params['realtime_start'].replace('-', '')}_fred_api.json"
        path = FIXTURES / name
        # Only two vintages were recorded; any other date replays one of them, which is all this
        # server needs to be believable.
        return (path if path.is_file() else FIXTURES / "payems_20250131_fred_api.json").read_text(
            encoding="utf-8")

    return get_text


def test_keyed_requests_are_paced_at_least_the_minimum_interval_apart():
    """~120 requests/min is FRED's limit, and this path makes one request per uncached vintage per
    series. Unpaced, `build_jobs_scorecard --since 2023-01` trips it inside one run."""
    clock = _Clock()
    days = [date(2024, 12, 31) + (date(2025, 1, 31) - date(2024, 12, 31)) * i for i in range(3)]

    fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server([]), cache_dir=None,
                   today=date(2026, 1, 1), min_interval=0.6, sleep=clock.sleep, clock=clock)

    assert clock.sleeps == [0.6, 0.6], clock.sleeps


def test_the_first_request_is_not_delayed():
    """Pacing is a gap BETWEEN requests. Sleeping before the first one would add a pointless 0.6s to
    every scan, three times a day, for nothing."""
    clock = _Clock()
    fetch_vintages("PAYEMS", [date(2025, 1, 31)], api_key=FAKE_KEY, get_text=_fred_server([]),
                   cache_dir=None, today=date(2026, 1, 1), min_interval=0.6, sleep=clock.sleep,
                   clock=clock)

    assert clock.sleeps == []


def test_pacing_never_sleeps_past_the_scan_deadline():
    """A paced wait must not push the run past the budget, and a budget already spent must not even
    be slept through: the request path refuses the request instead, which is the report an operator
    needs. Uses the real `default_get_text` because that is where the deadline is enforced."""
    from functools import partial

    clock = _Clock()
    attempts = []
    get = _requests_looking_get([(200, FRED_JSON_20250131)] * 4)

    def counting_get(url, params=None, headers=None, timeout=None):
        attempts.append(timeout)
        return get(url, params, headers, timeout)

    days = [date(2024, 12, 31), date(2025, 1, 31)]
    with pytest.raises(RuntimeError, match="deadline"):
        fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, cache_dir=None, today=date(2026, 1, 1),
                       min_interval=30.0, sleep=clock.sleep, clock=clock, deadline=clock() - 1.0,
                       get_text=partial(default_get_text, get=counting_get, sleep=clock.sleep,
                                        clock=clock))

    assert clock.sleeps == [], "a wait was taken with no budget left to spend it in"
    assert attempts == []


def test_the_pacing_interval_is_configurable_and_defaults_to_the_fred_limit(monkeypatch):
    assert FRED_MIN_INTERVAL_SECONDS == 0.6
    assert fred_min_interval() == 0.6

    clock = _Clock()
    days = [date(2024, 12, 31) + (date(2025, 1, 31) - date(2024, 12, 31)) * i for i in range(2)]
    fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server([]), cache_dir=None,
                   today=date(2026, 1, 1), min_interval=0, sleep=clock.sleep, clock=clock)
    assert clock.sleeps == [], "min_interval=0 must not pace"

    monkeypatch.setenv("FRED_MIN_INTERVAL_SECONDS", "2.5")
    assert fred_min_interval() == 2.5
    monkeypatch.setenv("FRED_MIN_INTERVAL_SECONDS", "")
    assert fred_min_interval() == 0.6, "an empty env value must fall back to the default"


def test_a_429_honours_retry_after():
    """FRED sends Retry-After when it rate-limits. Backing off 1.5s and immediately re-asking is how a
    rate limit becomes a failed scan."""
    clock = _Clock()
    get = _requests_looking_get([(429, "slow down"), (429, "slow down"), (200, FRED_JSON_20250131)],
                                resp_headers={"Retry-After": "45"})

    assert default_get_text(FRED_SERIES_OBSERVATIONS, {"api_key": FAKE_KEY}, get=get, sleep=clock.sleep,
                            clock=clock, secret=FAKE_KEY) is not None
    assert clock.sleeps == [45.0, 45.0], clock.sleeps


def test_a_429_without_retry_after_waits_at_least_thirty_seconds():
    clock = _Clock()
    get = _requests_looking_get([(429, "slow down"), (200, FRED_JSON_20250131)])

    default_get_text(FRED_SERIES_OBSERVATIONS, {"api_key": FAKE_KEY}, get=get, sleep=clock.sleep,
                     clock=clock, secret=FAKE_KEY)
    assert clock.sleeps and min(clock.sleeps) >= 30.0, clock.sleeps


def test_a_429_backoff_stays_inside_the_scan_deadline():
    """A 30s floor must not turn a 429 into four 30s waits inside a scan with 20s left. The existing
    budget check has to refuse the retry instead."""
    clock = _Clock()
    attempts = []
    get = _requests_looking_get([(429, "slow down")] * 4, resp_headers={"Retry-After": "45"})

    def counting_get(url, params=None, headers=None, timeout=None):
        attempts.append(timeout)
        return get(url, params, headers, timeout)

    with pytest.raises(RuntimeError):
        default_get_text(FRED_SERIES_OBSERVATIONS, {"api_key": FAKE_KEY}, get=counting_get,
                         sleep=clock.sleep, clock=clock, deadline=1000.0 + 20.0, secret=FAKE_KEY)
    assert len(attempts) == 1, f"a 45s retry was started with 20s of budget: {attempts}"


def test_the_keyless_csv_path_is_never_paced():
    """alfredgraph returns 12 vintages per request and is not rate-limited the same way. Pacing it
    would add a wait to every series for nothing."""
    clock = _Clock()
    days = [date(2024, 12, 31) + (date(2025, 1, 31) - date(2024, 12, 31)) * i for i in range(3)]

    def server(url, params):
        return PAYEMS_CSV

    fetch_vintages("PAYEMS", days, api_key="", get_text=server, cache_dir=None, today=date(2026, 1, 1),
                   sleep=clock.sleep, clock=clock)

    assert clock.sleeps == []


def test_the_new_paths_never_parse_a_probe_payload_as_data():
    """The existence probe downloads the series' current values. They must never reach the vintage."""
    def server(url, params, **kwargs):
        if "realtime_start" in params:
            raise VintageNotPublished("pre-history")
        return FRED_JSON_20250131

    out = fetch_vintages("JTSHIL", [date(2009, 12, 31)], api_key=FAKE_KEY, cache_dir=None,
                         today=date(2026, 1, 1), get_text=server)

    assert out[date(2009, 12, 31)] == {}, out
    assert parse_fred_observations_json(FRED_JSON_20250131), "the fixture itself must still parse"
