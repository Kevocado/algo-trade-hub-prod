"""No Azure references anywhere in the live tree. Production runs only on the VPS.

Azure Container Apps was retired in favour of the VPS stack (2026-09-24). Leaving the references
behind is not untidy, it is actively misleading in two ways that have already cost time:

- `tradehub/config/engines.yaml` defaulted `sports_sources` at `*.azurecontainerapps.io` hostnames
  that now 404, so a sports feed pointed at a service that does not exist. The defaults are now the
  VPS service names (`http://nfl:8001`, `http://cfb:8003`).
- `shared/config.py` read an `AZURE_CONNECTION_STRING` nothing consumed, and `research/legacy/`
  imported an `azure_logger` that is gone.

This test is the ratchet. `tests/test_repo_layout.py` already pins that the DEPLOY WORKFLOW carries no
Azure reference; that assertion stays where it is and is not duplicated here. This one covers the
source tree, so the next person who pastes an old Azure default back in fails their own PR.

Scan scope is exactly the live tree -- `tradehub/`, `shared/`, `tests/` (excluding this file),
`.github/`, and `market_sentiment_tool/src/`. History (`archive/`, `docs/superpowers/{reports,specs,
plans}/`) is deliberately outside it: those are records of what was true when written, and rewriting
them would be falsifying history rather than cleaning a tree.
"""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The live tree. `docs/superpowers/{reports,specs,plans}`, `archive/`, `research/` and `.agent/` are
# history or notes about history and are not production code.
SCAN_DIRS = ("tradehub", "shared", ".github", "market_sentiment_tool/src")
SCAN_TESTS = "tests"
FORBIDDEN = ("azure", "containerapp", "AZURE_")

# Two files are exempt, both because they are the guards themselves and must name the strings they
# ban: this one, and `tests/test_repo_layout.py`, whose assertion that the deploy workflow references
# no Azure is Kevin's ruling and stays where it is. Nothing else is exempt.
EXEMPT = {Path(__file__).name, "test_repo_layout.py"}

# Text-ish files only; a binary that happens to contain the bytes is not a reference to Azure.
SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml", ".json", ".toml", ".cfg",
            ".ini", ".sh", ".md", ".txt", ".env", ".sql", ".css", ".html"}
SKIP_DIR_PARTS = {"node_modules", "__pycache__", ".git", "dist", ".venv", "build", ".ruff_cache",
                  ".pytest_cache"}


def _files() -> list[Path]:
    out: list[Path] = []
    for rel in SCAN_DIRS:
        root = REPO / rel
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.is_dir() or path.suffix.lower() not in SUFFIXES:
                continue
            if SKIP_DIR_PARTS & set(path.parts):
                continue
            out.append(path)
    tests = REPO / SCAN_TESTS
    for path in tests.rglob("*"):
        if path.is_dir() or path.suffix.lower() not in SUFFIXES:
            continue
        if SKIP_DIR_PARTS & set(path.parts):
            continue
        out.append(path)
    return out


def _hits(path: Path, needle: str) -> list[tuple[int, str]]:
    """Every line mentioning `needle`, case-insensitively. Returns (line number, text)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lowered = needle.lower()
    return [
        (n, line.strip()[:160])
        for n, line in enumerate(text.splitlines(), 1)
        if lowered in line.lower()
    ]


def test_the_scan_covers_a_real_tree_and_the_workflow_directory():
    """A guard that silently scans nothing passes forever. Pin that it finds files at all."""
    files = _files()
    assert len(files) > 50, f"scan found only {len(files)} files; the scope is wrong"
    assert any(f.suffix == ".py" for f in files), "no Python scanned"
    assert (REPO / ".github").is_dir(), ".github/ missing; the deploy workflow must stay in scope"


def test_no_azure_references_in_the_live_tree():
    """The ratchet: any Azure string in production code, tests, or the workflows fails this PR."""
    offenders: list[str] = []
    for path in _files():
        # The guards name the strings they ban; see EXEMPT.
        if path.name in EXEMPT:
            continue
        for needle in FORBIDDEN:
            for lineno, line in _hits(path, needle):
                offenders.append(f"{path.relative_to(REPO)}:{lineno}: {line}")
    assert not offenders, (
        "Azure references found in the live tree. Production runs on the VPS only; remove them "
        "(or, if this is history under archive/ or docs/superpowers, leave it -- it is out of scope "
        "by design):\n  " + "\n  ".join(offenders)
    )


def test_the_workflow_assertion_in_repo_layout_is_still_there():
    """`tests/test_repo_layout.py` pins the deploy workflow separately. That ruling is Kevin's and it
    stays where it is; this test guards the source tree, not the workflow, and must not absorb it."""
    text = (REPO / "tests" / "test_repo_layout.py").read_text(encoding="utf-8")
    assert "az login" in text and "containerapp" in text and "AZURE_" in text, (
        "test_repo_layout.py must keep its own assertion that workflows reference no Azure"
    )
