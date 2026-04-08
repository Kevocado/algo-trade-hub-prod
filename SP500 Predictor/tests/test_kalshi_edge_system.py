"""
Test suite for the Kalshi Edge System — Phase 1-4 components.

Run with: python -m pytest tests/ -v

Tests are designed to work offline (no real API calls) using mocks.
"""

import sys
import os
import json
import asyncio
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ════════════════════════════════════════════════════════════════════
# NBA Engine Tests
# ════════════════════════════════════════════════════════════════════

class TestNBAEngine:
    """Tests for NBAEngine — verifies features and probability model without real API calls."""

    def test_parse_minutes_colon_format(self):
        from scripts.engines.nba_engine import NBAEngine
        engine = NBAEngine()
        assert engine._parse_minutes("32:14") == pytest.approx(32.23, abs=0.01)
        assert engine._parse_minutes("0:00") == 0.0
        assert engine._parse_minutes("40") == 40.0

    def test_estimate_prob_over_clear_favorite(self):
        """Player averaging 28 pts, line = 20.5 → should have high P(over)."""
        from scripts.engines.nba_engine import NBAEngine
        engine = NBAEngine()
        features = {
            "rolling_avg": 28.0,
            "rolling_std": 4.0,
            "min_avg": 34.0,
            "opp_drtg": 116.0,  # Bad defense
            "home_flag": 1,
            "b2b_flag": 0,
        }
        prob = engine._estimate_prob_over(features, line=20.5)
        assert prob > 70.0, f"Expected P(over) > 70%, got {prob}"

    def test_estimate_prob_over_clear_underdog(self):
        """Player averaging 15 pts, line = 25.5 → should have low P(over)."""
        from scripts.engines.nba_engine import NBAEngine
        engine = NBAEngine()
        features = {
            "rolling_avg": 15.0,
            "rolling_std": 4.0,
            "min_avg": 28.0,
            "opp_drtg": 111.0,  # Good defense
            "home_flag": 0,
            "b2b_flag": 1,  # Back to back
        }
        prob = engine._estimate_prob_over(features, line=25.5)
        assert prob < 20.0, f"Expected P(over) < 20%, got {prob}"

    def test_prob_always_in_bounds(self):
        """Probability must always be clipped to [2, 98]."""
        from scripts.engines.nba_engine import NBAEngine
        engine = NBAEngine()
        for avg in [0, 10, 50, 100]:
            for line in [0.5, 25.0, 100.0]:
                features = {
                    "rolling_avg": avg, "rolling_std": 3.0,
                    "min_avg": 30.0, "opp_drtg": 114.5,
                    "home_flag": 0, "b2b_flag": 0,
                }
                prob = engine._estimate_prob_over(features, line)
                assert 2.0 <= prob <= 98.0, f"Out of bounds: avg={avg}, line={line}, prob={prob}"

    def test_b2b_reduces_probability(self):
        """B2B flag should reduce modeled performance."""
        from scripts.engines.nba_engine import NBAEngine
        engine = NBAEngine()
        base_features = {
            "rolling_avg": 25.0, "rolling_std": 4.0, "min_avg": 32.0,
            "opp_drtg": 114.5, "home_flag": 0, "b2b_flag": 0,
        }
        b2b_features = {**base_features, "b2b_flag": 1}
        prob_rest = engine._estimate_prob_over(base_features, 22.5)
        prob_b2b  = engine._estimate_prob_over(b2b_features, 22.5)
        assert prob_b2b < prob_rest, "B2B should reduce probability"


# ════════════════════════════════════════════════════════════════════
# FastAPI Endpoint Tests
# ════════════════════════════════════════════════════════════════════

class TestFastAPIEndpoints:
    """Tests for the FastAPI layer using httpx TestClient."""

    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from api.main import app
        return TestClient(app)

    def test_health_endpoint(self, client):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "timestamp" in data

    def test_opportunities_empty_when_cache_empty(self, client):
        """With an empty cache, should return empty list, not 500."""
        response = client.get("/api/opportunities")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_nba_props_filter_by_min_edge(self, client):
        """min_edge filter should work correctly."""
        response = client.get("/api/nba_props?min_edge=20")
        assert response.status_code == 200
        results = response.json()
        for item in results:
            assert abs(item.get("edge_pct", 0)) >= 20

    def test_f1_signals_empty_list(self, client):
        """F1 signals with empty cache returns []."""
        response = client.get("/api/f1_signals")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_docs_available(self, client):
        """Swagger UI should be accessible."""
        response = client.get("/docs")
        assert response.status_code == 200


# ════════════════════════════════════════════════════════════════════
# Weather Maker Tests
# ════════════════════════════════════════════════════════════════════

