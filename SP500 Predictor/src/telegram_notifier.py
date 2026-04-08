"""
Async Telegram operator plane for Kalshi crypto trading.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from shared.kalshi_ws import load_rsa_private_key, sign_kalshi_message
from market_sentiment_tool.backend.runtime_bootstrap import resolve_kalshi_runtime_settings

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip('"').strip("'")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip('"').strip("'")
SUPABASE_URL = os.getenv("SUPABASE_URL", "") or os.getenv("VITE_SUPABASE_URL", "")
SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
KALSHI_API_KEY_ID = os.getenv("KALSHI_API_KEY_ID", "")
KALSHI_PRIVATE_KEY_PATH = os.getenv("KALSHI_PRIVATE_KEY_PATH", "")
KALSHI_TRADE_API_V2_BASE = resolve_kalshi_runtime_settings().api_base

POLL_INTERVAL = int(os.getenv("TELEGRAM_POLL_INTERVAL_S", "5"))


class TelegramNotifier:
    def __init__(self) -> None:
        self.bot_token = BOT_TOKEN
        self.chat_id = CHAT_ID
        self.supabase_url = SUPABASE_URL.rstrip("/")
        self.supabase_service_role_key = SUPABASE_SERVICE_ROLE_KEY
        self.kalshi_api_key_id = KALSHI_API_KEY_ID
        self.kalshi_private_key_path = KALSHI_PRIVATE_KEY_PATH
        self.kalshi_base_url = KALSHI_TRADE_API_V2_BASE.rstrip("/")
        self.base_url = f"https://api.telegram.org/bot{self.bot_token}"
        self._session: aiohttp.ClientSession | None = None
        self._resolved_chat_id: str | None = None
        self._last_update_id = 0
        self._private_key = None

    def is_enabled(self) -> bool:
        return bool(self.bot_token and self.chat_id)

    async def start(self) -> None:
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=20)
            self._session = aiohttp.ClientSession(timeout=timeout)
        await self._get_chat_id()

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None:
            await self.start()
        assert self._session is not None
        return self._session

    async def _get_chat_id(self) -> str:
        if self._resolved_chat_id:
            return self._resolved_chat_id
        if self.chat_id.lstrip("-").isdigit():
            self._resolved_chat_id = self.chat_id
            return self._resolved_chat_id

        session = await self._ensure_session()
        async with session.get(f"{self.base_url}/getUpdates") as response:
            if response.status == 200:
                payload = await response.json()
                for update in payload.get("result", []):
                    chat_id = update.get("message", {}).get("chat", {}).get("id")
                    if chat_id:
                        self._resolved_chat_id = str(chat_id)
                        return self._resolved_chat_id

        self._resolved_chat_id = self.chat_id
        return self._resolved_chat_id

    async def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        if not self.is_enabled():
            return False
        session = await self._ensure_session()
        chat_id = await self._get_chat_id()
        try:
            async with session.post(
                f"{self.base_url}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
            ) as response:
                return response.status == 200
        except Exception:
            return False

    async def send_alert(self, text: str) -> bool:
        return await self.send_message(text)

    async def alert_crypto_opportunity(
        self,
        *,
        asset: str,
        market_ticker: str,
        side: str,
        probability_yes: float,
        edge: float | None,
        price_dollars: float,
        reason: str,
    ) -> bool:
        title = "🚨 *Crypto Near Miss*" if reason == "near_miss" else "💡 *Crypto Opportunity*"
        blocked_by = "Edge < 5%" if reason == "near_miss" else reason
        return await self.send_message(
            "\n".join(
                [
                    title,
                    "",
                    f"Asset: *{asset}*",
                    f"Market: `{market_ticker}`",
                    f"Side: *{side}*",
                    f"P(YES): *{probability_yes:.3f}*",
                    f"Signal Price: *${price_dollars:.4f}*",
                    f"Edge: *{(edge or 0.0):+.3f}*",
                    f"Blocked By: *{blocked_by}*",
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
                ]
            )
        )

    async def alert_crypto_trade_executed(
        self,
        *,
        asset: str,
        market_ticker: str,
        side: str,
        price_dollars: float,
        edge: float,
        count: int,
        execution_result: dict[str, Any],
    ) -> bool:
        return await self.send_message(
            "\n".join(
                [
                    "✅ *Crypto Demo Trade Executed*",
                    "",
                    f"Asset: *{asset}*",
                    f"Market: `{market_ticker}`",
                    f"Contract Side: *{side}*",
                    f"Count: *{count}*",
                    f"Limit Price: *${price_dollars:.4f}*",
                    f"Edge: *{edge:+.3f}*",
                    f"Order Ref: `{execution_result.get('external_order_id') or execution_result.get('order_id') or execution_result.get('id') or 'n/a'}`",
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
                ]
            )
        )

    async def alert_crypto_trade_failed(self, *, asset: str, market_ticker: str, reason: str) -> bool:
        return await self.send_message(
            "\n".join(
                [
                    "❌ *Crypto Demo Trade Failed*",
                    "",
                    f"Asset: *{asset}*",
                    f"Market: `{market_ticker}`",
                    f"Reason: `{reason}`",
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
                ]
            )
        )

    async def alert_crypto_trading_disabled(self, *, asset: str, market_ticker: str, reason: str) -> bool:
        return await self.send_message(
            "\n".join(
                [
                    "🚨 *Crypto Trading Disabled*",
                    "",
                    f"Asset: *{asset}*",
                    f"Market: `{market_ticker}`",
                    f"Reason: `{reason}`",
                    "Trading is now disabled until operator intervention.",
                    f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}",
                ]
            )
        )

    async def _get_updates(self) -> list[dict[str, Any]]:
        session = await self._ensure_session()
        try:
            async with session.get(
                f"{self.base_url}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": POLL_INTERVAL},
            ) as response:
                if response.status == 200:
                    payload = await response.json()
                    return payload.get("result", [])
        except Exception:
            return []
        return []

    def _supabase_headers(self) -> dict[str, str]:
        return {
            "apikey": self.supabase_service_role_key,
            "Authorization": f"Bearer {self.supabase_service_role_key}",
            "Content-Type": "application/json",
        }

    async def _supabase_select(self, table: str, *, params: dict[str, str]) -> list[dict[str, Any]]:
        if not self.supabase_url or not self.supabase_service_role_key:
            return []
        session = await self._ensure_session()
        try:
            async with session.get(
                f"{self.supabase_url}/rest/v1/{table}",
                params=params,
                headers=self._supabase_headers(),
            ) as response:
                if response.status >= 300:
                    return []
                payload = await response.json()
                return payload if isinstance(payload, list) else []
        except Exception:
            return []

    def _load_private_key(self):
        if self._private_key is not None:
            return self._private_key
        if not self.kalshi_private_key_path:
            raise ValueError("KALSHI_PRIVATE_KEY_PATH is missing.")
        self._private_key = load_rsa_private_key(self.kalshi_private_key_path)
        return self._private_key

    def _kalshi_headers(self, method: str, path: str) -> dict[str, str]:
        if not self.kalshi_api_key_id:
            raise ValueError("KALSHI_API_KEY_ID is missing.")
        timestamp_ms = str(int(time.time() * 1000))
        message = f"{timestamp_ms}{method.upper()}{path.split('?')[0]}"
        signature = sign_kalshi_message(
            private_key=self._load_private_key(),
            message=message.encode("utf-8"),
        )
        return {
            "Content-Type": "application/json",
            "KALSHI-ACCESS-KEY": self.kalshi_api_key_id,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(signature).decode("utf-8"),
            "KALSHI-ACCESS-TIMESTAMP": timestamp_ms,
        }

    async def _kalshi_get(self, endpoint: str, *, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        session = await self._ensure_session()
        path = f"/trade-api/v2{endpoint}"
        try:
            async with session.get(
                f"{self.kalshi_base_url}{endpoint}",
                params=params,
                headers=self._kalshi_headers("GET", path),
            ) as response:
                if response.status >= 300:
                    return None
                return await response.json()
        except Exception:
            return None

    async def _get_crypto_status(self) -> str:
        user_settings = await self._supabase_select(
            "user_settings",
            params={"select": "auto_trade_enabled,crypto_auto_trade_enabled,crypto_trading_disabled_reason,crypto_trading_disabled_at,updated_at", "limit": "1"},
        )
        latest_runtime = await self._supabase_select(
            "agent_logs",
            params={
                "select": "timestamp,message,log_level",
                "module": "eq.orchestrator.crypto_runtime",
                "order": "timestamp.desc",
                "limit": "1",
            },
        )
        latest_signal = await self._supabase_select(
            "crypto_signal_events",
            params={
                "select": "created_at,status,resolved_ticker,skip_reason",
                "order": "created_at.desc",
                "limit": "1",
            },
        )
        latest_trade = await self._supabase_select(
            "trades",
            params={
                "select": "timestamp,market_ticker,status,contract_side",
                "engine": "eq.crypto_kalshi",
                "order": "timestamp.desc",
                "limit": "1",
            },
        )

        controls = user_settings[0] if user_settings else {}
        runtime = latest_runtime[0] if latest_runtime else {}
        signal = latest_signal[0] if latest_signal else {}
        trade = latest_trade[0] if latest_trade else {}
        return "\n".join(
            [
                "🛰️ *Crypto Status*",
                "",
                f"Auto Trade: *{bool(controls.get('auto_trade_enabled', False))}*",
                f"Crypto Enabled: *{bool(controls.get('crypto_auto_trade_enabled', False))}*",
                f"Disable Reason: `{controls.get('crypto_trading_disabled_reason') or 'none'}`",
                f"WS Status: `{runtime.get('message') or 'no runtime log yet'}`",
                f"Last Signal: `{signal.get('created_at') or 'n/a'}`",
                f"Last Trade: `{trade.get('timestamp') or 'n/a'}`",
            ]
        )

    async def _get_balance_text(self) -> str:
        payload = await self._kalshi_get("/portfolio/balance")
        if not payload:
            return "⚠️ Balance unavailable."
        balance_cents = float(payload.get("balance", 0))
        portfolio_value_cents = float(payload.get("portfolio_value", 0))
        return (
            "💵 *Kalshi Demo Balance*\n\n"
            f"Balance: *${balance_cents / 100:.2f}*\n"
            f"Portfolio Value: *${portfolio_value_cents / 100:.2f}*"
        )

    async def _get_positions_text(self) -> str:
        payload = await self._kalshi_get("/portfolio/positions", params={"limit": 10})
        if not payload:
            return "⚠️ Positions unavailable."
        positions = payload.get("market_positions", payload.get("positions", [])) or []
        if not positions:
            return "📭 *Open Positions*\n\nNo open crypto positions."
        lines = ["📭 *Open Positions*", ""]
        for position in positions[:5]:
            lines.append(
                f"• `{position.get('ticker', 'n/a')}` | qty={position.get('position', 0)} | value={position.get('market_exposure_dollars', position.get('market_exposure', 0))}"
            )
        return "\n".join(lines)

    async def _get_trades_text(self) -> str:
        rows = await self._supabase_select(
            "trades",
            params={
                "select": "timestamp,symbol,market_ticker,contract_side,execution_price,status,error_code",
                "engine": "eq.crypto_kalshi",
                "order": "timestamp.desc",
                "limit": "5",
            },
        )
        if not rows:
            return "🧾 *Recent Crypto Trades*\n\nNo crypto trade records yet."
        lines = ["🧾 *Recent Crypto Trades*", ""]
        for row in rows:
            lines.append(
                f"• `{row.get('market_ticker') or row.get('symbol')}` | {row.get('contract_side') or '?'} | {row.get('status')} | ${float(row.get('execution_price') or 0):.4f}"
            )
        return "\n".join(lines)

    async def _get_crypto_scan_text(self) -> str:
        rows = await self._supabase_select(
            "crypto_signal_events",
            params={
                "select": "created_at,asset,resolved_ticker,desired_side,status,skip_reason,edge,model_probability_yes",
                "order": "created_at.desc",
                "limit": "5",
            },
        )
        if not rows:
            return "🔎 *Crypto Scan*\n\nNo qualifying crypto signals recorded yet."
        lines = ["🔎 *Crypto Scan*", ""]
        for row in rows:
            lines.append(
                f"• `{row.get('resolved_ticker') or row.get('asset') or 'unresolved'}` | {row.get('desired_side') or '?'} | {row.get('status')} | {row.get('skip_reason') or 'live'} | edge={float(row.get('edge') or 0):+.3f} | P(YES)={float(row.get('model_probability_yes') or 0):.3f}"
            )
        return "\n".join(lines)

    async def _handle_command(self, command: str, from_chat_id: str) -> None:
        resolved_chat_id = await self._get_chat_id()
        if from_chat_id != resolved_chat_id:
            return

        cmd = command.strip().lower().split()[0]
        if cmd == "/help":
            await self.send_message(
                "\n".join(
                    [
                        "🤖 *Crypto Operator Commands*",
                        "",
                        "/crypto_status *(or /cryptostatus)*",
                        "/balance",
                        "/positions",
                        "/trades",
                        "/crypto_scan *(or /cryptoscan; signals + near misses)*",
                        "/help",
                    ]
                )
            )
        elif cmd in {"/crypto_status", "/cryptostatus"}:
            await self.send_message(await self._get_crypto_status())
        elif cmd == "/balance":
            await self.send_message(await self._get_balance_text())
        elif cmd == "/positions":
            await self.send_message(await self._get_positions_text())
        elif cmd == "/trades":
            await self.send_message(await self._get_trades_text())
        elif cmd in {"/crypto_scan", "/cryptoscan", "/scan"}:
            await self.send_message(await self._get_crypto_scan_text())
        else:
            await self.send_message(f"❓ Unknown command: `{cmd}`\nSend */help* for the list.")

    async def run_polling(self) -> None:
        while True:
            updates = await self._get_updates()
            for update in updates:
                self._last_update_id = max(self._last_update_id, update.get("update_id", 0))
                message = update.get("message", {})
                text = message.get("text", "")
                from_chat = str(message.get("chat", {}).get("id", ""))
                if text.startswith("/"):
                    try:
                        await self._handle_command(text, from_chat)
                    except Exception:
                        with contextlib.suppress(Exception):
                            await self.send_message("⚠️ Command failed. Try again in a few seconds.")
            await asyncio.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    async def _main() -> None:
        notifier = TelegramNotifier()
        await notifier.start()
        await notifier.send_message("✅ Async Telegram operator plane online.")
        await notifier.close()

    asyncio.run(_main())
