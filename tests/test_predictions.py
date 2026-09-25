from datetime import UTC, datetime

import pytest

from tradehub import predictions


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeTable:
    def __init__(self, parent):
        self._parent = parent

    def insert(self, rows):
        rows = rows if isinstance(rows, list) else [rows]
        self._parent.inserts.extend(rows)
        return self

    def execute(self):
        return _FakeResult(list(self._parent.inserts))


class _FakeSupa:
    def __init__(self):
        self.inserts: list = []
        self.tables: list = []

    def table(self, name):
        self.tables.append(name)
        assert name == predictions.PREDICTIONS_TABLE
        return _FakeTable(self)


def _row(**overrides):
    base = {
        "market_ticker": "KXHIGHNY-25SEP26-T70",
        "our_prob": 0.62,
        "market_prob": 0.55,
        "engine": "weather",
        "as_of": datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return predictions.build_prediction_row(**base)


def test_build_prediction_row_happy_path():
    row = _row()
    assert row["market_ticker"] == "KXHIGHNY-25SEP26-T70"
    assert row["our_prob"] == pytest.approx(0.62)
    assert row["market_prob"] == pytest.approx(0.55)
    assert row["engine"] == "weather"
    assert row["engine_version"] == "v0"
    assert row["status"] == "OPEN"
    assert row["as_of"] == "2026-09-24T12:00:00+00:00"


def test_build_prediction_row_rejects_out_of_range_prob():
    with pytest.raises(ValueError):
        _row(our_prob=1.5)
    with pytest.raises(ValueError):
        _row(our_prob=-0.1)
    with pytest.raises(ValueError):
        _row(market_prob=2.0)


def test_build_prediction_row_allows_missing_market_prob():
    assert _row(market_prob=None)["market_prob"] is None


def test_build_prediction_row_rejects_empty_ticker_and_engine():
    with pytest.raises(ValueError):
        _row(market_ticker="  ")
    with pytest.raises(ValueError):
        _row(engine="")


def test_build_prediction_row_rounds_probs_to_4dp():
    assert _row(our_prob=0.123456)["our_prob"] == pytest.approx(0.1235)


def test_record_prediction_inserts_one_row():
    supa = _FakeSupa()
    row = _row()
    inserted = predictions.record_prediction(supa, row)
    assert supa.tables == ["predictions"]
    assert supa.inserts == [row]
    assert inserted == row


def test_record_predictions_empty_list_is_noop():
    supa = _FakeSupa()
    assert predictions.record_predictions(supa, []) == []
    assert supa.inserts == []
    assert supa.tables == []


def test_record_predictions_batch_inserts():
    supa = _FakeSupa()
    rows = [_row(), _row(market_ticker="KXAAAGAS-26SEP26-B3.50")]
    out = predictions.record_predictions(supa, rows)
    assert len(out) == 2
    assert supa.tables == ["predictions"]
