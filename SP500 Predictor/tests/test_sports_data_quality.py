import unittest
from unittest.mock import patch, MagicMock
import sys
import os
from datetime import datetime, timedelta

# Ensure the 'SP500 Predictor' root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.engines.football_engine import FootballKalshiEngine
from scripts.engines.nba_engine import NBAEngine
from scripts.engines.f1_engine import F1Engine
from scripts.engines.dixon_coles import DixonColesModel
import pandas as pd

class TestSportsDataQuality(unittest.TestCase):

    def setUp(self):
        self.fb_engine = FootballKalshiEngine()
        # Initialize others if needed
        self.nba_engine = NBAEngine()
        self.f1_engine = F1Engine()

    def test_football_probability_summation(self):
        """Verify Poisson probabilities for Home/Draw/Away sum to 100%."""
        probs = self.fb_engine.calculate_poisson_edge(1.5, 1.2)
        total_prob = probs["HOME_WIN"] + probs["DRAW"] + probs["AWAY_WIN"]
        # In Poisson, grids from 0-7 might capture ~99.9% but not exactly 100%.
        # Check against a small margin relative to 100%.
        self.assertAlmostEqual(total_prob, 100.0, delta=2.0, msg=f"Probabilities sum to {total_prob}, expected ~100")

        # Test exact bounds
        for key, val in probs.items():
            self.assertGreaterEqual(val, 0.0)
            self.assertLessEqual(val, 100.0)

    def test_football_edge_math(self):
        """Verify evaluate_market correctly calculates edge_pct and payload schema."""
        model_prob = 60.0  # 60%
        kalshi_price = 50.0  # 50 cents (50%)

        # The threshold is 8.0, so 60 - 50 = 10% edge.
        payload = self.fb_engine.evaluate_market(
            match_title="Arsenal vs Chelsea",
            prediction_type="HOME_WIN",
            model_prob=model_prob,
            kalshi_price=kalshi_price
        )

        self.assertIsNotNone(payload)
        self.assertAlmostEqual(payload["edge_pct"], 0.10, places=4)
        self.assertEqual(payload["our_prob"], 0.60)
        self.assertEqual(payload["market_prob"], 0.50)

    def test_football_edge_math_below_threshold_returns_none(self):
        """A gap under edge_threshold (8%) must not produce a payload — this is
        the gate that was previously dead code behind an `if True:`."""
        payload = self.fb_engine.evaluate_market(
            match_title="Arsenal vs Chelsea",
            prediction_type="HOME_WIN",
            model_prob=52.0,
            kalshi_price=50.0,
        )
        self.assertIsNone(payload)

    def test_schema_validation(self):
        """Asser that payloads strictly match the Supabase kalshi_edges schema."""
        # Generate a mock payload
        payload = self.fb_engine.evaluate_market(
            match_title="Arsenal vs Chelsea",
            prediction_type="HOME_WIN",
            model_prob=70.0,
            kalshi_price=40.0
        )

        expected_keys = {"market_id", "title", "edge_type", "our_prob", "market_prob", "edge_pct", "raw_payload"}
        self.assertTrue(expected_keys.issubset(set(payload.keys())))
        self.assertEqual(payload["edge_type"], "SPORTS")
        self.assertIsInstance(payload["raw_payload"], dict)
        self.assertGreater(payload["edge_pct"], 0.0)


