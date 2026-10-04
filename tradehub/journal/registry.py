"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each.

Constructing a forecaster must not touch the network: clients are built here, used only when the
runner calls `targets`/`forecast`/`settle`.
"""

from __future__ import annotations

from tradehub.core.kalshi_feed import fetch_market
from tradehub.core.supabase_client import get_client
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.contract import Forecaster
from tradehub.journal.forecasters.baselines import build_baselines
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.daily_direction import build_wave2, wave2_closes
from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
from tradehub.journal.forecasters.housing import HousingForecaster
from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
from tradehub.journal.forecasters.sentiment import SentimentMeter
from tradehub.journal.forecasters.shrunk import MarketShrunk
from tradehub.journal.forecasters.sports import build_sports
from tradehub.journal.forecasters.spy_quant import SpyQuant
from tradehub.journal.kalshi_linked import KalshiImplied
from tradehub.journal.spx import SpxCloses

_LIVE = KalshiLive()
_LABOR = LaborData()
_SPX = SpxCloses()
_HOUSING = HousingForecaster()
# One closes object per wave-2 family, given to BOTH the model and its naive baselines (see
# `baselines.py`: the climatology a baseline freezes has to be the one the calendar carries).
_WAVE2 = wave2_closes()

FORECASTERS: list[Forecaster] = [
    # plan (b): CPI + FOMC, each beside its Kalshi pseudo-forecaster (spec §5, ruling Q5)
    CpiForecaster("KXCPI", _LIVE, fetch_market),
    CpiForecaster("KXCPICORE", _LIVE, fetch_market),
    KalshiImplied("cpi", ("KXCPI", "KXCPICORE"), "monthly", _LIVE, fetch_market),
    FomcMapped(_LIVE, fetch_market),
    KalshiImplied("fomc", (FOMC_SERIES,), "meeting", _LIVE, fetch_market, keep=is_hold_market),
    # plan (c): labor (spec §5); payrolls beside the market, the direction fits vs climatology
    PayrollsForecaster(_LIVE, fetch_market, _LABOR),
    KalshiImplied("labor", ("KXPAYROLLS",), "monthly", _LIVE, fetch_market),
    UnrateDirection(_LIVE, _LABOR),
    QuitsDirection(_LABOR),
    # plan (d): sentiment meter (spec §6)
    SentimentMeter(_SPX),
    # plan (e): walk-forward quant (spec §7); same target and settlement as the meter
    SpyQuant(_SPX),
    # wave 2 (spec §8): VIX, gold (GLD) and EUR/USD daily direction, same walk-forward model
    *build_wave2(_WAVE2),
    # wave 3 (spec §8): Case-Shiller national HPI month-over-month direction
    _HOUSING,
    # spec §8/§10: the naive baselines -- persistence and climatology for every non-market direction
    # family, each beside the model whose targets it prices, on the same closes and its own calendar.
    # Never promoted and never counted as evidence: see `forecasters/baselines.py` and `scoring.py`.
    *build_baselines(_SPX, _WAVE2, _HOUSING),
    # wave 3 (spec §8): NFL and CFB feed consumers, each beside its Kalshi-implied baseline
    *build_sports(),
]

# plan 15: the market-linked models again, each pulled toward the Kalshi price (see forecasters/shrunk.py).
# Their own scorecards, beside the pure models', which are untouched.
_SHRINKABLE = {"cpi_nowcast", "fomc_mapped", "labor_nowcast"}
# Order matters and is relied on: `run_journal` walks the list, so each wrapper finds the model's own
# frozen row already in the store (see forecasters/shrunk.py). The store is passed as a callable
# because this module is imported with no credentials in hand.
FORECASTERS += [MarketShrunk(f, get_client) for f in list(FORECASTERS)
                if f.name in _SHRINKABLE or f.name.startswith("sports_")]
