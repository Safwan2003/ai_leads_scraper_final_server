# AI Leads Scraper

## Overview

The AI Leads Scraper is a sophisticated, AI-powered lead generation system designed to identify, scrape, and qualify potential business leads across various online platforms. It leverages a modular architecture, asynchronous processing, intelligent caching, and large language models (LLMs) to deliver efficient, accurate, and continuously improving results.

This application provides a web-based interface for users to define their target market (service, industry, location) and select AI agents to scour the internet for relevant business leads.

## Features

*   **AI-Powered Query Generation:** LLMs craft highly targeted Google search queries for specific platforms and business needs.
*   **Multi-Platform Lead Generation:** Agents specialized for Google, Facebook, LinkedIn, Twitter, Instagram, and Freelance platforms.
*   **Intelligent Caching:**
    *   **Google Search Cache:** Caches Google search results for 14 days to reduce API calls and speed up repeated searches.
    *   **Smart Lead Refresh:** Avoids redundant web scraping by checking the database for fresh leads (updated within 14 days), retrieving them directly from DB, and only re-scraping stale or new leads.
*   **Robust Web Scraping:** Utilizes `crawl4ai` for primary content extraction with multi-layered fallbacks (direct HTML parsing, Google Dorking) for comprehensive contact information retrieval.
*   **AI Lead Qualification:** LLMs analyze scraped content to determine lead qualification status (Yes/Maybe/No), assign a lead score (0-10), and identify positive signals and negative red flags.
*   **Asynchronous Processing:** Built with FastAPI and `asyncio` for high concurrency and non-blocking operations, allowing many leads to be processed simultaneously.
*   **Modular and Extensible Architecture:** Clean separation of concerns for easy addition of new agents, LLM models, or data sources.
*   **Real-time Progress & Logging:** Web interface displays live progress, detailed logs, and newly found leads as they are discovered.
*   **CSV Export:** Export all collected leads to a CSV file for further analysis or CRM integration.
*   **Self-Correction Mechanisms:** LLM-driven query broadening for improved search coverage.

## Architecture

The project follows a modular architecture with distinct components:

```
AI_leads_MarkyTech_Server/
├───core/                 # Core utilities and configurations
│   ├───config.py         # Centralized environment variables and global settings
│   └───google_search.py  # Google Search API integration and caching logic
├───db/                   # Database management
│   └───database.py       # Database connection, schema, and CRUD operations
├───agents/               # Intelligent lead generation agents and their utilities
│   ├───implementations/  # Individual platform-specific agent implementations
│   │   ├───facebook_agent.py
│   │   ├───freelance_agent.py
│   │   ├───google_agent.py
│   │   ├───instagram_agent.py
│   │   ├───linkedin_agent.py
│   │   └───twitter_agent.py
│   ├───fallback_scraper.py # Robust web scraping with multi-layered fallbacks
│   ├───llm_utils.py      # LLM interaction, AI query generation, and lead qualification
│   ├───query_utils.py    # Utility functions for cleaning search queries
│   └───utils.py          # Generic scraping pipeline orchestrator
├───frontend/             # Web-based user interface
│   └───index.html
├───main.py               # FastAPI application entry point and API definitions
├───.env                  # Environment variables (example provided)
├───Readme.md             # Project documentation
└───requirements.txt      # Python dependencies
```

## Core Components & Logic

### Frontend (`frontend/index.html`)

A single-page web application built with HTML, Tailwind CSS, and JavaScript. It provides the user interface for:
*   Inputting lead generation criteria (Service, Industry, Location).
*   Selecting which AI agents to deploy.
*   Displaying real-time job progress, logs, and discovered leads.
*   Allowing sorting of leads and exporting them to CSV.
It communicates with the backend via asynchronous API calls.

### Backend (`main.py`)

The central API server built using the FastAPI framework.
*   **API Endpoints:** Exposes endpoints like `/scrape` (to initiate a job), `/status/{job_id}` (to get job progress), `/results/{job_id}` (to retrieve final leads), and `/export_csv` (to download all leads).
*   **Asynchronous Job Management:** Offloads long-running scraping tasks to background processes using FastAPI's `BackgroundTasks`, ensuring the API remains responsive.
*   **In-memory Job Status:** Maintains a dictionary (`_job_status`) to track the real-time state, progress, and collected leads for each active job.

### Database (`db/database.py`)

Manages persistent storage using MySQL (`aiomysql`).
*   **Connection Pooling:** Efficiently handles database connections.
*   **Schema Definition:** Defines two key tables:
    *   `leads`: Stores comprehensive information about each qualified business lead.
    *   `google_search_cache`: Caches Google search results to optimize API usage.
*   **Data Operations:** Provides asynchronous functions for creating tables, saving/updating leads, loading all leads, and retrieving leads by website.

### Core Services (`core/`)

*   **`core/config.py`:**
    *   Centralizes all application configurations, including API keys (Google, LiteLLM), database credentials, and global constants like `LEAD_REFRESH_DAYS` and `CACHE_EXPIRATION_DAYS`. This promotes maintainability and avoids scattered environment variable loading.
*   **`core/google_search.py`:**
    *   Integrates with the Google Custom Search Engine (CSE) API.
    *   **Intelligent Caching:** Implements a 14-day cache for Google search results. Before performing a live search, it checks the `google_search_cache` table. If a fresh entry exists, it uses the cached data, significantly reducing API calls and improving speed. Stale or new queries trigger a live search, and results are then cached.

### Intelligent Agents (`agents/`)

The heart of the lead generation process, designed for modularity and continuous improvement.

*   **`agents/implementations/`:**
    *   Contains individual Python files for each platform-specific agent (e.g., `facebook_agent.py`, `linkedin_agent.py`).
    *   Each agent is responsible for generating highly targeted Google search queries tailored to its platform, leveraging LLMs for precision.

*   **`agents/utils.py` (Generic Scraping Pipeline Orchestrator):**
    *   Orchestrates the entire lead processing pipeline for each agent.
    *   **Quality Shift: Smart Lead Refresh:** For every URL identified, it first checks the `leads` database.
        *   If a lead for that URL exists and was `last_updated` within `LEAD_REFRESH_DAYS` (14 days), the system **skips live re-scraping** for efficiency. Instead, it retrieves the existing, fresh lead data directly from the database and sends it to the frontend.
        *   If the lead is stale or new, it proceeds with live scraping and qualification. This ensures a merged view of results (fresh from DB, new/stale from live scrape) in the frontend.

*   **`agents/llm_utils.py` (LLM Interaction & Qualification - Core of Self-Improvement):**
    *   **`call_llm_with_retry()`:** A robust wrapper for LiteLLM API calls with retry logic.
    *   **`generate_ai_search_query()`:** Uses an LLM to generate precise Google search queries based on user criteria.
    *   **Quality Shift: Self-Correcting Query Generation (`generate_retry_query`):** If an initial search yields insufficient results, this function uses the LLM to generate a *broader* query. The LLM's prompt explicitly guides this self-correction, allowing the system to adapt its search strategy dynamically.
    *   **Quality Shift: AI Lead Qualification (`qualify_and_score_lead`):** The LLM analyzes scraped content to:
        *   Determine `qualified` status (Yes/Maybe/No).
        *   Assign a `lead_score` (0-10).
        *   Identify `signals` (positive indicators) and `red_flags` (negative indicators).
        *   Uses `NEGATIVE_KEYWORDS` (from `core/config.py`) for quick disqualification.

*   **`agents/query_utils.py` (Query Cleaning):**
    *   **`clean_query_output()`:** Sanitizes and refines LLM-generated search queries, ensuring they are valid and effective.

*   **`agents/fallback_scraper.py` (Robust Scraping Fallbacks - Adaptive Strategy):**
    *   Provides multi-layered methods for extracting information, designed for resilience and future adaptability.
    *   **Primary Scraping:** `scrape_lead_website()` uses `crawl4ai` for initial content extraction.
    *   **Multi-layered Fallbacks:** If primary scraping fails or contact details are missing, it logs the attempt and falls back to:
        *   **Direct HTML Parsing (`extract_from_html`):** Extracts emails/phones using regex.
        *   **Google Dorking (`extract_from_google`):** Performs additional Google searches for contact info.
    *   **Adaptive Potential:** Explicit logging of success/failure for each scraping method (e.g., `[Scrape] Primary scrape successful/failed`, `[Scrape] Google Dorking found/failed to find contacts`) creates a valuable dataset. This data can be analyzed in the future to "learn" which scraping methods are most effective for specific domains, enabling the system to adaptively prioritize methods.

## Advanced Concepts & Continuous Improvement

The system is built with several layers that enable it to "get more good and good" over time:

*   **Dynamic Query Adaptation:** The LLM-driven `generate_retry_query` is a live, in-session self-correction mechanism for search queries, allowing the system to overcome initial search limitations.
*   **Intelligent Caching:** The 14-day cache for Google searches and the smart lead refresh logic (for leads) ensure efficiency and prevent redundant work, allowing the system to focus resources on new or truly stale data.
*   **Data-Driven Feedback Loops (Future Potential):**
    *   **Query Performance:** By logging the success rate of LLM-generated queries (e.g., number of URLs yielded, qualified leads resulting), future iterations could fine-tune LLM prompts for better query generation.
    *   **Scraping Method Effectiveness:** The detailed logging in `fallback_scraper.py` creates a dataset to identify patterns (e.g., `crawl4ai` consistently failing on certain domains). This could lead to an adaptive strategy where the system automatically prioritizes more effective scraping methods for known problematic domains.
    *   **Lead Qualification Accuracy:** Integrating manual user feedback on lead quality could allow the system to refine its `qualify_and_score_lead` LLM prompts, making its AI vetting more precise over time.
*   **Modular and Extensible:** The highly modular structure facilitates easy integration of new agents, LLM models, or data sources, supporting continuous evolution.
*   **Asynchronous Efficiency:** Extensive use of `asyncio` and FastAPI ensures high concurrency, maximizing throughput for rapid processing and learning.

## Setup & Installation

### Prerequisites

*   **Python 3.8+:** Ensure you have a compatible Python version installed.
*   **MySQL Database:** A running MySQL server is required.
*   **Google Custom Search API Key & CSE ID:**
    1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
    2.  Create a new project or select an existing one.
    3.  Enable the "Custom Search API".
    4.  Go to "APIs & Services" > "Credentials" and create an API Key.
    5.  Go to the [Custom Search Engine](https://cse.google.com/cse/all) page.
    6.  Create a new search engine. You can configure it to search the entire web or specific sites.
    7.  Get your "Search engine ID" (also known as CSE ID).
*   **Groq API Key (or OpenRouter compatible LLM API Key):**
    1.  Sign up on [Groq](https://groq.com/) or [OpenRouter](https://openrouter.ai/).
    2.  Obtain your API Key.

### Environment Variables (`.env` file)

Create a file named `.env` in the root directory of the project and populate it with your credentials and database details:

```dotenv
# Google Custom Search API
google_api_key="YOUR_GOOGLE_API_KEY"
CSE_ID="YOUR_GOOGLE_CSE_ID"

# LLM API (e.g., Groq or OpenRouter)
GROQ_API_KEY="YOUR_GROQ_API_KEY"

# MySQL Database Configuration
DB_HOST="localhost"
DB_PORT=3306
DB_USER="your_mysql_user"
DB_PASSWORD="your_mysql_password"
DB_NAME="ai_leads_db"
```

### Installation Steps

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/Safwan2003/ai_leads_scraper_server.git
    cd ai_leads_scraper_server
    ```
2.  **Create and activate a virtual environment:**
    ```bash
    python -m venv .venv
    # On Windows:
    .venv\Scripts\activate
    # On Linux/macOS:
    source .venv/bin/activate
    ```
3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Note: `pydantic<2` is specified in `requirements.txt` to ensure compatibility with FastAPI's current setup.)*

4.  **Initialize the database:**
    The application will automatically create the necessary tables (`leads` and `google_search_cache`) when it starts. Ensure your MySQL server is running and accessible with the credentials provided in `.env`.

## Running the Application

1.  **Start the FastAPI backend:**
    ```bash
    uvicorn main:main --reload --host 0.0.0.0 --port 8000
    ```
    *(Note: We renamed `app.py` to `main.py` and the FastAPI app object from `app` to `main`.)*

2.  **Access the Frontend:**
    Open your web browser and navigate to:
    ```
    file:///C:/Users/DELL/OneDrive/Desktop/MarkyTech/AI_leads_MarkyTech_Server/frontend/index.html
    ```
    *(Adjust the path if your project is located elsewhere.)*

## Usage

1.  **Fill in the form:** Enter the `Service` you offer, the `Industry` you want to target, and the `Location`.
2.  **Select Agents:** Choose which AI agents (Google, Facebook, LinkedIn, etc.) you want to use for lead generation.
3.  **Scrape Leads:** Click the "Scrape Leads" button.
4.  **Monitor Progress:** Observe the real-time progress bar and logs. New leads will appear as they are discovered and qualified.
5.  **Export Results:** Once the scraping is complete, you can export all collected leads to a CSV file using the "Export to CSV" button.

## Contributing

Contributions are welcome! Please feel free to open issues or submit pull requests.

## License

This project is open-source and available under the [MIT License](https://opensource.org/licenses/MIT).
