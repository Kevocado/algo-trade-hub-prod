"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each."""

from __future__ import annotations

from tradehub.journal.contract import Forecaster

FORECASTERS: list[Forecaster] = []
