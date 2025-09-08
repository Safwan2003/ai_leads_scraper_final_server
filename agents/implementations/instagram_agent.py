# agents/instagram_agent.py
from agents.llm_utils import call_llm_with_retry
from agents.query_utils import clean_query_output
from agents.utils import run_generic_scraper
from typing import Callable # Added import

async def generate_instagram_query(service: str, industry: str, location: str) -> str:
    prompt = f"""
You are a lead generation expert focused on Instagram business profiles.
Craft a single **Google search query** that finds Instagram accounts of businesses 
in the given industry and location that are likely to need the given service.

Service: {service}
Industry: {industry}
Location: {location}

Rules for the query:
- Must include site:instagram.com
- Must include business context: ("small business" OR "official" OR "business profile")
- Must include contact intent: ("contact" OR "about us" OR "call" OR "email")
- Must include industry: "{industry}"
- Must include location: ("{location}" OR nearby city/region terms)
- Exclude influencers, agencies, personal accounts:
  -inurl:agency -inurl:influencer -inurl:personal -inurl:model
- Focus on business types: (cafe OR restaurant OR shop OR boutique OR salon OR ecommerce OR store)
- Return ONLY the final query string, nothing else.
"""
    resp = await call_llm_with_retry(prompt, temperature=0.4)
    raw = resp.choices[0].message.content.strip()

    # safety: agar multiple lines aajaye to last one le lo
    if "\n" in raw:
        raw = raw.split("\n")[-1].strip()

    return clean_query_output(raw, service, industry, location, "instagram.com")

async def run_instagram_scraper(service: str, industry: str, location: str, callback: Callable):
    await run_generic_scraper(
        generate_instagram_query,
        service,
        industry,
        location,
        "Instagram",
        callback
    )
