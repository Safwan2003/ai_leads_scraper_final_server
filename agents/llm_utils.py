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
You are a lead generation specialist. Generate one single **Google search query** 
that helps find businesses in the given industry and location who might need the service.

Service: {service}
Industry: {industry}
Location: {location}

---

### Rules for the query:
- Must include **business context**: ("small business" OR "local business" OR "official site" OR "company")  
- Must include **contact intent**: ("contact" OR "about us" OR "call" OR "email" OR "need" OR "require" OR "looking for" OR "seeking")  
- Must include **industry keyword**: "{industry}"  
- Must include **location keyword(s)**: ("{location}" OR nearby region/city terms)  
-  Must exclude groups, communities, agencies, influencers, marketplaces, and Reddit:  
  -inurl:groups -inurl:community -inurl:agency -inurl:influencer -inurl:marketplace -site:reddit.com

- Do not include explanations, comments, or formatting — return **only the final query string**.
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
def get_catchy_qualification(score: int) -> str:
    """Returns a catchy qualification status based on the lead score."""
    if score >= 90:
        return "Hot Lead"
    if score >= 75:
        return "Strong Prospect"
    if score >= 50:
        return "Good Fit"
    if score >= 25:
        return "Potential"
    return "Low Priority"

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
            "email": "N/A",
            "contact_no": "N/A",
            "qualified": "Low Priority",
            "lead_score": 1,
            "reasoning": "Contains negative keywords, indicating it's likely not a business lead.",
            "signals": [],
            "red_flags": ["negative keywords present"],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }

    prompt = f'''
You are an expert sales analyst. Your task is to analyze the provided website content and determine if the business is a potential lead for the given service.

**LEAD CONTEXT:**
- Service Needed: {service}
- Industry: {industry}
- Target Location: {location}

---

**RAW SCRAPED DATA:**
- Scraped Emails: {extra_contacts.get("emails") if extra_contacts else []}
- Scraped Phone Numbers: {extra_contacts.get("contact_no") if extra_contacts else []}
- Website Content:
{(markdown_content or '')[:4000]}

---

**INSTRUCTIONS:**

1.  **Analyze and Score:** Based on all the data, determine if this is a good lead. Assign a lead score from 0 to 100.
2.  **Identify Company Name:** Extract the company's name.
3.  **Extract Best Email:** From the "Scraped Emails" list and content, select the single best contact email.
4.  **Validate and Select Best Phone Number:** This is a critical task.
    - Examine the "Scraped Phone Numbers" list.
    - Use the "Target Location" ({location}) to determine which number is the most relevant. For example, if the location is "London", a UK number is more relevant than a US number.
    - Validate the chosen number. It must be a real, valid phone number.
    - Format the final, validated number into the international E.164 standard (e.g., +14155552671).
    - If no valid, relevant phone number can be found, you MUST return "N/A".
5.  **Provide Reasoning:** Briefly explain your reasoning for the score.
6.  **Identify Signals and Red Flags:** List positive buying signals or negative red flags.

---

**OUTPUT FORMAT:**
Return a single, minified JSON object with the following keys:
"company_name", "email", "contact_no", "lead_score", "reasoning", "signals", "red_flags"
The value for "contact_no" must be either a valid E.164 formatted string or "N/A".
'''
    try:
        resp = await call_llm_with_retry(prompt, temperature=0.1, response_format={"type": "json_object"})
        raw = resp.choices[0].message.content.strip()
        analysis = {}
        try:
            analysis = json.loads(raw)
        except Exception:
            m = re.search(r"{{.*}}", raw, flags=re.S)
            if m: analysis = json.loads(m.group(0))

        lead_score = max(0, min(100, int(analysis.get("lead_score") or 0)))
        qualified_status = get_catchy_qualification(lead_score)

        # The LLM is now responsible for returning a clean email and contact number or "N/A"
        final_email = analysis.get("email") or "N/A"
        if isinstance(final_email, list):
             final_email = final_email[0] if final_email else "N/A"


        final_contact_no = analysis.get("contact_no") or "N/A"
        if isinstance(final_contact_no, list):
            final_contact_no = final_contact_no[0] if final_contact_no else "N/A"


        return {
            "company_name": analysis.get("company_name") or "N/A",
            "email": final_email,
            "contact_no": final_contact_no,
            "qualified": qualified_status,
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
            "email": "N/A",
            "contact_no": "N/A",
            "qualified": "AI Error",
            "lead_score": 1,
            "reasoning": f"AI error: {e}",
            "signals": [],
            "red_flags": [],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }

