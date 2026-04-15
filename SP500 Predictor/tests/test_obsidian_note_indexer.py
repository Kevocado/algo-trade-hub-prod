from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_indexer_module():
    repo_root = Path(__file__).resolve().parents[2]
    module_path = repo_root / "scripts/index_obsidian_notes.py"
    spec = importlib.util.spec_from_file_location("index_obsidian_notes", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_index_markdown_note_parses_frontmatter(tmp_path):
    module = _load_indexer_module()
    note = tmp_path / "WeatherNote.md"
    note.write_text(
        "---\n"
        "title: Sample Weather Note\n"
        "type: api_spec\n"
        "domain: weather\n"
        "status: active\n"
        "settlement_source: nws\n"
        "tags: [weather, api]\n"
        "summary: Sample summary.\n"
        "---\n\n"
        "# Sample Weather Note\n\n"
        "## Fields\n",
        encoding="utf-8",
    )

    indexed = module.index_markdown_note(note, tmp_path)

    assert indexed.title == "Sample Weather Note"
    assert indexed.domain == "weather"
    assert indexed.note_type == "api_spec"
    assert indexed.settlement_source == "nws"
    assert indexed.tags == ["weather", "api"]
    assert indexed.headings == ["Sample Weather Note", "Fields"]


def test_index_markdown_note_falls_back_without_frontmatter(tmp_path):
    module = _load_indexer_module()
    note = tmp_path / "plain_note.md"
    note.write_text("# Plain Note\n\n## Section\n", encoding="utf-8")

    indexed = module.index_markdown_note(note, tmp_path)

    assert indexed.title == "Plain Note"
    assert indexed.domain == "unknown"
    assert indexed.note_type == "note"
    assert indexed.status == "unclassified"


def test_build_manifest_ignores_generated_index_and_obsidian(tmp_path):
    module = _load_indexer_module()
    (tmp_path / ".obsidian").mkdir()
    (tmp_path / ".obsidian/ignored.md").write_text("# Ignore Me\n", encoding="utf-8")
    (tmp_path / ".agent/index").mkdir(parents=True)
    (tmp_path / ".agent/index/generated.md").write_text("# Generated\n", encoding="utf-8")
    (tmp_path / "Weather").mkdir()
    (tmp_path / "Weather/Note.md").write_text("# Kept Note\n", encoding="utf-8")

    notes = module.build_manifest(tmp_path)

    assert [note.path for note in notes] == ["Weather/Note.md"]


def test_write_manifest_outputs_json_and_markdown(tmp_path):
    module = _load_indexer_module()
    notes = [
        module.IndexedNote(
            path="Weather/Note.md",
            title="Kept Note",
            domain="weather",
            note_type="research",
            status="active",
            settlement_source="nws",
            tags=["weather"],
            summary="Summary",
            headings=["Kept Note"],
            modified_utc="2026-04-09T00:00:00+00:00",
        )
    ]
    module.MANIFEST_JSON = tmp_path / ".agent/index/notes_manifest.json"
    module.MANIFEST_MD = tmp_path / ".agent/index/notes_manifest.md"

    module.write_manifest(notes, tmp_path)

    payload = json.loads(module.MANIFEST_JSON.read_text(encoding="utf-8"))
    markdown = module.MANIFEST_MD.read_text(encoding="utf-8")

    assert payload["notes"][0]["path"] == "Weather/Note.md"
    assert payload["notes"][0]["settlement_source"] == "nws"
    assert "Weather/Note.md" in markdown
