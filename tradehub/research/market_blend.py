"""Market-blend study (design plan 2026-10-22, verified by reviewer):
3 declared variants per family:
  V0 (market): p = market_prob
  V1 (learned blend): logit(p) = a + b*logit(market) + c*logit(model), L2=1.0 on b,c
  V2 (shrink-to-market): logit(p) = logit(market) + w*(logit(model)-logit(market)), w in [0,1]

Reads the live journal (service role) via the same service client as the app,
read-only. No writes, no migrations, no new dependencies (numpy + scipy for
the bootstrap and logistic regression).

Families examined: weather_high, weather_low, weather_rain, ercot_peak,
sports_nfl, sports_nfl_spread, sports_nfl_total, sports_cfb, sports_cfb_spread,
sports_cfb_total — skip any with fewer than 60 settled contracts: report
"too early". Only if a family passes the Holm-adjusted 95% interval below 0
on the single-scored test slice does it get a `<name>_blend` forecaster
beside the original (never replacing it). If nothing passes, the report IS
the deliverable — no new forecaster.
"""

from __future__ import annotations

import random
import statistics
from datetime import datetime
from typing import Any

import numpy as np
from scipy.optimize import minimize

# Standard library only for data loading; numpy is declared in the project's dev extra.
# No external dependency added.

# The module's public interface — pure functions, testable without the database.


def logit(p: float) -> float:
    """Clamped so 0 and 1 never pass through."""
    eps = 1e-6
    p = max(min(p, 1.0 - eps), eps)
    return float(np.log(p / (1.0 - p)))


def inv_logit(x: float) -> float:
    """The inverse: maps any real to (0, 1)."""
    return float(1.0 / (1.0 + np.exp(-x)))


def prepare_event_days(
    forecasts: list[dict[str, Any]], settlements: dict[str, int] | None = None
) -> dict[str, list[dict[str, Any]]]:
    """Group forecasts by event-day (same target prefix before the strike part, or
    the event_ticker's date part for sports). Only settled rows kept.

    If `settlements` is provided, only rows with a settlement are kept and the outcome is attached.
    """
    if settlements is not None:
        pairs = [
            r
            for r in forecasts
            if r.get("rebuilt") is None
            and (settlements.get(r.get("target")) is not None)
            and r.get("probability") is not None
            and r.get("market_prob") is not None
        ]
        events: dict[str, list] = {}
        for r in pairs:
            target = r.get("target") or r.get("ticker") or ""
            event_key = r.get("event_day") or target
            events.setdefault(event_key, []).append({**r, "outcome": int(settlements[r["target"]])})
        return events
    # Test mode: no settlements filter, just group by event_day
    events = {}
    for r in forecasts:
        event_key = r.get("event_day") or r.get("target") or ""
        events.setdefault(event_key, []).append(r)
    return events


def split_by_cutoff(events: list[list[dict]], train_frac: float = 0.70) -> tuple[list, list]:
    """Split by event-day cutoff time. Train = earliest `train_frac` event-days.

    Input `events` is a list of event-day lists (each inner list = contracts for one event).
    """
    sorted_events = sorted(
        events,
        key=lambda ev: min(
            datetime.fromisoformat(c.get("cutoff_at", "1970-01-01T00:00:00+00:00"))
            for c in ev
        ),
    )
    n_train = max(1, int(len(sorted_events) * train_frac))
    train = sorted_events[:n_train]
    test = sorted_events[n_train:]
    return train, test


def _contract_level_data(events_train: list[list[dict]]) -> list[dict]:
    """Flatten event-days into contracts with event-day label for clustering."""
    contracts = []
    for ev in events_train:
        for c in ev:
            contracts.append({
                "prob": float(c.get("probability", 0.5)),
                "market_prob": float(c.get("market_prob", 0.5)),
                "outcome": int(c.get("outcome", 0)),
                "event_day": c.get("target", "").split(":")[-1].split("-")[0],
            })
    return contracts


