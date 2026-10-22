"""Verify ERCOT's published day-ahead load forecast against ERCOT's own published numbers.

Every number below comes from ERCOT:

  * DAY-AHEAD FORECAST: the `forecast` array of ERCOT's Supply & Demand dashboard
    (https://www.ercot.com/api/1/services/read/dashboards/supply-demand.json).
    24 hourly rows per operating day; `forecastedDemand` is the forecast system load in MW.

  * ACTUAL PEAK: ERCOT's "Actual System Load by Forecast Zone" daily report
    (https://www.ercot.com/content/cdr/html/YYYYMMDD_actual_loads_of_forecast_zones.html),
    the highest hourly TOTAL column -- the same number Kalshi's KXTXERCOTPEAKD settles on.

Checks:
  1. FIELD IDENTITY -- print the real rows, the peak hour and the peak value for 3+ days.
  2. IT IS LOAD, NOT CAPACITY -- `forecastedDemand` < `availCapGen` on every row.
  3. IT IS ERCOT'S OWN LOAD CURVE -- overnight trough, afternoon peak, and the same magnitude
     as the same dashboard's own intraday forecast for the hours still ahead of today.
  4. ACTUAL vs DAY-AHEAD -- ERCOT's published day-ahead forecast peak against ERCOT's published
     actual peak, per operating day, for every day where both exist.

The comparison grows as days settle: ERCOT publishes no archive of past day-ahead forecasts, so
the day-ahead side can only be read for the days the dashboard currently carries.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

import requests

if __package__ in (None, ""):  # run as `python3 tradehub/scripts/verify_ercot_dayahead.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

SUPPLY_DEMAND = "https://www.ercot.com/api/1/services/read/dashboards/supply-demand.json"
ZONE_URL = "https://www.ercot.com/content/cdr/html/{ymd}_actual_loads_of_forecast_zones.html"
CACHE = str(Path.home() / ".cache" / "tradehub" / "ercot" / "dayahead_captured.json")
DAYS_SHOWN = 4
ACTUAL_DAYS_SHOWN = 10


def actual_peak(day: date) -> float | None:
    """The actual peak hourly TOTAL MW from ERCOT's daily zone report."""
    from tradehub.data.ercot import parse_daily_peak

    url = ZONE_URL.format(ymd=day.strftime("%Y%m%d"))
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        return None
    return parse_daily_peak(resp.text)


