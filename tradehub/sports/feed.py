"""Client for a predictor's GET /api/kalshi-feed (frozen pre-game snapshots + calibration)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import requests

from tradehub.sports.deadline import remaining_seconds
from tradehub.sports.kinds import KINDS, unrecognised

log = logging.getLogger(__name__)

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
    # How many bands the predictor cut its own calibration into, read off the payload. Zero means the
    # feed published no calibration at all, which is a different fact from one that published an
    # empty one.
    #
    # Read rather than assumed, because it is the predictor's setting and it is moving: the
    # 2026-09-27 ruling makes it 4, from 10, in NFL_Predictor and CFB_Predictor. Anything standing in
    # for the published record has to be cut on the SAME edges, so the count has to come from the
    # payload -- a hub-side copy of the number is a number that silently disagrees.
    n_buckets: int = 0
    # The names in the payload's `calibration` mapping that are neither a known kind nor a published
    # scalar, sorted. `[]` when there were none, which is a measurement; see the note below.
    #
    # Carried as data rather than left to the `log.warning` that was the whole report, because a log
    # line in this codebase is demonstrably not an observed channel (`sports/kinds.py` spells out
    # how: this repo upserted to four tables that never existed with bare `print()`s for
    # the life of the system). The ledger side of the same problem already rides a `per_sport` key,
    # and a build gap that is reported in one place and logged in the other is a gap a reader learns
    # to distrust. This one is the worse of the two: an unreadable kind on the FEED side means every
    # edge of that kind is judged on no band at all, with no diagnostic anywhere a human looks.
    unrecognised_kinds: list[str] = field(default_factory=list)


# The names the payload may publish in `calibration` that are not kinds. `n_buckets` is the
# predictor's setting rather than a band set, so it is not a kind and must not be tallied as one.
#
# The set is EXACT: a new scalar the payload starts publishing is itself an unread name, and that is
# the honest report -- this build has not been taught to read it. The `log.warning` used to call the
# result "kind(s) this build does not recognise", which claimed more than it detected; it now says
# "name(s) ... not recognised as a kind or a published scalar", which is exactly what
# `set(calibration) - _PUBLISHED_SCALARS` measures.
#
# Recorded payloads carry exactly `n_buckets, spread, total, winner`, so this is future-facing: the
# payoff is that the day a fifth key appears, the run summary says so rather than the log saying so
# to a channel nobody reads. No migration and no code change would be needed to notice the drift.
_PUBLISHED_SCALARS = frozenset({"n_buckets"})


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
    # The kinds to read are `sports.kinds.KINDS`, the same object the hub's settled ledger is filtered
    # against, so a fourth kind is added in one place rather than in a second copy here that nothing
    # ties to the first. Reading the payload off an inlined triple is what let the two drift.
    buckets = {k: calibration.get(k) or [] for k in KINDS}
    # A name the payload publishes that this build does not know is not read, and it must not be
    # dropped without a word: its edges would be judged on no band, or on another kind's, and
    # nothing downstream could tell that apart from a predictor that simply published no history for
    # it. So say which names, in TWO places at once -- the log line below, which is immediate and
    # per-fetch, and `Feed.unrecognised_kinds`, which rides into the run summary as a `per_sport` key
    # (`scan.DIAGNOSTIC_KEYS`). The second is the one a human reads; see that field.
    extra = unrecognised(set(calibration) - _PUBLISHED_SCALARS)
    if extra:
        log.warning("sports feed %s: published calibration carries %d name(s) this build does not "
                    "recognise as a kind or a published scalar (%s). They are not read, so edges of "
                    "kinds this build cannot place are judged on no band at all -- this is a build "
                    "that does not know the name, not a kind with nothing settled. Adding the kind to "
                    "tradehub/sports/kinds.py is the fix. The same list is published in the run "
                    "summary as per_sport[...]['feed_unrecognised_kinds'].",
                    sport, len(extra), ", ".join(extra))
    # The published count, and if the field is absent then the number of buckets actually published
    # -- the same fact, read a different way, rather than a default that might not match the edges.
    n_buckets = calibration.get("n_buckets")
    if not isinstance(n_buckets, int) or n_buckets <= 0:
        n_buckets = max((len(v) for v in buckets.values()), default=0)
    return Feed(
        sport=sport,
        generated_at=_utc(raw["generated_at"]),
        games=games,
        calibration=buckets,
        rejected=rejected,
        n_buckets=n_buckets,
        unrecognised_kinds=extra,
    )


def fetch_feed(
    base_url: str, *, get: Callable[..., Any] = requests.get, sleep: Callable[[float], None] = time.sleep,
    timeout: float = TIMEOUT_SECONDS, deadline: float | None = None,
) -> Feed:
    """GET the feed with one retry: scale-to-zero predictors can time out on the first request.

    The retry is bounded by the scan budget too. An unconditional retry after a 60s timeout means
    up to 122 seconds of predictor call inside a 15-minute scan that also has to serve the other
    engines, so when less than one attempt fits in what is left the second attempt is never
    started. Each attempt's timeout is clamped to the time remaining, because a request allowed to
    wait its full timeout is a request that can sit past the deadline.
    """
    url = base_url.rstrip("/") + FEED_PATH
    last_error: Exception | None = None
    for attempt in range(2):
        left = remaining_seconds(deadline) if deadline is not None else None
        if left is not None and left <= 0:
            raise FeedUnavailable(f"{url}: scan deadline reached before the feed fetch")
        per_attempt = min(timeout, left) if left is not None else timeout
        if attempt:
            if left is not None and left < per_attempt + RETRY_PAUSE_SECONDS:
                log.warning("sports feed %s: %0.1fs of scan budget left, not enough for a retry "
                            "(one attempt needs %0.1fs)", url, left, per_attempt)
                break
            sleep(RETRY_PAUSE_SECONDS if left is None else min(RETRY_PAUSE_SECONDS, left))
            left = remaining_seconds(deadline) if deadline is not None else None
            if left is not None and left <= 0:
                break
            per_attempt = min(timeout, left) if left is not None else timeout
        try:
            resp = get(url, timeout=per_attempt)
            resp.raise_for_status()
            return parse_feed(resp.json())
        except (requests.RequestException, ValueError, KeyError) as exc:
            last_error = exc
    raise FeedUnavailable(f"{url}: {last_error}")
