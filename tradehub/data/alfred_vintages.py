"""A FRED series exactly as it stood on past dates, keyless or keyed.

Two sources, interchangeable:

- `alfredgraph.csv?id=S,S,...&vintage_date=d1,d2,...` returns one column per requested vintage
  (header `S_YYYYMMDD`) with no API key, up to 12 per request. It is, however, unreachable from some
  networks -- this one gets an HTTP/2 INTERNAL_ERROR from it while `api.stlouisfed.org` answers -- so
  a scan that depends on it dies on the network, not on the data.
- `fred/series/observations?series_id=S&realtime_start=d&realtime_end=d&file_type=json&api_key=...`
  needs a key and returns ONE realtime window per request, so it cannot batch. The key travels in the
  query string, which `requests` copies into every `HTTPError` it raises, so it is redacted out of
  every message this module raises or logs.

`FRED_API_KEY` set -> the API. Unset -> the keyless CSV. Either way the result is the same
`{vintage date: {observation date: value}}`, and both write the same on-disk cache format, so a cache
written by one path is read by the other and a run cannot quietly grade two different datasets.

Past vintages never change, so each one is cached on disk as its own small CSV; only vintages dated
before today are cached.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

import requests

from tradehub.sports.deadline import remaining_seconds

ALFRED_GRAPH_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
FRED_SERIES_OBSERVATIONS = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_KEY_ENV = "FRED_API_KEY"
REDACTED = "***"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
VINTAGES_PER_REQUEST = 12  # alfredgraph returns at most 12 columns per request
REQUEST_TIMEOUT_SECONDS = 60.0
log = logging.getLogger(__name__)
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "tradehub" / "alfred"

Vintage = dict[date, float]  # observation date -> value, as published on the vintage date


def redact(text: str, secret: str | None) -> str:
    """Strip a secret out of a message.

    A FRED API key is a query parameter, so it ends up in `requests`' `PreparedRequest.url` and
    therefore in the text of every `HTTPError`, `ConnectionError` and `Timeout` raised while fetching
    with it -- all of which end up in a log line or a scan failure report. Redacting where the message
    is built is the only place that covers every one of them.
    """
    return text.replace(secret, REDACTED) if secret else text


def default_get_text(
    url: str,
    params: dict,
    *,
    get: Callable[..., Any] = requests.get,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
    deadline: float | None = None,
    secret: str | None = None,
) -> str:
    """GET with a browser User-Agent and retries, bounded by the scan deadline.

    Retry-with-backoff pattern adapted from ACCY-512-Final-Project (K. Sigey, 2026), fetch_with_retry.

    Three things this adds, each of which cost the hourly scan before:

    - the per-request timeout is clamped to the time remaining, so a request cannot sit past the
      deadline; the old flat 60s could, once per attempt;
    - a retry is only started when the budget can afford it (timeout + backoff), because four
      unconditional attempts were up to ~246s of predictor call inside a 15-minute scan;
    - HTTP 5xx is retried too. FRED's edge returns 503 under load, and retrying only transport
      errors turned a transient 503 into a dead engine for the whole run.

    `secret` is the FRED API key when there is one. It is never logged and never raised; it is only
    used to keep the key out of the messages `requests` builds from the request URL.
    """
    last: Exception | None = None
    for attempt in range(4):
        left = remaining_seconds(deadline, clock) if deadline is not None else None
        if left is not None and left <= 0:
            raise RuntimeError(redact(f"ALFRED request abandoned: the scan deadline passed at {url}", secret))
        timeout = REQUEST_TIMEOUT_SECONDS if left is None else min(REQUEST_TIMEOUT_SECONDS, max(1.0, left))
        try:
            resp = get(url, params=params, headers={"User-Agent": BROWSER_UA}, timeout=timeout)
        except requests.RequestException as exc:
            last = exc
        else:
            status = int(getattr(resp, "status_code", 200) or 200)
            # Retryable: 429 (rate limited) and 5xx (FRED's edge under load). Everything else is
            # final -- a 404 means the series or vintage does not exist, and retrying it four
            # times only delays the same failure by ~9s of backoff.
            #
            # Classify BEFORE raise_for_status(), never after. raise_for_status() raises
            # HTTPError, which IS a RequestException, but it is raised from this `else` clause,
            # which the `except` above does not cover -- so a 429 raised there escapes the retry
            # loop entirely and the caller gets a bare HTTPError instead of the documented
            # RuntimeError. That is exactly the regression round 1 introduced.
            if status == 429 or 500 <= status <= 599:
                last = requests.HTTPError(redact(f"{status} from {url}", secret))
            else:
                try:
                    resp.raise_for_status()
                except requests.RequestException as exc:
                    # Final, not retryable. Fail immediately -- and with the same error TYPE the
                    # retry path raises, because callers (and readers of the log) should not have
                    # to tell "404, do not retry" from "404 after four tries" by exception class.
                    message = redact(f"ALFRED request failed: {exc}", secret)
                    if secret:
                        # `raise ... from exc` would keep the ORIGINAL exception, and requests
                        # rebuilds its text from the request URL -- key and all -- so a
                        # `logger.exception` of this would print the key however carefully the
                        # message above is redacted. The redacted text already carries the status and
                        # the URL, so the cause is dropped rather than leaked.
                        raise RuntimeError(message) from None
                    raise RuntimeError(message) from exc
                return resp.text
        backoff = 1.5 * (attempt + 1)
        if deadline is not None and remaining_seconds(deadline, clock) < timeout + backoff:
            log.warning("alfred: %0.1fs of scan budget left, not enough for another attempt "
                        "(one needs %0.1fs)", remaining_seconds(deadline, clock), timeout + backoff)
            break
        sleep(backoff)
    raise RuntimeError(redact(f"ALFRED request failed after retries: {last}", secret))


def parse_alfred_csv(text: str) -> dict[date, Vintage]:
    """{vintage date: {observation date: value}} from a (multi-)vintage alfredgraph CSV."""
    rows = list(csv.reader(io.StringIO(text)))
    if not rows or rows[0][0] != "observation_date":
        raise ValueError(f"not an alfredgraph CSV: {text[:80]!r}")
    columns = []
    for name in rows[0][1:]:
        stamp = name.rsplit("_", 1)[-1]
        columns.append(datetime.strptime(stamp, "%Y%m%d").date())
    out: dict[date, Vintage] = {v: {} for v in columns}
    for row in rows[1:]:
        if not row or not row[0]:
            continue
        obs = date.fromisoformat(row[0])
        for vintage, cell in zip(columns, row[1:]):
            if cell not in ("", "."):
                out[vintage][obs] = float(cell)
    return out


def parse_fred_observations_json(text: str) -> Vintage:
    """{observation date: value} from one `fred/series/observations` payload.

    The same shape as one alfredgraph CSV column: the observations as published inside the payload's
    `realtime_start..realtime_end` window. FRED writes "." for an observation it has no value for,
    which is dropped rather than read as 0.0 -- a fabricated zero in a nowcast is worse than a gap.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"not a FRED series/observations payload: {text[:80]!r}") from exc
    # FRED reports its own errors as `{"error_code": ..., "error_message": ...}` with a 4xx status, so
    # a body without `observations` is never a series.
    if not isinstance(payload, dict) or not isinstance(payload.get("observations"), list):
        raise ValueError(f"not a FRED series/observations payload: {text[:80]!r}")
    out: Vintage = {}
    for obs in payload["observations"]:
        value = str(obs.get("value", "")).strip()
        if value in ("", "."):
            continue
        out[date.fromisoformat(obs["date"])] = float(value)
    return out


