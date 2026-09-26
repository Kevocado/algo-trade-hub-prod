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
    for needle in ("market_url", "source_url", "engine", "gate_status", "updated_at", "expires_at", "'ENERGY'", "kalshi_edges_market_id_key"):
        assert needle in sql, f"migration missing {needle}"


def test_kalshi_edges_migration_never_hands_legacy_rows_to_scan_engines():
    sql = (REPO / "market_sentiment_tool/supabase/migrations/20260416000005_kalshi_edges_urls_energy.sql").read_text(encoding="utf-8")
    # Existing rows come from the legacy scanners; tagging them 'weather'/'gas' would let the
    # scan's stale-edge cleanup (scoped by engine) delete another writer's rows.
    assert "SET engine = lower(edge_type)" not in sql
    assert "'legacy_' || lower(edge_type)" in sql
    # The unique index on market_id fails if the legacy inserters left duplicates: dedupe first.
    assert sql.index("DELETE FROM kalshi_edges") < sql.index("CREATE UNIQUE INDEX IF NOT EXISTS kalshi_edges_market_id_key")


def test_dockerfile_and_dockerignore():
    docker = (REPO / "Dockerfile").read_text(encoding="utf-8")
    ignore = (REPO / ".dockerignore").read_text(encoding="utf-8").split()
    assert "uvicorn tradehub.api.main:app" in docker
    assert "uv pip install --system" in docker and "-r pyproject.toml" in docker
    assert "npm run build" in docker and "ENV PYTHONPATH=/app" in docker
    for pattern in (".env", ".env.*", "*.pem", "*.key", "_attic", ".venv", "**/node_modules", "models", "*.pkl"):
        assert pattern in ignore, f".dockerignore must exclude {pattern}"
    # Docker matches .dockerignore patterns against the context-root-relative path, so a bare
    # `*.pem` / `models` only excludes the top level. Without the `**/` prefix a nested
    # `subdir/.env`, `subdir/keys/private.pem` or `subdir/models/` would still enter the context.
    for pattern in ("**/.env", "**/.env.*", "**/*.pem", "**/*.key", "**/models", "**/model", "**/*.pkl"):
        assert pattern in ignore, f".dockerignore must exclude {pattern} at any depth"


def test_deploy_workflow_builds_then_deploys_to_vps():
    import yaml

    path = REPO / ".github/workflows/deploy-tradehub.yml"
    assert path.is_file(), "deploy workflow missing"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"test", "build", "vps"}
    assert workflow["jobs"]["build"]["needs"] == "test"
    assert workflow["jobs"]["vps"]["needs"] == "build"
    assert workflow["jobs"]["vps"]["if"] == "vars.VPS_HOST != ''"
    assert workflow["env"]["IMAGE"] == "ghcr.io/kevocado/tradehub"
    for needle in (
        "deploy tradehub ${{ github.sha }}",
        "SUPABASE_SERVICE_ROLE_KEY: dummy-baseline-placeholder",
        "--build-arg VITE_SUPABASE_URL=",
        "secrets.VPS_KNOWN_HOSTS",
    ):
        assert needle in text, f"workflow missing {needle}"
    for azure in ("az login", "containerapp", "AZURE_"):
        assert azure not in text, f"workflow must not reference Azure ({azure})"


def test_pm2_process_files_are_retired():
    assert not (REPO / "Procfile").exists()
    assert not (REPO / "ecosystem.config.js").exists()
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "## VPS deployment" in readme
    assert "tradehub-scan.timer" in readme and "deploy tradehub" in readme
    assert "pm2 start" not in readme


def test_deploy_workflow_pushes_with_the_built_in_token():
    # A personal token needs write:packages to create the GHCR package; the
    # workflow's own GITHUB_TOKEN (permissions: packages: write) always can.
    text = (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8")
    assert "password: ${{ secrets.GITHUB_TOKEN }}" in text
    assert "GHCR_PAT" not in text