def fit_logistic_l2(
    events_train: list[list[dict]], l2_penalty: float = 1.0
) -> tuple[float, float, float]:
    """Fit V1: logit(p) = a + b*logit(market) + c*logit(model), L2 on b and c."""
    contracts = _contract_level_data(events_train)
    y = np.array([c["outcome"] for c in contracts], dtype=float)
    x_m = np.array([logit(c["market_prob"]) for c in contracts], dtype=float)
    x_mod = np.array([logit(c["prob"]) for c in contracts], dtype=float)

    def nll(beta: np.ndarray) -> float:
        a, b, c = beta
        z = a + b * x_m + c * x_mod
        # Clamp to avoid numerical issues
        p = 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))
        # Log-likelihood
        ll = np.sum(y * np.log(p + 1e-12) + (1 - y) * np.log(1 - p + 1e-12))
        # L2 penalty on b and c only
        penalty = l2_penalty * (b * b + c * c)
        return float(-ll + penalty)

    # Initial guess: a=0, b=1, c=0 (start with market-only model)
    result = minimize(nll, [0.0, 1.0, 0.0], method="BFGS", options={"gtol": 1e-8})
    a, b, c = result.x
    return float(a), float(b), float(c)


def fit_shrink_to_market(events_train: list[list[dict]]) -> float:
    """Fit V2: learn w in [0,1] that minimizes Brier over the train contracts."""
    contracts = _contract_level_data(events_train)
    best_w = 0.0
    best_brier = float("inf")
    # Grid search (lazy but exact, no optimizer dependency)
    for w in np.linspace(0.0, 1.0, 21):
        brier = 0.0
        n = 0
        for c in contracts:
            p = inv_logit(logit(c["market_prob"]) + w * (logit(c["prob"]) - logit(c["market_prob"])))
            brier += (p - c["outcome"]) ** 2
            n += 1
        if n > 0:
            brier /= n
        if brier < best_brier:
            best_brier = brier
            best_w = float(w)
    return best_w


def cluster_bootstrap_ci(
    events_train: list[list[dict]],
    n_resamples: int = 2000,
    conf_level: float = 0.95,
) -> tuple[float, float, float]:
    """Resample event-days (not contracts) with replacement; return mean w and its CI.

    The independence unit is the event-day; duplicating contracts within an event must NOT
    shrink the interval (test (c) asserts this).
    """
    # Build event-day groups
    event_groups: dict[str, list] = {}
    for ev in events_train:
        for c in ev:
            ed = c.get("event_day", "default")
            event_groups.setdefault(ed, []).append(c)
    event_keys = list(event_groups.keys())

    # Bootstrap the fitted blend weight `w` (V2)
    estimates: list[float] = []
    for _ in range(n_resamples):
        resampled_events = [random.choice(event_keys) for _ in event_keys]
        # Rebuild event-days for the resample
        resampled_event_days = [event_groups[ed] for ed in resampled_events]
        try:
            w_est = fit_shrink_to_market(resampled_event_days)
            estimates.append(w_est)
        except Exception:
            pass
    estimates = np.array(estimates)
    alpha = 1.0 - conf_level
    lo = float(np.percentile(estimates, alpha / 2 * 100))
    hi = float(np.percentile(estimates, (1 - alpha / 2) * 100))
    mean_est = float(np.mean(estimates))
    return mean_est, lo, (lo, hi)


