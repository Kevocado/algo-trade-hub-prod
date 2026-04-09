import importlib.util
import math
import os
from pathlib import Path
from types import SimpleNamespace

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "SP500 Predictor" / "scripts" / "audit_feature_parity.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_feature_parity", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class _FakeQuery:
    def __init__(self, data):
        self._data = data

    def select(self, *_args, **_kwargs):
        return self

    def eq(self, *_args, **_kwargs):
        return self

    def gte(self, *_args, **_kwargs):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeQuery(self._data)


def test_compute_drift_table_ranks_and_flags_features():
    module = _load_audit_module()
    live_frame = pd.DataFrame(
        {
            "Close": [105.0, 106.0],
            "Volume": [500.0, 520.0],
            "force_idx": [50.0, 55.0],
        }
    )
    train_frame = pd.DataFrame(
        {
            "Close": [100.0, 101.0, 102.0],
            "Volume": [100.0, 101.0, 99.0],
            "force_idx": [10.0, 11.0, 9.0],
        }
    )

    drift_table = module.compute_drift_table(live_frame, train_frame)

    assert list(drift_table["feature"][:2]) == ["Volume", "force_idx"]
    volume_row = drift_table.loc[drift_table["feature"] == "Volume"].iloc[0]
    assert volume_row["drift_score"] > module.RED_FLAG_THRESHOLD


def test_compute_drift_table_handles_zero_train_std():
    module = _load_audit_module()
    live_frame = pd.DataFrame({"Volume": [5.0, 5.0], "Close": [1.0, 1.0]})
    train_frame = pd.DataFrame({"Volume": [2.0, 2.0], "Close": [1.0, 1.0]})

    drift_table = module.compute_drift_table(live_frame, train_frame)

    volume_row = drift_table.loc[drift_table["feature"] == "Volume"].iloc[0]
    close_row = drift_table.loc[drift_table["feature"] == "Close"].iloc[0]
    assert math.isinf(volume_row["drift_score"])
    assert close_row["drift_score"] == 0.0


def test_fetch_live_audit_snapshots_extracts_feature_vectors():
    module = _load_audit_module()
    rows = [
        {
            "timestamp": "2026-04-09T00:00:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "BTC",
                "feature_vector": {"Close": 100.0, "Volume": 250.0},
            },
        },
        {
            "timestamp": "2026-04-09T01:00:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "ETH",
                "feature_vector": {"Close": 200.0, "Volume": 350.0},
            },
        },
    ]

    frames = module.fetch_live_audit_snapshots(_FakeSupabase(rows), hours=1)

    assert frames["BTC"].iloc[0]["Close"] == 100.0
    assert frames["ETH"].iloc[0]["Volume"] == 350.0


def test_fetch_live_audit_snapshots_filters_to_latest_process_epoch():
    module = _load_audit_module()
    rows = [
        {
            "timestamp": "2026-04-09T00:10:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "ETH",
                "evaluation_count": 240,
                "timestamp_utc": "2026-04-09T00:10:00+00:00",
                "feature_vector": {"Close": 2000.0, "Volume": 900000000.0},
            },
        },
        {
            "timestamp": "2026-04-09T00:20:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "ETH",
                "evaluation_count": 260,
                "timestamp_utc": "2026-04-09T00:20:00+00:00",
                "feature_vector": {"Close": 2010.0, "Volume": 910000000.0},
            },
        },
        {
            "timestamp": "2026-04-09T00:50:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "ETH",
                "evaluation_count": 20,
                "timestamp_utc": "2026-04-09T00:50:00+00:00",
                "feature_vector": {"Close": 2170.0, "Volume": 45000000.0},
            },
        },
        {
            "timestamp": "2026-04-09T00:55:00+00:00",
            "reasoning_context": {
                "audit_kind": "feature_distribution_snapshot",
                "asset": "ETH",
                "evaluation_count": 40,
                "timestamp_utc": "2026-04-09T00:55:00+00:00",
                "feature_vector": {"Close": 2175.0, "Volume": 50000000.0},
            },
        },
    ]

    frames = module.fetch_live_audit_snapshots(_FakeSupabase(rows), hours=1)

    assert list(frames["ETH"]["Close"]) == [2170.0, 2175.0]
    assert list(frames["ETH"]["Volume"]) == [45000000.0, 50000000.0]


def test_default_audit_windows():
    module = _load_audit_module()

    assert module.DEFAULT_LIVE_HOURS == 1
    assert module.DEFAULT_TRAIN_HOURS == 24


def test_fetch_training_feature_frame_passes_asset_to_build_features_in_raw_mode(monkeypatch):
    module = _load_audit_module()
    captured = {}
    fake_index = pd.date_range("2026-04-08T00:00:00Z", periods=230, freq="h")
    fake_bars = pd.DataFrame(
        {
            "Open": [100.0] * len(fake_index),
            "High": [101.0] * len(fake_index),
            "Low": [99.0] * len(fake_index),
            "Close": [100.5] * len(fake_index),
            "Volume": [250.0] * len(fake_index),
        },
        index=fake_index,
    )

    monkeypatch.setattr(module.yf, "download", lambda *args, **kwargs: fake_bars)

    def fake_build_features(frame, *, asset=None, is_live_inference=False, include_target=False):
        captured["asset"] = asset
        captured["is_live_inference"] = is_live_inference
        return pd.DataFrame(
            [{name: 1.0 for name in module.CANONICAL_CRYPTO_FEATURES}],
            index=[fake_index[-1]],
        )

    monkeypatch.setattr(module, "build_features", fake_build_features)

    frame = module.fetch_training_feature_frame("ETH", train_hours=24, warmup_hours=24)

    assert not frame.empty
    assert captured["asset"] == "ETH"
    assert captured["is_live_inference"] is False


def test_compute_drift_table_stays_finite_with_variable_training_distribution():
    module = _load_audit_module()
    live_frame = pd.DataFrame({"Volume": [110.0, 120.0], "force_idx": [9.0, 12.0]})
    train_frame = pd.DataFrame({"Volume": [90.0, 100.0, 110.0, 120.0], "force_idx": [4.0, 6.0, 8.0, 10.0]})

    drift_table = module.compute_drift_table(live_frame, train_frame)

    volume_row = drift_table.loc[drift_table["feature"] == "Volume"].iloc[0]
    force_idx_row = drift_table.loc[drift_table["feature"] == "force_idx"].iloc[0]
    assert math.isfinite(volume_row["drift_score"])
    assert math.isfinite(force_idx_row["drift_score"])
