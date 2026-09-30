"""L2 logistic regression by Newton's method (numpy only), and JSON artifacts checked against a manifest.

No pickles: an artifact is a JSON file of numbers, and `ArtifactStore.load` refuses any artifact whose
SHA-256 is not the one the manifest recorded when it was written (spec §7: "the loader refuses any
artifact whose hash is not in the manifest").
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

import numpy as np

from tradehub.models.spy_direction.features import FEATURES

L2 = 1.0
NEWTON_STEPS = 25
MIN_TRAIN = 500
MODEL_DIR_ENV = "TRADEHUB_MODEL_DIR"
DEFAULT_MODEL_DIR = Path.home() / ".cache" / "tradehub" / "models"


@dataclass(frozen=True)
class Artifact:
    features: tuple[str, ...]
    center: tuple[float, ...]
    scale: tuple[float, ...]
    intercept: float
    coef: tuple[float, ...]
    train_start: str
    train_end: str
    n_train: int

    def predict(self, row: dict[str, float]) -> float:
        z = [(row[f] - c) / s for f, c, s in zip(self.features, self.center, self.scale)]
        return float(1.0 / (1.0 + np.exp(-(self.intercept + float(np.dot(self.coef, z))))))

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=1)


def fit(x: list[list[float]], y: list[int], days: list[date], l2: float = L2, *,
        features: tuple[str, ...] = FEATURES, min_train: int = MIN_TRAIN) -> Artifact:
    if len(y) < min_train:
        raise ValueError(f"need >= {min_train} training rows, got {len(y)}")
    xa, ya = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    center, scale = xa.mean(axis=0), xa.std(axis=0)
    scale[scale == 0] = 1.0
    z = np.hstack([np.ones((len(ya), 1)), (xa - center) / scale])
    w = np.zeros(z.shape[1])
    penalty = np.diag([0.0] + [l2] * (z.shape[1] - 1))  # the intercept is not shrunk
    for _ in range(NEWTON_STEPS):
        p = 1.0 / (1.0 + np.exp(-z @ w))
        grad = z.T @ (p - ya) + penalty @ w
        hess = (z.T * (p * (1.0 - p))) @ z + penalty
        w -= np.linalg.solve(hess, grad)
    return Artifact(features, tuple(center.tolist()), tuple(scale.tolist()), float(w[0]), tuple(w[1:].tolist()),
                    min(days).isoformat(), max(days).isoformat(), len(ya))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    """`<root>/spy_direction/<name>.json` plus `manifest.json` = {name: sha256}."""

    def __init__(self, root: Path | None = None, namespace: str = "spy_direction"):
        base = root or Path(os.environ.get(MODEL_DIR_ENV) or DEFAULT_MODEL_DIR)
        self.dir = base / namespace

    def _manifest(self) -> dict[str, str]:
        path = self.dir / "manifest.json"
        return json.loads(path.read_text("utf-8")) if path.is_file() else {}

    def save(self, name: str, artifact: Artifact) -> str:
        self.dir.mkdir(parents=True, exist_ok=True)
        text = artifact.to_json()
        (self.dir / f"{name}.json").write_text(text, "utf-8")
        manifest = self._manifest() | {name: sha256(text)}
        (self.dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=1), "utf-8")
        return manifest[name]

    def load(self, name: str) -> tuple[Artifact, str] | None:
        path = self.dir / f"{name}.json"
        if not path.is_file():
            return None
        text = path.read_text("utf-8")
        digest = sha256(text)
        if self._manifest().get(name) != digest:
            raise ValueError(f"refusing artifact {name}: its sha256 is not the one in the manifest")
        raw = json.loads(text)
        return Artifact(**{k: tuple(v) if isinstance(v, list) else v for k, v in raw.items()}), digest
