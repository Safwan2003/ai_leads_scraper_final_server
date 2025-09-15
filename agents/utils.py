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
    get_lead_by_id_from_db,
)
from core.google_search import google_search
from agents.fallback_scraper import initial_scrape, enrich_lead, clean_emails, clean_contact_numbers
from agents.llm_utils import generate_retry_query, qualify_and_score_lead
from core.config import LEAD_REFRESH_DAYS

# -------------------------
# Cross-platform event loop policy
# -------------------------
if sys.platform.startswith("win"):
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        # Fallback for older Python versions
        pass


def post_process_lead(lead: Dict[str, Any], url: str, company_name_hint: str = "") -> Dict[str, Any]:
    """Normalize company_name, emails, and phone numbers after scraping + AI qualification."""
    if lead.get("company_name") == "N/A":
        try:
            extracted = tldextract.extract(url)
            if extracted.domain:
                company_name = extracted.domain.replace("-", " ").title()
                lead["company_name"] = company_name
        except Exception:
            pass

    if lead.get("company_name") == "N/A" and company_name_hint:
        lead["company_name"] = company_name_hint

    # ✅ Clean and normalize emails
    if isinstance(lead.get("email"), list):
        lead["email"] = clean_emails(lead["email"])
    elif isinstance(lead.get("email"), str) and lead["email"] != "N/A":
        lead["email"] = clean_emails([lead["email"]])

    # ✅ Clean and normalize contact numbers
    if isinstance(lead.get("contact_no"), list):
        lead["contact_no"] = clean_contact_numbers(lead["contact_no"])
    elif isinstance(lead.get("contact_no"), str) and lead["contact_no"] != "N/A":
        lead["contact_no"] = clean_contact_numbers([lead["contact_no"]])

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
    skip_cache: bool = False,
):
    callback({"status": "info", "message": f"[{platform}] Generating search query..."})
    try:
        query = await query_generator_func(service, industry, location)
        callback({"status": "info", "message": f"[{platform}] Search query: {query}"})
    except Exception as e:
        callback({"status": "error", "message": f"[{platform}] Error generating query: {e}"})
        return

    callback({"status": "info", "message": f"[{platform}] Searching for websites..."})
    urls = await google_search(query, skip_cache=skip_cache)

    if not urls:
        callback({"status": "info", "message": f"[{platform}] No URLs found, retrying with broader query..."})
        query = await generate_retry_query(query, platform)
        urls = await google_search(query, skip_cache=skip_cache)
        callback({"status": "info", "message": f"[{platform}] Retry query: {query} → Found {len(urls)} URLs."})

    if not urls:
        fallback_query = f'"{industry}" "{service}" "{location}" site:.com'
        callback({"status": "info", "message": f"[{platform}] Still no results. Using fallback query: {fallback_query}"})
        urls = await google_search(fallback_query, skip_cache=skip_cache)

    callback({"status": "info", "message": f"[{platform}] Found {len(urls)} URLs."})

    for url_data in urls:
        url = (url_data.get("url") or "").strip().lower()
        if not url:
            continue

        existing_lead = await get_lead_by_website_from_db(url)
        if not skip_cache and existing_lead:
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
                "emails": clean_emails(initial_data["emails"]),
                "contact_no": clean_contact_numbers(initial_data["contact_no"]),
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
                fallback_contacts["emails"] = clean_emails(fallback_contacts["emails"])
                fallback_contacts["contact_no"] = clean_contact_numbers(fallback_contacts["contact_no"])

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
            if (lead.get("email") == "N/A" or not lead.get("email")) and fallback_contacts.get("emails"):
                lead["email"] = fallback_contacts["emails"]
            if (lead.get("contact_no") == "N/A" or not lead.get("contact_no")) and fallback_contacts.get("contact_no"):
                lead["contact_no"] = fallback_contacts["contact_no"]

            await save_lead_to_db(lead)
            callback({"status": "lead", "lead": lead})

        except Exception as e:
            callback({"status": "error", "message": f"[{platform}] CRITICAL error processing {url}: {e}"})


async def rescrape_lead_by_id(job_id: str, lead_id: int, job_status_dict: Dict[str, Any]):
    job_status_dict[job_id] = {
        "status": "running",
        "progress": 0,
        "leads": [],
        "log": [f"Starting re-scrape for lead ID: {lead_id}"],
        "total_urls": 1,
        "processed_urls": 0,
        "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    def update_job_status(update: Dict[str, Any]):
        if update["status"] == "info":
            job_status_dict[job_id]["log"].append(update["message"])
        elif update["status"] == "error":
            job_status_dict[job_id]["log"].append(f"ERROR: {update['message']}")
        elif update["status"] == "lead":
            job_status_dict[job_id]["leads"].append(update["lead"])
            job_status_dict[job_id]["processed_urls"] += 1
            job_status_dict[job_id]["progress"] = 100

    try:
        lead_to_rescrape = await get_lead_by_id_from_db(lead_id)
        if not lead_to_rescrape:
            update_job_status({"status": "error", "message": f"Lead with ID {lead_id} not found."})
            job_status_dict[job_id]["status"] = "failed"
            return

        url = lead_to_rescrape["website"]
        service = lead_to_rescrape.get("search_tag", "").split(" ")[0]  # Approximation
        industry = lead_to_rescrape.get("industry", "")
        location = lead_to_rescrape.get("location", "")
        platform = lead_to_rescrape.get("source", "Google")

        update_job_status({"status": "info", "message": f"Re-scraping lead from {platform} for URL: {url}"})

        company_name_hint = lead_to_rescrape.get("company_name", "")
        initial_data = await initial_scrape(url)
        markdown = initial_data["markdown"]
        fallback_contacts = {
            "emails": clean_emails(initial_data["emails"]),
            "contact_no": clean_contact_numbers(initial_data["contact_no"]),
        }

        if not markdown:
            update_job_status({"status": "error", "message": f"Failed to scrape content from {url}."})
            job_status_dict[job_id]["status"] = "failed"
            return

        if not fallback_contacts["emails"] and not fallback_contacts["contact_no"]:
            enriched_data = await enrich_lead(url, company_name=company_name_hint)
            fallback_contacts["emails"].extend(enriched_data["emails"])
            fallback_contacts["contact_no"].extend(enriched_data["contact_no"])
            fallback_contacts["emails"] = clean_emails(fallback_contacts["emails"])
            fallback_contacts["contact_no"] = clean_contact_numbers(fallback_contacts["contact_no"])

        lead = await qualify_and_score_lead(
            markdown,
            service,
            industry,
            location,
            extra_contacts=fallback_contacts,
        )

        lead = post_process_lead(lead, url, company_name_hint)
        lead["website"] = url
        lead["source"] = platform
        lead["search_tag"] = lead_to_rescrape.get("search_tag")
        lead["industry"] = industry
        lead["location"] = location
        lead["last_updated"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

        if (lead.get("email") == "N/A" or not lead.get("email")) and fallback_contacts.get("emails"):
            lead["email"] = fallback_contacts["emails"]
        if (lead.get("contact_no") == "N/A" or not lead.get("contact_no")) and fallback_contacts.get("contact_no"):
            lead["contact_no"] = fallback_contacts["contact_no"]

        await save_lead_to_db(lead)
        update_job_status({"status": "lead", "lead": lead})
        job_status_dict[job_id]["status"] = "completed"

    except Exception as e:
        update_job_status({"status": "error", "message": f"CRITICAL error re-scraping {lead_id}: {e}"})
        job_status_dict[job_id]["status"] = "failed"
    finally:
        job_status_dict[job_id]["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
