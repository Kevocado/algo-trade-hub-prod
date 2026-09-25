"""The single place backtest code touches the network."""

from __future__ import annotations

from typing import Any

import requests


def default_get_json(url: str, params: dict | None = None) -> Any:
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()
