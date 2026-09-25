"""Client for a predictor's GET /api/kalshi-feed (frozen pre-game snapshots + calibration)."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import requests

FEED_PATH = "/api/kalshi-feed"
TIMEOUT_SECONDS = 60.0
RETRY_PAUSE_SECONDS = 2.0


class FeedUnavailable(RuntimeError):
    """The predictor could not serve its feed (down, cold, or not deployed yet)."""


@dataclass(frozen=True)
class FeedGame:
    sport: str
    game_id: str
    home: str
    away: str
    start_utc: datetime
    p_home: float
    margin_mu: float | None
    sigma: float | None
    total_mu: float | None
    total_sigma: float | None
    model_version: str | None
    snapshotted_at: datetime
    season: int | None = None
    week: int | None = None


@dataclass(frozen=True)
class Feed:
    sport: str
    generated_at: datetime
    games: list[FeedGame]
    calibration: dict[str, list[dict[str, Any]]]
    rejected: list[dict[str, str]] = field(default_factory=list)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _opt(value: Any) -> float | None:
    return None if value is None else float(value)


def parse_feed(raw: dict[str, Any]) -> Feed:
    """Validate the feed. Rows that are backfilled or not strictly pre-kickoff are
    dropped here too (defense in depth: the predictor already filters them)."""
    sport = raw["sport"]
    games: list[FeedGame] = []
    rejected: list[dict[str, str]] = []
    for row in raw.get("games") or []:
        game_id = str(row.get("game_id"))
        try:
            start, snapshotted = _utc(row["start_utc"]), _utc(row["snapshotted_at"])
            p_home = float(row["p_home"])
        except (KeyError, TypeError, ValueError):
            rejected.append({"game_id": game_id, "reason": "malformed"})
            continue
        if row.get("backfilled"):
            rejected.append({"game_id": game_id, "reason": "backfilled"})
        elif snapshotted >= start:
            rejected.append({"game_id": game_id, "reason": "snapshot_not_pregame"})
        elif not 0.0 <= p_home <= 1.0:
            rejected.append({"game_id": game_id, "reason": "bad_probability"})
        else:
            games.append(FeedGame(
                sport=sport, game_id=game_id, home=row["home"], away=row["away"], start_utc=start,
                p_home=p_home, margin_mu=_opt(row.get("margin_mu")), sigma=_opt(row.get("sigma")),
                total_mu=_opt(row.get("total_mu")), total_sigma=_opt(row.get("total_sigma")),
                model_version=row.get("model_version"), snapshotted_at=snapshotted,
                season=row.get("season"), week=row.get("week"),
            ))
    calibration = raw.get("calibration") or {}
    return Feed(
        sport=sport,
        generated_at=_utc(raw["generated_at"]),
        games=games,
        calibration={k: calibration.get(k) or [] for k in ("winner", "spread", "total")},
        rejected=rejected,
    )


def fetch_feed(
    base_url: str, *, get: Callable[..., Any] = requests.get, sleep: Callable[[float], None] = time.sleep,
    timeout: float = TIMEOUT_SECONDS,
) -> Feed:
    """GET the feed with one retry: scale-to-zero predictors can time out on the first request."""
    url = base_url.rstrip("/") + FEED_PATH
    last_error: Exception | None = None
    for attempt in range(2):
        if attempt:
            sleep(RETRY_PAUSE_SECONDS)
        try:
            resp = get(url, timeout=timeout)
            resp.raise_for_status()
            return parse_feed(resp.json())
        except (requests.RequestException, ValueError, KeyError) as exc:
            last_error = exc
    raise FeedUnavailable(f"{url}: {last_error}")
