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
    model: str = "groq/llama-3.3-70b-versatile",
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
The previous search query yielded insufficient results. Generate a broader query that keeps business relevance but returns more results. This is a self-correction step to improve search coverage. Output only the query.
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
async def qualify_and_score_lead(markdown_content: str, service: str, industry: str, location: str) -> Dict[str, Any]:
    if any(k in (markdown_content or "").lower() for k in NEGATIVE_KEYWORDS):
        return {
            "company_name": "N/A",
            "email": "N/A",
            "phone": "N/A",
            "qualified": "Maybe",
            "lead_score": 1,
            "reasoning": "Contains negative keywords.",
            "signals": [],
            "red_flags": ["negative keywords present"],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }

    prompt = f'''
You are a sales analyst. Given the page content, determine if it's a potential lead for:
Service: {service}
Industry: {industry}
Location: {location}

Return JSON with keys:
company_name, email, phone, qualified (Yes/Maybe/No), lead_score (0-10), reasoning, signals (list), red_flags (list)
Content:
{(markdown_content or '')[:4000]}
'''
    try:
        resp = await call_llm_with_retry(prompt, temperature=0.15, response_format={"type": "json_object"})
        raw = resp.choices[0].message.content.strip()
        try:
            analysis = json.loads(raw)
        except Exception:
            m = re.search(r"{{.*}}", raw, flags=re.S)
            analysis = json.loads(m.group(0)) if m else {}
        company_name = analysis.get("company_name") or "N/A"
        email = analysis.get("email") or "N/A"
        phone = analysis.get("phone") or "N/A"
        qualified = analysis.get("qualified") or "Maybe"
        lead_score = int(analysis.get("lead_score") or 0)
        reasoning = analysis.get("reasoning") or ""
        signals = analysis.get("signals") or []
        red_flags = analysis.get("red_flags") or []
        lead_score = max(0, min(10, lead_score))
        return {
            "company_name": company_name,
            "email": email,
            "phone": phone,
            "qualified": qualified,
            "lead_score": lead_score,
            "reasoning": reasoning,
            "signals": signals,
            "red_flags": red_flags,
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }
    except Exception as e:
        print(f"Error during qualification: {e}")
        return {
            "company_name": "N/A",
            "email": "N/A",
            "phone": "N/A",
            "qualified": "Maybe",
            "lead_score": 1,
            "reasoning": f"AI error: {e}",
            "signals": [],
            "red_flags": [],
            "scraped_content_preview": (markdown_content or "")[:500].replace("\n", " ") + "..."
        }