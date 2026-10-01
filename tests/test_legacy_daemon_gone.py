"""Guards for deleting the legacy daemon and its engines (v2 spec §9): what is gone stays gone."""

import ast
from pathlib import Path

from tradehub import engine_health as health

ROOT = Path(__file__).resolve().parents[1]
DELETED = (
    "tradehub/scripts/background_scanner.py",
    "tradehub/engines/macro_engine.py",
    "tradehub/engines/quant_engine.py",
    "tradehub/core/discord_notifier.py",
)
DELETED_MODULES = {p[:-3].replace("/", ".") for p in DELETED}


def test_the_deleted_files_do_not_exist():
    assert [p for p in DELETED if (ROOT / p).exists()] == []


def test_nothing_imports_a_deleted_module():
    offenders = []
    for path in (ROOT / "tradehub").rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] + [f"{node.module}.{a.name}" for a in node.names]
                if isinstance(node, ast.ImportFrom) else [])
            hit = DELETED_MODULES.intersection(names)
            if hit:
                offenders.append(f"{path.relative_to(ROOT)}: {sorted(hit)}")
    assert not offenders, offenders


def test_the_live_ruling_has_no_macro_site_and_no_wired_site():
    """No scanner is wired to a ruled-against engine any more, so every board reads `ran`, truthfully.

    The state machine (`quarantined`, `could_not_run`) is still code and is still tested, against the
    frozen pre-deletion ruling in `tests/legacy_ruling.py`.
    """
    assert "MacroEngine" not in {s.name for s in health.STOPPED_SITES}
    assert health.WIRED_STOPPED_SITES == ()
    assert {health.edge_type_state(edge_type) for edge_type, _ in health.EDGE_TYPES} == {health.STATE_RAN}
