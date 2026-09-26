"""Round 1 item 3: the labor step and the ALFRED fetcher ignore the scan deadline.

The scan runs every engine under `SCAN_DEADLINE_SECONDS`, and step 7b learned the hard way that
one unbounded HTTP path is enough to overrun the hourly timer and overlap the next run. The labor
step has three such paths:

1. `scan_labor` runs in the engine phase, BEFORE the weather/gas/CPI writes. A hung ALFRED request
   therefore delays those writes directly, which is the whole reason sports was moved to run last.
2. `default_get_text` uses a flat 60s timeout with four unconditional retries: up to ~246s of
   predictor call inside a 15-minute scan, with no deadline anywhere in sight.
3. It retries only transport errors, so an ALFRED edge returning 503 fails the whole step instead
   of backing off.
"""
from datetime import datetime, timezone

import pytest
import requests

from tradehub.data.kalshi_live import LiveMarket  # noqa: F401  (documents the shape used below)
from tradehub.edges import Quote
from tradehub.engine_config import load_engine_config
from tradehub.scripts import scan as scan_mod
from tradehub.sports.feed import FeedUnavailable

NOW = datetime(2026, 9, 27, 12, 5, tzinfo=timezone.utc)   # 08:05 ET, a labor hour


class _Clock:
    """A monotonic clock the test drives, so the deadline arithmetic is exercised for real."""

    def __init__(self, t: float = 1000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.t += seconds


# ── the fetcher ───────────────────────────────────────────────────────────────

class _Resp:
    status_code = 200
    text = "observation_date,ICSA_20260101\n2026-01-01,1\n"

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code))


def _resp(status):
    resp = _Resp()
    resp.status_code = status
    return resp


def test_the_request_timeout_is_clamped_to_the_remaining_time():
    from tradehub.data.alfred_vintages import default_get_text

    seen = []
    clock = _Clock()

    def get(url, params=None, headers=None, timeout=None):
        seen.append(timeout)
        return _resp(200)

    default_get_text("u", {}, get=get, sleep=clock.sleep, clock=clock, deadline=1000.0 + 12.0)
    assert seen == [pytest.approx(12.0)], seen


def test_a_5xx_is_retried_with_backoff():
    """ALFRED's edge returns 503 under load. Retrying only transport errors turned a transient
    503 into a dead engine for the whole run."""
    from tradehub.data.alfred_vintages import default_get_text

    responses = [_resp(503), _resp(200)]
    clock = _Clock()

    def get(url, params=None, headers=None, timeout=None):
        return responses.pop(0)

    assert default_get_text("u", {}, get=get, sleep=clock.sleep, clock=clock) is not None
    assert responses == [], "a 503 was not retried"
    assert clock.t > 1000.0, "the retry did not back off"


def test_retries_are_skipped_when_the_budget_cannot_afford_them():
    """With 5s of scan budget left, a 60s-timeout request plus a backoff cannot finish. One
    attempt is all the budget allows, so the second must not be started."""
    from tradehub.data.alfred_vintages import default_get_text

    attempts = []
    clock = _Clock()

    def get(url, params=None, headers=None, timeout=None):
        attempts.append(timeout)
        return _resp(500)

    with pytest.raises(RuntimeError):
        default_get_text("u", {}, get=get, sleep=clock.sleep, clock=clock, deadline=1000.0 + 5.0)
    assert len(attempts) == 1, f"a retry was started with less time than one attempt needs: {attempts}"


def test_a_deadline_in_the_past_raises_without_a_request():
    from tradehub.data.alfred_vintages import default_get_text

    called = []
    with pytest.raises(RuntimeError, match="deadline"):
        default_get_text("u", {}, get=lambda *a, **k: called.append(1) or _resp(200),
                         sleep=lambda s: None, deadline=1000.0 - 1)
    assert called == [], "a request was issued with the budget already spent"


def test_retries_still_run_when_there_is_budget():
    from tradehub.data.alfred_vintages import default_get_text

    responses = [_resp(503), _resp(200)]
    attempts = []
    clock = _Clock()

    def get(url, params=None, headers=None, timeout=None):
        attempts.append(timeout)
        return responses.pop(0)

    default_get_text("u", {}, get=get, sleep=clock.sleep, clock=clock, deadline=1000.0 + 600)
    assert len(attempts) == 2, attempts


# ── the scan step ─────────────────────────────────────────────────────────────

def _stub_everything(monkeypatch, calls, labor_scan=None, *, labor_due=True):
    """Stub every engine and every write, recording the order they happen in."""
    from tradehub import predictions
    from tradehub.core import supabase_client
    from tradehub.sports.scan import SportsRun

    mod = scan_mod
    monkeypatch.setattr(mod, "KalshiLive", lambda *a, **k: object())
    monkeypatch.setattr(mod, "scan_weather", lambda *a, **k: calls.append("weather") or ([], []))
    monkeypatch.setattr(mod, "scan_gas", lambda *a, **k: ([], []))
    monkeypatch.setattr(mod, "cpi_scan_due", lambda now: False)
    monkeypatch.setattr(mod, "latest_gate_statuses", lambda *a: {})
    monkeypatch.setattr(mod, "remove_stale_edges", lambda *a, **k: None)
    monkeypatch.setattr(mod, "remove_started_sports_edges", lambda *a, **k: [])
    monkeypatch.setattr(mod, "remove_closed_cpi_edges", lambda *a, **k: calls.append("cpi_cleanup"))
    monkeypatch.setattr(mod, "labor_scan_due", lambda now: labor_due)
    monkeypatch.setattr(mod, "sports_due", lambda now: True)
    monkeypatch.setattr(mod, "run_sports_for_cron",
                        lambda *a, **k: (calls.append("sports"), SportsRun([], [], {}, {}))[1])
    monkeypatch.setattr(mod, "run_labor_step", labor_scan or (lambda *a, **k: ([], [], "ok")))
    monkeypatch.setattr(supabase_client, "get_client", lambda: "supa")
    monkeypatch.setattr(supabase_client, "upsert_opportunities",
                        lambda rows: calls.append("sports_write" if rows and rows[0].get("edge_type") == "SPORTS"
                                                  else "engine_write"))
    monkeypatch.setattr(predictions, "record_predictions", lambda *a, **k: calls.append("pred_write"))


