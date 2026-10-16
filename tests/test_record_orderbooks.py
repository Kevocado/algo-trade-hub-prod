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


def test_prune_removes_only_whole_days_older_than_the_retention(tmp_path):
    (tmp_path / "2026-08-01").mkdir()      # 68 days old -> removed
    (tmp_path / "2026-09-01").mkdir()      # 37 days old -> kept
    (tmp_path / "2026-10-08").mkdir()      # the day being written -> kept
    (tmp_path / "not-a-date").mkdir()      # not a date -> left alone
    (tmp_path / "loose.txt").write_text("x")
    (tmp_path / "2026-08-01" / "12.jsonl.gz").write_text("old")

    assert ro.prune(tmp_path, NOW) == ["2026-08-01"]

    assert not (tmp_path / "2026-08-01").exists()
    for kept in ("2026-09-01", "2026-10-08", "not-a-date"):
        assert (tmp_path / kept).is_dir()
    assert (tmp_path / "loose.txt").exists()


def test_prune_on_a_missing_root_is_a_no_op(tmp_path):
    assert ro.prune(tmp_path / "nope", NOW) == []


def test_a_successful_run_prunes_and_reports_what_it_deleted(tmp_path, capsys, monkeypatch):
    old = tmp_path / "2026-08-01"
    old.mkdir()
    (old / "12.jsonl.gz").write_text("old")
    monkeypatch.setattr(
        ro, "datetime",
        type("Fixed", (datetime,), {"now": classmethod(lambda cls, tz=None: NOW)}),
    )
    monkeypatch.setattr(
        ro, "snapshot",
        lambda now, get: {"as_of": now.isoformat(), "pages": 1, "listed": 1, "truncated": False,
                          "top": [_m("A-1", "0.02", "0.04", "5")], "depth": [], "depth_failed": 0},
    )

    assert ro.main(["--root", str(tmp_path)]) == 0
    out = json.loads(capsys.readouterr().out)

    assert out["pruned"] == ["2026-08-01"] and out["retention_days"] == 60
    assert not old.exists()
    assert (tmp_path / "2026-10-08" / "14.jsonl.gz").exists()
