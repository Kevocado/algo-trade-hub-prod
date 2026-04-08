import os
import sys
import time
import logging
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from market_sentiment_tool.backend import mcp_server, orchestrator
from market_sentiment_tool.backend import runtime_bootstrap

CRYPTO_MODEL_FEATURES = [
    "Close",
    "High",
    "Low",
    "Open",
    "Volume",
    "hour",
    "dayofweek",
    "is_weekend",
    "is_retail_window",
    "is_us_session",
    "sin_hour",
    "cos_hour",
    "midnight_signal",
    "rsi_5",
    "rsi_7",
    "rsi_14",
    "vol_ratio",
    "dist_ma200",
    "force_idx",
    "rsi_div",
    "ret_1h_z",
    "ret_4h",
    "rsi_z",
    "z_score_24h",
    "vol_adj_ret",
    "relative_vol",
    "vol_pressure",
    "vol_spike",
    "retail_rsi",
    "trend_bias",
]


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


def test_build_crypto_feature_frame_produces_expected_columns():
    index = pd.date_range("2026-01-01", periods=260, freq="h", tz="UTC")
    close = np.linspace(90000.0, 93000.0, len(index))
    bars = pd.DataFrame(
        {
            "Open": close - 25.0,
            "High": close + 40.0,
            "Low": close - 40.0,
            "Close": close,
            "Volume": np.linspace(1000.0, 3000.0, len(index)),
        },
        index=index,
    )

    features = orchestrator._build_crypto_feature_frame(bars)
    assert not features.empty
    assert "target" not in features.columns
    assert len(features.columns) == len(CRYPTO_MODEL_FEATURES)
    assert all(name in features.columns for name in CRYPTO_MODEL_FEATURES)


def test_latest_crypto_feature_row_aligns_to_model(monkeypatch):
    index = pd.date_range("2026-01-01", periods=260, freq="h", tz="UTC")
    close = np.linspace(2500.0, 3100.0, len(index))
    bars = pd.DataFrame(
        {
            "Open": close - 3.0,
            "High": close + 6.0,
            "Low": close - 6.0,
            "Close": close,
            "Volume": np.linspace(500.0, 1500.0, len(index)),
        },
        index=index,
    )

    class FakeModel:
        feature_name_ = CRYPTO_MODEL_FEATURES

    orchestrator._CRYPTO_FEATURE_ROW_CACHE.clear()
    monkeypatch.setattr(orchestrator, "_fetch_alpaca_crypto_bars", lambda asset: bars)

    feature_row = orchestrator._latest_crypto_feature_row("ETH", FakeModel())

    assert list(feature_row.columns) == FakeModel.feature_name_
    assert feature_row.shape == (1, len(FakeModel.feature_name_))
    assert not feature_row.isnull().any(axis=None)


def test_merge_crypto_bar_sources_prefers_primary_on_overlap():
    primary_index = pd.date_range("2026-01-05", periods=3, freq="h", tz="UTC")
    backfill_index = pd.date_range("2026-01-04 22:00:00+00:00", periods=5, freq="h", tz="UTC")

    primary = pd.DataFrame(
        {
            "Open": [10.0, 11.0, 12.0],
            "High": [11.0, 12.0, 13.0],
            "Low": [9.0, 10.0, 11.0],
            "Close": [10.5, 11.5, 12.5],
            "Volume": [100.0, 110.0, 120.0],
        },
        index=primary_index,
    )
    backfill = pd.DataFrame(
        {
            "Open": [1.0, 2.0, 3.0, 4.0, 5.0],
            "High": [1.5, 2.5, 3.5, 4.5, 5.5],
            "Low": [0.5, 1.5, 2.5, 3.5, 4.5],
            "Close": [1.2, 2.2, 3.2, 4.2, 5.2],
            "Volume": [10.0, 20.0, 30.0, 40.0, 50.0],
        },
        index=backfill_index,
    )

    merged = orchestrator._merge_crypto_bar_sources(primary, backfill, required_bars=10)

    assert len(merged) == 5
    assert merged.loc[primary_index[0], "Close"] == 10.5
    assert merged.loc[primary_index[-1], "Volume"] == 120.0


