from supabase import create_client, Client
from config import Config

if not Config.SUPABASE_URL or not Config.SUPABASE_KEY:
    raise ValueError("Missing SUPABASE_URL or SUPABASE_KEY in environment variables.")

supabase: Client = create_client(Config.SUPABASE_URL, Config.SUPABASE_KEY)