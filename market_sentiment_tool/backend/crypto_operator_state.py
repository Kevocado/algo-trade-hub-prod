from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from market_sentiment_tool.backend.signal_events import CRYPTO_DOMAIN, SIGNAL_EVENTS_TABLE, normalize_signal_event


def _resolve_user_settings_user_id(supa: Any, user_id: str | None = None) -> str | None:
    if user_id:
        return user_id
    if supa is None:
        return None
    try:
        result = supa.table("user_settings").select("user_id").limit(1).execute()
        if result.data:
            return result.data[0].get("user_id")
    except Exception:
        return None
    return None


def fetch_trading_controls(supa: Any, user_id: str | None = None) -> dict[str, Any]:
    if supa is None:
        return {}

    query = supa.table("user_settings").select(
        "user_id,auto_trade_enabled,crypto_auto_trade_enabled,crypto_trading_disabled_reason,crypto_trading_disabled_at,updated_at"
    )
    target_user_id = _resolve_user_settings_user_id(supa, user_id=user_id)
    if target_user_id:
        query = query.eq("user_id", target_user_id)

    try:
        result = query.limit(1).execute()
        if result.data:
            return result.data[0]
    except Exception:
        return {}
    return {}


def is_crypto_trading_enabled(supa: Any, user_id: str | None = None) -> bool:
    controls = fetch_trading_controls(supa, user_id=user_id)
    if not controls:
        return False
    auto_trade_enabled = bool(controls.get("auto_trade_enabled", False))
    crypto_auto_trade_enabled = controls.get("crypto_auto_trade_enabled")
    if crypto_auto_trade_enabled is None:
        crypto_auto_trade_enabled = auto_trade_enabled
    return auto_trade_enabled and bool(crypto_auto_trade_enabled)


def set_crypto_trading_enabled(
    supa: Any,
    *,
    enabled: bool,
    user_id: str | None = None,
    reason: str | None = None,
) -> bool:
    if supa is None:
        return False

    target_user_id = _resolve_user_settings_user_id(supa, user_id=user_id)
    if not target_user_id:
        return False

    payload = {
        "crypto_auto_trade_enabled": bool(enabled),
        "crypto_trading_disabled_reason": None if enabled else reason,
        "crypto_trading_disabled_at": None if enabled else datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        supa.table("user_settings").update(payload).eq("user_id", target_user_id).execute()
        return True
    except Exception:
        return False


def insert_crypto_signal_event(
    supa: Any,
    *,
    event: dict[str, Any],
    user_id: str | None = None,
) -> bool:
    if supa is None:
        return False

    payload = normalize_signal_event(event, domain=CRYPTO_DOMAIN)
    target_user_id = _resolve_user_settings_user_id(supa, user_id=user_id)
    if target_user_id:
        payload["user_id"] = target_user_id

    try:
        supa.table(SIGNAL_EVENTS_TABLE).insert(payload).execute()
        return True
    except Exception:
        return False