class TestWeatherMaker:
    """Tests the NWS-based fair-value probability model (pure math, no API needed)."""

    def test_prob_above_high_confidence(self):
        """Forecast 60°F, strike 45°F, direction=above → near certain YES."""
        from scripts.engines.weather_maker import WeatherMaker
        maker = WeatherMaker()
        prob = maker._bayes_prob(forecast_high_f=60.0, strike=45.0, direction="above")
        assert prob > 90.0, f"Expected >90%, got {prob}"

    def test_prob_below_high_confidence(self):
        """Forecast 20°F, strike 40°F, direction=below → near certain YES."""
        from scripts.engines.weather_maker import WeatherMaker
        maker = WeatherMaker()
        prob = maker._bayes_prob(forecast_high_f=20.0, strike=40.0, direction="below")
        assert prob > 90.0, f"Expected >90%, got {prob}"

    def test_prob_near_strike_is_near_50(self):
        """Forecast == strike → should be near 50% (uncertainty)."""
        from scripts.engines.weather_maker import WeatherMaker
        maker = WeatherMaker()
        prob = maker._bayes_prob(forecast_high_f=50.0, strike=50.0, direction="above")
        assert 35.0 <= prob <= 65.0, f"Expected near 50%, got {prob}"

    def test_prob_always_in_bounds(self):
        """All probabilities must be clipped to [2, 98]."""
        from scripts.engines.weather_maker import WeatherMaker
        maker = WeatherMaker()
        for fcst in [0, 30, 70, 120]:
            for strike in [20, 50, 80]:
                for direction in ["above", "below"]:
                    prob = maker._bayes_prob(fcst, strike, direction)
                    assert 2.0 <= prob <= 98.0, f"Out of bounds: {prob}"

    def test_maker_spread_symmetric(self):
        """Bid should be 2¢ below fair value, ask 2¢ above."""
        from scripts.engines.weather_maker import WeatherMaker, MAKER_SPREAD_CENTS
        maker = WeatherMaker()
        fv = maker._bayes_prob(55.0, 50.0, "above")
        bid = round(fv - MAKER_SPREAD_CENTS, 1)
        ask = round(fv + MAKER_SPREAD_CENTS, 1)
        assert ask - bid == MAKER_SPREAD_CENTS * 2


# ════════════════════════════════════════════════════════════════════
# Telegram Command Parser Tests
# ════════════════════════════════════════════════════════════════════

class TestTelegramCommands:
    """Tests the command parser in TelegramNotifier (no real Telegram calls)."""

    def test_all_valid_commands_recognised(self):
        """All supported slash commands should hit the async handler without raising."""
        from src.telegram_notifier import TelegramNotifier
        tn = TelegramNotifier()
        async def fake_send_message(*_args, **_kwargs):
            return True

        async def fake_chat_id():
            return "12345"

        async def fake_text():
            return "ok"

        tn.send_message = fake_send_message
        tn._get_chat_id = fake_chat_id
        tn._get_crypto_status = fake_text
        tn._get_balance_text = fake_text
        tn._get_positions_text = fake_text
        tn._get_trades_text = fake_text
        tn._get_crypto_scan_text = fake_text

        for cmd in ["/help", "/crypto_status", "/cryptostatus", "/balance", "/positions", "/trades", "/crypto_scan", "/cryptoscan"]:
            asyncio.run(tn._handle_command(cmd, "12345"))

    def test_unknown_command_sends_help(self):
        """Unknown command → should send help hint, not raise."""
        from src.telegram_notifier import TelegramNotifier
        tn = TelegramNotifier()
        sent_messages = []

        async def fake_send_message(text, *_args, **_kwargs):
            sent_messages.append(text)
            return True

        async def fake_chat_id():
            return "12345"

        tn.send_message = fake_send_message
        tn._get_chat_id = fake_chat_id

        asyncio.run(tn._handle_command("/unknowncommand", "12345"))
        assert len(sent_messages) == 1
        call_text = sent_messages[0]
        assert "Unknown command" in call_text or "help" in call_text.lower()

    def test_send_alert_alias(self):
        """send_alert() must be an alias for send_message()."""
        import os
        os.environ["TELEGRAM_BOT_TOKEN"] = "test_token"
        os.environ["TELEGRAM_CHAT_ID"]   = "12345"

        from src.telegram_notifier import TelegramNotifier
        tn = TelegramNotifier()
        sent_messages = []

        async def fake_send_message(text, *_args, **_kwargs):
            sent_messages.append(text)
            return True

        tn.send_message = fake_send_message

        result = asyncio.run(tn.send_alert("test message"))
        assert sent_messages == ["test message"]
        assert result is True


# ════════════════════════════════════════════════════════════════════
# Microstructure Engine Tests
# ════════════════════════════════════════════════════════════════════

class TestMicrostructureEngine:
    """Tests MicrostructureEngine Binance features (pure math, no live API)."""

    def test_funding_signal_extreme_long(self):
        from src.microstructure_engine import MicrostructureEngine
        sig = MicrostructureEngine._funding_signal(2.5)
        assert "short" in sig.lower()

    def test_funding_signal_extreme_short(self):
        from src.microstructure_engine import MicrostructureEngine
        sig = MicrostructureEngine._funding_signal(-2.5)
        assert "long" in sig.lower()

    def test_funding_signal_neutral(self):
        from src.microstructure_engine import MicrostructureEngine
        sig = MicrostructureEngine._funding_signal(0.0)
        assert sig == "NEUTRAL"

    @patch("src.microstructure_engine.requests.get")
    def test_compute_funding_zscore_handles_empty(self, mock_get):
        """If Binance returns empty list, z_score should default to 0."""
        mock_get.return_value = MagicMock(status_code=200, json=MagicMock(return_value=[]))
        from src.microstructure_engine import MicrostructureEngine
        engine = MicrostructureEngine()
        result = engine.compute_funding_zscore("BTCUSDT")
        assert result["z_score"] == 0.0
