"""
shared/kalshi_ws.py
===================
Authenticated Kalshi WebSocket (Demo) client using the `websockets` library.

Responsibilities:
- Generate WS handshake auth headers using RSA-PSS (SHA256).
- Connect to the Demo WS endpoint.
- Subscribe to the public `ticker` channel.
- Reconnect on disconnect with exponential backoff.
- Route all incoming `type="ticker"` messages into an asyncio.Queue.

Security:
- Never embed private keys in code. Load via env/config and read from disk.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa, ed25519

log = logging.getLogger(__name__)

KALSHI_DEMO_WS_URL = "wss://demo-api.kalshi.co/trade-api/ws/v2"
_KALSHI_WS_PATH_TO_SIGN = "/trade-api/ws/v2"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_rsa_private_key(private_key_path: str):
    """
    Load an RSA private key from PEM at `private_key_path`.

    - Supports absolute paths and paths relative to repo root.
    - Raises ValueError with a clear error if missing/unreadable/unparseable.
    """
    if not private_key_path or not str(private_key_path).strip():
        raise ValueError("private_key_path is required (RSA private key PEM path).")

    path = Path(private_key_path)
    if not path.is_absolute():
        path = _repo_root() / path

    if not path.is_file():
        raise ValueError(f"RSA private key file not found: {path}")

    try:
        pem_bytes = path.read_bytes()
        return serialization.load_pem_private_key(pem_bytes, password=None)
    except Exception as exc:
        raise ValueError(f"Failed to load RSA private key from {path}: {exc}") from exc


def build_ws_auth_headers(
    *,
    api_key_id: str,
    private_key,
    timestamp_ms: Optional[str] = None,
) -> Dict[str, str]:
    """
    Build Kalshi WS handshake authentication headers.

    Signing string (per docs):
      timestamp + "GET" + "/trade-api/ws/v2"

    Signature:
      RSA-PSS + SHA256, salt_length = padding.PSS.DIGEST_LENGTH
    """
    if not api_key_id or not str(api_key_id).strip():
        raise ValueError("api_key_id is required.")

    ts = timestamp_ms or str(int(time.time() * 1000))
    msg = f"{ts}GET{_KALSHI_WS_PATH_TO_SIGN}"

    signature = sign_kalshi_message(private_key=private_key, message=msg.encode("utf-8"))
    sig_b64 = base64.b64encode(signature).decode("utf-8")

    return {
        "KALSHI-ACCESS-KEY": api_key_id,
        "KALSHI-ACCESS-SIGNATURE": sig_b64,
        "KALSHI-ACCESS-TIMESTAMP": ts,
    }


def sign_kalshi_message(*, private_key, message: bytes) -> bytes:
    """
    Kalshi signing helper.

    - RSA keys: RSA-PSS(SHA256)
    - Ed25519 keys: Ed25519 raw signature
    """
    if isinstance(private_key, rsa.RSAPrivateKey):
        return private_key.sign(
            message,
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.DIGEST_LENGTH,
            ),
            hashes.SHA256(),
        )
    if isinstance(private_key, ed25519.Ed25519PrivateKey):
        return private_key.sign(message)
    raise TypeError(f"Unsupported private key type for Kalshi signing: {type(private_key)}")


async def subscribe_ticker(ws, *, request_id: int = 1) -> None:
    """Subscribe to ticker updates for all markets."""
    msg = {
        "id": request_id,
        "cmd": "subscribe",
        "params": {"channels": ["ticker"]},
    }
    await ws.send(json.dumps(msg))


def _get_default_kalshi_config() -> tuple[Optional[str], Optional[str]]:
    """
    Prefer shared.config if available; fall back to environment variables.

    This module is meant to be usable in isolation, so it tolerates environments
    where importing shared.config might fail due to unrelated required vars.
    """
    try:
        from shared import config  # type: ignore

        return (getattr(config, "KALSHI_API_KEY_ID", None), getattr(config, "KALSHI_PRIVATE_KEY_PATH", None))
    except Exception:
        return (os.getenv("KALSHI_API_KEY_ID"), os.getenv("KALSHI_PRIVATE_KEY_PATH"))


async def connect_and_listen(
    ticker_queue: asyncio.Queue,
    *,
    ws_url: str = KALSHI_DEMO_WS_URL,
    api_key_id: Optional[str] = None,
    private_key_path: Optional[str] = None,
    min_backoff_s: float = 1.0,
    max_backoff_s: float = 60.0,
    jitter_s: float = 0.25,
) -> None:
    """
    Connect to Kalshi WS (authenticated), subscribe to ticker, and route ticker
    messages into `ticker_queue`. Reconnect on disconnect with exponential backoff.
    """
    if min_backoff_s <= 0:
        raise ValueError("min_backoff_s must be > 0")
    if max_backoff_s < min_backoff_s:
        raise ValueError("max_backoff_s must be >= min_backoff_s")
    if jitter_s < 0:
        raise ValueError("jitter_s must be >= 0")

    default_key_id, default_key_path = _get_default_kalshi_config()
    api_key_id = api_key_id or default_key_id
    private_key_path = private_key_path or default_key_path

    if not api_key_id:
        raise ValueError("Missing Kalshi API key id. Set KALSHI_API_KEY_ID or pass api_key_id=...")
    if not private_key_path:
        raise ValueError("Missing Kalshi private key path. Set KALSHI_PRIVATE_KEY_PATH or pass private_key_path=...")

    private_key = load_rsa_private_key(private_key_path)

    backoff_s = min_backoff_s

    while True:
        try:
            headers = build_ws_auth_headers(api_key_id=api_key_id, private_key=private_key)

            try:
                import websockets  # type: ignore
            except ImportError as exc:
                raise RuntimeError("Missing dependency: websockets (pip install websockets)") from exc

            log.info("Kalshi WS connecting to %s", ws_url)

            # websockets has renamed header args across versions; support both.
            try:
                ws_cm = websockets.connect(ws_url, additional_headers=headers)
            except TypeError:
                ws_cm = websockets.connect(ws_url, extra_headers=headers)

            async with ws_cm as ws:
                log.info("Kalshi WS connected; subscribing to ticker")
                await subscribe_ticker(ws)

                backoff_s = min_backoff_s  # reset after successful connect

                async for raw in ws:
                    try:
                        if isinstance(raw, (bytes, bytearray)):
                            raw = raw.decode("utf-8", errors="replace")
                        data = json.loads(raw)
                        if data.get("type") == "ticker":
                            await ticker_queue.put(data)
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        # Malformed payloads should not crash the stream.
                        log.debug("Kalshi WS message parse/route failed", exc_info=True)

        except asyncio.CancelledError:
            raise
        except Exception:
            log.warning("Kalshi WS disconnected/error; reconnecting soon", exc_info=True)

            sleep_s = min(backoff_s, max_backoff_s) + (random.random() * jitter_s if jitter_s else 0.0)
            await asyncio.sleep(sleep_s)
            backoff_s = min(backoff_s * 2.0, max_backoff_s)
