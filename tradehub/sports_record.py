"""Every sports predictor's own track record, normalised to one row shape. Display only.

The hub never re-scores a game: each adapter passes a predictor's published numbers through and only
renames them. A key that is missing gives None, never 0 and never a guess. Shapes differ per predictor
and were taken from the live responses (tests/fixtures/sports_record/*.json).

Row: {sport, market, label, n, hit_rate, n_pre, hit_rate_pre, vs_market, note}. `n_pre`/`hit_rate_pre` are
the made-before-kickoff / pre-tip / pre-session subset; the headline counts every recorded pick.
`vs_market` stays None here: the Kalshi comparison comes from the journal for NFL and CFB only.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from time import monotonic
from typing import Any

SPORTS = ("nfl", "cfb", "nba", "pl", "f1")
TIMEOUT_SECONDS = 6.0
CACHE_SECONDS = 300.0

# NBA's /api/... path returns the site page, not data: the record is served at /hub/track-record.
PATHS = {
    "nfl": "/api/track-record",
    "cfb": "/api/track-record",
    "nba": "/hub/track-record",
    "pl": "/api/hub/track-record",
    "f1": "/api/track-record",
}
DEFAULT_HOSTS = {s: f"https://{s}.40-160-91-131.sslip.io" for s in ("nba", "pl", "f1")}
# Only these NBA markets are comparable to a Kalshi price; `game_outcome` and `player_props` carry
# backtest-sized counts (1,469 and 125,500) that would read as a track record they are not.
NBA_MARKETS = ("h2h", "spread", "total")


def _num(value: Any) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _row(sport: str, market: str, label: str, n: Any, hit: Any, n_pre: Any = None, hit_pre: Any = None) -> dict[str, Any]:
    return {"sport": sport, "market": market, "label": label, "n": _num(n), "hit_rate": _num(hit),
            "n_pre": _num(n_pre), "hit_rate_pre": _num(hit_pre), "vs_market": None, "note": None}


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _nfl_cfb(sport: str, body: Any) -> list[dict[str, Any]]:
    games = _dict(_dict(body).get("games"))
    pre = _dict(games.get("pre_kickoff"))
    rows = []
    for market, label, pct in (("moneyline", "Winner", "pct_moneyline_correct"),
                               ("spread", "Spread", "pct_ats_correct"),
                               ("total", "Total", "pct_totals_correct")):
        # NFL reports a count per market (n_moneyline ...); CFB reports one n_resolved for all three.
        n_key = {"moneyline": "n_moneyline", "spread": "n_ats", "total": "n_totals"}[market]
        n = games.get(n_key, games.get("n_resolved"))
        n_pre = pre.get(n_key, pre.get("n_resolved"))
        rows.append(_row(sport, market, label, n, games.get(pct), n_pre, pre.get(pct)))
    return rows


def adapt_nfl(body: Any) -> list[dict[str, Any]]:
    return _nfl_cfb("nfl", body)


def adapt_cfb(body: Any) -> list[dict[str, Any]]:
    return _nfl_cfb("cfb", body)


def adapt_nba(body: Any) -> list[dict[str, Any]]:
    rows = []
    for item in body if isinstance(body, list) else []:
        item = _dict(item)
        market = item.get("market")
        if market not in NBA_MARKETS:
            continue
        pre = _dict(item.get("pre_tip"))
        rows.append(_row("nba", market, {"h2h": "Winner", "spread": "Spread", "total": "Total"}[market],
                         item.get("total_predictions"), item.get("hit_rate"),
                         item.get("n_pre_tip"), pre.get("hit_rate")))
    return rows


def adapt_pl(body: Any) -> list[dict[str, Any]]:
    summary = _dict(_dict(body).get("summary"))
    pre = _dict(_dict(summary.get("pre_kickoff")).get("by_market"))
    labels = {"match_result": "Result", "over_under_2_5": "Over/under 2.5", "btts": "Both teams score",
              "exact_score": "Exact score"}
    rows = []
    for market, stats in _dict(summary.get("by_market")).items():
        stats, pstats = _dict(stats), _dict(pre.get(market))
        rows.append(_row("pl", market, labels.get(market, market), stats.get("n_resolved"), stats.get("pct_correct"),
                         pstats.get("n_resolved"), pstats.get("pct_correct")))
    return rows


def adapt_f1(body: Any) -> list[dict[str, Any]]:
    body = _dict(body)
    pre = {(r.get("tier"), r.get("market")): _dict(r)
           for r in _dict(body.get("pre_session")).get("by_market", []) if isinstance(r, dict)}
    rows = []
    for r in body.get("by_market", []) if isinstance(body.get("by_market"), list) else []:
        r = _dict(r)
        p = pre.get((r.get("tier"), r.get("market")), {})
        rows.append(_row("f1", f"{r.get('market')}:{r.get('tier')}", f"{r.get('market')} ({r.get('tier')})",
                         r.get("n"), r.get("hit_rate"), p.get("n"), p.get("hit_rate")))
    return rows


ADAPTERS: dict[str, Callable[[Any], list[dict[str, Any]]]] = {
    "nfl": adapt_nfl, "cfb": adapt_cfb, "nba": adapt_nba, "pl": adapt_pl, "f1": adapt_f1,
}


def base_url(sport: str) -> str:
    """NFL/CFB come from the same config the sports board uses, so the two cannot disagree."""
    if sport in ("nfl", "cfb"):
        from tradehub.sports.config import load_sport_config

        return load_sport_config(sport).base_url
    return (os.getenv(f"SPORTS_{sport.upper()}_BASE_URL") or DEFAULT_HOSTS[sport]).rstrip("/")


def fetch_json(url: str, timeout: float = TIMEOUT_SECONDS) -> Any:
    import requests

    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return response.json()  # an HTML page (the NBA site's /api/...) is not JSON and raises


def sport_record(sport: str, fetch: Callable[[str], Any] = fetch_json) -> dict[str, Any]:
    """One sport, never raising: a failure is this sport's `unavailable`, not the page's."""
    try:
        body = fetch(base_url(sport) + PATHS[sport])
        if not isinstance(body, (dict, list)):
            raise ValueError("not a JSON object")
        return {"sport": sport, "status": "ok", "rows": ADAPTERS[sport](body)}
    except Exception as exc:  # noqa: BLE001 - fail soft per sport
        return {"sport": sport, "status": "unavailable", "error": f"{type(exc).__name__}", "rows": []}


_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def collect(fetch: Callable[[str], Any] = fetch_json, now: Callable[[], float] = monotonic) -> dict[str, Any]:
    """All five sports, fetched in parallel, each cached for five minutes (failures are not cached)."""
    t = now()

    def one(sport: str) -> dict[str, Any]:
        hit = _cache.get(sport)
        if hit and t - hit[0] < CACHE_SECONDS:
            return hit[1]
        result = sport_record(sport, fetch)
        if result["status"] == "ok":
            _cache[sport] = (t, result)
        return result

    with ThreadPoolExecutor(max_workers=len(SPORTS)) as pool:
        sports = list(pool.map(one, SPORTS))
    return {"as_of": datetime.now(timezone.utc).isoformat(), "sports": sports}
