"""
The suite must be hermetic, and importing the package must not touch os.environ.

`load_dotenv()` at module scope in a library module used to auto-load the
gitignored developer-local `.env` into `os.environ` for anything that imported
it. That made the suite's result a function of an untracked file (a developer's
`FRED_API_KEY` chose a different branch of `alfred_vintages.fetch_vintages`) and
put the Supabase service-role key and exchange keys one traceback away from a
transcript.

The contract these tests enforce:

  * importing any `tradehub.*` module has no effect on `os.environ`
  * no library module calls `load_dotenv()` at import time
  * the suite's pass/fail counts do not move when a `.env` is present, and do
    not move when that `.env` is full of deliberately wrong values
"""

from __future__ import annotations

import ast
import json
import os
import pkgutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

import tradehub

REPO = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = REPO / "tradehub"

# `sklearn` sets KMP_* and `transformers`/`fastmcp` set TORCHINDUCTOR_CACHE_DIR /
# FASTMCP_* on import. Those are third-party, not ours, and carry no secret, so
# they are excluded rather than pretended away -- the assertion is about the
# keys that matter, and it is enforced by name so a new leak cannot hide here.
THIRD_PARTY_IMPORT_KEYS = {
    "KMP_DUPLICATE_LIB_OK",
    "KMP_INIT_AT_FORK",
    "TORCHINDUCTOR_CACHE_DIR",
    "FASTMCP_HOST",
    "FASTMCP_PORT",
}


def _module_names() -> list[str]:
    return sorted(m.name for m in pkgutil.walk_packages(tradehub.__path__, "tradehub."))


def _garbage_env() -> str:
    """A `.env` whose every value is wrong in a way that must not change results.

    No real secret appears here. The FRED key is deliberately present and
    deliberately not a real key: the whole point is that a FRED_API_KEY-shaped
    variable sitting in a file must not steer the code that used to auto-load it.
    """
    return textwrap.dedent(
        """\
        FRED_API_KEY=not-a-real-key-this-must-not-be-used
        SUPABASE_URL=https://garbage.invalid
        SUPABASE_SERVICE_ROLE_KEY=garbage-service-role-key
        ALPACA_API_KEY=garbage-alpaca
        ALPACA_SECRET_KEY=garbage-alpaca-secret
        TIINGO_API_KEY=garbage-tiingo
        KALSHI_API_KEY_ID=garbage-kalshi-id
        KALSHI_PRIVATE_KEY_PATH=/nonexistent/garbage.pem
        KALSHI_API_KEY=garbage-kalshi-key
        GEMINI_API_KEY=garbage-gemini
        OPENROUTER_API_KEY=garbage-openrouter
        """
    )


# ── The contract ──────────────────────────────────────────────────────────────

def test_importing_tradehub_does_not_touch_os_environ():
    """No `tradehub.*` module may add to or mutate `os.environ` on import.

    Run in a subprocess so the assertion is about a *fresh* interpreter. In
    this process most of the package is already imported by earlier tests, so
    an import-time load would have happened invisibly before this test ran.
    """
    probe = textwrap.dedent(
        """
        import contextlib, importlib, io, json, os, pkgutil, sys
        import tradehub
        before = dict(os.environ)
        failures = []
        for m in pkgutil.walk_packages(tradehub.__path__, "tradehub."):
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    importlib.import_module(m.name)
            except Exception as exc:
                failures.append([m.name, type(exc).__name__, str(exc)[:200]])
        after = dict(os.environ)
        allowed = set(%r)
        added = sorted(k for k in after if k not in before and k not in allowed)
        changed = sorted(k for k in after if k in before and after[k] != before[k])
        print("PROBE" + json.dumps({
            "added": added, "changed": changed, "failures": failures,
        }))
        """
    ) % sorted(THIRD_PARTY_IMPORT_KEYS)

    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(REPO)
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, cwd=REPO
    )
    assert out.returncode == 0, out.stderr[-3000:]

    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("PROBE"))
    result = json.loads(line[len("PROBE"):])
    assert result["failures"] == [], f"modules failed to import: {result['failures']}"
    assert result["added"] == [], f"importing tradehub.* added to os.environ: {result['added']}"
    assert result["changed"] == [], f"importing tradehub.* mutated os.environ: {result['changed']}"


