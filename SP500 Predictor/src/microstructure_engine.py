import requests
import json
import os
import asyncio
import time
import threading
import numpy as np
from collections import deque
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from pathlib import Path

# Load .env
root_dir = Path(__file__).parent.parent.parent
load_dotenv(dotenv_path=root_dir / '.env', override=True)


class MicrostructureEngine:
    """
    Kalshi + Binance Microstructure Engine

    Phase 1 (Original): Kalshi order-book skew analysis — detects institutional whales.
    Phase 4 (Extended): Binance WebSocket features for crypto directional signals:
      - Rolling 7-day funding rate z-score
      - Order book imbalance (top-N bid vs ask volume)
      - Liquidation burst count per 5-min window
      - AI Scrutinizer (Gemini) filters out macro-chaos trades
    """

    def __init__(self):
        # Kalshi
        self.base_url = "https://api.elections.kalshi.com/trade-api/v2"
        self.api_key  = os.getenv("KALSHI_API_KEY")

        # Binance Futures REST base
        self.binance_futures_base = "https://fapi.binance.com"

        # In-memory rolling data stores (thread-safe deques)
        self._agg_trades:  dict[str, deque] = {}  # symbol → last 1000 aggTrades
        self._order_books: dict[str, dict]  = {}  # symbol → latest depth snapshot
        self._liquidations: dict[str, deque] = {}  # symbol → last 200 liquidation events
        self._ws_thread = None
        self._ws_running = False

    # ══════════════════════════════════════════════════════════════════════════
    # PART 1: Kalshi Order-Book Analysis (Original)
    # ══════════════════════════════════════════════════════════════════════════

    def fetch_order_book(self, ticker: str) -> dict:
        """Fetches the full order book depth for a Kalshi market."""
        url = f"{self.base_url}/markets/{ticker}/orderbook"
        try:
            r = requests.get(url, timeout=10)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {}

    def analyze_skew(self, ticker: str) -> dict:
        """
        Calculates buy/sell imbalance (skew) of the Kalshi order book.
        - Positive skew: more demand for YES (bullish).
        - Negative skew: more demand for NO (bearish).
        """
        book = self.fetch_order_book(ticker)
        if not book or not book.get('orderbook'):
            return {"skew": 0, "whale_detected": False, "signal": "Neutral"}

        ob = book['orderbook']
        yes_orders = ob.get('yes') or []
        no_orders  = ob.get('no')  or []

        yes_depth = sum(int(o[0]) * int(o[1]) for o in yes_orders)
        no_depth  = sum(int(o[0]) * int(o[1]) for o in no_orders)

        total_depth = yes_depth + no_depth
        if total_depth == 0:
            return {"skew": 0, "whale_detected": False, "signal": "Neutral"}

        skew = (yes_depth - no_depth) / total_depth

        yes_whale = any(int(o[1]) > 1000 for o in yes_orders)
        no_whale  = any(int(o[1]) > 1000 for o in no_orders)

        signal = "Neutral"
        if   skew >  0.3: signal = "Institutional Overweight: YES"
        elif skew < -0.3: signal = "Institutional Overweight: NO"

        return {
            "ticker":         ticker,
            "skew":           round(skew * 100, 1),
            "yes_depth":      yes_depth,
            "no_depth":       no_depth,
            "whale_detected": yes_whale or no_whale,
            "whale_side":     "YES" if yes_whale else ("NO" if no_whale else "None"),
            "signal":         signal,
        }

    # ══════════════════════════════════════════════════════════════════════════
    # PART 2: Binance Funding Rates (REST)
    # ══════════════════════════════════════════════════════════════════════════

    def get_funding_rate_history(self, symbol: str, days: int = 7) -> list:
        """
        Fetches the last N days of 8-hour funding rates for a perpetual futures contract.
        Returns list of {symbol, fundingTime, fundingRate}.
        """
        limit = days * 3  # 3 funding events per day
        try:
            r = requests.get(
                f"{self.binance_futures_base}/fapi/v1/fundingRate",
                params={"symbol": symbol, "limit": max(limit, 500)},
                timeout=10,
            )
            if r.status_code == 200:
                return r.json()
        except Exception as e:
            print(f"  ⚠️ Binance funding rate error for {symbol}: {e}")
        return []

    def compute_funding_zscore(self, symbol: str, window_days: int = 7) -> dict:
        """
        Computes the z-score of the current funding rate vs the trailing window.
        A large positive z-score = longs paying heavy funding = potential reversal short signal.
        """
        history = self.get_funding_rate_history(symbol, days=max(window_days * 2, 14))
        if not history:
            return {"symbol": symbol, "z_score": 0.0, "current_rate": 0.0, "mean": 0.0}

        rates = [float(h["fundingRate"]) for h in history]
        if len(rates) < window_days * 3:
            return {"symbol": symbol, "z_score": 0.0, "current_rate": rates[-1] if rates else 0.0}

        # Rolling window = last window_days * 3 readings
        window = rates[-(window_days * 3):]
        current = rates[-1]
        mu      = np.mean(window)
        sigma   = np.std(window)

        z_score = ((current - mu) / sigma) if sigma > 0 else 0.0

        return {
            "symbol":       symbol,
            "z_score":      round(z_score, 3),
            "current_rate": current,
            "mean":         round(mu, 6),
            "std":          round(sigma, 6),
            "window_days":  window_days,
            "signal":       self._funding_signal(z_score),
        }

    @staticmethod
    def _funding_signal(z_score: float) -> str:
        """Interprets z-score into a trading signal."""
        if   z_score >  2.0: return "EXTREME_LONG_CROWDING → potential short"
        elif z_score >  1.0: return "ELEVATED_LONGS → mild short bias"
        elif z_score < -2.0: return "EXTREME_SHORT_CROWDING → potential long"
        elif z_score < -1.0: return "ELEVATED_SHORTS → mild long bias"
        return "NEUTRAL"

    # ══════════════════════════════════════════════════════════════════════════
    # PART 3: Binance Order Book Snapshot (REST)
    # ══════════════════════════════════════════════════════════════════════════

    def get_order_book_snapshot(self, symbol: str, depth: int = 20) -> dict:
        """
        Fetches top-N Binance Futures order book levels and computes imbalance.
        Imbalance = (bid_volume - ask_volume) / (bid_volume + ask_volume)
        """
        try:
            r = requests.get(
                f"{self.binance_futures_base}/fapi/v1/depth",
                params={"symbol": symbol, "limit": depth},
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json()
                bids = data.get("bids", [])
                asks = data.get("asks", [])

                bid_vol = sum(float(b[1]) for b in bids[:10])
                ask_vol = sum(float(a[1]) for a in asks[:10])
                total   = bid_vol + ask_vol

                imbalance = (bid_vol - ask_vol) / total if total > 0 else 0.0
                return {
                    "symbol":    symbol,
                    "bid_vol":   round(bid_vol, 2),
                    "ask_vol":   round(ask_vol, 2),
                    "imbalance": round(imbalance, 4),
                    "signal":    "BUY_PRESSURE" if imbalance > 0.2 else
                                 "SELL_PRESSURE" if imbalance < -0.2 else "BALANCED",
                }
        except Exception as e:
            print(f"  ⚠️ Binance order book error for {symbol}: {e}")
        return {"symbol": symbol, "imbalance": 0.0, "signal": "UNKNOWN"}

    # ══════════════════════════════════════════════════════════════════════════
    # PART 4: Binance WebSocket Subscriber
    # ══════════════════════════════════════════════════════════════════════════

    def start_websocket_listener(self, symbols: list = None, daemon: bool = True):
        """
        Starts a background thread subscribing to Binance WebSocket streams:
          - @aggTrade  — rolling trade flow
          - @forceOrder — liquidation events
          - @depth5    — top-5 order book snapshot

        Data is stored in the _agg_trades / _liquidations / _order_books dicts.
        Call stop_websocket_listener() to shut down gracefully.
        """
        if symbols is None:
            symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

        if self._ws_running:
            print("  ⚠️ WebSocket listener already running.")
            return

        self._ws_running = True
        self._ws_thread = threading.Thread(
            target=self._ws_loop,
            args=(symbols,),
            daemon=daemon,
            name="BinanceWS",
        )
        self._ws_thread.start()
        print(f"  ✅ Binance WebSocket listener started for: {symbols}")

    def stop_websocket_listener(self):
        """Signals the WebSocket loop to stop."""
        self._ws_running = False
        print("  🛑 Binance WebSocket listener stopping...")

    def _ws_loop(self, symbols: list):
        """
        Core WebSocket event loop using the `websockets` library.
        Runs in a dedicated thread with its own asyncio event loop.
        """
        try:
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._ws_async(symbols))
        except Exception as e:
            print(f"  ⚠️ WebSocket loop error: {e}")

    async def _ws_async(self, symbols: list):
        """Async WebSocket subscription logic."""
        try:
            import websockets
        except ImportError:
            print("  ⚠️ websockets package not installed — run: pip install websockets")
            return

        # Compose combined stream URL
        streams = []
        for sym in symbols:
            s = sym.lower()
            streams += [f"{s}@aggTrade", f"{s}@forceOrder", f"{s}@depth5"]

        ws_url = f"wss://fstream.binance.com/stream?streams={'/'.join(streams)}"

        try:
            async with websockets.connect(ws_url) as ws:
                print(f"  🔌 Binance WS connected: {len(streams)} streams")
                while self._ws_running:
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=30)
                        msg = json.loads(raw)
                        data = msg.get("data", msg)
                        event_type = data.get("e", "")
                        symbol = data.get("s", "UNKNOWN")

                        if event_type == "aggTrade":
                            self._agg_trades.setdefault(symbol, deque(maxlen=1000))
                            self._agg_trades[symbol].append({
                                "price": float(data.get("p", 0)),
                                "qty":   float(data.get("q", 0)),
                                "buyer_maker": data.get("m", False),
                                "time": data.get("T", 0),
                            })

                        elif event_type == "forceOrder":
                            order = data.get("o", {})
                            self._liquidations.setdefault(symbol, deque(maxlen=200))
                            self._liquidations[symbol].append({
                                "side":  order.get("S", ""),
                                "qty":   float(order.get("q", 0)),
                                "price": float(order.get("p", 0)),
                                "time":  data.get("E", 0),
                            })

                        elif event_type == "depthUpdate":
                            self._order_books[symbol] = {
                                "bids": data.get("b", []),
                                "asks": data.get("a", []),
                                "last_update": data.get("E", 0),
                            }

                    except asyncio.TimeoutError:
                        continue
                    except Exception as e:
                        print(f"  ⚠️ WS message error: {e}")
                        break

        except Exception as e:
            print(f"  ⚠️ WS connection error: {e}")

    # ══════════════════════════════════════════════════════════════════════════
    # PART 5: Composite Signal + AI Scrutinizer
    # ══════════════════════════════════════════════════════════════════════════

    def get_crypto_signal(self, symbol: str, validate_with_ai: bool = True) -> dict:
        """
        Generates a composite crypto directional signal:
        1. Funding rate z-score
        2. Order book imbalance
        3. Liquidation burst in last 5 min
        4. AI Scrutinizer (Gemini) — aborts if macro chaos detected

        Returns a signal dict with direction, confidence, and AI verdict.
        """
        funding = self.compute_funding_zscore(symbol)
        ob      = self.get_order_book_snapshot(symbol)

        # Liquidation burst: count liquidations in last 5 minutes
        now_ms  = int(time.time() * 1000)
        five_min_ms = 5 * 60 * 1000
        recent_liqs = [
            l for l in list(self._liquidations.get(symbol, []))
            if (now_ms - l.get("time", 0)) < five_min_ms
        ]
        liq_burst = len(recent_liqs)

        # Score: positive = long bias, negative = short bias
        score = 0.0
        score += funding["z_score"] * -0.4   # High funding → short bias
        score += ob["imbalance"] * 0.3        # Bid pressure → long bias
        if liq_burst > 5:                     # Liq burst usually = forced sellers → bounce
            score += 0.3

        direction  = "LONG" if score > 0.1 else "SHORT" if score < -0.1 else "FLAT"
        confidence = round(min(abs(score) * 50 + 50, 90), 1)

        signal = {
            "symbol":       symbol,
            "direction":    direction,
            "confidence":   confidence,
            "funding_z":    funding["z_score"],
            "ob_imbalance": ob["imbalance"],
            "liq_burst":    liq_burst,
            "raw_score":    round(score, 3),
            "ai_cleared":   None,
            "ai_reason":    None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        if direction == "FLAT":
            return signal

        # AI Scrutinizer
        if validate_with_ai:
            try:
                from src.ai_validator import AIValidator
                validator = AIValidator()
                result = validator.validate_crypto_signal(symbol)
                signal["ai_cleared"] = result["proceed"]
                signal["ai_reason"]  = result["reason"]

                if not result["proceed"]:
                    signal["direction"]  = "ABORTED"
                    signal["confidence"] = 0.0
                    print(f"  🤖 AI aborted {symbol} signal: {result['reason'][:80]}")
            except Exception as e:
                print(f"  ⚠️ AI scrutinizer error: {e}")
                signal["ai_cleared"] = True  # Fail-open if AI unavailable

        return signal


if __name__ == "__main__":
    engine = MicrostructureEngine()

    print("Testing Kalshi skew analysis...")
    ticker = "KXHIGHNY-26MAR18-T45"
    print(json.dumps(engine.analyze_skew(ticker), indent=2))

    print("\nTesting Binance funding rate z-score...")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        funding = engine.compute_funding_zscore(sym)
        print(f"  {sym}: z={funding['z_score']:.2f}σ | {funding['signal']}")

    print("\nTesting order book imbalance...")
    for sym in ["BTCUSDT", "ETHUSDT"]:
        ob = engine.get_order_book_snapshot(sym)
        print(f"  {sym}: imbalance={ob['imbalance']:+.3f} | {ob['signal']}")

    print("\nGenerating composite crypto signal (no AI)...")
    sig = engine.get_crypto_signal("BTCUSDT", validate_with_ai=False)
    print(json.dumps(sig, indent=2))
