"""Naive baselines (spec §8 "naive baselines publish first so the journal has honest company",
§10 "with persistence shown beside it").

Every assertion here compares two DIFFERENT numbers or two different objects; nothing asserts only that
something was called.
"""

import random
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from journal_fakes import FakeJournalDB

from tradehub.journal.calendars import is_target_day
from tradehub.journal.daily import DailyCloses, DailySource, settle_daily
from tradehub.journal.forecasters.baselines import (
    BASELINE_PREFIX,
    DirectionBaseline,
    MonthlyBaseline,
    baseline_name,
    is_baseline,
    persistence_up,
)
from tradehub.journal.forecasters.daily_direction import DirectionForecaster
from tradehub.journal.forecasters.housing import HousingForecaster, add_months, target_for
from tradehub.journal.nyse import is_session
from tradehub.journal.runner import run_journal
from tradehub.journal.scoring import headline, score
from tradehub.journal.spx import freeze_at
from tradehub.models.spy_direction.model import ArtifactStore

ET = ZoneInfo("America/New_York")
VIX_SOURCE = "fred:VIXCLS"


def _closes(levels: dict[date, float]) -> DailyCloses:
    return DailyCloses(DailySource("vix", VIX_SOURCE, lambda start: (dict(levels), "America/New_York"), is_session))


def _baseline(closes: DailyCloses, kind: str, family: str = "vix") -> DirectionBaseline:
    return DirectionBaseline(closes, family, kind, is_session=is_session,
                             settle=lambda target, now: settle_daily(target, now, closes))


def _freeze_morning(day: date) -> datetime:
    """06:00 CT on `day`: inside the 05:00-08:00 CT window the daily families freeze in."""
    return datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=11)


def _next_session_after(day: date) -> date:
    while not is_session(day):
        day += timedelta(days=1)
    return day


def _walk(n=900, seed=5, start=date(2023, 1, 2)):
    """Random session closes: long enough for a walk-forward fit and for a five-year base rate."""
    rng, level, out, day = random.Random(seed), 100.0, {}, start
    while len(out) < n:
        if is_session(day):
            level *= 1.0 + rng.gauss(0.0002, 0.006)
            out[day] = level
        day += timedelta(days=1)
    return out


# A direction pattern with an exactly countable up-share: up, down, up, up, down, repeating.
_PATTERN = (1, -1, 1, 1, -1)


def _pattern_closes(n=900, start=date(2023, 1, 2)):
    level, out, day, i = 100.0, {}, start, 0
    while len(out) < n:
        if is_session(day):
            level += _PATTERN[i % 5]
            out[day] = level
            i += 1
        day += timedelta(days=1)
    return out


def _counted_up_share(n: int) -> float:
    """Hand-count: rising steps among the n-1 session-to-session transitions of the pattern."""
    rising = sum(1 for k in range(1, n) if _PATTERN[k % 5] > 0)
    return rising / (n - 1)


# ---------------------------------------------------------------- persistence


def test_persistence_repeats_the_previous_sessions_direction():
    day, thursday, friday = date(2026, 10, 5), date(2026, 10, 1), date(2026, 10, 2)
    up = persistence_up({thursday: 100.0, friday: 101.0}, day, is_session)
    down = persistence_up({thursday: 101.0, friday: 100.0}, day, is_session)
    assert up == (1.0, friday), up
    assert down == (0.0, friday), down


def test_persistence_skips_the_weekend_but_still_names_friday_as_the_previous_session():
    # Monday's previous session is Friday, three calendar days back. A calendar-day rule would call
    # this a gap and post no baseline at all on every Monday.
    thursday, friday, monday = date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5)
    assert persistence_up({thursday: 100.0, friday: 101.0}, monday, is_session) == (1.0, friday)


def test_persistence_records_a_gap_rather_than_guessing():
    day = date(2026, 10, 5)
    # Friday has not printed: the newest close is three sessions old, and its direction says nothing
    # about Friday's.
    assert persistence_up({date(2026, 9, 30): 100.0, date(2026, 10, 1): 101.0}, day, is_session) is None
    assert persistence_up({date(2026, 10, 2): 101.0}, day, is_session) is None   # no session before Friday
    assert persistence_up({}, day, is_session) is None
    # A close for the target day itself is invisible: the freeze happens before that close prints.
    assert persistence_up({date(2026, 10, 1): 100.0, date(2026, 10, 2): 101.0, date(2026, 10, 5): 1.0},
                          day, is_session) == (1.0, date(2026, 10, 2))
    # The same hole through the FORECASTER, not just the helper: no previous session, no forecast.
    thin = _closes({date(2026, 10, 2): 101.0})
    forecaster = _baseline(thin, "persistence")
    assert forecaster.forecast(forecaster.targets(_freeze_morning(day))[0], _freeze_morning(day)) is None


