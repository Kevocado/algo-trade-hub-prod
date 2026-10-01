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
    # The hook that read `useFPLOptimizations` was deleted as unreachable (plan n, 2026-10-01), so the
    # guard is now that nothing in the frontend mentions it.
    frontend = [p for p in (REPO / "market_sentiment_tool/src").rglob("*.ts*")
                if "useFPLOptimizations" in p.read_text(encoding="utf-8")]
    assert frontend == []


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


def test_tradehub_data_package_is_not_gitignored():
    """`Data/` in .gitignore is matched case-insensitively on macOS, so it also swallows
    `tradehub/data/`. Files there must stay visible to `git status` and normal `git add`,
    otherwise a new data module is silently left untracked and never reaches a PR."""
    probe = "tradehub/data/_gitignore_probe.py"
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", "--no-index", probe], cwd=REPO, capture_output=True
    )
    assert ignored.returncode == 1, (
        f"{probe} is ignored; a new tradehub/data module would be silently untracked. "
        "Add a `!tradehub/data/` exception to .gitignore instead of `git add -f`."
    )


def test_tradehub_data_package_keeps_build_artifacts_ignored():
    """Guard against fixing the case-insensitivity trap by blanket re-including the package,
    which would un-hide its __pycache__ and litter `git status`."""
    for artifact in ("tradehub/data/__pycache__/weather.cpython-312.pyc", "Data/big.parquet"):
        result = subprocess.run(
            ["git", "check-ignore", "-q", "--no-index", artifact], cwd=REPO, capture_output=True
        )
        assert result.returncode == 0, f"{artifact} must stay ignored"


def test_deploy_workflow_builds_then_deploys_to_vps():
    import yaml

    path = REPO / ".github/workflows/deploy-tradehub.yml"
    assert path.is_file(), "deploy workflow missing"
    text = path.read_text(encoding="utf-8")
    workflow = yaml.safe_load(text)
    assert set(workflow["jobs"]) == {"test", "frontend", "build", "vps"}
    assert workflow["jobs"]["build"]["needs"] == ["test", "frontend"]
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


