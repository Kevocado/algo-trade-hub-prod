from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000007_predictions_hardening.sql"
)


def test_hardening_migration_covers_step_2b():
    sql = MIGRATION.read_text(encoding="utf-8")
    for needle in (
        "ADD COLUMN IF NOT EXISTS settlement_payload jsonb",
        "ADD COLUMN IF NOT EXISTS settled_at timestamptz",
        "CHECK (status <> 'SETTLED' OR result IS NOT NULL)",
        "PRIMARY KEY (engine, engine_version)",
        'CREATE POLICY "predictions_owner_read" ON predictions FOR SELECT',
        'CREATE POLICY "track_record_owner_read" ON track_record FOR SELECT',
    ):
        assert needle in sql, needle
    assert "FOR ALL" not in sql, "clients must not get write policies"
