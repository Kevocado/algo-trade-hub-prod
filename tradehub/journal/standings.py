"""The front page's "what we found": the best and worst forecaster, each with its own error bar.

Pure. Nothing here recomputes a Brier score -- it reads what the journal already stored and compares
each forecaster's measured gap against the standard error stored beside it.

**Why this exists as its own rule.** An audit of the first replays found all four daily models within
0.01 of climatology over ~760 sessions, the best of them about 1.1 standard errors from zero:
indistinguishable from noise, printed as "+0.010". A number with no interval reads as a result. So
every figure here travels with its interval, and a gap that does not clear its own bar is reported as
indistinguishable rather than as a win.

**Deliberately no interval on `bss`.** BSS is a ratio of two means, so its standard error is neither
the gap's nor anything this module can measure. A delta-method approximation is easy to write and
would be a number nobody measured printed as though it were one (migration
`20260428000017_journal_backtests_uncertainty.sql` says this at length). The gap carries the
uncertainty; `bss` is `-brier_diff / brier_baseline` by definition, so a reader who wants skill with
an interval can derive it from a measured quantity.

**A missing figure is None, never 0.0.** A replay written before migration 017 carries no error bar,
and "we did not measure an interval" must not compare as a zero-width bar -- under which every gap
would read as a decisive win.
"""

from __future__ import annotations

from typing import Any

# How many standard errors a gap must clear to be called a result rather than noise. Two is the
# standing convention for a single comparison and is deliberately round: this is a disclosure
# threshold, not a hypothesis test, and the number is shown on the page so a reader can apply their own.
DISTINCT_SE = 2.0


def gap_verdict(diff: float | None, se: float | None) -> str:
    """`beats` / `loses to` / `indistinguishable` / `no difference` / `unknown`.

    `diff` is our mean squared error minus the baseline's, so NEGATIVE is better. `unknown` covers
    both absent values, and is reached before any comparison: without an interval there is no bar for
    the gap to clear, and defaulting to a zero-width one turns every replay into a decisive result.
    """
    if diff is None or se is None:
        return "unknown"
    if se == 0:
        return "no difference" if diff == 0 else ("beats" if diff < 0 else "loses to")
    if abs(diff) < DISTINCT_SE * se:
        return "indistinguishable"
    return "beats" if diff < 0 else "loses to"


# The live market-linked forecasters (graded against the Kalshi price). These are the ones that can
# claim "beats the Kalshi price" because their baseline IS the Kalshi price.
# Includes the cautious copies (shrunk versions) which also have baseline="market".
LIVE_MARKET_LINKED = frozenset({
    # Direction forecasters with KalshiImplied
    "cpi_nowcast", "fomc_mapped", "labor_nowcast",
    # Sports
    "sports_nfl", "sports_cfb",
    # Weather
    "weather_high", "weather_low", "weather_rain",
    # ERCOT
    "ercot_peak",
    # Gas
    "gas",
})


def _is_live_market_linked(card: dict[str, Any]) -> bool:
    """True if this forecaster is a live market-linked one (graded against Kalshi price)."""
    name = card.get("forecaster")
    version = card.get("forecaster_version", "")
    # Check by forecaster name
    if name in LIVE_MARKET_LINKED:
        return True
    # Check by version (cautious copies have version like "gas-v2_cautious")
    if version.endswith("_cautious") and name in {"cpi_nowcast", "fomc_mapped", "labor_nowcast", "sports_nfl", "sports_cfb"}:
        return True
    return False


def _entry(card: dict[str, Any], row: dict[str, Any] | None) -> dict[str, Any]:
    """One forecaster's row: the measured gap, its interval, and what those two justify."""
    diff = (row or {}).get("brier_diff")
    se = (row or {}).get("brier_diff_se")
    return {
        "forecaster": card.get("forecaster"),
        "version": card.get("forecaster_version"),
        "baseline": card.get("baseline"),
        "cadence": card.get("cadence"),
        "gap": diff,
        "se": se,
        "n": (row or {}).get("n"),
        "n_settled": card.get("n_settled"),
        "bss": (row or {}).get("bss"),
        "verdict": gap_verdict(diff, se),
        "date_from": (row or {}).get("date_from"),
        "date_to": (row or {}).get("date_to"),
        "costs": (row or {}).get("costs"),  # carry costs forward for the verdict sentence
    }


