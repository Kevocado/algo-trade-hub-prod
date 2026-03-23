"""
Database Hard Reset — Truncates polluted historical tables in Supabase.

Run this script to wipe all scanner data and start fresh.
Records the wipe date so the UI can display data coverage.

Usage:
    python scripts/db_hard_reset.py
"""

import sys
import os
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from src.supabase_client import get_client


TABLES_TO_WIPE = [
    "live_opportunities",
    "paper_signals",
    "trade_history",
    "scanner_runs",
]


def hard_reset():
    """Truncate all historical tables and record the wipe date."""
    client = get_client()
    wipe_time = datetime.now(timezone.utc).isoformat()

    print(f"🗑️  HARD RESET — Wiping all data at {wipe_time}")
    print(f"   Tables: {', '.join(TABLES_TO_WIPE)}")
    print()

    for table in TABLES_TO_WIPE:
        try:
            # Delete all rows (Supabase doesn't have TRUNCATE via SDK)
            client.table(table).delete().neq("id", -1).execute()
            print(f"  ✅ {table} — wiped")
        except Exception as e:
            print(f"  ⚠️ {table} — error: {e}")

    # Record the wipe date as a sentinel row
    try:
        client.table("scanner_runs").insert({
            "run_id": f"HARD_RESET_{wipe_time}",
            "status": "completed",
            "engines_run": ["HARD_RESET"],
            "total_opps": 0,
            "duration_sec": 0,
            "wipe_date": wipe_time,
        }).execute()
        print(f"\n  📌 Wipe date recorded: {wipe_time}")
    except Exception as e:
        print(f"\n  ⚠️ Failed to record wipe date: {e}")

    print("\n✅ Hard reset complete. All tables are clean.")
    print(f"   UI will show: 'Historical Data Coverage: {wipe_time[:10]} → Present'")


if __name__ == "__main__":
    confirm = input("⚠️  This will DELETE ALL DATA. Type 'RESET' to confirm: ")
    if confirm.strip() == "RESET":
        hard_reset()
    else:
        print("Aborted.")