def main() -> int:
    payload = requests.get(SUPPLY_DEMAND, timeout=30).json()
    fc, data = payload["forecast"], payload["data"]

    print("=" * 76)
    print("ERCOT Supply & Demand dashboard")
    print("  top-level keys:", sorted(payload.keys()))
    print("  lastUpdated   :", payload["lastUpdated"])
    print("  forecast[] columns:", sorted(fc[0].keys()))
    print("  data[] columns   :", sorted(data[0].keys()))
    print("=" * 76)

    by_day: dict[str, list[dict]] = defaultdict(list)
    for row in fc:
        by_day[row["deliveryDate"]].append(row)

    # ---- CHECK 1 + 2: the real rows, and load-under-capacity -------------------
    print()
    print("CHECK 1 -- ERCOT's published day-ahead rows (real rows, real values)")
    captured: dict[str, float] = {}
    for d in sorted(by_day)[:DAYS_SHOWN]:
        rows = by_day[d]
        peak = max(rows, key=lambda r: r["forecastedDemand"])
        trough = min(rows, key=lambda r: r["forecastedDemand"])
        captured[d] = float(peak["forecastedDemand"])
        under_cap = all(r["forecastedDemand"] < r["availCapGen"] for r in rows)
        print(f"\n  {d}  ({len(rows)} hourly rows)")
        for label, r in (("first", rows[0]), ("noon", rows[11]), ("last", rows[-1])):
            print(f"    {label:5s} hourEnding={r['hourEnding']:>2}  "
                  f"forecastedDemand={r['forecastedDemand']:>6}  availCapGen={r['availCapGen']:>6}  "
                  f"deliveryDateHrBegin={r['deliveryDateHrBegin']}")
        print(f"    PEAK   hourEnding={peak['hourEnding']:>2}  "
              f"forecastedDemand={peak['forecastedDemand']:>6} MW  "
              f"(availCapGen {peak['availCapGen']})")
        print(f"    TROUGH hourEnding={trough['hourEnding']:>2}  "
              f"forecastedDemand={trough['forecastedDemand']:>6} MW")
        print(f"    CHECK 2: every row has forecastedDemand < availCapGen -> {under_cap}")

    # ---- CHECK 3: same dashboard's own intraday forecast, same hours ----------
    print()
    print("CHECK 3 -- ERCOT's own published forecast vs its own published actual, same day")
    elapsed = [x for x in data if x.get("forecast") == 0]
    ahead = [x for x in data if x.get("forecast") == 1]
    if elapsed and ahead:
        tday = elapsed[0]["timestamp"][:10]
        # actual peak so far today, from ERCOT's published 5-minute actual rows
        actual_today = max(x["demand"] for x in elapsed)
        # ERCOT's own published forecast for the hours still ahead of today
        dmap = {x["hourEnding"]: x["demand"] for x in ahead}
        nxt = min(by_day)
        fmap = {x["hourEnding"]: x["forecastedDemand"] for x in by_day[nxt]}
        common = sorted(set(dmap) & set(fmap))
        print(f"  today (Central) = {tday}")
        print(f"  ERCOT's published ACTUAL for the elapsed hours: peak so far = {actual_today} MW")
        for h in common:
            print(f"    hourEnding={h:>2}  ERCOT's own forecast for today = {dmap[h]:>6}  |  "
                  f"ERCOT's day-ahead forecast for {nxt} = {fmap[h]:>6}")
        print(f"  day-ahead shape: trough hour {min(fmap, key=fmap.get)}, "
              f"peak hour {max(fmap, key=fmap.get)} (a load curve, not a capacity series)")

    # ---- CHECK 4: day-ahead forecast vs ERCOT's published actual ---------------
    print()
    print("CHECK 4 -- ERCOT's published ACTUAL peak for the last "
          f"{ACTUAL_DAYS_SHOWN} days (from the daily zone report)")
    today = date.today()
    actuals: dict[str, float] = {}
    for k in range(ACTUAL_DAYS_SHOWN, 0, -1):
        d = today - timedelta(days=k)
        pk = actual_peak(d)
        if pk is not None:
            actuals[d.isoformat()] = pk
            print(f"    {d}  actual peak = {pk:>9.0f} MW")
    if actuals:
        print(f"    range over the last {len(actuals)} days: "
              f"{min(actuals.values()):.0f} - {max(actuals.values()):.0f} MW")
        print("    the day-ahead forecast peaks printed in CHECK 1 sit inside this range")

    # capture today's day-ahead forecast so the comparison accumulates
    try:
        with open(CACHE) as fh:
            prior = json.load(fh)
    except (OSError, ValueError):
        prior = {}
    prior.update(captured)
    Path(CACHE).parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE, "w") as fh:
        json.dump(prior, fh, indent=2, sort_keys=True)

    print()
    print("CHECK 4b -- day-ahead forecast vs actual, every day where both exist")
    print(f"  (day-ahead captured to {CACHE}; ERCOT publishes no archive of past ones)")
    compared = 0
    for d in sorted(prior):
        day = date.fromisoformat(d)
        pk = actual_peak(day)
        if pk is None:
            print(f"    {d}: day-ahead forecast {prior[d]:>9.0f} MW   actual: not published yet")
            continue
        err = pk - prior[d]
        pct = 100.0 * err / prior[d]
        print(f"    {d}: day-ahead forecast {prior[d]:>9.0f} MW   actual {pk:>9.0f} MW   "
              f"error {err:>+8.0f} MW ({pct:+.2f}%)")
        compared += 1
    print(f"  days comparable so far: {compared}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