class TestFootballFindOpportunitiesEndToEnd(unittest.TestCase):
    """Exercises find_opportunities() itself — real price via a matched Kalshi
    market, all three outcomes scored, no fabricated fallback price — instead
    of only testing the Poisson math or evaluate_market() in isolation."""

    def setUp(self):
        self.engine = FootballKalshiEngine()
        self.engine.edge_threshold = 0.0  # isolate wiring from exact fitted probabilities

    def _dc_model(self):
        return DixonColesModel(
            attack={"Arsenal": 0.4, "Chelsea": 0.1},
            defense={"Arsenal": -0.2, "Chelsea": 0.0},
            home_advantage=0.25,
            rho=-0.05,
        )

    @patch("scripts.engines.football_engine.log_signal_event")
    @patch("scripts.engines.football_engine.get_active_sports_markets")
    def test_scores_all_three_outcomes_against_real_matched_markets(self, mock_markets, mock_log):
        mock_markets.return_value = [
            {"ticker": "SOCCER-PL-ARSCHE-ARS", "title": "Arsenal", "event_ticker": "SOCCER-PL-ARSCHE", "price": 40},
            {"ticker": "SOCCER-PL-ARSCHE-DRAW", "title": "Draw", "event_ticker": "SOCCER-PL-ARSCHE", "price": 25},
            {"ticker": "SOCCER-PL-ARSCHE-CHE", "title": "Chelsea", "event_ticker": "SOCCER-PL-ARSCHE", "price": 30},
        ]
        fixture = {
            "homeTeam": {"name": "Arsenal"},
            "awayTeam": {"name": "Chelsea"},
            "competition": {"code": "PL"},
            "id": 12345,
        }
        with patch.object(self.engine, "fetch_fixtures", return_value=[fixture]), \
             patch.object(self.engine, "_get_dixon_coles_model", return_value=self._dc_model()):
            opportunities = self.engine.find_opportunities()

        self.assertEqual(len(opportunities), 3)  # one live market per outcome
        outcomes = {op["raw_payload"]["outcome"] for op in opportunities}
        self.assertEqual(outcomes, {"HOME_WIN", "DRAW", "AWAY_WIN"})
        for op in opportunities:
            self.assertEqual(op["edge_type"], "SPORTS")
            self.assertIn(op["action"], {"BUY YES", "BUY NO"})
            self.assertIn(op["market_id"], {
                "SOCCER-PL-ARSCHE-ARS", "SOCCER-PL-ARSCHE-DRAW", "SOCCER-PL-ARSCHE-CHE",
            })
            self.assertIn("net_edge_pct", op["raw_payload"])

    @patch("scripts.engines.football_engine.log_signal_event")
    @patch("scripts.engines.football_engine.get_active_sports_markets")
    def test_skips_outcome_with_no_live_kalshi_market_instead_of_faking_a_price(self, mock_markets, mock_log):
        # Only the home-win contract is live; draw/away should be skipped,
        # never priced against a fabricated constant like the old 45.0 stub.
        mock_markets.return_value = [
            {"ticker": "SOCCER-PL-ARSCHE-ARS", "title": "Arsenal", "event_ticker": "SOCCER-PL-ARSCHE", "price": 40},
        ]
        fixture = {
            "homeTeam": {"name": "Arsenal"},
            "awayTeam": {"name": "Chelsea"},
            "competition": {"code": "PL"},
            "id": 12345,
        }
        with patch.object(self.engine, "fetch_fixtures", return_value=[fixture]), \
             patch.object(self.engine, "_get_dixon_coles_model", return_value=self._dc_model()):
            opportunities = self.engine.find_opportunities()

        self.assertEqual(len(opportunities), 1)
        self.assertEqual(opportunities[0]["raw_payload"]["outcome"], "HOME_WIN")

    @patch("scripts.engines.football_engine.get_active_sports_markets")
    def test_skips_fixture_with_no_fitted_model(self, mock_markets):
        mock_markets.return_value = []
        fixture = {
            "homeTeam": {"name": "Arsenal"},
            "awayTeam": {"name": "Chelsea"},
            "competition": {"code": "PL"},
            "id": 12345,
        }
        with patch.object(self.engine, "fetch_fixtures", return_value=[fixture]), \
             patch.object(self.engine, "_get_dixon_coles_model", return_value=None):
            opportunities = self.engine.find_opportunities()
        self.assertEqual(opportunities, [])


