"""`/api/shadow-performance` had no success-path test, so its real dependencies were invisible.

Found on 2026-09-27 while checking whether applying `20260415090000_signal_events_unification.sql`
would actually make the endpoint work. It would not. The endpoint needs **two** things, and only the
first is a migration:

1. `signal_events` to exist — the migration renames `crypto_signal_events` into place. This was never
   applied to the live project, so the endpoint returned a raw PostgREST `PGRST205` dump.
2. **Working Alpaca credentials.** `build_shadow_report` calls `_fetch_alpaca_hourly_closes`, which
   reads `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` and makes a live call to `data.alpaca.markets` for
   BTC/USD and ETH/USD hourly bars, used to mark each signal's outcome. `vps-stack/compose.yml` passes
   `SUPABASE_*`, `SPORTS_*`, `OPENROUTER_API_KEY` and `FRED_API_KEY` to the tradehub service, but no
   `ALPACA_*`.

So applying the migration alone moves the failure from "table not found" to "Alpaca credentials
missing" — and since PR #20 taught the endpoint to name the *migration* in its error, the message
would have stopped naming the thing that was still wrong. An operator would apply the migration, see
a different 503, and reasonably conclude the fix had half-worked.

Why nobody noticed: every existing reference to `build_shadow_timeline_response` monkeypatches it to
**fail** (`tests/test_kalshi_edge_system.py:57` and `:111`), so the suite only ever proved the error
handling worked. The success path was never exercised.

These tests pin both dependencies, so the next person to see a red `/shadow` learns the full list from
CI rather than from production, one failed deploy at a time.
"""
import pandas as pd
import pytest

from tradehub.scripts import shadow_performance as sp


class _Query:
    """Chainable no-op, so a test fails on real logic rather than on a missing builder method."""

    def __init__(self, rows):
        self.rows = rows

    def __getattr__(self, name):
        if name.startswith("_"):
            raise AttributeError(name)
        return lambda *a, **k: self

    def execute(self):
        return type("R", (), {"data": self.rows, "count": len(self.rows)})()


class _Client:
    def __init__(self, rows=()):
        self.rows = list(rows)
        self.queried = []

    def table(self, name):
        self.queried.append(name)
        if name != sp.SIGNAL_EVENTS_TABLE:
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")
        return _Query(self.rows)


@pytest.fixture
def no_crypto_network(monkeypatch):
    """Replaces the live market-data call. `_fetch_alpaca_hourly_closes` is the only seam that reaches
    the network, and an empty frame is a legitimate answer: no bars for the window."""
    calls = []

    def fake(asset, *, start, end):
        calls.append(asset)
        return pd.DataFrame(columns=["timestamp", "Close"]), "kraken"

    monkeypatch.setattr(sp, "_fetch_crypto_hourly_closes", fake)
    return calls


def test_the_shadow_timeline_works_once_signal_events_exists(monkeypatch, no_crypto_network):
    """The gap. With the table present, the endpoint must return a payload rather than raise -- and
    it must do so with the market-data call stubbed, so this test needs no credentials and no network.

    Empty `signal_events` is exactly what production looks like the moment the rename migration lands
    on a project that has never graded a signal, so this is the first state an operator will hit.
    """
    client = _Client()
    monkeypatch.setattr(sp, "_load_supabase_client", lambda: client)

    response = sp.build_shadow_timeline_response(hours=24, domain="crypto")

    assert isinstance(response, dict)
    assert client.queried == [sp.SIGNAL_EVENTS_TABLE], "should read signal_events and nothing else"
    assert "series" in response, sorted(response)
    assert response["series"] == [], "no settled signals, so an empty series is the honest result"


def test_a_missing_signal_events_table_is_reported_as_a_missing_table(monkeypatch, no_crypto_network):
    """The failure that was live. It must be distinguishable from every other failure, because it is
    fixed by applying a migration rather than by editing code."""

    class _Missing(_Client):
        def table(self, name):
            raise RuntimeError(
                "Could not find the table 'public.signal_events' in the schema cache"
            )

    monkeypatch.setattr(sp, "_load_supabase_client", lambda: _Missing())

    with pytest.raises(Exception) as caught:
        sp.build_shadow_timeline_response(hours=24, domain="crypto")

    assert "signal_events" in str(caught.value)


def test_works_without_alpaca_credentials(monkeypatch):
    """The route uses keyless Kraken/Coinbase market data, so ALPACA_* being unset must not block it.

    The old behavior raised `MissingCredentialError("Alpaca API", ...)` when ALPACA_* was unset.
    That is gone: Kraken and Coinbase need no credentials, and the route must run with no env vars
    set at all.
    """
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_SECRET_KEY", raising=False)
    monkeypatch.delenv("ALPACA_DATA_API_BASE", raising=False)
    monkeypatch.setattr(sp, "_load_supabase_client", lambda: _Client())

    def fake_fetch(asset, *, start, end):
        index = pd.date_range("2026-10-01", periods=2, freq="h", tz="UTC")
        return pd.DataFrame({"Close": [100.0, 101.0]}, index=index), "kraken"

    monkeypatch.setattr(sp, "_fetch_crypto_hourly_closes", fake_fetch)

    # Must not raise, and must return a payload rather than empty
    report = sp.build_shadow_timeline_response(hours=24, domain="crypto")
    assert report["domain"] == "crypto"
    assert report["hours"] == 24
    assert "thresholds" in report

