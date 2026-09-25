"""Structural guarantees of the cleaned-up repo. Each cleanup task adds assertions here."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def tracked(*pathspecs: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "--", *pathspecs], cwd=REPO, check=True, capture_output=True, text=True
    ).stdout
    return [line for line in out.splitlines() if line]


def tracked_python_text() -> dict[str, str]:
    files = [f for f in tracked("*.py") if not f.startswith(("archive/", "research/"))]
    return {f: (REPO / f).read_text(encoding="utf-8", errors="replace") for f in files if (REPO / f).is_file()}


SPORTS_MODULES = ("nba_engine", "f1_engine", "ncaa_engine", "football_engine", "dixon_coles")


def test_no_sports_engine_files_tracked():
    offenders = [f for f in tracked("*.py") if Path(f).stem in SPORTS_MODULES]
    assert offenders == []


def test_no_code_references_sports_engines():
    pattern = re.compile(r"\b(" + "|".join(SPORTS_MODULES) + r")\b|NBAEngine|F1Engine|NCAAEngine|FootballKalshiEngine")
    offenders = [f for f, text in tracked_python_text().items() if pattern.search(text) and f != "tests/test_repo_layout.py"]
    assert offenders == []


def _top_level_names(path: str) -> set[str]:
    tree = ast.parse((REPO / path).read_text(encoding="utf-8"))
    return {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}


EQUITIES_DEFS = {
    "update_portfolio_state", "check_kill_switch", "poll_latest_ticks", "aggregate_market_snapshot",
    "AgentState", "quantitative_analysis", "_call_local_llm", "macro_sentiment", "cio_supervisor",
    "execute_trade", "build_graph", "heartbeat_loop",
}
CRYPTO_DEFS = {
    "run_crypto_services", "crypto_worker_loop", "build_crypto_graph", "evaluate_crypto_edge",
    "market_resolution", "write_trade_to_supabase", "log_to_supabase", "check_crypto_trade_switch",
    "initialize_runtime_clients",
}


def test_orchestrator_has_no_equities_swarm_but_keeps_crypto_path():
    names = _top_level_names("market_sentiment_tool/backend/orchestrator.py")
    assert names & EQUITIES_DEFS == set()
    assert CRYPTO_DEFS <= names


def test_mcp_server_has_no_alpaca_tools_but_keeps_kalshi():
    path = "market_sentiment_tool/backend/mcp_server.py"
    names = _top_level_names(path)
    assert names & {"get_portfolio", "get_market_data", "execute_paper_trade", "close_position"} == set()
    assert {"execute_kalshi_order", "submit_kalshi_order", "assert_kill_switch", "assert_crypto_trading_enabled"} <= names
    assert "alpaca" not in (REPO / path).read_text(encoding="utf-8").lower()


def test_equities_only_backend_files_removed():
    gone = [
        "market_sentiment_tool/backend/quant_engine.py",
        "market_sentiment_tool/backend/ingestion.py",
        "market_sentiment_tool/backend/news_rag.py",
        "market_sentiment_tool/backend/requirements.rag.txt",
        "market_sentiment_tool/backend/supabase_hard_reset.sql",
    ]
    assert tracked(*gone) == []


def test_research_is_parked_and_not_imported():
    assert tracked("quant_research_lab") == []
    assert tracked("Weather") == []
    assert tracked("research/engines/tsa_engine.py", "research/engines/eia_engine.py") != []
    offenders = [
        f for f, text in tracked_python_text().items()
        if re.search(r"^\s*(from|import)\s+research\b|quant_research_lab|tsa_engine|eia_engine|TSAEngine|EIAEngine", text, re.MULTILINE)
        and f != "tests/test_repo_layout.py"
    ]
    assert offenders == []


def test_dead_code_and_retired_targets_removed():
    gone = [
        "SP500 Predictor/src/features.py", "SP500 Predictor/src/market_scanner.py", "SP500 Predictor/src/model_daily.py",
        "SP500 Predictor/src/modeling.py", "SP500 Predictor/src/sentiment.py", "SP500 Predictor/src/utils.py",
        "SP500 Predictor/streamlit_app.py", "SP500 Predictor/.github", "SP500 Predictor/scripts/push_to_hf.sh",
        "hf_space_deployment", "FPL_Optimizer", "website", "ncca_api-1.json", ".bolt",
    ]
    assert tracked(*gone) == []


def test_no_fpl_or_hf_space_references_in_runtime_code():
    runtime = {f: t for f, t in tracked_python_text().items() if f != "tests/test_repo_layout.py"}
    assert [f for f, t in runtime.items() if "FPL_Optimizer" in t or "fpl_optimizations" in t] == []
    hook = (REPO / "market_sentiment_tool/src/hooks/useSupabaseData.ts").read_text(encoding="utf-8")
    assert "useFPLOptimizations" not in hook


def test_old_sp500_folder_is_gone_and_package_exists():
    assert tracked("SP500 Predictor") == []
    for pkg in ("tradehub", "tradehub/core", "tradehub/engines", "tradehub/scripts", "tradehub/api"):
        assert (REPO / pkg / "__init__.py").is_file(), pkg
    assert (REPO / "tradehub/config/settings.yaml").is_file()


def test_no_sys_path_hacks_or_old_import_roots():
    scoped = {
        f: t for f, t in tracked_python_text().items()
        if f.startswith(("tradehub/", "tests/", "shared/", "market_sentiment_tool/")) and f not in {"tests/test_repo_layout.py", "tests/test_compare_junit.py", "tests/test_rewrite_imports.py"}
    }
    assert [f for f, t in scoped.items() if re.search(r"sys\.path\.(insert|append)", t)] == []
    old = re.compile(r"(?m)^\s*(from|import)\s+(src|scripts|api)(\.|\s)|SP500 Predictor|SP500_Predictor")
    assert [f for f, t in scoped.items() if old.search(t)] == []


def test_single_dependency_manifest():
    reqs = [f for f in tracked("*requirements*.txt") if not f.startswith(("archive/", "_attic/"))]
    assert reqs == []
    assert (REPO / "pyproject.toml").is_file()


def test_generated_output_not_tracked():
    assert tracked("graphify-out") == []


def test_docs_do_not_point_at_removed_paths():
    stale = re.compile(r"SP500 Predictor|FPL_Optimizer|hf_space_deployment|quant_research_lab")
    docs = ["README.md", "SYSTEM_ARCH.md", ".agent/index/SYSTEM_MAP.md", ".agent/index/notes_manifest.md"]
    assert [d for d in docs if stale.search((REPO / d).read_text(encoding="utf-8"))] == []


def test_predictions_ledger_migration_defines_both_tables():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000003_predictions_ledger.sql"
    assert path.is_file(), "predictions ledger migration is missing"
    sql = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS predictions" in sql
    assert "CREATE TABLE IF NOT EXISTS track_record" in sql
    assert '"predictions_owner"' in sql
    assert '"track_record_owner"' in sql
    for column in ("market_ticker", "our_prob", "as_of", "status", "brier"):
        assert column in sql, f"predictions table missing column {column}"


def test_backtest_runs_migration_defines_table():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000004_backtest_runs.sql"
    assert path.is_file(), "backtest_runs migration is missing"
    sql = path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS backtest_runs" in sql
    assert '"backtest_runs_owner"' in sql
    for column in ("config_hash", "data_hash", "pnl_after_fees", "max_drawdown", "gate_status", "cal_buckets"):
        assert column in sql, f"backtest_runs missing column {column}"


def test_backtest_log_loss_migration_adds_nullable_column():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000006_backtest_log_loss.sql"
    assert path.is_file(), "backtest log-loss migration is missing"
    sql = path.read_text(encoding="utf-8")
    assert "ALTER TABLE backtest_runs" in sql
    assert "log_loss numeric(12,8)" in sql
    assert "log_loss numeric(12,8) NOT NULL" not in sql


def test_kalshi_edges_urls_energy_migration():
    path = REPO / "market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql"
    assert path.is_file(), "kalshi_edges urls/energy migration is missing"
    sql = path.read_text(encoding="utf-8")
    for needle in ("market_url", "source_url", "'ENERGY'", "kalshi_edges_market_id_key"):
        assert needle in sql, f"migration missing {needle}"
