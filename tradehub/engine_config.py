"""Per-engine edge configuration loaded from tradehub/config/engines.yaml."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

import yaml

CONFIG_PATH = Path(__file__).resolve().parent / "config" / "engines.yaml"


@dataclass(frozen=True)
class EngineConfig:
    min_edge_pct: float
    prefer_maker: bool = True
    params: Mapping[str, float] = field(default_factory=dict)


def load_engine_config(engine: str, path: Path = CONFIG_PATH) -> EngineConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = dict(data[engine])
    min_edge = float(raw.pop("min_edge_pct"))
    prefer_maker = bool(raw.pop("prefer_maker", True))
    return EngineConfig(min_edge_pct=min_edge, prefer_maker=prefer_maker, params={k: float(v) for k, v in raw.items()})
