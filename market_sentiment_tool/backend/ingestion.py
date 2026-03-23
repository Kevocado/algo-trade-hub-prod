"""
ingestion.py — Async Alpaca WebSocket Tick Ingestion
=====================================================
I/O-bound asynchronous process that maintains the Alpaca WebSocket stream.
Writes L2 tick data to a local SQLite WAL database. The orchestrator polls
this database at its own cadence, ensuring zero dropped packets.

Boot order: Step 3 (after LLM server and MCP server).
"""

import asyncio
import sqlite3
import os
import logging
from datetime import datetime, timezone

from dotenv import load_dotenv
from alpaca.data.live import StockDataStream

# ── Load .env from project root (one directory up from /backend) ──
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

ALPACA_API_KEY = os.getenv("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "local_ticks.sqlite3")

# ── Logging ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [INGESTION]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Watchlist — expand as needed ──
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "SPY", "QQQ", "GLD", "USO"]


# ═══════════════════════════════════════════════════════════════════
# SQLite WAL setup
# ═══════════════════════════════════════════════════════════════════

def setup_db() -> sqlite3.Connection:
    """Create the local ticks database with WAL journal mode for concurrency."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ticks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol      TEXT    NOT NULL,
            price       REAL    NOT NULL,
            size        INTEGER NOT NULL,
            timestamp   TEXT    NOT NULL,
            conditions  TEXT,
            tape        TEXT,
            ingested_at TEXT    DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts
        ON ticks (symbol, timestamp DESC)
    """)
    conn.commit()
    log.info("SQLite WAL database ready at %s", DB_PATH)
    return conn


# ═══════════════════════════════════════════════════════════════════
# Alpaca WebSocket handlers
# ═══════════════════════════════════════════════════════════════════

DB_CONN: sqlite3.Connection | None = None


async def handle_trade(data):
    """Callback fired on each trade tick from Alpaca."""
    global DB_CONN
    if DB_CONN is None:
        return

    try:
        DB_CONN.execute(
            "INSERT INTO ticks (symbol, price, size, timestamp, conditions, tape) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                data.symbol,
                float(data.price),
                int(data.size),
                data.timestamp.isoformat() if data.timestamp else datetime.now(timezone.utc).isoformat(),
                str(getattr(data, "conditions", None)),
                getattr(data, "tape", None),
            ),
        )
        DB_CONN.commit()
    except Exception as exc:
        log.error("Failed to insert tick for %s: %s", data.symbol, exc)


async def handle_quote(data):
    """Optional: handle L2 quote updates."""
    # Future: store bid/ask spread for order-flow analysis
    pass


# ═══════════════════════════════════════════════════════════════════
# Main boot
# ═══════════════════════════════════════════════════════════════════

def main():
    global DB_CONN
    DB_CONN = setup_db()

    if not ALPACA_API_KEY or not ALPACA_SECRET_KEY:
        log.error("ALPACA_API_KEY / ALPACA_SECRET_KEY not set in .env — cannot connect.")
        return

    from alpaca.data.live import StockDataStream
    stream = StockDataStream(ALPACA_API_KEY, ALPACA_SECRET_KEY)
    stream.subscribe_trades(handle_trade, *WATCHLIST)
    log.info("Subscribing to trades for: %s", ", ".join(WATCHLIST))

    # Start the live Alpaca stream.
    log.info("Alpaca WebSocket stream starting (Live Data)…")
    try:
        stream.run()
    except KeyboardInterrupt:
        log.info("Ingestion shutting down gracefully.")
    except Exception as exc:
        log.warning("Alpaca WebSocket failed (limit exceeded or network error): %s", exc)
    finally:
        if DB_CONN:
            DB_CONN.close()

if __name__ == "__main__":
    main()