def test_persistence_uses_the_familys_own_calendar_not_the_new_york_one():
    """2026-07-03 is an ECB reference day and an NYSE holiday. Monday's previous session differs by
    family, and the two calendars here disagree about which way the last one went."""
    closes = {date(2026, 7, 1): 1.20, date(2026, 6, 30): 1.05, date(2026, 7, 2): 1.00, date(2026, 7, 3): 1.10}
    monday = date(2026, 7, 6)
    assert is_target_day(monday) and is_session(monday)
    assert not is_session(date(2026, 7, 3)) and is_target_day(date(2026, 7, 3))
    assert persistence_up(closes, monday, is_target_day) == (1.0, date(2026, 7, 3))   # Thu->Fri was up
    assert persistence_up(closes, monday, is_session) == (0.0, date(2026, 7, 2))      # Wed->Thu was down


# --------------------------------------------------------------- climatology


def test_climatology_is_the_long_run_base_rate_and_not_a_zero_or_one():
    levels = _pattern_closes()
    closes = _closes(levels)
    now = _freeze_morning(_next_session_after(max(levels) + timedelta(days=1)))
    climatology = _baseline(closes, "climatology")
    [entry] = climatology.targets(now)
    frozen = climatology.forecast(entry, now)
    assert frozen is not None
    # 900 sessions of a 5-step pattern, nothing clamped: the probability is the counted up-share.
    assert frozen.probability == pytest.approx(_counted_up_share(len(levels)))
    assert 0.5 < frozen.probability < 0.7
    persistence = _baseline(closes, "persistence").forecast(entry, now)
    assert persistence.probability in (0.0, 1.0) and persistence.probability != frozen.probability


def test_climatology_records_a_gap_without_a_full_window_of_sessions():
    levels = _walk(n=200)   # under the 253 changes climatology needs
    closes = _closes(levels)
    now = _freeze_morning(_next_session_after(max(levels) + timedelta(days=1)))
    climatology = _baseline(closes, "climatology")
    [entry] = climatology.targets(now)
    assert entry.climatology_prob is None      # no base rate exists, and the calendar says so
    assert climatology.forecast(entry, now) is None


# ------------------------------------------------ the full §3 contract, end to end


def test_a_baseline_freezes_in_the_models_own_window_and_settles_on_the_same_outcome(tmp_path):
    """Spec §8: "baselines implement the full §3 contract including freeze tests, no unscored
    decoration." Same calendar row, same freeze cutoff, same settlement, and a scorecard of its own."""
    levels = _walk()
    last = max(levels)
    day = _next_session_after(last + timedelta(days=1))
    levels[last] = levels[max(d for d in levels if d < last)] * 1.02   # Friday rose over Thursday
    levels[day] = levels[last] * 1.02                                    # and Monday rose over Friday
    published = {d: v for d, v in levels.items() if d < day}
    clock = [_freeze_morning(day)]
    closes = _closes(published)
    roster = [DirectionForecaster(closes, "vix_direction", "vix-wf-v1", ArtifactStore(tmp_path, "vix_direction")),
              _baseline(closes, "persistence"), _baseline(closes, "climatology")]
    model, persistence, climatology = roster
    keys = [f"{f.name}@{f.version}" for f in roster]
    db = FakeJournalDB(lambda: clock[0])

    out = run_journal(db, roster, clock[0])
    assert [out["forecasters"][k]["frozen"] for k in keys] == [1, 1, 1]
    target = f"vix:{day.isoformat()}:up"
    rows = {r["forecaster"]: r for r in db.tables["journal_forecasts"]}
    assert {r["target"] for r in rows.values()} == {target}            # one target, frozen by all three
    assert len(db.tables["journal_calendars"]) == 1                    # and ONE calendar row
    assert db.tables["journal_calendars"][0]["cutoff_at"] == freeze_at(day).isoformat()
    # Persistence: the previous session rose, so it freezes the certain answer, and says which session
    # it read. Climatology freezes the base rate and names its window.
    assert rows[persistence.name]["probability"] == 1.0
    assert rows[persistence.name]["payload"]["previous_session"] == (day - timedelta(days=1)).isoformat()
    assert 0.0 < rows[climatology.name]["probability"] < 1.0
    assert rows[climatology.name]["payload"]["kind"] == "climatology"

    published[day] = levels[day]                                      # the close is now public
    clock[0] = _freeze_morning(day + timedelta(days=1))
    run_journal(db, roster, clock[0])
    # Settlements are per TARGET, not per forecaster: one row, and all three cards read it.
    assert [s["target"] for s in db.tables["journal_settlements"]] == [target]
    assert db.tables["journal_settlements"][0]["outcome"] == 1
    cards = {c["forecaster"]: c for c in db.tables["journal_scores"]}
    assert {c["n_settled"] for c in cards.values()} == {1}            # scored, not decoration
    assert {c["baseline"] for c in cards.values()} == {"climatology"}
    # The runner hands `score` the forecaster's name, which is the only thing the never-promote rule
    # has to go on.
    assert cards[persistence.name]["gate_status"] == "SHADOW"
    assert any("naive baseline" in r for r in cards[persistence.name]["gate_reasons"])
    assert not any("naive baseline" in r for r in cards[model.name]["gate_reasons"])


