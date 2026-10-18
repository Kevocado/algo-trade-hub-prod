from tradehub.engine_config import load_engine_config
from tradehub.sports.config import load_reviewer_config, load_sport_config

# Production runs on the VPS stack: the sports feeds are the `nfl` and `cfb` services on the compose
# network, and the public site is one sslip hostname. These are the DEFAULTS in
# tradehub/config/engines.yaml; env overrides (SPORTS_NFL_BASE_URL etc.) are pinned by the next test.
VPS_NFL_BASE = "http://nfl:8001"
VPS_CFB_BASE = "http://cfb:8003"
VPS_SITE_URL = "https://sports.40-160-91-131.sslip.io"


def test_nfl_config_defaults_to_the_vps_predictor(monkeypatch):
    monkeypatch.delenv("SPORTS_NFL_BASE_URL", raising=False)
    monkeypatch.delenv("SPORTS_NFL_SITE_URL", raising=False)
    cfg = load_sport_config("nfl")
    assert cfg.engine == "sports_nfl"
    assert cfg.base_url == VPS_NFL_BASE
    assert cfg.site_url == VPS_SITE_URL
    assert cfg.series == {"winner": "KXNFLGAME", "spread": "KXNFLSPREAD", "total": "KXNFLTOTAL"}
    assert cfg.series_titles["KXNFLGAME"] == "Professional Football Game"
    assert cfg.edge.min_edge_pct > 0 and cfg.edge.params["calibration_max_dev"] == 0.10


def test_cfb_config_defaults_to_the_vps_predictor(monkeypatch):
    monkeypatch.delenv("SPORTS_CFB_BASE_URL", raising=False)
    monkeypatch.delenv("SPORTS_CFB_SITE_URL", raising=False)
    cfg = load_sport_config("cfb")
    assert cfg.base_url == VPS_CFB_BASE
    assert cfg.site_url == VPS_SITE_URL


def test_base_and_site_urls_can_be_moved_by_env(monkeypatch):
    monkeypatch.setenv("SPORTS_CFB_BASE_URL", "https://cfb.example.com/")
    monkeypatch.setenv("SPORTS_CFB_SITE_URL", "https://sports.example.com")
    cfg = load_sport_config("cfb")
    assert cfg.base_url == "https://cfb.example.com"
    assert cfg.site_url == "https://sports.example.com"
    assert cfg.series["winner"] == "KXNCAAFGAME"


def test_sports_engine_blocks_stay_numeric_for_load_engine_config():
    assert load_engine_config("sports_cfb").params["min_resting_size"] > 0


def test_reviewer_config():
    cfg = load_reviewer_config()
    assert cfg.model.endswith(":free")
    assert cfg.daily_budget == 40
    assert cfg.price_bucket_cents == 5
