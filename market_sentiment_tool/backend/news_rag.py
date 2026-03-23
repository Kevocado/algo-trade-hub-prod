import os
import logging
import feedparser
import chromadb
from chromadb.utils import embedding_functions

logging.basicConfig(level=logging.INFO, format="%(asctime)s  [NEWS RAG]  %(levelname)s  %(message)s")
log = logging.getLogger(__name__)

# Config
DB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_db")
WATCHLIST = ["AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "META", "GOOG", "SPY", "QQQ", "GLD", "USO"]

# Use a lightweight sentence-transformer model for rapid local embeddings
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

def init_chroma():
    """Initialize Persistent ChromaDB and create/get the collection."""
    # Ensure the directory exists
    os.makedirs(DB_DIR, exist_ok=True)
    
    client = chromadb.PersistentClient(path=DB_DIR)
    sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=EMBEDDING_MODEL)
    
    collection = client.get_or_create_collection(
        name="financial_news", 
        embedding_function=sentence_transformer_ef
    )
    return collection

def fetch_yahoo_news(symbol: str) -> list[dict]:
    """Fetch top recent articles for a specific ticker from Yahoo Finance RSS."""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={symbol}&region=US&lang=en-US"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:5]:  # top 5 per symbol
        articles.append({
            "id": f"{symbol}_{entry.id if hasattr(entry, 'id') else entry.link}",
            "title": getattr(entry, "title", ""),
            "summary": getattr(entry, "summary", ""),
            "link": getattr(entry, "link", ""),
            "symbol": symbol,
            "published": getattr(entry, "published", "")
        })
    return articles

def fetch_macro_news() -> list[dict]:
    """Fetch top macroeconomic market news from CNBC."""
    url = "https://search.cnbc.com/rs/search/combinedcms/view.xml?profile=120000000&id=10000664"
    feed = feedparser.parse(url)
    articles = []
    for entry in feed.entries[:10]:
        articles.append({
            "id": f"MACRO_{entry.id if hasattr(entry, 'id') else entry.link}",
            "title": getattr(entry, "title", ""),
            "summary": getattr(entry, "summary", ""),
            "link": getattr(entry, "link", ""),
            "symbol": "MACRO",
            "published": getattr(entry, "published", "")
        })
    return articles

def update_vector_db():
    """Main loop wrapper to fetch all news and upsert into ChromaDB."""
    log.info("Initializing ChromaDB at %s", DB_DIR)
    collection = init_chroma()
    
    all_articles = []
    
    log.info("Fetching macro market news...")
    all_articles.extend(fetch_macro_news())
    
    for sym in WATCHLIST:
        log.info("Fetching news for %s...", sym)
        all_articles.extend(fetch_yahoo_news(sym))
        
    if not all_articles:
        log.warning("No articles found to ingest.")
        return
        
    ids = []
    documents = []
    metadatas = []
    
    for a in all_articles:
        # Combine title and summary for the semantic embedding document
        doc_text = f"{a['title']} - {a['summary']}"
        # Skip empty
        if len(doc_text) < 10:
            continue
            
        ids.append(a['id'])
        documents.append(doc_text)
        metadatas.append({
            "symbol": a["symbol"], 
            "link": a["link"], 
            "published": a["published"]
        })
        
    log.info("Upserting %d articles into ChromaDB collection 'financial_news'...", len(ids))
    collection.upsert(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )
    log.info("Vector DB update complete.")

if __name__ == "__main__":
    update_vector_db()
