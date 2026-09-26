from datetime import date
from pathlib import Path
from urllib.parse import urlencode

import pytest
import requests

from tradehub.data.alfred_vintages import (
    ALFRED_GRAPH_CSV,
    FRED_SERIES_OBSERVATIONS,
    VINTAGES_PER_REQUEST,
    fetch_vintages,
    parse_alfred_csv,
    parse_fred_observations_json,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "labor"
PAYEMS_CSV = (FIXTURES / "payems_2024_2025.csv").read_text(encoding="utf-8")
# Real `fred/series/observations` payloads (file_type=json, observation_start=2024-09-01) for the same
# two PAYEMS vintages, recorded 2026-09-26. No api_key appears in a response body; the key only ever
# travels in the request URL.
FRED_JSON = {
    "2024-12-31": (FIXTURES / "payems_20241231_fred_api.json").read_text(encoding="utf-8"),
    "2025-01-31": (FIXTURES / "payems_20250131_fred_api.json").read_text(encoding="utf-8"),
}
FAKE_KEY = "abcdef0123456789abcdef0123456789"


def test_parse_multi_vintage_csv_skips_blank_cells():
    vintages = parse_alfred_csv(PAYEMS_CSV)
    assert sorted(vintages) == [date(2024, 12, 31), date(2025, 1, 31), date(2025, 2, 28), date(2025, 3, 31)]
    assert date(2024, 12, 1) not in vintages[date(2024, 12, 31)]  # not yet published
    assert vintages[date(2025, 1, 31)][date(2024, 12, 1)] == 159536.0
    assert vintages[date(2025, 2, 28)][date(2024, 12, 1)] == 158926.0  # after the Feb-2025 benchmark


def test_parse_rejects_non_csv():
    with pytest.raises(ValueError):
        parse_alfred_csv("<html>Access Denied</html>")


def _fake_server(calls):
    def get_text(url, params):
        assert url == ALFRED_GRAPH_CSV
        days = params["vintage_date"].split(",")
        assert params["id"].split(",") == ["PAYEMS"] * len(days)
        calls.append(days)
        header = "observation_date," + ",".join(f"PAYEMS_{d.replace('-', '')}" for d in days)
        return header + "\n2024-01-01," + ",".join(str(100 + i) for i in range(len(days))) + "\n"
    return get_text


def test_fetch_batches_requests_and_caches_past_vintages(tmp_path):
    calls = []
    days = [date(2024, 1, 1) + (date(2024, 1, 2) - date(2024, 1, 1)) * i for i in range(VINTAGES_PER_REQUEST + 3)]
    out = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert [len(c) for c in calls] == [VINTAGES_PER_REQUEST, 3]
    assert out[days[0]] == {date(2024, 1, 1): 100.0}
    assert (tmp_path / "PAYEMS" / f"{days[0].isoformat()}.csv").is_file()
    again = fetch_vintages("PAYEMS", days, get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert again == out and len(calls) == 2  # served from the cache


def test_fetch_never_requests_today_or_future(tmp_path):
    calls = []
    out = fetch_vintages("PAYEMS", [date(2026, 1, 1), date(2026, 2, 1), date(2025, 12, 31)],
                         get_text=_fake_server(calls), cache_dir=tmp_path, today=date(2026, 1, 1))
    assert calls == [["2025-12-31"]]
    assert list(out) == [date(2025, 12, 31)]


def test_the_cache_round_trips_seven_digit_values_exactly(tmp_path):
    """`_write_cache` used `{v:g}`, which is SIX significant digits. CCSA 1,897,123 was cached as
    `1.897e+06` and read back as 1897000.0 — so a cached run and a fresh run produced different
    nowcasts, and the difference was invisible unless you diffed two runs by hand.
    """
    from tradehub.data.alfred_vintages import _write_cache

    vintage = date(2026, 8, 31)
    values = {
        date(2026, 8, 1): 1897123.0,      # 7 digits: the CCSA case
        date(2026, 7, 1): 1_234_567.0,
        date(2026, 6, 1): 0.1,
        date(2026, 5, 1): -23.0,
        date(2026, 4, 1): 0.000123,
        date(2026, 3, 1): 1234567.5,
    }
    _write_cache(tmp_path / "CCSA" / f"{vintage}.csv", "CCSA", vintage, values)
    text = (tmp_path / "CCSA" / f"{vintage}.csv").read_text(encoding="utf-8")
    assert "1897123" in text and "e+0" not in text, text
    assert parse_alfred_csv(text)[vintage] == values, parse_alfred_csv(text)[vintage]


def test_a_warm_cache_gives_the_same_values_as_a_cold_one(tmp_path):
    """The property the precision bug broke: fetch_vintages must be a pure function of the
    requested vintage dates, whether or not they were already on disk."""
    big = {date(2026, 8, 1): 1897123.0, date(2026, 7, 1): 1_234_567.0}
    header = "observation_date,CCSA_20260831"

    def server(url, params):
        return header + "\n" + "\n".join(f"{obs.isoformat()},{value}" for obs, value in big.items()) + "\n"

    days = [date(2026, 8, 31)]
    cold = fetch_vintages("CCSA", days, get_text=server, cache_dir=tmp_path, today=date(2026, 9, 5))
    warm = fetch_vintages("CCSA", days, get_text=server, cache_dir=tmp_path, today=date(2026, 9, 5))
    assert cold == warm
    assert warm[date(2026, 8, 31)] == big


# ── the keyed FRED API path ───────────────────────────────────────────────────
#
# alfredgraph.csv is keyless but, from some networks, unreachable (this machine gets an HTTP/2
# INTERNAL_ERROR from it, while api.stlouisfed.org answers). With FRED_API_KEY set we ask the API
# instead. The two must be interchangeable, or a run on the VPS would quietly grade different numbers
# from the same backtest.


def _csv_server(calls):
    def get_text(url, params):
        assert url == ALFRED_GRAPH_CSV
        calls.append(("csv", params))
        return PAYEMS_CSV

    return get_text


def _fred_server(calls):
    def get_text(url, params, **kwargs):
        assert url == FRED_SERIES_OBSERVATIONS
        calls.append(("api", params, kwargs))
        # Only the two recorded vintages have their own payload; any other date replays one of them,
        # which is all this server needs to be believable.
        return FRED_JSON.get(params["realtime_start"], FRED_JSON["2025-01-31"])

    return get_text


def test_the_api_path_and_the_keyless_csv_path_give_identical_month_end_values(tmp_path):
    """The property that makes the fallback safe: same series, same vintage dates, same numbers.
    Both sides here are recordings -- the alfredgraph CSV and the FRED API JSON -- of the same two
    PAYEMS month-end vintages."""
    days = [date(2024, 12, 31), date(2025, 1, 31)]
    keyed = fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server([]),
                           cache_dir=tmp_path / "api", today=date(2026, 1, 1))
    keyless = fetch_vintages("PAYEMS", days, api_key="", get_text=_csv_server([]),
                             cache_dir=tmp_path / "csv", today=date(2026, 1, 1))

    assert keyed == keyless
    # Spot-check the month-end values themselves, so an equal-but-wrong pair cannot pass.
    assert keyed[date(2025, 1, 31)][date(2024, 12, 1)] == 159536.0
    assert keyed[date(2024, 12, 31)][date(2024, 11, 1)] == 159288.0
    assert date(2024, 12, 1) not in keyed[date(2024, 12, 31)]  # not yet published on that vintage


def test_parse_fred_json_matches_the_recorded_csv_column():
    assert parse_fred_observations_json(FRED_JSON["2025-01-31"]) == parse_alfred_csv(PAYEMS_CSV)[date(2025, 1, 31)]
    assert parse_fred_observations_json(FRED_JSON["2024-12-31"]) == {
        date(2024, 9, 1): 159025.0, date(2024, 10, 1): 159061.0, date(2024, 11, 1): 159288.0,
    }


def test_the_api_path_asks_for_one_realtime_window_per_vintage():
    """Unlike alfredgraph's 12 vintage columns, the API returns a single realtime window, so there is
    nothing to batch: one request per uncached vintage, with realtime_start == realtime_end."""
    calls = []
    days = [date(2024, 12, 31) + (date(2025, 1, 31) - date(2024, 12, 31)) * i for i in range(3)]
    fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server(calls),
                   cache_dir=None, today=date(2026, 1, 1))

    assert [c[1]["realtime_start"] for c in calls] == ["2024-12-31", "2025-01-31", "2025-03-03"]
    for _, params, kwargs in calls:
        assert params["series_id"] == "PAYEMS"
        assert params["realtime_end"] == params["realtime_start"]
        assert params["file_type"] == "json"
        assert params["api_key"] == FAKE_KEY
        # The key must also reach the fetcher as `secret`, or nothing redacts it out of the errors
        # `requests` builds from this request's URL.
        assert kwargs["secret"] == FAKE_KEY


