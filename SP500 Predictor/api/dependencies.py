"""
FastAPI Dependencies — shared singletons injected via Depends().
Keeps the main app clean and makes testing easy (override dependencies in tests).
"""

import os
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv

root_dir = Path(__file__).parent.parent
load_dotenv(dotenv_path=root_dir / '.env', override=True)


# ─── Supabase client ─────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def get_supabase():
    """
    Returns a cached Supabase client.
    Uses the same SUPABASE_URL / SUPABASE_KEY from .env as the rest of the app.
    lru_cache ensures we create only one connection pool for the lifetime of the server.
    """
    try:
        from supabase import create_client
        url = os.getenv("SUPABASE_URL", "")
        key = os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            print("⚠️  SUPABASE_URL or SUPABASE_KEY missing — Supabase calls will fail.")
            return None
        return create_client(url, key)
    except ImportError:
        print("⚠️  supabase package not installed — Supabase calls will fail.")
        return None
    except Exception as e:
        print(f"⚠️  Supabase init error: {e}")
        return None


# ─── In-memory scanner results cache ─────────────────────────────────────────
# The background_scanner writes into this dict; the API reads from it.
# This avoids hammering Supabase on every API request.
_scanner_cache: dict = {
    "opportunities": [],
    "nba_signals": [],
    "f1_signals": [],
    "nws_readings": {},
    "last_updated": None,
}


def get_scanner_cache() -> dict:
    """Returns the live in-memory scanner result store."""
    return _scanner_cache


def update_scanner_cache(key: str, value) -> None:
    """Thread-safe update of the scanner cache. Called by background_scanner."""
    from datetime import datetime, timezone
    _scanner_cache[key] = value
    _scanner_cache["last_updated"] = datetime.now(timezone.utc)
