# Walk-Forward S&P 500 Quant (Wave 1, Plan e) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the pickle-downloading quant with an in-repo, walk-forward, monthly-refit logistic model of next-session S&P 500 direction, journaled beside the sentiment meter.

**Architecture:** `tradehub/models/spy_direction/` holds the training code: price-only features from closes strictly before the session, an L2 logistic regression by Newton's method (numpy), and JSON artifacts whose SHA-256 must match a manifest before they load. `SpyQuant` fits the month's artifact once (on sessions before the 1st of the month), reuses it all month, and shares the meter's target, `SpxCloses` and settlement.

**Tech Stack:** Python 3.12, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-tradehub-v2-prediction-journal-design.md` (§7 Walk-forward quant). **Depends on:** plans (a) and (d) merged (uses `tradehub/journal/spx.py`).

> **Provenance:** every code block below was implemented and run by the reviewer on top of plan (a) in a scratch worktree before this plan was written (full backend suite 1383 passed with `time.monotonic` forced to 5.0 and to 1e7; frontend vitest 462 passed, tsc, eslint and build clean; new Python files ruff-clean). Copy the code as written; if `main` has moved and something disagrees, fix it and say so in the PR.

## Global Constraints

- Everything in plan (a)'s Global Constraints (`docs/superpowers/plans/2026-09-29-journal-pipeline.md`) applies: freeze by trigger, gaps never backfilled, per-target gate minimums (daily 200, monthly/meeting 50), BSS vs market else climatology, timezone-aware timestamps, isolation per forecaster, tests green at both monotonic clocks.
- A forecaster is a class implementing `tradehub.journal.contract.Forecaster`; its `(name, version)` is its journal key and must be unique in `tradehub/journal/registry.py`.
- Constructing a forecaster must not touch the network; network happens only inside `targets` / `forecast` / `settle`.
- `forecast()` returns `None` when an input is missing (a recorded gap), never a guess or a default.
- **Never trained on the scored period:** the artifact for month M is trained only on sessions before M's first day and is used only for sessions in M.
- **No pickles, no remote downloads:** artifacts are JSON numbers under `TRADEHUB_MODEL_DIR` (default `~/.cache/tradehub/models`), and the loader refuses any artifact whose hash is not in `manifest.json`.
- Features are price-only (FRED SP500 has no volume and breadth is unavailable, see plan (d)); that is narrower than the spec allows, never wider.
- The legacy `tradehub/engines/quant_engine.py` (HF pickle download) is **not** touched here: it is still imported by `tradehub/scripts/background_scanner.py`. Retiring it is a separate follow-up PR once `spy_quant` has a journal record.
- The VPS container needs a persistent volume for `TRADEHUB_MODEL_DIR`, or the month's artifact is re-fit (deterministically, same hash) after each redeploy; either is correct, the volume just avoids the recompute.

---
### Task 1: Hashed walk-forward model, the quant forecaster, and its registration

**Files:**
- Create: `tradehub/models/__init__.py` (empty), `tradehub/models/spy_direction/__init__.py`, `tradehub/models/spy_direction/features.py`, `tradehub/models/spy_direction/model.py`, `tradehub/journal/forecasters/spy_quant.py`
- Modify: `tradehub/journal/registry.py` (replace the whole file; assumes (b)–(d) merged, else add only the `SpyQuant` import and entry)
- Test: `tests/test_journal_spy_quant.py`

**Interfaces:**
- Consumes: plan (d) `tradehub.journal.spx`.
- Produces: `FEATURES`, `MIN_HISTORY=201`, `feature_row(history)`, `features_for(closes, day) -> (row, newest_close_date) | None`, `training_set(closes, before) -> (x, y, days)`; `Artifact` (frozen; `.predict(row)`, `.to_json()`), `fit(x, y, days, l2=1.0)` (needs >= 500 rows), `sha256(text)`, `ArtifactStore(root=None)` with `.save(name, artifact) -> sha` and `.load(name) -> (Artifact, sha) | None` (raises `ValueError` on a hash mismatch); `SpyQuant(closes, store=None)` (name `spy_quant`, version `spy-wf-v1`, cadence `daily`), `artifact_name(day) -> 'spy-dir-YYYY-MM'`.

- [ ] **Step 1: Write the failing test** (`tests/test_journal_spy_quant.py`)

```python
import random
from datetime import UTC, date, datetime, timedelta

