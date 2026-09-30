"""FRED Case-Shiller National HPI (CSNTINSA) for monthly direction forecasting.

Spec §8: Housing forecaster freezes monthly on the FRED release calendar (~2 months after
observation), settles on the release value. No intra-month nowcasting in v1.
"""
from __future__ import annotations

from datetime import date
from collections.abc import Mapping
from tradehub.data.fred_daily import fetch_fred_daily

CASE_SHILLER_SERIES = "CSNTINSA"


def fetch_case_shiller(start: date) -> Mapping[date, float]:
    """Fetch Case-Shiller National HPI from FRED."""
    return fetch_fred_daily(CASE_SHILLER_SERIES, start)
