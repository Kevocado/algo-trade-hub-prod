import os
import sys
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from market_sentiment_tool.backend import mcp_server, orchestrator
from market_sentiment_tool.backend import runtime_bootstrap


class FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def contains(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class FakeSupabase:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return FakeQuery(self._data)


def _future_time(hours: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.fixture(autouse=True)
def reset_crypto_state(monkeypatch):
    orchestrator._TRADED_TICKER_LAST_TS.clear()
    monkeypatch.setattr(orchestrator, "supa", None)
    monkeypatch.setattr(orchestrator, "log_to_supabase", lambda *args, **kwargs: None)


def test_resolve_kalshi_market_picks_nearest_hourly_bucket_and_nearest_strike(monkeypatch):
    markets = [
        {
            "ticker": "KXBTC-NEXT-60000",
            "event_ticker": "KXBTC-NEXT",
            "title": "Bitcoin price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 60000,
        },
        {
            "ticker": "KXBTC-NEXT-60500",
            "event_ticker": "KXBTC-NEXT",
            "title": "Bitcoin price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 60500,
        },
        {
            "ticker": "KXBTC-LATER-60300",
            "event_ticker": "KXBTC-LATER",
            "title": "Bitcoin price today at 12AM",
            "close_time": _future_time(2),
            "strike_price": 60300,
        },
        {
            "ticker": "KXBTC-15M-60300",
            "event_ticker": "KXBTC-FAST",
            "title": "Bitcoin price in 15 min",
            "close_time": _future_time(1),
            "strike_price": 60300,
        },
        {
            "ticker": "KXETH-NEXT-3500",
            "event_ticker": "KXETH-NEXT",
            "title": "Ethereum price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 3500,
        },
    ]

    monkeypatch.setattr(orchestrator, "_kalshi_get", lambda *_args, **_kwargs: {"markets": markets, "cursor": None})

    resolved = orchestrator.resolve_kalshi_market(asset="BTC", spot_price=60320.0)

    assert resolved is not None
    assert resolved["ticker"] == "KXBTC-NEXT-60500"
    assert resolved["event_ticker"] == "KXBTC-NEXT"
    assert resolved["strike_price"] == 60500


def test_market_resolution_uses_spot_price_not_signal_price(monkeypatch):
    markets = [
        {
            "ticker": "KXBTC-NEXT-40000",
            "event_ticker": "KXBTC-NEXT",
            "title": "Bitcoin price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 40000,
        },
        {
            "ticker": "KXBTC-NEXT-70000",
            "event_ticker": "KXBTC-NEXT",
            "title": "Bitcoin price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 70000,
        },
    ]

    monkeypatch.setattr(orchestrator, "_kalshi_get", lambda *_args, **_kwargs: {"markets": markets, "cursor": None})
    monkeypatch.setattr(orchestrator, "_fetch_alpaca_spot_price", lambda asset: 70100.0 if asset == "BTC" else None)
    monkeypatch.setattr(orchestrator, "_cooldown_allows_trade", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        orchestrator,
        "_kalshi_orderbook_bbo_dollars",
        lambda *_args, **_kwargs: {"yes_ask": 0.59, "yes_bid": 0.58, "no_ask": 0.41, "no_bid": 0.40},
    )

    signal = {
        "asset": "BTC",
        "market_ticker": "KXBTC-SOURCE",
        "side": "YES",
        "probability_yes": 0.60,
        "price_dollars": 0.42,
        "spot_price_dollars": None,
        "resolved_ticker": None,
        "edge": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": {},
    }

    result = orchestrator.market_resolution({"ticker": {}, "trade_signal": signal, "resolved_market_ticker": None, "final_edge": None, "execution_result": None})

    assert result["resolved_market_ticker"] == "KXBTC-NEXT-70000"
    assert result["trade_signal"]["spot_price_dollars"] == 70100.0
    assert result["trade_signal"]["resolved_ticker"] == "KXBTC-NEXT-70000"


def test_cooldown_blocks_via_memory_and_supabase(monkeypatch):
    ticker_id = "KXBTC-NEXT-60000"

    orchestrator._TRADED_TICKER_LAST_TS[ticker_id] = time.time()
    assert orchestrator._cooldown_allows_trade(ticker_id) is False

    orchestrator._TRADED_TICKER_LAST_TS.clear()
    monkeypatch.setattr(orchestrator, "supa", FakeSupabase([{"id": 1}]))
    assert orchestrator._cooldown_allows_trade(ticker_id) is False


def test_market_resolution_calls_plain_submit_helper(monkeypatch):
    markets = [
        {
            "ticker": "KXETH-NEXT-3500",
            "event_ticker": "KXETH-NEXT",
            "title": "Ethereum price today at 11PM",
            "close_time": _future_time(1),
            "strike_price": 3500,
        }
    ]
    submitted = {}

    monkeypatch.setattr(orchestrator, "_kalshi_get", lambda *_args, **_kwargs: {"markets": markets, "cursor": None})
    monkeypatch.setattr(orchestrator, "_fetch_alpaca_spot_price", lambda asset: 3490.0 if asset == "ETH" else None)
    monkeypatch.setattr(orchestrator, "_cooldown_allows_trade", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(
        orchestrator,
        "_kalshi_orderbook_bbo_dollars",
        lambda *_args, **_kwargs: {"yes_ask": 0.55, "yes_bid": 0.54, "no_ask": 0.45, "no_bid": 0.44},
    )
    def fake_submit_kalshi_order(**kwargs):
        submitted["payload"] = kwargs
        return {"status": "accepted", "order_id": "demo-order"}

    monkeypatch.setattr(mcp_server, "submit_kalshi_order", fake_submit_kalshi_order)
    monkeypatch.setattr(
        mcp_server,
        "execute_kalshi_order",
        lambda **_kwargs: pytest.fail("market_resolution should not call execute_kalshi_order"),
    )

    signal = {
        "asset": "ETH",
        "market_ticker": "KXETH-SOURCE",
        "side": "YES",
        "probability_yes": 0.72,
        "price_dollars": 0.51,
        "spot_price_dollars": None,
        "resolved_ticker": None,
        "edge": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "raw": {},
    }

    result = orchestrator.market_resolution({"ticker": {}, "trade_signal": signal, "resolved_market_ticker": None, "final_edge": None, "execution_result": None})

    assert result["resolved_market_ticker"] == "KXETH-NEXT-3500"
    assert submitted["payload"]["ticker"] == "KXETH-NEXT-3500"
    assert submitted["payload"]["side"] == "yes"
    assert submitted["payload"]["action"] == "buy"
    assert submitted["payload"]["count"] == orchestrator.KALSHI_ORDER_COUNT
    assert submitted["payload"]["limit_price_dollars"] == "0.5500"


def test_load_canonical_env_prefers_repo_root(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "market_sentiment_tool" / "backend"
    backend_dir.mkdir(parents=True)
    module_file = backend_dir / "fake_module.py"
    module_file.write_text("# test module\n", encoding="utf-8")

    (repo_root / ".env").write_text("SUPABASE_SERVICE_ROLE_KEY=root-key\n", encoding="utf-8")
    (repo_root / "market_sentiment_tool" / ".env").write_text("SUPABASE_SERVICE_ROLE_KEY=service-key\n", encoding="utf-8")

    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    bootstrap = runtime_bootstrap.load_canonical_env(str(module_file))

    assert bootstrap.env_path == repo_root / ".env"
    assert bootstrap.source_label == "repo_root"
    assert os.getenv("SUPABASE_SERVICE_ROLE_KEY") == "root-key"


def test_load_canonical_env_reports_syntax_error(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "market_sentiment_tool" / "backend"
    backend_dir.mkdir(parents=True)
    module_file = backend_dir / "fake_module.py"
    module_file.write_text("# test module\n", encoding="utf-8")

    (repo_root / ".env").write_text("SUPABASE_URL=https://example.supabase.co\nthis is not valid\n", encoding="utf-8")

    monkeypatch.delenv("SUPABASE_URL", raising=False)
    bootstrap = runtime_bootstrap.load_canonical_env(str(module_file))

    assert bootstrap.env_path == repo_root / ".env"
    assert bootstrap.syntax_errors
    assert "invalid dotenv syntax" in bootstrap.syntax_errors[0]


def test_resolve_kalshi_settings_uses_mode_and_rejects_invalid_legacy_host(monkeypatch):
    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setenv("KALSHI_DEMO_API_BASE", "https://demo-api.kalshi.co/trade-api/v2")
    monkeypatch.setenv("KALSHI_API_BASE", "https://api.kalshi.com/trade-api/v2")
    monkeypatch.setenv("KALSHI_WS_URL", "wss://demo-api.kalshi.co/trade-api/ws/v2")

    settings = runtime_bootstrap.resolve_kalshi_runtime_settings()

    assert settings.mode == "demo"
    assert settings.api_base == "https://demo-api.kalshi.co/trade-api/v2"
    assert settings.ws_url == "wss://demo-api.kalshi.co/trade-api/ws/v2"
    assert any("KALSHI_API_BASE points to unsupported Kalshi host" in error for error in settings.errors)


def test_validate_runtime_env_requires_supabase_and_private_key(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    backend_dir = repo_root / "market_sentiment_tool" / "backend"
    backend_dir.mkdir(parents=True)
    module_file = backend_dir / "fake_module.py"
    module_file.write_text("# test module\n", encoding="utf-8")

    (repo_root / ".env").write_text(
        "\n".join(
            [
                "SUPABASE_URL=https://example.supabase.co",
                "KALSHI_ENV=demo",
                "KALSHI_API_KEY_ID=test-key",
                "KALSHI_PRIVATE_KEY_PATH=/tmp/missing.pem",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY", "KALSHI_ENV", "KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH"):
        monkeypatch.delenv(key, raising=False)

    bootstrap = runtime_bootstrap.load_canonical_env(str(module_file))
    settings = runtime_bootstrap.resolve_kalshi_runtime_settings()
    errors = runtime_bootstrap.validate_runtime_env(
        env_bootstrap=bootstrap,
        kalshi=settings,
        require_supabase=True,
        require_kalshi=True,
    )

    assert any("Missing required env var: SUPABASE_SERVICE_ROLE_KEY" in error for error in errors)
    assert any("KALSHI_PRIVATE_KEY_PATH is invalid" in error for error in errors)
