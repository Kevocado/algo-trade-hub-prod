import asyncio
import os
import sys
from datetime import datetime, timezone

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_shadow_report_computes_hit_rate_brier_and_virtual_pnl(monkeypatch):
    from scripts import shadow_performance

    rows = [
        {
            "asset": "BTC",
            "created_at": "2026-04-09T03:30:00+00:00",
            "source_market_ticker": "BTC-A",
            "desired_side": "YES",
            "status": "signal_detected",
            "model_probability_yes": 0.60,
            "payload": {},
        },
        {
            "asset": "ETH",
            "created_at": "2026-04-09T03:40:00+00:00",
            "source_market_ticker": "ETH-B",
            "desired_side": "NO",
            "status": "signal_detected",
            "model_probability_yes": 0.40,
            "payload": {},
        },
    ]

    monkeypatch.setattr(shadow_performance, "fetch_recent_signal_events", lambda **_kwargs: rows)
    monkeypatch.setattr(
        shadow_performance,
        "_current_hour_utc",
        lambda reference=None: pd.Timestamp("2026-04-09T05:00:00Z"),
    )

    def fake_fetch(asset, *, start, end):
        if asset == "BTC":
            index = pd.to_datetime(["2026-04-09T02:00:00Z", "2026-04-09T03:00:00Z"], utc=True)
            return pd.DataFrame({"Close": [100.0, 101.0]}, index=index)
        index = pd.to_datetime(["2026-04-09T02:00:00Z", "2026-04-09T03:00:00Z"], utc=True)
        return pd.DataFrame({"Close": [200.0, 199.0]}, index=index)

    monkeypatch.setattr(shadow_performance, "_fetch_alpaca_hourly_closes", fake_fetch)

    report = shadow_performance.build_shadow_report(hours=24, btc_yes=0.55, btc_no=0.45, eth_yes=0.55, eth_no=0.45)

    assert report["overall"]["count"] == 2
    assert report["consideration"]["evaluated_count"] == 2
    assert report["consideration"]["considered_count"] == 2
    assert report["consideration"]["dead_zone_count"] == 0
    assert report["overall"]["hit_rate"] == pytest.approx(1.0)
    assert report["overall"]["brier_score"] == pytest.approx(0.16)
    assert report["overall"]["virtual_pnl_pct"] == pytest.approx(1.5)
    assert "Brier Score: 0.1600" in shadow_performance.render_shadow_report(report, telegram=False)


def test_shadow_report_handles_no_recent_data():
    from scripts import shadow_performance

    text = shadow_performance.render_shadow_report(
        {
            "hours": 24,
            "overall": {"count": 0, "hit_rate": None, "virtual_pnl_pct": 0.0, "brier_score": None},
            "by_asset": {"BTC": {}, "ETH": {}},
            "thresholds": {"BTC": shadow_performance.ThresholdConfig(0.5751, 0.4249), "ETH": shadow_performance.ThresholdConfig(0.551, 0.449)},
            "bucket_stats": {},
            "consideration": {"evaluated_count": 0, "considered_count": 0, "dead_zone_count": 0},
            "freshness": {
                "BTC": {"latest_bar": None, "age_hours": None, "is_stale": None},
                "ETH": {"latest_bar": None, "age_hours": None, "is_stale": None},
            },
            "errors": [],
        },
        telegram=True,
    )

    assert "Bot Would Have Considered: 0 trades" in text
    assert "No recent shadow outcomes" in text


def test_shadow_current_hour_utc_handles_aware_datetime():
    from scripts import shadow_performance

    ts = shadow_performance._current_hour_utc(datetime(2026, 4, 9, 22, 17, tzinfo=timezone.utc))

    assert ts == pd.Timestamp("2026-04-09T22:00:00Z")


def test_shadow_alpaca_config_reads_env_lazily(monkeypatch):
    from scripts import shadow_performance

    monkeypatch.setenv("ALPACA_API_KEY", "key-123")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "secret-456")
    monkeypatch.setenv("ALPACA_DATA_API_BASE", "https://example.alpaca")

    api_base, api_key, secret_key = shadow_performance._alpaca_config()

    assert api_base == "https://example.alpaca"
    assert api_key == "key-123"
    assert secret_key == "secret-456"


