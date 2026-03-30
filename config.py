import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

class Config:
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_KEY = os.getenv("SUPABASE_KEY")
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", "dev-secret-key")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")