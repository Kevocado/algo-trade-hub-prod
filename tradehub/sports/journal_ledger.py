"""The hub's own settled record for sports, read from the prediction journal.

`scan._hub_settled_ledger` used to build this from every settled `predictions` row, which counted all the
rungs of a spread or total ladder as separate evidence. The journal journals one market per game and kind
(`tradehub.journal.forecasters.sports`), frozen before kickoff and settled on Kalshi's own result, so this
record is the same facts without the double counting. The shape it returns, `HubLedger`, is unchanged:
`engine -> kind -> [(probability, hit)]`.

It never raises: a failed or impossible read returns `HubLedger(read_failed=True)`, which the run report
publishes as "not measured", and the scan falls back to the predictor's published calibration exactly as it
did before.
"""

from __future__ import annotations

import logging

from tradehub.journal.store import FORECASTS, fetch_settlements, select_all
from tradehub.sports.kinds import KINDS
from tradehub.sports.scan import SPORTS_ENGINES, HubLedger

log = logging.getLogger(__name__)

# Spelled out, not imported: `journal.forecasters.sports` imports `sports.scan`, so importing it back
# would be a cycle. A test pins this to the journal's own constant.
HUB_FEED_VERSION = "feed-v1"


def _forecaster(sport: str, kind: str) -> str:
    """The journal's name for one sport and kind: `sports_nfl`, `sports_nfl_spread`, `sports_nfl_total`."""
    return f"sports_{sport}" + ("" if kind == "winner" else f"_{kind}")


def journal_settled_ledger(supa) -> HubLedger:
    pairs: dict[str, dict[str, list[tuple[float, bool]]]] = {}
    try:
        for sport, engine in SPORTS_ENGINES.items():
            for kind in KINDS:
                name = _forecaster(sport, kind)
                forecasts = select_all(
                    supa, FORECASTS,
                    lambda q, n=name: q.eq("forecaster", n).eq("forecaster_version", HUB_FEED_VERSION),
                    ("id",))
                outcomes = fetch_settlements(supa, [f["target"] for f in forecasts])
                rows = [(float(f["probability"]), bool(outcomes[f["target"]]))
                        for f in forecasts if f["target"] in outcomes]
                if rows:
                    pairs.setdefault(engine, {})[kind] = rows
    except Exception:
        log.exception("sports scan: journal read failed; using the predictor's calibration")
        return HubLedger(read_failed=True)
    return HubLedger(pairs, {})