def _ranked_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort entries by gap (ascending, so most negative = best), excluding unknown gaps."""
    def _gap(e: dict[str, Any]) -> float | None:
        return e["gap"]
    return sorted(
        (e for e in entries if _gap(e) is not None),
        key=lambda e: (_gap(e) is None, _gap(e))
    )


def standings(cards: list[dict[str, Any]], backtests: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank the forecasters by their measured gap. Pure: both inputs are already fetched.

    Returns TWO separate leaderboards:
      - market_linked: forecasters graded against the Kalshi price (baseline="market")
      - climatology: forecasters graded against the usual rate (baseline="climatology")

    A forecaster with no replay row is NOT given a gap of 0.0 and ranked. It appears in neither end,
    because there is nothing measured to rank it on; `n_settled` still counts it.
    """
    latest = {(r.get("forecaster"), r.get("forecaster_version")): r for r in backtests}
    measured = [_entry(c, latest.get((c.get("forecaster"), c.get("forecaster_version"))))
                for c in cards]

    # Split into market-linked and climatology-baseline
    market_linked_entries = [e for e in measured if _is_live_market_linked(e)]
    climatology_entries = [e for e in measured if not _is_live_market_linked(e) and e["baseline"] == "climatology"]

    market_ranked = _ranked_entries(market_linked_entries)
    climato_ranked = _ranked_entries(climatology_entries)

    # Collect cost info for the verdict sentence (only market-linked cards can have costs)
    costs_map = {}
    for c in cards:
        if _is_live_market_linked(c):
            row = latest.get((c.get("forecaster"), c.get("forecaster_version")))
            if row and row.get("costs"):
                costs_map[c.get("forecaster")] = row["costs"]

    out: dict[str, Any] = {
        "n_settled": sum(int(c.get("n_settled") or 0) for c in cards),
        "n_replayed": len(market_ranked) + len(climato_ranked),
        "forecasters": len(cards),
        "distinct_se": DISTINCT_SE,
        "market_linked": [e["forecaster"] for e in market_ranked],
        "climatology": [e["forecaster"] for e in climato_ranked],
    }
    # Only include costs in output if at least one forecaster has costs
    if costs_map:
        out["costs"] = costs_map  # for the verdict sentence

    if market_ranked:
        out["market_linked_best"] = market_ranked[0]
        out["market_linked_worst"] = market_ranked[-1] if len(market_ranked) > 1 else None
    else:
        out["market_linked_best"] = None
        out["market_linked_worst"] = None

    if climato_ranked:
        out["climatology_best"] = climato_ranked[0]
        out["climatology_worst"] = climato_ranked[-1] if len(climato_ranked) > 1 else None
    else:
        out["climatology_best"] = None
        out["climatology_worst"] = None

    return out


def _fmt(value: float | None, places: int = 3) -> str:
    """Format a number with sign for gaps (e.g., −0.030, +0.020)."""
    if value is None:
        return "—"
    if value == 0:
        return "0" + "." + "0" * places
    return f"{value:+.{places}f}"


def _fmt_se(value: float | None, places: int = 3) -> str:
    """Format a standard error (always non-negative, no sign)."""
    if value is None:
        return "—"
    return f"{value:.{places}f}"


def _has_cost_edge(costs: dict[str, Any]) -> bool:
    """True if this card has costs data showing the edge survives after costs."""
    if not costs:
        return False
    edge_after = costs.get("edge_after_costs_pct")
    if edge_after is None:
        return False
    return edge_after > 0


