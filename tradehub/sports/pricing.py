"""YES probability for each Kalshi sports market from the predictor's frozen distribution.

The hub never models sports: winner markets use the predictor's own p_home; spread and
total markets evaluate its Normal(margin_mu, sigma) / Normal(total_mu, total_sigma) at
Kalshi's half-point strikes (so no continuity correction is needed).
"""

from __future__ import annotations

import math

from tradehub.markets import prob_in_interval
from tradehub.sports.kalshi import SportsMarket, team_code
from tradehub.sports.mapping import MatchedGame


def price_market(kind: str, sm: SportsMarket, mg: MatchedGame) -> float | None:
    game = mg.game
    code = team_code(sm)
    if kind == "winner":
        if code == mg.home_code:
            return game.p_home
        if code == mg.away_code:
            return 1.0 - game.p_home
        return None
    strike = sm.market.floor_strike
    if sm.market.strike_type != "greater" or strike is None:
        return None
    if kind == "spread":
        if game.margin_mu is None or not game.sigma:
            return None
        if code == mg.home_code:   # home wins by more than the strike
            return prob_in_interval(game.margin_mu, game.sigma, (strike, math.inf))
        if code == mg.away_code:   # away wins by more than the strike
            return prob_in_interval(game.margin_mu, game.sigma, (-math.inf, -strike))
        return None
    if kind == "total":
        if game.total_mu is None or not game.total_sigma:
            return None
        return prob_in_interval(game.total_mu, game.total_sigma, (strike, math.inf))
    return None


def home_oriented(kind: str, sm: SportsMarket, mg: MatchedGame, yes_prob: float) -> float:
    """The YES probability restated the way the predictor's calibration buckets are keyed:
    home win / home cover / over. Away-team markets flip."""
    if kind in ("winner", "spread") and team_code(sm) == mg.away_code:
        return 1.0 - yes_prob
    return yes_prob
