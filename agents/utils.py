# agents/utils.py
import os
import sys
import asyncio
import datetime
from typing import Callable, Dict, Any
import tldextract

# Custom imports
from db.database import (
    save_lead_to_db,
    get_lead_by_website_from_db,
)
from core.google_search import google_search
from agents.fallback_scraper import initial_scrape, enrich_lead
from agents.llm_utils import generate_retry_query, qualify_and_score_lead
from core.config import LEAD_REFRESH_DAYS

# Windows console + asyncio robustness
if os.name == "nt":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        import codecs
        sys.stdout = codecs.getwriter("utf-8")(sys.stdout.buffer, "strict")
        sys.stderr = codecs.getwriter("utf-8")(sys.stderr.buffer, "strict")
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


def post_process_lead(lead: Dict[str, Any], url: str, company_name_hint: str = "") -> Dict[str, Any]:
    if lead.get("company_name") == "N/A":
        try:
            extracted = tldextract.extract(url)
            if extracted.domain:
                company_name = extracted.domain.replace("-", " ").title()
                lead["company_name"] = company_name
        except Exception:
            pass  # Ignore errors in post-processing
    
    if lead.get("company_name") == "N/A" and company_name_hint:
        lead["company_name"] = company_name_hint

    return lead


# -------------------------
# Generic pipeline
# -------------------------
async def run_generic_scraper(
    query_generator_func: Callable,
    service: str,
    industry: str,
    location: str,
    platform: str,
    callback: Callable,
):
    callback({"status": "info", "message": f"[{platform}] Generating search query..."})
    try:
        query = await query_generator_func(service, industry, location)
        callback({"status": "info", "message": f"[{platform}] Search query: {query}"})
    except Exception as e:
        callback({"status": "error", "message": f"[{platform}] Error generating query: {e}"})
        return

    callback({"status": "info", "message": f"[{platform}] Searching for websites..."})
    urls = await google_search(query)

    if not urls:
        callback({"status": "info", "message": f"[{platform}] No URLs found, retrying with broader query..."})
        query = await generate_retry_query(query, platform)
        urls = await google_search(query)
        callback({"status": "info", "message": f"[{platform}] Retry query: {query} → Found {len(urls)} URLs."})

    if not urls:
        fallback_query = f'"{industry}" "{service}" "{location}" site:.com'
        callback({"status": "info", "message": f"[{platform}] Still no results. Using fallback query: {fallback_query}"})
        urls = await google_search(fallback_query)

    callback({"status": "info", "message": f"[{platform}] Found {len(urls)} URLs."})

    for url_data in urls:
        url = (url_data.get("url") or "").strip().lower()
        if not url:
            continue

        existing_lead = await get_lead_by_website_from_db(url)
        if existing_lead:
            last_updated = existing_lead.get("last_updated")
            if last_updated and isinstance(last_updated, datetime.datetime):
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=datetime.timezone.utc)
                if datetime.datetime.now(datetime.timezone.utc) - last_updated < datetime.timedelta(days=LEAD_REFRESH_DAYS):
                    callback({"status": "info", "message": f"[{platform}] Skipping fresh lead: {url}"})
                    callback({"status": "lead", "lead": existing_lead})
                    continue
            callback({"status": "info", "message": f"[{platform}] Refreshing stale lead: {url}"})

        callback({"status": "info", "message": f"[{platform}] Processing {url}..."})
        try:
            company_name_hint = url_data.get("title", "")

            # Step 1: Initial, lightweight scrape
            initial_data = await initial_scrape(url)
            markdown = initial_data["markdown"]
            fallback_contacts = {
                "emails": initial_data["emails"],
                "contact_no": initial_data["contact_no"],
            }

            if not markdown:
                callback({"status": "error", "message": f"[{platform}] Failed to scrape content from {url}."})
                continue

            # Step 2: Enrich if necessary
            if not fallback_contacts["emails"] and not fallback_contacts["contact_no"]:
                callback({"status": "info", "message": f"[{platform}] No contacts on main page, enriching lead for {url}..."})
                enriched_data = await enrich_lead(url, company_name=company_name_hint)
                fallback_contacts["emails"].extend(enriched_data["emails"])
                fallback_contacts["contact_no"].extend(enriched_data["contact_no"])
                
                # Remove duplicates
                fallback_contacts["emails"] = list(set(fallback_contacts["emails"]))
                fallback_contacts["contact_no"] = list(set(fallback_contacts["contact_no"]))


            # Step 3: AI Qualification
            lead = await qualify_and_score_lead(
                markdown,
                service,
                industry.replace("clothing", "").strip(),
                location,
                extra_contacts=fallback_contacts,
            )

            # Step 4: Post-processing and saving
            lead = post_process_lead(lead, url, company_name_hint)
            lead["website"] = url
            lead["source"] = platform
            lead["search_tag"] = url_data.get("search_tag")
            lead["industry"] = industry
            lead["location"] = location
            lead["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            
            # Update email and contact_no from fallback_contacts if AI missed them
            if lead.get("email") == "N/A" and fallback_contacts.get("emails"):
                lead["email"] = fallback_contacts["emails"]
            if lead.get("contact_no") == "N/A" and fallback_contacts.get("contact_no"):
                lead["contact_no"] = fallback_contacts["contact_no"]


            await save_lead_to_db(lead)
            callback({"status": "lead", "lead": lead})

        except Exception as e:
            callback({"status": "error", "message": f"[{platform}] CRITICAL error processing {url}: {e}"})
