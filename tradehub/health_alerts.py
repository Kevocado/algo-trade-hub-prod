"""Failure notifier for the health report: one Telegram message when something is wrong.

Deliberately tiny and dependency-light. The heavy `tradehub.core.telegram_notifier` is an async
operator plane with a command loop and Kalshi signing; this needs none of that, and importing it here
would drag an event loop and credentials into a read-only health path.

Two rules:
  * **Never print or log a secret.** The bot token is read from the environment and placed only in
    the request URL that Telegram itself requires; it is never returned to a caller or printed.
  * **Unconfigured is a no-op, not an error.** If TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is absent we
    return False and the caller says so out loud. We do not invent a destination and we do not read
    `.env` ourselves -- the process environment is the only source, and the API's lifespan
    `load_local_env()` is what populates it before any of this runs.
"""

from __future__ import annotations

import os
from typing import Any, Callable

import requests

TELEGRAM_SEND_URL = "https://api.telegram.org/bot{token}/sendMessage"
# Telegram rejects a message longer than this outright, so a long problem list would be dropped rather
# than truncated. Split instead, on line boundaries.
TELEGRAM_MAX_CHARS = 4096


def telegram_configured() -> bool:
    """True only when BOTH the bot token and the chat id are present in the environment."""
    return bool(_token() and _chat_id())


def _token() -> str:
    return (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()


def _chat_id() -> str:
    return (os.getenv("TELEGRAM_CHAT_ID") or "").strip()


def build_alert_message(report: dict[str, Any]) -> str:
    """A short human message for a degraded report, or "" when the report is healthy.

    Empty for a healthy report is load-bearing: it is what keeps `alert_on_failures` from sending a
    "nothing is wrong" ping every time it is called.
    """
    problems = list(report.get("problems") or [])
    if not problems:
        return ""
    generated = report.get("generated_at", "")
    lines = ["Algo Trade Hub health check", f"as of {generated}", ""]
    lines.extend(f"- {p}" for p in problems)
    lines.append("")
    lines.append(f"{len(problems)} problem(s). See /health.")
    return "\n".join(lines)


def split_message(message: str, limit: int = TELEGRAM_MAX_CHARS) -> list[str]:
    """Split a message into chunks each within Telegram's limit, never mid-line.

    A single line longer than the limit is hard-split rather than dropped: losing a problem line to a
    length rule is the one outcome a health alert must not have.
    """
    if len(message) <= limit:
        return [message]
    chunks: list[str] = []
    current = ""
    for line in message.splitlines():
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_alert(
    message: str,
    *,
    post: Callable[..., Any] = requests.post,
) -> bool:
    """POST the message to the configured chat, split to fit. True only if every chunk sent."""
    token, chat_id = _token(), _chat_id()
    if not token or not chat_id:
        return False
    try:
        for chunk in split_message(message):
            response = post(
                TELEGRAM_SEND_URL.format(token=token),
                json={"chat_id": chat_id, "text": chunk},
                timeout=10,
            )
            if getattr(response, "status_code", 0) != 200:
                return False
    except Exception:  # noqa: BLE001 - a notifier must never crash the caller
        return False
    return True


def alert_on_failures(
    report: dict[str, Any],
    *,
    post: Callable[..., Any] = requests.post,
) -> bool:
    """Send an alert if the report is degraded AND Telegram is configured; else no-op.

    Returns True only when a message was actually delivered. False covers both "healthy" and "not
    configured", so a caller that wants to distinguish them checks `build_alert_message` first.
    """
    message = build_alert_message(report)
    if not message:
        return False
    if not telegram_configured():
        return False
    return send_alert(message, post=post)
