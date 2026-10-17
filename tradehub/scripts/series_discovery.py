"""Series discovery: curated check of likely active Kalshi series with volume in last 30 days.

Outputs docs/research/2026-10-series-discovery.md with top 10 and top 3 recommendations.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

import requests

BASE = "https://api.elections.kalshi.com/trade-api/v2"
NOW = datetime.now(timezone.utc)
CUTOFF = NOW - timedelta(days=30)
SESSION = requests.Session()
SESSION.timeout = 15

JOURNAL_SERIES = {
    "KXCPI", "KXCPICORE", "KXFOMC", "KXPAYROLLS", "KXUNRATE", "KXQUITS",
    "KXSPX", "KXVIX", "KXGOLD", "KXEURUSD", "KXCSUSHPINSA", "KXNHL", "KXNFL", "KXCFB",
    "KXHIGHNY", "KXHIGHMIA", "KXHIGHTBOS", "KXHIGHPHIL", "KXLOWNY", "KXLOWMIA", "KXLOWTBOS", "KXLOWPHIL",
    "KXRAINNY", "KXRAINMIA", "KXRAINTBOS", "KXRAINPHIL",
    "KXTXERCOTPEAKD",
    "KXAAAGASD", "KXAAAGASDNE", "KXAAAGASDTX",
}

# Curated list of series likely to have volume in the last 30 days
# Based on known active categories: Economics, Climate, Financials, Sports, Elections
CANDIDATE_SERIES = [
    # Economics (daily/weekly/monthly)
    "KXCPI", "KXCPICORE", "KXCPIFOOD", "KXCPISHELTER", "KXPCEHEAD", "KXPCECORE",
    "KXPAYROLLS", "KXUNRATE", "KXQUITS", "KXCONTCLAIMS", "KXJPCONCONF", "KXISMPMI",
    "KXJETFUEL", "KXNGASMAX", "KXWTIMAX", "KXGASMIN", "KXAAAGASD", "KXAAAGASDNE", "KXAAAGASDTX",
    "KXSOYBEANMON", "KXCORNWALLMEADOWBY", "KXSDCORNYIELD", "KXERCOTPEAKD",
    # Climate (daily weather)
    "KXHIGHNY", "KXHIGHMIA", "KXHIGHTBOS", "KXHIGHPHIL", "KXLOWNY", "KXLOWMIA", "KXLOWTBOS", "KXLOWPHIL",
    "KXRAINNY", "KXRAINMIA", "KXRAINTBOS", "KXRAINPHIL", "KXHIGHTVHHH", "KXLOWTEBBR",
    # Financials (daily/weekly)
    "KXSPX", "KXVIX", "KXGOLD", "KXEURUSD", "KXUSDJPY", "KXUST10AM", "KXUST30", "KXINXM",
    "KXNFLXAPP", "KXTESLAM2", "KXSHOPA", "KXRBLXA", "KXRPRESPRIMARY",
    # Sports (seasonal)
    "KXNFL", "KXNFLSPREAD", "KXNFLTOTAL", "KXCFB", "KXCFBSPREAD", "KXCFBTOTAL",
    "KXNHL", "KXNBAGAMES", "KXNBA", "KXNCAAF", "KXNCAAM",
    # Elections (as they happen)
    "KXPRESPARTY", "KXSENATE", "KXHOUSE", "KXGOV",
    # Crypto
    "KXETH", "KXBTC", "KXSHIBAD",
]

def get_json(path: str, params: dict | None = None) -> dict:
    url = urljoin(BASE + "/", path.lstrip("/"))
    resp = SESSION.get(url, params=params)
    if resp.status_code == 429:
        time.sleep(2)
        resp = SESSION.get(url, params=params)
    resp.raise_for_status()
    return resp.json()


def parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def series_volume_last_30d(series_ticker: str) -> tuple[float, int, datetime | None]:
    """Return (total_volume, n_settled_events, latest_settlement) in the last 30 days."""
    params = {"series_ticker": series_ticker, "status": "settled", "limit": 1000}
    cursor = None
    vol = 0.0
    events = set()
    latest = None
    while True:
        if cursor:
            params["cursor"] = cursor
        data = get_json("markets", params)
        batch = data.get("markets", [])
        if not batch:
            break
        for m in batch:
            close = m.get("close_time")
            if not close:
                continue
            t = parse_iso(close)
            if t < CUTOFF:
                continue
            v = m.get("volume_fp") or m.get("volume") or 0.0
            vol += float(v)
            ev = m.get("event_ticker")
            if ev:
                events.add(ev)
            if latest is None or t > latest:
                latest = t
        cursor = data.get("cursor")
        if not cursor:
            break
        time.sleep(0.1)
    return vol, len(events), latest


def fetch_series_details(ticker: str) -> dict:
    try:
        data = get_json(f"series/{ticker}")
        return data.get("series", {})
    except Exception:
        return {}


def main():
    t0 = time.time()
    print(f"Checking {len(CANDIDATE_SERIES)} candidate series...", file=sys.stderr)

    with_volume = []
    for i, ticker in enumerate(CANDIDATE_SERIES):
        try:
            vol, n_events, latest = series_volume_last_30d(ticker)
        except Exception as e:
            print(f"  {ticker}: ERR {e}", file=sys.stderr)
            continue
        if vol > 0:
            with_volume.append((ticker, vol, n_events, latest))
            print(f"  {ticker}: vol={vol:.1f} events={n_events}", file=sys.stderr)
        else:
            print(f"  {ticker}: no volume in last 30d", file=sys.stderr)
        if i % 10 == 0:
            print(f"  checked {i+1}/{len(CANDIDATE_SERIES)}... ({time.time()-t0:.1f}s)", file=sys.stderr)
        time.sleep(0.15)

    print(f"\n{len(with_volume)} series with >0 volume in last 30d", file=sys.stderr)

    details_cache = {}
    for ticker, vol, n_ev, latest in with_volume:
        details_cache[ticker] = fetch_series_details(ticker)
        time.sleep(0.1)

    def source_quality(sources):
        if not sources:
            return 0
        for src in sources:
            if src.get("url"):
                return 2
        return 1

    results = []
    for ticker, vol, n_ev, latest in with_volume:
        details = details_cache.get(ticker, {})
        src_q = source_quality(details.get("settlement_sources", []))
        # Get category/frequency from details or defaults
        cat = details.get("category", "Unknown")
        freq = details.get("frequency", "unknown")
        results.append({
            "ticker": ticker,
            "category": cat,
            "frequency": freq,
            "volume_30d": vol,
            "n_settled_events": n_ev,
            "latest_settlement": latest.isoformat() if latest else None,
            "settlement_sources": details.get("settlement_sources", []),
            "contract_terms_url": details.get("contract_terms_url", ""),
            "title": details.get("title", ""),
            "in_journal": ticker in JOURNAL_SERIES,
            "_source_q": src_q,
        })

    for r in results:
        r["_score"] = r["volume_30d"] * r["_source_q"] * max(1, r["n_settled_events"])

    results.sort(key=lambda r: r["_score"], reverse=True)

    # Write Markdown
    md = []
    md.append(f"# Series Discovery — {NOW.date().isoformat()}\n")
    md.append("Curated check of likely-active Kalshi series with >0 volume in the last 30 days, ranked by\n")
    md.append("(30d volume) × (source quality: 2=free URL, 1=agency no URL, 0=private) × (1 + settled events).\n")
    md.append("Series already in the journal are marked and excluded from recommendations.\n")

    md.append("\n| Rank | Series | Category | Freq | 30d Volume | Settled Events | Source Quality | Free Source | In Journal |\n")
    md.append("|---:|---|---|---|---:|---:|---:|---|---:|\n")

    for i, r in enumerate(results, 1):
        sources = r["settlement_sources"]
        free_src = " | ".join(f'{src.get("name","")} ({src.get("url","")})' for src in sources if src.get("url")) or "—"
        src_q = "free" if r["_source_q"] == 2 else ("agency" if r["_source_q"] == 1 else "private")
        journal = "✓" if r["in_journal"] else ""
        md.append(f"| {i} | {r['ticker']} | {r['category']} | {r['frequency']} | {r['volume_30d']:.1f} | {r['n_settled_events']} | {src_q} | {free_src} | {journal} |")

    md.append("\n## Top 10 by Score\n")
    md.append("| Rank | Series | Score | 30d Vol | Events | Source | Free Source |\n")
    md.append("|---:|---|---:|---:|---:|---|---|\n")
    for i, r in enumerate(results[:10], 1):
        sources = r["settlement_sources"]
        free_src = " | ".join(f'{src.get("name","")} ({src.get("url","")})' for src in sources if src.get("url")) or "—"
        md.append(f"| {i} | {r['ticker']} | {r['_score']:.1f} | {r['volume_30d']:.1f} | {r['n_settled_events']} | {r['_source_q']} | {free_src} |")

    md.append("\n## Top 3 Recommendations (not in journal)\n")
    recs = [r for r in results if not r["in_journal"]][:3]
    for i, r in enumerate(recs, 1):
        sources = r["settlement_sources"]
        free_src = "; ".join(f'{src.get("name","")} ({src.get("url","")})' for src in sources if src.get("url")) or "no free source named"
        md.append(f"\n### {i}. {r['ticker']} — {r['title']}\n")
        md.append(f"- **Category:** {r['category']} | **Frequency:** {r['frequency']}\n")
        md.append(f"- **30d volume:** {r['volume_30d']:.1f} | **Settled events (30d):** {r['n_settled_events']}\n")
        md.append(f"- **Settles on:** {r['title']}\n")
        md.append(f"- **Free source:** {free_src}\n")
        md.append(f"- **Why:** {r['volume_30d']:.0f} vol × {r['_source_q']} source × {r['n_settled_events']} events = score {r['_score']:.1f}. "
                  f"Settlement data is public; a forecaster can be built and graded against Kalshi.\n")

    out_path = "docs/research/2026-10-series-discovery.md"
    import os
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write("\n".join(md))
    print(f"\nWrote {out_path} ({time.time()-t0:.1f}s)", file=sys.stderr)

    print("\nTop 10:")
    for i, r in enumerate(results[:10], 1):
        print(f"  {i}. {r['ticker']} ({r['category']}) vol={r['volume_30d']:.1f} events={r['n_settled_events']} src_q={r['_source_q']} journal={r['in_journal']}")


if __name__ == "__main__":
    BASE = "https://api.elections.kalshi.com/trade-api/v2"
    main()