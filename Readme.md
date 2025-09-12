# AI Leads MarkyTech Server

This project is a powerful, AI-driven lead generation server. It uses a FastAPI backend to manage and run scraping "agents" that find, process, and qualify business leads from various web sources. The system is designed to be modular, allowing for the easy addition of new agents to target different platforms.

A simple, reactive frontend provides a user-friendly interface to start scraping jobs, monitor their real-time progress, and view the qualified leads as they are generated.

## Features

- **AI-Powered Qualification**: Uses a Large Language Model (LLM) to analyze scraped website content, qualify leads ("Yes", "No", "Maybe"), assign a lead score, and identify buying signals or red flags.
- **Multi-Agent Architecture**: Employs different agents to generate specialized search queries for various platforms (e.g., Google, LinkedIn).
- **Robust Scraping & Enrichment**: Features a multi-step scraping process:
    1.  A quick initial scrape for basic content.
    2.  A deep "enrichment" scrape using fallback methods (Google Dorking, crawling contact pages) if contact info is missing.
    3.  Regex and `mailto`/`tel` link parsing to ensure maximum contact information extraction.
- **Database & Caching**:
    -   Saves all qualified leads to a MySQL database.
    -   Caches Google Search results to reduce API costs and speed up repeated queries.
    -   Avoids re-processing recent leads by checking the database for "freshness".
- **Asynchronous Processing**: Built with `asyncio` and FastAPI to handle multiple scraping tasks concurrently without blocking.
- **Real-time Frontend**: A web interface built with Tailwind CSS that allows users to:
    -   Define a target service, industry, and location.
    -   Select which agents to run.
    -   Monitor job progress and view live logs.
    -   View, sort, and export generated leads to CSV.

## How It Works

1.  **User Input**: The user provides a `service`, `industry`, and `location` on the frontend and selects which agents to deploy (e.g., Google, LinkedIn).
2.  **Job Creation**: The frontend sends a request to the `POST /scrape` endpoint. The FastAPI backend creates a unique `job_id` and starts the scraping process in the background.
3.  **Agent Activation**: The backend runs the selected agents concurrently. Each agent generates a specialized, AI-crafted Google search query tailored to its platform.
4.  **Google Search**: The system executes the search queries using the Google Custom Search API. Results are cached in the database.
5.  **Scraping & Analysis**: For each URL found:
    -   The system checks if a fresh lead for this website already exists in the database.
    -   The website's content is scraped using `crawl4ai`.
    -   If contact info is missing, the `enrich_lead` function performs deeper scraping.
    -   The scraped content and contact info are passed to the LLM via `qualify_and_score_lead`.
6.  **Qualification & Storage**: The LLM analyzes the content and returns a structured JSON object containing the company name, qualified status, lead score, reasoning, signals, and red flags. This final lead object is saved to the MySQL database.
7.  **Real-time Updates**: The frontend periodically polls the `GET /status/{job_id}` endpoint, which returns the current job status, logs, and any leads found so far. The UI updates in real-time to show this information.
8.  **Export**: The user can click "Export to CSV" to download all leads stored in the database via the `GET /export_csv` endpoint.

## Tech Stack

-   **Backend**: Python, FastAPI, Uvicorn
-   **Database**: MySQL (via `aiomysql` for async operations)
-   **AI / LLM**: `litellm` (configured for Groq/OpenRouter)
-   **Web Scraping**: `crawl4ai`, `BeautifulSoup4`
-   **Google Search**: `google-api-python-client`
-   **Frontend**: HTML, Tailwind CSS, Vanilla JavaScript
-   **Environment Management**: `python-dotenv`

## Project Structure

```
.
├── agents/                 # Core lead generation logic
│   ├── implementations/    # Agent-specific query generators (google, linkedin, etc.)
│   ├── fallback_scraper.py # Robust contact info extraction
│   ├── llm_utils.py        # LLM interaction for qualification and query generation
│   ├── query_utils.py      # Helpers for cleaning search queries
│   └── utils.py            # Main scraping pipeline orchestrator
├── core/                   # Core configuration and services
│   ├── config.py           # Environment variables and settings
│   └── google_search.py    # Google Search API wrapper with caching
├── db/                     # Database interaction
│   └── database.py         # Schema definition, connection pool, and CRUD operations
├── frontend/               # The user interface
│   └── index.html          # Single-page application
├── .gitignore              # Specifies files to ignore in git
├── main.py                 # FastAPI application entrypoint, defines API endpoints
├── Readme.md               # This file
└── requirements.txt        # Python dependencies
```

## API Documentation

The API is served by the FastAPI application in `main.py`.

### `POST /scrape`

Starts a new lead generation job. The process runs in the background.

-   **Status Code**: `202` (Accepted)
-   **Request Body**:
    ```json
    {
      "service": "string",
      "industry": "string",
      "location": "string",
      "agents": ["google", "linkedin"]
    }
    ```
-   **Response Body**:
    ```json
    {
      "job_id": "string (uuid)"
    }
    ```

### `GET /status/{job_id}`

Poll this endpoint to get the real-time status, logs, and results of a running job.

-   **Path Parameter**: `job_id` (string) - The ID returned from the `/scrape` endpoint.
-   **Response Body**:
    ```json
    {
      "status": "running" | "completed" | "failed",
      "progress": 0, // Percentage (0-100)
      "leads": [ /* array of lead objects */ ],
      "log": [ /* array of log messages */ ],
      "total_urls": 0,
      "processed_urls": 0,
      "start_time": "string (isoformat)"
    }
    ```

### `GET /export_csv`

Downloads all leads currently stored in the database as a CSV file.

-   **Response**: A `text/csv` file attachment named `leads.csv`.

## Setup and Installation

Follow these steps to run the project locally.

### 1. Prerequisites

-   Python 3.8+
-   A running MySQL server.

### 2. Clone the Repository

```bash
git clone <your-repository-url>
cd AI_leads_MarkyTech_Server
```

### 3. Set up a Virtual Environment

```bash
# Windows
python -m venv .venv
.venv\Scripts\activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a file named `.env` in the root of the project directory. This file will hold your secret keys and database credentials. Add the following content to it, replacing the placeholder values with your actual credentials.

```env
# --- Google API ---
# From Google Cloud Console, with Custom Search API enabled
google_api_key="YOUR_GOOGLE_API_KEY"
# From Programmable Search Engine control panel
CSE_ID="YOUR_CUSTOM_SEARCH_ENGINE_ID"

# --- LLM Provider (Groq / OpenRouter) ---
# Get this from Groq or OpenRouter
GROQ_API_KEY="YOUR_GROQ_OR_OPENROUTER_API_KEY"

# --- MySQL Database ---
DB_HOST="localhost"
DB_PORT=3306
DB_USER="your_db_user"
DB_PASSWORD="your_db_password"
DB_NAME="your_db_name"
```

### 6. Initialize the Database

The application will create the necessary tables automatically on startup. However, you must first create the database itself in MySQL.

```sql
-- Connect to your MySQL server and run:
CREATE DATABASE your_db_name;
```

## Running the Application

Once the setup is complete, you can start the FastAPI server using Uvicorn.

```bash
uvicorn main:main --reload
```

-   `--reload` enables hot-reloading, so the server will restart automatically when you change the code.

The API will be available at `http://127.0.0.1:8000`.

You can access the frontend by opening the `frontend/index.html` file in your web browser.