def test_no_library_module_calls_load_dotenv_at_module_scope():
    """The root cause, guarded structurally.

    Any module-scope `load_dotenv()` under `tradehub/` is the defect. Entrypoints
    (`main()`, a `__main__` block, the API lifespan) are allowed and are checked
    separately below, because that is the fix: load explicitly where a process
    starts, nowhere else.
    """
    offenders = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "env.py":  # the one sanctioned wrapper
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:  # module scope only, not inside def/class
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "load_dotenv":
                    offenders.append(f"{path.relative_to(REPO)}:{sub.lineno}")
    assert offenders == [], (
        "module-scope load_dotenv() reintroduces the import-time .env leak: "
        + ", ".join(offenders)
    )


def test_env_wrapper_is_the_only_dotenv_caller():
    """All `load_dotenv` use in the package is funnelled through `core/env.py`."""
    callers = []
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if path.name == "env.py":
            continue
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if "load_dotenv" in stripped and not stripped.startswith("#"):
                callers.append(f"{path.relative_to(REPO)}:{i}")
    assert callers == [], f"load_dotenv referenced outside tradehub/core/env.py: {callers}"


def test_load_local_env_is_explicit_and_opt_in():
    """`load_local_env()` is a no-op when no `.env` exists -- the production case."""
    from tradehub.core.env import env_path, load_local_env

    assert env_path() == REPO / ".env"
    missing = REPO / "definitely-not-here.env"
    assert load_local_env(env_file=missing) is False


def test_entrypoints_still_opt_into_the_local_env_file():
    """The fix must not break local development: each entrypoint still loads it.

    These are the places allowed to touch `os.environ`. If one of them stops
    loading, a developer's `python -m tradehub.scripts.scan` silently runs with
    no credentials -- a regression this file exists to prevent.
    """
    expected = {
        "market_sentiment_tool/backend/orchestrator.py": "load_env_values(__file__)",
        "market_sentiment_tool/backend/mcp_server.py": "load_env_values(__file__)",
        "tradehub/api/main.py": "load_local_env()",
        "tradehub/scripts/scan.py": "load_local_env()",
        "tradehub/scripts/settle_predictions.py": "load_local_env()",
        "tradehub/scripts/market_alerts.py": "load_local_env()",
        "tradehub/scripts/weather_auto_sell.py": "load_local_env()",
        "tradehub/scripts/auto_retrain_regime.py": "load_local_env()",
        "tradehub/scripts/force_demo_trade.py": "load_local_env()",
        "tradehub/engines/weather_engine.py": "load_local_env()",
    }
    for rel, call in expected.items():
        assert call in (REPO / rel).read_text(encoding="utf-8"), f"{rel} no longer loads the local .env"


def test_importing_mst_backend_does_not_touch_os_environ():
    """Same contract for `market_sentiment_tool.backend`, which the suite imports too.

    `orchestrator` and `mcp_server` used to call `load_canonical_env()` at module
    scope. That is what made the whole suite's result a function of whether a
    `.env` existed, because the test module imports both at import time.
    """
    probe = textwrap.dedent(
        """
        import contextlib, importlib, io, json, os
        before = dict(os.environ)
        failures = []
        for name in ("market_sentiment_tool.backend.orchestrator",
                     "market_sentiment_tool.backend.mcp_server"):
            try:
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    importlib.import_module(name)
            except Exception as exc:
                failures.append([name, type(exc).__name__, str(exc)[:200]])
        after = dict(os.environ)
        print("PROBE" + json.dumps({
            "added": sorted(k for k in after if k not in before),
            "changed": sorted(k for k in after if k in before and after[k] != before[k]),
            "failures": failures,
        }))
        """
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(REPO)
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, cwd=REPO
    )
    assert out.returncode == 0, out.stderr[-3000:]
    line = next(ln for ln in out.stdout.splitlines() if ln.startswith("PROBE"))
    result = json.loads(line[len("PROBE"):])
    assert result["failures"] == [], result["failures"]
    assert result["added"] == [], f"importing mst.backend added to os.environ: {result['added']}"
    assert result["changed"] == [], f"importing mst.backend mutated os.environ: {result['changed']}"


def test_api_app_loads_env_in_lifespan_not_at_import():
    """The API loads `.env` when the server boots, not when the module is imported.

    Import-time loading is what the test suite tripped over: it imports
    `tradehub.api.main` on nearly every API test, and that used to be enough to
    pull the developer's `.env` into the test process.
    """
    from tradehub.api import main as api_main

    assert api_main.app.router.lifespan_context is not None, "app must carry the env-loading lifespan"
    src = (REPO / "tradehub/api/main.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    module_level = [
        n for n in tree.body
        if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom))
    ]
    for node in module_level:
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) and sub.func.id == "load_local_env":
                pytest.fail(f"load_local_env() called at module scope (line {sub.lineno})")


