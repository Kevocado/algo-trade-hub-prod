"""Kalshi quotes: *_dollars are 0-1 strings, the legacy cent keys are gone.

Live payload captured from GET /markets?series_ticker=KXHIGHNY on 2026-09-28.
The legacy keys are absent from every market, so ``m.get('yes_ask', 0)`` did not
fall back to a quote -- it fabricated a 0c price for markets quoting right now,
and ``my_prob - 0`` published a probability-sized "edge" at an untradeable
price. A missing figure is never a number, so it must be None.
"""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from tradehub.core.kalshi_feed import process_markets
from tradehub.core.kalshi_portfolio import KalshiPortfolio
from tradehub.markets import QUOTE_FIELDS, quote_cents

# The real market from the briefing: 62c/63c YES, 37c/38c NO.
LIVE_T64 = {
    "ticker": "KXHIGHNY-26SEP28-T64",
    "yes_bid_dollars": "0.6200",
    "yes_ask_dollars": "0.6300",
    "no_bid_dollars": "0.3700",
    "no_ask_dollars": "0.3800",
    "floor_strike": 64,
    "cap_strike": None,
}

# A real market with no two-sided interest: Kalshi quotes the degenerate ends
# as 0.0000/1.0000 rather than omitting the field.
LIVE_T71 = {
    "ticker": "KXHIGHNY-26SEP28-T71",
    "yes_bid_dollars": "0.0000",
    "yes_ask_dollars": "0.0100",
    "no_bid_dollars": "0.9900",
    "no_ask_dollars": "1.0000",
}

NO_PRICE_KEYS = ("ticker", "floor_strike", "cap_strike")


# ─── the shared normaliser ────────────────────────────────────────────────────

def test_dollar_string_rescales_to_cents():
    prices = quote_cents(LIVE_T64)
    assert prices["yes_ask"] == 63.0  # 63c, not 0.63 and not 0
    assert prices["yes_ask"] != 0.63
    assert prices["yes_ask"] != 0
    assert prices == {"yes_bid": 62.0, "yes_ask": 63.0, "no_bid": 37.0, "no_ask": 38.0}


def test_rescale_is_pinned_in_both_directions():
    """Dollars scale up by 100; legacy cents are already scaled and must not move."""
    dollars = quote_cents({"yes_ask_dollars": "0.6200"})
    cents = quote_cents({"yes_ask": 62})

    assert dollars["yes_ask"] == 62.0
    assert cents["yes_ask"] == 62.0
    # the two generations agree, so no caller can tell which schema it got
    assert dollars == cents
    # and neither is read as a dollars-scale price
    assert dollars["yes_ask"] != 0.62
    assert cents["yes_ask"] != 0.62


def test_rescale_is_exact_not_a_float_artefact():
    """0.29 * 100 == 28.999999999999996 and 0.07 * 100 == 7.000000000000001."""
    prices = quote_cents({"yes_bid_dollars": "0.2900", "yes_ask_dollars": "0.0700"})
    assert prices["yes_bid"] == 29.0
    assert prices["yes_ask"] == 7.0
    assert repr(prices["yes_bid"]) == "29.0"
    assert repr(prices["yes_ask"]) == "7.0"


def test_missing_price_fields_are_none_never_zero():
    prices = quote_cents({k: None for k in NO_PRICE_KEYS})
    assert set(prices) == set(QUOTE_FIELDS)
    assert all(v is None for v in prices.values())
    assert 0 not in prices.values()


def test_dollars_win_over_legacy_when_both_are_present():
    prices = quote_cents({**LIVE_T64, "yes_ask": 99, "no_bid": 99})
    assert prices["yes_ask"] == 63.0
    assert prices["no_bid"] == 37.0


def test_unparseable_and_degenerate_quotes_are_none():
    assert quote_cents({"yes_ask_dollars": ""})["yes_ask"] is None
    assert quote_cents({"yes_ask_dollars": "n/a"})["yes_ask"] is None
    assert quote_cents(LIVE_T71) == {
        "yes_bid": None,
        "yes_ask": 1.0,
        "no_bid": 99.0,
        "no_ask": None,
    }


# ─── site 1: kalshi_feed.process_markets ───────────────────────────────────────

def test_process_markets_carries_the_real_quote():
    (row,) = process_markets([{**LIVE_T64, "title": "Will the high be above 64?"}], "BTC")
    assert (row["yes_bid"], row["yes_ask"], row["no_bid"], row["no_ask"]) == (62.0, 63.0, 37.0, 38.0)
    assert row["market_id"] == "KXHIGHNY-26SEP28-T64"


def test_process_markets_does_not_fabricate_a_zero_price():
    (row,) = process_markets([{k: v for k, v in LIVE_T64.items() if not k.endswith("_dollars")}], "BTC")
    assert {k: row[k] for k in QUOTE_FIELDS} == dict.fromkeys(QUOTE_FIELDS)
    assert all(row[k] is None for k in QUOTE_FIELDS)


def test_process_markets_still_reads_a_legacy_only_market():
    legacy = {"ticker": "KXBTC-OLD", "floor_strike": 100000, "cap_strike": None,
              "yes_bid": 62, "yes_ask": 63, "no_bid": 37, "no_ask": 38}
    (row,) = process_markets([legacy], "BTC")
    assert (row["yes_bid"], row["yes_ask"], row["no_bid"], row["no_ask"]) == (62, 63, 37, 38)


# ─── site 2: kalshi_portfolio.get_portfolio_summary ────────────────────────────

def _portfolio(monkeypatch, market):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    monkeypatch.setenv("KALSHI_API_KEY_ID", "test-key-id")
    monkeypatch.setenv("KALSHI_API_KEY", pem)

    kp = KalshiPortfolio()
    monkeypatch.setattr(kp, "get_balance", lambda: {"balance": 2000, "portfolio_value": 2000})
    monkeypatch.setattr(kp, "get_positions", lambda: [{"ticker": "KXHIGHNY-26SEP28-T64", "position": 10}])
    monkeypatch.setattr(kp, "get_market_data", lambda t: {"market": market} if market is not None else {})
    monkeypatch.setattr(kp, "get_settlements", lambda limit=30: [])
    return kp.get_portfolio_summary()


def test_portfolio_mid_price_comes_from_the_dollar_quote(monkeypatch):
    (position,) = _portfolio(monkeypatch, LIVE_T64)["positions"]
    assert position["current_price"] == pytest.approx(62.5)
    assert position["current_price"] != 0
    assert position["market_exposure_dollars"] == pytest.approx(6.25)


def test_portfolio_does_not_persist_a_zero_price(monkeypatch):
    unpriced = {k: v for k, v in LIVE_T64.items() if not k.endswith("_dollars")}
    (position,) = _portfolio(monkeypatch, unpriced)["positions"]
    assert "current_price" not in position
    assert "market_exposure_dollars" not in position
    assert _portfolio(monkeypatch, None)["market_exposure"] == 0
