"""Labor through the journal (v2 spec §5): payrolls as-is, plus UNRATE and JOLTS-quits direction.

- `labor_nowcast` / `labor-v1`: the existing ridge payroll nowcast on every KXPAYROLLS strike, same
  math as `tradehub.scripts.scan.scan_labor`; Kalshi-linked, graded against the market.
- `unrate_direction` / `unrate-dir-v1`: P(UNRATE first print is up >= 0.1pp); frozen before the jobs
  release (the KXPAYROLLS close is the calendar); graded against climatology.
- `quits_direction` / `quits-dir-v1`: P(JOLTS quits first print is up); JOLTS has no market, so its
  cutoff is a conservative QUITS_CUTOFF_DAYS after the reference month (JOLTS lands ~35-40 days out).

All three settle against FRED first prints (vintages), never a consensus feed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from tradehub.data.alfred_vintages import Vintage, fetch_vintages
from tradehub.data.kalshi_live import LiveMarket
from tradehub.data.labor_inputs import (
    LaborInputs,
    cache_dir_from_env,
    feature_table,
    load_labor_inputs,
    payroll_nowcasts,
)
from tradehub.engines.labor import (
    LABOR_ENGINE_VERSION,
    PAYROLL_SERIES,
    TRAIN_START,
    add_months,
    first_prints,
    month_end,
    payroll_prob,
)
from tradehub.engines.labor_direction import (
    MIN_QUITS_SIGMA,
    MIN_UNRATE_SIGMA,
    QUITS_FEATURES,
    QUITS_UP,
    UNRATE_UP,
    DirectionNowcast,
    direction_nowcast,
    with_quits_feature,
)
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import entry_for, in_freeze_window, kalshi_target, quote_mid, settle_on_kalshi
from tradehub.markets import event_month

ET = ZoneInfo("America/New_York")
QUITS_CUTOFF_DAYS = 25  # earliest JOLTS release is ~30 days after the reference month ends
SETTLE_SEARCH_DAYS = 75  # daily vintages searched for a first print; after that the target stays open


def last_completed_month(now: datetime) -> date:
    today = now.astimezone(ET).date()
    return add_months(date(today.year, today.month, 1), -1)


def _months(first: date, last: date) -> list[date]:
    out, month = [], first
    while month <= last:
        out.append(month)
        month = add_months(month, 1)
    return out


def _target_month(target: str) -> date:
    return date.fromisoformat(target.split(":")[2] + "-01")


class LaborData:
    """The vintages all three labor forecasters read, fetched at most once per ET day and shared."""

    def __init__(self, load: Callable[..., LaborInputs] = load_labor_inputs,
                 fetch: Callable[..., dict[date, Vintage]] = fetch_vintages):
        self._load, self._fetch = load, fetch
        self._memo: dict[tuple[str, date], Any] = {}

    def _once(self, key: str, now: datetime, build: Callable[[], Any]) -> Any:
        slot = (key, now.astimezone(ET).date())
        if slot not in self._memo:
            self._memo = {k: v for k, v in self._memo.items() if k[1] == slot[1]}
            self._memo[slot] = build()
        return self._memo[slot]

    def inputs(self, now: datetime) -> LaborInputs:
        return self._once("inputs", now, lambda: self._load(
            first_month=TRAIN_START, last_month=last_completed_month(now), releases={},
            as_of=now.astimezone(ET).date(), unrate_from=TRAIN_START, with_adp=False))

    def quits(self, now: datetime) -> dict[date, Vintage]:
        today = now.astimezone(ET).date()
        days = [month_end(m) for m in _months(add_months(TRAIN_START, -1), last_completed_month(now))]
        return self._once("quits", now, lambda: self._fetch(
            "JTSQUL", days, cache_dir=cache_dir_from_env(), today=today))

    def first_print_change(self, series: str, month: date, now: datetime) -> float | None:
        """First-print change of `month` (vs m-1 in the same release), or None if not printed yet."""
        today = now.astimezone(ET).date()
        days = [d for k in range(SETTLE_SEARCH_DAYS) if (d := month_end(month) + timedelta(days=k)) < today]
        vintages = self._fetch(series, days, cache_dir=cache_dir_from_env(), today=today)
        return first_prints(vintages, change=True).get(month)


def unrate_nowcast(data: LaborData, month: date, now: datetime) -> DirectionNowcast | None:
    inputs = data.inputs(now)
    table = feature_table(inputs, _months(TRAIN_START, month), {})
    return direction_nowcast(table, first_prints(inputs.unrate, change=True), month,
                             threshold=UNRATE_UP, min_sigma=MIN_UNRATE_SIGMA)


def quits_nowcast(data: LaborData, month: date, now: datetime) -> DirectionNowcast | None:
    quits = data.quits(now)
    table = {}
    for m, feats in feature_table(data.inputs(now), _months(TRAIN_START, month), {}).items():
        augmented = with_quits_feature(feats, quits.get(month_end(m)))
        if augmented is not None:
            table[m] = augmented
    return direction_nowcast(table, first_prints(quits, change=True), month,
                             threshold=QUITS_UP, min_sigma=MIN_QUITS_SIGMA, features=QUITS_FEATURES)


def payroll_markets_by_month(live, now: datetime) -> dict[date, list[LiveMarket]]:
    """Open KXPAYROLLS markets inside the freeze lead whose reference month has ended."""
    out: dict[date, list[LiveMarket]] = {}
    for lm in live.open_markets(PAYROLL_SERIES):
        month = event_month(lm.market.event_ticker)
        if in_freeze_window(lm, now) and month_end(month) < now.astimezone(ET).date():
            out.setdefault(month, []).append(lm)
    return out


class PayrollsForecaster:
    name = "labor_nowcast"
    version = LABOR_ENGINE_VERSION
    cadence = "monthly"

    def __init__(self, live, fetch_market: Callable[[str], Any], data: LaborData, *,
                 nowcasts_fn: Callable[[list[date], datetime], dict] | None = None):
        self._live, self._fetch_market = live, fetch_market
        self._nowcasts_fn = nowcasts_fn or (lambda months, now: payroll_nowcasts(
            data.inputs(now), months, {}, train_from=TRAIN_START))
        self._open: dict[str, tuple[date, LiveMarket]] = {}
        self._nowcasts: dict | None = None

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._open = {kalshi_target(lm.market.ticker): (month, lm)
                      for month, lms in payroll_markets_by_month(self._live, now).items() for lm in lms}
        self._nowcasts = None
        return [entry_for(lm, "labor", self.cadence) for _, lm in self._open.values()]

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        if entry.target not in self._open:
            return None
        month, lm = self._open[entry.target]
        if self._nowcasts is None:
            self._nowcasts = self._nowcasts_fn(sorted({m for m, _ in self._open.values()}), now)
        nc = self._nowcasts.get(month)
        if nc is None:
            return None
        return Forecast(self.name, self.version, entry.target, payroll_prob(lm.market, nc.mu, nc.sigma),
                        market_prob=quote_mid(lm),
                        payload={"month": month.isoformat(), "mu_k": round(nc.mu, 2), "sigma_k": round(nc.sigma, 2),
                                 "n_train": nc.model.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class _DirectionForecaster:
    """Shared shape of the two direction forecasters; subclasses set identity and the calendar."""

    name: str
    version: str
    cadence = "monthly"
    series: str
    threshold: float
    kind: str

    def __init__(self, data: LaborData, *, nowcast_fn: Callable[[date, datetime], DirectionNowcast | None],
                 settle_fn: Callable[[date, datetime], float | None] | None = None):
        self._nowcast_fn = nowcast_fn
        self._settle_fn = settle_fn or (lambda month, now: data.first_print_change(self.series, month, now))
        self._nowcasts: dict[str, DirectionNowcast | None] = {}

    def target_for(self, month: date) -> str:
        return f"labor:{self.kind}:{month:%Y-%m}:up"

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        raise NotImplementedError

    def targets(self, now: datetime) -> list[CalendarEntry]:
        self._nowcasts = {}
        entries = []
        for month, cutoff in self._calendar(now).items():
            nc = self._nowcast_fn(month, now)
            self._nowcasts[self.target_for(month)] = nc
            entries.append(CalendarEntry(self.target_for(month), "labor", self.cadence, cutoff,
                                         climatology_prob=nc.climatology if nc else None))
        return entries

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        nc = self._nowcasts.get(entry.target)
        if nc is None:
            return None
        return Forecast(self.name, self.version, entry.target, nc.prob_up,
                        payload={"month": nc.month.isoformat(), "mu": round(nc.mu, 4), "sigma": round(nc.sigma, 4),
                                 "climatology": round(nc.climatology, 4), "n_train": nc.model.n_train,
                                 "coef": dict(zip(nc.model.features, nc.model.coef))})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        change = self._settle_fn(_target_month(target), now)
        if change is None:
            return None
        return Settlement(target, int(change > self.threshold), f"fred:{self.series}:first_print", realized_value=change)


class UnrateDirection(_DirectionForecaster):
    name, version, series, threshold, kind = "unrate_direction", "unrate-dir-v1", "UNRATE", UNRATE_UP, "unrate"

    def __init__(self, live, data: LaborData, **kwargs):
        kwargs.setdefault("nowcast_fn", lambda month, now: unrate_nowcast(data, month, now))
        super().__init__(data, **kwargs)
        self._live = live

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        # The jobs release is the cutoff; the payroll markets carry it (they close 5 minutes before).
        return {m: min(lm.market.close_time for lm in lms) for m, lms in payroll_markets_by_month(self._live, now).items()}


class QuitsDirection(_DirectionForecaster):
    name, version, series, threshold, kind = "quits_direction", "quits-dir-v1", "JTSQUL", QUITS_UP, "quits"

    def __init__(self, data: LaborData, **kwargs):
        kwargs.setdefault("nowcast_fn", lambda month, now: quits_nowcast(data, month, now))
        super().__init__(data, **kwargs)

    def _calendar(self, now: datetime) -> dict[date, datetime]:
        month = last_completed_month(now)
        cutoff = datetime.combine(month_end(month) + timedelta(days=QUITS_CUTOFF_DAYS), time(0), ET)
        return {month: cutoff} if now < cutoff else {}
