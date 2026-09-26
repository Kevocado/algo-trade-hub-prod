"""Game -> Kalshi event mapping: versioned alias tables, ET-date event suffixes, honest unmatched reports."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from tradehub.sports.feed import FeedGame
from tradehub.sports.kalshi import SportsMarket

ALIASES_DIR = Path(__file__).resolve().parent / "aliases"
EASTERN = ZoneInfo("America/New_York")


@dataclass(frozen=True)
class Aliases:
    version: str
    teams: dict[str, str]   # predictor team name/code -> Kalshi code


@dataclass(frozen=True)
class MatchedGame:
    game: FeedGame
    home_code: str
    away_code: str
    suffix: str                                   # e.g. "26SEP27HOUIND"
    markets: dict[str, list[SportsMarket]]        # kind -> markets of this game's event
    date_shift_days: int = 0                      # Kalshi event date minus the feed's ET kickoff date


@dataclass
class MatchReport:
    matched: list[MatchedGame] = field(default_factory=list)
    unmatched_games: list[tuple[str, str]] = field(default_factory=list)   # (game_id, reason)
    unmatched_events: list[str] = field(default_factory=list)              # winner events with no feed game


def load_aliases(sport: str) -> Aliases:
    raw = json.loads((ALIASES_DIR / f"{sport}.json").read_text(encoding="utf-8"))
    return Aliases(version=raw["version"], teams=dict(raw["teams"]))


def kalshi_date(start_utc: datetime) -> str:
    """Kalshi dates game events by the US Eastern calendar day of kickoff: '26OCT01'."""
    return start_utc.astimezone(EASTERN).strftime("%y%b%d").upper()


def _by_suffix(markets: list[SportsMarket]) -> dict[str, list[SportsMarket]]:
    grouped: dict[str, list[SportsMarket]] = {}
    for sm in markets:
        grouped.setdefault(sm.market.event_ticker.split("-", 1)[1], []).append(sm)
    return grouped


def match_games(
    games: list[FeedGame], markets_by_series: dict[str, list[SportsMarket]], series: dict[str, str], aliases: Aliases,
) -> MatchReport:
    """Build each game's event suffix (ET date + away + home; home-first accepted too) and look it up
    in the open markets. Anything that doesn't line up exactly is reported, never guessed."""
    grouped = {kind: _by_suffix(markets_by_series.get(s, [])) for kind, s in series.items()}
    report = MatchReport()
    claimed: set[str] = set()
    for game in games:
        home, away = aliases.teams.get(game.home), aliases.teams.get(game.away)
        missing = [name for name, code in ((game.home, home), (game.away, away)) if code is None]
        if missing:
            report.unmatched_games.append((game.game_id, f"no_alias:{missing[0]}"))
            continue
        # Same ET day first; then +-1 day, because placeholder kickoff times (ESPN's 03:59Z "TBD")
        # can land on the wrong day. The same two teams a day apart are the same game.
        candidates = [
            (shift, f"{kalshi_date(game.start_utc + timedelta(days=shift))}{a}{b}")
            for shift in (0, 1, -1) for a, b in ((away, home), (home, away))
        ]
        found = next(((shift, c) for shift, c in candidates if any(c in g for g in grouped.values())), None)
        if found is None:
            report.unmatched_games.append((game.game_id, f"no_kalshi_event:{candidates[0][1]}"))
            continue
        shift, suffix = found
        claimed.add(suffix)
        report.matched.append(MatchedGame(
            game=game, home_code=home, away_code=away, suffix=suffix,
            markets={kind: grouped[kind].get(suffix, []) for kind in series}, date_shift_days=shift,
        ))
    feed_days = {kalshi_date(g.start_utc + timedelta(days=d)) for g in games for d in (0, 1, -1)}
    report.unmatched_events = sorted(
        f"{series['winner']}-{s}" for s in grouped["winner"] if s not in claimed and s[:7] in feed_days
    )
    return report
