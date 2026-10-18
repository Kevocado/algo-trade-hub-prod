"""Every migration file must be recorded in docs/superpowers/plans/migrations-applied.md.

A migration and the code that reads it ship in one PR but are applied at different times by different
people. The journal store is the proof this is not a formality: `freeze()` and `upsert_score()` both
carry fallbacks for columns added by migrations `20260428000018` and `20260428000020`, because PostgREST
rejects the *whole* write when it names an unknown column -- so applying a migration late makes the
journal record nothing while every scorecard keeps its last value, and nothing looks broken.

This test is the human checkpoint. It fails when a PR adds a migration nobody recorded, so applying one
is a dated, deliberate act rather than an assumption. It also fails when the record names a file that no
longer exists, so a renamed migration cannot leave a stale entry behind that silently widens the guard.
"""
from __future__ import annotations

import re
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "supabase" / "migrations"
RECORD = Path(__file__).resolve().parents[1] / "docs" / "superpowers" / "plans" / "migrations-applied.md"

# Supabase migration filenames are `<timestamp>_<slug>.sql`; the timestamp orders them.
NAME_RE = re.compile(r"^(\d{14})_[A-Za-z0-9_-]+\.sql$")


def _migration_files() -> list[str]:
    return sorted(p.name for p in MIGRATIONS_DIR.glob("*.sql"))


def _recorded_names(text: str) -> list[str]:
    """Migration filenames named in the record, in the order they appear.

    Only names shaped like a migration filename count, so a path or glob mentioned in the prose
    (`.../migrations/*.sql`) is not mistaken for an entry.
    """
    seen: list[str] = []
    for name in re.findall(r"`([^`]+\.sql)`", text):
        if NAME_RE.match(name) and name not in seen:
            seen.append(name)
    return seen


def _watermark(text: str) -> str | None:
    m = re.search(r"\*\*Watermark:\s*`([^`]+\.sql)`\*\*", text)
    return m.group(1) if m else None


def test_the_record_file_exists():
    assert RECORD.is_file(), f"{RECORD} is missing; a human must record every applied migration"


def test_every_migration_file_is_recorded_as_applied():
    recorded = set(_recorded_names(RECORD.read_text()))
    unrecorded = [name for name in _migration_files() if name not in recorded]
    assert not unrecorded, (
        f"Migration file(s) not recorded in {RECORD.name}: {unrecorded}. Apply the migration, add a row "
        "to the table, and update the watermark. Do not skip this -- the journal writes silently break."
    )


def test_the_record_names_no_migration_that_does_not_exist():
    """A stale entry is as bad as a missing one: it widens the guard's watermark past the truth."""
    on_disk = set(_migration_files())
    phantom = [name for name in _recorded_names(RECORD.read_text()) if name not in on_disk]
    assert not phantom, f"{RECORD.name} records migration(s) that are not on disk: {phantom}"


def test_the_watermark_is_the_newest_migration():
    """The recorded newest migration must be the newest file, in timestamp order."""
    files = _migration_files()
    watermark = _watermark(RECORD.read_text())
    assert watermark is not None, f"{RECORD.name} has no '**Watermark:** `file.sql`' line"
    newest = max(files, key=lambda name: NAME_RE.match(name).group(1))
    assert watermark == newest, (
        f"Watermark is {watermark} but the newest migration on disk is {newest}. Update the watermark "
        "when you record a migration."
    )


def test_migration_filenames_are_well_formed():
    """Every filename must be `<14-digit-timestamp>_<slug>.sql`.

    This checks FORMAT, deliberately not ordering, and the name used to claim otherwise. Ordering
    cannot drift from the timestamps anyway: the watermark is computed as
    `max(files, key=lambda name: NAME_RE.match(name).group(1))`, so "newest" is the largest
    timestamp no matter what order `glob` returned. Format is what actually matters, because that
    same `max()` calls `NAME_RE.match(name).group(1)` on every file: one migration named without a
    14-digit prefix turns this guard into an `AttributeError` on None, which reads as a crash in
    the test rather than as the naming mistake it is.
    """
    for name in _migration_files():
        assert NAME_RE.match(name), f"{name} does not match <14-digit-timestamp>_<slug>.sql"
