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
    without_import = re.sub(r"(?m)^import sys\n", "", text)
    if not re.search(r"\bsys\b", without_import):
        text = without_import
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