def _cache_file(cache_dir: Path, series_id: str, vintage: date) -> Path:
    return cache_dir / series_id / f"{vintage.isoformat()}.csv"


def _write_cache(path: Path, series_id: str, vintage: date, values: Vintage) -> None:
    # repr(), not `:g`. `:g` is SIX significant digits, so CCSA 1,897,123 was cached as
    # "1.897e+06" and read back as 1897000.0 — a cached run and a fresh run then produced
    # different nowcasts, silently. Past vintages never change, so a cache written this way is
    # wrong forever; repr(float) round-trips exactly in Python 3.
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [f"observation_date,{series_id}_{vintage.strftime('%Y%m%d')}"]
    lines += [f"{obs.isoformat()},{values[obs]!r}" for obs in sorted(values)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def fetch_vintages(
    series_id: str,
    vintages: list[date],
    *,
    get_text: Callable[..., str] = default_get_text,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    today: date | None = None,
    deadline: float | None = None,
    api_key: str | None = None,
) -> dict[date, Vintage]:
    """The series as published on each requested date, batching uncached dates per request.

    `FRED_API_KEY` (or `api_key`) set -> `fred/series/observations`, one request per uncached vintage.
    Unset -> keyless `alfredgraph.csv`, up to `VINTAGES_PER_REQUEST` vintages per request. Both write
    the same on-disk cache, so a run reads back what either path wrote.
    """
    today = today or datetime.now(timezone.utc).date()
    key = (api_key if api_key is not None else os.getenv(FRED_API_KEY_ENV, "")).strip()
    wanted = sorted({v for v in vintages if v < today})
    out: dict[date, Vintage] = {}
    missing = []
    for vintage in wanted:
        path = _cache_file(cache_dir, series_id, vintage) if cache_dir else None
        if path is not None and path.is_file():
            out[vintage] = parse_alfred_csv(path.read_text(encoding="utf-8"))[vintage]
        else:
            missing.append(vintage)
    if key:
        for vintage in missing:
            # One request per vintage, not a batch: the API answers with the single realtime window
            # asked for, so `realtime_start == realtime_end` IS the vintage. The key goes in the
            # query string FRED requires, and is also passed as `secret` so the fetcher can keep it
            # out of the errors `requests` builds from that request's URL.
            params = {
                "series_id": series_id,
                "realtime_start": vintage.isoformat(),
                "realtime_end": vintage.isoformat(),
                "file_type": "json",
                "api_key": key,
            }
            extra = {} if deadline is None else {"deadline": deadline}
            extra["secret"] = key
            values = parse_fred_observations_json(get_text(FRED_SERIES_OBSERVATIONS, params, **extra))
            out[vintage] = values
            if cache_dir is not None and values:
                _write_cache(_cache_file(cache_dir, series_id, vintage), series_id, vintage, values)
        return out
    for start in range(0, len(missing), VINTAGES_PER_REQUEST):
        chunk = missing[start:start + VINTAGES_PER_REQUEST]
        params = {"id": ",".join([series_id] * len(chunk)), "vintage_date": ",".join(v.isoformat() for v in chunk)}
        # Only pass `deadline` when there is one, so a caller-supplied get_text with the old
        # two-argument signature keeps working.
        extra = {} if deadline is None else {"deadline": deadline}
        parsed = parse_alfred_csv(get_text(ALFRED_GRAPH_CSV, params, **extra))
        for vintage in chunk:
            values = parsed.get(vintage, {})
            out[vintage] = values
            if cache_dir is not None and values:
                _write_cache(_cache_file(cache_dir, series_id, vintage), series_id, vintage, values)
    return out