def test_labor_runs_after_the_other_engines_have_written_and_before_sports(monkeypatch):
    """The point of the item: an ALFRED hang must not delay or endanger the weather/gas/CPI
    writes, so labor runs after them. Sports still runs last of all."""
    calls: list[str] = []
    _stub_everything(monkeypatch, calls, labor_scan=lambda *a, **k: (calls.append("labor"), ([], [], "ok"))[1])
    scan_mod.main(now=NOW, live=object(), client=object())
    for required in ("engine_write", "cpi_cleanup", "labor", "sports"):
        assert required in calls, f"{required} never happened: {calls}"
    assert calls.index("engine_write") < calls.index("labor"), calls
    assert calls.index("cpi_cleanup") < calls.index("labor"), calls
    assert calls.index("labor") < calls.index("sports"), calls


def test_an_exhausted_budget_skips_labor_without_failing_the_scan(monkeypatch, capsys):
    """`SCAN_DEADLINE_SECONDS` is checked before the labor step: with no budget left, the step is
    reported as skipped and the engines that already wrote keep their rows."""
    import json

    calls: list[str] = []
    real = scan_mod._ensure_scan_deadline
    armed = {"trip": False}

    def spy(deadline):
        if armed["trip"]:
            raise TimeoutError("scan deadline exceeded")
        real(deadline)

    _stub_everything(monkeypatch, calls,
                     labor_scan=lambda *a, **k: pytest.fail("the labor step ran with no budget left"))
    monkeypatch.setattr(scan_mod, "_ensure_scan_deadline", spy)
    monkeypatch.setattr(scan_mod, "remove_closed_cpi_edges",
                        lambda *a, **k: (calls.append("cpi_cleanup"), armed.__setitem__("trip", True))[0])
    rc = scan_mod.main(now=NOW, live=object(), client=object())
    summary = json.loads(capsys.readouterr().out)
    assert summary["labor_nowcast"]["status"] == "skipped: scan deadline reached before the labor step", \
        summary["labor_nowcast"]
    assert summary["writes"]["edges"]["labor_nowcast"] == "skipped", summary["writes"]
    assert summary["writes"]["edges"]["weather"] == "ok", summary["writes"]
    assert rc == 0, summary["failures"]


def test_main_reports_rather_than_crashes_without_a_supabase_client(monkeypatch, capsys):
    """get_client() raising must produce a summary and a non-zero exit, not an
    UnboundLocalError: the sports summary variables were only bound inside the client branch."""
    import json

    calls: list[str] = []
    from tradehub.core import supabase_client

    _stub_everything(monkeypatch, calls)
    monkeypatch.setattr(supabase_client, "get_client",
                        lambda: (_ for _ in ()).throw(RuntimeError("no service key")))
    rc = scan_mod.main(now=NOW, live=object(), client=None)
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "partial_failure", summary["status"]
    assert any("client" in f for f in summary["failures"]), summary["failures"]
    assert summary["sports"]["status"] == "skipped: no Supabase client", summary["sports"]
    assert summary["labor_nowcast"]["status"] == "skipped: no Supabase client", summary["labor_nowcast"]
    assert rc == 1


def test_the_deadline_reaches_the_alfred_fetcher(monkeypatch):
    """Not just the Kalshi client: the scan's deadline has to arrive at the HTTP request."""
    from tradehub.engines.labor import labor_market

    seen: dict = {}

    def inputs_fn(**kwargs):
        seen.update(kwargs)
        raise FeedUnavailable("stop here: the inputs were called with the right kwargs")

    market = labor_market({"ticker": "KXPAYROLLS-14MAY-T0", "event_ticker": "KXPAYROLLS-14MAY",
                           "strike_type": "greater", "floor_strike": 0,
                           "open_time": "2014-05-01T00:00:00Z", "close_time": "2014-06-06T12:29:00Z",
                           "title": "jobs"})

    class Live:
        def open_markets(self, series):
            return [type("LM", (), {"market": market, "quote": Quote(0.02, 0.05, 10.0, 10.0)})()]

    with pytest.raises(FeedUnavailable):
        scan_mod.scan_labor(Live(), datetime(2014, 6, 3, 14, 0, tzinfo=timezone.utc),
                            load_engine_config("labor_nowcast"), inputs_fn=inputs_fn, deadline=4242.0)
    assert seen.get("deadline") == 4242.0, (
        f"the ALFRED inputs were fetched with no deadline: {seen}"
    )
