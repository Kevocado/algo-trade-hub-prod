import random
from datetime import UTC, date, datetime, timedelta

import pytest

from tradehub.journal.contract import CalendarEntry
from tradehub.journal.forecasters.spy_quant import SpyQuant
from tradehub.journal.nyse import is_session
from tradehub.journal.spx import SpxCloses, freeze_at, spx_target
from tradehub.models.spy_direction.features import features_for
from tradehub.models.spy_direction.model import ArtifactStore


def _trend_closes(n=900, seed=3):
    rng = random.Random(seed)
    level, out, day = 4000.0, {}, date(2023, 1, 3)
    while len(out) < n:
        if is_session(day):
            level *= 1.0 + rng.gauss(0.0004, 0.01)
            out[day] = level
        day += timedelta(days=1)
    return out


def test_features_use_only_closes_before_the_session():
    closes = _trend_closes()
    day = max(closes)
    row, newest = features_for(closes, day)
    assert newest < day
    bumped = dict(closes) | {day: closes[day] * 2}  # the session's own close must not move anything
    assert features_for(bumped, day)[0] == row


def test_monthly_artifact_is_trained_before_the_month_and_hash_checked(tmp_path):
    closes = _trend_closes()
    last = max(closes)
    now = datetime.combine(last, datetime.min.time(), UTC) + timedelta(hours=11)
    store = ArtifactStore(tmp_path)
    fc = SpyQuant(SpxCloses(fetch=lambda s, start: {d: v for d, v in closes.items() if d < last}), store)
    artifact, digest = fc.model_for(last, now)
    assert artifact.train_end < last.replace(day=1).isoformat()  # never trained on the scored month
    assert fc.model_for(last, now)[1] == digest  # the month's artifact is written once, then reused
    path = store.dir / f"spy-dir-{last:%Y-%m}.json"
    path.write_text(path.read_text().replace('"n_train"', '"n_train" ', 1))
    with pytest.raises(ValueError, match="manifest"):
        store.load(f"spy-dir-{last:%Y-%m}")


def test_quant_forecast_records_its_artifact(tmp_path):
    closes = _trend_closes()
    last = max(closes)
    fc = SpyQuant(SpxCloses(fetch=lambda s, start: {d: v for d, v in closes.items() if d < last}),
                  ArtifactStore(tmp_path))
    now = freeze_at(last) - timedelta(hours=1)
    forecast = fc.forecast(CalendarEntry(spx_target(last), "spx", "daily", freeze_at(last)), now)
    assert 0.0 < forecast.probability < 1.0
    assert len(forecast.payload["artifact_sha256"]) == 64 and forecast.payload["n_train"] >= 500


def test_the_registry_runs_the_quant_on_the_meters_closes():
    from tradehub.journal.registry import FORECASTERS

    by_key = {(f.name, f.version): f for f in FORECASTERS}
    quant, meter = by_key[("spy_quant", "spy-wf-v1")], by_key[("sentiment_meter", "meter-v1")]
    assert quant._closes is meter._closes  # one FRED fetch per run serves both, and one settlement truth
