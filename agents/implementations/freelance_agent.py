# agents/freelance_agent.py
from agents.llm_utils import call_llm_with_retry
from agents.query_utils import clean_query_output
from agents.utils import run_generic_scraper
from typing import Callable

async def generate_freelance_project_query(service: str, industry: str, location: str) -> str:
    prompt = f"""
You are a lead generation expert. Your task is to generate a **Google search query** 
to find active freelance projects, gigs, or client postings in the given industry and location 
that may require the specified service.

Service: {service}
Industry: {industry}
Location: {location}

Rules for the query:
- Must include freelance platforms or project listings: (site:upwork.com OR site:fiverr.com OR site:freelancer.com OR site:peopleperhour.com)
- Must include project intent: ("looking for {service}" OR "need {service}" OR "project {service}" OR "hire for {service}" OR "help with {service}")
- Must include business/client context: ("company" OR "startup" OR "small business" OR "organization" OR "client")
- Must include location: ("{location}" OR nearby city/region terms)
- Must include contact signals: ("contact" OR "about" OR "email")
- Exclude freelancer profiles or portfolios: -"freelancer" -"profile" -"portfolio" -"resume"
- Return ONLY the final query string, nothing else.
"""
    resp = await call_llm_with_retry(prompt, temperature=0.4)
    raw = resp.choices[0].message.content.strip()

    # safety: if multiple lines returned, take the last
    if "\n" in raw:
        raw = raw.split("\n")[-1].strip()

    return clean_query_output(raw, service, industry, location, "upwork.com")

async def run_freelance_scraper(service: str, industry: str, location: str, callback: Callable, skip_cache: bool = False):
    await run_generic_scraper(
        generate_freelance_project_query,
        service,
        industry,
        location,
        "Freelance",  # source/platform name
        callback,
        skip_cache=skip_cache
    )
