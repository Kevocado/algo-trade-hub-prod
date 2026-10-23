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
    # Weather engine retirement (2026-10-16)
    "tradehub/engines/weather_engine.py",
    "tradehub/engines/weather_maker.py",
    "tradehub/scripts/weather_auto_sell.py",
]


def test_the_cleaned_up_python_files_stay_deleted():
    assert [p for p in DELETED if (ROOT / p).exists()] == []


def test_the_weather_scan_branch_is_gone():
    """The three-city weather scan branch was deleted along with its engines."""
    scan_py = (ROOT / "tradehub/scripts/scan.py").read_text(encoding="utf-8")
    # The functions and branch should not exist
    assert "def _scan_weather_city" not in scan_py
    assert "def scan_weather" not in scan_py
    assert 'if name == "weather"' not in scan_py
    # The weather data and engine imports should be gone
    assert "from tradehub.data.weather import" not in scan_py
    assert "from tradehub.engines.weather import" not in scan_py
    # The summary should not have a weather key
    assert '"weather":' not in scan_py
    # The allowlist should not include weather
    assert '"weather"' not in scan_py or '"weather",' not in scan_py

    # The market_alerts hook should be gone
    alerts_py = (ROOT / "tradehub/scripts/market_alerts.py").read_text(encoding="utf-8")
    assert "weather_auto_sell" not in alerts_py
    assert "Weather Auto-Sell" not in alerts_py


def test_the_cache_backed_endpoints_are_gone():
    from tradehub.api.main import app

    paths = {route.path for route in app.routes}
    assert "/api/opportunities" not in paths and "/api/nws_weather" not in paths
