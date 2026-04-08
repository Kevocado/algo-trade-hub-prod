from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

from dotenv import dotenv_values, load_dotenv


_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=")


class RuntimeBootstrapError(RuntimeError):
    pass


@dataclass(frozen=True)
class EnvBootstrap:
    env_path: Path | None
    source_label: str
    parsed_values: dict[str, str] = field(default_factory=dict)
    syntax_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class KalshiRuntimeSettings:
    mode: str
    api_base: str
    ws_url: str
    errors: list[str] = field(default_factory=list)


def repo_root_for(module_file: str) -> Path:
    return Path(module_file).resolve().parents[2]


def service_root_for(module_file: str) -> Path:
    return Path(module_file).resolve().parents[1]


def env_candidates_for(module_file: str) -> list[tuple[str, Path]]:
    repo_root = repo_root_for(module_file)
    service_root = service_root_for(module_file)
    return [
        ("repo_root", repo_root / ".env"),
        ("service_local", service_root / ".env"),
    ]


def _validate_env_syntax(path: Path) -> list[str]:
    errors: list[str] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if not _ENV_LINE_RE.match(raw_line):
                errors.append(f"{path}:{line_no}: invalid dotenv syntax")
    return errors


def load_canonical_env(module_file: str) -> EnvBootstrap:
    for source_label, candidate in env_candidates_for(module_file):
        if not candidate.is_file():
            continue
        syntax_errors = _validate_env_syntax(candidate)
        if syntax_errors:
            return EnvBootstrap(
                env_path=candidate,
                source_label=source_label,
                parsed_values={},
                syntax_errors=syntax_errors,
            )

        load_dotenv(candidate, override=True)
        parsed = {
            key: str(value)
            for key, value in (dotenv_values(candidate) or {}).items()
            if key and value is not None
        }
        for key, value in parsed.items():
            if not os.getenv(key):
                os.environ[key] = value
        return EnvBootstrap(
            env_path=candidate,
            source_label=source_label,
            parsed_values=parsed,
            syntax_errors=[],
        )

    return EnvBootstrap(env_path=None, source_label="missing", parsed_values={}, syntax_errors=[])


def _clean_url(raw: str | None) -> str:
    return (raw or "").strip().strip('"').strip("'").rstrip("/")


def _url_host(raw: str) -> str:
    return (urlparse(raw).hostname or "").lower()


def _normalize_api_base(raw: str) -> str:
    raw = _clean_url(raw)
    if not raw:
        return raw
    marker = "/trade-api/v2"
    if raw.endswith(marker):
        return raw
    return f"{raw}{marker}"


def _normalize_ws_url(raw: str) -> str:
    raw = _clean_url(raw)
    if not raw:
        return raw
    marker = "/trade-api/ws/v2"
    if raw.endswith(marker):
        return raw
    return f"{raw}{marker}"


def _kalshi_defaults(mode: str) -> tuple[str, str]:
    if mode == "live":
        base = "https://api.elections.kalshi.com/trade-api/v2"
        ws = "wss://api.elections.kalshi.com/trade-api/ws/v2"
        return base, ws
    base = "https://demo-api.kalshi.co/trade-api/v2"
    ws = "wss://demo-api.kalshi.co/trade-api/ws/v2"
    return base, ws


def _allowed_hosts(mode: str) -> tuple[set[str], set[str]]:
    if mode == "live":
        host = "api.elections.kalshi.com"
        return ({host}, {host})
    host = "demo-api.kalshi.co"
    return ({host}, {host})


def infer_kalshi_mode(environ: dict[str, str] | None = None) -> str:
    env = environ or os.environ
    explicit = (env.get("KALSHI_ENV") or "").strip().lower()
    if explicit in {"demo", "live"}:
        return explicit

    candidates = [
        env.get("KALSHI_WS_URL", ""),
        env.get("KALSHI_API_BASE", ""),
        env.get("KALSHI_DEMO_API_BASE", ""),
    ]
    for raw in candidates:
        host = _url_host(raw)
        if host == "api.elections.kalshi.com":
            return "live"
        if host == "demo-api.kalshi.co":
            return "demo"
    return "demo"