# ── Hermeticity of the suite itself ───────────────────────────────────────────

def _run_alfred_and_no_edges() -> str:
    """Pass/fail counts only -- the wall-clock suffix is not part of the result."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = str(REPO)
    env["SUPABASE_SERVICE_ROLE_KEY"] = "dummy-baseline-placeholder"
    # The two files that the leaked FRED_API_KEY used to steer differently.
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "tests/test_alfred_vintages.py", "tests/test_cpi_no_edges.py"],
        capture_output=True, text=True, env=env, cwd=REPO,
    )
    last = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else out.stderr[-2000:]
    # "36 passed in 19.71s" -> "36 passed"
    return last.split(" in ")[0].strip()


def test_alfred_results_do_not_depend_on_a_present_env_file(tmp_path):
    """A `.env` full of wrong values must not change the ALFRED/CPI results.

    This is the test that the old `load_dotenv()` call made impossible to
    satisfy. Before the fix, a developer's real FRED_API_KEY in `.env` made
    `fetch_vintages` take the keyed branch and pass a `secret=` kwarg to these
    tests' two-argument fake servers -- a `TypeError`, i.e. the "pre-existing
    order-dependent failure" that several engineers saw on one commit.
    """
    env_file = REPO / ".env"
    if env_file.exists():
        # Never read, move, or overwrite a developer's real `.env` -- that file is
        # the thing being protected, and this test must not be the thing that
        # destroys it. CI checks out without one, so the assertion runs there on
        # every push; on a workstation it is verified with the real file moved
        # aside by hand (see .superpowers/sdd/2026-09-28-cpi-display/
        # dotenv-at-import-report.md).
        pytest.skip("a real .env is present in this working tree; refusing to touch it")

    baseline = _run_alfred_and_no_edges()

    env_file.write_text(_garbage_env(), encoding="utf-8")
    try:
        with_garbage = _run_alfred_and_no_edges()
    finally:
        env_file.unlink()

    assert baseline == with_garbage, (
        f"results depend on an untracked .env file:\n  no .env:    {baseline}\n  garbage .env: {with_garbage}"
    )


def test_garbage_env_values_never_reach_the_process_environment(tmp_path):
    """Loading a garbage `.env` through the sanctioned wrapper works and is scoped.

    Complements the test above: it shows `load_local_env()` genuinely reads a
    file (so the entrypoint tests are meaningful) while the test process itself
    stays clean.
    """
    from tradehub.core.env import load_local_env

    garbage = tmp_path / ".env"
    garbage.write_text(_garbage_env(), encoding="utf-8")
    for key in ("FRED_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(key, None)

    assert load_local_env(env_file=garbage) is True
    assert os.environ["FRED_API_KEY"] == "not-a-real-key-this-must-not-be-used"
    assert os.environ["SUPABASE_URL"] == "https://garbage.invalid"

    for key in ("FRED_API_KEY", "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(key, None)


def test_load_local_env_does_not_override_the_real_environment(tmp_path):
    """`override=False` is what makes production safe: real variables win."""
    from tradehub.core.env import load_local_env

    env_file = tmp_path / ".env"
    env_file.write_text("SOME_PROBE_VAR=from-file\n", encoding="utf-8")
    os.environ["SOME_PROBE_VAR"] = "from-environment"
    try:
        assert load_local_env(env_file=env_file) is True
        assert os.environ["SOME_PROBE_VAR"] == "from-environment"
    finally:
        os.environ.pop("SOME_PROBE_VAR", None)


def test_table_missing_does_not_match_a_missing_column_of_an_existing_table():
    """CodeRabbit, on #62: `table_missing()` matched any message naming the table plus "does not
    exist" -- which a MISSING COLUMN message also contains. So a `journal_scores` table that exists but
    lacks a queried column was reported as "the table is not there yet", the read fell through to the
    legacy tables, and the API served legacy records as though no forecaster had moved onto the
    journal. That is silent wrong data, not a visible failure."""
    from tradehub.gate_status import table_missing

    missing_table = RuntimeError(
        'Could not find the table \'public.journal_scores\' in the schema cache')
    missing_column = RuntimeError(
        'column journal_scores.forecaster does not exist')

    assert table_missing(missing_table, "journal_scores") is True
    assert table_missing(missing_column, "journal_scores") is False, (
        "a missing COLUMN must not read as a missing TABLE")
    # the table name alone is not enough either: an unrelated error quoting it must not match
    assert table_missing(RuntimeError("permission denied for journal_scores"), "journal_scores") is False


def test_journal_scores_reads_every_page_not_the_first_thousand_rows():
    """CodeRabbit, on #62: Supabase returns at most 1,000 rows by default and this read had no
    `.range()` paging, so `journal_engines(...)` -- which decides WHICH engines are journal-backed --
    was built from a partial set. Any scorecard past the cap was invisible and its engine fell back to
    the legacy tables.

    The client here models PostgREST's default limit, because the fake journal DB does not: without a
    cap this test passes whether or not the read pages, which is exactly how a vacuous test hides.
    """
    from tradehub.journal import legacy

    CAP = 1000
    total = 1200
    rows = [{"forecaster": f"f{i:04d}", "forecaster_version": "v1", "n_settled": 1,
             "gate_status": "SHADOW"} for i in range(total)]

    class Q:
        def __init__(self, lo, hi):
            self.lo, self.hi = lo, hi

        def select(self, *_a):
            return self

        def order(self, *_a):
            return self

        def range(self, lo, hi):
            return Q(lo, hi)

        def execute(self):
            page = rows[self.lo:self.hi + 1]
            return type("R", (), {"data": page})()

    class Capped:
        def table(self, _name):
            # no `.range()` call means the whole table in one request -> capped at CAP
            return Q(0, min(CAP, total) - 1)

    read = legacy.journal_scores(Capped())
    assert len(read) == total, (
        f"read {len(read)} of {total}; every engine past the cap would fall back to the legacy tables")


def test_scorecard_paging_uses_a_total_order_so_a_version_is_never_split_across_pages():
    """CodeRabbit (Major, on #97): `journal_scores` was ordered by `forecaster` alone, which is not a
    total order. Two versions of one forecaster straddling a page boundary have undefined relative
    order, and `select_all` issues a separate `.range()` per page -- so a version could appear TWICE or
    be omitted, and an omitted version then vanishes from `merge_track_record()`.

    `journal_scores` has `PRIMARY KEY (forecaster, forecaster_version)`, so that pair is total. The fake
    models the server: it applies whatever ORDER BY was requested and pages with the SAME page size the
    pager uses, so a boundary lands inside one forecaster's versions. Paging by a page size the pager
    does not use would read one page and prove nothing.
    """
    from tradehub.journal import legacy
    from tradehub.journal.store import PAGE

    rows = [{"forecaster": f, "forecaster_version": v}
            for f in ("a", "b", "c") for v in ("v1", "v2")]     # 6 rows, PAGE is 1000

    class Server:
        """PostgREST: applies the requested ORDER BY, and `.range()` follows that order."""

        def __init__(self):
            self.order: list[str] = []
            self.window = (0, 0)
            self.pages: list[list[tuple[str, str]]] = []

        def read(self, rows):
            ordered = sorted(rows, key=lambda r: tuple(r[k] for k in self.order))
            lo, hi = self.window
            page = ordered[lo:hi + 1]
            self.pages.append([(r["forecaster"], r["forecaster_version"]) for r in page])
            return page

    class Q:
        def __init__(self, server):
            self.server = server

        def select(self, *_a):
            return self

        def order(self, col):
            self.server.order.append(col)
            return self

        def range(self, lo, hi):
            self.server.window = (lo, hi)
            return self

        def execute(self):
            return type("R", (), {"data": self.server.read(rows)})()

    class Store:
        def __init__(self):
            self.server = Server()

        def table(self, _name):
            return Q(self.server)

    # PAGE is 1000 and there are 6 rows, so force the boundary to fall inside `b`'s versions by
    # making the pager's page size small for this test only.
    import tradehub.journal.store as store_mod
    original, store_mod.PAGE = store_mod.PAGE, 4
    try:
        store = Store()
        read = legacy.journal_scores(store)
        pages = store.server.pages
    finally:
        store_mod.PAGE = original

    assert set(store.server.order) == {"forecaster", "forecaster_version"}, (
        f"a one-key order is not total across versions: {store.server.order}")
    assert len(pages) > 1, f"the fixture never paged, so nothing was proven: {pages}"
    pairs = [(r["forecaster"], r["forecaster_version"]) for r in read]
    assert len(pairs) == len(set(pairs)), f"a version was duplicated across pages: {pages}"
    assert len(read) == len(rows), f"lost rows across pages: {pages}"
