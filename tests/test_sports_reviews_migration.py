from pathlib import Path

MIGRATION = Path(__file__).resolve().parents[1] / (
    "market_sentiment_tool/supabase/migrations/20260416000008_sports_reviews.sql"
)


def test_sports_reviews_migration():
    sql = MIGRATION.read_text()
    assert "CREATE TABLE IF NOT EXISTS sports_reviews" in sql
    for column in ("cache_key", "market_ticker", "side", "price_bucket", "entry_price", "our_prob", "model",
                   "status", "explainable", "drivers", "red_flags", "created_at"):
        assert column in sql
    assert "CHECK (status IN ('ok', 'invalid', 'error'))" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "FOR SELECT" in sql and "FOR ALL" not in sql      # writes come only from the service-role scan
    assert "sports_reviews_cache_key_idx" in sql and "sports_reviews_created_at_idx" in sql
