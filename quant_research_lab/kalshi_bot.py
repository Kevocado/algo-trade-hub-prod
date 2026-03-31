import logging
import time
import base64
import pickle
import uuid
import requests
from datetime import datetime
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
from apscheduler.schedulers.blocking import BlockingScheduler

# === NO HEAVY IMPORTS HERE ===

# ... (Configuration, send_tg, and get_headers functions stay the same) ...

def trade_cycle():
    # HEAVY LIFTING HAPPENS ONLY INSIDE HERE
    import yfinance as yf
    import pandas as pd
    import ta
    logger.info("Starting trade cycle imports...")
    # ... your logic ...

if __name__ == "__main__":
    # This part runs INSTANTLY because it doesn't need pandas
    send_tg("🚀 *KalshiBot Booting...* (Lazy Mode)")
    
    # Test Auth
    # ... auth logic ...
    
    sched = BlockingScheduler()
    sched.add_job(trade_cycle, 'cron', minute=1)
    sched.start()