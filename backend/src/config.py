from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")