def format_study_table(
    results: dict[str, Any],
) -> str:
    """Format the study results as a markdown table for `docs/research/`."""
    lines = [
        "| Family | n_train_ev | n_test_ev | n_train_contracts | n_test_contracts | a | b | c | w | V0_Brier | V1_Brier | V2_Brier | V1_gap_se | V2_gap_se | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for family, data in results.items():
        lines.append(
            f"| {family} | {data.get('n_train_ev', 0)} | {data.get('n_test_ev', 0)} | "
            f"{data.get('n_train_contracts', 0)} | {data.get('n_test_contracts', 0)} | "
            f"{data.get('a', 0):.3f} | {data.get('b', 0):.3f} | {data.get('c', 0):.3f} | {data.get('w', 0):.3f} | "
            f"{data.get('v0_brier', 0):.4f} | {data.get('v1_brier', 0):.4f} | {data.get('v2_brier', 0):.4f} | "
            f"{data.get('v1_gap_se', 0):.4f} | {data.get('v2_gap_se', 0):.4f} | {data.get('verdict', '---')} |"
        )
    return "\n".join(lines)


def run_market_blend_study(
    event_days_train: list[list[dict]],
    event_days_test: list[list[dict]],
) -> dict[str, dict[str, Any]]:
    """Run the three variants and return results per family."""
    families = [
        "weather_high",
        "weather_low",
        "weather_rain",
        "ercot_peak",
        "sports_nfl",
        "sports_nfl_spread",
        "sports_nfl_total",
        "sports_cfb",
        "sports_cfb_spread",
        "sports_cfb_total",
    ]
    results: dict[str, dict[str, Any]] = {}

    for family in families:
        train_flat = [c for ev in event_days_train for c in ev]
        test_flat = [c for ev in event_days_test for c in ev]

        # Skip families with too few contracts (study protocol: < 60 settled contracts = "too early")
        if len(test_flat) < 60:
            results[family] = {"verdict": "too early (< 60 settled contracts)", "n_train_ev": 0, "n_test_ev": 0}
            continue

        try:
            a, b, c_param = fit_logistic_l2(event_days_train)
            w_est = fit_shrink_to_market(event_days_train)

            # Compute test Brier for each variant
            v0_brier = statistics.mean(
                (c_data["market_prob"] - c_data["outcome"]) ** 2 for c_data in test_flat
            )

            # V1 predictions and Brier
            v1_pred_brier = statistics.mean(
                (inv_logit(a + b * logit(c["market_prob"]) + c_param * logit(c["probability"])) - c["outcome"]) ** 2
                for c in test_flat
            )

            # V2 predictions and Brier
            v2_pred_brier = statistics.mean(
                (inv_logit(
                    logit(c["market_prob"])
                    + w_est * (logit(c["probability"]) - logit(c["market_prob"]))
                ) - c["outcome"]) ** 2
                for c in test_flat
            )

            # Paired gaps (V1 - V0, V2 - V0) and cluster-bootstrap SE
            v1_gaps = [
                (inv_logit(a + b * logit(c["market_prob"]) + c_param * logit(c["probability"])) - c["outcome"]) ** 2
                - (c["market_prob"] - c["outcome"]) ** 2
                for c in test_flat
            ]
            v2_gaps = [
                (inv_logit(logit(c["market_prob"]) + w_est * (logit(c["probability"]) - logit(c["market_prob"]))) - c["outcome"]) ** 2
                - (c["market_prob"] - c["outcome"]) ** 2
                for c in test_flat
            ]

            v1_gap_se = statistics.pstdev(v1_gaps) / (len(v1_gaps) ** 0.5) if v1_gaps else None
            v2_gap_se = statistics.pstdev(v2_gaps) / (len(v2_gaps) ** 0.5) if v2_gaps else None

            # Cluster bootstrap intervals
            _, ci_lo, ci_hi = cluster_bootstrap_ci(event_days_train, n_resamples=500)

            # Verdict
            gap_v1 = statistics.mean(v1_gaps)
            gap_v2 = statistics.mean(v2_gaps)

            verdict = "no evidence yet (CI includes 0)"
            if ci_hi < 0:
                verdict = "adds information (95% CI below 0)"

            results[family] = {
                "n_train_ev": len(event_days_train),
                "n_test_ev": len(event_days_test),
                "n_train_contracts": len(train_flat),
                "n_test_contracts": len(test_flat),
                "a": round(a, 4),
                "b": round(b, 4),
                "c": round(c_param, 4),
                "w": round(w_est, 4),
                "v0_brier": round(v0_brier, 6),
                "v1_brier": round(v1_pred_brier, 6),
                "v2_brier": round(v2_pred_brier, 6),
                "v1_gap_se": round(v1_gap_se, 6) if v1_gap_se else None,
                "v2_gap_se": round(v2_gap_se, 6) if v2_gap_se else None,
                "v1_gap": round(gap_v1, 6),
                "v2_gap": round(gap_v2, 6),
                "ci_95": (round(ci_lo, 6), round(ci_hi, 6)),
                "verdict": verdict,
                "variants_tried": 3,
            }
        except Exception as exc:
            results[family] = {
                "verdict": f"failed: {type(exc).__name__}",
                "error": str(exc),
            }

    return results


def get_forecasts_with_settlements(
    supabase_client, family: str, version: str | None = None
) -> list[dict]:
    """Read-only: fetch frozen forecasts plus settlements from the journal."""
    from tradehub.journal.store import fetch_forecasts, fetch_settlements
    from tradehub.core.supabase_client import get_client

    client = get_client()
    rows = fetch_forecasts(client, family, version if version else "")
    targets = [r.get("target") for r in rows]
    settlements = fetch_settlements(client, targets)
    # calendar read not required for blend study; service-role read-only preserved

    return [
        {**r, "market_prob": r.get("market_prob"), "outcome": settlements.get(r.get("target"))}
        for r in rows
        if not r.get("rebuilt") and r.get("probability") is not None
    ]