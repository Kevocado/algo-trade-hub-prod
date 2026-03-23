"""
news_rag.py — News ingestion & semantic search via Supabase pgvector
====================================================================
Replaces the previous ChromaDB implementation. Embeddings are stored in
the `news_embeddings` table (see shared/migrations/002_add_pgvector_news.sql).

• Fetch → Embed → Upsert  (run by background_scanner.py or standalone)
• Query                    (called by orchestrator.py for RAG context)

PREREQUISITE: Run migration 002 in the Supabase SQL Editor first.
"""

import logging
import os
import sys

import feedparser

# ── Shared config (works with PYTHONPATH=. from Procfile) ─────────────────
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from shared import config  # noqa: E402
from supabase import create_client, Client as SupabaseClient
from sentence_transformers import SentenceTransformer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  [NEWS RAG]  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
WATCHLIST       = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "SPY", "QQQ", "GLD", "USO"]
EMBEDDING_MODEL = "all-MiniLM-L6-v2"  # 384-dim — matches migration 002

# ── Lazy-loaded singletons ────────────────────────────────────────────────────
_supa: SupabaseClient | None = None
_model: SentenceTransformer | None = None


def _get_supa() -> SupabaseClient:
    global _supa
    if _supa is None:
        _supa = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        log.info("Supabase pgvector client initialised.")
    return _supa


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        log.info("Loading sentence-transformer model '%s'…", EMBEDDING_MODEL)
        _model = SentenceTransformer(EMBEDDING_MODEL)
        log.info("Model loaded.")
    return _model


# ── News Fetching (unchanged from previous version) ──────────────────────────

def fetch_yahoo_news(symbol: str) -> list[dict]:
    """Top 5 recent articles for a ticker from Yahoo Finance RSS."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:5]:
        articles.append({
            "id":        f"{symbol}_{getattr(entry, 'id', getattr(entry, 'link', symbol))}",
            "title":     getattr(entry, "title",     ""),
            "summary":   getattr(entry, "summary",   ""),
            "link":      getattr(entry, "link",      ""),
            "symbol":    symbol,
            "published": getattr(entry, "published", ""),
        })
    return articles


def fetch_macro_news() -> list[dict]:
    """Top 10 macro market news from CNBC."""
    url = "https://search.cnbc.com/rs/search/combinedcms/view.xml?profile=120000000&id=10000664"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:10]:
        articles.append({
            "id":        f"MACRO_{getattr(entry, 'id', getattr(entry, 'link', 'macro'))}",
            "title":     getattr(entry, "title",     ""),
            "summary":   getattr(entry, "summary",   ""),
            "link":      getattr(entry, "link",      ""),
            "symbol":    "MACRO",
            "published": getattr(entry, "published", ""),
        })
    return articles


# ── Core: Fetch → Embed → Upsert ─────────────────────────────────────────────

def update_vector_db() -> None:
    """
    Fetch all news, compute 384-dim embeddings, and upsert into
    Supabase `news_embeddings`. Replaces the old ChromaDB upsert.
    """
    supa  = _get_supa()
    model = _get_model()

    all_articles: list[dict] = []

    log.info("Fetching macro market news…")
    all_articles.extend(fetch_macro_news())

    for sym in WATCHLIST:
        log.info("Fetching news for %s…", sym)
        all_articles.extend(fetch_yahoo_news(sym))

    if not all_articles:
        log.warning("No articles found — skipping upsert.")
        return

    # Build (id, doc_text, metadata) tuples, dropping empty docs
    rows: list[dict] = []
    for a in all_articles:
        doc_text = f"{a['title']} - {a['summary']}".strip()
        if len(doc_text) < 10:
            continue
        rows.append({
            "id":        a["id"],
            "symbol":    a["symbol"],
            "doc_text":  doc_text,
            "link":      a["link"],
            "published": a["published"],
        })

    if not rows:
        log.warning("All articles were too short — skipping upsert.")
        return

    # Batch embed (sentence-transformers is efficient in batch)
    log.info("Computing embeddings for %d articles…", len(rows))
    embeddings = model.encode(
        [r["doc_text"] for r in rows],
        batch_size=32,
        show_progress_bar=False,
        normalize_embeddings=True,
    )

    # Attach embedding vectors and upsert to Supabase
    upsert_payload = []
    for row, emb in zip(rows, embeddings):
        upsert_payload.append({**row, "embedding": emb.tolist()})

    log.info("Upserting %d articles into Supabase news_embeddings…", len(upsert_payload))
    supa.table("news_embeddings").upsert(upsert_payload, on_conflict="id").execute()
    log.info("pgvector update complete.")


# ── Core: Semantic Search (replaces ChromaDB collection.query) ───────────────

def query_news(query_text: str, n_results: int = 3) -> list[str]:
    """
    Semantic nearest-neighbour search via Supabase pgvector RPC.
    Returns a list of doc_text strings, ordered by cosine similarity.
    Falls back to an empty list on any failure (orchestrator handles gracefully).
    """
    try:
        supa  = _get_supa()
        model = _get_model()

        query_embedding = model.encode(
            query_text,
            normalize_embeddings=True,
        ).tolist()

        res = supa.rpc(
            "match_news",
            {"query_embedding": query_embedding, "match_count": n_results},
        ).execute()

        if res.data:
            return [row["doc_text"] for row in res.data]
    except Exception as exc:
        log.warning("pgvector query failed: %s", exc)

    return []


# ── Standalone entrypoint ────────────────────────────────────────────────────

if __name__ == "__main__":
    update_vector_db()
