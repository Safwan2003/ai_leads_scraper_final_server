# agents/llm_utils.py
import json
import asyncio
import random
import litellm
import re
from typing import Dict, Any

from agents.query_utils import clean_query_output
from core.config import NEGATIVE_KEYWORDS # Import NEGATIVE_KEYWORDS from config

# -------------------------
# Async LLM wrapper
# -------------------------
async def call_llm_with_retry(
    prompt: str,
    model: str = "groq/openai/gpt-oss-20b",
    temperature: float = 0.3,
    retries: int = 3,
    response_format=None,
):
    messages = [{"role": "user", "content": prompt}]
    for attempt in range(retries):
        try:
            resp = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format=response_format
            )
            return resp
        except Exception as e:
            if attempt < retries - 1:
                wait = 2 ** attempt + random.random()
                print(f"[LLM retry {attempt+1}] {e} → sleeping {wait:.1f}s")
                await asyncio.sleep(wait)
            else:
                print(f"[LLM] final attempt failed: {e}")
                raise

# -------------------------
# AI-powered query generators
# -------------------------
async def generate_ai_search_query(service: str, industry: str, location: str) -> str:
    prompt = f'''
You are an expert lead-generation researcher.
Your task: generate a single Google search query to find small-to-medium businesses 
in the industry below that are likely to need help with this service.

Service: {service}
Industry: {industry}
Location: {location}

Output only the final Google query string.
'''
    try:
        resp = await call_llm_with_retry(prompt, temperature=0.45)
        raw = resp.choices[0].message.content.strip()
        return clean_query_output(raw, service, industry, location, "com")
    except Exception as e:
        print(f"Error generating AI query: {e}")
        return f'"{industry}" "{service}" "{location}" -site:gov -site:edu'

async def generate_retry_query(original_query: str, platform: str) -> str:
    prompt = f'''
Original query: {original_query}
Platform: {platform}
Generate a broader query that keeps business relevance but returns more results. Output only the query.
'''
    try:
        resp = await call_llm_with_retry(prompt, temperature=0.6)
        raw = resp.choices[0].message.content.strip()
        if "\n" in raw:
            raw = raw.split("\n")[-1].strip()
        return raw
    except Exception as e:
        print(f"Error generating retry query: {e}")
        return original_query

# -------------------------
# Qualifier
# -------------------------
async def qualify_and_score_lead(
    markdown_content: str,
    service: str,
    industry: str,
    location: str,
    extra_contacts: dict = None
) -> Dict[str, Any]:
    if any(k in (markdown_content or "").lower() for k in NEGATIVE_KEYWORDS):
        return {
            "company_name": "N/A",
            "company_description": "N/A",
            "email": "N/A",
            "contact_no": "N/A",
            "social_media_links": {},
            "qualified": "Maybe",
            "lead_score": 1,
            "reasoning": "Contains negative keywords.",
            "signals": [],
            "red_flags": ["negative keywords present"],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }

    prompt = f'''
You are an expert sales analyst. Your task is to analyze the provided website content and determine if the business is a potential lead for the given service.

Service: {service}
Industry: {industry}
Location: {location}

---

**Instructions:**

1.  **Identify the Company:** Find the company\'s name. It\'s often in the page title, headers, or footer.
2.  **Find Contact Information:** Extract the company\'s email and phone number. Prioritize the "Extra Contacts" provided below, as they were found by a scraper.
3.  **Qualify the Lead:** Based on the content, decide if the business is a "Yes", "Maybe", or "No" for the specified service.
4.  **Score the Lead:** Assign a lead score from 0 to 10, where 10 is a perfect match.
5.  **Provide Reasoning:** Briefly explain your reasoning for the qualification and score.
6.  **Identify Signals and Red Flags:** List any positive signals (e.g., "outdated website", "no blog") or red flags (e.g., "already using a competitor", "not in the right industry").

---

**Extra Contacts (from scraping):**
Emails: {extra_contacts.get("emails") if extra_contacts else []}
Contact No: {extra_contacts.get("contact_no") if extra_contacts else []}

---

**Content to Analyze:**
{(markdown_content or '')[:4000]}

---

**Output Format:**

Return a single JSON object with the following keys:
"company_name", "email", "contact_no", "qualified", "lead_score", "reasoning", "signals", "red_flags"
'''
    try:
        resp = await call_llm_with_retry(prompt, temperature=0.15, response_format={"type": "json_object"})
        raw = resp.choices[0].message.content.strip()
        analysis = {}
        try:
            analysis = json.loads(raw)
        except Exception:
            m = re.search(r"{{.*}}", raw, flags=re.S)
            if m: analysis = json.loads(m.group(0))

        lead_score = max(0, min(10, int(analysis.get("lead_score") or 0)))

        return {
            "company_name": analysis.get("company_name") or "N/A",
            "email": analysis.get("email") or (extra_contacts.get("emails")[0] if extra_contacts and extra_contacts.get("emails") else "N/A"),
            "contact_no": analysis.get("contact_no") or (extra_contacts.get("contact_no")[0] if extra_contacts and extra_contacts.get("contact_no") else "N/A"),
            "qualified": analysis.get("qualified") or "Maybe",
            "lead_score": lead_score,
            "reasoning": analysis.get("reasoning") or "",
            "signals": analysis.get("signals") or [],
            "red_flags": analysis.get("red_flags") or [],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }
    except Exception as e:
        print(f"Error during qualification: {e}")
        return {
            "company_name": "N/A",
            "email": extra_contacts.get("emails")[0] if extra_contacts and extra_contacts.get("emails") else "N/A",
            "contact_no": extra_contacts.get("contact_no")[0] if extra_contacts and extra_contacts.get("contact_no") else "N/A",
            "qualified": "Maybe",
            "lead_score": 1,
            "reasoning": f"AI error: {e}",
            "signals": [],
            "red_flags": [],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }

