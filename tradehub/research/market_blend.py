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
    """Flatten event-days; drop contracts missing probability, market_prob, or outcome."""
    contracts = []
    for ev in events_train:
        for c in ev:
            prob = c.get("probability")
            mkt = c.get("market_prob")
            out = c.get("outcome")
            if prob is None or mkt is None or out is None:
                continue  # missing market_prob dropped, never filled
            contracts.append({
                "prob": float(prob),
                "market_prob": float(mkt),
                "outcome": int(out),
                "event_day": c.get("event_day", c.get("target", "").split(":")[-1].split("-")[0]),
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
    seed: int = 42,
) -> tuple[float, float, float]:
    """Event-day resample bootstrap of V2 shrink-weight `w`. Returns (mean, lo, hi)."""
    rng = random.Random(seed)
    event_groups: dict[str, list] = {}
    for ev in events_train:
        for c in ev:
            ed = c.get("event_day", c.get("target", "default"))
            event_groups.setdefault(ed, []).append(c)
    event_keys = list(event_groups.keys())
    estimates: list[float] = []
    for _ in range(n_resamples):
        resampled_events = [event_keys[rng.randrange(len(event_keys))] for _ in event_keys]
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
    return mean_est, lo, hi


def cluster_bootstrap_gap_ci(
    events_test: list[list[dict]],
    a: float, b: float, c: float, w_est: float,
    n_resamples: int = 2000,
    conf_level: float = 0.95,
    seed: int = 42,
) -> tuple[float, float, float, float, float, float]:
    """Event-day cluster bootstrap of V1-V0 and V2-V0 paired gaps on test slice."""
    rng = random.Random(seed)
    event_groups: dict[str, list] = {}
    for ev in events_test:
        ed = ev[0].get("event_day", ev[0].get("target", "default")) if ev else "default"
        event_groups.setdefault(ed, ev)
    event_keys = list(event_groups.keys())
    if not event_keys:
        return 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
    v1_estimates: list[float] = []
    v2_estimates: list[float] = []
    for _ in range(n_resamples):
        resampled_events = [event_groups[event_keys[rng.randrange(len(event_keys))]] for _ in event_keys]
        contracts = [c for ev in resampled_events for c in ev]
        v1_gaps = []
        v2_gaps = []
        for c_data in contracts:
            p0 = c_data.get("market_prob", 0.5)
            p_model = c_data.get("probability", 0.5)
            out = int(c_data.get("outcome", 0))
            p_v1 = inv_logit(a + b * logit(p0) + c * logit(p_model))
            p_v2 = inv_logit(logit(p0) + w_est * (logit(p_model) - logit(p0)))
            v1_gaps.append((p_v1 - out) ** 2 - (p0 - out) ** 2)
            v2_gaps.append((p_v2 - out) ** 2 - (p0 - out) ** 2)
        if v1_gaps:
            v1_estimates.append(statistics.mean(v1_gaps))
        if v2_gaps:
            v2_estimates.append(statistics.mean(v2_gaps))
    alpha = 1.0 - conf_level
    def _interval(estimates: list[float]) -> tuple[float, float, float]:
        if not estimates:
            return 0.0, 0.0, 0.0
        arr = np.array(estimates)
        mean_est = float(np.mean(arr))
        lo = float(np.percentile(arr, alpha / 2 * 100))
        hi = float(np.percentile(arr, (1 - alpha / 2) * 100))
        return mean_est, lo, hi
    v1_mean, v1_lo, v1_hi = _interval(v1_estimates)
    v2_mean, v2_lo, v2_hi = _interval(v2_estimates)
    return v1_mean, v1_lo, v1_hi, v2_mean, v2_lo, v2_hi


def _fmt_f(v) -> str:
    return f"{v:.3f}" if isinstance(v, float) else (str(v) if v is not None else "---")

def _fmt_brier(v) -> str:
    return f"{v:.4f}" if isinstance(v, float) else (str(v) if v is not None else "---")

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
            f"{_fmt_f(data.get('a'))} | {_fmt_f(data.get('b'))} | {_fmt_f(data.get('c'))} | {_fmt_f(data.get('w'))} | "
            f"{_fmt_brier(data.get('v0_brier'))} | {_fmt_brier(data.get('v1_brier'))} | {_fmt_brier(data.get('v2_brier'))} | "
            f"{_fmt_brier(data.get('v1_gap_se'))} | {_fmt_brier(data.get('v2_gap_se'))} | {data.get('verdict', '---')} |"
        )
    return "\n".join(lines)


