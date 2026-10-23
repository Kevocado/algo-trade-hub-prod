"""Sports predictors' records: adapters against the real live bodies, and a fail-soft endpoint.

Fixtures in tests/fixtures/sports_record/ are the live responses (checked 2026-10-23), with every list
cut to five rows and every key kept. Expected numbers are copied from them, not computed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradehub import sports_record as sr
from tradehub.api import main

FIX = Path(__file__).parent / "fixtures" / "sports_record"


def body(sport: str):
    return json.loads((FIX / f"{sport}.json").read_text(encoding="utf-8"))


def by(rows, market):
    return next(r for r in rows if r["market"] == market)


def test_nfl_rows_carry_the_all_picks_figure_and_the_pre_kickoff_subset():
    rows = sr.adapt_nfl(body("nfl"))
    assert [r["label"] for r in rows] == ["Winner", "Spread", "Total"]
    win = by(rows, "moneyline")
    assert (win["n"], win["hit_rate"], win["n_pre"], win["hit_rate_pre"]) == (94, 0.5851063829787234, 61, 0.5901639344262295)
    assert by(rows, "total")["hit_rate"] == 0.4148936170212766
    assert all(r["vs_market"] is None for r in rows)  # the Kalshi comparison is the journal's, not this adapter's


def test_cfb_uses_its_one_resolved_count_for_all_three_markets():
    rows = sr.adapt_cfb(body("cfb"))
    win = by(rows, "moneyline")
    assert (win["n"], win["hit_rate"], win["n_pre"], win["hit_rate_pre"]) == (517, 0.7562862669245648, 256, 0.6796875)
    assert by(rows, "spread")["n"] == 517


def test_nba_keeps_only_the_markets_a_kalshi_price_exists_for():
    rows = sr.adapt_nba(body("nba"))
    assert [r["market"] for r in rows] == ["h2h", "spread", "total"]  # not game_outcome (1,469) or player_props (125,500)
    h2h = by(rows, "h2h")
    assert (h2h["n"], h2h["hit_rate"], h2h["n_pre"], h2h["hit_rate_pre"]) == (43, 0.535, 42, 0.548)


def test_pl_reads_the_summary_and_its_pre_kickoff_block():
    rows = sr.adapt_pl(body("pl"))
    res = by(rows, "match_result")
    assert (res["label"], res["n"], res["hit_rate"], res["n_pre"], res["hit_rate_pre"]) == ("Result", 70, 0.5142857142857142, 20, 0.5)


def test_f1_is_one_honest_summary_row_not_a_hit_rate():
    (row,) = sr.adapt_f1(body("f1"))
    assert (row["label"], row["n"], row["n_pre"], row["hit_rate"]) == ("All markets", 2420, 1364, None)
    assert "Brier" in row["note"]


@pytest.mark.parametrize("sport", sr.SPORTS)
def test_a_missing_key_is_none_never_zero_and_an_empty_body_is_no_rows(sport):
    rows = sr.ADAPTERS[sport]({})
    assert all(r["n"] is None and r["hit_rate"] is None and r["n_pre"] is None for r in rows)
    assert len(rows) == {"nfl": 3, "cfb": 3, "f1": 1}.get(sport, 0)  # empty bodies: NFL/CFB show three empty markets, F1 one


def test_one_sport_failing_marks_only_that_sport_unavailable():
    def fetch(url):
        if "/hub/track-record" in url:
            raise TimeoutError("slow")
        return {}

    out = sr.collect(fetch=fetch, now=lambda: 1.0e9)
    status = {s["sport"]: s["status"] for s in out["sports"]}
    assert status["nba"] == "unavailable" and status["nfl"] == "ok" and status["f1"] == "ok"
    assert [s["sport"] for s in out["sports"]] == list(sr.SPORTS)


def test_a_non_json_page_is_unavailable_not_a_crash():
    def fetch(url):
        raise ValueError("Expecting value")  # what `.json()` raises on the NBA site's HTML page

    assert sr.sport_record("nba", fetch)["status"] == "unavailable"
    assert sr.sport_record("nba", lambda url: "<!doctype html>")["status"] == "unavailable"


def test_a_good_answer_is_cached_for_five_minutes_and_a_failure_is_not():
    sr._cache.clear()
    calls = []

    def fetch(url):
        calls.append(url)
        if "/api/hub/track-record" in url:
            raise TimeoutError
        return {}

    sr.collect(fetch=fetch, now=lambda: 100.0)
    first = len(calls)
    sr.collect(fetch=fetch, now=lambda: 200.0)  # 100 s later: the four good sports come from the cache
    assert len(calls) == first + 1 and "/api/hub/track-record" in calls[-1]  # only the failed one is retried
    sr.collect(fetch=fetch, now=lambda: 100.0 + sr.CACHE_SECONDS + 1)
    assert len(calls) > first + 1 + 3  # the cache expired


def test_nfl_and_cfb_use_the_sports_board_config_and_the_others_use_their_own_hosts(monkeypatch):
    monkeypatch.setenv("SPORTS_NBA_BASE_URL", "http://nba.internal:8000/")
    assert sr.base_url("nba") == "http://nba.internal:8000"
    monkeypatch.delenv("SPORTS_PL_BASE_URL", raising=False)
    assert sr.base_url("pl") == "https://pl.40-160-91-131.sslip.io"
    assert sr.base_url("nfl") and sr.base_url("cfb")


def test_the_endpoint_serves_the_collected_record(monkeypatch):
    monkeypatch.setattr(sr, "collect", lambda: {"as_of": "x", "sports": [{"sport": "nfl", "status": "ok", "rows": []}]})
    response = TestClient(main.app).get("/api/sports-record")
    assert response.status_code == 200 and response.json()["sports"][0]["sport"] == "nfl"
