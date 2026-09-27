"""The sports edge row must not present a spread artifact as an opportunity.

From the live War Room on 2026-09-27, `/api/sports-edges` returned rows that render as:

    UConn wins     YES @ 18c   78% vs 33%   +59.3 pp
    Syracuse wins  NO  @ 20c   22% vs 65%   +57.3 pp

Both numbers are arithmetically correct and both are meaningless to a reader. `edge_pct` is the
after-fee edge against the ENTRY price on the chosen side (18c), while `market_prob` is the quote
MID (33%). Printing them side by side invites `78 - 33 = 45`, which is not the 59.3 shown. And that
quote is 30c wide (bid 0.18 / ask 0.48), which is why the row is rejected for `wide_quote`: the
"edge" IS the spread.

So the row has to say what it compares, and a row the filter rejected must never lead with a number
that looks like an opportunity.

The fixture below is shaped like a real `kalshi_edges` row: the sports fields live in
`raw_payload`, which is where the scan writes them.
"""
import pytest

from tradehub.sports.scan import edge_row


def _row(**overrides):
    """A real-shaped sports edge row: the 0.18/0.48 quote from the live page."""
    raw = {
        "side": "yes", "entry_price": 0.18, "maker": True,
        "sport": "cfb", "kind": "winner", "home": "UConn", "away": "Syracuse",
        "start_utc": "2026-10-03T16:00:00+00:00", "game_id": "401858252",
        "yes_bid": 0.18, "yes_ask": 0.48,
        "tier": "filtered", "candidate": False,
        "reject_reasons": ["wide_quote", "thin_book", "calibration_insufficient"],
    }
    row = {
        "market_id": "KXNCAAFGAME-26OCT03SYRCONN-CONN",
        "title": "UConn wins",
        "our_prob": 0.7825,
        "market_prob": 0.33,          # the MID, which the page printed beside the edge
        "edge_pct": 0.5925,           # after-fee vs the 0.18 entry -- a different quantity
        "market_url": "https://kalshi.com/markets/x",
        "source_url": "https://sports.40-160-91-131.sslip.io/?sport=cfb&game=401858252",
        "engine": "sports_cfb",
        "gate_status": "SHADOW",
        "engine_version": "feed:unknown",
        "raw_payload": raw,
    }
    row.update(overrides)
    return row


def _passing(**raw_overrides):
    raw = {**_row()["raw_payload"], "tier": "top_pick", "candidate": True, "reject_reasons": []}
    raw.update(raw_overrides)
    return _row(raw_payload=raw)


def test_the_row_carries_the_price_the_edge_was_computed_against():
    """`edge_pct` is after-fee vs `entry_price`, so the entry price and side travel with it and the
    UI can label the comparison instead of implying it was against the mid."""
    row = edge_row(_passing())

    assert row["entry_price"] == 0.18
    assert row["side"] == "yes"
    assert row["edge_pct"] == pytest.approx(0.5925)
    assert row["market_prob"] == pytest.approx(0.33), "the mid is a different number and is kept"


def test_a_rejected_row_carries_no_headline_edge():
    """The most misleading thing on the page: a rejected row's spread artifact rendered as a +59pp
    opportunity. A row the filter refused has no headline number at all."""
    rejected = edge_row(_row())
    assert rejected["edge_pct"] is None, rejected
    assert rejected["reject_reasons"], "the reasons must survive so the row can explain itself"

    assert edge_row(_passing())["edge_pct"] == pytest.approx(0.5925)


def test_a_candidate_row_that_failed_on_wide_quote_still_shows_no_edge():
    """`candidate` and `tier` can disagree after a re-scan. The filter's verdict wins: a row whose
    reject_reasons include wide_quote has no edge worth showing."""
    row = edge_row(_passing(reject_reasons=["wide_quote"]))

    assert row["edge_pct"] is None
    assert "wide_quote" in row["reject_reasons"]


def test_the_quote_spread_is_reported_so_a_wide_quote_is_visible():
    """The thing that explains the number. Without it a reader cannot tell a real disagreement from
    a wide quote."""
    row = edge_row(_row())

    assert row["quote_spread"] == pytest.approx(0.30)
    assert row["entry_price"] == 0.18


def test_a_narrow_quote_reports_a_narrow_spread():
    row = edge_row(_passing(yes_bid=0.52, yes_ask=0.54))

    assert row["quote_spread"] == pytest.approx(0.02)


def test_an_unknown_engine_version_is_not_printed_as_the_word_unknown():
    """Every row on the live page carried the literal string "unknown" under the gate badge, because
    engine_version is the placeholder `feed:unknown`. A blank plus a flag says what is true."""
    placeholder = edge_row(_row())
    assert placeholder["engine_version"] is None
    assert placeholder["model_version_known"] is False

    real = edge_row(_row(engine_version="feed:xgb@2026-09-04T22:12:49+00:00"))
    assert real["engine_version"] == "feed:xgb@2026-09-04T22:12:49+00:00"
    assert real["model_version_known"] is True


def test_the_gate_is_never_dropped_even_when_the_version_is_a_placeholder():
    """The gate is keyed on (engine, engine_version). Hiding the placeholder must not hide the
    SHADOW badge, which is the honest label for every one of these rows."""
    row = edge_row(_row())

    assert row["gate_status"] == "SHADOW"
    assert row["engine"] == "sports_cfb"
