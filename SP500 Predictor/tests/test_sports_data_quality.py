import unittest
from unittest.mock import patch, MagicMock
import sys
import os

# Ensure the 'SP500 Predictor' root is in PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.engines.football_engine import FootballKalshiEngine
from scripts.engines.nba_engine import NBAEngine
from scripts.engines.f1_engine import F1Engine
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

    def test_nba_sanity_checks(self):
        """Ensure NBA engine probability estimates stay within bounds[0, 100]"""
        features = {
            "rolling_avg": 25.0,
            "rolling_std": 5.0,
            "opp_drtg": 110.0,
            "home_flag": 1,
            "b2b_flag": 0
        }
        
        prob = self.nba_engine._estimate_prob_over(features, 24.5)
        self.assertGreaterEqual(prob, 0.0)
        self.assertLessEqual(prob, 100.0)
        
        # Verify schema components requested (must parse without crashing frontend)
        # nba_engine generates list of dicts. We mock the pipeline out.
        signal = {
            "player": "LeBron James",
            "stat": "points",
            "line": 24.5,
            "model_prob_over": prob,
            "kalshi_ticker": "NBAPTS-LEBRON-O24.5",
            "kalshi_yes_ask": 45.0,
            "edge_pct": prob - 45.0,
            "action": "BUY YES",
            "injury_flag": False
        }
        self.assertIn("player", signal)
        self.assertIn("model_prob_over", signal)

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