import pytest

from tradehub.journal.contract import CalendarEntry
from tradehub.journal.forecasters.spy_quant import SpyQuant
from tradehub.journal.nyse import is_session
from tradehub.journal.spx import SpxCloses, freeze_at, spx_target
from tradehub.models.spy_direction.features import features_for
from tradehub.models.spy_direction.model import ArtifactStore


def _trend_closes(n=900, seed=3):
    rng = random.Random(seed)
    level, out, day = 4000.0, {}, date(2023, 1, 3)
    while len(out) < n:
        if is_session(day):
            level *= 1.0 + rng.gauss(0.0004, 0.01)
            out[day] = level
        day += timedelta(days=1)
    return out


def test_features_use_only_closes_before_the_session():
    closes = _trend_closes()
    day = max(closes)
    row, newest = features_for(closes, day)
    assert newest < day
    bumped = dict(closes) | {day: closes[day] * 2}  # the session's own close must not move anything
    assert features_for(bumped, day)[0] == row


def test_monthly_artifact_is_trained_before_the_month_and_hash_checked(tmp_path):
    closes = _trend_closes()
    last = max(closes)
    now = datetime.combine(last, datetime.min.time(), UTC) + timedelta(hours=11)
    store = ArtifactStore(tmp_path)
    fc = SpyQuant(SpxCloses(fetch=lambda s, start: {d: v for d, v in closes.items() if d < last}), store)
    artifact, digest = fc.model_for(last, now)
    assert artifact.train_end < last.replace(day=1).isoformat()  # never trained on the scored month
    assert fc.model_for(last, now)[1] == digest  # the month's artifact is written once, then reused
    path = store.dir / f"spy-dir-{last:%Y-%m}.json"
    path.write_text(path.read_text().replace('"n_train"', '"n_train" ', 1))
    with pytest.raises(ValueError, match="manifest"):
        store.load(f"spy-dir-{last:%Y-%m}")


def test_quant_forecast_records_its_artifact(tmp_path):
    closes = _trend_closes()
    last = max(closes)
    fc = SpyQuant(SpxCloses(fetch=lambda s, start: {d: v for d, v in closes.items() if d < last}),
                  ArtifactStore(tmp_path))
    now = freeze_at(last) - timedelta(hours=1)
    forecast = fc.forecast(CalendarEntry(spx_target(last), "spx", "daily", freeze_at(last)), now)
    assert 0.0 < forecast.probability < 1.0
    assert len(forecast.payload["artifact_sha256"]) == 64 and forecast.payload["n_train"] >= 500


def test_the_registry_runs_the_quant_on_the_meters_closes():
    from tradehub.journal.registry import FORECASTERS

    by_key = {(f.name, f.version): f for f in FORECASTERS}
    quant, meter = by_key[("spy_quant", "spy-wf-v1")], by_key[("sentiment_meter", "meter-v1")]
    assert quant._closes is meter._closes  # one FRED fetch per run serves both, and one settlement truth
```

- [ ] **Step 2: Run it to verify it fails**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_spy_quant.py -v`
Expected: FAIL — `No module named 'tradehub.journal.forecasters.spy_quant'`.

- [ ] **Step 3: Implement**

`tradehub/models/spy_direction/__init__.py`:

```python
"""Walk-forward S&P 500 next-session direction model (v2 spec §7). Training lives here, in-repo."""
```

`tradehub/models/spy_direction/features.py`:

