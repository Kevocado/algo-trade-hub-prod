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
        for _ in range(2):  # applied twice: the migration must be idempotent
            applied = run(MIGRATION.read_text(encoding="utf-8"))
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
