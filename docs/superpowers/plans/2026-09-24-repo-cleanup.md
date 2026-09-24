# Repo Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Shrink `algo-trade-hub-prod` to only what the in-scope system runs, in a space-free layout that imports without `sys.path` hacks and installs from one dependency manifest, without changing the behavior of anything that stays.

**Architecture:** This is a behavior-preserving refactor, verified two ways. First, a structural test file (`tests/test_repo_layout.py`) grows one assertion group per task, and each group is written first and seen to fail. Second, a JUnit comparison tool checks that every test that passed at the baseline still passes after each task. The only tests allowed to disappear are the sports tests that this plan deliberately deletes. The package move is a scripted codemod with its own unit tests. It is not hand-editing.

**Tech Stack:**
- Python 3.12, created by `uv` in a local `.venv`
- `pytest` and `ruff`
- `uv pip install -r pyproject.toml` (the project is **not** installed as a package; everything runs from the repo root)
- Node 24 for the frontend check: `npm run build` / `npm run test` in `market_sentiment_tool/`

**Spec:** [docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md](../specs/2026-09-23-trade-hub-prediction-scope-design.md), section 8 "Repo cleanup". Read it before starting.

## Global Constraints

- **Repo root:** `/Users/sigey/Documents/Projects/algo-trade-hub-prod`. Every command below runs from the repo root unless it says otherwise. Paths containing a space (`SP500 Predictor`) must be quoted.
- **Behavior-preserving:** don't change logic in any code that stays. The only edits allowed are removals, moves, import rewrites, and path fixes that a move forces. If a step seems to need a logic change, stop and report it; don't improvise.
- **Never delete untracked files.** Untracked leftovers (model `.pkl` files, caches, `.pem` keys, local data) are moved into `_attic/`, which is gitignored. The user deletes `_attic/` later. Tracked files are removed with `git rm` / `git mv` so history keeps them.
- **Never** run `git push`, `git reset --hard`, `git clean`, `git checkout -- <path>`, or any history rewrite. The git-history purge of the old `quant_research_lab/*.txt` key files is **out of scope**. It needs explicit user approval.
- **Package name refinement vs. the spec:** the spec says `core/` and `engines/`. This plan puts them under one top-level package, `tradehub/` (`tradehub/core`, `tradehub/engines`, `tradehub/scripts`, `tradehub/api`), because bare top-level names like `api`, `core`, and `scripts` collide with names that other installed distributions sometimes ship.
- **`Weather/` refinement vs. the spec:** the spec says delete `Weather/`. It actually holds weather-market research notes (NWS API spec, Open-Meteo ensembles, settlement rules, market mapping) that the upcoming weather engine needs. It is **moved** to `research/weather_notes/`, not deleted.
- Keep `AGENTS.md`, `Rules.md`, `task.md`, `implementation_plan.md`, `.agent/`, `.agents/`, and `.obsidian/`. `AGENTS.md` defines them as this repo's working vault. HF *Hub* model downloads (`get_hf_path` in `quant_engine.py`) stay. Only the public HF *Space* sync is retired.
- Don't touch `Procfile` or `ecosystem.config.js` (the VPS is retired in a later rollout step), the Supabase database, or any migration file.
- Commit messages end with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

## Prerequisites (do these before Task 1)

- [ ] **P1: Confirm the working tree is clean.**

Run: `git status --short`
Expected: no output. If there is output, **STOP and ask the user** to commit the pending Phase 0 schema work and the `docs/` specs and plans first. Do not stash, discard, or commit someone else's work yourself.

- [ ] **P2: Create the working branch.**

If executing in an isolated worktree, create it with the superpowers:using-git-worktrees skill using branch name `chore/repo-cleanup`. Otherwise:
Run: `git switch -c chore/repo-cleanup`
Expected: `Switched to a new branch 'chore/repo-cleanup'`

---

## File Structure (end state)

```
algo-trade-hub-prod/
├── pyproject.toml              NEW   single dependency manifest + pytest/ruff config
├── tradehub/                   NEW   (was "SP500 Predictor/")
│   ├── __init__.py
│   ├── core/                   ← SP500 Predictor/src/*  (kept modules only)
│   ├── engines/                ← SP500 Predictor/scripts/engines/{macro_engine,quant_engine,weather_engine,weather_maker}.py
│   ├── scripts/                ← SP500 Predictor/scripts/*.py (kept) + supabase_setup.sql stays out (see research/legacy)
│   ├── api/                    ← SP500 Predictor/api/*
│   └── config/settings.yaml    ← SP500 Predictor/config/settings.yaml
├── tests/                      ← SP500 Predictor/tests/* (kept) + test_repo_layout.py + tools tests
├── tools/                      NEW   compare_junit.py, rewrite_imports.py (dev tooling)
├── research/                   NEW   parked, not imported by runtime code
│   ├── README.md
│   ├── engines/                ← tsa_engine.py, eia_engine.py
│   ├── quant_lab/              ← quant_research_lab/*
│   ├── weather_notes/          ← Weather/*
│   ├── legacy/                 ← backtester.py, evaluation.py, optimizer.py, weather_model.py, fred_model.py, supabase_setup.sql
│   └── tools/                  ← discover_series.py, generate_market_snapshot.py
├── models/                     untracked runtime model files (gitignored)
├── shared/                     unchanged location
├── market_sentiment_tool/      unchanged location (frontend + backend + supabase migrations)
├── _attic/                     untracked leftovers, gitignored, the user deletes it later
└── docs/                       unchanged
```

**Removed (tracked):** sports engines and sports tests, the equities/Alpaca swarm, SPY-model modules, debug scripts, Streamlit app, HF Space deployment and its workflows, `FPL_Optimizer/`, `website/`, `ncca_api-1.json`, `.bolt/`, `graphify-out/` (untracked, regenerated locally), and every `requirements*.txt`.

---

## Task 1: Baseline test run + JUnit comparison tool

**Files:**
- Create: `tools/compare_junit.py`
- Create: `tests/test_compare_junit.py`
- Modify: `.gitignore` (add `.cleanup/`)

**Interfaces:**
- Produces: CLI `python tools/compare_junit.py BASELINE_XML CURRENT_XML [--allow-removed GLOB ...]`. It exits `0` when every test that passed in the baseline still passes (ignoring keys that match an `--allow-removed` glob), and `1` otherwise, printing each regression. Test keys are normalized to `<test_module>[.<TestClass>]::<test_name>`, so the same test matches before and after its file moves from `SP500 Predictor/tests/` to `tests/`.
- Produces: `.cleanup/baseline.xml`, the baseline JUnit report every later task compares against.

- [ ] **Step 1: Create the virtualenv with the pre-cleanup dependencies**

```bash
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r "SP500 Predictor/requirements.txt" -r market_sentiment_tool/backend/requirements.txt -r requirements.vps.txt pytest ruff
```
Expected: ends with `Installed N packages`. If one package fails to build on 3.12 (for example `soccerdata`), re-run the same command without that single requirements line by passing it through a temp file, and note the dropped package in your task report. It only matters to sports code, which Task 2 deletes.

- [ ] **Step 2: Record the baseline**

```bash
mkdir -p .cleanup
.venv/bin/python -m pytest "SP500 Predictor/tests" -q -p no:cacheprovider --junitxml=.cleanup/baseline.xml | tail -5
```
Expected: a summary line such as `N passed, M failed`. Failures are acceptable at baseline. They just aren't protected. Paste that summary line into your task report.

- [ ] **Step 3: Write the failing test for the comparison tool**

Create `tests/test_compare_junit.py`:

