# agents/utils.py
import os
import sys
import asyncio
import datetime
from typing import Callable, Dict, Any

# Custom imports
from db.database import (
    save_lead_to_db,
    get_lead_by_website_from_db,
)
from core.google_search import google_search
from agents.fallback_scraper import scrape_url
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

# -------------------------
# Generic pipeline
# -------------------------
async def run_generic_scraper(
    query_generator_func: Callable,
    service: str,
    industry: str,
    location: str,
    platform: str,
    callback: Callable  # New parameter for status updates
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

        # Smart Refresh Logic
        existing_lead = await get_lead_by_website_from_db(url)
        if existing_lead:
            last_updated = existing_lead.get("last_updated")
            if last_updated and isinstance(last_updated, datetime.datetime):
                # Ensure last_updated is offset-aware for comparison
                if last_updated.tzinfo is None:
                    last_updated = last_updated.replace(tzinfo=datetime.timezone.utc)

                if datetime.datetime.now(datetime.timezone.utc) - last_updated < datetime.timedelta(days=LEAD_REFRESH_DAYS):
                    callback({"status": "info", "message": f"[{platform}] Skipping fresh lead: {url}"})
                    callback({"status": "lead", "lead": existing_lead})  # Show the fresh lead
                    continue  # Skip to next URL
            callback({"status": "info", "message": f"[{platform}] Refreshing stale lead: {url}"})

        callback({"status": "info", "message": f"[{platform}] Processing {url}..."})
        try:
            scrape_results = await scrape_url(url, company_name=industry)
            markdown = scrape_results["markdown"]
            fallback_contacts = scrape_results["fallback_contacts"]

            if not markdown:
                callback({"status": "error", "message": f"[{platform}] Failed to scrape content from {url}."})
                continue

            lead = await qualify_and_score_lead(markdown, service, industry, location)
            lead["website"] = url
            lead["source"] = platform
            lead["search_tag"] = url_data.get("search_tag")
            lead["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

            if not lead.get("email") or lead["email"] in ["N/A", "None", ""]:
                if fallback_contacts.get("emails"):
                    lead["email"] = fallback_contacts["emails"][0]
                    lead["reasoning"] += " | Email added via fallback."

            if not lead.get("phone") or lead["phone"] in ["N/A", "None", ""]:
                if fallback_contacts.get("phones"):
                    lead["phone"] = fallback_contacts["phones"][0]
                    lead["reasoning"] += " | Phone added via fallback."

            await save_lead_to_db(lead)
            callback({"status": "lead", "lead": lead})

        except Exception as e:
            callback({"status": "error", "message": f"[{platform}] CRITICAL error processing {url}: {e}"})