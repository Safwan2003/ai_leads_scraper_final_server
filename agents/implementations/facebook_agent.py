# agents/facebook_agent.py
from agents.llm_utils import call_llm_with_retry
from agents.query_utils import clean_query_output
from agents.utils import run_generic_scraper
from typing import Callable

async def generate_facebook_query(service: str, industry: str, location: str) -> str:
    prompt = f"""
You are a lead generation expert focused on Facebook business pages.
Generate a single **Google search query** that finds Facebook pages of businesses 
in the given industry and location that are likely to need the given service.

Service: {service}
Industry: {industry}
Location: {location}

Rules for the query:
- Must include site:facebook.com
- Must include business context: ("small business" OR "local business" OR "official page")
- Must include contact intent: ("contact" OR "about" OR "call" OR "email")
- Must include industry: "{industry}"
- Must include location: ("{location}" OR nearby city/region terms)
- Exclude groups, communities, agencies, influencers:
  -inurl:groups -inurl:community -inurl:agency -inurl:influencer -inurl:marketplace
- Return ONLY the final query string, no explanation.
"""
    resp = await call_llm_with_retry(prompt, temperature=0.4)
    raw = resp.choices[0].message.content.strip()
    if "\n" in raw:
        raw = raw.split("\n")[-1].strip()
    return clean_query_output(raw, service, industry, location, "facebook.com")

async def run_facebook_scraper(service: str, industry: str, location: str, callback: Callable, skip_cache: bool = False):
    await run_generic_scraper(
        generate_facebook_query,
        service,
        industry,
        location,
        "Facebook",
        callback,
        skip_cache=skip_cache
    )
