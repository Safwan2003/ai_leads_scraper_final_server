import os
import aiomysql
import asyncio
import json
from typing import List, Dict, Any, Optional


from core.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

POOL = None

async def get_pool():
    global POOL
    if POOL is None:
        POOL = await aiomysql.create_pool(
            host=DB_HOST, port=DB_PORT,
            user=DB_USER, password=DB_PASSWORD,
            db=DB_NAME, autocommit=True
        )
    return POOL

# --- Schema Definition ---
async def create_tables():
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Leads Table
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS leads (
                id INT AUTO_INCREMENT PRIMARY KEY,
                company_name VARCHAR(255),
                website VARCHAR(255) UNIQUE,
                email VARCHAR(255),
                phone VARCHAR(255),
                qualified VARCHAR(50),
                lead_score INT,
                reasoning TEXT,
                signals JSON,
                red_flags JSON,
                source VARCHAR(100),
                search_tag VARCHAR(255),
                scraped_content_preview TEXT,
                last_updated DATETIME
            )
            """)
            # Google Search Cache Table
            await cur.execute("""
            CREATE TABLE IF NOT EXISTS google_search_cache (
                id INT AUTO_INCREMENT PRIMARY KEY,
                query_hash VARCHAR(64) UNIQUE,
                results JSON,
                timestamp DATETIME
            )
            """)

# --- Lead Management ---
async def save_lead_to_db(lead: Dict[str, Any]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Using INSERT ... ON DUPLICATE KEY UPDATE for "upsert" behavior
            sql = """
            INSERT INTO leads (company_name, website, email, phone, qualified, lead_score, reasoning, signals, red_flags, source, search_tag, scraped_content_preview, last_updated)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                company_name=VALUES(company_name), email=VALUES(email), phone=VALUES(phone), qualified=VALUES(qualified),
                lead_score=VALUES(lead_score), reasoning=VALUES(reasoning), signals=VALUES(signals), red_flags=VALUES(red_flags),
                source=VALUES(source), search_tag=VALUES(search_tag), scraped_content_preview=VALUES(scraped_content_preview), last_updated=VALUES(last_updated);
            """
            await cur.execute(sql, (
                lead.get("company_name"),
                lead.get("website"),
                lead.get("email"),
                lead.get("phone"),
                lead.get("qualified"),
                lead.get("lead_score"),
                lead.get("reasoning"),
                json.dumps(lead.get("signals", [])),
                json.dumps(lead.get("red_flags", [])),
                lead.get("source"),
                lead.get("search_tag"),
                lead.get("scraped_content_preview"),
                lead.get("last_updated")
            ))

async def load_all_leads_from_db() -> List[Dict[str, Any]]:
    pool = await get_pool()
    leads = []
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM leads ORDER BY last_updated DESC")
            rows = await cur.fetchall()
            for row in rows:
                # Deserialize JSON fields
                if row.get('signals'):
                    row['signals'] = json.loads(row['signals'])
                if row.get('red_flags'):
                    row['red_flags'] = json.loads(row['red_flags'])
                leads.append(dict(row))
    return leads

async def get_lead_by_website_from_db(website_url: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM leads WHERE website = %s", (website_url,))
            row = await cur.fetchone()
            if row:
                # Deserialize JSON fields
                if row.get('signals'):
                    row['signals'] = json.loads(row['signals'])
                if row.get('red_flags'):
                    row['red_flags'] = json.loads(row['red_flags'])
                return dict(row)
    return None

# --- Main entry point to initialize ---
async def initialize_database():
    await create_tables()

if __name__ == '__main__':
    asyncio.run(initialize_database())
    print("Database and tables should be ready.")
