import pandas as pd
import pytest

from market_sentiment_tool.backend import orchestrator


def test_callable_model_receives_feature_frame_and_is_clamped():
    frame = pd.DataFrame([{"f1": 1.0, "f2": 2.0}])
    seen = {}

    def model(x):
        seen["x"] = x
        return 1.7

    assert orchestrator._model_yes_probability(model, frame) == pytest.approx(1.0)
    assert seen["x"] is frame


def test_callable_model_in_range_passes_through():
    frame = pd.DataFrame([{"f1": 1.0}])
    assert orchestrator._model_yes_probability(lambda x: 0.42, frame) == pytest.approx(0.42)
