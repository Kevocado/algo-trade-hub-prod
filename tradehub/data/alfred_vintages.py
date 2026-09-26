"""Keyless ALFRED vintages: a FRED series exactly as it stood on past dates.

`alfredgraph.csv?id=S,S,...&vintage_date=d1,d2,...` returns one column per
requested vintage (header `S_YYYYMMDD`), with no API key. Past vintages
never change, so each one is cached on disk as its own small CSV; only
vintages dated before today are cached.
"""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

import requests

ALFRED_GRAPH_CSV = "https://alfred.stlouisfed.org/graph/alfredgraph.csv"
BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
VINTAGES_PER_REQUEST = 12  # alfredgraph returns at most 12 columns per request
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "tradehub" / "alfred"

Vintage = dict[date, float]  # observation date -> value, as published on the vintage date


def default_get_text(url: str, params: dict) -> str:
    """GET with a browser User-Agent and retries (FRED's edge drops bare clients).

    Retry-with-backoff pattern adapted from ACCY-512-Final-Project (K. Sigey, 2026), fetch_with_retry.
    """
    last: Exception | None = None
    for attempt in range(4):
        try:
            resp = requests.get(url, params=params, headers={"User-Agent": BROWSER_UA}, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"ALFRED request failed after retries: {last}")


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
    get_text: Callable[[str, dict], str] = default_get_text,
    cache_dir: Path | None = DEFAULT_CACHE_DIR,
    today: date | None = None,
) -> dict[date, Vintage]:
    """The series as published on each requested date, batching uncached dates per request."""
    today = today or datetime.now(timezone.utc).date()
    wanted = sorted({v for v in vintages if v < today})
    out: dict[date, Vintage] = {}
    missing = []
    for vintage in wanted:
        path = _cache_file(cache_dir, series_id, vintage) if cache_dir else None
        if path is not None and path.is_file():
            out[vintage] = parse_alfred_csv(path.read_text(encoding="utf-8"))[vintage]
        else:
            missing.append(vintage)
    for start in range(0, len(missing), VINTAGES_PER_REQUEST):
        chunk = missing[start:start + VINTAGES_PER_REQUEST]
        params = {"id": ",".join([series_id] * len(chunk)), "vintage_date": ",".join(v.isoformat() for v in chunk)}
        parsed = parse_alfred_csv(get_text(ALFRED_GRAPH_CSV, params))
        for vintage in chunk:
            values = parsed.get(vintage, {})
            out[vintage] = values
            if cache_dir is not None and values:
                _write_cache(_cache_file(cache_dir, series_id, vintage), series_id, vintage, values)
    return out
