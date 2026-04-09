from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_JSON = REPO_ROOT / ".agent/index/notes_manifest.json"
MANIFEST_MD = REPO_ROOT / ".agent/index/notes_manifest.md"
IGNORED_PARTS = {
    ".git",
    ".obsidian",
    ".agent/index",
    "__pycache__",
    ".pytest_cache",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
}
REQUIRED_KEYS = ("title", "type", "domain", "status", "tags", "summary")


@dataclass
class IndexedNote:
    path: str
    title: str
    domain: str
    note_type: str
    status: str
    tags: list[str]
    summary: str
    headings: list[str]
    modified_utc: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "domain": self.domain,
            "type": self.note_type,
            "status": self.status,
            "tags": self.tags,
            "summary": self.summary,
            "headings": self.headings,
            "modified_utc": self.modified_utc,
        }


def _is_ignored(path: Path) -> bool:
    path_str = str(path)
    if ".agent/index" in path_str:
        return True
    return any(part in IGNORED_PARTS for part in path.parts)


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    parts = text.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, text
    raw_frontmatter = parts[0][4:]
    body = parts[1]
    parsed = yaml.safe_load(raw_frontmatter) or {}
    if not isinstance(parsed, dict):
        parsed = {}
    return parsed, body


def _extract_title(body: str, fallback: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return fallback


def _extract_headings(body: str, limit: int = 8) -> list[str]:
    headings: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("# ") or stripped.startswith("## "):
            headings.append(stripped.lstrip("#").strip())
        if len(headings) >= limit:
            break
    return headings


def _normalize_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def index_markdown_note(path: Path, repo_root: Path) -> IndexedNote:
    text = path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(text)
    fallback_title = path.stem.replace("_", " ").replace("-", " ").strip() or path.name
    title = str(frontmatter.get("title") or _extract_title(body, fallback_title))
    note_type = str(frontmatter.get("type") or "note")
    domain = str(frontmatter.get("domain") or "unknown")
    status = str(frontmatter.get("status") or "unclassified")
    tags = _normalize_tags(frontmatter.get("tags"))
    summary = str(frontmatter.get("summary") or "").strip()
    if not summary:
        summary = f"Indexed note at {path.relative_to(repo_root)}."
    modified_utc = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat()
    return IndexedNote(
        path=str(path.relative_to(repo_root)),
        title=title,
        domain=domain,
        note_type=note_type,
        status=status,
        tags=tags,
        summary=summary,
        headings=_extract_headings(body),
        modified_utc=modified_utc,
    )


def build_manifest(repo_root: Path = REPO_ROOT) -> list[IndexedNote]:
    notes: list[IndexedNote] = []
    for path in sorted(repo_root.rglob("*.md")):
        if _is_ignored(path):
            continue
        notes.append(index_markdown_note(path, repo_root))
    return notes


def write_manifest(notes: list[IndexedNote], repo_root: Path = REPO_ROOT) -> None:
    MANIFEST_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "vault_root": str(repo_root),
        "required_frontmatter_keys": list(REQUIRED_KEYS),
        "notes": [note.as_dict() for note in notes],
    }
    MANIFEST_JSON.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# Notes Manifest",
        "",
        f"Generated: {payload['generated_at_utc']}",
        f"Vault Root: `{repo_root}`",
        "",
        "| Path | Domain | Type | Status | Title | Tags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for note in notes:
        tags = ", ".join(note.tags)
        lines.append(
            f"| `{note.path}` | {note.domain} | {note.note_type} | {note.status} | {note.title} | {tags} |"
        )
    MANIFEST_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    notes = build_manifest(REPO_ROOT)
    write_manifest(notes, REPO_ROOT)
    print(f"Indexed {len(notes)} markdown notes into {MANIFEST_JSON} and {MANIFEST_MD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