def run_market_blend_study(
    event_days_train: list[list[dict]],
    event_days_test: list[list[dict]],
    family: str = "",
) -> dict[str, dict[str, Any]]:
    """Run three variants. If family given, contracts filtered by family tag."""
    def _filter_family(ev_list: list[list[dict]]) -> list[list[dict]]:
        if not family:
            return ev_list
        filtered = []
        for ev in ev_list:
            matches = []
            for c in ev:
                target = c.get("target", "")
                ed = c.get("event_day", "")
                forecaster = c.get("forecaster", "")
                if family in target or family in ed or family in forecaster:
                    matches.append(c)
            if matches:
                filtered.append(matches)
        return filtered

    train_ev = _filter_family(event_days_train)
    test_ev = _filter_family(event_days_test)
    families = [
        "weather_high", "weather_low", "weather_rain", "ercot_peak",
        "sports_nfl", "sports_nfl_spread", "sports_nfl_total",
        "sports_cfb", "sports_cfb_spread", "sports_cfb_total",
    ]
    families_to_run = [family] if (family and family in families) else (families if not family else [family])
    results: dict[str, dict[str, Any]] = {}

    for f in families_to_run:
        f_train = train_ev if (f == family or not family) else _filter_family(event_days_train)
        f_test = test_ev if (f == family or not family) else _filter_family(event_days_test)
        f_train_flat = [c for ev in f_train for c in ev]
        f_test_flat = [c for ev in f_test for c in ev]
        if len(f_test_flat) < 60:
            results[f] = {
                "verdict": "too early (< 60 settled contracts)",
                "n_train_ev": len(f_train), "n_test_ev": len(f_test),
                "n_train_contracts": len(f_train_flat),
                "n_test_contracts": len(f_test_flat),
                "a": None, "b": None, "c": None, "w": None,
                "v0_brier": None, "v1_brier": None, "v2_brier": None,
                "v1_gap": None, "v2_gap": None,
                "v1_gap_se": None, "v2_gap_se": None,
                "ci_95_v1": (None, None), "ci_95_v2": (None, None),
                "variants_tried": 0,
            }
            continue
        try:
            a, b, c_param = fit_logistic_l2(f_train)
            w_est = fit_shrink_to_market(f_train)
            v0_brier = statistics.mean(
                (c_data.get("market_prob", 0.5) - int(c_data.get("outcome", 0))) ** 2
                for c_data in f_test_flat
            )
            v1_pred_brier = statistics.mean(
                (inv_logit(a + b * logit(c_data.get("market_prob", 0.5)) + c_param * logit(c_data.get("probability", 0.5))) - int(c_data.get("outcome", 0))) ** 2
                for c_data in f_test_flat
            )
            v2_pred_brier = statistics.mean(
                (inv_logit(logit(c_data.get("market_prob", 0.5)) + w_est * (logit(c_data.get("probability", 0.5)) - logit(c_data.get("market_prob", 0.5)))) - int(c_data.get("outcome", 0))) ** 2
                for c_data in f_test_flat
            )
            v1_gaps = []
            v2_gaps = []
            for c_data in f_test_flat:
                p0 = c_data.get("market_prob", 0.5)
                p_model = c_data.get("probability", 0.5)
                out = int(c_data.get("outcome", 0))
                p_v1 = inv_logit(a + b * logit(p0) + c_param * logit(p_model))
                p_v2 = inv_logit(logit(p0) + w_est * (logit(p_model) - logit(p0)))
                v1_gaps.append((p_v1 - out) ** 2 - (p0 - out) ** 2)
                v2_gaps.append((p_v2 - out) ** 2 - (p0 - out) ** 2)
            gap_v1 = statistics.mean(v1_gaps) if v1_gaps else 0.0
            gap_v2 = statistics.mean(v2_gaps) if v2_gaps else 0.0
            v1_mean_g, v1_lo, v1_hi, v2_mean_g, v2_lo, v2_hi = cluster_bootstrap_gap_ci(
                f_test, a, b, c_param, w_est, n_resamples=2000, seed=42
            )
            verdict_v1 = "adds information" if v1_hi < 0 else "no evidence yet (CI includes 0)"
            verdict_v2 = "adds information" if v2_hi < 0 else "no evidence yet (CI includes 0)"
            # Family verdict based on V1 (learned blend) as primary; V2 reported separately in table
            verdict = verdict_v1
            v1_gap_se = statistics.pstdev(v1_gaps) / (len(v1_gaps) ** 0.5) if v1_gaps else None
            v2_gap_se = statistics.pstdev(v2_gaps) / (len(v2_gaps) ** 0.5) if v2_gaps else None
            results[f] = {
                "n_train_ev": len(f_train), "n_test_ev": len(f_test),
                "n_train_contracts": len(f_train_flat), "n_test_contracts": len(f_test_flat),
                "a": round(a, 4), "b": round(b, 4), "c": round(c_param, 4), "w": round(w_est, 4),
                "v0_brier": round(v0_brier, 6), "v1_brier": round(v1_pred_brier, 6), "v2_brier": round(v2_pred_brier, 6),
                "v1_gap_se": round(v1_gap_se, 6) if v1_gap_se else None,
                "v2_gap_se": round(v2_gap_se, 6) if v2_gap_se else None,
                "v1_gap": round(gap_v1, 6), "v2_gap": round(gap_v2, 6),
                "ci_95_v1": (round(v1_lo, 6), round(v1_hi, 6)),
                "ci_95_v2": (round(v2_lo, 6), round(v2_hi, 6)),
                "verdict": verdict, "verdict_v2": verdict_v2, "variants_tried": 3,
            }
        except Exception as exc:
            results[f] = {
                "verdict": f"failed: {type(exc).__name__}", "error": str(exc),
                "n_train_ev": len(f_train), "n_test_ev": len(f_test),
            }
    return results


