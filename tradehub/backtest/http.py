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
MAX_RETRY_AFTER_SECONDS = 60.0
REQUEST_TIMEOUT_SECONDS = 30.0


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


def _remaining(deadline: float | None) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("HTTP per-call deadline exceeded")
    return remaining


def _retry_sleep(delay: float, deadline: float | None) -> None:
    remaining = _remaining(deadline)
    if remaining is not None and delay >= remaining:
        raise requests.Timeout("HTTP per-call deadline exceeded before retry")
    time.sleep(delay)


def default_get_json(
    url: str,
    params: dict | None = None,
    *,
    deadline: float | None = None,
) -> Any:
    """GET JSON with bounded retries and an optional monotonic deadline."""
    for attempt in range(MAX_ATTEMPTS):
        remaining = _remaining(deadline)
        request_timeout = REQUEST_TIMEOUT_SECONDS if remaining is None else min(REQUEST_TIMEOUT_SECONDS, remaining)
        try:
            response = requests.get(url, params=params, timeout=request_timeout)
        except requests.RequestException:
            if attempt >= MAX_ATTEMPTS - 1:
                raise
            _retry_sleep(min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS), deadline)
            continue
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            status = getattr(response, "status_code", None)
            retryable = status == 429 or (isinstance(status, int) and 500 <= status <= 599)
            if not retryable or attempt >= MAX_ATTEMPTS - 1:
                raise
            headers = getattr(response, "headers", {}) or {}
            retry_after = _retry_after_seconds(headers.get("Retry-After"))
            if retry_after is not None and retry_after > MAX_RETRY_AFTER_SECONDS:
                raise
            exponential = min(BASE_BACKOFF_SECONDS * (2**attempt), MAX_BACKOFF_SECONDS)
            try:
                _retry_sleep(max(exponential, retry_after or 0.0), deadline)
            except requests.Timeout as timeout_exc:
                raise timeout_exc from exc
            continue
        return response.json()
    raise RuntimeError("HTTP retry loop exited without a response")
