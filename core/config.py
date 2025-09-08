# core/config.py
import os
from dotenv import load_dotenv
import litellm

load_dotenv()

# Google API Keys
GOOGLE_API_KEY = os.getenv("google_api_key")
GOOGLE_CSE_ID = os.getenv("CSE_ID")

# LiteLLM (Groq/OpenRouter) API Keys
litellm.api_key = os.getenv("GROQ_API_KEY")
litellm.api_base = "https://openrouter.ai/api/v1"

# Database Configuration
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

# Other Configs
LEAD_REFRESH_DAYS = 14 # How many days before a lead is considered stale
CACHE_EXPIRATION_DAYS = 14 # How many days before a cached search result is considered stale
NEGATIVE_KEYWORDS = ["jobs", "careers", "learn", "tutorial", "course"]