def test_shadow_report_counts_dead_zone_and_reports_freshness(monkeypatch):
    from scripts import shadow_performance

    rows = [
        {
            "asset": "BTC",
            "created_at": "2026-04-09T03:30:00+00:00",
            "source_market_ticker": "BTC-A",
            "desired_side": "YES",
            "status": "signal_detected",
            "model_probability_yes": 0.60,
            "payload": {},
        },
        {
            "asset": "ETH",
            "created_at": "2026-04-09T03:40:00+00:00",
            "source_market_ticker": "ETH-B",
            "desired_side": None,
            "status": "inference_heartbeat",
            "model_probability_yes": 0.50,
            "payload": {},
        },
    ]

    monkeypatch.setattr(shadow_performance, "fetch_recent_signal_events", lambda **_kwargs: rows)
    monkeypatch.setattr(
        shadow_performance,
        "_current_hour_utc",
        lambda reference=None: pd.Timestamp("2026-04-09T05:00:00Z"),
    )

    def fake_fetch(asset, *, start, end):
        if asset == "BTC":
            index = pd.to_datetime(["2026-04-09T02:00:00Z", "2026-04-09T03:00:00Z"], utc=True)
            return pd.DataFrame({"Close": [100.0, 101.0]}, index=index)
        index = pd.to_datetime(["2026-04-09T02:00:00Z", "2026-04-09T03:00:00Z"], utc=True)
        return pd.DataFrame({"Close": [200.0, 200.0]}, index=index)

    monkeypatch.setattr(shadow_performance, "_fetch_alpaca_hourly_closes", fake_fetch)

    report = shadow_performance.build_shadow_report(hours=24, btc_yes=0.55, btc_no=0.45, eth_yes=0.55, eth_no=0.45)
    text = shadow_performance.render_shadow_report(report, telegram=False)

    assert report["consideration"]["evaluated_count"] == 2
    assert report["consideration"]["considered_count"] == 1
    assert report["consideration"]["dead_zone_count"] == 1
    assert "Bot Would Have Considered: 1 trades" in text
    assert "Dead Zone: 1" in text
    assert "BTC: fresh" in text


def test_force_demo_trade_rejects_non_demo(monkeypatch):
    from scripts import force_demo_trade

    monkeypatch.setenv("KALSHI_ENV", "prod")
    monkeypatch.setattr(sys, "argv", ["force_demo_trade.py", "KXETH-TEST", "YES"])

    assert force_demo_trade.main() == 2


def test_force_demo_trade_submits_known_ticker(monkeypatch):
    from scripts import force_demo_trade

    submitted = {}

    monkeypatch.setenv("KALSHI_ENV", "demo")
    monkeypatch.setattr(sys, "argv", ["force_demo_trade.py", "KXETH-TEST", "YES"])
    monkeypatch.setattr(
        force_demo_trade,
        "submit_kalshi_order",
        lambda **kwargs: submitted.update(kwargs) or {"status": "accepted", "order_id": "demo-1"},
    )

    assert force_demo_trade.main() == 0
    assert submitted["ticker"] == "KXETH-TEST"
    assert submitted["side"] == "yes"
    assert submitted["count"] == 1


def test_telegram_help_and_stats_commands(monkeypatch):
    from src.telegram_notifier import TelegramNotifier

    tn = TelegramNotifier()
    sent_messages = []

    async def fake_send_message(text, *_args, **_kwargs):
        sent_messages.append(text)
        return True

    async def fake_chat_id():
        return "12345"

    async def fake_stats():
        return "stats ok"

    tn.send_message = fake_send_message
    tn._get_chat_id = fake_chat_id
    tn._get_crypto_status = fake_stats
    tn._get_balance_text = fake_stats
    tn._get_positions_text = fake_stats
    tn._get_trades_text = fake_stats
    tn._get_scan_text = lambda domain: fake_stats()
    tn._get_performance_text = lambda domain: fake_stats()

    asyncio.run(tn._handle_command("/help", "12345"))
    asyncio.run(tn._handle_command("/stats", "12345"))
    asyncio.run(tn._handle_command("/accuracy", "12345"))
    asyncio.run(tn._handle_command("/performance crypto", "12345"))

    assert "/performance {domain}" in sent_messages[0]
    assert "/test_trade" not in sent_messages[0]
    assert "/force_demo_buy" not in sent_messages[0]
    assert sent_messages[1] == "stats ok"
    assert sent_messages[2] == "stats ok"
    assert sent_messages[3] == "stats ok"


