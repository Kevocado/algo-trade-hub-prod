from datetime import UTC, datetime

import pytest

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.scoring import MIN_BUCKET_TARGETS, murphy, reliability, score, settled_pairs


def _row(target, prob, market=None, rebuilt=False, quote=None):
    row = {"target": target, "probability": prob, "market_prob": market, "rebuilt": rebuilt}
    if quote is not None:
        row["payload"] = {"yes_bid": quote[0], "yes_ask": quote[1]}
    return row


def test_contract_rejects_naive_times_and_bad_values():
    with pytest.raises(ValueError, match="timezone-aware"):
        CalendarEntry("t", "fam", "daily", datetime(2026, 10, 1, 8))  # noqa: DTZ001
    with pytest.raises(ValueError, match="cadence"):
        CalendarEntry("t", "fam", "hourly", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="probability"):
        Forecast("f", "v1", "t", 1.2)
    with pytest.raises(ValueError, match="outcome"):
        Settlement("t", 2, "src")


def test_source_hash_is_stable_and_input_sensitive():
    a = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 2})
    b = Forecast("f", "v1", "t", 0.6, payload={"y": 2, "x": 1})
    c = Forecast("f", "v1", "t", 0.6, payload={"x": 1, "y": 3})
    assert a.source_hash == b.source_hash != c.source_hash


def test_rebuilt_and_unsettled_rows_are_never_counted():
    rows = [_row("a", 0.9), _row("b", 0.9, rebuilt=True), _row("c", 0.9)]
    pairs = settled_pairs(rows, {"a": 1, "b": 1})
    assert [p["target"] for p in pairs] == ["a"]
    card = score(rows, {"a": 1, "b": 1}, {}, "daily")
    assert card["n_targets"] == 2 and card["n_settled"] == 1


def test_bss_uses_market_where_it_exists_else_climatology():
    rows = [_row("m", 0.8, market=0.6), _row("c", 0.7)]
    cal = {"c": {"climatology_prob": 0.5}}
    card = score(rows, {"m": 1, "c": 1}, cal, "daily")
    ours = ((0.8 - 1) ** 2 + (0.7 - 1) ** 2) / 2
    base = ((0.6 - 1) ** 2 + (0.5 - 1) ** 2) / 2
    assert card["bss"] == pytest.approx(1 - ours / base, abs=1e-6)
    assert card["baseline"] == "market"


def test_a_target_with_no_baseline_is_scored_but_excluded_from_bss():
    card = score([_row("x", 0.9)], {"x": 1}, {}, "daily")
    assert card["brier"] == pytest.approx(0.01)
    assert card["bss"] is None and card["baseline"] == "none"
    assert "no baseline" in " ".join(card["gate_reasons"])


def test_gate_counts_monthly_at_50_and_daily_at_200():
    rows = [_row(f"t{i}", 0.9, market=0.6) for i in range(60)]
    settle = {f"t{i}": 1 for i in range(60)}
    monthly = score(rows, settle, {}, "monthly")
    daily = score(rows, settle, {}, "daily")
    assert not any("settled targets" in r for r in monthly["gate_reasons"])
    assert any("need 200" in r for r in daily["gate_reasons"])


def test_promotion_needs_positive_skill_and_calibrated_buckets():
    good = [_row(f"g{i}", 0.95, market=0.6, quote=(0.58, 0.62)) for i in range(MIN_BUCKET_TARGETS * 3)]
    card = score(good, {r["target"]: 1 for r in good}, {}, "monthly")
    assert card["calibration_ready"] and card["bss"] > 0
    assert card["gate_status"] == "PROMOTED", card["gate_reasons"]
    worse = [_row(f"w{i}", 0.6, market=0.95) for i in range(60)]
    card = score(worse, {r["target"]: 1 for r in worse}, {}, "monthly")
    assert card["gate_status"] == "SHADOW" and any("not positive" in r for r in card["gate_reasons"])


def test_reliability_is_confidence_space_and_murphy_adds_up():
    pairs = [{"probability": 0.3, "outcome": 0}, {"probability": 0.7, "outcome": 1},
             {"probability": 0.7, "outcome": 0}, {"probability": 0.2, "outcome": 0}]
    buckets = {b["bucket"]: b for b in reliability(pairs)}
    assert buckets["70-80"]["n"] == 3  # 0.3 and both 0.7s
    m = murphy(pairs)
    brier = sum((p["probability"] - p["outcome"]) ** 2 for p in pairs) / len(pairs)
    # Binned Murphy is exact when every bin holds a single forecast value, as here.
    assert m["reliability"] - m["resolution"] + m["uncertainty"] == pytest.approx(brier, abs=1e-6)


def test_a_market_forecaster_with_no_frozen_quotes_cannot_promote():
    rows = [_row(f"g{i}", 0.95, market=0.6) for i in range(MIN_BUCKET_TARGETS * 3)]
    card = score(rows, {r["target"]: 1 for r in rows}, {}, "monthly")
    assert card["bss"] > 0 and card["gate_status"] == "SHADOW"
    assert any("no frozen quotes" in r for r in card["gate_reasons"])
    assert card["costs"]["n_quoted"] == 0


def test_skill_that_fees_and_spread_eat_does_not_promote():
    # Forecast 0.75 against a 0.60 mid, with a wide 50/70 book. At a 70% hit rate the Brier skill vs
    # the market is positive (it beats 0.60 whenever the hit rate is above 0.675), but buying at the
    # 70c ask plus a 2c fee needs a 72% hit rate to break even: the edge exists only before costs.
    rows = [_row(f"t{i}", 0.75, market=0.60, quote=(0.50, 0.70)) for i in range(60)]
    settle = {r["target"]: int(i < 42) for i, r in enumerate(rows)}
    card = score(rows, settle, {}, "monthly")
    assert card["bss"] > 0 and card["costs"]["n_traded"] == 60
    assert card["costs"]["net_pnl_cents"] == pytest.approx(42 * (30 - 2) + 18 * (-70 - 2))  # -100
    assert card["gate_status"] == "SHADOW" and any("after fees and spread" in r for r in card["gate_reasons"])


def test_climatology_baselines_carry_no_cost_block():
    rows = [_row(f"c{i}", 0.9) for i in range(5)]
    card = score(rows, {r["target"]: 1 for r in rows}, {r["target"]: {"climatology_prob": 0.5} for r in rows}, "daily")
    assert card["baseline"] == "climatology" and card["costs"] == {}