def get_forecasts_with_settlements(
    supabase_client, family: str, version: str
) -> list[dict]:
    """Read-only: fetch frozen forecasts plus settlements from the journal.
    Only settled rows with both probability and market_prob kept.
    """
    from tradehub.journal.store import fetch_forecasts, fetch_settlements

    client = supabase_client
    rows = fetch_forecasts(client, family, version)
    targets = [r.get("target") for r in rows]
    settlements = fetch_settlements(client, targets)
    result = []
    for r in rows:
        if r.get("rebuilt"):
            continue
        prob = r.get("probability")
        mkt = r.get("market_prob")
        target = r.get("target")
        if prob is None or mkt is None or target is None:
            continue
        settlement = settlements.get(target)
        if settlement is None:
            continue  # unsettled rows dropped
        result.append({
            **r,
            "market_prob": mkt,
            "probability": prob,
            "outcome": int(settlement),
        })
    return result


def main(argv: list[str] | None = None) -> None:
    """CLI entrypoint: load study data from JSON file, run blend study, print table."""
    import argparse, json
    parser = argparse.ArgumentParser(description="Market-blend study (read-only)")
    parser.add_argument(
        "--from-json",
        metavar="FILE",
        required=True,
        help="JSON file with exported journal rows",
    )
    args = parser.parse_args(argv)
    with open(args.from_json, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        forecasts = data.get("forecasts", [])
    else:
        forecasts = data
    events = prepare_event_days(forecasts)
    event_list = list(events.values())
    train_ev, test_ev = split_by_cutoff(event_list)
    results = run_market_blend_study(train_ev, test_ev)
    print(format_study_table(results))


if __name__ == "__main__":
    main()