def test_the_key_comes_from_the_environment_and_its_absence_keeps_the_keyless_path(monkeypatch):
    calls = []
    monkeypatch.setenv("FRED_API_KEY", FAKE_KEY)
    fetch_vintages("PAYEMS", [date(2025, 1, 31)], get_text=_fred_server(calls), cache_dir=None,
                   today=date(2026, 1, 1))
    assert [c[0] for c in calls] == ["api"]

    monkeypatch.delenv("FRED_API_KEY", raising=False)
    csv_calls = []
    fetch_vintages("PAYEMS", [date(2025, 1, 31)], get_text=_csv_server(csv_calls), cache_dir=None,
                   today=date(2026, 1, 1))
    assert [c[0] for c in csv_calls] == ["csv"]


def test_a_cache_written_by_one_path_is_read_by_the_other(tmp_path):
    """A VPS with a key and a laptop without one share nothing but the cache directory. A cache
    written by the API path must satisfy a keyless run, or the same backtest grades two datasets."""
    days = [date(2024, 12, 31), date(2025, 1, 31)]
    cache = tmp_path / "alfred"
    fetch_vintages("PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server([]), cache_dir=cache,
                   today=date(2026, 1, 1))

    def no_network(url, params):
        raise AssertionError(f"a warm cache still hit the network: {url}")

    assert fetch_vintages("PAYEMS", days, api_key="", get_text=no_network, cache_dir=cache,
                          today=date(2026, 1, 1)) == fetch_vintages(
        "PAYEMS", days, api_key=FAKE_KEY, get_text=_fred_server([]), cache_dir=tmp_path / "other",
        today=date(2026, 1, 1))


