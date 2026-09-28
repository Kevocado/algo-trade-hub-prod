"""
FastAPI Dependencies — shared singletons injected via Depends().
Keeps the main app clean and makes testing easy (override dependencies in tests).
"""

import os
from functools import lru_cache

# No `load_dotenv()` at import time -- see `tradehub.core.env`. The API app
# calls `load_local_env()` in its lifespan, which runs when the server actually
# boots, so importing this module (as the test suite does) is side-effect free.


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
        key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "") or os.getenv("SUPABASE_KEY", "")
        if not url or not key:
            print("⚠️  SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY missing — Supabase calls will fail.")
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
