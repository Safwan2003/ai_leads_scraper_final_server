from fastapi import FastAPI, BackgroundTasks, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse, FileResponse
from pydantic import BaseModel
from typing import List, Dict, Any
import asyncio
import csv
import io
import uuid
import datetime
import json

# Local imports
from agents.implementations.google_agent import run_google_scraper
from agents.implementations.facebook_agent import run_facebook_scraper
from agents.implementations.linkedin_agent import run_linkedin_scraper
from agents.implementations.twitter_agent import run_twitter_scraper
from agents.implementations.instagram_agent import run_instagram_scraper
from agents.implementations.freelance_agent import run_freelance_scraper
from db.database import initialize_database, load_all_leads_from_db

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

# In-memory store for job statuses and results
_job_status: Dict[str, Dict[str, Any]] = {}

# Request model for /scrape endpoint
class ScrapeRequest(BaseModel):
    service: str
    industry: str
    location: str
    agents: List[str]



# --- Background Task for Scraping ---
async def _run_scraping_job(job_id: str, service: str, industry: str, location: str, agents: List[str]):
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
            'twitter': run_twitter_scraper,
            'instagram': run_instagram_scraper,
            'freelance': run_freelance_scraper, 
        }
        for agent in agents:
            if agent in agent_map:
                tasks.append(asyncio.create_task(agent_map[agent](service, industry, location, update_job_status)))

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
    background_tasks.add_task(_run_scraping_job, job_id, request_data.service, request_data.industry, request_data.location, request_data.agents)
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
    leads = await load_all_leads_from_db()
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
