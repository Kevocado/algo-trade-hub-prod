import pytest

from tradehub import track_record


def _settled(id_, prob, market_prob, result):
    return {
        "id": id_,
        "our_prob": prob,
        "market_prob": market_prob,
        "result": result,
        "brier": (prob - (1 if result == "yes" else 0)) ** 2,
        "market_brier": None if market_prob is None else (market_prob - (1 if result == "yes" else 0)) ** 2,
        "status": "SETTLED",
    }


def test_bucketize_boundaries():
    assert track_record.bucketize(0.5) == "50-60"
    assert track_record.bucketize(0.599) == "50-60"
    assert track_record.bucketize(0.6) == "60-70"
    assert track_record.bucketize(1.0) == "90-100"


def test_compute_calibration_buckets():
    rows = [
        _settled("a", 0.55, 0.5, "yes"),
        _settled("b", 0.65, 0.6, "no"),
        _settled("c", 0.75, 0.7, "yes"),
        _settled("d", 0.75, 0.7, "no"),
    ]
    buckets = {b["bucket"]: b for b in track_record.compute_calibration(rows)}
    assert buckets["50-60"]["n"] == 1
    assert buckets["50-60"]["observed"] == pytest.approx(1.0)
    assert buckets["60-70"]["observed"] == pytest.approx(0.0)
    assert buckets["70-80"]["n"] == 2
    assert buckets["70-80"]["observed"] == pytest.approx(0.5)
    assert buckets["70-80"]["predicted"] == pytest.approx(0.75)


def test_compute_calibration_mirrors_no_favored_rows_into_confidence_space():
    # 0.30 means 70% confidence in NO. It resolves NO, so it is a hit in "70-80",
    # and it pools correctly with a YES-favored 0.75 row that resolved YES.
    rows = [_settled("a", 0.30, 0.5, "no"), _settled("b", 0.75, 0.5, "yes")]
    buckets = {b["bucket"]: b for b in track_record.compute_calibration(rows)}
    assert buckets["70-80"]["n"] == 2
    assert buckets["70-80"]["predicted"] == pytest.approx(0.725)
    assert buckets["70-80"]["observed"] == pytest.approx(1.0)


def test_compute_calibration_no_favored_miss():
    # 0.20 (80% confident NO) that resolves YES is a miss in "80-90".
    buckets = {b["bucket"]: b for b in track_record.compute_calibration([_settled("a", 0.20, 0.5, "yes")])}
    assert buckets["80-90"]["observed"] == pytest.approx(0.0)
    assert buckets["80-90"]["predicted"] == pytest.approx(0.80)


def test_compute_engine_summary_briers():
    rows = [_settled("a", 0.7, 0.5, "yes"), _settled("b", 0.8, 0.9, "no")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 2
    assert summary["brier_ours"] == pytest.approx((0.09 + 0.64) / 2)
    assert summary["brier_market"] == pytest.approx((0.25 + 0.81) / 2)


def test_compute_engine_summary_missing_market_brier_is_none():
    rows = [_settled("a", 0.7, None, "yes")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["brier_market"] is None


def _gate_kwargs(**overrides):
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    base = dict(engine="weather", cadence="daily", summary=summary, cal_buckets=cal, simulated_pnl_after_fees=50.0)
    base.update(overrides)
    return base


def test_gate_promotes_when_all_criteria_met():
    gate = track_record.check_promotion_gate(**_gate_kwargs())
    assert gate["status"] == "PROMOTED"
    assert gate["reasons"] == []


def test_gate_blocks_on_insufficient_contracts():
    rows = [_settled("a", 0.95, 0.6, "yes")]
    summary = track_record.compute_engine_summary(rows)
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate["status"] == "SHADOW"
    assert any("200" in r for r in gate["reasons"])


def test_gate_blocks_when_model_brier_not_below_market():
    gate = track_record.check_promotion_gate(**_gate_kwargs(simulated_pnl_after_fees=50.0))
    assert gate["status"] == "PROMOTED"  # sanity: base case promotes
    rows = [_settled(f"r{i}", 0.4, 0.9, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    gate2 = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate2["status"] == "SHADOW"
    assert any("Brier" in r for r in gate2["reasons"])


def test_gate_blocks_on_nonpositive_pnl_and_missing_market_brier():
    gate = track_record.check_promotion_gate(**_gate_kwargs(simulated_pnl_after_fees=0.0))
    assert gate["status"] == "SHADOW"
    rows = [_settled(f"r{i}", 0.95, None, "yes") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    gate2 = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=50.0,
    )
    assert gate2["status"] == "SHADOW"
    assert any("market" in r.lower() for r in gate2["reasons"])


def test_gate_blocks_on_calibration_miss_over_10pp():
    # 200 settled rows all predicted 0.95 but only half resolve yes -> 45pp miss.
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes" if i % 2 == 0 else "no") for i in range(200)]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary,
        cal_buckets=cal, simulated_pnl_after_fees=50.0,
    )
    assert gate["status"] == "SHADOW"
    assert any("calibration" in r.lower() for r in gate["reasons"])


class _PagedResult:
    def __init__(self, data):
        self.data = data


class _PagedQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters = {}
        self._range = (0, len(rows) - 1)

    def select(self, *_a):
        return self

    def eq(self, col, val):
        self._filters[col] = val
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        matched = [r for r in self._rows if all(r.get(k) == v for k, v in self._filters.items())]
        start, end = self._range
        return _PagedResult(matched[start:end + 1])


class _PagedSupa:
    def __init__(self, rows):
        self.rows = rows

    def table(self, name):
        assert name == "predictions"
        return _PagedQuery(self.rows)


def test_fetch_settled_rows_pages_past_the_1000_row_cap(monkeypatch):
    monkeypatch.setattr(track_record, "PAGE_SIZE", 3)
    rows = [{"id": f"r{i}", "engine": "weather", "status": "SETTLED"} for i in range(7)]
    rows += [{"id": "x", "engine": "weather", "status": "OPEN"}, {"id": "y", "engine": "gas", "status": "SETTLED"}]
    got = track_record.fetch_settled_rows(_PagedSupa(rows), "weather")
    assert [r["id"] for r in got] == [f"r{i}" for i in range(7)]


def test_gate_reports_worst_calibration_miss_across_all_buckets():
    cal = [
        {"bucket": "50-60", "n": 50, "predicted": 0.55, "observed": 0.70},  # 15pp miss
        {"bucket": "90-100", "n": 50, "predicted": 0.95, "observed": 0.60},  # 35pp miss
    ]
    summary = {"n_settled": 300, "brier_ours": 0.10, "brier_market": 0.20}
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=summary, cal_buckets=cal, simulated_pnl_after_fees=5.0,
    )
    assert gate["status"] == "SHADOW"
    assert gate["max_cal_dev"] == pytest.approx(0.35)
    assert sum("calibration" in r.lower() for r in gate["reasons"]) == 2


def test_gate_monthly_cadence_needs_only_50_contracts():
    rows = [_settled(f"r{i}", 0.95, 0.6, "yes") for i in range(50)]
    summary = track_record.compute_engine_summary(rows)
    gate = track_record.check_promotion_gate(
        engine="macro", cadence="monthly", summary=summary,
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=10.0,
    )
    assert gate["status"] == "PROMOTED"
