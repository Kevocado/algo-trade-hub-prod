from market_sentiment_tool.backend import orchestrator


def test_sniper_models_are_tried_before_legacy_model_dir():
    for candidates, asset in ((orchestrator.BTC_MODEL_CANDIDATES, "btc"), (orchestrator.ETH_MODEL_CANDIDATES, "eth")):
        sniper = candidates.index(f"models/{asset}_sniper.pkl")
        legacy = [i for i, c in enumerate(candidates) if c.startswith("model/")]
        assert all(sniper < i for i in legacy)


def test_incompatible_lgbm_model_files_are_not_candidates():
    for candidates in (orchestrator.BTC_MODEL_CANDIDATES, orchestrator.ETH_MODEL_CANDIDATES):
        assert not any("lgbm_model_" in c for c in candidates)


def test_production_vps_path_stays_first():
    assert orchestrator.BTC_MODEL_CANDIDATES[0] == "/root/kalshibot/btc_model.pkl"
    assert orchestrator.ETH_MODEL_CANDIDATES[0] == "/root/kalshibot/eth_model.pkl"
