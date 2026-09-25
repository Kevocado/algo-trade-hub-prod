"""The single place backtest code touches the network."""

from __future__ import annotations

import math
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import requests

MAX_ATTEMPTS = 5
BASE_BACKOFF_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0


def _retry_after_seconds(value: Any, *, now: datetime | None = None) -> float | None:
    """Parse Retry-After seconds or an HTTP date into a non-negative delay."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        seconds = float(text)
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError, OverflowError):
            return None
        if parsed is None:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        reference = now or datetime.now(timezone.utc)
        if reference.tzinfo is None:
            reference = reference.replace(tzinfo=timezone.utc)
        seconds = (parsed.astimezone(timezone.utc) - reference.astimezone(timezone.utc)).total_seconds()
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def default_get_json(url: str, params: dict | None = None) -> Any:
    """GET JSON with bounded exponential backoff for transient failures."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = requests.get(url, params=params, timeout=30)
        except requests.RequestException:
            if attempt >= MAX_ATTEMPTS - 1:
                raise
            time.sleep(min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS))
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError:
            status = getattr(response, "status_code", None)
            retryable = status == 429 or (isinstance(status, int) and 500 <= status <= 599)
            if not retryable or attempt >= MAX_ATTEMPTS - 1:
                raise
            headers = getattr(response, "headers", {}) or {}
            retry_after = _retry_after_seconds(headers.get("Retry-After"))
            exponential = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
            time.sleep(max(exponential, retry_after or 0.0))
            continue
        return response.json()
    raise RuntimeError("HTTP retry loop exited without a response")
