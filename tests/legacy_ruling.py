"""The quarantine ruling as it stood while the legacy daemon ran, kept as DATA so its state machine stays tested.

`tradehub/scripts/background_scanner.py`, `macro_engine.py` and `quant_engine.py` were deleted (v2 spec §9)
and the daemon was the only thing that ever wired `WeatherEngine` or `MacroEngine` to a scanner. So in
production no site is wired any more and every edge type reads `ran`: truthfully, because `scan.py` feeds
the boards. The `quarantined` and `could_not_run` states, the partition and the copy around them are still
code, still reachable through `tradehub.engine_health`, and still pinned by `test_engine_health.py` and
`test_weather_macro_quarantine.py`; those tests assert against this frozen ruling instead of the live one.

`LiveTuple` makes the three ruling constants read the module's CURRENT value each time they are touched, so
a test that imports `STOPPED_SITES` sees whatever the autouse fixture (or its own monkeypatch) installed.
"""

from __future__ import annotations

from dataclasses import replace

from tradehub import engine_health as health


class LiveTuple:
    """A read-through view of `tradehub.engine_health.<name>`; iterates, indexes, sizes and tests membership."""

    def __init__(self, name: str):
        self._name = name

    def _value(self):
        return getattr(health, self._name)

    def __iter__(self):
        return iter(self._value())

    def __len__(self):
        return len(self._value())

    def __getitem__(self, index):
        return self._value()[index]

    def __contains__(self, item):
        return item in self._value()


STOPPED_SITES = LiveTuple("STOPPED_SITES")
WIRED_STOPPED_SITES = LiveTuple("WIRED_STOPPED_SITES")
UNWIRED_STOPPED_SITES = LiveTuple("UNWIRED_STOPPED_SITES")

_REAL = {site.name: site for site in health.STOPPED_SITES}

LEGACY_SITES = (
    replace(_REAL["WeatherEngine"], wired_to_a_scanner=True),
    health.StoppedSite(
        name="MacroEngine",
        module="tradehub/engines/macro_engine.py",  # deleted: a tombstone, so file-evidence tests skip it
        site="tradehub/engines/macro_engine.py:459",
        edge_type="MACRO",
        wired_to_a_scanner=True,
        disposition="repaired_quarantined",
        reason=("This is the Tier-1 real-edge macro engine, and it prices every market against `yes_ask`. "
                + health._THE_API_MOVED + health._REPAIRED_AND_QUARANTINED),
    ),
    _REAL["WeatherMaker"],
    _REAL["clean_market_data"],
)

DELETED_MODULES = frozenset({"tradehub/engines/macro_engine.py"})


def install(monkeypatch) -> None:
    """Make `tradehub.engine_health` answer from the legacy ruling for the duration of one test."""
    monkeypatch.setattr(health, "STOPPED_SITES", LEGACY_SITES)
    monkeypatch.setattr(health, "STOPPED_SITE_NAMES", frozenset(s.name for s in LEGACY_SITES))
    monkeypatch.setattr(health, "WIRED_STOPPED_SITES", tuple(s for s in LEGACY_SITES if s.wired_to_a_scanner))
    monkeypatch.setattr(health, "UNWIRED_STOPPED_SITES", tuple(s for s in LEGACY_SITES if not s.wired_to_a_scanner))
