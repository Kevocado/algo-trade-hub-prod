"""The journal's freeze and immutability guarantees, run against a real Postgres.

These are the spec's load-bearing claims (v2 §3-§4), and they live in database triggers, so a fake
client cannot prove them. Each test runs SQL through `psql` inside a throwaway `postgres:16-alpine`
container. When Docker is unavailable the module is skipped, loudly; CI and the pre-push checklist
must run it with Docker.
"""
from __future__ import annotations

import shutil
import subprocess
import time
import uuid
from pathlib import Path

import pytest

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260428000014_prediction_journal.sql"
)
COSTS_MIGRATION = MIGRATION.with_name("20260428000015_journal_costs.sql")
# The paired Brier the hero's ratio needs, plus the migration that validates its constraints. Applied
# here because a fake client cannot show that the CHECKs are named, NOT VALID, and idempotent -- and
# because an inline CHECK on ADD COLUMN would scan a non-empty table under ACCESS EXCLUSIVE.
PAIRED_MIGRATION = MIGRATION.with_name("20260428000020_journal_scores_paired_brier.sql")
PAIRED_VALIDATE_MIGRATION = MIGRATION.with_name("20260428000021_journal_scores_paired_brier_validate.sql")


def _docker_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    return subprocess.run(["docker", "info"], capture_output=True).returncode == 0  # noqa: PLW1510


pytestmark = pytest.mark.skipif(not _docker_ok(), reason="needs Docker for a throwaway postgres:16 (journal triggers)")


@pytest.fixture(scope="module")
def pg():
    name = f"journal-pg-{uuid.uuid4().hex[:8]}"
    subprocess.run(["docker", "run", "-d", "--name", name, "-e", "POSTGRES_PASSWORD=x", "postgres:16-alpine"],
                   check=True, capture_output=True)
    try:
        for _ in range(60):
            if subprocess.run(["docker", "exec", name, "pg_isready", "-U", "postgres"], capture_output=True).returncode == 0:  # noqa: PLW1510
                break
            time.sleep(0.5)
        time.sleep(1.0)

        def run(sql: str) -> subprocess.CompletedProcess:
            return subprocess.run(["docker", "exec", "-i", name, "psql", "-q", "-v", "ON_ERROR_STOP=1", "-U", "postgres",  # noqa: PLW1510
                                   "-tA"], input=sql, text=True, capture_output=True)

        # Supabase has these roles; a plain postgres does not.
        assert run("CREATE ROLE anon; CREATE ROLE authenticated;").returncode == 0
        for _ in range(2):  # applied twice: the migrations must be idempotent
            for migration in (MIGRATION, COSTS_MIGRATION, PAIRED_MIGRATION, PAIRED_VALIDATE_MIGRATION):
                applied = run(migration.read_text(encoding="utf-8"))
                assert applied.returncode == 0, applied.stderr
        yield run
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)  # noqa: PLW1510


def _calendar(run, target: str, seconds: float) -> None:
    out = run(f"INSERT INTO journal_calendars (target, family, cadence, cutoff_at) "
              f"VALUES ('{target}', 'test', 'daily', now() + interval '{seconds} seconds');")
    assert out.returncode == 0, out.stderr


def test_a_freeze_before_the_cutoff_is_accepted_and_frozen_at_is_server_time(pg):
    _calendar(pg, "t:ok", 60)
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash, frozen_at) "
             "VALUES ('f', 'v1', 't:ok', 0.6, 'h', '2000-01-01T00:00:00Z') RETURNING frozen_at > now() - interval '1 minute';")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[0] == "t"  # the client's 2000-01-01 was ignored


def test_a_freeze_after_the_cutoff_is_refused(pg):
    _calendar(pg, "t:late", 1)
    time.sleep(2.0)
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
             "VALUES ('f', 'v1', 't:late', 0.6, 'h');")
    assert out.returncode != 0
    assert "cutoff" in out.stderr and "has passed" in out.stderr


def test_a_freeze_for_a_target_without_a_calendar_row_is_refused(pg):
    out = pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
             "VALUES ('f', 'v1', 't:unknown', 0.6, 'h');")
    assert out.returncode != 0
    assert "no calendar row" in out.stderr