def test_the_climatology_baseline_freezes_the_number_the_calendar_carries_and_scores_zero_against_it():
    """The calendar's `climatology_prob` IS the reference every non-market target is graded against. If
    these two drifted apart the baseline card would score positive skill against itself, which is the
    one thing a null hypothesis must never do.

    The residual is not zero and cannot be: `store.freeze` rounds the probability to 5dp and the
    calendar stores `climatology_prob` unrounded. That dust is exactly why `score` refuses to promote a
    baseline rather than relying on BSS happening to be 0.
    """
    levels = _walk()
    closes = _closes(levels)
    now = _freeze_morning(_next_session_after(max(levels) + timedelta(days=1)))
    climatology = _baseline(closes, "climatology")
    [entry] = climatology.targets(now)
    frozen = climatology.forecast(entry, now)
    assert frozen.probability == entry.climatology_prob
    row = {"target": entry.target, "probability": round(frozen.probability, 5), "market_prob": None,
           "rebuilt": False}
    calendar = {entry.target: {"climatology_prob": entry.climatology_prob}}
    card = score([row], {entry.target: 1}, calendar, "daily", forecaster=climatology.name)
    assert card["baseline"] == "climatology"
    assert abs(card["bss"]) < 1e-4
    assert card["gate_status"] == "SHADOW" and any("naive baseline" in r for r in card["gate_reasons"])


# --------------------------------------------------- never promoted, never evidence


def test_a_baseline_is_never_promoted_even_when_its_numbers_look_like_a_model():
    """200 calibrated daily targets and positive skill against climatology: every other reason the gate
    lists is clear. A baseline is still SHADOW, because "yesterday again" is not a forecast anyone should
    act on, and a PROMOTED card is counted in the hero's `promoted`."""
    rows = [{"target": f"vix:d{i:04d}:up", "probability": 0.95, "market_prob": None, "rebuilt": False}
            for i in range(200)]
    calendar = {r["target"]: {"climatology_prob": 0.53} for r in rows}
    settled = {r["target"]: 1 for r in rows}
    baseline = score(rows, settled, calendar, "daily", forecaster=baseline_name("persistence", "vix"))
    model = score(rows, settled, calendar, "daily", forecaster="vix_direction")
    assert model["gate_status"] == "PROMOTED", model["gate_reasons"]
    assert model["bss"] > 0 and baseline["bss"] == model["bss"]       # same rows, same skill
    assert baseline["gate_status"] == "SHADOW"
    assert any("baseline" in reason for reason in baseline["gate_reasons"])
    assert not any("baseline" in reason for reason in model["gate_reasons"])