def test_auto_retrain_does_not_replace_incumbent_on_tie_or_worse(monkeypatch, tmp_path):
    from scripts import auto_retrain_regime

    model_path = tmp_path / "btc_model.pkl"
    model_path.write_text("placeholder")
    dump_calls = []

    monkeypatch.setattr(
        auto_retrain_regime,
        "_fetch_training_bars",
        lambda asset, days=14: pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=pd.to_datetime(["2026-04-01T00:00:00Z"], utc=True)),
    )
    features = pd.DataFrame(
        {
            **{name: [0.1, 0.2, 0.3, 0.4] for name in auto_retrain_regime.CANONICAL_CRYPTO_FEATURES},
            "target": [0, 1, 0, 1],
        },
        index=pd.date_range("2026-04-01", periods=4, freq="h", tz="UTC"),
    )
    monkeypatch.setattr(auto_retrain_regime, "build_features", lambda *args, **kwargs: features)
    monkeypatch.setattr(auto_retrain_regime, "_train_candidate_model", lambda features: ("candidate", features[auto_retrain_regime.CANONICAL_CRYPTO_FEATURES], features["target"], 0.75))
    monkeypatch.setattr(auto_retrain_regime, "_candidate_model_path", lambda asset: model_path)
    monkeypatch.setattr(auto_retrain_regime.orchestrator, "_load_pickle_model", lambda path: object())
    monkeypatch.setattr(auto_retrain_regime, "_feature_contract_matches", lambda model: True)
    monkeypatch.setattr(auto_retrain_regime, "_brier_score", lambda model, x, y: 0.20)
    monkeypatch.setattr(auto_retrain_regime.joblib, "dump", lambda model, path: dump_calls.append((model, path)))

    result = auto_retrain_regime.retrain_asset("BTC")

    assert result.promoted is False
    assert result.reason == "candidate_not_strictly_better"
    assert dump_calls == []


def test_auto_retrain_replaces_incumbent_only_when_candidate_is_better(monkeypatch, tmp_path):
    from scripts import auto_retrain_regime

    model_path = tmp_path / "eth_model.pkl"
    model_path.write_text("placeholder")
    dump_calls = []

    monkeypatch.setattr(
        auto_retrain_regime,
        "_fetch_training_bars",
        lambda asset, days=14: pd.DataFrame({"Open": [1], "High": [1], "Low": [1], "Close": [1], "Volume": [1]}, index=pd.to_datetime(["2026-04-01T00:00:00Z"], utc=True)),
    )
    features = pd.DataFrame(
        {
            **{name: [0.1, 0.2, 0.3, 0.4] for name in auto_retrain_regime.CANONICAL_CRYPTO_FEATURES},
            "target": [0, 1, 0, 1],
        },
        index=pd.date_range("2026-04-01", periods=4, freq="h", tz="UTC"),
    )
    monkeypatch.setattr(auto_retrain_regime, "build_features", lambda *args, **kwargs: features)
    monkeypatch.setattr(auto_retrain_regime, "_train_candidate_model", lambda features: ("candidate", features[auto_retrain_regime.CANONICAL_CRYPTO_FEATURES], features["target"], 0.90))
    monkeypatch.setattr(auto_retrain_regime, "_candidate_model_path", lambda asset: model_path)
    monkeypatch.setattr(auto_retrain_regime.orchestrator, "_load_pickle_model", lambda path: object())
    monkeypatch.setattr(auto_retrain_regime, "_feature_contract_matches", lambda model: True)
    monkeypatch.setattr(auto_retrain_regime, "_brier_score", lambda model, x, y: 0.20)
    monkeypatch.setattr(auto_retrain_regime.joblib, "dump", lambda model, path: dump_calls.append((model, path)))

    result = auto_retrain_regime.retrain_asset("ETH")

    assert result.promoted is True
    assert result.reason == "candidate_beats_incumbent"
    assert dump_calls[0][0] == "candidate"
    assert dump_calls[0][1] == model_path
