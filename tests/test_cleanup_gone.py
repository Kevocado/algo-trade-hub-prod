from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DELETED = [
    "shared/api_server.py",
    "shared/background_scanner.py",
    "shared/fast_scanner.py",
    "shared/weather_features.py",
    "tradehub/core/ai_validator.py",
    "tradehub/core/microstructure_engine.py",
    "tradehub/core/news_analyzer.py",
    "tradehub/core/predictit_engine.py",
]


def test_the_cleaned_up_python_files_stay_deleted():
    assert [p for p in DELETED if (ROOT / p).exists()] == []


def test_the_cache_backed_endpoints_are_gone():
    from tradehub.api.main import app

    paths = {route.path for route in app.routes}
    assert "/api/opportunities" not in paths and "/api/nws_weather" not in paths
