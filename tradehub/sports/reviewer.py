"""LLM reviewer (spec §3.2 stage 2): an OpenRouter free model reads a public fact pack for each
candidate and answers strict JSON {explainable, drivers, red_flags}. It never produces or changes
a probability; any failure leaves the edge "unreviewed" and never blocks it."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

import requests

log = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
REVIEWS_TABLE = "sports_reviews"
# Sentinel for "the daily call count is unknown"; any real budget is smaller than this.
_BUDGET_UNKNOWN = 10**9

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "explainable": {"type": "boolean"},
        "drivers": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
        "red_flags": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["explainable", "drivers", "red_flags"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You review a sports prediction-market edge for a human trader. You get a fact pack: a predictor's "
    "frozen pre-game probability and point distribution, the Kalshi price, and how well calibrated the "
    "predictor has been in this probability range. Decide whether the gap between the predictor and the "
    "market is explainable from these facts. List the concrete drivers from the fact pack. List red flags: "
    "anything that could make the predictor stale or wrong that the fact pack cannot show (injuries, "
    "lineup news, weather, how old the snapshot is). Never give a probability or a number of your own. "
    "Answer with JSON only."
)


@dataclass(frozen=True)
class Review:
    status: str                    # ok | invalid | error | skipped_budget | no_key
    explainable: bool | None
    drivers: tuple[str, ...]
    red_flags: tuple[str, ...]
    model: str | None = None


@dataclass(frozen=True)
class ReviewRequest:
    key: str
    sport: str
    game_id: str
    market_ticker: str
    side: str
    entry_price: float
    price_bucket: int
    our_prob: float
    net_edge_pct: float
    fact_pack: dict[str, Any]


def _unreviewed(status: str, model: str | None = None) -> Review:
    return Review(status=status, explainable=None, drivers=(), red_flags=(), model=model)


def parse_review(content: str, model: str | None = None) -> Review:
    """Validate the model's answer against REVIEW_SCHEMA by hand (never trust the provider)."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return _unreviewed("invalid", model)
    if not isinstance(data, dict) or set(data) != {"explainable", "drivers", "red_flags"}:
        return _unreviewed("invalid", model)
    explainable, drivers, flags = data["explainable"], data["drivers"], data["red_flags"]
    if not isinstance(explainable, bool):
        return _unreviewed("invalid", model)
    for items in (drivers, flags):
        if not isinstance(items, list) or len(items) > 5 or not all(isinstance(i, str) for i in items):
            return _unreviewed("invalid", model)
    return Review(status="ok", explainable=explainable, drivers=tuple(drivers), red_flags=tuple(flags), model=model)


def tier(review: Review | None) -> str:
    """Top Pick only when reviewed, explainable and free of red flags (spec §3.2)."""
    if review is None or review.status != "ok":
        return "unreviewed"
    if review.explainable and not review.red_flags:
        return "top_pick"
    return "flagged"


def price_bucket(entry_price: float, cents: int) -> int:
    return int(round(entry_price * 100)) // cents


def cache_key(sport: str, game_id: str, market_ticker: str, side: str, bucket: int) -> str:
    return f"{sport}:{game_id}:{market_ticker}:{side}:{bucket}"


class OpenRouterReviewer:
    def __init__(self, api_key: str, model: str, timeout: float, post: Callable[..., Any] = requests.post):
        self._key, self.model, self._timeout, self._post = api_key, model, timeout, post

    def review(self, fact_pack: dict[str, Any]) -> Review:
        body = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(fact_pack, sort_keys=True)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "sports_edge_review", "strict": True, "schema": REVIEW_SCHEMA},
            },
            # Only route to providers that honour response_format; the free router may otherwise ignore it.
            "provider": {"require_parameters": True},
        }
        try:
            resp = self._post(OPENROUTER_URL, headers={"Authorization": f"Bearer {self._key}"}, json=body,
                              timeout=self._timeout)
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
        except (requests.RequestException, ValueError, KeyError, IndexError, TypeError):
            return _unreviewed("error", self.model)
        return parse_review(content, self.model)


class ReviewStore(Protocol):
    def cached(self, key: str) -> Review | None: ...
    def calls_since(self, since: datetime) -> int: ...
    def save(self, request: ReviewRequest, review: Review) -> None: ...