def resolve_kalshi_runtime_settings(environ: dict[str, str] | None = None) -> KalshiRuntimeSettings:
    env = environ or os.environ
    mode = infer_kalshi_mode(env)
    default_api_base, default_ws_url = _kalshi_defaults(mode)
    allowed_api_hosts, allowed_ws_hosts = _allowed_hosts(mode)
    errors: list[str] = []

    api_candidates: list[tuple[str, str]] = []
    if mode == "live":
        api_candidates.append(("KALSHI_API_BASE", _normalize_api_base(env.get("KALSHI_API_BASE"))))
    else:
        api_candidates.append(("KALSHI_DEMO_API_BASE", _normalize_api_base(env.get("KALSHI_DEMO_API_BASE"))))
        api_candidates.append(("KALSHI_API_BASE", _normalize_api_base(env.get("KALSHI_API_BASE"))))

    ws_candidates: list[tuple[str, str]] = [
        ("KALSHI_WS_URL", _normalize_ws_url(env.get("KALSHI_WS_URL"))),
    ]

    resolved_api_base = default_api_base
    for key, value in api_candidates:
        if not value:
            continue
        host = _url_host(value)
        if host not in allowed_api_hosts:
            errors.append(
                f"{key} points to unsupported Kalshi host '{host or value}' for mode={mode}. "
                f"Allowed host(s): {', '.join(sorted(allowed_api_hosts))}."
            )
    for key, value in api_candidates:
        if not value:
            continue
        host = _url_host(value)
        if host not in allowed_api_hosts:
            continue
        resolved_api_base = value
        break

    resolved_ws_url = default_ws_url
    for key, value in ws_candidates:
        if not value:
            continue
        host = _url_host(value)
        if host not in allowed_ws_hosts:
            errors.append(
                f"{key} points to unsupported Kalshi WS host '{host or value}' for mode={mode}. "
                f"Allowed host(s): {', '.join(sorted(allowed_ws_hosts))}."
            )
            continue
        resolved_ws_url = value
        break

    return KalshiRuntimeSettings(
        mode=mode,
        api_base=resolved_api_base,
        ws_url=resolved_ws_url,
        errors=errors,
    )


def validate_runtime_env(
    *,
    env_bootstrap: EnvBootstrap,
    kalshi: KalshiRuntimeSettings,
    require_supabase: bool = True,
    require_kalshi: bool = True,
) -> list[str]:
    errors = list(env_bootstrap.syntax_errors)

    if env_bootstrap.env_path is None:
        errors.append("No .env file found. Expected repo root .env or market_sentiment_tool/.env fallback.")
        return errors

    if require_supabase:
        for key in ("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
            if not os.getenv(key, "").strip():
                errors.append(f"Missing required env var: {key} (loaded from {env_bootstrap.env_path})")

    if require_kalshi:
        for key in ("KALSHI_API_KEY_ID", "KALSHI_PRIVATE_KEY_PATH"):
            if not os.getenv(key, "").strip():
                errors.append(f"Missing required env var: {key} (loaded from {env_bootstrap.env_path})")
        errors.extend(kalshi.errors)

        private_key_path = os.getenv("KALSHI_PRIVATE_KEY_PATH", "").strip()
        if private_key_path:
            try:
                from shared.kalshi_ws import load_rsa_private_key

                load_rsa_private_key(private_key_path)
            except Exception as exc:
                errors.append(f"KALSHI_PRIVATE_KEY_PATH is invalid: {exc}")

    return errors


def critical_var_presence(keys: Iterable[str], parsed_values: dict[str, str]) -> dict[str, bool]:
    presence: dict[str, bool] = {}
    for key in keys:
        presence[key] = bool(os.getenv(key, "").strip()) or bool(parsed_values.get(key, "").strip())
    return presence
