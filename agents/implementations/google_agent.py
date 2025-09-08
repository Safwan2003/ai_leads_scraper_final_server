# agents/google_agent.py
from agents.llm_utils import generate_ai_search_query
from agents.utils import run_generic_scraper
from typing import Callable # Added import

async def run_google_scraper(service: str, industry: str, location: str, callback: Callable):
    await run_generic_scraper(
        generate_ai_search_query,
        service,
        industry,
        location,
        "Google",
        callback
    )
