"""Every /api route is registered before the SPA catch-all, so the app shell never shadows an endpoint."""
import importlib.util
import os
import sys

from tradehub.api import main as api_main


def _routes_with_a_spa_mounted(tmp_path):
    """`api_main.app` as registered when the SPA is present, from a private module instance.

    Not `importlib.reload`: other test modules bind `app` at import time and would be left holding the old
    object. Loading the file under a private name gives a fresh app and a fresh `mount_frontend` call and
    leaves the real module alone. Driven from a temp dist, so it runs whether or not `dist` was ever built.
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>spa</title>")
    previous = os.environ.get("FRONTEND_DIST")
    os.environ["FRONTEND_DIST"] = str(tmp_path)
    spec = importlib.util.spec_from_file_location("_spa_order_probe", api_main.__file__)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("FRONTEND_DIST", None)
        else:
            os.environ["FRONTEND_DIST"] = previous
        sys.modules.pop(spec.name, None)
    return [getattr(route, "path", None) for route in module.app.routes]


def test_every_api_route_is_registered_before_the_spa_catch_all(tmp_path):
    paths = _routes_with_a_spa_mounted(tmp_path)
    api_routes = [p for p in paths if isinstance(p, str) and p.startswith("/api/")]
    assert api_routes, "the probe found no /api/ routes, so it proves nothing"
    assert "" in paths, "the probe did not mount a SPA, so it proves nothing about the order"
    shadowed = [p for p in api_routes if paths.index(p) > paths.index("")]
    assert not shadowed, f"registered after the SPA catch-all and would be shadowed: {shadowed}"


def test_the_cpi_display_endpoint_is_gone(tmp_path):
    assert "/api/cpi-display" not in _routes_with_a_spa_mounted(tmp_path)
    assert "/api/journal" in _routes_with_a_spa_mounted(tmp_path)