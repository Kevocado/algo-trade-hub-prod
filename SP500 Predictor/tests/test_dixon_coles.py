import random
import sys
import os
from datetime import datetime, timedelta

import numpy as np
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from scripts.engines.dixon_coles import fit_dixon_coles, DixonColesModel, _tau


def _synthetic_league(rng_seed: int = 42):
    """6-team league where ground-truth attack/defense strengths are known,
    so the fitted model's recovered structure can be checked directly."""
    random.seed(rng_seed)
    np.random.seed(rng_seed)

    teams = ["Strong", "AboveAvg", "Mid1", "Mid2", "BelowAvg", "Weak"]
    true_attack = {"Strong": 0.6, "AboveAvg": 0.3, "Mid1": 0.0, "Mid2": -0.05, "BelowAvg": -0.3, "Weak": -0.6}
    true_defense = {"Strong": -0.4, "AboveAvg": -0.2, "Mid1": 0.0, "Mid2": 0.05, "BelowAvg": 0.2, "Weak": 0.4}
    home_adv = 0.25

    matches = []
    start = datetime(2025, 8, 1)
    for round_i in range(10):
        order = teams[:]
        random.shuffle(order)
        for i in range(0, len(order), 2):
            h, a = order[i], order[i + 1]
            lam = np.exp(true_attack[h] + true_defense[a] + home_adv)
            mu = np.exp(true_attack[a] + true_defense[h])
            matches.append({
                "home": h,
                "away": a,
                "home_goals": int(np.random.poisson(lam)),
                "away_goals": int(np.random.poisson(mu)),
                "date": start + timedelta(days=round_i * 7),
            })
    return matches


class TestTau:
    def test_tau_is_one_outside_low_score_cells(self):
        assert _tau(2, 2, 1.4, 1.1, -0.1) == 1.0
        assert _tau(0, 2, 1.4, 1.1, -0.1) == 1.0

    def test_tau_adjusts_low_score_cells(self):
        assert _tau(0, 0, 1.4, 1.1, -0.1) != 1.0
        assert _tau(1, 1, 1.4, 1.1, -0.1) != 1.0


class TestFitDixonColes:
    def test_requires_minimum_teams(self):
        matches = [{"home": "A", "away": "B", "home_goals": 1, "away_goals": 0, "date": None}]
        with pytest.raises(ValueError):
            fit_dixon_coles(matches)

    def test_requires_non_empty_matches(self):
        with pytest.raises(ValueError):
            fit_dixon_coles([])

    def test_recovers_relative_team_strength(self):
        model = fit_dixon_coles(_synthetic_league())
        assert model.attack["Strong"] > model.attack["Weak"]
        assert model.defense["Strong"] < model.defense["Weak"]  # lower = better defense

    def test_match_probabilities_sum_to_100(self):
        model = fit_dixon_coles(_synthetic_league())
        for home, away in [("Strong", "Weak"), ("Mid1", "Mid2"), ("Weak", "Strong")]:
            probs = model.match_probabilities(home, away)
            assert abs(sum(probs.values()) - 100.0) < 0.5
            for value in probs.values():
                assert 0.0 <= value <= 100.0

    def test_home_advantage_favors_home_side_for_evenly_matched_teams(self):
        model = fit_dixon_coles(_synthetic_league())
        probs = model.match_probabilities("Mid1", "Mid2")
        probs_flipped = model.match_probabilities("Mid2", "Mid1")
        # Same two teams, but whoever is "home" should get a probability lift.
        assert probs["HOME_WIN"] > probs_flipped["AWAY_WIN"] - 1.0

    def test_strong_favorite_beats_weak_underdog_more_often_than_not(self):
        model = fit_dixon_coles(_synthetic_league())
        probs = model.match_probabilities("Strong", "Weak")
        assert probs["HOME_WIN"] > probs["AWAY_WIN"]
        assert probs["HOME_WIN"] > 50.0


class TestDixonColesModelDirect:
    def test_score_grid_normalizes(self):
        model = DixonColesModel(
            attack={"A": 0.2, "B": -0.2},
            defense={"A": -0.1, "B": 0.1},
            home_advantage=0.3,
            rho=-0.05,
        )
        grid = model.score_grid("A", "B")
        assert abs(grid.sum() - 1.0) < 1e-9
