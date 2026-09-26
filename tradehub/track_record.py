"""Per-engine track record: calibration, Brier vs market, promotion gate.

Consumes the settled `predictions` rows (spec sections 4.5 and 6) — the
same rows the settlement job writes. Pure math except for
`refresh_track_record`, which upserts the `track_record` rollup table.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

BUCKETS = ["50-60", "60-70", "70-80", "80-90", "90-100"]
MIN_CONTRACTS = {"daily": 200, "monthly": 50}
MAX_CALIBRATION_MISS = 0.10
# A calibration bucket needs this many contracts (effective, see
# _contract_weights) before its miss can block promotion; thinner buckets
# are still reported. Spec section 6.
MIN_BUCKET_CONTRACTS = 20
TRACK_RECORD_TABLE = "track_record"


def bucketize(prob: float) -> str:
    """Map a probability to its 10pp calibration bucket.

    Confidence is mirrored at 0.5 (a 0.3 forecast is 70% confidence it
    resolves NO). Boundaries are deterministic: 0.5 -> "50-60",
    1.0 -> "90-100".
    """
    confidence = max(prob, 1.0 - prob)
    confidence = min(max(confidence, 0.5), 1.0)
    # 1e-9 absorbs float dust (e.g. 0.7 * 10 == 6.999999999999999 in float);
    # empirically verified: 0.5 -> "50-60", 0.6 -> "60-70", 1.0 -> "90-100".
    idx = min(int(confidence * 10 + 1e-9) - 5, 4)
    return BUCKETS[idx]


def _settled_only(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in rows if r.get("result") in ("yes", "no")]


def _quoted_settled(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    settled = _settled_only(rows)
    quoted = [r for r in settled if r.get("market_prob") is not None]
    return quoted, len(settled) - len(quoted)


def _contract_key(row: dict[str, Any]) -> str:
    """Rows about the same Kalshi contract share a key; rows without a ticker stand alone."""
    ticker = row.get("market_ticker")
    return f"ticker:{ticker}" if ticker else f"row:{row.get('id', id(row))}"


def _contract_weights(rows: list[dict[str, Any]]) -> list[float]:
    """Weight each row 1/k, k = rows for its contract, so every contract counts once.

    The hourly scan predicts each open market many times; without this a
    single daily market would count ~24 times toward the gate.
    """
    counts: dict[str, int] = {}
    for row in rows:
        key = _contract_key(row)
        counts[key] = counts.get(key, 0) + 1
    return [1.0 / counts[_contract_key(row)] for row in rows]


def _confidence_and_hit(row: dict[str, Any]) -> tuple[float, bool]:
    """Confidence in the favored side, and whether that side won."""
    prob = float(row["our_prob"])
    favored_yes = prob >= 0.5
    confidence = prob if favored_yes else 1.0 - prob
    hit = (row["result"] == "yes") if favored_yes else (row["result"] == "no")
    return confidence, hit


def compute_calibration(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-bucket contract-weighted n, mean confidence, and favored-side hit rate.

    `n` is the effective number of contracts in the bucket (sum of row
    weights); `n_rows` is the raw row count.
    """
    settled, _ = _quoted_settled(rows)
    groups: dict[str, list[tuple[float, bool, float]]] = {b: [] for b in BUCKETS}
    for row, weight in zip(settled, _contract_weights(settled)):
        confidence, hit = _confidence_and_hit(row)
        groups[bucketize(confidence)].append((confidence, hit, weight))
    out = []
    for bucket in BUCKETS:
        members = groups[bucket]
        if not members:
            continue
        total = sum(w for _, _, w in members)
        predicted = sum(c * w for c, _, w in members) / total
        observed = sum(w for _, hit, w in members if hit) / total
        out.append({"bucket": bucket, "n": round(total, 2), "n_rows": len(members),
                    "predicted": round(predicted, 4), "observed": round(observed, 4)})
    return out


def _weighted_mean(pairs: list[tuple[float, float]]) -> float | None:
    total = sum(w for _, w in pairs)
    return sum(v * w for v, w in pairs) / total if total else None


