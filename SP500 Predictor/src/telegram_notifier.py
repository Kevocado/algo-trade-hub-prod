"""
Telegram Notifier — Two-Way Command Center

Outbound: Formatted alerts for all trading engines (weather, NBA, F1, crypto, etc.)
Inbound:  Command listener loop that handles slash commands from the user.

Supported commands:
  /status   — Portfolio summary + top opportunity
  /scan     — Trigger an immediate HybridScanner run
  /kill     — Send kill-switch alert (manual liquidation reminder)
  /nba      — Latest NBA prop signals
  /f1       — Latest F1 telemetry signals
  /weather  — Current NWS weather readings
  /help     — List all commands

Bot: t.me/KevsWeatherBot
"""

import os
import time
import threading
import requests
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip('"').strip("'")
CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip('"').strip("'")
BASE_URL  = f"https://api.telegram.org/bot{BOT_TOKEN}"

# Command polling interval (seconds)
POLL_INTERVAL = 5


class TelegramNotifier:
    """Two-way Telegram interface: sends alerts and listens for slash commands."""

    def __init__(self):
        self.bot_token = BOT_TOKEN
        self.chat_id   = CHAT_ID
        self._resolved_chat_id = None
        self._last_update_id   = 0   # Tracks processed update IDs to avoid replaying
        self._listener_thread  = None

    # ── Connectivity ─────────────────────────────────────────────────────────

    def is_enabled(self):
        return bool(self.bot_token and self.chat_id)

    def _get_chat_id(self):
        """Resolves numeric chat ID from TELEGRAM_CHAT_ID env var (or getUpdates)."""
        if self._resolved_chat_id:
            return self._resolved_chat_id
        if self.chat_id.lstrip("-").isdigit():
            self._resolved_chat_id = self.chat_id
            return self._resolved_chat_id
        try:
            r = requests.get(f"{BASE_URL}/getUpdates", timeout=5)
            if r.status_code == 200:
                for update in r.json().get("result", []):
                    chat_id = update.get("message", {}).get("chat", {}).get("id")
                    if chat_id:
                        self._resolved_chat_id = str(chat_id)
                        return self._resolved_chat_id
        except Exception as e:
            print(f"  ⚠️ Failed to resolve chat ID: {e}")
        self._resolved_chat_id = self.chat_id
        return self._resolved_chat_id

    # ── Outbound: Core send ───────────────────────────────────────────────────

    def send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """Send a raw text message to the configured chat."""
        if not self.is_enabled():
            print("  ⚠️ Telegram not configured")
            return False
        chat_id = self._get_chat_id()
        try:
            r = requests.post(
                f"{BASE_URL}/sendMessage",
                json={"chat_id": chat_id, "text": text, "parse_mode": parse_mode},
                timeout=10,
            )
            return r.status_code == 200
        except Exception as e:
            print(f"  ⚠️ Telegram send failed: {e}")
            return False

    # Alias used by weather_auto_sell.py and other scripts
    def send_alert(self, text: str) -> bool:
        return self.send_message(text)

    # ── Outbound: Formatted Alerts ───────────────────────────────────────────

    def alert_weather_edge(self, city: str, nws_temp: float, action: str, price: float, ticker: str):
        """Weather latency arbitrage alert."""
        text = (
            f"🌤️ *Weather Edge Alert*\n\n"
            f"NWS printed *{nws_temp}°F* for {city}\n"
            f"Suggested: *{action}* at ${price:.2f}\n"
            f"Ticker: `{ticker}`\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_weather_maker(self, city: str, strike: float, fair_value: float,
                             bid: float, ask: float, ticker: str, direction: str):
        """Weather market-maker limit order suggestion."""
        text = (
            f"🏦 *Weather Maker Signal*\n\n"
            f"📍 {city} | {direction.upper()} {strike}°F\n"
            f"💎 Fair Value: *{fair_value:.1f}¢*\n"
            f"📋 Suggested limit BUY at `{bid:.1f}¢` | limit SELL at `{ask:.1f}¢`\n"
            f"Ticker: `{ticker}`\n"
            f"➡️ Maker orders = zero Kalshi fees + rebate\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_nba_prop(self, player: str, stat: str, line: float,
                        model_prob: float, kalshi_price: float, edge: float,
                        action: str, injury_flag: bool = False):
        """NBA player prop signal."""
        injury_tag = "\n⚠️ *INJURY REPORT TRIGGERED — Stale line!*" if injury_flag else ""
        text = (
            f"🏀 *NBA Prop Signal*{injury_tag}\n\n"
            f"👤 {player} — {stat.title()} O/U {line}\n"
            f"🤖 Model P(Over): *{model_prob:.1f}%* | Kalshi: *{kalshi_price:.0f}¢*\n"
            f"📈 Edge: *+{edge:.1f}%* → {action}\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_f1_signal(self, driver: str, event: str, signal_type: str,
                         model_prob: float, kalshi_price: float, edge: float,
                         action: str, key_metric: str = ""):
        """F1 telemetry-derived Kalshi signal."""
        text = (
            f"🏎️ *F1 Telemetry Signal*\n\n"
            f"👤 {driver} | {event}\n"
            f"📊 Signal: *{signal_type.title()}*\n"
            f"🤖 Model Prob: *{model_prob:.1f}%* | Kalshi: *{kalshi_price:.0f}¢*\n"
            f"📈 Edge: *+{edge:.1f}%* → {action}\n"
            f"{'🔬 ' + key_metric if key_metric else ''}\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_kill_switch(self, reason: str, positions: list = None):
        """Kill switch condition alert."""
        pos_text = ""
        if positions:
            pos_text = "\n".join([f"  • `{p.get('ticker', '?')}`" for p in positions[:5]])
            pos_text = f"\n\nOpen Positions:\n{pos_text}"
        text = (
            f"🚨 *KILL SWITCH TRIGGERED*\n\n"
            f"Reason: {reason}\n"
            f"Action: *Liquidate all positions immediately*"
            f"{pos_text}"
        )
        return self.send_message(text)

    def alert_vix_emergency(self, vix_value: float):
        """VIX > 45 emergency liquidation warning."""
        text = (
            f"🔴 *VIX EMERGENCY*\n\n"
            f"VIX has spiked to *{vix_value:.1f}*\n"
            f"Action: *Liquidate all positions immediately*\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_gex_flip(self, ticker: str, gex_value: float, direction: str):
        """GEX flip alert."""
        emoji = "⚠️" if direction == "negative" else "🟢"
        text = (
            f"{emoji} *Gamma Flip: {ticker}*\n\n"
            f"GEX turned *{direction}* ({gex_value:+.2f})\n"
            f"{'Expect expanded range & increased volatility.' if direction == 'negative' else 'Dealer hedging should stabilize prices.'}\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_liquidity_cascade(self, ticker: str, amihud_ratio: float, sigma_above: float):
        """Amihud illiquidity spike alert."""
        text = (
            f"🚨 *Liquidity Cascade: {ticker}*\n\n"
            f"Amihud ratio: *{amihud_ratio:.6f}* ({sigma_above:.1f}σ above mean)\n"
            f"Action: *Reduce exposure immediately*\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_model_drift(self, brier_score: float, threshold: float):
        """Model accuracy drift warning."""
        text = (
            f"📉 *Model Drift Detected*\n\n"
            f"Brier Score: *{brier_score:.4f}* (threshold: {threshold:.4f})\n"
            f"Action: Consider retraining or adjusting parameters\n"
            f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
        )
        return self.send_message(text)

    def alert_scanner_results(self, opportunities: list, min_edge: float = 15.0):
        """Summary of high-edge opportunities from the scanner."""
        high_edge = [o for o in opportunities if float(o.get("edge", 0)) >= min_edge]
        if not high_edge:
            return False
        high_edge.sort(key=lambda x: float(x.get("edge", 0)), reverse=True)
        top = high_edge[:5]
        lines = [f"🤖 *Scanner: {len(high_edge)} opportunities >{min_edge}% edge*\n"]
        for opp in top:
            lines.append(
                f"• *{opp.get('engine', '?')}* | {opp.get('asset', '?')} | "
                f"{opp.get('action', '?')} | Edge: +{opp.get('edge', 0):.1f}%"
            )
        return self.send_message("\n".join(lines))

    def alert_crypto_signal(self, symbol: str, direction: str, confidence: float,
                             funding_z: float, ob_imbalance: float, aborted: bool = False):
        """Crypto microstructure signal (or AI-aborted signal)."""
        if aborted:
            text = (
                f"🤖 *Crypto Signal ABORTED by AI*\n\n"
                f"Symbol: `{symbol}` | {direction.upper()}\n"
                f"Gemini detected macro chaos — trade skipped.\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            )
        else:
            text = (
                f"💹 *Crypto Microstructure Signal*\n\n"
                f"Symbol: `{symbol}` | {direction.upper()}\n"
                f"Confidence: *{confidence:.1f}%*\n"
                f"Funding Rate Z-Score: *{funding_z:+.2f}σ*\n"
                f"Order Book Imbalance: *{ob_imbalance:+.2f}*\n"
                f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
            )
        return self.send_message(text)

    # ══════════════════════════════════════════════════════════════════════════
    # INBOUND: Two-Way Command Listener
    # ══════════════════════════════════════════════════════════════════════════

    def _get_updates(self) -> list:
        """Polls Telegram getUpdates for new messages since last_update_id."""
        try:
            r = requests.get(
                f"{BASE_URL}/getUpdates",
                params={"offset": self._last_update_id + 1, "timeout": POLL_INTERVAL},
                timeout=POLL_INTERVAL + 2,
            )
            if r.status_code == 200:
                return r.json().get("result", [])
        except Exception:
            pass
        return []

    def _handle_command(self, command: str, from_chat_id: str):
        """
        Dispatches incoming slash commands to the appropriate handler.
        Imports engines lazily to avoid circular imports.
        """
        cmd = command.strip().lower().split()[0]  # handle "/cmd@botname" format

        if cmd == "/help":
            self.send_message(
                "🤖 *Kalshi Edge Bot — Commands*\n\n"
                "/status — Portfolio + top opportunity\n"
                "/scan   — Trigger immediate scanner run\n"
                "/kill   — Issue kill-switch alert\n"
                "/nba    — Latest NBA prop signals\n"
                "/f1     — Latest F1 signals\n"
                "/weather — NWS weather readings\n"
                "/help   — This message"
            )

        elif cmd == "/status":
            try:
                from src.kalshi_portfolio import KalshiPortfolio, check_portfolio_available
                if check_portfolio_available():
                    kp = KalshiPortfolio()
                    summary = kp.get_portfolio_summary()
                    pos_count = len(summary.get("positions", []))
                    balance = summary.get("balance", 0)
                    self.send_message(
                        f"📊 *Portfolio Status*\n\n"
                        f"Open Positions: *{pos_count}*\n"
                        f"Balance: *${balance/100:.2f}*\n"
                        f"⏰ {datetime.now(timezone.utc).strftime('%H:%M UTC')}"
                    )
                else:
                    self.send_message("⚠️ Kalshi portfolio unavailable. Check API keys.")
            except Exception as e:
                self.send_message(f"⚠️ Status error: `{e}`")

        elif cmd == "/scan":
            self.send_message("🔄 Triggering scanner... (results in ~60s)")
            try:
                from src.market_scanner import HybridScanner
                scanner = HybridScanner()
                results = scanner.run_full_scan()
                all_opps = []
                for engine_results in results.values():
                    if isinstance(engine_results, list):
                        all_opps.extend(engine_results)
                self.alert_scanner_results(all_opps, min_edge=12.0)
            except Exception as e:
                self.send_message(f"⚠️ Scan failed: `{e}`")

        elif cmd == "/kill":
            self.alert_kill_switch(
                reason="Manual override via Telegram /kill command",
                positions=[]
            )

        elif cmd == "/nba":
            try:
                from scripts.engines.nba_engine import NBAEngine
                engine = NBAEngine()
                signals = engine.get_signals()
                if not signals:
                    self.send_message("🏀 No NBA signals above threshold right now.")
                else:
                    top = signals[:3]
                    lines = ["🏀 *Top NBA Prop Signals*\n"]
                    for s in top:
                        lines.append(
                            f"• {s['player']} — {s['stat']} O/U {s['line']} | "
                            f"Edge: +{s.get('edge_pct', 0):.1f}% | {s.get('action', '?')}"
                        )
                    self.send_message("\n".join(lines))
            except Exception as e:
                self.send_message(f"⚠️ NBA signal error: `{e}`")

        elif cmd == "/f1":
            try:
                from scripts.engines.f1_engine import F1Engine
                engine = F1Engine()
                signals = engine.get_latest_signals()
                if not signals:
                    self.send_message("🏎️ No F1 signals above threshold right now.")
                else:
                    top = signals[:3]
                    lines = ["🏎️ *Top F1 Signals*\n"]
                    for s in top:
                        lines.append(
                            f"• {s['driver']} | {s['event']} | "
                            f"Edge: +{s.get('edge_pct', 0):.1f}% | {s.get('action', '?')}"
                        )
                    self.send_message("\n".join(lines))
            except Exception as e:
                self.send_message(f"⚠️ F1 signal error: `{e}`")

        elif cmd == "/weather":
            try:
                from scripts.engines.weather_maker import WeatherMaker
                maker = WeatherMaker()
                readings = maker.get_all_nws_readings()
                if not readings:
                    self.send_message("🌤️ No NWS readings available.")
                else:
                    lines = ["🌡️ *Current NWS Readings*\n"]
                    for city, data in list(readings.items())[:5]:
                        obs = data.get("observed_high_f", "N/A")
                        fcst = data.get("forecast_high_f", "N/A")
                        lines.append(f"• {city}: Obs={obs}°F | Fcst={fcst}°F")
                    self.send_message("\n".join(lines))
            except Exception as e:
                self.send_message(f"⚠️ Weather error: `{e}`")

        else:
            self.send_message(f"❓ Unknown command: `{cmd}`\nSend */help* for the list.")

    def _listener_loop(self):
        """
        Background thread: polls getUpdates every POLL_INTERVAL seconds,
        processes any new slash commands, and updates _last_update_id.
        """
        print("📱 Telegram command listener started.")
        while True:
            try:
                updates = self._get_updates()
                for update in updates:
                    self._last_update_id = max(self._last_update_id, update.get("update_id", 0))
                    msg = update.get("message", {})
                    text = msg.get("text", "")
                    from_chat = str(msg.get("chat", {}).get("id", ""))

                    # Only accept commands from our configured chat
                    resolved = self._get_chat_id()
                    if text.startswith("/") and from_chat == resolved:
                        print(f"  💬 Received command: {text!r}")
                        self._handle_command(text, from_chat)

            except Exception as e:
                print(f"  ⚠️ Listener loop error: {e}")

            time.sleep(POLL_INTERVAL)

    def run_command_listener(self, daemon: bool = True):
        """
        Starts the command listener in a background thread.
        Set daemon=True so it auto-exits when the main process ends.
        Call this once at startup in background_scanner.py.
        """
        if not self.is_enabled():
            print("  ⚠️ Telegram not configured — command listener not started.")
            return
        if self._listener_thread and self._listener_thread.is_alive():
            print("  ⚠️ Listener already running.")
            return
        self._listener_thread = threading.Thread(
            target=self._listener_loop, daemon=daemon, name="TelegramListener"
        )
        self._listener_thread.start()
        print("  ✅ Telegram command listener running (background thread).")


# ── Dev / Test entrypoint ─────────────────────────────────────────────────────
if __name__ == "__main__":
    print("Testing Telegram Notifier...")
    notifier = TelegramNotifier()

    if not notifier.is_enabled():
        print("  ❌ Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID in .env")
        exit(1)

    result = notifier.send_message("✅ *Kalshi Edge Bot* — Two-way Telegram online!\nSend /help for commands.")
    print("  ✅ Message sent!" if result else "  ❌ Failed.")

    print("\n  Starting command listener (Ctrl+C to stop)...")
    notifier.run_command_listener(daemon=False)