```python
"""Price-derived features only (spec §7), computed from closes strictly before the target session.

FRED SP500 carries no volume and no breadth series is freely reachable (see the sentiment meter), so
v1 is price-only; that is a narrower feature set than the spec allows, never a wider one.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Mapping
from datetime import date

FEATURES = ("r1", "r5", "r20", "vol20", "ma50_gap", "ma200_gap")
MIN_HISTORY = 201  # closes needed before a session to compute every feature


def _ret(closes: list[float], k: int) -> float:
    return math.log(closes[-1] / closes[-1 - k])


def feature_row(history: list[float]) -> dict[str, float] | None:
    """Features from `history` (oldest first), all of which is known before the target session."""
    if len(history) < MIN_HISTORY:
        return None
    daily = [math.log(b / a) for a, b in zip(history[-21:-1], history[-20:])]
    return {
        "r1": _ret(history, 1),
        "r5": _ret(history, 5),
        "r20": _ret(history, 20),
        "vol20": statistics.pstdev(daily),
        "ma50_gap": history[-1] / statistics.fmean(history[-50:]) - 1.0,
        "ma200_gap": history[-1] / statistics.fmean(history[-200:]) - 1.0,
    }


def features_for(closes: Mapping[date, float], day: date) -> tuple[dict[str, float], date] | None:
    """(features, date of the newest close used) for session `day`, or None without enough history."""
    days = sorted(d for d in closes if d < day)
    row = feature_row([closes[d] for d in days])
    return (row, days[-1]) if row is not None else None


def training_set(closes: Mapping[date, float], before: date) -> tuple[list[list[float]], list[int], list[date]]:
    """Rows for every session t < `before`: features from closes before t, label = close(t) > close(t-1)."""
    days = sorted(d for d in closes if d < before)
    values = [closes[d] for d in days]
    x, y, used = [], [], []
    for i in range(MIN_HISTORY, len(days)):
        row = feature_row(values[:i])
        if row is None:
            continue
        x.append([row[f] for f in FEATURES])
        y.append(int(values[i] > values[i - 1]))
        used.append(days[i])
    return x, y, used
```

`tradehub/models/spy_direction/model.py`:

```python
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


def fit(x: list[list[float]], y: list[int], days: list[date], l2: float = L2) -> Artifact:
    if len(y) < MIN_TRAIN:
        raise ValueError(f"need >= {MIN_TRAIN} training sessions, got {len(y)}")
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
    return Artifact(FEATURES, tuple(center.tolist()), tuple(scale.tolist()), float(w[0]), tuple(w[1:].tolist()),
                    min(days).isoformat(), max(days).isoformat(), len(ya))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ArtifactStore:
    """`<root>/spy_direction/<name>.json` plus `manifest.json` = {name: sha256}."""

    def __init__(self, root: Path | None = None):
        base = root or Path(os.environ.get(MODEL_DIR_ENV) or DEFAULT_MODEL_DIR)
        self.dir = base / "spy_direction"

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
```

`tradehub/journal/forecasters/spy_quant.py`:

```python
"""Walk-forward quant (v2 spec §7): P(S&P 500 up on session t) from a monthly-refit logistic model.

The model used for any session in month M is trained only on sessions before the 1st of M, on an
expanding window, and is written once as a hashed artifact; later sessions in M load that same
artifact. Nothing is ever trained on a session it is then scored on.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from tradehub.journal.contract import CalendarEntry, Forecast, Settlement
from tradehub.journal.spx import SpxCloses, settle_spx, spx_entry, target_day
from tradehub.models.spy_direction.features import features_for, training_set
from tradehub.models.spy_direction.model import Artifact, ArtifactStore, fit

STALE_DAYS = 5  # newest close older than this before the session -> gap, not a guess


def artifact_name(day: date) -> str:
    return f"spy-dir-{day:%Y-%m}"


class SpyQuant:
    name = "spy_quant"
    version = "spy-wf-v1"
    cadence = "daily"

    def __init__(self, closes: SpxCloses, store: ArtifactStore | None = None):
        self._closes = closes
        self._store = store or ArtifactStore()

    def targets(self, now: datetime) -> list[CalendarEntry]:
        return spx_entry(now, self._closes, "spx")

    def model_for(self, day: date, now: datetime) -> tuple[Artifact, str]:
        name = artifact_name(day)
        found = self._store.load(name)
        if found is not None:
            return found
        month_start = day.replace(day=1)
        artifact = fit(*training_set(self._closes.get(now), before=month_start))
        return artifact, self._store.save(name, artifact)

    def forecast(self, entry: CalendarEntry, now: datetime) -> Forecast | None:
        day = target_day(entry.target)
        found = features_for(self._closes.get(now), day)
        if found is None or (day - found[1]) > timedelta(days=STALE_DAYS):
            return None
        row, newest = found
        artifact, digest = self.model_for(day, now)
        return Forecast(self.name, self.version, entry.target, artifact.predict(row),
                        payload={"features": row, "newest_close": newest.isoformat(), "artifact_sha256": digest,
                                 "train_start": artifact.train_start, "train_end": artifact.train_end,
                                 "n_train": artifact.n_train})

    def settle(self, target: str, now: datetime) -> Settlement | None:
        return settle_spx(target, now, self._closes)
```

