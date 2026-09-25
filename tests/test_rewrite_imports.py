import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rewrite_imports", REPO / "tools" / "rewrite_imports.py")
rewrite_imports = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rewrite_imports)


def test_rewrites_all_import_forms():
    src = (
        "from src.kalshi_feed import get_real_kalshi_markets\n"
        "from src import telegram_notifier\n"
        "import src.utils as u\n"
        "from scripts.engines.weather_engine import WeatherEngine\n"
        "from scripts.engines import quant_engine\n"
        "from scripts import shadow_performance\n"
        "from scripts.market_alerts import run_all_alerts\n"
        "from api.schemas import Foo\n"
        "from SP500_Predictor.src.kalshi_portfolio import KalshiPortfolio\n"
        "    from scripts.engines.quant_engine import fetch_live_btc_alpaca\n"
    )
    assert rewrite_imports.rewrite_source(src) == (
        "from tradehub.core.kalshi_feed import get_real_kalshi_markets\n"
        "from tradehub.core import telegram_notifier\n"
        "import tradehub.core.utils as u\n"
        "from tradehub.engines.weather_engine import WeatherEngine\n"
        "from tradehub.engines import quant_engine\n"
        "from tradehub.scripts import shadow_performance\n"
        "from tradehub.scripts.market_alerts import run_all_alerts\n"
        "from tradehub.api.schemas import Foo\n"
        "from tradehub.core.kalshi_portfolio import KalshiPortfolio\n"
        "    from tradehub.engines.quant_engine import fetch_live_btc_alpaca\n"
    )


def test_rewrites_patch_targets_and_uvicorn_string_but_not_hostnames():
    src = (
        '@patch("src.microstructure_engine.requests.get")\n'
        "@patch('scripts.engines.weather_maker.foo')\n"
        '@patch("scripts.shadow_performance.bar")\n'
        'uvicorn.run("api.main:app")\n'
        'host = "api.elections.kalshi.com"\n'
    )
    assert rewrite_imports.rewrite_source(src) == (
        '@patch("tradehub.core.microstructure_engine.requests.get")\n'
        "@patch('tradehub.engines.weather_maker.foo')\n"
        '@patch("tradehub.scripts.shadow_performance.bar")\n'
        'uvicorn.run("tradehub.api.main:app")\n'
        'host = "api.elections.kalshi.com"\n'
    )


def test_does_not_touch_lookalike_names():
    src = "from srcfoo import x\nfrom scriptsx import y\nfrom apikit import z\n"
    assert rewrite_imports.rewrite_source(src) == src


def test_strips_sys_path_idioms_and_unused_sys_import():
    src = (
        "import os\n"
        "import sys\n"
        "REPO_ROOT = 1\n"
        "if str(REPO_ROOT) not in sys.path:\n"
        "    sys.path.insert(0, str(REPO_ROOT))\n"
        "for path in (REPO_ROOT, PREDICTOR_ROOT):\n"
        "    text = str(path)\n"
        "    if text not in sys.path:\n"
        "        sys.path.insert(0, text)\n"
        "sys.path.append(os.path.join(os.path.dirname(__file__), '..'))\n"
        "x = 1\n"
    )
    assert rewrite_imports.strip_sys_path_hacks(src) == "import os\nREPO_ROOT = 1\nx = 1\n"


def test_keeps_sys_import_when_still_used():
    src = "import sys\nsys.path.insert(0, 'x')\nsys.exit(0)\n"
    assert rewrite_imports.strip_sys_path_hacks(src) == "import sys\nsys.exit(0)\n"


def test_keeps_sys_import_when_used_as_bare_name():
    src = "import sys\nsys.path.insert(0, 'x')\nmonkeypatch.setattr(sys, 'argv', [])\n"
    assert rewrite_imports.strip_sys_path_hacks(src) == "import sys\nmonkeypatch.setattr(sys, 'argv', [])\n"