def test_a_baseline_card_does_not_add_its_targets_to_the_headline():
    """`_independent` drops a card that shares its target set with another card. A baseline is exactly
    that: the same targets, and a null hypothesis rather than evidence about the future. It still
    appears in the list, like a `_cautious` copy does."""
    model = {"forecaster": "vix_direction", "calibration_ready": True, "n_targets": 200, "n_settled": 200,
             "gate_status": "SHADOW"}
    persistence = {"forecaster": baseline_name("persistence", "vix"), "calibration_ready": True,
                   "n_targets": 200, "n_settled": 200, "gate_status": "SHADOW"}
    climatology = {"forecaster": baseline_name("climatology", "vix"), "calibration_ready": True,
                   "n_targets": 200, "n_settled": 200, "gate_status": "SHADOW"}
    alone = headline([model])
    assert (alone["frozen_calibrated"], alone["settled_calibrated"], alone["forecasters"]) == (200, 200, 1)
    assert headline([model, persistence, climatology]) == {**alone, "forecasters": 3, "calibrated": 3}
    # The rule is the prefix, not "every card but the first": an unrelated model still counts.
    other = {**model, "forecaster": "housing_direction", "n_targets": 40, "n_settled": 40}
    assert headline([model, other])["settled_calibrated"] == 240


def test_the_baseline_prefix_is_one_constant_every_consumer_shares():
    assert baseline_name("persistence", "vix") == f"{BASELINE_PREFIX}persistence_vix"
    assert is_baseline(baseline_name("climatology", "housing"))
    assert not is_baseline("vix_direction") and not is_baseline("kalshi_implied_vix")


def test_a_baseline_kind_is_one_of_the_two_naive_ones(tmp_path):
    closes = _closes(_walk())
    for build in (lambda kind: DirectionBaseline(closes, "vix", kind, is_session=is_session,
                                                settle=lambda t, n: None),
                  lambda kind: MonthlyBaseline(_housing(_ramp(), tmp_path), kind)):
        with pytest.raises(ValueError, match="kind"):
            build("coin_flip")


def test_a_baseline_row_names_the_series_it_read(tmp_path):
    """The audit trail every other daily row carries: gold settles on the GLD ETF, not COMEX GC=F, and a
    baseline that does not say so is a number nobody can check."""
    levels = _walk()
    closes = _closes(levels)
    now = _freeze_morning(_next_session_after(max(levels) + timedelta(days=1)))
    for kind in ("persistence", "climatology"):
        fc = _baseline(closes, kind)
        payload = fc.forecast(fc.targets(now)[0], now).payload
        assert payload["source"] == VIX_SOURCE and payload["kind"] == kind
    fc = _housing(_monthly_levels(), tmp_path)
    persistence = MonthlyBaseline(fc, "persistence")
    assert persistence.forecast(persistence.targets(NOW)[0], NOW).payload["source"] == "fred:CSUSHPISA:first_print"


# ----------------------------------------------------------------- housing (monthly)


def _housing(levels, tmp_path, vintages=None):
    return HousingForecaster(levels_fn=lambda start: dict(levels), vintages_fn=lambda *a, **k: (vintages or {}),
                             store=ArtifactStore(tmp_path, "housing_direction"))


def test_the_housing_baselines_reuse_the_models_fetch_rather_than_pulling_the_series_again(tmp_path):
    """Three forecasters reading one series: `HousingForecaster.targets` refetches once per run, and the
    two baselines must read that memo. A `history()` that refetched would triple an hourly HTTP call for
    the same numbers."""
    calls = []

    def levels_fn(start):
        calls.append(start)
        return dict(_monthly_levels())

    fc = HousingForecaster(levels_fn=levels_fn, vintages_fn=lambda *a, **k: {},
                           store=ArtifactStore(tmp_path, "housing_direction"))
    roster = [fc, MonthlyBaseline(fc, "persistence"), MonthlyBaseline(fc, "climatology")]
    for f in roster:
        for entry in f.targets(NOW):
            f.forecast(entry, NOW)
    assert len(calls) == 1, f"{len(calls)} level fetches for one run"


def _monthly_levels(last=date(2026, 6, 1)):
    levels, month, i = {}, date(1987, 1, 1), 0
    while month <= last:
        levels[month] = 60.0 + 0.004 * i + (0.01 if i % 3 == 0 else 0.0)
        month, i = add_months(month, 1), i + 1
    return levels


NOW = datetime(2026, 9, 25, 12, tzinfo=ET)     # inside the five days before the 09-29 release
JULY = date(2026, 7, 1)


def entry_for(month: date):
    """A calendar row for a month the data cannot produce on its own, exactly as `test_journal_housing`
    does: with June missing, `targets()` moves the month instead of naming the stale one."""
    return type("E", (), {"target": target_for(month)})()