```python
import importlib.util
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("compare_junit", REPO / "tools" / "compare_junit.py")
compare_junit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compare_junit)


def _write(tmp_path, name, cases):
    body = "".join(
        f'<testcase classname="{cls}" name="{test}">{inner}</testcase>' for cls, test, inner in cases
    )
    path = tmp_path / name
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite>{body}</testsuite></testsuites>')
    return path


def test_key_normalizes_old_and_new_locations():
    assert compare_junit.test_key("SP500 Predictor.tests.test_x", "test_a") == "test_x::test_a"
    assert compare_junit.test_key("tests.test_x", "test_a") == "test_x::test_a"
    assert compare_junit.test_key("tests.test_x.TestY", "test_b") == "test_x.TestY::test_b"


def test_load_results_reads_statuses(tmp_path):
    path = _write(tmp_path, "r.xml", [
        ("tests.test_x", "test_ok", ""),
        ("tests.test_x", "test_bad", "<failure/>"),
        ("tests.test_x", "test_err", "<error/>"),
        ("tests.test_x", "test_skip", "<skipped/>"),
    ])
    assert compare_junit.load_results(path) == {
        "test_x::test_ok": "passed",
        "test_x::test_bad": "failed",
        "test_x::test_err": "failed",
        "test_x::test_skip": "skipped",
    }


def test_regressions_flags_lost_passes_but_allows_listed_removals():
    baseline = {"test_x::a": "passed", "test_x::b": "passed", "test_dixon_coles::c": "passed", "test_x::d": "failed"}
    current = {"test_x::a": "passed", "test_x::b": "failed"}
    assert compare_junit.regressions(baseline, current, ["test_dixon_coles*"]) == ["test_x::b: passed -> failed"]


def test_regressions_reports_missing_tests():
    assert compare_junit.regressions({"test_x::a": "passed"}, {}, []) == ["test_x::a: passed -> missing"]


def test_main_exit_codes(tmp_path):
    base = _write(tmp_path, "b.xml", [("tests.test_x", "test_a", "")])
    good = _write(tmp_path, "g.xml", [("tests.test_x", "test_a", "")])
    bad = _write(tmp_path, "x.xml", [("tests.test_x", "test_a", "<failure/>")])
    assert compare_junit.main([str(base), str(good)]) == 0
    assert compare_junit.main([str(base), str(bad)]) == 1
```

- [ ] **Step 4: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_compare_junit.py -q -p no:cacheprovider`
Expected: an ERROR during collection mentioning `tools/compare_junit.py` (file not found).

- [ ] **Step 5: Implement the tool**

Create `tools/compare_junit.py`:

```python
"""Fail if any test that passed in a baseline JUnit report no longer passes.

Inputs are JUnit files pytest just wrote locally, so stdlib ElementTree is acceptable here;
never point this tool at XML from an untrusted source.
"""
from __future__ import annotations

import argparse
import fnmatch
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def test_key(classname: str, name: str) -> str:
    parts = classname.split(".")
    start = next((i for i, part in enumerate(parts) if part.startswith("test_")), 0)
    return f"{'.'.join(parts[start:])}::{name}"