`tradehub/journal/registry.py` (whole file):

```python
"""The forecasters the journal job runs. Plans (b)-(f) append theirs here, one line each.

Constructing a forecaster must not touch the network: clients are built here, used only when the
runner calls `targets`/`forecast`/`settle`.
"""

from __future__ import annotations

from tradehub.core.kalshi_feed import fetch_market
from tradehub.data.kalshi_live import KalshiLive
from tradehub.journal.contract import Forecaster
from tradehub.journal.forecasters.cpi import CpiForecaster
from tradehub.journal.forecasters.fomc import FOMC_SERIES, FomcMapped, is_hold_market
from tradehub.journal.forecasters.labor import LaborData, PayrollsForecaster, QuitsDirection, UnrateDirection
from tradehub.journal.forecasters.sentiment import SentimentMeter
from tradehub.journal.forecasters.spy_quant import SpyQuant
from tradehub.journal.kalshi_linked import KalshiImplied
from tradehub.journal.spx import SpxCloses

_LIVE = KalshiLive()
_LABOR = LaborData()
_SPX = SpxCloses()

FORECASTERS: list[Forecaster] = [
    # plan (b): CPI + FOMC, each beside its Kalshi pseudo-forecaster (spec §5, ruling Q5)
    CpiForecaster("KXCPI", _LIVE, fetch_market),
    CpiForecaster("KXCPICORE", _LIVE, fetch_market),
    KalshiImplied("cpi", ("KXCPI", "KXCPICORE"), "monthly", _LIVE, fetch_market),
    FomcMapped(_LIVE, fetch_market),
    KalshiImplied("fomc", (FOMC_SERIES,), "meeting", _LIVE, fetch_market, keep=is_hold_market),
    # plan (c): labor (spec §5); payrolls beside the market, the direction fits vs climatology
    PayrollsForecaster(_LIVE, fetch_market, _LABOR),
    KalshiImplied("labor", ("KXPAYROLLS",), "monthly", _LIVE, fetch_market),
    UnrateDirection(_LIVE, _LABOR),
    QuitsDirection(_LABOR),
    # plan (d): sentiment meter (spec §6)
    SentimentMeter(_SPX),
    # plan (e): walk-forward quant (spec §7); same target and settlement as the meter
    SpyQuant(_SPX),
]
```

- [ ] **Step 4: Run to verify it passes**

Run: `SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider tests/test_journal_*.py -v`
Expected: all pass; the tamper test proves the manifest check (one edited byte -> `ValueError`).

- [ ] **Step 5: Commit**

```bash
git add tradehub/models tradehub/journal/forecasters/spy_quant.py tradehub/journal/registry.py tests/test_journal_spy_quant.py
git commit -m "feat(journal): walk-forward S&P 500 quant with hashed monthly artifacts"
```

---
### Final task: verify and open the PR

- [ ] Full backend suite at both CI clocks:

```bash
mkdir -p /tmp/mono && for c in 5.0 1e7; do printf 'import time\ntime.monotonic=lambda: %s\n' $c > /tmp/mono/sitecustomize.py; PYTHONPATH=/tmp/mono SUPABASE_SERVICE_ROLE_KEY=x .venv/bin/python -m pytest -q -p no:cacheprovider; done
```
Expected: both runs all-pass.

- [ ] Ruff on the files this plan created: `.venv/bin/python -m ruff check <those files>` → `All checks passed!`
- [ ] Open one PR from a fresh branch off `main` (after plan (a) is merged). Body: what the forecaster(s) predict, their `(name, version)` keys, and "no migration needed".

## Self-Review

- **Spec §7:** in-repo training code, walk-forward expanding window, monthly refit, never trained on the scored period (asserted: `train_end < first day of the month`), versioned artifacts with SHA hashes plus a manifest, loader refusing unknown hashes (asserted by tampering), price-derived features only, same settlement and cadence as the meter.
- **Type consistency:** `fit(*training_set(...))` argument order matches `training_set`'s return; `SpxCloses` is the one shared instance (asserted by the registry test).
