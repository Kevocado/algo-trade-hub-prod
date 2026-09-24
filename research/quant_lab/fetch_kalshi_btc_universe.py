"""
Kalshi Historical BTC Ticker Fetcher.
Connects to the Kalshi Historical API, iterates through paginated results,
and builds a master CSV of all Bitcoin-related market tickers.
"""

import os
import time
import logging
import requests
import pandas as pd
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Constants
API_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2/historical/markets"
PAGE_LIMIT = 1000
SLEEP_TIME = 0.5
SERIES_TICKERS = ["KXBTC"]   # Fetch hourly
OUTPUT_FILE = "kalshi_historical_btc_tickers.csv"

def get_headers() -> dict:
    """Construct API headers using the credentials in .env."""
    load_dotenv()
    api_key = os.getenv("KALSHI_API_KEY_ID")

    if not api_key:
        raise ValueError("KALSHI_API_KEY_ID not found in .env file.")

    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

def fetch_btc_universe() -> None:
    """Fetch paginated API results and compile the master DataFrame."""
    headers = get_headers()
    all_markets = []

    for series in SERIES_TICKERS:
        logger.info("Initializing fetch for series: %s", series)
        cursor = None
        page_count = 1

        while True:
            params = {
                "limit": PAGE_LIMIT,
                "series_ticker": series
            }
            if cursor:
                params["cursor"] = cursor

            try:
                response = requests.get(
                    API_BASE_URL,
                    headers=headers,
                    params=params,
                    timeout=15
                )
                response.raise_for_status()
                data = response.json()

                markets = data.get("markets", [])
                if not markets:
                    logger.info("No more markets found for %s.", series)
                    break

                for market in markets:
                    all_markets.append({
                        "ticker": market.get("ticker"),
                        "series": series,
                        "title": market.get("title"),
                        "open_time": market.get("open_time"),
                        "close_time": market.get("close_time"),
                        "settled_time": market.get("settled_time")
                    })

                logger.info(
                    "[%s] Page %d fetched: %d markets added.",
                    series, page_count, len(markets)
                )

                cursor = data.get("cursor")
                if not cursor:
                    logger.info("Reached end of pagination for %s.", series)
                    break

                page_count += 1
                time.sleep(SLEEP_TIME)  # Respect rate limits

            except requests.RequestException as error:
                logger.error("API Request failed on page %d for %s: %s", page_count, series, error)
                break

    if not all_markets:
        logger.warning("No markets were found. Exiting without saving.")
        return

    # Convert to DataFrame, remove duplicates (if any), and save
    df_markets = pd.DataFrame(all_markets)
    df_markets = df_markets.drop_duplicates(subset=["ticker"])
    
    # Sort chronologically by open_time for better readability
    df_markets = df_markets.sort_values(by="open_time").reset_index(drop=True)

    df_markets.to_csv(OUTPUT_FILE, index=False)
    logger.info("✅ Successfully saved %d unique BTC tickers to %s", len(df_markets), OUTPUT_FILE)

if __name__ == "__main__":
    fetch_btc_universe()