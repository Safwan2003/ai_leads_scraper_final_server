# agents/twitter_agent.py
from agents.llm_utils import call_llm_with_retry
from agents.query_utils import clean_query_output
from agents.utils import run_generic_scraper
from typing import Callable

async def generate_twitter_query(service: str, industry: str, location: str) -> str:
    prompt = f"""
You are a lead generation expert specializing in Twitter (X).
Craft a single Google search query to find real businesses, business owners, 
founders, or CEOs active on Twitter who may need the given service.

Service: {service}
Industry: {industry}
Location: {location}

Rules for the query:
- Must include: (site:x.com OR site:twitter.com)
- Must include industry: "{industry}"
- Must include service intent: ("need {service}" OR "looking for {service}" OR "hiring {service}" OR "help with {service}" OR "growth" OR "digital presence")
- Must include business/owner context: ("business" OR "small business" OR "founder" OR "owner" OR "CEO" OR "company")
- Must include location: ("{location}" OR nearby city/region terms)
- Must include contact signals: ("contact" OR "about" OR "email")
- Exclude agencies, freelancers, and job spam:
  -"agency" -"consultant" -"marketing services" -"freelancer" -"upwork" -"fiverr" -"jobs"
- Return ONLY the final query string (no explanation).

"""
    resp = await call_llm_with_retry(prompt, temperature=0.4)
    raw = resp.choices[0].message.content.strip()

    # safety: agar LLM multiple line bhej de
    if "\n" in raw:
        raw = raw.split("\n")[-1].strip()

    return clean_query_output(raw, service, industry, location, "x.com")

async def run_twitter_scraper(service: str, industry: str, location: str, callback: Callable):
    await run_generic_scraper(
        generate_twitter_query,   # 👈 yahan se query milegi
        service,
        industry,
        location,
        "Twitter",                 # 👈 yeh source name hai (JSON me save hoga)
        callback
    )
