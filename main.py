from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import asyncio
import sys
import csv
import io
import uuid
import datetime
import json






# Local imports
from agents.implementations.google_agent import run_google_scraper
from agents.implementations.facebook_agent import run_facebook_scraper
from agents.implementations.linkedin_agent import run_linkedin_scraper
from agents.implementations.instagram_agent import run_instagram_scraper
from agents.utils import rescrape_lead_by_id
from db.database import (
    initialize_database, load_all_leads_from_db, get_lead_by_id_from_db, 
    update_lead_in_db, delete_lead_from_db, get_leads_stats,
    bulk_delete_leads, bulk_update_lead_status
)

class LeadUpdate(BaseModel):
    company_name: str
    website: str
    qualified: str
    lead_score: int
    email: List[str] | None = None
    contact_no: List[str] | None = None
    industry: str | None = None
    location: str | None = None
    status: str | None = None

class BulkUpdateRequest(BaseModel):
    lead_ids: List[int]
    action: str
    value: str | None = None

main = FastAPI(
    title="AI Leads Scraper API",
    description="API for scraping and qualifying business leads using AI agents.",
    version="1.0.0",
)

# CORS Middleware
# This allows the frontend (running on a different address) to communicate with the backend.
main.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

@main.on_event("startup")
async def startup_event():
    await initialize_database()

@main.on_event("shutdown")
async def shutdown_event():
    from db.database import close_pool
    await close_pool()

# In-memory store for job statuses and results
_job_status: Dict[str, Dict[str, Any]] = {}

# Request model for /scrape endpoint
class ScrapeRequest(BaseModel):
    service: str
    industry: str
    location: str
    agents: List[str]
    skip_cache: bool = False



