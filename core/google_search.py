# core/google_search.py
import json
import datetime
from googleapiclient.discovery import build
from typing import List, Dict, Optional
import hashlib # Needed for query_hash
import aiomysql # Needed for DictCursor

from db.database import get_pool # Import get_pool to interact with DB
from core.config import GOOGLE_API_KEY, GOOGLE_CSE_ID, CACHE_EXPIRATION_DAYS # Import from config

MAX_RESULTS = 10 # This can remain local if it's specific to this module

# --- Google Search Cache Management (DEFINED HERE) ---
async def get_google_search_from_cache(query: str) -> Optional[Dict[str, str]]:
    pool = await get_pool()
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT results, timestamp FROM google_search_cache WHERE query_hash = %s", (query_hash,))
            row = await cur.fetchone()
            if row:
                return row # Returns {'results': ..., 'timestamp': ...}
    return None

async def save_google_search_to_cache(query: str, results: List[Dict[str, str]], timestamp: str):
    pool = await get_pool()
    query_hash = hashlib.sha256(query.encode()).hexdigest()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = """
            INSERT INTO google_search_cache (query_hash, results, timestamp)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE
                results=VALUES(results), timestamp=VALUES(timestamp);
            """
            await cur.execute(sql, (query_hash, json.dumps(results), timestamp))

# --- Main Google Search Function ---
async def google_search(query: str, max_results: int = MAX_RESULTS, skip_cache: bool = False) -> List[Dict[str, str]]:
    now = datetime.datetime.now(datetime.timezone.utc)

    # Check cache first
    if not skip_cache:
        cached_entry = await get_google_search_from_cache(query)
        if cached_entry:
            timestamp = cached_entry["timestamp"]
            # Ensure timestamp is a datetime object for comparison
            if isinstance(timestamp, str):
                timestamp = datetime.datetime.fromisoformat(timestamp).replace(tzinfo=datetime.timezone.utc)
            elif timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=datetime.timezone.utc)

            if now - timestamp < datetime.timedelta(days=CACHE_EXPIRATION_DAYS):
                print(f"[CACHE] Google search hit for: {query}")
                return json.loads(cached_entry["results"])
            else:
                print(f"[CACHE] Stale entry for: {query}")

    # If not in cache or stale, perform the search
    if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
        raise ValueError("Google API Key or Custom Search Engine ID not set in environment.")

    service = build("customsearch", "v1", developerKey=GOOGLE_API_KEY)
    results = []
    try:
        res = service.cse().list(q=query, cx=GOOGLE_CSE_ID, num=max_results).execute()
        for item in res.get("items", []):
            results.append({"url": item.get("link"), "snippet": item.get("snippet"), "search_tag": query})

        # Update cache
        await save_google_search_to_cache(query, results, now.isoformat())
        print(f"[API] Google search executed and cached for: {query}")

    except Exception as e:
        print(f"Google search error for query '{query}': {e}")

    return results