def test_a_calendar_row_cannot_be_created_in_the_past_or_changed(pg):
    past = pg("INSERT INTO journal_calendars (target, family, cadence, cutoff_at) "
              "VALUES ('t:past', 'test', 'daily', now() - interval '1 second');")
    assert past.returncode != 0 and "not in the future" in past.stderr
    _calendar(pg, "t:cal", 60)
    moved = pg("UPDATE journal_calendars SET cutoff_at = cutoff_at + interval '1 day' WHERE target = 't:cal';")
    assert moved.returncode != 0 and "immutable" in moved.stderr


def test_forecasts_cannot_be_updated_or_deleted_but_rebuilt_can_flip_on(pg):
    _calendar(pg, "t:imm", 60)
    assert pg("INSERT INTO journal_forecasts (forecaster, forecaster_version, target, probability, source_hash) "
              "VALUES ('f', 'v1', 't:imm', 0.6, 'h');").returncode == 0
    changed = pg("UPDATE journal_forecasts SET probability = 0.9 WHERE target = 't:imm';")
    assert changed.returncode != 0 and "immutable" in changed.stderr
    sneaky = pg("UPDATE journal_forecasts SET rebuilt = true, probability = 0.9 WHERE target = 't:imm';")
    assert sneaky.returncode != 0
    deleted = pg("DELETE FROM journal_forecasts WHERE target = 't:imm';")
    assert deleted.returncode != 0 and "immutable" in deleted.stderr
    flipped = pg("UPDATE journal_forecasts SET rebuilt = true WHERE target = 't:imm' RETURNING rebuilt;")
    assert flipped.returncode == 0 and flipped.stdout.strip().splitlines()[0] == "t"
    back = pg("UPDATE journal_forecasts SET rebuilt = false WHERE target = 't:imm';")
    assert back.returncode != 0


def test_a_settlement_is_refused_before_the_cutoff_and_immutable_after(pg):
    _calendar(pg, "t:set", 1)
    early = pg("INSERT INTO journal_settlements (target, outcome, source) VALUES ('t:set', 1, 'test');")
    assert early.returncode != 0 and "before its cutoff" in early.stderr
    time.sleep(2.0)
    assert pg("INSERT INTO journal_settlements (target, outcome, source) VALUES ('t:set', 1, 'test');").returncode == 0
    changed = pg("UPDATE journal_settlements SET outcome = 0 WHERE target = 't:set';")
    assert changed.returncode != 0 and "immutable" in changed.stderr


def test_truncate_is_refused_even_for_the_owner(pg):
    for table in ("journal_forecasts", "journal_settlements", "journal_calendars"):
        out = pg(f"TRUNCATE {table} CASCADE;")
        assert out.returncode != 0 and "TRUNCATE" in out.stderr, table


def test_clients_have_no_write_privilege(pg):
    out = pg("SELECT count(*) FROM information_schema.role_table_grants WHERE grantee IN ('anon','authenticated') "
             "AND table_name LIKE 'journal_%' AND privilege_type IN ('INSERT','UPDATE','DELETE','TRUNCATE');")
    assert out.returncode == 0 and out.stdout.strip() == "0"


def test_the_costs_column_exists_and_defaults_to_an_empty_object(pg):
    out = pg("INSERT INTO journal_scores (forecaster, forecaster_version, cadence, baseline) "
             "VALUES ('c', 'v1', 'daily', 'none'); SELECT costs::text FROM journal_scores WHERE forecaster = 'c';")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "{}"


def test_the_paired_brier_columns_are_nullable_and_default_to_null(pg):
    """Rows scored before 20260428000020 carry NULL in both. They are not backfilled, and NULL is what
    `market_skill()` reads to decide the hero has nothing to pool -- so the default MUST stay NULL and
    must not be a zero, which would publish a fabricated 1.00 skill."""
    out = pg("INSERT INTO journal_scores (forecaster, forecaster_version, cadence, baseline) "
             "VALUES ('legacy', 'v1', 'daily', 'market'); "
             "SELECT coalesce((SELECT brier_on_baseline::text FROM journal_scores WHERE forecaster = 'legacy'), "
             "'NULL') || '/' || "
             "coalesce((SELECT n_baseline::text FROM journal_scores WHERE forecaster = 'legacy'), 'NULL');")
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip().splitlines()[-1] == "NULL/NULL"


