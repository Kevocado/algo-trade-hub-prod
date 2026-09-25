import pytest

from tradehub.engine_config import CONFIG_PATH, EngineConfig, load_engine_config


def test_repo_config_has_weather_and_gas():
    weather = load_engine_config("weather")
    gas = load_engine_config("gas")
    assert weather.min_edge_pct > 0 and gas.min_edge_pct > 0
    assert weather.prefer_maker is True
    assert weather.params["error_sigma"] > 0
    assert CONFIG_PATH.name == "engines.yaml"


def test_unknown_engine_raises(tmp_path):
    path = tmp_path / "engines.yaml"
    path.write_text("weather:\n  min_edge_pct: 5\n")
    with pytest.raises(KeyError):
        load_engine_config("gas", path)


def test_extra_keys_go_to_params(tmp_path):
    path = tmp_path / "engines.yaml"
    path.write_text("gas:\n  min_edge_pct: 3\n  prefer_maker: false\n  foo: 1.5\n")
    assert load_engine_config("gas", path) == EngineConfig(min_edge_pct=3.0, prefer_maker=False, params={"foo": 1.5})
