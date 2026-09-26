"""Per-sport settings: predictor URLs, Kalshi series, edge/candidate thresholds, LLM reviewer."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import yaml

from tradehub.engine_config import CONFIG_PATH, EngineConfig, load_engine_config

SERIES: dict[str, dict[str, str]] = {
    "nfl": {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"},
    "cfb": {"winner": "KXNCAAFGAME", "spread": "KXNCAAFSPREAD", "total": "KXNCAAFTOTAL"},
}
SERIES_TITLES: dict[str, str] = {
    "KXNFLGAME": "Professional Football Game",
    "KXNFLSPREAD": "Pro Football Spread",
    "KXNFLTOTAL": "Pro Football Total Points",
    "KXNCAAFGAME": "College Football Game",
    "KXNCAAFSPREAD": "College Football Spread",
    "KXNCAAFTOTAL": "College Football Total Points",
}


@dataclass(frozen=True)
class SportConfig:
    sport: str
    engine: str
    base_url: str
    site_url: str
    series: Mapping[str, str]
    series_titles: Mapping[str, str]
    edge: EngineConfig


@dataclass(frozen=True)
class ReviewerConfig:
    model: str
    daily_budget: int
    timeout_seconds: float
    price_bucket_cents: int


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_sport_config(sport: str, path: Path = CONFIG_PATH) -> SportConfig:
    sources = _yaml(path)["sports_sources"][sport]
    prefix = f"SPORTS_{sport.upper()}_"
    base_url = os.getenv(prefix + "BASE_URL") or sources["base_url"]
    site_url = os.getenv(prefix + "SITE_URL") or sources["site_url"]
    series = SERIES[sport]
    return SportConfig(
        sport=sport,
        engine=f"sports_{sport}",
        base_url=base_url.rstrip("/"),
        site_url=site_url.rstrip("/"),
        series=series,
        series_titles={s: SERIES_TITLES[s] for s in series.values()},
        edge=load_engine_config(f"sports_{sport}", path),
    )


def load_reviewer_config(path: Path = CONFIG_PATH) -> ReviewerConfig:
    raw = _yaml(path)["sports_reviewer"]
    return ReviewerConfig(
        model=str(raw["model"]),
        daily_budget=int(raw["daily_budget"]),
        timeout_seconds=float(raw["timeout_seconds"]),
        price_bucket_cents=int(raw["price_bucket_cents"]),
    )