class SupabaseReviewStore:
    """Append-only `sports_reviews` table: every API call is one row (so the daily count is exact);
    only status='ok' rows are served from the cache. Supabase, not a local file, because the VPS
    scan runs in a throwaway container with no volume.

    Every method fails open, per this module's contract that no review failure may block an edge.
    The cache degrading to a miss costs one extra LLM call; letting the exception escape would
    cost the entire sports scan, and losing a verdict we already paid for is worse than both.
    """

    def __init__(self, supa, now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self._supa, self._now = supa, now

    def cached(self, key: str) -> Review | None:
        try:
            rows = (self._supa.table(REVIEWS_TABLE).select("*").eq("cache_key", key).eq("status", "ok")
                    .order("created_at", desc=True).limit(1).execute().data or [])
        except Exception:
            log.warning("sports review cache lookup failed; treating as a miss key=%s", key, exc_info=True)
            return None
        if not rows:
            return None
        row = rows[0]
        return Review(status="ok", explainable=bool(row["explainable"]), drivers=tuple(row["drivers"] or []),
                      red_flags=tuple(row["red_flags"] or []), model=row.get("model"))

    def calls_since(self, since: datetime) -> int:
        try:
            return len(self._supa.table(REVIEWS_TABLE).select("id").gte("created_at", since.isoformat()).execute().data or [])
        except Exception:
            # Unknown, not zero: report the budget as already spent so an outage cannot
            # silently turn into unbounded LLM spend.
            log.warning("sports review budget count failed; treating the daily budget as spent", exc_info=True)
            return _BUDGET_UNKNOWN

    def save(self, request: ReviewRequest, review: Review) -> None:
        try:
            self._supa.table(REVIEWS_TABLE).insert({
                "cache_key": request.key, "sport": request.sport, "game_id": request.game_id,
                "market_ticker": request.market_ticker, "side": request.side, "entry_price": request.entry_price,
                "price_bucket": request.price_bucket, "our_prob": round(request.our_prob, 4),
                "model": review.model, "status": review.status, "explainable": review.explainable,
                "drivers": list(review.drivers), "red_flags": list(review.red_flags),
                "created_at": self._now().isoformat(),
            }).execute()
        except Exception:
            # The verdict is still returned to the caller; only the cache write is lost.
            log.warning("sports review save failed key=%s", request.key, exc_info=True)


def review_candidates(
    reqs: list[ReviewRequest], store: ReviewStore, reviewer: OpenRouterReviewer | None, *, budget: int, now: datetime,
) -> dict[str, Review]:
    """Cache first, then call the model for the largest edges until today's UTC budget is spent.

    Store calls are individually guarded: a broken cache must not cost the scan, and a failed
    insert must not discard a verdict we already paid for.
    """
    day_start = now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    used = _safe(store.calls_since, day_start, default=_BUDGET_UNKNOWN) if reviewer is not None else 0
    out: dict[str, Review] = {}
    for req in sorted(reqs, key=lambda r: r.net_edge_pct, reverse=True):
        if req.key in out:
            continue
        hit = _safe(store.cached, req.key)
        if hit is not None:
            out[req.key] = hit
        elif reviewer is None:
            out[req.key] = _unreviewed("no_key")
        elif used >= budget:
            out[req.key] = _unreviewed("skipped_budget")
        else:
            review = reviewer.review(req.fact_pack)
            used += 1
            _safe(store.save, req, review)
            out[req.key] = review
    return out


def _safe(fn: Callable[..., Any], *args: Any, default: Any = None) -> Any:
    try:
        return fn(*args)
    except Exception:
        log.warning("sports review store call failed: %s", getattr(fn, "__name__", fn), exc_info=True)
        return default


class MemoryReviewStore:
    """In-process store for dry runs and tests: nothing is persisted."""

    def __init__(self):
        self._rows: list[tuple[str, datetime, Review]] = []

    def cached(self, key: str) -> Review | None:
        return next((r for k, _, r in reversed(self._rows) if k == key and r.status == "ok"), None)

    def calls_since(self, since: datetime) -> int:
        return sum(1 for _, at, _ in self._rows if at >= since)

    def save(self, request: ReviewRequest, review: Review) -> None:
        self._rows.append((request.key, datetime.now(timezone.utc), review))
