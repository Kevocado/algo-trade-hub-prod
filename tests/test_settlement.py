import pytest

from tradehub import settlement


def test_compute_realized_pnl_long_winner():
    # 10 contracts bought at 55c, settled at $1.00, 10c total fees.
    assert settlement.compute_realized_pnl(10, 0.55, 1.0, fees_cents=10) == pytest.approx(4.40)


def test_compute_realized_pnl_short_loser():
    # Short 5 contracts at 40c, settles YES at $1.00: loss.
    assert settlement.compute_realized_pnl(-5, 0.40, 1.0) == pytest.approx(-3.00)


def test_compute_realized_pnl_zero_qty():
    assert settlement.compute_realized_pnl(0, 0.50, 1.0, fees_cents=7) == pytest.approx(-0.07)


def test_brier_score_perfect_and_worst():
    assert settlement.brier_score(1.0, 1) == pytest.approx(0.0)
    assert settlement.brier_score(0.0, 1) == pytest.approx(1.0)
    assert settlement.brier_score(0.7, 1) == pytest.approx(0.09)


def test_parse_market_result_finalized_yes():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "yes"}}) == ("SETTLED", 1)


def test_parse_market_result_finalized_no():
    assert settlement.parse_market_result({"market": {"status": "finalized", "result": "no"}}) == ("SETTLED", 0)


def test_parse_market_result_active_and_determined_are_open():
    for status in ("active", "determined", "paused", "unknown"):
        assert settlement.parse_market_result({"market": {"status": status, "result": None}}) == ("OPEN", None)


def test_parse_market_result_canceled_outcomes():
    for result in (None, "", "canceled"):
        payload = {"market": {"status": "finalized", "result": result}}
        assert settlement.parse_market_result(payload) == ("CANCELED", None)
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": None}}) is True
    assert settlement.is_market_canceled({"market": {"status": "finalized", "result": "yes"}}) is False


def test_parse_market_result_malformed_is_open_not_settled():
    for payload in ({}, {"market": None}, {"market": {"status": "finalized"}}, "nope", None):
        assert settlement.parse_market_result(payload) == ("OPEN", None)


def test_settle_prediction_row_settles_and_scores_both_briers():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": "yes"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["id"] == "abc"
    assert update["status"] == "SETTLED"
    assert update["result"] == "yes"
    assert update["brier"] == pytest.approx(0.09)
    assert update["market_brier"] == pytest.approx(0.25)


def test_settle_prediction_row_missing_market_prob_gives_null_market_brier():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": None}
    market = {"market": {"status": "finalized", "result": "no"}}
    update = settlement.settle_prediction_row(row, market)
    assert update["status"] == "SETTLED"
    assert update["result"] == "no"
    assert update["brier"] == pytest.approx(0.49)
    assert update["market_brier"] is None


def test_settle_prediction_row_open_market_returns_none():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    assert settlement.settle_prediction_row(row, {"market": {"status": "active", "result": None}}) is None


def test_settle_prediction_row_canceled_marks_canceled_without_fabricating_result():
    row = {"id": "abc", "our_prob": 0.7, "market_prob": 0.5}
    market = {"market": {"status": "finalized", "result": None}}
    update = settlement.settle_prediction_row(row, market)
    assert update == {"id": "abc", "status": "CANCELED"}
    assert "result" not in update and "brier" not in update


# --- I/O (Task 4) ---


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeQuery:
    def __init__(self, parent):
        self._parent = parent
        self._payload = None
        self._eq_id = None

    def select(self, *_a):
        return self

    def eq(self, col, val):
        # apply_prediction_settlement calls .update() before .eq("id", ...),
        # so the id is captured here and committed at execute() time.
        if col == "id":
            self._eq_id = val
        else:
            self._parent.filters.append((col, val))
        return self

    def update(self, payload):
        self._payload = payload
        return self

    def execute(self):
        if self._payload is not None:
            self._parent.updates.append({"id": self._eq_id, **self._payload})
            return _FakeResult(list(self._parent.updates))
        return _FakeResult([r for r in self._parent.rows if r["status"] == "OPEN"])


class _FakeSupaIO:
    def __init__(self, rows):
        self.rows = rows
        self.tables: list = []
        self.filters: list = []
        self.updates: list = []

    def table(self, name):
        self.tables.append(name)
        return _FakeQuery(self)


def _open_row(id_, ticker, our, market):
    return {"id": id_, "market_ticker": ticker, "our_prob": our, "market_prob": market, "status": "OPEN"}


def test_fetch_open_predictions_returns_only_open():
    supa = _FakeSupaIO([_open_row("a", "T1", 0.6, 0.5), {"id": "b", "status": "SETTLED"}])
    rows = settlement.fetch_open_predictions(supa)
    assert [r["id"] for r in rows] == ["a"]
    assert supa.filters == [("status", "OPEN")]


def test_run_settlement_pass_settles_finalized_and_skips_others():
    rows = [
        _open_row("a", "KXFINAL-YES", 0.7, 0.5),
        _open_row("b", "KXACTIVE", 0.6, 0.4),
        _open_row("c", "KXFINAL-CANCEL", 0.6, 0.4),
        _open_row("d", "KXUNKNOWN", 0.6, 0.4),
    ]
    markets = {
        "KXFINAL-YES": {"market": {"status": "finalized", "result": "yes"}},
        "KXACTIVE": {"market": {"status": "active", "result": None}},
        "KXFINAL-CANCEL": {"market": {"status": "finalized", "result": None}},
    }

    def fake_fetch(ticker):
        if ticker == "KXUNKNOWN":
            raise ValueError("404 Not Found")  # unknown ticker (or environment mismatch)
        return markets[ticker]

    supa = _FakeSupaIO(rows)
    summary = settlement.run_settlement_pass(supa, fake_fetch)
    assert summary == {"checked": 4, "settled": 1, "canceled": 1, "skipped": 2}
    statuses = {u["id"]: u["status"] for u in supa.updates}
    assert statuses == {"a": "SETTLED", "c": "CANCELED"}


def test_run_settlement_pass_is_idempotent():
    row = _open_row("a", "KXFINAL-YES", 0.7, 0.5)
    market = {"market": {"status": "finalized", "result": "yes"}}
    supa = _FakeSupaIO([row])
    first = settlement.run_settlement_pass(supa, lambda _t: market)
    assert first["settled"] == 1
    # Simulate the row flipping to SETTLED in the DB, as the real pass would.
    supa.rows = [{**row, "status": "SETTLED"}]
    supa.updates.clear()
    second = settlement.run_settlement_pass(supa, lambda _t: market)
    assert second == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
    assert supa.updates == []


def test_run_settlement_pass_no_open_predictions():
    supa = _FakeSupaIO([])
    summary = settlement.run_settlement_pass(supa, lambda _t: (_ for _ in ()).throw(AssertionError("must not fetch")))
    assert summary == {"checked": 0, "settled": 0, "canceled": 0, "skipped": 0}
