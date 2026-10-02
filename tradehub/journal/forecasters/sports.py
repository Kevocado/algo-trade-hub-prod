"""Sports consumers (v2 spec §8 wave 3): the NFL and CFB predictors' frozen pre-game feeds, journaled.

The journal never re-models or re-settles a game. It consumes what `tradehub.sports.scan.run_sports_scan`
already prices from each predictor's `/api/kalshi-feed` (the same code path as the hub's sports board,
so the two cannot disagree), freezes that probability before kickoff, and settles on Kalshi's own market
result. Each sport also gets a market pseudo-forecaster (the Kalshi mid frozen at the same moment), so
the model's skill is measured against the price on exactly the same contracts.

One target per game: only `winner` markets, and of a game's two winner markets only the first in ASCII
ticker order. The two are exact complements, and spread/total lines on one game are correlated; counting
them as separate targets would inflate the settled count the gate is judged on. The rule never looks at
the forecast.

Spread and total consumers (plan 11) follow the same shape with a different pick rule, because a game has a
ladder of strikes per team and every rung of one game is the same bet restated: only the rung the market
prices nearest a coin flip is journaled (`one_rung`), chosen from the Kalshi mid alone, never from the
forecast. Each kind is its own forecaster name, so winners, spreads and totals are scored apart; the winner
keys are unchanged.

The forecaster version is `feed-v1` and stays put when the predictor retrains: the predictor's own
`model_version` is recorded in each row's payload, so the journal's key is the consumer, not the model.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

from tradehub.core.kalshi_feed import fetch_market
from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.kalshi_linked import FREEZE_LEAD, kalshi_target, settle_on_kalshi
from tradehub.sports.kalshi import SportsKalshi
from tradehub.sports.scan import SportsRun, run_sports_scan

SPORTS = ("nfl", "cfb")
KINDS = ("winner", "spread", "total")
FEED_VERSION = "feed-v1"
SCAN_BUDGET_SECONDS = 600.0


def _default_scan(sport: str) -> Callable[[datetime], SportsRun]:
    def scan(now: datetime) -> SportsRun:
        deadline = time.monotonic() + SCAN_BUDGET_SECONDS
        return run_sports_scan(now, SportsKalshi(deadline=deadline), sports=(sport,), deadline=deadline)
    return scan


def one_per_game(predictions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """{ticker: prediction row}: winner markets only, the first ticker (ASCII) of each game."""
    chosen: dict[str, dict[str, Any]] = {}
    for row in predictions:
        payload = row.get("raw_payload") or {}
        if payload.get("kind") != "winner":
            continue
        game = payload["game_id"]
        if game not in chosen or row["market_ticker"] < chosen[game]["market_ticker"]:
            chosen[game] = row
    return {row["market_ticker"]: row for row in chosen.values()}


def one_rung(predictions: list[dict[str, Any]], kind: str) -> dict[str, dict[str, Any]]:
    """{ticker: prediction row}: per game, the one `kind` market whose Kalshi mid is nearest 0.5.

    Ties go to the first ticker (ASCII). A row with no mid has no baseline and is never chosen. The rule
    reads only the market's price, so the forecast cannot influence which rung is journaled.
    """
    chosen: dict[str, dict[str, Any]] = {}
    for row in predictions:
        payload = row.get("raw_payload") or {}
        if payload.get("kind") != kind or row.get("market_prob") is None:
            continue
        game = payload["game_id"]
        rank = (abs(float(row["market_prob"]) - 0.5), row["market_ticker"])
        best = chosen.get(game)
        if best is None or rank < (abs(float(best["market_prob"]) - 0.5), best["market_ticker"]):
            chosen[game] = row
    return {row["market_ticker"]: row for row in chosen.values()}


class SportsSnapshot:
    """One sport's priced markets, scanned at most once per hourly run and shared by every forecaster."""

    def __init__(self, sport: str, scan: Callable[[datetime], SportsRun] | None = None):
        self.sport = sport
        self._scan = scan or _default_scan(sport)
        self._hour: datetime | None = None
        self._rows: dict[str, dict[str, dict[str, Any]]] = {}

    def rows(self, now: datetime, kind: str = "winner") -> dict[str, dict[str, Any]]:
        hour = now.replace(minute=0, second=0, microsecond=0)
        if self._hour != hour:
            predictions = self._scan(now).predictions
            self._rows = {"winner": one_per_game(predictions),
                          "spread": one_rung(predictions, "spread"), "total": one_rung(predictions, "total")}
            self._hour = hour
        return self._rows[kind]


