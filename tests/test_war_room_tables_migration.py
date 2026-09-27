"""The five War Room tables are backend-only, so they get no client policy at all.

Review finding on 2026-09-27, and it was a real one. The migration created

    CREATE POLICY <table>_owner_all ON <table> FOR ALL TO authenticated
        USING (auth.uid() IS NOT NULL) WITH CHECK (auth.uid() IS NOT NULL)

`auth.uid() IS NOT NULL` is true for *any* signed-in user, so that policy let every authenticated
client insert, update and delete all five tables. The project's rule is that clients are read-only at
most, and this was a write grant wearing a row-level-security costume.

The fix follows `news_embeddings` in `20260416000010_rls_portfolio_news.sql`: enable RLS and create
no client policy, which leaves the service role -- the only thing that bypasses RLS -- able to do
anything. The War Room now reads all of this through the API, so no client grant is needed either.
"""
from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000011_war_room_tables.sql"
)

TABLES = ("live_opportunities", "paper_signals", "trade_history", "scanner_runs", "paper_trades")


def _sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _statements() -> str:
    """The migration with `--` comment lines removed.

    The migration's comments quote the bad policy in full, because explaining what went wrong is worth
    more than brevity. A test that matched those words would therefore be defeated by editing a
    comment, so the assertions below run against executable SQL only.
    """
    lines = [line for line in _sql().splitlines() if not line.lstrip().startswith("--")]
    # Collapse runs of spaces too, so aligning the SQL for readability cannot break an assertion.
    return "\n".join(" ".join(line.split()) for line in lines)


def test_it_creates_the_five_tables():
    sql = _sql()
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table}" in sql, table


def test_row_level_security_is_enabled_on_all_five():
    statements = _statements()
    for table in TABLES:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements, table


def test_no_table_gets_a_for_all_policy():
    """The regression. `FOR ALL TO authenticated USING (auth.uid() IS NOT NULL)` allowed any
    signed-in client to insert, update and delete -- the opposite of read-only-at-most."""
    assert "FOR ALL" not in _statements(), (
        "a FOR ALL policy on these tables is a client write grant; they are backend-only"
    )


def test_no_client_write_grant_of_any_shape():
    """Covers the shapes a `FOR ALL` check would miss: an INSERT/UPDATE/DELETE policy aimed at
    anon or authenticated, whether spelled as `FOR INSERT` or per-command."""
    statements = _statements()
    for grant in ("TO authenticated", "TO anon", "FOR INSERT", "FOR UPDATE", "FOR DELETE",
                  "WITH CHECK", "CREATE POLICY"):
        assert grant not in statements, f"client write grant found: {grant}"


def test_the_migration_is_still_idempotent_and_drops_the_old_policy_name():
    """Re-running must be safe, and a database where the old policy was already applied must have it
    removed -- otherwise fixing the grant would leave the write policy in place."""
    statements = _statements()
    assert "DROP POLICY IF EXISTS" in statements
    # The old name is dropped per table, so a re-run cannot leave `_owner_all` behind on a database
    # where the write grant was already applied.
    for table in TABLES:
        assert f'DROP POLICY IF EXISTS "{table}_owner_all" ON {table}' in statements, table
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in statements, table