def compute_engine_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Distinct settled contracts and contract-weighted mean Briers.

    `n_settled` counts contracts, not rows (spec section 6 says "settled
    contracts"). Market Brier still fails closed: every settled row must
    carry one.
    """
    settled, n_unquoted = _quoted_settled(rows)
    weights = _contract_weights(settled)
    ours = _weighted_mean([(float(r["brier"]), w) for r, w in zip(settled, weights) if r.get("brier") is not None])
    market_pairs = [(float(r["market_brier"]), w) for r, w in zip(settled, weights) if r.get("market_brier") is not None]
    market = _weighted_mean(market_pairs) if settled and len(market_pairs) == len(settled) else None
    return {
        "n_settled": len({_contract_key(r) for r in settled}),
        "n_rows": len(settled),
        "n_unquoted": n_unquoted,
        "brier_ours": round(ours, 5) if ours is not None else None,
        "brier_market": round(market, 5) if market is not None else None,
    }


def check_promotion_gate(
    *,
    engine: str,
    cadence: str,
    summary: dict[str, Any],
    cal_buckets: list[dict[str, Any]],
    simulated_pnl_after_fees: float | None,
) -> dict[str, Any]:
    """Evaluate the spec section 6 promotion gate for one engine.

    Returns {"status": "PROMOTED"|"SHADOW", "reasons": [...]} where
    reasons lists every unmet criterion. Re-evaluated after every
    settlement pass: an engine that slips below any threshold is
    demoted back to SHADOW (promotion is dynamic, per the spec).
    """
    reasons: list[str] = []
    min_contracts = MIN_CONTRACTS.get(cadence, MIN_CONTRACTS["daily"])
    if summary["n_settled"] < min_contracts:
        reasons.append(f"only {summary['n_settled']} settled contracts, need {min_contracts} ({cadence})")
    ours = summary.get("brier_ours")
    market = summary.get("brier_market")
    if market is None:
        reasons.append("no market Brier recorded; gate cannot be evaluated")
    elif ours is None or ours >= market:
        reasons.append(f"model Brier {ours} is not below market Brier {market}")
    if simulated_pnl_after_fees is None or simulated_pnl_after_fees <= 0:
        reasons.append("simulated P&L after fees/spread is not positive")
    worst_miss = 0.0
    for bucket in cal_buckets:
        if bucket["n"] < MIN_BUCKET_CONTRACTS:
            continue  # too thin to judge; still shown in cal_buckets
        miss = abs(bucket["observed"] - bucket["predicted"])
        worst_miss = max(worst_miss, miss)
        if miss > MAX_CALIBRATION_MISS:
            reasons.append(f"calibration miss {miss:.1%} in bucket {bucket['bucket']} (limit 10pp)")
    status = "PROMOTED" if not reasons else "SHADOW"
    return {"status": status, "reasons": reasons, "max_cal_dev": round(worst_miss, 4)}


PAGE_SIZE = 1000  # PostgREST's default max rows per response


def fetch_settled_rows(supa, engine: str) -> list[dict[str, Any]]:
    """All SETTLED prediction rows for one engine, paged past PostgREST's 1000-row cap."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        res = (
            supa.table("predictions").select("*")
            .eq("engine", engine).eq("status", "SETTLED")
            .order("id").range(start, start + PAGE_SIZE - 1).execute()
        )
        page = res.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
        start += PAGE_SIZE


def refresh_track_record(supa, engine: str, cadence: str = "daily",
                         simulated_pnl_after_fees: float | None = None) -> list[dict[str, Any]]:
    """Recompute one rollup per engine_version from the engine's settled rows and upsert them.

    Each version earns its own record: a new model version never inherits
    its predecessor's promotion.
    """
    by_version: dict[str, list[dict[str, Any]]] = {}
    for row in fetch_settled_rows(supa, engine):
        by_version.setdefault(row.get("engine_version") or "v0", []).append(row)
    return [
        _upsert_version(supa, engine, version, rows, cadence, simulated_pnl_after_fees)
        for version, rows in sorted(by_version.items())
    ]


def _upsert_version(supa, engine: str, engine_version: str, rows: list[dict[str, Any]], cadence: str,
                    simulated_pnl_after_fees: float | None) -> dict[str, Any]:
    summary = compute_engine_summary(rows)
    cal_buckets = compute_calibration(rows)
    gate = check_promotion_gate(engine=engine, cadence=cadence, summary=summary,
                                cal_buckets=cal_buckets,
                                simulated_pnl_after_fees=simulated_pnl_after_fees)
    payload = {
        "engine": engine,
        "engine_version": engine_version,
        "n_settled": summary["n_settled"],
        "brier_ours": summary["brier_ours"],
        "brier_market": summary["brier_market"],
        "cal_buckets": cal_buckets,
        "max_cal_dev": gate["max_cal_dev"],
        "gate_status": gate["status"],
        "updated_at": datetime.now(UTC).isoformat(),
    }
    supa.table(TRACK_RECORD_TABLE).upsert(payload, on_conflict="engine,engine_version").execute()
    return payload
