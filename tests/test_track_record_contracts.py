import pytest

from tradehub import track_record


def _row(ticker, prob, market_prob, result, version="v1", id_=None):
    outcome = 1 if result == "yes" else 0
    return {
        "id": id_ or f"{ticker}-{prob}-{market_prob}",
        "market_ticker": ticker,
        "engine_version": version,
        "our_prob": prob,
        "market_prob": market_prob,
        "result": result,
        "brier": (prob - outcome) ** 2,
        "market_brier": (market_prob - outcome) ** 2,
        "status": "SETTLED",
    }


def test_hourly_repeats_of_one_market_count_as_one_contract():
    rows = [_row("KXHIGHNY-26SEP25-B72.5", 0.9, 0.6, "yes", id_=f"h{i}") for i in range(24)]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 1
    assert summary["n_rows"] == 24


def test_briers_weight_each_contract_equally():
    # Market A predicted 3 times (Brier 0.01 each), market B once (Brier 0.81).
    rows = [_row("A", 0.9, 0.5, "yes", id_=f"a{i}") for i in range(3)] + [_row("B", 0.9, 0.5, "no")]
    summary = track_record.compute_engine_summary(rows)
    assert summary["n_settled"] == 2
    assert summary["brier_ours"] == pytest.approx((0.01 + 0.81) / 2)
    assert summary["brier_market"] == pytest.approx(0.25)


def test_calibration_n_is_effective_contracts():
    rows = [_row("A", 0.95, 0.5, "yes", id_=f"a{i}") for i in range(4)] + [_row("B", 0.95, 0.5, "no")]
    (bucket,) = track_record.compute_calibration(rows)
    assert bucket["bucket"] == "90-100"
    assert bucket["n"] == pytest.approx(2.0)
    assert bucket["n_rows"] == 5
    assert bucket["observed"] == pytest.approx(0.5)  # A hit, B missed: one contract each


def test_thin_bucket_does_not_block_the_gate():
    # 199 contracts right at 0.95, one stray 0.55 miss (the case that blocked the step-2 gate).
    rows = [_row(f"M{i}", 0.95, 0.9, "yes") for i in range(199)] + [_row("STRAY", 0.55, 0.5, "no")]
    summary = track_record.compute_engine_summary(rows)
    cal = track_record.compute_calibration(rows)
    gate = track_record.check_promotion_gate(engine="weather", cadence="daily", summary=summary,
                                             cal_buckets=cal, simulated_pnl_after_fees=5.0)
    assert gate["status"] == "PROMOTED", gate["reasons"]
    assert any(b["bucket"] == "50-60" and b["n"] == 1 for b in cal)  # still reported


def test_full_bucket_miss_still_blocks_the_gate():
    rows = [_row(f"M{i}", 0.95, 0.9, "yes" if i % 2 else "no") for i in range(200)]
    gate = track_record.check_promotion_gate(
        engine="weather", cadence="daily", summary=track_record.compute_engine_summary(rows),
        cal_buckets=track_record.compute_calibration(rows), simulated_pnl_after_fees=5.0)
    assert gate["status"] == "SHADOW"
    assert any("calibration" in r for r in gate["reasons"])


class _Upserts:
    def __init__(self, rows):
        self.rows = rows
        self.upserts = []

    def table(self, name):
        self.name = name
        return self

    def select(self, *_a):
        return self

    def eq(self, *_a):
        return self

    def order(self, *_a, **_k):
        return self

    def range(self, start, end):
        self._slice = (start, end)
        return self

    def upsert(self, payload, on_conflict):
        self.upserts.append((payload, on_conflict))
        return self

    def execute(self):
        if self.name == "predictions":
            start, end = self._slice
            return type("R", (), {"data": self.rows[start:end + 1]})()
        return type("R", (), {"data": []})()


def test_refresh_writes_one_record_per_engine_version():
    rows = [_row("A", 0.9, 0.5, "yes", version="v1"), _row("B", 0.8, 0.5, "yes", version="v2"),
            _row("C", 0.7, 0.5, "no", version="v2")]
    supa = _Upserts(rows)
    out = track_record.refresh_track_record(supa, "weather", cadence="daily")
    assert [(p["engine_version"], p["n_settled"]) for p in out] == [("v1", 1), ("v2", 2)]
    assert {c for _, c in supa.upserts} == {"engine,engine_version"}


def test_refresh_preserves_the_scans_weather_engine_version():
    from tradehub.engines.weather import WEATHER_ENGINE_VERSION

    supa = _Upserts([_row("A", 0.9, 0.5, "yes", version=WEATHER_ENGINE_VERSION)])
    [payload] = track_record.refresh_track_record(supa, "weather", cadence="daily")
    assert payload["engine_version"] == WEATHER_ENGINE_VERSION


def test_backtest_rows_carry_their_market_ticker():
    from tradehub.backtest.metrics import prediction_row

    rows = [prediction_row(0.8, 0.5, "yes", market_ticker="A") for _ in range(5)]
    assert rows[0]["market_ticker"] == "A"
    assert track_record.compute_engine_summary(rows)["n_settled"] == 1
