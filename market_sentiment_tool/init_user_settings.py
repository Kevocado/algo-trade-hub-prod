import os
from dotenv import load_dotenv
from supabase import create_client

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

supa = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
    
# Find 'sigey2@illinois.edu'
users = supa.auth.admin.list_users()
user_id = None
for u in users:
    if u.email == "sigey2@illinois.edu":
        user_id = u.id
        break

if user_id:
    # Insert or update
    supa.table("user_settings").upsert({
        "user_id": user_id,
        "auto_trade_enabled": False,
        "max_daily_drawdown": 0.05
    }).execute()
    print("Kill switch row initialized for user", user_id)
else:
    print("User sigey2@illinois.edu not found")
