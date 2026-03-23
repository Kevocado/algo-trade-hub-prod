import os
from dotenv import load_dotenv
from supabase import create_client

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

supa = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))
print("Portfolio:", supa.table("portfolio_state").select("*").limit(1).execute().data)