def test_the_api_path_still_abandons_when_the_scan_deadline_has_passed():
    """The deadline travels `fetch_vintages` -> `default_get_text` on the API path too, so a scan
    with 7 of its 15 minutes gone cannot start a request it cannot finish."""
    from functools import partial

    from tradehub.data.alfred_vintages import default_get_text

    attempts = []
    clock = _Clock()
    ok = _requests_looking_get([(200, FRED_JSON["2025-01-31"])])

    def get(url, params=None, headers=None, timeout=None):
        attempts.append(timeout)
        return ok(url, params, headers, timeout)

    with pytest.raises(RuntimeError, match="deadline"):
        fetch_vintages("PAYEMS", [date(2025, 1, 31)], api_key=FAKE_KEY,
                       get_text=partial(default_get_text, get=get, sleep=clock.sleep, clock=clock),
                       cache_dir=None, today=date(2026, 1, 1), deadline=clock() - 1.0)

    assert attempts == []


def test_a_missing_observation_is_dropped_rather_than_read_as_zero():
    """FRED writes "." for a missing observation. Treating it as 0.0 would put a fabricated payrolls
    print of zero into a nowcast."""
    payload = ('{"observations":[{"date":"2025-01-01","value":"159069"},'
               '{"date":"2025-02-01","value":"."},{"date":"2025-03-01","value":""}]}')
    assert parse_fred_observations_json(payload) == {date(2025, 1, 1): 159069.0}


