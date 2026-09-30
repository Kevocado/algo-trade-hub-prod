# Wave 2 Daily-Direction Forecasters (VIX, Gold, EUR/USD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Journal next-session direction for VIX, gold and EUR/USD with the same walk-forward model as the S&P quant, each on its own session calendar and a source that is reachable from the VPS.

**Architecture:** `tradehub/journal/daily.py` generalises `spx.py` over a `DailySource(family, source, fetch, is_session)`: the same target shape (`<family>:<t>:up`), 08:00 CT freeze, 3h freeze lead, climatology and settlement, plus a `closed_only` guard so an intraday bar is never a close. `DirectionForecaster` reuses `tradehub/models/spy_direction` (features, logistic fit, hashed monthly artifacts) with a per-family artifact namespace. Three thin source constructors pick VIX/FRED, gold/Yahoo-GLD and EUR/USD/Frankfurter.

**Tech Stack:** Python 3.12, numpy, requests, pytest. Reuses plan (a), (d) and (e) code.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§8 Wave 2–3 forecasters, §6 target definition, §10 gates). **Depends on:** plans (a), (d) and (e) merged (all are).

> **Provenance:** every code block below was implemented and run by the reviewer on top of `main@34cff1c` in a scratch worktree before this plan was written: full backend suite **1393 passed** with `time.monotonic` forced to 5.0 and to 1e7; new files ruff-clean; both live sources fetched and parsed (2,952 GLD closes, 3,007 ECB EUR/USD rates, latest 2026-09-29). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, daily gate minimum **200 settled targets**, BSS vs climatology (no market exists for these), timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- **Never push to `main`.** One PR, from a fresh branch off `main`.
- **Spec deviations (reviewer's decisions of 2026-09-30, for Kevin to confirm in the PR):**
  1. **No Stooq.** Stooq serves scripts a JavaScript proof-of-work wall (also from the VPS) and the journal does not bypass bot checks. Do **not** add a Yahoo "fallback" behind it: the earlier attempt used Stooq symbols against a dead endpoint.
  2. **Gold settles on the GLD ETF (raw close), not COMEX GC=F:** a continuous futures series jumps at every contract roll and would grade roll artefacts as "direction". The tile must say `GLD (gold ETF)`.
  3. **EUR/USD settles on the ECB euro reference rate** (Frankfurter, keyless, documented), one rate per TARGET business day published ~16:00 CET, which is after the 08:00 CT freeze.
  4. **VIX** uses FRED `VIXCLS` (the key is already on the VPS); FRED posts it a day or two late, so settlement is retried on later runs.
- Yahoo returns 429 to the default `python-requests` agent and 200 to an honest one: the journal sends `tradehub-journal/1.0 (+repo url)` and **must not** spoof a browser user agent.
- A close is usable only after its exchange-local date has ended (`closed_only`); a bar for "today" can be an intraday price.
- All three are `provisional` until 200 settled targets (daily gate); their probabilities come from the same L2 logistic, price-only features, refit monthly on sessions before the month, never on the scored period.
- Reachability checked from the VPS on 2026-09-30: Frankfurter 200, Yahoo chart 200, Stooq wall. Record a fresh check in the PR body.
- Out of scope: housing and the Kalshi-vs-model pseudo-forecaster (wave 3), earnings and crypto (v1.x), any change to `quant_engine.py` or the weather quarantine.

---

### Task 1: Sources, calendars, daily plumbing and the direction forecasters

**Files:**
- Modify: `tradehub/models/spy_direction/model.py` (`ArtifactStore` gains a `namespace`; default unchanged)
- Create: `tradehub/data/frankfurter.py`, `tradehub/data/yahoo_chart.py`, `tradehub/journal/calendars.py`, `tradehub/journal/daily.py`, `tradehub/journal/forecasters/daily_direction.py`
- Test: `tests/test_journal_wave2.py`

**Interfaces:**
- Consumes: plan (d) `tradehub.journal.spx` (`CT`, `FREEZE_LEAD`, `HISTORY_DAYS`, `climatology_up`, `freeze_at`, `up_outcome`), `tradehub.journal.nyse` (`is_session`, `_easter`), `tradehub.data.fred_daily.fetch_fred_daily`; plan (e) `tradehub.models.spy_direction.{features,model}`; plan (a) `CalendarEntry`, `Forecast`, `Settlement`, `run_journal`, `tests/journal_fakes.FakeJournalDB`.
- Produces: `parse_rates`, `fetch_eurusd`; `parse_chart`, `fetch_chart`, `default_get_json` (honest UA); `is_target_day`; `DailySource`, `DailyCloses`, `closed_only`, `next_target_day(now, is_session)`, `daily_entry`, `settle_daily`; `vix_source`, `gold_source`, `eurusd_source`, `DirectionForecaster(closes, name, version, store=None)`, `build_wave2(store_root=None)` → forecasters `vix_direction@vix-wf-v1`, `gold_direction@gold-wf-v1`, `eurusd_direction@eurusd-wf-v1` (cadence `daily`, targets `vix:<t>:up`, `gold:<t>:up`, `eurusd:<t>:up`).

- [ ] **Step 1: Write the failing test** (`tests/test_journal_wave2.py`)

```python
import random
from datetime import UTC, date, datetime, timedelta

from journal_fakes import FakeJournalDB

from tradehub.data.frankfurter import parse_rates
from tradehub.data.yahoo_chart import parse_chart
from tradehub.journal.calendars import is_target_day
from tradehub.journal.daily import DailyCloses, DailySource, closed_only, next_target_day, settle_daily
from tradehub.journal.forecasters.daily_direction import DirectionForecaster, eurusd_source, gold_source, vix_source
from tradehub.journal.nyse import is_session
from tradehub.journal.runner import run_journal
from tradehub.models.spy_direction.model import ArtifactStore


def _series(is_open, n=900, seed=5, start=date(2023, 1, 2)):
    rng, level, out, day = random.Random(seed), 100.0, {}, start
    while len(out) < n:
        if is_open(day):
            level *= 1.0 + rng.gauss(0.0002, 0.006)
            out[day] = level
        day += timedelta(days=1)
    return out


def test_target_calendar_skips_ecb_holidays_and_weekends():
    assert not is_target_day(date(2026, 4, 3))   # Good Friday
    assert not is_target_day(date(2026, 4, 6))   # Easter Monday
    assert not is_target_day(date(2026, 5, 1)) and not is_target_day(date(2026, 12, 26))
    assert is_target_day(date(2026, 9, 30)) and not is_target_day(date(2026, 10, 3))
    assert is_target_day(date(2026, 7, 3)) and not is_session(date(2026, 7, 3))  # the calendars differ


def test_frankfurter_and_yahoo_payloads_parse_to_date_keyed_closes():
    rates = parse_rates({"rates": {"2026-09-28": {"USD": 1.1378}, "2026-09-29": {"USD": 1.1355}}})
    assert rates == {date(2026, 9, 28): 1.1378, date(2026, 9, 29): 1.1355}
    payload = {"chart": {"result": [{
        "meta": {"exchangeTimezoneName": "America/New_York"},
        "timestamp": [1790688600, 1790775000, 1790861400],  # 13:30 UTC = 09:30 EDT
        "indicators": {"quote": [{"close": [382.89, None, 383.6]}], "adjclose": [{"adjclose": [1, 2, 3]}]},
    }]}}
    closes, tz = parse_chart(payload)
    assert tz == "America/New_York" and len(closes) == 2 and 382.89 in closes.values()
    assert 1.0 not in closes.values()  # raw close, never adjclose


def test_a_bar_dated_today_is_never_a_close():
    now = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)  # 11:00 EDT: today's GLD bar is intraday
    closes = {date(2026, 9, 30): 380.0, date(2026, 10, 1): 383.0}
    assert closed_only(closes, "America/New_York", now) == {date(2026, 9, 30): 380.0}
    same_evening = datetime(2026, 10, 2, 3, 0, tzinfo=UTC)  # 23:00 EDT on Oct 1: still "today"
    assert date(2026, 10, 1) not in closed_only(closes, "America/New_York", same_evening)
    next_day = datetime(2026, 10, 2, 5, 0, tzinfo=UTC)  # 01:00 EDT on Oct 2: Oct 1 is over
    assert date(2026, 10, 1) in closed_only(closes, "America/New_York", next_day)


def test_the_target_follows_each_familys_own_calendar():
    friday = datetime(2026, 7, 3, 11, 0, tzinfo=UTC)  # 06:00 CDT on the US holiday
    assert next_target_day(friday, is_target_day) == date(2026, 7, 3)  # ECB still publishes
    assert next_target_day(friday, is_session) is None  # NYSE is shut and Monday's freeze is far off


def test_eurusd_freezes_before_the_fix_and_settles_on_the_ecb_rate(tmp_path):
    rates = _series(is_target_day)
    last = max(rates)
    day = last + timedelta(days=1)
    while not is_target_day(day):
        day += timedelta(days=1)
    rates[day] = rates[last] * 1.01  # the fix that will print on the target day
    published = {d: v for d, v in rates.items() if d < day}
    clock = [datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=11)]  # 06:00 CDT
    source = DailySource("eurusd", "ecb:EURUSD", lambda start: (dict(published), "Europe/Berlin"), is_target_day)
    fc = DirectionForecaster(DailyCloses(source), "eurusd_direction", "eurusd-wf-v1",
                             ArtifactStore(tmp_path, "eurusd_direction"))
    db = FakeJournalDB(lambda: clock[0])
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["eurusd_direction@eurusd-wf-v1"]["frozen"] == 1
    [row] = db.tables["journal_forecasts"]
    assert row["target"] == f"eurusd:{day.isoformat()}:up" and row["payload"]["source"] == "ecb:EURUSD"
    published[day] = rates[day]
    clock[0] = datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=11)
    out = run_journal(db, [fc], clock[0])
    assert out["forecasters"]["eurusd_direction@eurusd-wf-v1"]["settled"] == 1
    assert db.tables["journal_settlements"][0]["outcome"] == 1


def test_settle_waits_for_the_close_and_ignores_a_non_session():
    source = DailySource("vix", "fred:VIXCLS", lambda s: ({date(2026, 9, 29): 18.0}, "America/New_York"), is_session)
    closes = DailyCloses(source)
    now = datetime(2026, 10, 1, 15, 0, tzinfo=UTC)
    assert settle_daily("vix:2026-09-30:up", now, closes) is None  # FRED has not posted the 30th
    assert settle_daily("vix:2026-10-03:up", now, closes) is None  # a Saturday is not a session


def test_each_family_has_its_own_artifact_namespace_and_stale_data_is_a_gap(tmp_path):
    closes = _series(is_session)
    last = max(closes)
    source = DailySource("vix", "fred:VIXCLS", lambda s: (dict(closes), "America/New_York"), is_session)
    fc = DirectionForecaster(DailyCloses(source), "vix_direction", "vix-wf-v1", ArtifactStore(tmp_path, "vix_direction"))
    now = datetime.combine(last + timedelta(days=1), datetime.min.time(), UTC) + timedelta(hours=11)
    artifact, digest = fc.model_for(last + timedelta(days=1), now)
    assert (tmp_path / "vix_direction").is_dir() and not (tmp_path / "spy_direction").exists()
    assert artifact.train_end < (last + timedelta(days=1)).replace(day=1).isoformat() and len(digest) == 64
    from tradehub.journal.contract import CalendarEntry
    far = last + timedelta(days=30)
    assert fc.forecast(CalendarEntry(f"vix:{far.isoformat()}:up", "vix", "daily", now + timedelta(days=30)), now) is None


def test_the_registry_runs_wave_2_with_unique_keys_and_no_network():
    from tradehub.journal.registry import FORECASTERS

    keys = [(f.name, f.version) for f in FORECASTERS]
    assert {("vix_direction", "vix-wf-v1"), ("gold_direction", "gold-wf-v1"),
            ("eurusd_direction", "eurusd-wf-v1")} <= set(keys)
    assert len(set(keys)) == len(keys)
    assert vix_source().family == "vix" and gold_source().source == "yahoo:GLD" and eurusd_source().family == "eurusd"


def test_yahoo_requests_identify_the_journal_not_a_browser(monkeypatch):
    from tradehub.data import yahoo_chart

    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen.update(headers=headers, timeout=timeout)
        return Resp()

    monkeypatch.setattr(yahoo_chart.requests, "get", fake_get)
    assert yahoo_chart.default_get_json("https://x", {}) == {"ok": True}
    assert seen["headers"]["User-Agent"].startswith("tradehub-journal/") and "Mozilla" not in seen["headers"]["User-Agent"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_wave2.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'tradehub.data.frankfurter'`.

- [ ] **Step 3: Implement**

`tradehub/models/spy_direction/model.py` (apply this change; wave-1 behaviour is unchanged because the default namespace is `spy_direction`):

```diff
diff --git a/tradehub/models/spy_direction/model.py b/tradehub/models/spy_direction/model.py
index eb9bfd0..26eecc2 100644
--- a/tradehub/models/spy_direction/model.py
+++ b/tradehub/models/spy_direction/model.py
@@ -69,9 +69,9 @@ def sha256(text: str) -> str:
 class ArtifactStore:
     """`<root>/spy_direction/<name>.json` plus `manifest.json` = {name: sha256}."""
 
-    def __init__(self, root: Path | None = None):
+    def __init__(self, root: Path | None = None, namespace: str = "spy_direction"):
         base = root or Path(os.environ.get(MODEL_DIR_ENV) or DEFAULT_MODEL_DIR)
-        self.dir = base / "spy_direction"
+        self.dir = base / namespace
 
     def _manifest(self) -> dict[str, str]:
         path = self.dir / "manifest.json"
```

`tradehub/data/frankfurter.py`:

```python
"""ECB euro foreign-exchange reference rates via Frankfurter (keyless, documented, daily).

The ECB publishes one EUR/USD reference rate per TARGET business day at about 16:00 CET. The wave-2
EUR/USD forecaster settles on this series because Stooq (the spec's source) now serves scripts a
JavaScript proof-of-work wall, which the journal does not bypass.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from tradehub.backtest.http import default_get_json

FRANKFURTER_URL = "https://api.frankfurter.dev/v1"


def parse_rates(payload: dict[str, Any], quote: str = "USD") -> dict[date, float]:
    rates = payload.get("rates") or {}
    return {date.fromisoformat(day): float(row[quote]) for day, row in rates.items() if quote in row}


def fetch_eurusd(start: date, *, end: date | None = None,
                 get_json: Callable[..., Any] = default_get_json) -> dict[date, float]:
    window = f"{start.isoformat()}..{end.isoformat() if end else ''}"
    return parse_rates(get_json(f"{FRANKFURTER_URL}/{window}", {"base": "EUR", "symbols": "USD"}))
```

`tradehub/data/yahoo_chart.py`:

```python
"""Daily raw closes from Yahoo's chart JSON (keyless; the endpoint yfinance already uses).

Used for gold (the GLD ETF, see `forecasters/daily_direction.py`). Raw `close`, never `adjclose`: the
settlement is the price that printed, and adjusted history is restated after distributions.
Bars whose exchange-local date is None-priced are dropped, not zero-filled.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

import requests

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
# Yahoo answers 429 to the default python-requests agent and 200 to an honest, descriptive one. The
# journal identifies itself; it does not pretend to be a browser.
USER_AGENT = "tradehub-journal/1.0 (+https://github.com/Kevocado/algo-trade-hub-prod)"
TIMEOUT_SECONDS = 30


def default_get_json(url: str, params: dict | None = None) -> Any:
    response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT_SECONDS)
    response.raise_for_status()
    return response.json()


def parse_chart(payload: dict[str, Any]) -> tuple[dict[date, float], str]:
    """({exchange-local date: close}, exchange timezone name) from one chart payload."""
    result = ((payload.get("chart") or {}).get("result") or [None])[0]
    if not result:
        raise ValueError(f"no chart result in payload: {str(payload)[:120]}")
    zone_name = result["meta"].get("exchangeTimezoneName") or "UTC"
    zone = ZoneInfo(zone_name)
    closes = result["indicators"]["quote"][0]["close"]
    out: dict[date, float] = {}
    for stamp, close in zip(result.get("timestamp") or [], closes, strict=False):
        if close is not None:
            out[datetime.fromtimestamp(stamp, UTC).astimezone(zone).date()] = float(close)
    return out, zone_name


def fetch_chart(symbol: str, start: date, *, get_json: Callable[..., Any] = default_get_json
                ) -> tuple[dict[date, float], str]:
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
    params = {"period1": period1, "period2": int(datetime.now(UTC).timestamp()) + 86400, "interval": "1d"}
    return parse_chart(get_json(f"{CHART_URL}/{symbol}", params))
```

`tradehub/journal/calendars.py`:

```python
"""Session calendars for the daily-direction families (v2 spec §8: each family states its own).

- NYSE sessions (`tradehub.journal.nyse`): S&P 500, VIX (CBOE follows NYSE), gold via the GLD ETF.
- TARGET business days: EUR/USD, because the ECB publishes one reference rate per TARGET day. They
  are weekdays except New Year's Day, Good Friday, Easter Monday, 1 May, 25 and 26 December.
"""

from __future__ import annotations

from datetime import date, timedelta

from tradehub.journal.nyse import _easter, is_session


def is_target_day(day: date) -> bool:
    if day.weekday() >= 5:
        return False
    easter = _easter(day.year)
    closed = {date(day.year, 1, 1), easter - timedelta(days=2), easter + timedelta(days=1),
              date(day.year, 5, 1), date(day.year, 12, 25), date(day.year, 12, 26)}
    return day not in closed


__all__ = ["is_session", "is_target_day"]
```

`tradehub/journal/daily.py`:

```python
"""Daily-direction plumbing for any family (v2 spec §8), generalising `spx.py` over calendar and source.

Target, exactly (same as the S&P): `<family>:<t>:up` is 1 iff the close of session t is strictly above
the previous session's close; unchanged is not up. t is the first session (in the family's calendar)
whose 08:00 CT freeze is still ahead, frozen inside `FREEZE_LEAD` of it. A close is usable only once
its exchange-local date is over (`closed_only`): a bar for "today" may be an intraday price, and
settling on it would grade a forecast against a number that later moves.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from tradehub.journal.contract import CalendarEntry, Settlement
from tradehub.journal.spx import CT, FREEZE_LEAD, HISTORY_DAYS, climatology_up, freeze_at, up_outcome

Fetch = Callable[[date], tuple[Mapping[date, float], str]]  # start -> (closes, exchange tz name)


@dataclass(frozen=True)
class DailySource:
    family: str
    source: str  # settlement source label, e.g. "fred:VIXCLS"
    fetch: Fetch
    is_session: Callable[[date], bool]


def daily_target(family: str, day: date) -> str:
    return f"{family}:{day.isoformat()}:up"


def target_day(target: str) -> date:
    return date.fromisoformat(target.split(":")[1])


def next_session(day: date, is_session: Callable[[date], bool]) -> date:
    while not is_session(day):
        day += timedelta(days=1)
    return day


def next_target_day(now: datetime, is_session: Callable[[date], bool]) -> date | None:
    day = next_session(now.astimezone(CT).date(), is_session)
    if freeze_at(day) <= now:
        day = next_session(day + timedelta(days=1), is_session)
    return day if freeze_at(day) - now <= FREEZE_LEAD else None


def closed_only(closes: Mapping[date, float], tz_name: str, now: datetime) -> dict[date, float]:
    """Drop bars dated today or later in the exchange's own time zone."""
    today = now.astimezone(ZoneInfo(tz_name)).date()
    return {d: v for d, v in closes.items() if d < today}


class DailyCloses:
    """One family's closes, fetched at most once per hourly run and shared by its forecasters."""

    def __init__(self, source: DailySource):
        self.source = source
        self._hour: datetime | None = None
        self._closes: dict[date, float] = {}

    def get(self, now: datetime) -> dict[date, float]:
        hour = now.astimezone(CT).replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            closes, tz_name = self.source.fetch(hour.date() - timedelta(days=HISTORY_DAYS))
            self._closes = closed_only(closes, tz_name, now)
            self._hour = hour
        return self._closes


def daily_entry(now: datetime, closes: DailyCloses) -> list[CalendarEntry]:
    day = next_target_day(now, closes.source.is_session)
    if day is None:
        return []
    return [CalendarEntry(daily_target(closes.source.family, day), closes.source.family, "daily", freeze_at(day),
                          climatology_prob=climatology_up(closes.get(now), day))]


def settle_daily(target: str, now: datetime, closes: DailyCloses) -> Settlement | None:
    day = target_day(target)
    data = closes.get(now)
    outcome = up_outcome(data, day) if closes.source.is_session(day) else None
    if outcome is None:
        return None
    return Settlement(target, outcome, closes.source.source, realized_value=data[day])
```

`tradehub/journal/forecasters/daily_direction.py`:

```python
"""Wave-2 daily-direction forecasters (v2 spec §8): VIX, gold, EUR/USD.

No new modelling pattern: each is the wave-1 walk-forward logistic (`tradehub/models/spy_direction`,
price-only features of its own closes, monthly refit on sessions before the month, hashed artifact)
pointed at a different series, and each is graded against climatology like the S&P.

Sources (all reachability-checked from the VPS on 2026-09-30; Stooq, the spec's source, is behind a
JavaScript proof-of-work wall and is not used):
    vix     FRED VIXCLS              NYSE sessions   settles when FRED posts the close (a day or two late)
    gold    Yahoo chart, GLD ETF     NYSE sessions   the ETF, not COMEX GC=F: a continuous futures
                                                     series jumps at each contract roll, which would
                                                     grade roll artefacts as "direction"
    eurusd  Frankfurter, ECB ref.    TARGET days     one reference rate per business day (~16:00 CET,
                                                     after the 08:00 CT freeze)
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tradehub.data.frankfurter import fetch_eurusd
from tradehub.data.fred_daily import fetch_fred_daily
from tradehub.data.yahoo_chart import fetch_chart
from tradehub.journal.calendars import is_target_day
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.daily import DailyCloses, DailySource, daily_entry, settle_daily, target_day
from tradehub.journal.nyse import is_session
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

STALE_DAYS = 6  # newest close older than this before the session -> a recorded gap, not a guess


def vix_source(fred=fetch_fred_daily) -> DailySource:
    return DailySource("vix", "fred:VIXCLS", lambda start: (fred("VIXCLS", start), "America/New_York"), is_session)


def gold_source(chart=fetch_chart) -> DailySource:
    return DailySource("gold", "yahoo:GLD", lambda start: chart("GLD", start), is_session)


def eurusd_source(rates=fetch_eurusd) -> DailySource:
    return DailySource("eurusd", "ecb:EURUSD", lambda start: (rates(start), "Europe/Berlin"), is_target_day)


class DirectionForecaster:
    cadence = "daily"

    def __init__(self, closes: DailyCloses, name: str, version: str, store: ArtifactStore | None = None):
        self._closes, self.name, self.version = closes, name, version
        self._family = closes.source.family
        self._store = store or ArtifactStore(namespace=f"{self._family}_direction")

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return daily_entry(now, self._closes)

    def _artifact_name(self, day: date) -> str:
        return f"{self._family}-dir-{day:%Y-%m}"

    def model_for(self, day: date, now: datetime) -> tuple[Artifact, str]:
        name = self._artifact_name(day)
        found = self._store.load(name)
        if found is not None:
            return found
        artifact = fit(*training_set(self._closes.get(now), before=day.replace(day=1)))
        return artifact, self._store.save(name, artifact)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        found = features_for(self._closes.get(now), day)
        if found is None or (day - found[1]) > timedelta(days=STALE_DAYS):
            return None
        row, newest = found
        artifact, digest = self.model_for(day, now)
        return Forecast(self.name, self.version, entry.target, artifact.predict(row),
                        payload={"features": row, "newest_close": newest.isoformat(), "artifact_sha256": digest,
                                 "train_end": artifact.train_end, "n_train": artifact.n_train,
                                 "source": self._closes.source.source})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_daily(target, now, self._closes)


def build_wave2(store_root=None) -> list[DirectionForecaster]:
    def store(family):
        return ArtifactStore(store_root, namespace=f"{family}_direction") if store_root else None

    return [
        DirectionForecaster(DailyCloses(vix_source()), "vix_direction", "vix-wf-v1", store("vix")),
        DirectionForecaster(DailyCloses(gold_source()), "gold_direction", "gold-wf-v1", store("gold")),
        DirectionForecaster(DailyCloses(eurusd_source()), "eurusd_direction", "eurusd-wf-v1", store("eurusd")),
    ]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_wave2.py -v`
Expected: 9 passed, including the registry test only after Task 2 (it is red until then, so 8 passed and 1 failed here).

- [ ] **Step 5: Commit**

```bash
git add tradehub/models/spy_direction/model.py tradehub/data/frankfurter.py tradehub/data/yahoo_chart.py tradehub/journal/calendars.py tradehub/journal/daily.py tradehub/journal/forecasters/daily_direction.py tests/test_journal_wave2.py
git commit -m "feat(journal): VIX, gold (GLD) and EUR/USD daily-direction forecasters"
```

---

### Task 2: Register the forecasters and verify

**Files:**
- Modify: `tradehub/journal/registry.py` (add the import and the `*build_wave2()` entry)

**Interfaces:**
- Produces: `FORECASTERS` gains the three wave-2 keys, all unique.

- [ ] **Step 1:** the registry test `test_the_registry_runs_wave_2_with_unique_keys_and_no_network` was written in Task 1 and is the one still failing. Run `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_wave2.py -k registry -v` → FAIL.

- [ ] **Step 2: Implement** — apply to `tradehub/journal/registry.py`:

```diff
diff --git a/tradehub/journal/registry.py b/tradehub/journal/registry.py
index de9d513..3240aac 100644
--- a/tradehub/journal/registry.py
+++ b/tradehub/journal/registry.py
@@ -10,6 +10,7 @@ from tradehub.core.kalshi_feed import fetch_market
 from tradehub.data.kalshi_live import KalshiLive
 from tradehub.journal.contract import Forecaster
 from tradehub.journal.forecasters.cpi import CpiForecaster
+from tradehub.journal.forecasters.daily_direction import build_wave2
 from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
 from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
 from tradehub.journal.forecasters.sentiment import SentimentMeter
@@ -37,4 +38,6 @@ FORECASTERS: list[Forecaster] = [
     SentimentMeter(_SPX),
     # plan (e): walk-forward quant (spec §7); same target and settlement as the meter
     SpyQuant(_SPX),
+    # wave 2 (spec §8): VIX, gold (GLD) and EUR/USD daily direction, same walk-forward model
+    *build_wave2(),
 ]
```

- [ ] **Step 3: Full verification**

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
.venv/bin/python -m ruff check tradehub/journal tradehub/data/frankfurter.py tradehub/data/yahoo_chart.py tests/test_journal_wave2.py
```
Expected: both runs all-pass (reviewer baseline 1393), ruff `All checks passed!`.

- [ ] **Step 4: Live smoke (paste the output in the PR)**

```bash
SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python - <<'EOF'
from datetime import date, datetime, UTC
from tradehub.journal.forecasters.daily_direction import gold_source, eurusd_source
from tradehub.journal.daily import closed_only
for s in (gold_source(), eurusd_source()):
    c, tz = s.fetch(date(2015, 1, 1))
    n = closed_only(c, tz, datetime.now(UTC))
    print(s.family, len(c), len(n), min(n), max(n), round(n[max(n)], 4))
EOF
```
Expected: gold ≈ 2950 closes ending yesterday; eurusd ≈ 3000 rates ending the last TARGET day. A 429 from Yahoo means the user agent was changed: fix it, do not add a fallback.

- [ ] **Step 5: Commit and open the PR** (`feat(journal): wave 2 daily-direction forecasters`)

```bash
git add tradehub/journal/registry.py
git commit -m "feat(journal): run the wave-2 daily-direction forecasters"
```
PR body: the three keys, the four deviations above, the VPS reachability check, verification output, "no migration needed". After merge the reviewer checks the first freezes (they start the morning after the deploy; each needs ≥ 500 training sessions, which all three sources provide).

## Self-Review

- **Spec §8:** VIX, gold and EUR/USD daily direction on "the same daily-cadence settle job as SPY; no new modeling pattern, just new targets": the same walk-forward model and target definition, per-family calendars (§6: "Wave-2 directionals use the same definition on their own session calendar"), and the tile source stated in `source` on every forecast row. Deviations (no Stooq, GLD, ECB) are listed for Kevin.
- **Correctness guards tested:** intraday bar never settles (`closed_only`), non-session and not-yet-posted closes never settle, TARGET vs NYSE calendars differ (US holiday, Good Friday), per-family artifact namespaces (a VIX fit can never load as the S&P's), honest user agent.
- **Type consistency:** `DailySource.fetch` returns `(closes, tz_name)` everywhere (`vix_source` wraps FRED with `America/New_York`, `eurusd_source` wraps rates with `Europe/Berlin`); target ids are `<family>:<YYYY-MM-DD>:up`.
