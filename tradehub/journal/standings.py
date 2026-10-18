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
    }


def standings(cards: list[dict[str, Any]], backtests: list[dict[str, Any]]) -> dict[str, Any]:
    """Rank the forecasters by their measured gap. Pure: both inputs are already fetched.

    A forecaster with no replay row is NOT given a gap of 0.0 and ranked. It appears in neither end,
    because there is nothing measured to rank it on; `n_settled` still counts it, so the page's
    evidence total is not quietly reduced by a model that has been running but not replayed.
    """
    latest = {(r.get("forecaster"), r.get("forecaster_version")): r for r in backtests}
    measured = [_entry(c, latest.get((c.get("forecaster"), c.get("forecaster_version"))))
                for c in cards]

    def _gap(e: dict[str, Any]) -> float | None:
        return e["gap"]

    ranked = sorted((e for e in measured if _gap(e) is not None),
                    key=lambda e: (_gap(e) is None, _gap(e)))
    return {
        "best": ranked[0] if ranked else None,
        "worst": ranked[-1] if len(ranked) > 1 else None,
        "n_settled": sum(int(c.get("n_settled") or 0) for c in cards),
        "n_replayed": len(ranked),
        "forecasters": len(cards),
        # Only a market-linked baseline can support a "beats the market" claim: a card graded against
        # climatology has no market to be better than. Listed, never pooled into that claim.
        "market_linked": sorted(c.get("forecaster") for c in cards if c.get("baseline") == "market"),
        "distinct_se": DISTINCT_SE,
    }


def _fmt(value: float | None, places: int = 3) -> str:
    return "—" if value is None else f"{value:+.{places}f}"


def verdict_sentence(rows: dict[str, Any]) -> str:
    """The lede, assembled from the numbers. Every branch is derived; none is a fixed conclusion.

    A claim of beating the market is only ever made when a market-linked forecaster's gap clears two
    standard errors. Otherwise the sentence says what was measured -- the gap, the interval, and how
    far inside it the result sits -- because that is the claim the data supports.
    """
    if not rows["forecasters"] or not rows["n_settled"]:
        return ("No forecaster has settled results yet, so there is nothing to compare against "
                "the Kalshi price.")

    best = rows["best"]
    if best is None:
        return (f"{rows['n_settled']} settled results across {rows['forecasters']} forecasters, "
                "but no replay yet, so skill against the market is not measured.")

    gap, se, n = best["gap"], best["se"], best["n"]
    window = f"{_fmt(gap)} ± {_fmt(se)}" if se is not None else f"{_fmt(gap)} with no interval"
    plural = "contract" if rows["n_settled"] == 1 else "contracts"
    sample = f"over {n} replayed sessions" if n else "over an unrecorded number of sessions"

    if best["verdict"] == "beats" and best["baseline"] == "market":
        return (f"{best['forecaster']} beats the Kalshi price by {_fmt(gap)} ± {_fmt(se)} "
                f"{sample}, on {rows['n_settled']} settled {plural} in total.")

    if best["verdict"] == "unknown":
        return (f"Best measured result is {best['forecaster']} at {_fmt(gap)}, but no interval was "
                f"recorded, so we cannot say whether it clears noise. {sample}.")

    # Indistinguishable is the honest common case and gets the plainest wording.
    return (f"No forecaster beats the Kalshi price after costs. Best is {best['forecaster']} at "
            f"{window} {sample}, inside the noise.")