@pytest.mark.parametrize("body", [
    "<html>Access Denied</html>",
    '{"error_code": 400, "error_message": "Bad Request.  Variable api_key is not set."}',
])
def test_a_payload_that_is_not_a_series_response_is_rejected(body):
    with pytest.raises(ValueError):
        parse_fred_observations_json(body)


# ── the key must never escape ─────────────────────────────────────────────────


def _requests_looking_get(responses):
    """A `requests.get` stand-in that builds error messages the way requests does: with the FULL
    url, query string and all. That is the leak -- a 400 from FRED embeds `?api_key=...`."""
    def get(url, params=None, headers=None, timeout=None):
        full = url + ("?" + urlencode(params) if params else "")
        status, text = responses.pop(0)

        class _Resp:
            status_code = status

            def __init__(self):
                self.text = text

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise requests.HTTPError(f"{self.status_code} Client Error: for url: {full}")

        return _Resp()

    return get


def test_the_key_is_not_in_the_error_a_rejected_request_raises():
    from tradehub.data.alfred_vintages import default_get_text

    params = {"series_id": "PAYEMS", "realtime_start": "2025-01-31", "realtime_end": "2025-01-31",
              "file_type": "json", "api_key": FAKE_KEY}
    get = _requests_looking_get([(400, '{"error_code": 400}')])

    with pytest.raises(RuntimeError) as caught:
        default_get_text(FRED_SERIES_OBSERVATIONS, params, get=get, secret=FAKE_KEY)

    reported = str(caught.value) + str(caught.value.__cause__) + repr(caught.value.__cause__)
    assert FAKE_KEY not in reported, reported
    assert "***" in reported, "nothing was redacted, so the guard is not actually doing anything"
    assert params["api_key"] == FAKE_KEY, "the request itself must still carry the real key"


def test_the_key_is_not_in_the_error_a_transport_failure_raises():
    from tradehub.data.alfred_vintages import default_get_text

    def get(url, params=None, headers=None, timeout=None):
        raise requests.ConnectionError(
            f"HTTPConnectionPool(host='api.stlouisfed.org'): Max retries exceeded with url: "
            f"/fred/series/observations?{urlencode(params)}")

    with pytest.raises(RuntimeError) as caught:
        default_get_text(FRED_SERIES_OBSERVATIONS, {"api_key": FAKE_KEY}, get=get, secret=FAKE_KEY)

    assert FAKE_KEY not in str(caught.value)


def test_the_key_is_not_in_the_log(caplog):
    from tradehub.data.alfred_vintages import default_get_text

    clock = _Clock()
    get = _requests_looking_get([(500, "boom")] * 4)
    with caplog.at_level("WARNING"):
        with pytest.raises(RuntimeError):
            default_get_text(FRED_SERIES_OBSERVATIONS, {"api_key": FAKE_KEY}, get=get, sleep=clock.sleep,
                             clock=clock, deadline=1000.0 + 5.0, secret=FAKE_KEY)

    assert [r for r in caplog.records if "budget" in r.getMessage()], "the retry warning never fired"
    assert FAKE_KEY not in caplog.text, caplog.text


def test_a_deadline_already_past_does_not_leak_the_key_either():
    from tradehub.data.alfred_vintages import default_get_text

    params = {"api_key": FAKE_KEY}
    with pytest.raises(RuntimeError) as caught:
        default_get_text(FRED_SERIES_OBSERVATIONS, params, get=lambda *a, **k: pytest.fail("no request"),
                         secret=FAKE_KEY, clock=lambda: 1000.0, deadline=1000.0 - 1.0)
    assert FAKE_KEY not in str(caught.value)


class _Clock:
    """A monotonic clock that only moves when something sleeps, so a retry backoff is observable."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds
