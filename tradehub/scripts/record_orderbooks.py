"""Hourly snapshot of Kalshi quotes, kept on disk for a later maker-fill study.

Kalshi publishes no historical order books, so the only way to ask "would a resting maker order at the
extremes have filled, and was it picked off?" is to record the book ourselves and pair it later with the
public trade tape. Two records per run, both gzip JSON lines under `<root>/<YYYY-MM-DD>/<HH>.jsonl.gz`:

- `top`: top of book for every TRADED open market closing within `HORIZON` (one listing scan; ~95% of
  listed strikes never trade and are skipped).
- `depth`: the full book for up to `DEPTH_CAP` of those markets priced at the extremes (<=10c or >=90c
  mid), the cells a maker study would test.

Read only. No orders, no credentials (the market-data API is public). A run that hits its time budget
stops listing and says so (`truncated`) rather than pretending it saw everything.
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from tradehub.backtest.http import default_get_json
from tradehub.backtest.kalshi_history import KALSHI_PUBLIC_BASE

HORIZON = timedelta(days=3)
PAGE_LIMIT = 1000
MAX_PAGES = 1000
DEPTH_CAP = 300
EXTREME = 0.10
BUDGET_SECONDS = 8 * 60
ROOT_ENV = "TRADEHUB_ORDERBOOK_DIR"
DEFAULT_ROOT = Path("/cache/orderbooks")
TOP_FIELDS = ("yes_bid_dollars", "yes_ask_dollars", "yes_bid_size_fp", "yes_ask_size_fp",
              "last_price_dollars", "volume_fp", "volume_24h_fp", "open_interest_fp", "close_time")


def _f(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def top_row(market: dict[str, Any]) -> dict[str, Any]:
    row = {"ticker": market.get("ticker"), "event_ticker": market.get("event_ticker")}
    row |= {k: market.get(k) for k in TOP_FIELDS}
    return row


def is_extreme(market: dict[str, Any]) -> bool:
    bid, ask = _f(market.get("yes_bid_dollars")), _f(market.get("yes_ask_dollars"))
    if bid is None or ask is None or ask <= 0:
        return False
    mid = (bid + ask) / 2
    return mid <= EXTREME or mid >= 1 - EXTREME


def snapshot(now: datetime, get: Callable[..., Any], *, base: str = KALSHI_PUBLIC_BASE,
             clock: Callable[[], float] = time.monotonic, budget: float = BUDGET_SECONDS,
             max_pages: int = MAX_PAGES, depth_cap: int = DEPTH_CAP) -> dict[str, Any]:
    deadline = clock() + budget
    lo, hi = int(now.timestamp()), int((now + HORIZON).timestamp())
    traded: list[dict[str, Any]] = []
    cursor, pages, listed, truncated = None, 0, 0, False
    while True:
        if pages >= max_pages or clock() >= deadline:
            truncated = True
            break
        params = {"status": "open", "limit": PAGE_LIMIT, "min_close_ts": lo, "max_close_ts": hi}
        if cursor:
            params["cursor"] = cursor
        data = get(f"{base}/markets", params)
        pages += 1
        markets = data.get("markets") or []
        listed += len(markets)
        traded += [m for m in markets if (_f(m.get("volume_fp")) or 0) > 0]
        cursor = data.get("cursor")
        if not cursor:
            break
    depth, depth_failed = [], 0
    for market in [m for m in traded if is_extreme(m)][:depth_cap]:
        if clock() >= deadline:
            truncated = True
            break
        try:
            book = get(f"{base}/markets/{market['ticker']}/orderbook", None)
        except Exception:  # noqa: BLE001 - one bad book must not cost the snapshot
            depth_failed += 1
            continue
        depth.append({"ticker": market["ticker"], "book": book.get("orderbook_fp") or book.get("orderbook")})
    return {"as_of": now.isoformat(), "pages": pages, "listed": listed, "truncated": truncated,
            "top": [top_row(m) for m in traded], "depth": depth, "depth_failed": depth_failed}


def write(snap: dict[str, Any], root: Path, now: datetime) -> Path:
    path = root / now.strftime("%Y-%m-%d") / f"{now:%H}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        meta = {k: snap[k] for k in ("as_of", "pages", "listed", "truncated", "depth_failed")}
        fh.write(json.dumps({"kind": "meta", **meta}) + "\n")
        for row in snap["top"]:
            fh.write(json.dumps({"kind": "top", **row}) + "\n")
        for row in snap["depth"]:
            fh.write(json.dumps({"kind": "depth", **row}) + "\n")
    tmp.replace(path)
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.getenv(ROOT_ENV, str(DEFAULT_ROOT)))
    args = parser.parse_args(argv)
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    snap = snapshot(datetime.now(UTC), lambda url, params: default_get_json(url, params))
    path = write(snap, Path(args.root), now)
    print(json.dumps({"path": str(path), "listed": snap["listed"], "traded": len(snap["top"]),
                      "depth": len(snap["depth"]), "depth_failed": snap["depth_failed"],
                      "pages": snap["pages"], "truncated": snap["truncated"]}))
    return 0 if snap["top"] else 1


if __name__ == "__main__":
    sys.exit(main())
