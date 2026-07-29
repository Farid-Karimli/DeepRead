from dotenv import load_dotenv
import os

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
REDIS_URL = os.getenv("REDIS_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Supabase secret keys (`sb_secret_...`) are server-only and replace the legacy
# service-role JWT. Keep SUPABASE_KEY as a temporary compatibility alias because
# the existing persistence layer imports that name.
SUPABASE_SECRET_KEY = os.getenv("SUPABASE_SECRET_KEY")
SUPABASE_KEY = SUPABASE_SECRET_KEY or os.getenv("SUPABASE_KEY")
BRAVE_SEARCH_API_KEY = os.getenv("BRAVE_SEARCH_API_KEY")
BRAVE_ANSWERS_API_KEY = os.getenv("BRAVE_ANSWERS_API_KEY")
COHERE_API_KEY = os.getenv("COHERE_API_KEY")
WANDB_API_KEY = os.getenv("WANDB_API_KEY")
WEAVE_PROJECT = os.getenv("WEAVE_PROJECT", "gardoslab/deepread")
WEAVE_DISABLED = os.getenv("WEAVE_DISABLED", "").lower() in ("1", "true", "yes")
