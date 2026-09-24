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
        if re.search(r"^\s*(from|import)\s+research\b|quant_research_lab|tsa_engine|eia_engine|TSAEngine|EIAEngine", text, re.M)
        and f != "tests/test_repo_layout.py"
    ]
    assert offenders == []