def test_deploy_workflow_prunes_docker_images_before_it_pulls():
    """The VPS ran out of disk mid-deploy, and it looked exactly like a code regression.

    `b49879e` built green and failed only in `vps` with `no space left on device`, on a 99%-full
    38G disk holding 35 images totalling 33.91GB. The *identical commit* deployed fine after a
    manual 7.26GB prune. Every merge to `main` pulls a fresh image and leaves the superseded one
    behind, so nothing was ever reclaiming them. Ordering is the load-bearing part of the fix:
    reclaiming space after the layer extract has already failed is worth nothing, and a plain
    "does the workflow prune?" check stays green through a reorder that reinstates the outage.
    """
    import yaml

    workflow = yaml.safe_load(
        (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8"))
    runs = [str(s.get("run", "")) for s in workflow["jobs"]["vps"]["steps"]]

    # The pull is not in this repo: `ssh ... deploy tradehub <sha>` invokes a stack script on the
    # VPS that does the `docker pull`. So the pull is pinned to whichever step carries that call.
    prune_at = [i for i, r in enumerate(runs) if "docker image prune" in r]
    pull_at = [i for i, r in enumerate(runs) if "deploy tradehub" in r]
    assert prune_at, f"the vps job no longer prunes anything; its steps run {runs}"
    assert pull_at, f"the vps job no longer deploys; its steps run {runs}"
    assert min(prune_at) < min(pull_at), (
        f"the prune must run before the pull, but the prune is at step {prune_at} "
        f"and the pull at step {pull_at}"
    )
    # `-a` is the whole point. The superseded per-SHA images are tagged, not dangling, so a plain
    # `docker image prune` reclaims none of them and the disk creeps at the same measured ~5GB.
    assert "docker image prune -a -f" in runs[min(prune_at)], runs[min(prune_at)]


def test_deploy_workflow_cannot_reach_a_volume_prune():
    """The highest-value assertion in this file: a volume prune in a deploy workflow is data loss.

    All three local volumes on the VPS are in use (`kalshi_portfolio` and the bind-mounted
    caches), so a prune that takes volumes destroys live state on the very machine the deploy
    depends on. The `system prune` subcommand is the same hazard one indirection away, and it is
    broad enough to be the tempting one-word "fix" for a full disk -- so it is pinned too. The
    check is on the whole file text rather than the parsed commands, which also forbids
    reintroducing either spelling in a comment, where it sits one uncomment away from shipping.
    """
    text = (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8")
    assert "--volumes" not in text, "the deploy workflow must never be able to prune volumes"
    assert "docker system prune" not in text, (
        "`docker system prune` reclaims volumes under its volumes flag and is far broader than "
        "this job needs; use `docker image prune -a -f` instead"
    )


def test_deploy_prune_fails_soft_and_reports_free_space():
    """A cleanup step that can block a deploy reintroduces the class of failure it is fixing, and
    a red `vps` job with no disk numbers is the diagnosis this whole change exists to prevent.

    Both halves are pinned because each fails silently: dropping `continue-on-error` turns a
    cleanup hiccup into a failed deploy, and dropping either `df` leaves a future reader with the
    same SSH-in-and-measure-it detour that cost an hour here. The per-command `||` guards are what
    make the failure a GitHub warning inside the step; `continue-on-error` is the backstop.
    """
    import yaml

    workflow = yaml.safe_load(
        (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["vps"]["steps"]
    prunes = [s for s in steps if "docker image prune" in str(s.get("run", ""))]
    assert prunes, f"the vps job no longer prunes anything; its steps are {[s.get('name') for s in steps]}"
    prune = prunes[0]

    assert prune["continue-on-error"] is True, (
        "a prune failure must not be able to fail the deploy"
    )
    run = prune["run"]
    assert run.count("df -h /") == 2, f"free space must be reported before and after; got {run!r}"
    # Build cache was 229MB with 80MB reclaimable, so this one earns its place.
    assert "docker builder prune -f" in run, run
    for command in ("docker image prune -a -f", "docker builder prune -f"):
        assert f"{command} || echo" in run, f"{command} must be guarded so it fails soft: {run!r}"


def test_deploy_prune_warnings_use_real_annotation_syntax():
    """A guard that is not an annotation is silent-but-nonfatal, which helps nobody.

    GitHub's workflow commands are a *double* colon on both sides of the keyword. The first
    version of these guards used a single colon, which `echo` prints happily as ordinary log text:
    no annotation, nothing in the run's checks UI, and a prune failure nobody sees. It shipped
    through the fail-soft test, and through a report that claimed the double-colon form had been
    verified, because the old assertion was `f"{command} || echo" in run` -- that measured that a
    guard existed, not that the guard was an annotation. That is this repo's recurring failure
    mode: a test that passes while measuring nothing.

    So the positive side is checked per guard command rather than per file, and the negative side
    forbids the single-colon variant outright. The naive `":warning:" not in text` cannot be used,
    because that substring IS contained in the correct double-colon form; a negative lookbehind is
    what actually distinguishes an annotation from log text.
    """
    import yaml

    path = REPO / ".github/workflows/deploy-tradehub.yml"
    text = path.read_text(encoding="utf-8")
    steps = yaml.safe_load(text)["jobs"]["vps"]["steps"]
    prunes = [s for s in steps if "docker image prune" in str(s.get("run", ""))]
    assert prunes, f"the vps job no longer prunes anything; its steps are {[s.get('name') for s in steps]}"
    run = prunes[0]["run"]

    for command in ("docker image prune -a -f", "docker builder prune -f", "df -h /"):
        assert command + ' || echo "::warning::' in run, (
            f"every guard on {command!r} must emit a double-colon annotation; got {run!r}"
        )
    # Nothing anywhere in the file may use the single-colon form, which prints as plain log text.
    # Over the whole file, so a regression cannot hide in a comment either.
    defect = re.search(r"(?<!:):warning:", text)
    assert defect is None, (
        f"single-colon :warning: at offset {defect.start()} is plain log text, not an annotation; "
        "GitHub's workflow commands need a double colon on both sides of the keyword"
    )


def test_ci_runs_the_frontend_suite_and_typechecker():
    """The workflow ran `python -m pytest -q` and nothing else, so all of market_sentiment_tool's
    tests never executed on any PR: 128 green tests that were not run. The Dockerfile's
    `npm run build` is `vite build`, which transpiles without typechecking and never runs vitest, so
    a `tsc` break shipped green too. `build` now depends on this job, which is what makes any
    frontend test claim on this repo mean something.

    Each command is asserted separately because dropping ONE of them leaves the others looking fine:
    `npm ci` alone is a green no-op, and a job that only runs vitest still ships a type error."""
    import yaml

    workflow = yaml.safe_load(
        (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8"))
    job = workflow["jobs"]["frontend"]
    steps = [str(s.get("run", "")) for s in job["steps"]]

    assert job["defaults"]["run"]["working-directory"] == "market_sentiment_tool"
    assert any(s.strip() == "npm ci" for s in steps), steps
    assert any(s.strip() == "npm run typecheck" for s in steps), steps
    assert any(s.strip() == "npx vitest run" for s in steps), steps
    # `npm test` is `vitest run` here, but the explicit form is what the job must say.
    assert workflow["jobs"]["build"]["needs"] == ["test", "frontend"], (
        "the image must not be built or pushed when the frontend job fails"
    )


def test_ci_frontend_job_shares_the_python_job_path_triggers():
    """The `paths:` filter is workflow-level, so a new job inherits it -- but only while it stays in
    this workflow file. Asserted so a job added to a trigger-less workflow is not mistaken for one
    that runs on the same paths as the Python tests."""
    import yaml

    workflow = yaml.safe_load(
        (REPO / ".github/workflows/deploy-tradehub.yml").read_text(encoding="utf-8"))
    paths = workflow[True]["push"]["paths"]   # `on:` parses to the YAML boolean True

    assert "market_sentiment_tool/**" in paths, paths
    assert ".github/workflows/deploy-tradehub.yml" in paths, paths


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


def test_the_app_is_branded_algo_trade_hub():
    html = (REPO / "market_sentiment_tool/index.html").read_text(encoding="utf-8")
    assert "<title>Algo Trade Hub</title>" in html
    assert "Lovable" not in html and "lovable.dev" not in html
    assert "Algo Trade Hub" in (REPO / "market_sentiment_tool/src/App.tsx").read_text(encoding="utf-8")
    assert 'title="Algo Trade Hub API"' in (REPO / "tradehub/api/main.py").read_text(encoding="utf-8")


def test_rls_hardening_migration_is_recorded():
    sql = (REPO / "market_sentiment_tool/supabase/migrations/20260416000010_rls_portfolio_news.sql").read_text(encoding="utf-8")
    assert "ALTER TABLE kalshi_portfolio ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE news_embeddings ENABLE ROW LEVEL SECURITY" in sql
    assert "FOR SELECT" in sql and "FOR ALL" not in sql
