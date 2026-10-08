import gzip
import json
from datetime import UTC, datetime

from tradehub.scripts import record_orderbooks as ro

NOW = datetime(2026, 10, 8, 14, 0, tzinfo=UTC)


def _m(ticker, bid, ask, vol):
    return {"ticker": ticker, "event_ticker": ticker.split("-")[0], "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "volume_fp": vol, "close_time": "2026-10-09T00:00:00Z"}


class Api:
    def __init__(self, pages, fail=()):
        self.pages, self.fail, self.calls = pages, set(fail), []

    def __call__(self, url, params):
        self.calls.append((url, params))
        if url.endswith("/orderbook"):
            ticker = url.split("/")[-2]
            if ticker in self.fail:
                raise RuntimeError("500")
            return {"orderbook_fp": {"yes_dollars": [["0.03", "10"]], "no_dollars": []}}
        i = int((params or {}).get("cursor") or 0)
        return {"markets": self.pages[i], "cursor": str(i + 1) if i + 1 < len(self.pages) else ""}


def test_only_traded_markets_are_kept_and_only_extremes_get_depth():
    api = Api([[_m("A-1", "0.02", "0.04", "5"), _m("B-1", "0.45", "0.55", "9"), _m("C-1", "0.01", "0.03", "0")],
               [_m("D-1", "0.95", "0.97", "1")]])
    snap = ro.snapshot(NOW, api)
    assert [r["ticker"] for r in snap["top"]] == ["A-1", "B-1", "D-1"]
    assert [d["ticker"] for d in snap["depth"]] == ["A-1", "D-1"]
    assert snap["pages"] == 2 and snap["listed"] == 4 and snap["truncated"] is False
    first = api.calls[0][1]
    assert first["status"] == "open" and first["max_close_ts"] - first["min_close_ts"] == 3 * 86400


def test_a_run_out_of_time_says_truncated_rather_than_complete():
    ticks = iter([0.0, 0.0, 999.0, 999.0, 999.0])
    api = Api([[_m("A-1", "0.02", "0.04", "5")], [_m("B-1", "0.02", "0.04", "5")]])
    snap = ro.snapshot(NOW, api, clock=lambda: next(ticks), budget=10)
    assert snap["truncated"] is True and snap["pages"] == 1


def test_one_failed_book_is_counted_not_fatal():
    api = Api([[_m("A-1", "0.02", "0.04", "5"), _m("B-1", "0.96", "0.98", "5")]], fail={"A-1"})
    snap = ro.snapshot(NOW, api)
    assert snap["depth_failed"] == 1 and [d["ticker"] for d in snap["depth"]] == ["B-1"]


def test_no_quote_is_never_called_an_extreme():
    assert not ro.is_extreme({"yes_bid_dollars": None, "yes_ask_dollars": "0.03"})
    assert not ro.is_extreme({"yes_bid_dollars": "0.00", "yes_ask_dollars": "0.00"})
    assert ro.is_extreme({"yes_bid_dollars": "0.00", "yes_ask_dollars": "0.03"})


def test_the_file_is_one_gzip_jsonl_per_hour_with_meta_first(tmp_path):
    snap = ro.snapshot(NOW, Api([[_m("A-1", "0.02", "0.04", "5")]]))
    path = ro.write(snap, tmp_path, NOW)
    assert path == tmp_path / "2026-10-08" / "14.jsonl.gz"
    with gzip.open(path, "rt") as fh:
        lines = [json.loads(x) for x in fh.read().splitlines()]
    assert [x["kind"] for x in lines] == ["meta", "top", "depth"] and lines[0]["listed"] == 1
    assert not list(tmp_path.rglob("*.tmp"))
