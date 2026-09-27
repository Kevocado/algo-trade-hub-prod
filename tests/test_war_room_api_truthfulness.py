"""The War Room's own API must serve what its pages read, and must not read tables that no
migration creates.

Two defects this pins, both found in the live app on 2026-09-27:

- `/api/positions` and `/api/pnl_summary` queried `paper_trades`, a table no migration has ever
  created (its only definition is `research/legacy/supabase_setup.sql`) and that nothing in the
  codebase writes. Live: HTTP 500, `PGRST205`. The product is suggest-only, so there is no writer
  because there should not be one -- an empty portfolio dressed as a broken query is the worst of
  both. These now answer honestly instead of raising.
- `/api/shadow-performance` needs `signal_events`, which `20260415090000_signal_events_unification.sql`
  creates by renaming `crypto_signal_events`. The code is right and the database is behind, so the
  error has to SAY that rather than forward a raw PostgREST dump.

And one guard, because both are the same mistake: a name passed to `supabase.table(...)` that no
migration creates. `test_no_code_references_a_table_no_migration_creates` fails the build instead of
production.
"""
from pathlib import Path

import asyncio

import pytest
from fastapi import FastAPI, HTTPException

from tradehub.api import main as api_main

MIGRATIONS = Path(__file__).resolve().parents[1] / "market_sentiment_tool" / "supabase" / "migrations"


class _Query:
    """The smallest supabase-py chain the API uses: .select().eq() and friends return self."""

    def __init__(self, rows, recorder=None, table=None):
        self.rows = rows
        self.recorder = recorder
        self.table = table

    def select(self, *args):
        return self

    def eq(self, *args):
        return self

    def order(self, *args):
        return self

    def limit(self, *args):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Client:
    """Records every table name it is asked for, once each, and fails on a table the schema lacks —
    the same PGRST205 the live API returned."""

    def __init__(self, tables, rows=None):
        self.tables = tables
        self.rows = rows or {}
        self.queried = []

    def table(self, name):
        if name not in self.tables:
            raise RuntimeError(f"Could not find the table 'public.{name}' in the schema cache")
        self.queried.append(name)
        return _Query(self.rows.get(name, []))


def _client(rows=None, tables=None):
    return _Client(tables if tables is not None else ["kalshi_portfolio", "kalshi_edges"], rows)


def _app():
    app = FastAPI()
    for route in api_main.app.routes:
        if getattr(route, "path", "").startswith(("/api/positions", "/api/pnl_summary", "/api/shadow-performance")):
            app.router.routes.append(route)
    return app


# ── the portfolio endpoints answer instead of raising ──────────────────────────


def test_positions_answers_an_empty_list_and_names_the_table_it_read():
    """No `paper_trades` in any migration, and nothing writes it. A 500 here is what put a red
    'unavailable' on the War Room; the honest answer for a suggest-only product is an empty list."""
    client = _client(tables=["paper_trades"])
    positions = asyncio.run(api_main.get_positions(engine=None, supabase=client))

    assert positions == []
    assert client.queried == ["paper_trades"], "the endpoint should still read the ledger when it exists"


def test_pnl_summary_reports_zeroes_rather_than_raising():
    client = _client(tables=["paper_trades"])
    summary = asyncio.run(api_main.get_pnl_summary(supabase=client))

    assert summary.total_paper_trades == 0
    assert summary.total_pnl_cents == 0.0
    assert summary.win_rate_pct == 0.0


def test_the_pnl_response_says_the_product_places_no_orders():
    """A `total_pnl_cents: 0` reads as 'you are flat'. This product never places an order, so the
    response has to say which of those it is."""
    client = _client(tables=["paper_trades"])
    body = asyncio.run(api_main.get_pnl_summary(supabase=client))

    assert body.suggest_only is True, body


@pytest.mark.parametrize("call", [
    lambda c: api_main.get_positions(engine=None, supabase=c),
    lambda c: api_main.get_pnl_summary(supabase=c),
])
def test_a_ledger_that_is_not_in_the_database_fails_loudly_and_says_which_migration(call):
    """Not silence. An empty position list reads as "you are flat", which is a different and wrong
    claim; a 503 that names the migration is the truth plus the fix."""
    client = _client(tables=["kalshi_portfolio"])   # paper_trades deliberately ABSENT

    with pytest.raises(HTTPException) as caught:
        asyncio.run(call(client))

    assert caught.value.status_code == 503
    assert "20260416000011_war_room_tables.sql" in str(caught.value.detail)


def test_the_shadow_performance_error_says_which_migration_is_missing(monkeypatch):
    """A raw PostgREST dump is not actionable. This failure is fixed by APPLYING a migration, not by
    editing code, so the response has to say which one -- otherwise the next person to see a red
    /shadow has to reverse-engineer it."""
    def boom(**_kwargs):
        raise RuntimeError("Could not find the table 'public.signal_events' in the schema cache")

    monkeypatch.setattr(api_main, "build_shadow_timeline_response", boom)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(api_main.get_shadow_performance(domain="crypto", hours=24))

    detail = str(caught.value.detail)
    assert "20260415090000_signal_events_unification.sql" in detail, detail
    assert "crypto_signal_events" in detail, detail


# ── the guard that stops this whole class ─────────────────────────────────────


def _tables_created_by_migrations() -> set[str]:
    import re

    created = set()
    pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:public\.)?\"?(\w+)\"?", re.I)
    for path in sorted(MIGRATIONS.glob("*.sql")):
        for match in pattern.finditer(path.read_text(encoding="utf-8")):
            created.add(match.group(1).lower())
        # A rename creates the new name too: `ALTER TABLE x RENAME TO y`.
        for match in re.finditer(r"RENAME\s+TO\s+\"?(\w+)\"?", path.read_text(encoding="utf-8"), re.I):
            created.add(match.group(1).lower())
    return created


def _tables_referenced_in_code() -> set[str]:
    import re

    root = Path(__file__).resolve().parents[1] / "tradehub"
    referenced = set()
    for path in root.rglob("*.py"):
        for match in re.finditer(r"""\.table\(\s*["'](\w+)["']""", path.read_text(encoding="utf-8")):
            referenced.add(match.group(1).lower())
    return referenced


def test_the_migration_scanner_finds_the_tables_it_should():
    created = _tables_created_by_migrations()
    assert {"trades", "kalshi_edges", "signal_events", "jobs_scorecard", "backtest_runs"} <= created, sorted(created)


def test_no_code_references_a_table_no_migration_creates():
    """The guard. `paper_trades` reached production through a legacy research file; this is the test
    that would have stopped it."""
    created = _tables_created_by_migrations()
    referenced = _tables_referenced_in_code()
    missing = sorted(referenced - created)

    assert not missing, (
        "these names are passed to supabase.table(...) but no migration creates them: "
        f"{missing}. Either add a migration or stop querying them."
    )
