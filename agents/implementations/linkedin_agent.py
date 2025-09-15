# agents/linkedin_agent.py
from agents.llm_utils import call_llm_with_retry
from agents.query_utils import clean_query_output
from agents.utils import run_generic_scraper
from typing import Callable

async def generate_linkedin_query(service: str, industry: str, location: str) -> str:
    prompt = f"""
You are a lead generation expert specializing in LinkedIn.
Craft a single Google search query targeting LinkedIn pages of real businesses 
or business decision-makers who may need the given service.

Service: {service}
Industry: {industry}
Location: {location}

Rules for the query:
- Must include one of:
    - site:linkedin.com/company (business profiles)
    - site:linkedin.com/posts (demand signals)
- Must include industry: "{industry}"
- Must include service intent: ("need {service}" OR "looking for {service}" OR "hiring {service}" OR "update {service}" OR "growth" OR "digital presence")
- Must include location: ("{location}" OR nearby region terms)
- Must include contact/business context: ("owner" OR "founder" OR "CEO" OR "about" OR "contact")
- Exclude agencies, recruiters, consultants, service providers, job postings:
  -"agency" -"consultant" -"marketing services" -"recruiter" -"job" -"hiring platform"
- Return ONLY the final query string (no explanation).
"""
    resp = await call_llm_with_retry(prompt, temperature=0.4)
    raw = resp.choices[0].message.content.strip()

    if "\n" in raw:
        raw = raw.split("\n")[-1].strip()

    return clean_query_output(raw, service, industry, location, "linkedin.com")

async def run_linkedin_scraper(service: str, industry: str, location: str, callback: Callable, skip_cache: bool = False):
    await run_generic_scraper(
        generate_linkedin_query,
        service,
        industry,
        location,
        "LinkedIn",
        callback,
        skip_cache=skip_cache
    )
