from __future__ import annotations

from typing import Any

SIGNAL_EVENTS_TABLE = "signal_events"
LEGACY_CRYPTO_SIGNAL_EVENTS_VIEW = "crypto_signal_events"
CRYPTO_DOMAIN = "crypto"
SUPPORTED_SIGNAL_EVENT_DOMAINS = frozenset({CRYPTO_DOMAIN})


def normalize_signal_event(event: dict[str, Any], *, domain: str = CRYPTO_DOMAIN) -> dict[str, Any]:
    payload = dict(event)
    payload["domain"] = str(payload.get("domain") or domain).strip().lower()
    return payload


def is_supported_signal_event_domain(domain: str | None) -> bool:
    normalized = str(domain or "").strip().lower()
    return normalized in SUPPORTED_SIGNAL_EVENT_DOMAINS