def _start(row: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(row["raw_payload"]["start_utc"])


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    p = row["raw_payload"]
    out = {"sport": p["sport"], "game_id": p["game_id"], "kind": p["kind"], "start_utc": p["start_utc"],
           "snapshotted_at": p["snapshotted_at"], "model_version": p.get("model_version"),
           "yes_bid": p.get("yes_bid"), "yes_ask": p.get("yes_ask")}
    if p["kind"] != "winner":   # which way YES points, frozen with the forecast
        team, strike = p.get("team"), p.get("strike")
        out |= {"strike": strike, "team": team, "home": p.get("home"), "away": p.get("away"),
                "yes_means": (f"{team} wins by more than {strike:g}" if p["kind"] == "spread"
                              else f"total points above {strike:g}")}
    return out


class _SportsBase:
    cadence = "daily"
    version: str
    name: str

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
                 kind: str = "winner"):
        if kind not in KINDS:
            raise ValueError(f"unknown sports kind {kind!r}")
        self._snapshot, self._fetch_market, self.kind = snapshot, fetch, kind
        self.suffix = "" if kind == "winner" else f"_{kind}"
        self.family = f"sports_{snapshot.sport}{self.suffix}"

    def targets(self, now: datetime) -> list[CalendarEntry]:
        out = []
        for ticker, row in self._snapshot.rows(now, self.kind).items():
            start = _start(row)
            if now < start <= now + FREEZE_LEAD:
                out.append(CalendarEntry(kalshi_target(ticker), self.family, self.cadence, start, market_linked=True))
        return out

    def _row(self, entry: CalendarEntry, now: datetime) -> dict[str, Any] | None:
        return self._snapshot.rows(now, self.kind).get(entry.target.removeprefix("kalshi:"))

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_on_kalshi(target, self._fetch_market)


class SportsFeedForecaster(_SportsBase):
    """The predictor's frozen pre-game probability for the game's winner market."""

    version = FEED_VERSION

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
                 kind: str = "winner"):
        super().__init__(snapshot, fetch, kind)
        self.name = f"sports_{snapshot.sport}{self.suffix}"

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        row = self._row(entry, now)
        if row is None:
            return None
        return Forecast(self.name, self.version, entry.target, float(row["our_prob"]),
                        market_prob=row.get("market_prob"), payload=_payload(row))


class SportsMarketImplied(_SportsBase):
    """The Kalshi mid for the same contract, frozen at the same moment: the baseline the feed is graded against."""

    version = "v1"

    def __init__(self, snapshot: SportsSnapshot, fetch: Callable[[str], Any] = fetch_market,
                 kind: str = "winner"):
        super().__init__(snapshot, fetch, kind)
        self.name = f"kalshi_implied_sports_{snapshot.sport}{self.suffix}"

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        row = self._row(entry, now)
        if row is None or row.get("market_prob") is None:
            return None
        return Forecast(self.name, self.version, entry.target, float(row["market_prob"]),
                        market_prob=float(row["market_prob"]), payload=_payload(row))


def build_sports(scans: dict[str, Callable[[datetime], SportsRun]] | None = None) -> list[_SportsBase]:
    out: list[_SportsBase] = []
    for sport in SPORTS:
        snapshot = SportsSnapshot(sport, (scans or {}).get(sport))
        for kind in KINDS:
            out += [SportsFeedForecaster(snapshot, kind=kind), SportsMarketImplied(snapshot, kind=kind)]
    return out


__all__ = ["SportsFeedForecaster", "SportsMarketImplied", "SportsSnapshot", "build_sports", "one_per_game", "one_rung"]
