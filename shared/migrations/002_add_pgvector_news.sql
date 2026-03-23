-- ============================================================
-- Migration 002: Enable pgvector & create news_embeddings table
-- Replaces local ChromaDB. Target: wuhpbvgidnrrdndhkehl
-- Run this ONCE in the Supabase SQL Editor.
-- ============================================================

-- Enable the pgvector extension (Supabase supports this natively)
CREATE EXTENSION IF NOT EXISTS vector;

-- News embeddings table
-- The embedding column stores 384-dimensional vectors produced by
-- the all-MiniLM-L6-v2 sentence-transformer (same model used by ChromaDB).
CREATE TABLE IF NOT EXISTS news_embeddings (
  id          text PRIMARY KEY,           -- e.g. "AAPL_<article_id>"
  symbol      text NOT NULL,
  doc_text    text NOT NULL,
  link        text,
  published   text,
  embedding   vector(384),               -- 384 dims = all-MiniLM-L6-v2 output
  created_at  timestamptz DEFAULT now()
);

-- IVFFlat index for fast approximate nearest-neighbour search
-- (lists=100 is a sensible default for <100k rows)
CREATE INDEX IF NOT EXISTS news_embeddings_ivfflat
  ON news_embeddings
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

-- ── Helper RPC for semantic search ──
-- Usage from Python:
--   supa.rpc("match_news", {"query_embedding": [...], "match_count": 3}).execute()
CREATE OR REPLACE FUNCTION match_news(
  query_embedding vector(384),
  match_count     int DEFAULT 3
)
RETURNS TABLE (
  id        text,
  symbol    text,
  doc_text  text,
  link      text,
  published text,
  similarity float
)
LANGUAGE plpgsql
AS $$
BEGIN
  RETURN QUERY
  SELECT
    ne.id,
    ne.symbol,
    ne.doc_text,
    ne.link,
    ne.published,
    1 - (ne.embedding <=> query_embedding) AS similarity
  FROM news_embeddings ne
  ORDER BY ne.embedding <=> query_embedding
  LIMIT match_count;
END;
$$;