def test_fetch_alpaca_crypto_bars_backfills_when_live_history_short(monkeypatch):
    short_index = pd.date_range("2026-01-01", periods=168, freq="h", tz="UTC")
    live_close = np.linspace(90000.0, 92000.0, len(short_index))
    historical_index = pd.date_range("2025-12-20", periods=260, freq="h", tz="UTC")
    historical_close = np.linspace(85000.0, 91000.0, len(historical_index))

    live_frame = pd.DataFrame(
        {
            "Open": live_close - 25.0,
            "High": live_close + 40.0,
            "Low": live_close - 40.0,
            "Close": live_close,
            "Volume": np.linspace(1000.0, 3000.0, len(short_index)),
        },
        index=short_index,
    )
    historical_frame = pd.DataFrame(
        {
            "Open": historical_close - 25.0,
            "High": historical_close + 40.0,
            "Low": historical_close - 40.0,
            "Close": historical_close,
            "Volume": np.linspace(500.0, 2500.0, len(historical_index)),
        },
        index=historical_index,
    )

    monkeypatch.setattr(orchestrator, "ALPACA_API_KEY", "key")
    monkeypatch.setattr(orchestrator, "ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(orchestrator, "_fetch_yfinance_crypto_bars", lambda asset, lookback_hours=orchestrator.CRYPTO_FEATURE_LOOKBACK_HOURS: historical_frame)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "bars": {
                    "BTC/USD": [
                        {
                            "t": ts.isoformat(),
                            "o": float(row.Open),
                            "h": float(row.High),
                            "l": float(row.Low),
                            "c": float(row.Close),
                            "v": float(row.Volume),
                        }
                        for ts, row in live_frame.iterrows()
                    ]
                }
            }

    class FakeRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            return FakeResponse()

    import sys

    monkeypatch.setitem(sys.modules, "requests", FakeRequests)

    merged = orchestrator._fetch_alpaca_crypto_bars("BTC", lookback_hours=220)

    assert len(merged) >= orchestrator.CRYPTO_MIN_FEATURE_BARS
    assert merged.index.max() == live_frame.index.max()


def test_fetch_yfinance_crypto_bars_raises_clear_error_when_dependency_missing(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "yfinance":
            raise ModuleNotFoundError("No module named 'yfinance'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    with pytest.raises(ModuleNotFoundError, match="yfinance is required for crypto historical backfill"):
        orchestrator._fetch_yfinance_crypto_bars("BTC")


def test_fetch_alpaca_crypto_bars_logs_when_merged_history_still_short(monkeypatch, caplog):
    short_index = pd.date_range("2026-01-01", periods=168, freq="h", tz="UTC")
    live_close = np.linspace(90000.0, 92000.0, len(short_index))
    historical_index = pd.date_range("2025-12-25", periods=20, freq="h", tz="UTC")
    historical_close = np.linspace(85000.0, 85500.0, len(historical_index))

    live_frame = pd.DataFrame(
        {
            "Open": live_close - 25.0,
            "High": live_close + 40.0,
            "Low": live_close - 40.0,
            "Close": live_close,
            "Volume": np.linspace(1000.0, 3000.0, len(short_index)),
        },
        index=short_index,
    )
    historical_frame = pd.DataFrame(
        {
            "Open": historical_close - 25.0,
            "High": historical_close + 40.0,
            "Low": historical_close - 40.0,
            "Close": historical_close,
            "Volume": np.linspace(500.0, 700.0, len(historical_index)),
        },
        index=historical_index,
    )

    monkeypatch.setattr(orchestrator, "ALPACA_API_KEY", "key")
    monkeypatch.setattr(orchestrator, "ALPACA_SECRET_KEY", "secret")
    monkeypatch.setattr(orchestrator, "_fetch_yfinance_crypto_bars", lambda asset, lookback_hours=orchestrator.CRYPTO_FEATURE_LOOKBACK_HOURS: historical_frame)

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "bars": {
                    "BTC/USD": [
                        {
                            "t": ts.isoformat(),
                            "o": float(row.Open),
                            "h": float(row.High),
                            "l": float(row.Low),
                            "c": float(row.Close),
                            "v": float(row.Volume),
                        }
                        for ts, row in live_frame.iterrows()
                    ]
                }
            }

    class FakeRequests:
        @staticmethod
        def get(*_args, **_kwargs):
            return FakeResponse()

    monkeypatch.setitem(sys.modules, "requests", FakeRequests)

    with caplog.at_level(logging.INFO):
        with pytest.raises(ValueError, match="Need at least"):
            orchestrator._fetch_alpaca_crypto_bars("BTC", lookback_hours=220)

    messages = [record.getMessage() for record in caplog.records]
    assert any("Alpaca returned only 168 hourly bars for BTC/USD" in message for message in messages)
    assert any("merged history is still short" in message for message in messages)


def test_evaluate_crypto_edge_skips_on_feature_inference_failure(monkeypatch):
    ticker_message = {
        "msg": {
            "market_ticker": "KXBTC-DUMMY",
            "yes_bid_dollars": 0.49,
            "yes_ask_dollars": 0.51,
        }
    }

    monkeypatch.setattr(orchestrator, "load_crypto_models", lambda: (object(), object()))
    monkeypatch.setattr(
        orchestrator,
        "_latest_crypto_feature_row",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("bad features")),
    )

    result = orchestrator.evaluate_crypto_edge(
        {"ticker": ticker_message, "trade_signal": None, "resolved_market_ticker": None, "final_edge": None, "execution_result": None}
    )

    assert result == {"trade_signal": None}