def load_results(path: Path) -> dict[str, str]:
    results: dict[str, str] = {}
    for case in ET.parse(path).getroot().iter("testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        else:
            status = "passed"
        results[test_key(case.get("classname", ""), case.get("name", ""))] = status
    return results


def regressions(baseline: dict[str, str], current: dict[str, str], allowed_removed: list[str]) -> list[str]:
    found = []
    for key, status in sorted(baseline.items()):
        if status != "passed" or any(fnmatch.fnmatchcase(key, glob) for glob in allowed_removed):
            continue
        now = current.get(key, "missing")
        if now != "passed":
            found.append(f"{key}: passed -> {now}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument("--allow-removed", nargs="*", default=[])
    args = parser.parse_args(argv)
    baseline = load_results(args.baseline)
    current = load_results(args.current)
    lost = regressions(baseline, current, args.allow_removed)
    passed_before = sum(1 for s in baseline.values() if s == "passed")
    passed_now = sum(1 for s in current.values() if s == "passed")
    print(f"baseline passed: {passed_before}  current passed: {passed_now}  regressions: {len(lost)}")
    for line in lost:
        print(f"  REGRESSION {line}")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_compare_junit.py -q -p no:cacheprovider`
Expected: `5 passed`

- [ ] **Step 7: Ignore the scratch folder**

Append to `.gitignore`:

```gitignore

# ── Cleanup scratch (baseline test reports) ──────
.cleanup/
```

- [ ] **Step 8: Commit**

```bash
git add tools/compare_junit.py tests/test_compare_junit.py .gitignore
git commit -m "chore: add baseline JUnit comparison tool for the repo cleanup

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 2: Remove the sports engines

The hub no longer models sports. The dedicated predictor repos own that (spec §3.3).

**Files:**
- Create: `tests/test_repo_layout.py`
- Delete (git rm): `SP500 Predictor/scripts/engines/{nba_engine,f1_engine,ncaa_engine,football_engine,dixon_coles}.py`, `SP500 Predictor/tests/test_dixon_coles.py`, `SP500 Predictor/tests/test_sports_data_quality.py`, `SP500 Predictor/KALSHI_SPORTS_CORE_BRIEF.md`. Also delete `SP500 Predictor/scripts/debug_engines.py` and `SP500 Predictor/src/market_scanner.py`: both are dead code that imports the sports engines, so they must go in this task for its layout test to pass.
- Modify: `SP500 Predictor/scripts/background_scanner.py` (imports + `scan_real_edge`)
- Modify: `SP500 Predictor/api/main.py` (remove the `/api/nba_props` and `/api/f1_signals` endpoints), `SP500 Predictor/api/schemas.py` (remove `NBASignal`, `F1Signal`), `SP500 Predictor/api/dependencies.py` (remove the `nba_signals`/`f1_signals` cache keys)
- Modify: `SP500 Predictor/tests/test_kalshi_edge_system.py` (delete class `TestNBAEngine` and the two sports endpoint tests)
- Modify: `shared/background_scanner.py` (remove football import, `sys.path` hack, `fetch_and_store_football`, and its call)

**Interfaces:**
- Produces: `tests/test_repo_layout.py` with helpers `tracked(*pathspecs) -> list[str]` and `tracked_python_text() -> dict[str, str]`. Later tasks append test functions to this file.

- [ ] **Step 1: Write the failing layout test**

Create `tests/test_repo_layout.py`:

```python
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
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `2 failed`. The first lists the five engine files. The second lists `background_scanner.py`, `shared/background_scanner.py`, and the test files.

- [ ] **Step 3: Delete the sports files**

```bash
git rm -q "SP500 Predictor/scripts/engines/nba_engine.py" "SP500 Predictor/scripts/engines/f1_engine.py" "SP500 Predictor/scripts/engines/ncaa_engine.py" "SP500 Predictor/scripts/engines/football_engine.py" "SP500 Predictor/scripts/engines/dixon_coles.py" "SP500 Predictor/tests/test_dixon_coles.py" "SP500 Predictor/tests/test_sports_data_quality.py" "SP500 Predictor/KALSHI_SPORTS_CORE_BRIEF.md" "SP500 Predictor/scripts/debug_engines.py" "SP500 Predictor/src/market_scanner.py"
```

- [ ] **Step 3b: Remove the sports API endpoints**

These endpoints only served cached output of the deleted engines, and nothing in the frontend calls them (`git grep -n "nba_props\|f1_signals" -- market_sentiment_tool/src` prints nothing).

In `SP500 Predictor/api/main.py`:
- In the import block, change `    Opportunity, NWSReading, NBASignal, F1Signal, ShadowPerformanceResponse,` to `    Opportunity, NWSReading, ShadowPerformanceResponse,`.
- Delete from the banner line directly above `# ENDPOINT 6: /api/nba_props` (the `# ════` line) down to, **but not including**, the `# ════` banner line directly above `# ENDPOINT 8: /api/shadow-performance`. This removes `get_nba_props` and `get_f1_signals`.

In `SP500 Predictor/api/schemas.py`, delete from the line `# ─── NBA Props ───…` down to, **but not including**, the line `# ─── Shadow Performance ───…`. That removes `NBASignal` and `F1Signal`.

In `SP500 Predictor/api/dependencies.py`, inside `_scanner_cache`, delete the two lines `    "nba_signals": [],` and `    "f1_signals": [],`.

In `SP500 Predictor/tests/test_kalshi_edge_system.py`, inside `class TestFastAPIEndpoints`, delete the whole methods `test_nba_props_filter_by_min_edge` and `test_f1_signals_empty_list`, from each `def` line through the blank line before the next `def`.

- [ ] **Step 4: Strip sports from `SP500 Predictor/scripts/background_scanner.py`**

Delete these four import lines, near the top of the file:

```python
from scripts.engines.nba_engine import NBAEngine
from scripts.engines.f1_engine import F1Engine
from scripts.engines.ncaa_engine import NCAAEngine
from scripts.engines.football_engine import FootballKalshiEngine
```

In `scan_real_edge()`, delete everything from the line `    # ── Sports Schedule Fetchers ──` down to, **but not including**, the line `    print(f"\n📊 Total real-edge opportunities: {len(all_ops)}")`. That removes the NBA schedule, F1, NCAA, Soccer, and NBA Props blocks. After the edit, the TSA and EIA blocks are directly followed by the `📊 Total` print. Those two blocks are removed in Task 4.

- [ ] **Step 5: Delete `TestNBAEngine` from `SP500 Predictor/tests/test_kalshi_edge_system.py`**

Delete from the line `class TestNBAEngine:` down to, **but not including**, the line `class TestFastAPIEndpoints:`.

- [ ] **Step 6: Strip football from `shared/background_scanner.py`**

Delete these three lines, near the top:

```python
# Add "SP500 Predictor" to sys.path so we can import its scripts module despite the space in the folder name
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'SP500 Predictor')))
from scripts.engines.football_engine import FootballKalshiEngine
```

Delete the whole function `def fetch_and_store_football():`, from its `def` line down to, **but not including**, the comment line `# This dictionary represents backtested "Green Islands"`.

In `main_loop()`, delete the single line `            fetch_and_store_football()`.

If `sys` is no longer used anywhere in the file (`grep -n "sys\." shared/background_scanner.py` prints nothing), delete the line `import sys`. Do the same for `os` (`grep -n "os\." shared/background_scanner.py`).

- [ ] **Step 7: Verify the layout test passes**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `2 passed`

- [ ] **Step 8: Verify nothing else regressed**

```bash
.venv/bin/python -m pytest "SP500 Predictor/tests" -q -p no:cacheprovider --junitxml=.cleanup/current.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/current.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
.venv/bin/python -m py_compile "SP500 Predictor/scripts/background_scanner.py" shared/background_scanner.py "SP500 Predictor/api/main.py" "SP500 Predictor/api/schemas.py" "SP500 Predictor/api/dependencies.py"
```
Expected: the compare prints `regressions: 0` and exits 0. `py_compile` prints nothing.

- [ ] **Step 9: Commit**

```bash
git add -A tests/test_repo_layout.py "SP500 Predictor" shared/background_scanner.py
git commit -m "chore: remove sports engines from the trade hub

The dedicated NBA/NFL/PL/F1/CFB predictor repos own sports models; the
hub will consume their APIs read-only instead.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 3: Remove the equities / Alpaca swarm

The equities LangGraph (`ORCHESTRATOR_MODE=market_sentiment`: quant → macro → CIO → execute) trades Alpaca stocks, not Kalshi, so it is out of scope (spec §3.3). The crypto path is the production default and must keep working exactly as before.

**Files:**
- Modify: `market_sentiment_tool/backend/orchestrator.py`
- Modify: `market_sentiment_tool/backend/mcp_server.py`
- Delete (git rm): `market_sentiment_tool/backend/quant_engine.py`, `market_sentiment_tool/backend/ingestion.py`, `market_sentiment_tool/backend/news_rag.py`, `market_sentiment_tool/backend/requirements.rag.txt`, `market_sentiment_tool/backend/supabase_hard_reset.sql`
- Test: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Consumes: `tracked()` from Task 2.
- Produces: `orchestrator.py` always runs the crypto services. The functions that must keep existing, unchanged: `run_crypto_services`, `crypto_worker_loop`, `build_crypto_graph`, `evaluate_crypto_edge`, `market_resolution`, `write_trade_to_supabase`, `log_to_supabase`, `check_crypto_trade_switch`, `initialize_runtime_clients`. In `mcp_server.py`, `execute_kalshi_order`, `submit_kalshi_order`, `assert_kill_switch`, and `assert_crypto_trading_enabled` stay unchanged.

- [ ] **Step 1: Append the failing tests**

Append to `tests/test_repo_layout.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `3 failed, 2 passed`

- [ ] **Step 3: Delete the equities functions from `orchestrator.py`**

Delete each of these **whole top-level definitions** in `market_sentiment_tool/backend/orchestrator.py`: the `def`/`class` line through the last line of its body. Locate each by searching for the exact text in the second column.

| Delete | Search for |
|---|---|
| `update_portfolio_state` | `def update_portfolio_state(` |
| `check_kill_switch` | `def check_kill_switch(` (do **not** touch `check_crypto_trade_switch`) |
| the SQLite tick polling section | from the banner comment `# SQLite Tick Polling` (including the `# ═══` line above it) through the end of `def aggregate_market_snapshot(`. This includes `_last_tick_id = 0` and `poll_latest_ticks`. |
| the LangGraph equities nodes | from the banner comment `# LangGraph State & Nodes` (including the `# ═══` line above it) through the end of `def execute_trade(`. This covers `AgentState`, `quantitative_analysis`, `_call_local_llm`, `macro_sentiment`, `cio_supervisor`, and `execute_trade`. Stop **before** the banner `# Crypto Models + Kalshi WS Edge Evaluation`. |
| the swarm graph builder | from the banner `# Build the LangGraph Swarm` (including the `# ═══` line above it) through the end of `def build_graph():` |
| the equities heartbeat | from the banner `# Live Mark-to-Market & Heartbeat` (including the `# ═══` line above it) through the end of `async def heartbeat_loop():`. Stop **before** the banner `# Entrypoint`. |

- [ ] **Step 4: Simplify the entrypoint to crypto-only**

In the `if __name__ == "__main__":` block, replace:

```python
            initialize_runtime_clients(require_supabase=True, require_kalshi=(ORCHESTRATOR_MODE != "market_sentiment"))
            log.info("Starting Orchestrator (mode=%s)…", ORCHESTRATOR_MODE)
            if ORCHESTRATOR_MODE == "market_sentiment":
                asyncio.run(heartbeat_loop())
            else:
                asyncio.run(run_crypto_services())
```

with:

```python
            initialize_runtime_clients(require_supabase=True, require_kalshi=True)
            log.info("Starting Orchestrator (crypto services)…")
            asyncio.run(run_crypto_services())
```

- [ ] **Step 5: Delete module constants and imports that only the equities code used**

Run:

```bash
for n in DB_PATH HEARTBEAT_SECONDS LOCAL_LLM_ENDPOINT LOCAL_LLM_MODEL ORCHESTRATOR_MODE sqlite3; do echo "$n: $(grep -cw "$n" market_sentiment_tool/backend/orchestrator.py)"; done
```

Expected: each prints `1`, meaning only its definition or import remains. Delete that one line for each: the `DB_PATH = ...`, `HEARTBEAT_SECONDS = ...`, `LOCAL_LLM_ENDPOINT = ...`, `LOCAL_LLM_MODEL = ...`, and `ORCHESTRATOR_MODE = ...` assignments, and `import sqlite3`. If any count is greater than 1, leave that name in place and list it in your task report. Also delete, in the module docstring, the line `Boot order: Step 4 (after ingestion.py is streaming).` and any docstring sentence mentioning `ORCHESTRATOR_MODE`.

- [ ] **Step 6: Remove the Alpaca tools from `mcp_server.py`**

In `market_sentiment_tool/backend/mcp_server.py`:
1. Delete the imports `from alpaca.trading.client import TradingClient`, `from alpaca.trading.requests import MarketOrderRequest`, and `from alpaca.trading.enums import OrderSide, TimeInForce`.
2. Delete the lines `ALPACA_API_KEY = os.getenv("ALPACA_API_KEY", "")`, `ALPACA_SECRET_KEY = os.getenv("ALPACA_SECRET_KEY", "")`, and `alpaca: TradingClient | None = None`.
3. Delete this block:
```python
try:
    alpaca = TradingClient(ALPACA_API_KEY, ALPACA_SECRET_KEY, paper=True)
    log.info("Alpaca TradingClient initialized (paper mode).")
except Exception as exc:
    log.warning("Alpaca TradingClient init failed (will use mock): %s", exc)
```
4. Delete these four whole functions, **each including the `@mcp.tool()` line directly above it**: `get_portfolio`, `get_market_data`, `execute_paper_trade`, `close_position`.
5. Replace the module docstring's first four lines with:
```python
"""
mcp_server.py — FastMCP Tool Bridge for Kalshi Execution
=========================================================
Exposes Kalshi order tools over FastMCP, bound strictly to 127.0.0.1.
```

- [ ] **Step 7: Delete the equities-only backend files**

```bash
git rm -q market_sentiment_tool/backend/quant_engine.py market_sentiment_tool/backend/ingestion.py market_sentiment_tool/backend/news_rag.py market_sentiment_tool/backend/requirements.rag.txt market_sentiment_tool/backend/supabase_hard_reset.sql
```

- [ ] **Step 8: Check for broken or unused names**

Run: `.venv/bin/ruff check --select F401,F811,F821 market_sentiment_tool/backend/orchestrator.py market_sentiment_tool/backend/mcp_server.py`
Expected: **zero `F821` (undefined name)** findings. For each `F401` (unused import) finding, delete that import, then re-run until the command prints `All checks passed!`.

- [ ] **Step 9: Verify**

```bash
.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider
.venv/bin/python -m pytest "SP500 Predictor/tests" -q -p no:cacheprovider --junitxml=.cleanup/current.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/current.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
```
Expected: layout `5 passed`, and the compare prints `regressions: 0`. `test_crypto_kalshi_last_mile.py` exercises the orchestrator and mcp_server heavily, so it's the main safety net here.

- [ ] **Step 10: Commit**

```bash
git add -A market_sentiment_tool/backend tests/test_repo_layout.py
git commit -m "chore: remove equities/Alpaca swarm, keep crypto Kalshi path

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 4: Create `research/` and consolidate model file locations

This parks TSA/EIA, the quant lab, the weather notes, and legacy modules that later rollout steps will mine for reuse (backtester math, optimizer retrain logic). It also makes `models/` at the repo root the single home for runtime model files.

**Files:**
- Create: `research/README.md`
- Move (git mv): `SP500 Predictor/scripts/engines/{tsa_engine,eia_engine}.py` → `research/engines/`; `quant_research_lab/*` → `research/quant_lab/`; `Weather/*` → `research/weather_notes/`; `SP500 Predictor/src/{backtester,evaluation,optimizer,weather_model,fred_model}.py` and `SP500 Predictor/scripts/supabase_setup.sql` → `research/legacy/`; `SP500 Predictor/scripts/{discover_series,generate_market_snapshot}.py` → `research/tools/`; `update_research_lab.py` → `research/quant_lab/update_research_lab.py`
- Modify: `SP500 Predictor/scripts/background_scanner.py` (remove TSA/EIA); `market_sentiment_tool/backend/orchestrator.py` and `SP500 Predictor/scripts/auto_retrain_regime.py` (model path candidates); `research/quant_lab/update_research_lab.py` (hardcoded path)
- Test: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Produces: runtime code resolves crypto models from `models/…` (and the existing `model/…` / root fallbacks). No runtime code may reference `quant_research_lab/` or import from `research/`.

- [ ] **Step 1: Append the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py::test_research_is_parked_and_not_imported -q -p no:cacheprovider`
Expected: `1 failed`

- [ ] **Step 3: Move the tracked files**

```bash
mkdir -p research/engines research/quant_lab research/weather_notes research/legacy research/tools
git mv "SP500 Predictor/scripts/engines/tsa_engine.py" "SP500 Predictor/scripts/engines/eia_engine.py" research/engines/
for f in $(git ls-files quant_research_lab); do mkdir -p "research/quant_lab/$(dirname "${f#quant_research_lab/}")"; git mv "$f" "research/quant_lab/${f#quant_research_lab/}"; done
git ls-files -z Weather | while IFS= read -r -d '' f; do mkdir -p "research/weather_notes/$(dirname "${f#Weather/}")"; git mv "$f" "research/weather_notes/${f#Weather/}"; done
git mv "SP500 Predictor/src/backtester.py" "SP500 Predictor/src/evaluation.py" "SP500 Predictor/src/optimizer.py" "SP500 Predictor/src/weather_model.py" "SP500 Predictor/src/fred_model.py" "SP500 Predictor/scripts/supabase_setup.sql" research/legacy/
git mv "SP500 Predictor/scripts/discover_series.py" "SP500 Predictor/scripts/generate_market_snapshot.py" research/tools/
git mv update_research_lab.py research/quant_lab/update_research_lab.py
```
Expected: no errors. Run `git ls-files quant_research_lab Weather` and expect no output.

- [ ] **Step 4: Move untracked model files and leftovers out of the old folders**

```bash
mkdir -p models _attic
if [ -d quant_research_lab/models ]; then for f in quant_research_lab/models/*; do [ -e "models/$(basename "$f")" ] && mv "$f" "_attic/$(basename "$f").from-quant_research_lab" || mv "$f" models/; done; rmdir quant_research_lab/models; fi
[ -d quant_research_lab ] && mv quant_research_lab _attic/quant_research_lab_untracked
[ -d Weather ] && mv Weather _attic/Weather_untracked
for f in btc_sniper.pkl eth_sniper.pkl; do [ -e "$f" ] && mv "$f" "_attic/$f.root-copy"; done
ls models
```
Expected: `ls models` lists the crypto model files (for example `btc_sniper.pkl` and `eth_sniper.pkl`). The root copies of `btc_sniper.pkl`/`eth_sniper.pkl` were always shadowed by the `quant_research_lab/models/` copies earlier in the search order, so parking them changes nothing.

- [ ] **Step 5: Ignore `_attic/`**

Append to `.gitignore`:

```gitignore

# ── Untracked leftovers from the repo cleanup (user deletes manually) ──
_attic/
```

- [ ] **Step 6: Point model-path candidates at `models/`**

In `market_sentiment_tool/backend/orchestrator.py`, inside `load_crypto_models()`, replace the BTC candidate list with:

```python
        candidates=[
            "/root/kalshibot/btc_model.pkl",
            "models/btc_model.pkl",
            "model/btc_model.pkl",
            "model/lgbm_model_BTC.pkl",
            "models/btc_sniper.pkl",
            "btc_sniper.pkl",
        ],
```

and the ETH candidate list with:

```python
        candidates=[
            "/root/kalshibot/eth_model.pkl",
            "models/eth_model.pkl",
            "model/eth_model.pkl",
            "model/lgbm_model_ETH.pkl",
            "models/eth_sniper.pkl",
            "eth_sniper.pkl",
        ],
```

In `SP500 Predictor/scripts/auto_retrain_regime.py`, change the two candidate strings that contain `quant_research_lab/models/` to `models/`. The line `f"quant_research_lab/models/{asset.lower()}_model.pkl",` becomes `f"models/{asset.lower()}_model.pkl",`, and `f"quant_research_lab/models/{asset.lower()}_sniper.pkl",` becomes `f"models/{asset.lower()}_sniper.pkl",`. If that leaves the same string listed twice in the candidate list, delete the second occurrence.

- [ ] **Step 7: Remove TSA/EIA from `SP500 Predictor/scripts/background_scanner.py`**

Delete the imports `from scripts.engines.tsa_engine import TSAEngine` and `from scripts.engines.eia_engine import EIAEngine`. In `scan_real_edge()`, delete the block from `    # ── TSA Travel Engine ──` down to, **but not including**, `    print(f"\n📊 Total real-edge opportunities: {len(all_ops)}")`.

- [ ] **Step 8: Fix the hardcoded path in the moved research script**

In `research/quant_lab/update_research_lab.py`, replace:

```python
LAB_DIR = '/Users/sigey/Documents/Projects/algo-trade-hub-prod/quant_research_lab'
```

with:

```python
LAB_DIR = str(__import__("pathlib").Path(__file__).resolve().parent)
```

- [ ] **Step 9: Write `research/README.md`**

```markdown
# research/

Parked material. **Nothing in the runtime (`tradehub/`, `shared/`, `market_sentiment_tool/`) may import from here.**
`tests/test_repo_layout.py` enforces this.

| Folder | What | Why it's kept |
|---|---|---|
| `engines/` | TSA throughput and EIA nat-gas engines | Out of scope for now (spec §3.3). EIA may return as a weather-driven add-on. |
| `quant_lab/` | Crypto research notebooks, Kalshi history CSVs, research bots | Reference for the crypto shadow engine and the backtest suite. |
| `weather_notes/` | NWS/Open-Meteo API notes, settlement rules, Kalshi weather market mapping | Input to the weather engine (rollout step 4). |
| `legacy/` | `backtester.py`, `evaluation.py`, `optimizer.py`, `weather_model.py`, `fred_model.py`, `supabase_setup.sql` | Math to reuse in the backtest suite (rollout step 3) and model registry. Not runnable as-is: `backtester.py` depends on a removed Azure Blob logger. |
| `tools/` | `discover_series.py`, `generate_market_snapshot.py` | One-off Kalshi exploration helpers. |
```

- [ ] **Step 10: Verify**

```bash
.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider
.venv/bin/python -m pytest "SP500 Predictor/tests" -q -p no:cacheprovider --junitxml=.cleanup/current.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/current.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
```
Expected: layout `6 passed`, and the compare prints `regressions: 0`.

- [ ] **Step 11: Commit**

```bash
git add -A research .gitignore "SP500 Predictor" market_sentiment_tool/backend/orchestrator.py tests/test_repo_layout.py
git status --short | grep -E "^\?\?" || true
git commit -m "chore: park TSA/EIA, quant lab, weather notes and legacy modules in research/

Runtime model files now resolve from models/ at the repo root.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: the `grep` for untracked files prints nothing under `research/` or `models/`. Model files are covered by the existing `models/` and `*.pkl` gitignore rules.

---

## Task 5: Delete dead code and retired deploy targets

Everything deleted here is either unreachable from the kept code (verified by import-graph analysis when this plan was written) or a deploy target the spec retires.

**Files:**
- Delete (git rm), under `SP500 Predictor/`:
  - `src/features.py`, `src/model_daily.py`, `src/modeling.py`, `src/sentiment.py`, `src/utils.py`
  - `scripts/check_for_empty_loops.py`, `scripts/db_hard_reset.py`, `scripts/debug_kalshi.py`, `scripts/force_retrain.py`, `scripts/train_all_models.py`, `scripts/train_daily_models.py`, `scripts/push_to_hf.sh`
  - `streamlit_app.py`, `.streamlit/config.toml`, `.devcontainer/devcontainer.json`, `.github/workflows/{ai_optimizer,scanner,sync_to_hf}.yml`
  - `CLAUDE_CODE_PROMPT.md`, `CODEBASE_OVERVIEW.md`, `HUGGING_FACE_SETUP.md`, `README.md`, `app_changes_1_3_25.md`, `f1_model_lab.ipynb`, `refractor_prompt.ipynb`, `requirements.txt`, `.gitignore`
- Delete (git rm), at the repo root: `hf_space_deployment/`, `FPL_Optimizer/`, `website/`, `ncca_api-1.json`, `.bolt/`
- Modify: `shared/api_server.py` (remove the FPL endpoints), `market_sentiment_tool/src/hooks/useSupabaseData.ts` (remove `useFPLOptimizations`)
- Test: `tests/test_repo_layout.py` (append)

Note: the three workflows under `SP500 Predictor/.github/workflows/` have **never run**, because GitHub only runs workflows in the repo-root `.github/`. Deleting them changes no live automation. Scheduled jobs are recreated on Azure in rollout step 5.

- [ ] **Step 1: Append the failing tests**

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `2 failed, 6 passed`

- [ ] **Step 3: Delete the files**

```bash
cd "SP500 Predictor"
git rm -q src/features.py src/model_daily.py src/modeling.py src/sentiment.py src/utils.py \
  scripts/check_for_empty_loops.py scripts/db_hard_reset.py scripts/debug_kalshi.py \
  scripts/force_retrain.py scripts/train_all_models.py scripts/train_daily_models.py scripts/push_to_hf.sh \
  streamlit_app.py .streamlit/config.toml .devcontainer/devcontainer.json \
  .github/workflows/ai_optimizer.yml .github/workflows/scanner.yml .github/workflows/sync_to_hf.yml \
  CLAUDE_CODE_PROMPT.md CODEBASE_OVERVIEW.md HUGGING_FACE_SETUP.md README.md app_changes_1_3_25.md \
  f1_model_lab.ipynb refractor_prompt.ipynb requirements.txt .gitignore
cd ..
git rm -r -q hf_space_deployment FPL_Optimizer website ncca_api-1.json .bolt
```
Expected: no errors. If one path reports `did not match any files`, re-run the command without that path and note it in your report. It was already gone.

- [ ] **Step 4: Park untracked leftovers of deleted folders**

```bash
[ -d FPL_Optimizer ] && mv FPL_Optimizer _attic/FPL_Optimizer_untracked
[ -d hf_space_deployment ] && mv hf_space_deployment _attic/hf_space_deployment_untracked
[ -d website ] && mv website _attic/website_untracked
true
```

- [ ] **Step 5: Remove the FPL endpoints from `shared/api_server.py`**

Delete the section from the comment line `# FPL Optimization Endpoints` (including any `# ───` / `# ═══` rule line directly above it) down to, **but not including**, the line `@app.get("/kalshi/edges", tags=["kalshi"])`. That removes `optimize_fpl` and `fpl_history`. Then update the module docstring and the `FastAPI(description=...)` string. Replace the phrase `FPL optimization results and Kalshi scanner status` with `Kalshi scanner status`, and replace `Serves FPL optimizations and scanner status` with `Serves Kalshi scanner status`.

- [ ] **Step 6: Remove the unused FPL hook from the frontend**

In `market_sentiment_tool/src/hooks/useSupabaseData.ts`, delete the whole function `export function useFPLOptimizations() {`, from that line through its closing `}`. It is not imported anywhere (`git grep useFPLOptimizations` shows only the definition).

- [ ] **Step 7: Verify**

```bash
.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider
.venv/bin/python -m pytest "SP500 Predictor/tests" -q -p no:cacheprovider --junitxml=.cleanup/current.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/current.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
.venv/bin/python -m py_compile shared/api_server.py
(cd market_sentiment_tool && npx tsc --noEmit -p . && npm run build 2>&1 | tail -3)
```
Expected: layout `8 passed`; `regressions: 0`; `tsc` prints nothing; `vite build` ends with a `built in` line.

- [ ] **Step 8: Commit**

```bash
git add -A "SP500 Predictor" shared/api_server.py market_sentiment_tool/src/hooks/useSupabaseData.ts tests/test_repo_layout.py
git commit -m "chore: delete dead SPY-model code, Streamlit, HF Space deploy and FPL

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

## Task 6: Move `SP500 Predictor/` into the `tradehub/` package and remove `sys.path` hacks

**Files:**
- Create: `tools/rewrite_imports.py`, `tests/test_rewrite_imports.py`, `pyproject.toml`, `tradehub/__init__.py`, `tradehub/core/__init__.py`, `tradehub/engines/__init__.py`, `tradehub/scripts/__init__.py`
- Move (git mv):
  - `SP500 Predictor/src/*` → `tradehub/core/`
  - `SP500 Predictor/scripts/engines/*` → `tradehub/engines/`
  - `SP500 Predictor/scripts/*.py` → `tradehub/scripts/`
  - `SP500 Predictor/api/*` → `tradehub/api/`
  - `SP500 Predictor/config/settings.yaml` → `tradehub/config/settings.yaml`
  - `SP500 Predictor/tests/*` → `tests/`
- Modify: `market_sentiment_tool/backend/orchestrator.py` (`_load_async_telegram_notifier`), `market_sentiment_tool/backend/kalshi_auth_probe.py`, `shared/api_server.py`, `shared/config.py`, `tests/test_audit_feature_parity.py`, `tests/test_crypto_kalshi_last_mile.py`, `tests/test_obsidian_note_indexer.py`
- Test: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Consumes: the layout helpers from Task 2, and `tools/compare_junit.py` from Task 1.
- Produces:
  - Import roots `tradehub.core`, `tradehub.engines`, `tradehub.scripts`, `tradehub.api`, `shared`, and `market_sentiment_tool.backend`, all resolved from the repo root.
  - `tools/rewrite_imports.py` with `rewrite_source(text: str) -> str`, `strip_sys_path_hacks(text: str) -> str`, and CLI `python tools/rewrite_imports.py PATH [PATH ...]`, which rewrites the files in place and prints the ones it changed.
  - Scripts now run as modules from the repo root, for example `python -m tradehub.scripts.background_scanner` or `uvicorn tradehub.api.main:app`.

- [ ] **Step 1: Write the failing codemod tests**

Create `tests/test_rewrite_imports.py`:

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_rewrite_imports.py -q -p no:cacheprovider`
Expected: ERROR, because `tools/rewrite_imports.py` is not found.

- [ ] **Step 3: Implement the codemod**

Create `tools/rewrite_imports.py`:

```python
"""Rewrite old SP500 Predictor import paths to the tradehub package and strip sys.path hacks."""
from __future__ import annotations

import re
import sys
from pathlib import Path

_IMPORT_RULES = [
    (re.compile(r"\bSP500_Predictor\.src\b"), "tradehub.core"),
    (re.compile(r"(?m)^(\s*)from scripts\.engines(?=[\s.])"), r"\1from tradehub.engines"),
    (re.compile(r"(?m)^(\s*)import scripts\.engines\."), r"\1import tradehub.engines."),
    (re.compile(r"(?m)^(\s*)from src(?=[\s.])"), r"\1from tradehub.core"),
    (re.compile(r"(?m)^(\s*)import src\."), r"\1import tradehub.core."),
    (re.compile(r"(?m)^(\s*)from scripts(?=[\s.])"), r"\1from tradehub.scripts"),
    (re.compile(r"(?m)^(\s*)import scripts\."), r"\1import tradehub.scripts."),
    (re.compile(r"(?m)^(\s*)from api(?=[\s.])"), r"\1from tradehub.api"),
    (re.compile(r"(?m)^(\s*)import api\."), r"\1import tradehub.api."),
]
_STRING_RULES = [
    (re.compile(r"""(["'])scripts\.engines\."""), r"\1tradehub.engines."),
    (re.compile(r"""(["'])src\."""), r"\1tradehub.core."),
    (re.compile(r"""(["'])scripts\."""), r"\1tradehub.scripts."),
    (re.compile(r"""(["'])api\.main:app(["'])"""), r"\1tradehub.api.main:app\2"),
]
_SYS_PATH_RULES = [
    re.compile(r"(?m)^for path in \(REPO_ROOT, PREDICTOR_ROOT\):\n(?:[ \t]+[^\n]*\n){3}"),
    re.compile(r"(?m)^[ \t]*if [^\n]* not in sys\.path:\n[ \t]+sys\.path\.(?:insert|append)\([^\n]*\)\n"),
    re.compile(r"(?m)^sys\.path\.(?:insert|append)\([^\n]*\)\n"),
]


def rewrite_source(text: str) -> str:
    for pattern, replacement in _IMPORT_RULES + _STRING_RULES:
        text = pattern.sub(replacement, text)
    return text


def strip_sys_path_hacks(text: str) -> str:
    for pattern in _SYS_PATH_RULES:
        text = pattern.sub("", text)
    if not re.search(r"\bsys\.", text):
        text = re.sub(r"(?m)^import sys\n", "", text)
    return text


def main(paths: list[str]) -> int:
    for raw in paths:
        path = Path(raw)
        original = path.read_text(encoding="utf-8")
        updated = strip_sys_path_hacks(rewrite_source(original))
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print(f"rewrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

- [ ] **Step 4: Run the codemod tests**

Run: `.venv/bin/python -m pytest tests/test_rewrite_imports.py -q -p no:cacheprovider`
Expected: `5 passed`

- [ ] **Step 5: Append the failing layout tests**

```python
def test_old_sp500_folder_is_gone_and_package_exists():
    assert tracked("SP500 Predictor") == []
    for pkg in ("tradehub", "tradehub/core", "tradehub/engines", "tradehub/scripts", "tradehub/api"):
        assert (REPO / pkg / "__init__.py").is_file(), pkg
    assert (REPO / "tradehub/config/settings.yaml").is_file()


def test_no_sys_path_hacks_or_old_import_roots():
    scoped = {
        f: t for f, t in tracked_python_text().items()
        if f.startswith(("tradehub/", "tests/", "shared/", "market_sentiment_tool/")) and f != "tests/test_repo_layout.py"
    }
    assert [f for f, t in scoped.items() if re.search(r"sys\.path\.(insert|append)", t)] == []
    old = re.compile(r"(?m)^\s*(from|import)\s+(src|scripts|api)(\.|\s)|SP500 Predictor|SP500_Predictor")
    assert [f for f, t in scoped.items() if old.search(t)] == []
```

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `2 failed, 8 passed`

- [ ] **Step 6: Create `pyproject.toml`**

This makes the repo root importable for pytest and gives Task 7 its manifest.

```toml
[project]
name = "tradehub"
version = "0.1.0"
description = "Kalshi trade hub: edge engines, settlement and track record"
requires-python = ">=3.11"
dependencies = [
    "aiohttp",
    "alpaca-py",
    "cryptography>=41.0.0",
    "fastapi>=0.110.0",
    "fastmcp",
    "joblib>=1.3.0",
    "langgraph",
    "lightgbm>=4.0.0",
    "numpy>=1.24.0",
    "pandas>=2.0.0",
    "python-dotenv>=1.0.0",
    "python-telegram-bot>=21.0",
    "pyyaml>=6.0",
    "requests>=2.31.0",
    "scikit-learn>=1.3.0",
    "scipy>=1.11.0",
    "supabase>=2.0.0",
    "ta>=0.11.0",
    "uvicorn[standard]>=0.27.0",
    "websockets>=12.0",
    "yfinance>=0.2.28",
]

[project.optional-dependencies]
# Heavier deps used only by tradehub.scripts.background_scanner's AI/news path and HF model downloads.
scanner = [
    "fredapi>=0.5.1",
    "google-genai>=0.1.0",
    "huggingface_hub",
    "python-dateutil",
    "sentencepiece>=0.1.99",
    "torch>=2.1.0",
    "transformers>=4.36.0",
]
research = [
    "apscheduler>=3.10.4",
    "ipykernel",
    "jupyter>=1.0.0",
    "lxml>=5.0.0",
    "matplotlib>=3.7.0",
    "meteostat",
    "optuna>=3.4.0",
    "plotly>=5.15.0",
    "pytz",
    "seaborn>=0.13.0",
    "shap>=0.42.0",
    "statsmodels>=0.14.0",
    "vectorbt>=0.25.0",
]
dev = [
    "httpx>=0.27.0",
    "pytest>=8.0.0",
    "ruff>=0.6.0",
]

[tool.pytest.ini_options]
pythonpath = ["."]
testpaths = ["tests"]
addopts = "-p no:cacheprovider"

[tool.ruff]
line-length = 120
extend-exclude = ["research", "archive", "_attic", "market_sentiment_tool/node_modules"]
```

- [ ] **Step 7: Move the code with git**

```bash
mkdir -p tradehub/core tradehub/engines tradehub/scripts tradehub/api tradehub/config
for f in $(git ls-files "SP500 Predictor/src" | sed 's#^SP500 Predictor/src/##'); do git mv "SP500 Predictor/src/$f" "tradehub/core/$f"; done
for f in $(git ls-files "SP500 Predictor/scripts/engines" | sed 's#^SP500 Predictor/scripts/engines/##'); do git mv "SP500 Predictor/scripts/engines/$f" "tradehub/engines/$f"; done
for f in $(git ls-files "SP500 Predictor/scripts" | sed 's#^SP500 Predictor/scripts/##'); do git mv "SP500 Predictor/scripts/$f" "tradehub/scripts/$f"; done
for f in $(git ls-files "SP500 Predictor/api" | sed 's#^SP500 Predictor/api/##'); do git mv "SP500 Predictor/api/$f" "tradehub/api/$f"; done
git mv "SP500 Predictor/config/settings.yaml" tradehub/config/settings.yaml
for f in $(git ls-files "SP500 Predictor/tests" | sed 's#^SP500 Predictor/tests/##'); do git mv "SP500 Predictor/tests/$f" "tests/$f"; done
git ls-files "SP500 Predictor"
```
Expected: the final command prints nothing, meaning no tracked files remain under `SP500 Predictor/`. (`SP500 Predictor/src/__init__.py` becomes `tradehub/core/__init__.py`, and `SP500 Predictor/scripts/engines/__init__.py` becomes `tradehub/engines/__init__.py`.)

- [ ] **Step 8: Add the missing package markers**

```bash
for d in tradehub tradehub/core tradehub/engines tradehub/scripts tradehub/api; do [ -f "$d/__init__.py" ] || : > "$d/__init__.py"; done
```

- [ ] **Step 9: Park the untracked remainder of the old folder**

It holds a `.pem` key, model/data caches, and `pages/`. Never commit it.

```bash
[ -d "SP500 Predictor" ] && mv "SP500 Predictor" "_attic/SP500_Predictor_untracked"
ls "_attic/SP500_Predictor_untracked" 2>/dev/null | head
```

- [ ] **Step 10: Run the codemod over the moved code**

```bash
.venv/bin/python tools/rewrite_imports.py $(git ls-files "tradehub/*.py" "tests/*.py" | grep -v -e "^tests/test_rewrite_imports.py$" -e "^tests/test_repo_layout.py$")
git diff --stat
```
Expected: it prints one `rewrote …` line per changed file. Review `git diff` for `tradehub/` and `tests/`. Every change should be an import rewrite or a removed `sys.path` line; anything else is a bug in the codemod. If you find one, fix the codemod plus its test, and re-run from Step 4.

- [ ] **Step 11: Fix the path computations the move changed (manual edits)**

These change directory depth, so the codemod can't fix them:

`tests/test_audit_feature_parity.py`: replace

```python
REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "SP500 Predictor" / "scripts" / "audit_feature_parity.py"
```

with

```python
REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = REPO_ROOT / "tradehub" / "scripts" / "audit_feature_parity.py"
```

`tests/test_obsidian_note_indexer.py`: replace `repo_root = Path(__file__).resolve().parents[2]` with `repo_root = Path(__file__).resolve().parents[1]`.

`tests/test_crypto_kalshi_last_mile.py`: the codemod removed its `if REPO_ROOT not in sys.path:` block. Now replace `REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))` with `REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))`. If `REPO_ROOT` is no longer referenced anywhere else in that file (`grep -n REPO_ROOT tests/test_crypto_kalshi_last_mile.py` shows only the definition), delete that line instead.

`market_sentiment_tool/backend/orchestrator.py`: replace the body of `_load_async_telegram_notifier` with:

```python
def _load_async_telegram_notifier():
    from tradehub.core.telegram_notifier import TelegramNotifier

    return TelegramNotifier
```

`market_sentiment_tool/backend/kalshi_auth_probe.py` and `shared/api_server.py`: run the codemod on them, since they only have `sys.path` hacks:
`.venv/bin/python tools/rewrite_imports.py market_sentiment_tool/backend/kalshi_auth_probe.py shared/api_server.py`
Then in `kalshi_auth_probe.py`, if a `REPO_ROOT = ...` line remains and is unused, delete it. This script now runs as `python -m market_sentiment_tool.backend.kalshi_auth_probe` from the repo root.

`shared/config.py`: replace `"./SP500 Predictor/kalshi_private_key.pem"` with `"./kalshi_private_key.pem"`, and replace the docstring phrase `(market_sentiment_tool, SP500 Predictor, FPL_Optimizer, shared scanners)` with `(market_sentiment_tool, tradehub, shared scanners)`.

Comment-only references: in `tradehub/core/supabase_client.py`, change `Thin CRUD wrapper for the SP500 Predictor.` to `Thin CRUD wrapper for the trade hub.`. In `tradehub/core/kalshi_feed.py`, replace the comment line `# SP500 Predictor/KALSHI_SPORTS_CORE_BRIEF.md.` with `# (sports brief removed; sports now live in the dedicated predictor repos).`. In `tradehub/config/settings.yaml`, change `# SP500 Predictor — Central Configuration` to `# Trade Hub — Central Configuration`.

- [ ] **Step 12: Verify no old import roots or hacks remain**

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q -p no:cacheprovider`
Expected: `10 passed`. If `test_no_sys_path_hacks_or_old_import_roots` fails, it lists the offending files. Fix each by hand with the same rules as the codemod.

- [ ] **Step 13: Check for broken names across the moved code**

Run: `.venv/bin/ruff check --select F821,F811 tradehub tests shared market_sentiment_tool/backend`
Expected: `All checks passed!`. An F821 means an import rewrite missed something. Fix the import; don't suppress it.

- [ ] **Step 14: Full regression check from the new layout**

```bash
.venv/bin/python -m pytest -q --junitxml=.cleanup/current.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/current.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
.venv/bin/python -c "import tradehub.api.main, tradehub.scripts.background_scanner, tradehub.scripts.shadow_performance, market_sentiment_tool.backend.orchestrator; print('imports OK')"
```
Expected: `regressions: 0` and `imports OK`. Plain `pytest` now runs `tests/` via the pyproject config. If the import smoke test fails only because a required environment variable is missing, and not with `ModuleNotFoundError`, note it in your report and continue. Any `ModuleNotFoundError` must be fixed.

- [ ] **Step 15: Commit**

```bash
git add -A tradehub tests tools pyproject.toml market_sentiment_tool/backend shared
git status --short | grep -E "^\?\?" || true
git commit -m "refactor: move SP500 Predictor into the tradehub package, drop sys.path hacks

Imports now resolve from the repo root (pytest pythonpath, python -m).
Behavior-preserving: rewritten by tools/rewrite_imports.py (unit tested).

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: the untracked-files grep prints nothing.

---

## Task 7: One dependency manifest

**Files:**
- Delete (git rm): `requirements.vps.txt`, `market_sentiment_tool/backend/requirements.txt`, `research/quant_lab/requirements.txt`, `research/quant_lab/requirements-research.txt`
- Test: `tests/test_repo_layout.py` (append)

**Interfaces:**
- Consumes: `pyproject.toml` from Task 6.
- Produces: the install command, used from here on: `uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner`.

- [ ] **Step 1: Append the failing test**

```python
def test_single_dependency_manifest():
    reqs = [f for f in tracked("*requirements*.txt") if not f.startswith(("archive/", "_attic/"))]
    assert reqs == []
    assert (REPO / "pyproject.toml").is_file()
```

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py::test_single_dependency_manifest -q`
Expected: `1 failed`, listing the four files.

- [ ] **Step 2: Delete the old manifests**

```bash
git rm -q requirements.vps.txt market_sentiment_tool/backend/requirements.txt research/quant_lab/requirements.txt research/quant_lab/requirements-research.txt
```

Note: `ta-lib` (needs a system C library) and `pylint` from the old research list are intentionally not carried over, and nothing imports them. Say so in your report.

- [ ] **Step 3: Prove the manifest works from a clean environment**

```bash
rm -rf .venv-fresh
uv venv .venv-fresh --python 3.12
uv pip install --python .venv-fresh/bin/python -r pyproject.toml --extra dev --extra scanner
.venv-fresh/bin/python -m pytest -q --junitxml=.cleanup/fresh.xml | tail -3
.venv-fresh/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/fresh.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
```
Expected: `regressions: 0`. If a test regresses only in the fresh env with `ModuleNotFoundError: No module named 'X'`, add the distribution that provides `X` to the right list in `pyproject.toml` (`dependencies` if runtime code imports it at module import time, otherwise `scanner`) and re-run this step.

- [ ] **Step 4: Replace the old venv with the fresh one**

```bash
rm -rf .venv && mv .venv-fresh .venv
```
(`.venv` is gitignored and this plan created it in Task 1. It is not user data.)

- [ ] **Step 5: Verify and commit**

```bash
.venv/bin/python -m pytest tests/test_repo_layout.py -q
git add -A pyproject.toml requirements.vps.txt market_sentiment_tool/backend research/quant_lab tests/test_repo_layout.py
git commit -m "chore: replace 11 requirements files with one pyproject.toml

Install: uv pip install -r pyproject.toml --extra dev --extra scanner

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: layout `11 passed`.

---

## Task 8: Untrack generated files, refresh pointers, final verification

**Files:**
- Untrack (`git rm -r --cached`): `graphify-out/`
- Modify: `.gitignore`, `README.md`, `SYSTEM_ARCH.md`, `implementation_plan.md`, `task.md`, `.agent/index/notes_manifest.json`, `.agent/index/notes_manifest.md`, `.agent/index/SYSTEM_MAP.md`, `docs/superpowers/plans/2026-09-23-settlement-realized-pnl.md` (superseded banner)
- Test: `tests/test_repo_layout.py` (append)

- [ ] **Step 1: Append the failing tests**

```python
def test_generated_output_not_tracked():
    assert tracked("graphify-out") == []


def test_docs_do_not_point_at_removed_paths():
    stale = re.compile(r"SP500 Predictor|FPL_Optimizer|hf_space_deployment|quant_research_lab")
    docs = ["README.md", "SYSTEM_ARCH.md", ".agent/index/SYSTEM_MAP.md", ".agent/index/notes_manifest.md"]
    assert [d for d in docs if stale.search((REPO / d).read_text(encoding="utf-8"))] == []
```

Run: `.venv/bin/python -m pytest tests/test_repo_layout.py -q`
Expected: `2 failed, 11 passed`

- [ ] **Step 2: Stop tracking graphify output**

```bash
git rm -r -q --cached graphify-out
printf '\n# ── Generated knowledge graph (rebuild locally; see AGENTS.md) ──\ngraphify-out/\n' >> .gitignore
```
The files stay on disk. `AGENTS.md` tells agents to rebuild them locally.

- [ ] **Step 3: Regenerate the notes index**

The indexer is covered by `tests/test_obsidian_note_indexer.py`.

Run: `.venv/bin/python scripts/index_obsidian_notes.py`
Expected: exits 0. `.agent/index/notes_manifest.json` and `.md` no longer list `SP500 Predictor/...` notes, because those files were deleted in Task 5.

- [ ] **Step 4: Rewrite path references in the architecture docs**

In `README.md`, `SYSTEM_ARCH.md`, and `.agent/index/SYSTEM_MAP.md`:
- Replace every `SP500 Predictor/src/` with `tradehub/core/`, `SP500 Predictor/scripts/engines/` with `tradehub/engines/`, `SP500 Predictor/scripts/` with `tradehub/scripts/`, and `SP500 Predictor/api/` with `tradehub/api/`. Then replace any remaining `SP500 Predictor` with `tradehub`.
- In `README.md`, replace the quick-start `cd "SP500 Predictor"` instruction block with:

```markdown
uv venv .venv --python 3.12
uv pip install --python .venv/bin/python -r pyproject.toml --extra dev --extra scanner
.venv/bin/python -m pytest            # run from the repo root
.venv/bin/python -m tradehub.scripts.background_scanner
```
- Delete README/SYSTEM_ARCH tree lines or bullets that mention `FPL_Optimizer`, `hf_space_deployment`, `quant_research_lab`, `Weather/`, or `website/`, and add a tree line `├── research/   # parked research, not imported by runtime (see research/README.md)`.

Re-run `grep -nE "SP500 Predictor|FPL_Optimizer|hf_space_deployment|quant_research_lab" README.md SYSTEM_ARCH.md .agent/index/SYSTEM_MAP.md` and expect no output.

- [ ] **Step 5: Point the working-state files at the current spec**

Replace the entire contents of `implementation_plan.md` with:

```markdown
# Implementation Plan

Current build specification:
- Spec: `docs/superpowers/specs/2026-09-23-trade-hub-prediction-scope-design.md`
- Plans: `docs/superpowers/plans/` (one plan per rollout step; the repo cleanup is step 1)
```

Replace the `## Current Focus` section of `task.md` with:

```markdown
## Current Focus
- Rollout step 1 (repo cleanup) complete. Next: step 2, predictions ledger + settlement by market result
  (revise docs/superpowers/plans/2026-09-23-settlement-realized-pnl.md per the spec §9).
```

- [ ] **Step 6: Mark the old settlement plan superseded**

Insert this block directly under the title line of `docs/superpowers/plans/2026-09-23-settlement-realized-pnl.md`:

```markdown
> **SUPERSEDED (2026-09-24).** Do not execute as written. The repo cleanup removed `heartbeat_loop` (Task 5 target)
> and the spec moved to suggest-only, scale-to-zero jobs, so settlement must score *predictions* against Kalshi
> market results via a cron entrypoint (spec §4.5, §9 step 2). Its pure-math Tasks 1–2 are reusable in the rewrite.
```

- [ ] **Step 7: Final verification (all of it)**

```bash
.venv/bin/python -m pytest -q --junitxml=.cleanup/final.xml | tail -3
.venv/bin/python tools/compare_junit.py .cleanup/baseline.xml .cleanup/final.xml --allow-removed "test_dixon_coles*" "test_sports_data_quality*" "test_kalshi_edge_system.TestNBAEngine::*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_nba_props*" "test_kalshi_edge_system.TestFastAPIEndpoints::test_f1_signals*"
.venv/bin/ruff check --select F821,F811 tradehub tests shared market_sentiment_tool/backend
(cd market_sentiment_tool && npx tsc --noEmit -p . && npm run build 2>&1 | tail -2 && npm run test 2>&1 | tail -3)
git status --short
```
Expected: `regressions: 0`; the layout tests are all passing (13); ruff prints `All checks passed!`; `tsc` is silent; the vite build succeeds; vitest's pass count equals what it was before Task 5. `git status --short` shows only the intended staged changes, with no stray untracked files outside the gitignored `_attic/`, `.cleanup/`, `models/`, `graphify-out/`, and `.venv/`.

- [ ] **Step 8: Commit**

```bash
git add -A .gitignore README.md SYSTEM_ARCH.md implementation_plan.md task.md .agent/index docs/superpowers/plans/2026-09-23-settlement-realized-pnl.md tests/test_repo_layout.py
git commit -m "chore: untrack graphify output, refresh docs and notes index for new layout

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 9: Report to the user**

Summarize: the baseline and final pass counts from `compare_junit.py`, the files parked in `_attic/` (so the user can review and delete them), any dependency you had to add in Task 7, and anything you listed as "left in place" in Task 3 Step 5. Remind them that the git-history purge of the old key files and the Azure migration are separate, approval-gated steps.

---

## Self-Review (done while writing)

**Spec §8 coverage:**

| Spec row | Where it's handled |
|---|---|
| `SP500 Predictor/` rename | Task 6, as the `tradehub/` package (refinement stated in Global Constraints) |
| Sports engines | Task 2 |
| TSA/EIA to `research/` | Task 4 |
| `FPL_Optimizer/` | Task 5 |
| Equities swarm, `supabase_hard_reset.sql`, local SQLite ticks | Task 3. Ticks are untracked, and `ingestion.py`, which wrote them, is gone. `chroma_db/` is untracked and was used only by the deleted RAG; it can be moved to `_attic/` by the user. |
| `hf_space_deployment/`, `sync_to_hf.yml`, empty `website/` | Task 5 |
| `Weather/` | Task 4, moved rather than deleted (refinement stated in Global Constraints) |
| `quant_research_lab/` | Task 4 |
| `graphify-out/` | Task 8 |
| Root meta clutter | `.bolt` in Task 5, root `*.pkl` in Task 4. `task.md`/`implementation_plan.md`/`Rules.md` are kept because `AGENTS.md` depends on them; the first two are refreshed in Task 8. `midterm.html` and `trades.log` are already gitignored/untracked, so nothing to do. |
| `requirements*.txt` | Task 7 |
| Root `.pem` files | Untracked and gitignored. Deleting them requires key rotation first, so it is left to the user; the plan doesn't touch them. |
| Git history purge | Out of scope; needs user approval (Global Constraints). |

**Placeholder scan:** no TBD, TODO, or "similar to Task N". Every code step contains full code, and every deletion names exact files or exact start/stop anchor lines.

**Consistency:** the `--allow-removed` globs are identical in every task. The layout test count grows 2 → 5 → 6 → 8 → 10 → 11 → 13 across Tasks 2 → 8. The codemod function names (`rewrite_source`, `strip_sys_path_hacks`) match between `tools/rewrite_imports.py` and its tests. The `compare_junit` function names (`test_key`, `load_results`, `regressions`, `main`) match between the tool and its tests.