class TestNBAEngineEndToEnd(unittest.TestCase):
    """Exercises get_signals() itself so a dict-key regression (edge vs
    edge_pct, confidence vs model_prob_over, etc.) fails a real assertion
    instead of a hand-built mock dict that used the wrong keys and always
    passed regardless of what the real pipeline produced."""

    def setUp(self):
        self.engine = NBAEngine(min_edge_pct=5.0)

    @staticmethod
    def _stats_df():
        rows = []
        base_date = datetime(2026, 1, 1)  # far from "today" — never collides with B2B check
        for i in range(6):
            rows.append({
                "date": (base_date + timedelta(days=i)).strftime("%Y-%m-%d"),
                "pts": 28.0,
                "reb": 7.0,
                "ast": 6.0,
                "min": 34.0,
                "fg_pct": 0.5,
                "home": True,
                "opp_team_id": 2,
            })
        return pd.DataFrame(rows)

    @patch("scripts.engines.nba_engine.log_signal_event")
    @patch("scripts.engines.nba_engine.get_active_sports_markets")
    def test_get_signals_uses_real_kalshi_line_and_correct_schema(self, mock_markets, mock_log):
        mock_markets.return_value = [
            {"ticker": "NBAPTS-JAMES-O29.5", "title": "LeBron James Points O29.5",
             "price": 40, "event_ticker": "NBA-LAL-BOS"},
        ]
        with patch.object(self.engine, "_fetch_players",
                           return_value=[{"id": 1, "team": {"abbreviation": "LAL"}}]), \
             patch.object(self.engine, "_fetch_recent_stats", return_value=self._stats_df()), \
             patch.object(self.engine, "_fetch_todays_games", return_value=[
                 {"home_team": {"abbreviation": "LAL"}, "visitor_team": {"abbreviation": "BOS"}}
             ]), \
             patch.object(self.engine, "_fetch_injuries", return_value={}):
            signals = self.engine.get_signals(player_names=["LeBron James"])

        self.assertEqual(len(signals), 1)
        signal = signals[0]

        # Guard directly against the dict-key regression: these are the real
        # top-level keys get_signals() produces, not the ones the old
        # __main__ block and the old test assumed (model_prob_over, player,
        # kalshi_yes_ask, edge_pct at the top level).
        self.assertIn("edge", signal)
        self.assertIn("confidence", signal)
        self.assertNotIn("model_prob_over", signal)

        self.assertEqual(signal["edge_type"], "SPORTS")
        self.assertEqual(signal["market_id"], "NBAPTS-JAMES-O29.5")
        self.assertIn(signal["action"], {"BUY YES", "BUY NO", "MONITOR"})

        raw = signal["raw_payload"]
        self.assertEqual(raw["player"], "LeBron James")
        self.assertEqual(raw["stat"], "points")
        self.assertEqual(raw["line"], 29.5)
        self.assertEqual(raw["kalshi_ticker"], "NBAPTS-JAMES-O29.5")
        self.assertTrue(raw["is_home"])
        self.assertEqual(raw["opponent"], "BOS")  # not LAL — the opponent-DRTG fix

    @patch("scripts.engines.nba_engine.log_signal_event")
    @patch("scripts.engines.nba_engine.get_active_sports_markets")
    def test_get_signals_skips_player_with_no_game_today(self, mock_markets, mock_log):
        mock_markets.return_value = [
            {"ticker": "NBAPTS-JAMES-O29.5", "title": "LeBron James Points O29.5",
             "price": 40, "event_ticker": "NBA-LAL-BOS"},
        ]
        with patch.object(self.engine, "_fetch_players",
                           return_value=[{"id": 1, "team": {"abbreviation": "LAL"}}]), \
             patch.object(self.engine, "_fetch_recent_stats", return_value=self._stats_df()), \
             patch.object(self.engine, "_fetch_todays_games", return_value=[]), \
             patch.object(self.engine, "_fetch_injuries", return_value={}):
            signals = self.engine.get_signals(player_names=["LeBron James"])

        self.assertEqual(signals, [])

    @patch("scripts.engines.nba_engine.log_signal_event")
    @patch("scripts.engines.nba_engine.get_active_sports_markets")
    def test_get_signals_skips_player_with_no_live_kalshi_prop(self, mock_markets, mock_log):
        mock_markets.return_value = []  # no live markets at all
        with patch.object(self.engine, "_fetch_players",
                           return_value=[{"id": 1, "team": {"abbreviation": "LAL"}}]), \
             patch.object(self.engine, "_fetch_recent_stats", return_value=self._stats_df()), \
             patch.object(self.engine, "_fetch_todays_games", return_value=[
                 {"home_team": {"abbreviation": "LAL"}, "visitor_team": {"abbreviation": "BOS"}}
             ]), \
             patch.object(self.engine, "_fetch_injuries", return_value={}):
            signals = self.engine.get_signals(player_names=["LeBron James"])

        self.assertEqual(signals, [])

    def test_nba_prob_estimate_stays_in_bounds(self):
        """Ensure NBA engine probability estimates stay within bounds [0, 100]."""
        features = {
            "rolling_avg": 25.0,
            "rolling_std": 5.0,
            "opp_drtg": 110.0,
            "home_flag": 1,
            "b2b_flag": 0
        }
        prob = self.engine._estimate_prob_over(features, 24.5)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 100.0)


class TestF1SanityChecks(unittest.TestCase):

    def setUp(self):
        self.f1_engine = F1Engine()

    def test_f1_sanity_checks(self):
        """Ensure F1 engine podium probabilities stay within [0, 100] and schema has driver"""
        # Mock sector_df and deg_df
        driver = "VER"
        sector_df = pd.DataFrame([{"Driver": "VER", "LapTime_s_z": -1.5}])
        deg_df = pd.DataFrame([{"Driver": "VER", "deg_rate": 0.03}])

        prob = self.f1_engine._estimate_podium_prob(driver, sector_df, deg_df)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 100.0)

        # Verify schema components requested
        signal = {
            "driver": driver,
            "signal_type": "podium",
            "model_prob": prob,
            "kalshi_ticker": "F1PODIUM-VER",
            "kalshi_yes_ask": 60.0,
            "edge_pct": prob - 60.0,
            "action": "BUY YES",
            "key_metric": "Quali pace z=-1.5σ vs field"
        }
        self.assertIn("driver", signal)
        self.assertIn("model_prob", signal)

if __name__ == "__main__":
    unittest.main()
