"""
config.py — Canonical configuration loader for Algo-Trade-Hub
=============================================================
Single source of truth for all environment variables. Every sub-system
(market_sentiment_tool, SP500 Predictor, FPL_Optimizer, shared scanners)
imports from here. No sub-system keeps its own .env or load_dotenv call.

Usage (with PYTHONPATH=. set in Procfile):
    from shared.config import SUPABASE_URL, ALPACA_API_KEY, ...
"""

import os
from pathlib import Path
from dotenv import load_dotenv


def _find_root_env() -> Path:
    """Walk up from the config.py file location until a .env is found."""
    current = Path(__file__).resolve().parent  # shared/
    for _ in range(5):
        candidate = current / ".env"
        if candidate.exists():
            return candidate
        current = current.parent
    raise FileNotFoundError(
        "Root .env not found. Expected at algo-trade-hub-prod/.env"
    )


# Load once on first import; override=False so OS vars take precedence
_env_path = _find_root_env()
load_dotenv(_env_path, override=False)


# ── Helpers ──────────────────────────────────────────────────────────────────

def require(key: str) -> str:
    """Return the env var or raise immediately with a clear error."""
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(
            f"Required env var '{key}' is missing or empty in {_env_path}"
        )
    return val


def get(key: str, default: str = "") -> str:
    """Return the env var or a safe default."""
    return os.getenv(key, default)


# ── Supabase ─────────────────────────────────────────────────────────────────
SUPABASE_URL              = require("SUPABASE_URL")
SUPABASE_SERVICE_ROLE_KEY = require("SUPABASE_SERVICE_ROLE_KEY")
VITE_SUPABASE_URL         = get("VITE_SUPABASE_URL")
VITE_SUPABASE_PUBLISHABLE_KEY = get("VITE_SUPABASE_PUBLISHABLE_KEY")
VITE_SUPABASE_PROJECT_ID  = get("VITE_SUPABASE_PROJECT_ID")

# ── Alpaca Paper Trading ──────────────────────────────────────────────────────
ALPACA_API_KEY    = require("ALPACA_API_KEY")
ALPACA_SECRET_KEY = require("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

# ── Kalshi ────────────────────────────────────────────────────────────────────
# Defaults to DEMO — switch to https://api.kalshi.co after 30-day paper protocol
KALSHI_API_BASE      = get("KALSHI_API_BASE", "https://demo-api.kalshi.co")
KALSHI_API_KEY_ID    = get("KALSHI_API_KEY_ID")
KALSHI_PRIVATE_KEY_PATH = get("KALSHI_PRIVATE_KEY_PATH", "./SP500 Predictor/kalshi_private_key.pem")

# ── LLM Engine (OpenRouter / DeepSeek cloud pivot) ───────────────────────────
LOCAL_LLM_ENDPOINT   = get("LOCAL_LLM_ENDPOINT", "https://openrouter.ai/api/v1/chat/completions")
LOCAL_LLM_MODEL_NAME = get("LOCAL_LLM_MODEL_NAME", "deepseek/deepseek-chat")
OPENROUTER_API_KEY   = get("OPENROUTER_API_KEY")

# ── Data APIs ────────────────────────────────────────────────────────────────
FRED_API_KEY   = get("FRED_API_KEY")
TIINGO_API_KEY = get("TIINGO_API_KEY")
GEMINI_API_KEY = get("GEMINI_API_KEY")
FOOTBALL_DATA_API_KEY = get("FOOTBALL_DATA_API_KEY")

# ── Azure Blob (FPL Optimizer files) ────────────────────────────────────────
AZURE_CONNECTION_STRING = get("AZURE_CONNECTION_STRING")

# ── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = get("TELEGRAM_CHAT_ID")