def verdict_sentence(rows: dict[str, Any]) -> str:
    """The lede, assembled from the numbers. Every branch is derived; none is a fixed conclusion.

    A claim of beating the Kalshi price is only ever made when a MARKET-LINKED forecaster's
    gap clears two standard errors. Otherwise the sentence says what was measured -- the gap,
    the interval, and how far inside it the result sits -- because that is the claim the data supports.

    "After costs" is ONLY mentioned when a market-linked forecaster has costs data showing
    the edge survives after Kalshi's taker fee and spread.
    """
    if not rows["forecasters"] or not rows["n_settled"]:
        return ("No forecaster has settled results yet, so there is nothing to compare against "
                "the Kalshi price.")

    # Market-linked best is the primary result
    best_market = rows.get("market_linked_best")
    best_climato = rows.get("climatology_best")

    # Determine what we can say
    if best_market is None and best_climato is None:
        return (f"{rows['n_settled']} settled results across {rows['forecasters']} forecasters, "
                "but no replay yet, so skill is not measured.")

    plural = "contract" if rows["n_settled"] == 1 else "contracts"
    sample = ""

    # Market-linked result
    if best_market:
        gap, se, n = best_market["gap"], best_market["se"], best_market["n"]
        sample = f"over {n} replayed sessions" if n else "over an unrecorded number of sessions"
        window = f"{_fmt(gap)} ± {_fmt_se(se)}" if se is not None else f"{_fmt(gap)} with no interval"

        if best_market["verdict"] == "beats":
            # Check if this forecaster has costs backing the edge
            has_costs = best_market["forecaster"] in rows.get("costs", {})
            has_cost_edge = has_costs and _has_cost_edge(rows["costs"][best_market["forecaster"]])

            if has_cost_edge:
                return (f"{best_market['forecaster']} beats the Kalshi price after costs "
                        f"by {_fmt(gap)} ± {_fmt(se)} {sample}, "
                        f"on {rows['n_settled']} settled contracts in total.")
            else:
                return (f"{best_market['forecaster']} beats the Kalshi price "
                        f"by {_fmt(gap)} ± {_fmt(se)} {sample}, "
                        f"on {rows['n_settled']} settled {plural} in total.")

        if best_market["verdict"] == "unknown":
            return (f"Best measured result is {best_market['forecaster']} at {_fmt(gap)}, "
                    f"but no interval was recorded, so we cannot say whether it clears noise. "
                    f"{sample}.")

    # Climatology-best result (fallback when no market-linked beats)
    if best_climato:
        gap, se, n = best_climato["gap"], best_climato["se"], best_climato["n"]
        sample = f"over {n} replayed sessions" if n else "over an unrecorded number of sessions"
        window = f"{_fmt(gap)} ± {_fmt_se(se)}" if se is not None else f"{_fmt(gap)} with no interval"

        if best_climato["verdict"] == "beats":
            return (f"Best vs climatology is {best_climato['forecaster']} at {window} "
                    f"{sample}, on {rows['n_settled']} settled {plural} in total.")

        if best_climato["verdict"] == "unknown":
            return (f"Best measured result is {best_climato['forecaster']} at {_fmt(gap)}, "
                    f"but no interval was recorded, so we cannot say whether it clears noise. "
                    f"{sample}.")

    # Indistinguishable / loses to / no difference
    # Find the best overall (market-linked preferred if it has a gap, else climatology)
    best_overall = best_market or best_climato
    if best_overall:
        gap, se, n = best_overall["gap"], best_overall["se"], best_overall["n"]
        sample = f"over {n} replayed sessions" if n else "over an unrecorded number of sessions"
        window = f"{_fmt(gap)} ± {_fmt_se(se)}" if se is not None else f"{_fmt(gap)} with no interval"
        name = best_overall["forecaster"]

        if best_overall["verdict"] == "loses to":
            return (f"{name} loses to the baseline by {_fmt(-gap)} ± {_fmt(se)} {sample}, "
                    f"on {rows['n_settled']} settled {plural} in total.")
        if best_overall["verdict"] == "no difference":
            return (f"{name} matches the baseline {sample}, "
                    f"on {rows['n_settled']} settled {plural} in total.")

    # Default indistinguishable
    if best_overall:
        return (f"No forecaster beats its baseline. Best is {best_overall['forecaster']} at "
                f"{window} {sample}, inside the noise.")

    # Fallback
    return (f"{rows['n_settled']} settled results across {rows['forecasters']} forecasters, "
            "but no replay yet, so skill is not measured.")


def _fmt(value: float | None, places: int = 3) -> str:
    return "—" if value is None else f"{value:+.{places}f}"