# --- Background Task for Scraping ---
async def _run_scraping_job(job_id: str, service: str, industry: str, location: str, agents: List[str], skip_cache: bool = False):
    _job_status[job_id] = {
        "status": "running",
        "progress": 0,
        "leads": [],
        "log": [],
        "total_urls": 0,
        "processed_urls": 0,
        "start_time": datetime.datetime.now(datetime.timezone.utc).isoformat()
    }

    def update_job_status(update: Dict[str, Any]):
        if update["status"] == "info":
            _job_status[job_id]["log"].append(update["message"])
            if "Found" in update["message"] and "URLs" in update["message"]:
                try:
                    # Extract number of URLs from message like "Found X URLs."
                    parts = update["message"].split(" ")
                    if len(parts) > 2 and parts[0] == "Found" and parts[2] == "URLs.":
                        _job_status[job_id]["total_urls"] += int(parts[1])
                except ValueError:
                    pass
        elif update["status"] == "error":
            _job_status[job_id]["log"].append(f"ERROR: {update['message']}")
        elif update["status"] == "lead":
            _job_status[job_id]["leads"].append(update["lead"])
            _job_status[job_id]["processed_urls"] += 1
            if _job_status[job_id]["total_urls"] > 0:
                _job_status[job_id]["progress"] = (_job_status[job_id]["processed_urls"] / _job_status[job_id]["total_urls"]) * 100

    try:
        tasks = []
        agent_map = {
            'google': run_google_scraper,
            'facebook': run_facebook_scraper,
            'linkedin': run_linkedin_scraper,
            'instagram': run_instagram_scraper,
        }
        for agent in agents:
            if agent in agent_map:
                tasks.append(asyncio.create_task(agent_map[agent](service, industry, location, update_job_status, skip_cache=skip_cache)))

        if not tasks:
            update_job_status({"status": "info", "message": "No web scraping agents selected."})
            _job_status[job_id]["status"] = "completed"
            return

        await asyncio.gather(*tasks)
        _job_status[job_id]["status"] = "completed"
        _job_status[job_id]["progress"] = 100

    except Exception as e:
        _job_status[job_id]["status"] = "failed"
        _job_status[job_id]["log"].append(f"CRITICAL JOB ERROR: {e}")
    finally:
        _job_status[job_id]["end_time"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

# --- API Endpoints ---


@main.post("/scrape", response_model=Dict[str, str], status_code=202)
async def scrape_api(request_data: ScrapeRequest, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(_run_scraping_job, job_id, request_data.service, request_data.industry, request_data.location, request_data.agents, request_data.skip_cache)
    return {"job_id": job_id}

@main.post("/rescrape/{lead_id}", response_model=Dict[str, str], status_code=202)
async def rescrape_api(lead_id: int, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    background_tasks.add_task(rescrape_lead_by_id, job_id, lead_id, _job_status)
    return {"job_id": job_id}


@main.get("/status/{job_id}", response_model=Dict[str, Any])
async def get_status(job_id: str):
    status = _job_status.get(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    return status

@main.get("/results/{job_id}", response_model=Dict[str, Any])
async def get_results(job_id: str):
    status = _job_status.get(job_id)
    if not status:
        raise HTTPException(status_code=404, detail="Job not found")
    if status["status"] != "completed":
        raise HTTPException(status_code=409, detail="Job not completed yet")
    return {"job_id": job_id, "leads": status["leads"]}

@main.get("/export_csv")
async def export_csv():
    # Fetch all leads, not just a page
    data = await load_all_leads_from_db(limit=10000) # A large limit to get all leads
    leads = data.get('leads', [])
    if not leads:
        raise HTTPException(status_code=204, detail="No leads to export")

    output = io.StringIO()
    writer = csv.writer(output)
    # Adjust header to match all fields from the database
    writer.writerow(['id', 'company_name', 'website', 'email', 'contact_no', 'industry', 'location', 'qualified', 'lead_score', 'reasoning', 'signals', 'red_flags', 'source', 'search_tag', 'scraped_content_preview', 'last_updated'])
    for lead in leads:
        writer.writerow([
            lead.get('id'),
            lead.get('company_name', 'N/A'),
            lead.get('website', 'N/A'),
            json.dumps(lead.get('email', [])),
            json.dumps(lead.get('contact_no', [])),
            lead.get('industry', 'N/A'),
            lead.get('location', 'N/A'),
            lead.get('qualified', 'N/A'),
            lead.get('lead_score', 'N/A'),
            lead.get("reasoning", ""),
            json.dumps(lead.get("signals", [])), # Serialize json
            json.dumps(lead.get("red_flags", [])), # Serialize json
            lead.get("source", ""),
            lead.get("search_tag", ""),
            lead.get("scraped_content_preview", ""),
            lead.get('last_updated', 'N/A').isoformat() if isinstance(lead.get('last_updated'), datetime.datetime) else lead.get('last_updated', 'N/A')
        ])
    output.seek(0)
    
    headers = {
        "Content-Disposition": "attachment; filename=leads.csv",
        "Content-type": "text/csv",
    }
    return StreamingResponse(output, headers=headers)

# --- Admin Panel Endpoints ---

@main.get("/admin/leads", response_model=Dict[str, Any])
async def get_all_leads_for_admin(
    page: int = 1,
    limit: int = 10,
    sort_by: str = "last_updated",
    sort_order: str = "DESC",
    search_term: str = None,
    website: str = None,
    qualified: str = None,
    source: str = None,
    start_date: str = None,
    end_date: str = None,
    min_score: int = None
):
    filters = {
        "search_term": search_term,
        "website": website,
        "qualified": qualified,
        "source": source,
        "start_date": start_date,
        "end_date": end_date,
        "min_score": min_score
    }
    result = await load_all_leads_from_db(page, limit, sort_by, sort_order, filters)
    return result

@main.get("/admin/stats", response_model=Dict[str, Any])
async def get_admin_stats():
    stats = await get_leads_stats()
    return stats

@main.post("/admin/bulk-actions/leads", status_code=200)
async def bulk_update_leads_for_admin(request: BulkUpdateRequest, background_tasks: BackgroundTasks):
    if not request.lead_ids:
        raise HTTPException(status_code=400, detail="No lead IDs provided")

    if request.action == "delete":
        await bulk_delete_leads(request.lead_ids)
        return {"message": "Leads deleted successfully"}
    
    if request.action.startswith("set_status_"):
        status = request.action.replace("set_status_", "")
        await bulk_update_lead_status(request.lead_ids, status)
        return {"message": f"Leads status updated to {status}"}

    if request.action == "rescrape":
        job_ids = []
        for lead_id in request.lead_ids:
            job_id = str(uuid.uuid4())
            background_tasks.add_task(rescrape_lead_by_id, job_id, lead_id, _job_status)
            job_ids.append(job_id)
        return {"message": f"Started rescraping for {len(job_ids)} leads.", "job_ids": job_ids}

    raise HTTPException(status_code=400, detail="Invalid bulk action")

@main.get("/admin/leads/{lead_id}", response_model=Dict[str, Any])
async def get_lead_for_admin(lead_id: int):
    lead = await get_lead_by_id_from_db(lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    return lead

@main.put("/admin/leads/{lead_id}", status_code=204)
async def update_lead_for_admin(lead_id: int, lead_data: LeadUpdate):
    await update_lead_in_db(lead_id, lead_data.dict())

@main.delete("/admin/leads/{lead_id}", status_code=204)
async def delete_lead_for_admin(lead_id: int):
    await delete_lead_from_db(lead_id)