def test_housing_baselines_freeze_the_model_own_month_with_its_own_climatology(tmp_path):
    levels = _monthly_levels()
    fc = _housing(levels, tmp_path)
    persistence, climatology = MonthlyBaseline(fc, "persistence"), MonthlyBaseline(fc, "climatology")
    assert target_for(add_months(max(levels), 1)) == "housing:2026-07:up"
    assert [e.target for e in persistence.targets(NOW)] == ["housing:2026-07:up"]
    assert climatology.targets(NOW) == persistence.targets(NOW)      # the same row, so one is enough

    entry = persistence.targets(NOW)[0]
    up, clim = persistence.forecast(entry, NOW), climatology.forecast(entry, NOW)
    assert up is not None and up.probability == 1.0                  # June's level beat May's
    assert clim is not None and 0.5 < clim.probability < 0.9
    assert up.probability != clim.probability
    assert entry.climatology_prob == pytest.approx(clim.probability)


def _ramp():
    """Monotone monthly levels from 2024-01 through 2026-06, the last month before the target."""
    return {add_months(date(2024, 1, 1), i): 100.0 + i for i in range(30)}


def test_housing_persistence_repeats_the_previous_month_and_is_a_gap_without_it(tmp_path):
    levels = _ramp()
    rising = MonthlyBaseline(_housing(levels, tmp_path), "persistence")
    assert rising.forecast(rising.targets(NOW)[0], NOW).probability == 1.0
    falling_levels = {**levels, date(2026, 4, 1): 140.0, date(2026, 5, 1): 130.0, date(2026, 6, 1): 120.0}
    falling = MonthlyBaseline(_housing(falling_levels, tmp_path), "persistence")
    assert falling.forecast(falling.targets(NOW)[0], NOW).probability == 0.0
    # June never printed, so the series' newest month is May and July's previous month is missing.
    holed = MonthlyBaseline(_housing({m: v for m, v in levels.items() if m < date(2026, 6, 1)}, tmp_path),
                            "persistence")
    assert holed.forecast(entry_for(JULY), NOW) is None


def test_a_housing_baseline_never_forecasts_a_month_that_is_already_published(tmp_path):
    levels = _monthly_levels()
    out = {**levels, JULY: levels[max(levels)]}     # July is already out, and there IS a base rate
    entry = entry_for(JULY)
    assert MonthlyBaseline(_housing(out, tmp_path), "persistence").forecast(entry, NOW) is None
    assert MonthlyBaseline(_housing(out, tmp_path), "climatology").forecast(entry, NOW) is None


def test_a_housing_baseline_records_a_gap_rather_than_a_short_history_base_rate(tmp_path):
    levels = _ramp()   # 30 months: too few month-over-month changes for a base rate
    climatology = MonthlyBaseline(_housing(levels, tmp_path), "climatology")
    assert [e.climatology_prob for e in climatology.targets(NOW)] == [None]
    assert climatology.forecast(climatology.targets(NOW)[0], NOW) is None


# ------------------------------------------------------------------- the registry


def test_the_registry_publishes_both_baselines_for_every_non_market_direction_family():
    from tradehub.journal.registry import FORECASTERS

    forecasters = list(FORECASTERS)
    keys = [(f.name, f.version) for f in forecasters]
    assert len(set(keys)) == len(keys), "(name, version) is the journal key"
    families = {"spx", "vix", "gold", "eurusd", "housing"}
    assert {baseline_name(k, f) for k in ("persistence", "climatology") for f in families} <= {n for n, _ in keys}
    by_name = {f.name: f for f in forecasters}
    assert by_name[baseline_name("persistence", "vix")].cadence == by_name["vix_direction"].cadence == "daily"
    assert by_name[baseline_name("climatology", "housing")].cadence == by_name["housing_direction"].cadence
    # The baselines read the SAME closes/history objects as the models they price. That is what makes
    # the climatology number they freeze identical to the one the calendar carries.
    assert by_name[baseline_name("persistence", "vix")]._closes is by_name["vix_direction"]._closes
    assert by_name[baseline_name("climatology", "spx")]._closes is by_name["spy_quant"]._closes
    assert by_name[baseline_name("persistence", "housing")]._housing is by_name["housing_direction"]
    # Each family keeps its own calendar: EUR/USD follows the ECB reference days, not the NYSE.
    eurusd = by_name["eurusd_direction"]._closes.source.is_session
    assert by_name[baseline_name("persistence", "eurusd")]._is_session is eurusd is is_target_day