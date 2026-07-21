"""
dixon_coles.py — Dixon & Coles (1997) football scoring model.

Independent-Poisson goal models systematically underestimate draws and
narrow-margin scorelines (0-0, 1-0, 0-1, 1-1) because real matches are not
independent Poisson processes — a team already leading tends to ease off,
a team chasing the game tends to open up. Dixon-Coles corrects exactly
those four cells with a single low-score correlation parameter (rho) on
top of team attack/defense strengths and a home-advantage term, all fit by
maximum likelihood. This module also applies the paper's exponential
time-decay weighting so recent matches count more than matches from
months ago, instead of every match in a season counting equally.

Reference: Dixon, M.J. and Coles, S.G. (1997), "Modelling Association
Football Scores and Inefficiencies in the Football Betting Market."
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from math import exp

import numpy as np
from scipy.optimize import minimize
from scipy.stats import poisson

DEFAULT_XI = 0.0018  # per-day time decay rate used in the original paper
MAX_GOALS = 10
MIN_MATCHES = 30
MIN_TEAMS = 4


def _tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score correlation correction for cells (0,0)/(0,1)/(1,0)/(1,1)."""
    if x == 0 and y == 0:
        return 1.0 - lam * mu * rho
    if x == 0 and y == 1:
        return 1.0 + lam * rho
    if x == 1 and y == 0:
        return 1.0 + mu * rho
    if x == 1 and y == 1:
        return 1.0 - rho
    return 1.0


@dataclass
class DixonColesModel:
    attack: dict[str, float]
    defense: dict[str, float]
    home_advantage: float
    rho: float

    @property
    def teams(self) -> set[str]:
        return set(self.attack.keys())

    def expected_goals(self, home_team: str, away_team: str) -> tuple[float, float]:
        """Returns (lambda, mu): expected goals for the home and away side."""
        lam = exp(self.attack[home_team] + self.defense[away_team] + self.home_advantage)
        mu = exp(self.attack[away_team] + self.defense[home_team])
        return lam, mu

    def score_grid(self, home_team: str, away_team: str, max_goals: int = MAX_GOALS) -> np.ndarray:
        """Returns a (max_goals+1) x (max_goals+1) probability grid, tau-adjusted and renormalized."""
        lam, mu = self.expected_goals(home_team, away_team)
        home_probs = poisson.pmf(np.arange(max_goals + 1), lam)
        away_probs = poisson.pmf(np.arange(max_goals + 1), mu)
        grid = np.outer(home_probs, away_probs)
        for x in (0, 1):
            for y in (0, 1):
                grid[x, y] *= _tau(x, y, lam, mu, self.rho)
        grid = np.clip(grid, 0.0, None)
        total = grid.sum()
        if total > 0:
            grid = grid / total
        return grid

    def match_probabilities(self, home_team: str, away_team: str, max_goals: int = MAX_GOALS) -> dict[str, float]:
        """Returns {"HOME_WIN": pct, "DRAW": pct, "AWAY_WIN": pct} summing to ~100.0."""
        grid = self.score_grid(home_team, away_team, max_goals=max_goals)
        home_win = float(np.tril(grid, -1).sum())
        draw = float(np.trace(grid))
        away_win = float(np.triu(grid, 1).sum())
        return {
            "HOME_WIN": home_win * 100.0,
            "DRAW": draw * 100.0,
            "AWAY_WIN": away_win * 100.0,
        }


def _match_weight(match_date: datetime | None, reference: datetime, xi: float) -> float:
    if match_date is None or xi <= 0:
        return 1.0
    days = max((reference - match_date).days, 0)
    return exp(-xi * days)


def fit_dixon_coles(
    matches: list[dict],
    *,
    xi: float = DEFAULT_XI,
    reference_date: datetime | None = None,
    max_iter: int = 200,
) -> DixonColesModel:
    """
    Fits team attack/defense strengths, home advantage, and rho by maximum
    likelihood, with exponential time-decay weighting by match recency.

    Args:
        matches: list of {"home": str, "away": str, "home_goals": int,
                  "away_goals": int, "date": datetime | None}.
        xi: per-day decay rate (0 disables recency weighting).
        reference_date: "today" for decay purposes; defaults to the most
                  recent match date in the data.
        max_iter: optimizer iteration cap.

    Raises:
        ValueError: fewer than MIN_TEAMS distinct teams in the data.
    """
    if not matches:
        raise ValueError("Cannot fit Dixon-Coles on an empty match list.")

    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    n = len(teams)
    if n < MIN_TEAMS:
        raise ValueError(f"Need at least {MIN_TEAMS} distinct teams to fit Dixon-Coles, got {n}.")
    idx = {team: i for i, team in enumerate(teams)}

    dated = [m.get("date") for m in matches if m.get("date") is not None]
    reference = reference_date or (max(dated) if dated else datetime.utcnow())
    weights = np.array([_match_weight(m.get("date"), reference, xi) for m in matches])

    home_idx = np.array([idx[m["home"]] for m in matches])
    away_idx = np.array([idx[m["away"]] for m in matches])
    home_goals = np.array([m["home_goals"] for m in matches], dtype=float)
    away_goals = np.array([m["away_goals"] for m in matches], dtype=float)

    # Parameter vector x = [attack_0..attack_{n-2}, defense_0..defense_{n-1}, home_adv, rho]
    # The last team's attack is derived as -sum(others) to fix the additive
    # scale ambiguity between attack and defense (Dixon-Coles is only
    # identified up to a shift without this constraint).
    def unpack(x):
        attack = np.concatenate([x[: n - 1], [-np.sum(x[: n - 1])]])
        defense = x[n - 1: 2 * n - 1]
        home_adv = x[2 * n - 1]
        rho = x[2 * n]
        return attack, defense, home_adv, rho

    def neg_log_likelihood(x):
        attack, defense, home_adv, rho = unpack(x)
        lam = np.exp(attack[home_idx] + defense[away_idx] + home_adv)
        mu = np.exp(attack[away_idx] + defense[home_idx])
        ll = poisson.logpmf(home_goals, lam) + poisson.logpmf(away_goals, mu)

        tau_adj = np.ones_like(ll)
        low_score_mask = (home_goals <= 1) & (away_goals <= 1)
        low_score_positions = np.where(low_score_mask)[0]
        for i in low_score_positions:
            t = _tau(int(home_goals[i]), int(away_goals[i]), lam[i], mu[i], rho)
            tau_adj[i] = t if t > 1e-6 else 1e-6
        ll = ll + np.log(tau_adj)

        return -float(np.sum(weights * ll))

    x0 = np.zeros(2 * n + 1)
    x0[2 * n - 1] = 0.2   # home advantage starting guess
    x0[2 * n] = -0.05     # rho starting guess

    bounds = [(-3.0, 3.0)] * (2 * n - 1) + [(-1.0, 1.0)] + [(-0.2, 0.2)]

    result = minimize(
        neg_log_likelihood,
        x0,
        method="L-BFGS-B",
        bounds=bounds,
        options={"maxiter": max_iter},
    )

    attack, defense, home_adv, rho = unpack(result.x)
    return DixonColesModel(
        attack=dict(zip(teams, attack.tolist())),
        defense=dict(zip(teams, defense.tolist())),
        home_advantage=float(home_adv),
        rho=float(rho),
    )