def test_a_paired_brier_is_only_stored_alongside_a_paired_count(pg):
    """Both columns are independent in the schema, so the invariant `market_skill()` depends on -- a
    numerator and a count that came from the same subset -- is checked here, in the database."""
    good = pg("INSERT INTO journal_scores (forecaster, forecaster_version, cadence, baseline, n_settled, "
              "brier, brier_baseline, brier_on_baseline, n_baseline) VALUES "
              "('paired', 'v1', 'daily', 'market', 400, 0.61, 0.04, 0.01, 100);")
    assert good.returncode == 0, good.stderr

    def refused(**extra) -> bool:
        cols = ", ".join(f"{k} = {v}" for k, v in extra.items())
        out = pg(f"UPDATE journal_scores SET {cols} WHERE forecaster = 'paired';")
        return out.returncode != 0

    assert refused(n_baseline=-1), "a negative matched count was accepted"
    assert refused(brier_on_baseline=-0.01), "a negative Brier (a squared error) was accepted"
    assert refused(n_settled=10, n_baseline=100), (
        "a matched count larger than the card's settled set was accepted: that is the invariant the "
        "headline's ratio was reading past")
    # A real card's shape passes, and the subset count can never exceed the settled one.
    assert pg("UPDATE journal_scores SET n_settled = 400, n_baseline = 400 WHERE forecaster = 'paired';").returncode == 0


def test_the_paired_brier_constraints_are_named_and_deferred_then_validated(pg):
    """An inline `CHECK` on `ADD COLUMN` holds ACCESS EXCLUSIVE for the length of a full-table scan,
    which blocks the hourly journal's reads AND writes. A named NOT VALID constraint records under a
    brief lock and skips the scan; 20260428000021 then validates it under SHARE UPDATE EXCLUSIVE.

    `convalidated` is the only observable difference between the two, so it is asserted directly:
    re-running 00020 re-adds the constraints NOT VALID, and only the follow-up flips them to true.

    Concatenated into text, a boolean renders as `true`/`false`, NOT as psql's own `t`/`f` -- which is
    how an assertion comparing against "t" passes vacuously on a table full of "false".
    """
    def convalidated() -> dict[str, str]:
        out = pg("SELECT conname || '=' || convalidated FROM pg_constraint "
                 "WHERE conrelid = 'journal_scores'::regclass AND conname LIKE 'journal_scores_%';")
        assert out.returncode == 0, out.stderr
        assert all("=" in line for line in out.stdout.strip().splitlines()), out.stdout
        return dict(line.split("=", 1) for line in out.stdout.strip().splitlines())

    expected = {"journal_scores_brier_on_baseline_nonneg", "journal_scores_n_baseline_nonneg",
                "journal_scores_n_baseline_within_settled"}

    applied = convalidated()
    assert expected <= set(applied), f"unnamed or missing paired-Brier constraints: {sorted(applied)}"
    assert applied["journal_scores_n_baseline_nonneg"] == "true", (
        f"constraints left NOT VALID enforce nothing for existing rows: {applied}")
    assert all(applied[name] == "true" for name in expected), applied

    # The fixture applied 00020 BEFORE 00021, so both states are already recorded in the pair. Prove it
    # rather than trusting the SQL text: re-run 00020 alone and the constraint must go back to NOT VALID.
    assert pg(PAIRED_MIGRATION.read_text(encoding="utf-8")).returncode == 0
    deferred = convalidated()
    assert all(deferred[name] == "false" for name in expected), (
        f"00020 does not defer the scan -- it validated inline: {deferred}")
    assert pg(PAIRED_VALIDATE_MIGRATION.read_text(encoding="utf-8")).returncode == 0
    assert all(convalidated()[name] == "true" for name in expected)
