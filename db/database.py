
import os
import aiomysql
import asyncio
import json
from typing import List, Dict, Any, Optional


from core.config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, CACHE_EXPIRATION_DAYS

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

async def close_pool():
    global POOL
    if POOL:
        POOL.close()
        await POOL.wait_closed()
        POOL = None

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
                email JSON,
                contact_no JSON,
                industry VARCHAR(255),
                location VARCHAR(255),
                qualified VARCHAR(50),
                lead_score INT,
                reasoning TEXT,
                signals JSON,
                red_flags JSON,
                source VARCHAR(100),
                search_tag VARCHAR(255),
                status VARCHAR(50) DEFAULT 'New',
                scraped_content_preview TEXT,
                last_updated DATETIME,
                last_scraped DATETIME
            )
            """)

            # --- Migration logic ---
            # Add status column if it doesn't exist
            await cur.execute("SHOW COLUMNS FROM leads LIKE 'status'")
            if not await cur.fetchone():
                await cur.execute("ALTER TABLE leads ADD COLUMN status VARCHAR(50) DEFAULT 'New'")
            await cur.execute("SHOW COLUMNS FROM leads LIKE 'address'")
            if await cur.fetchone():
                await cur.execute("ALTER TABLE leads DROP COLUMN address")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'phone'")
            if await cur.fetchone():
                await cur.execute("ALTER TABLE leads CHANGE COLUMN phone contact_no VARCHAR(255)")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'industry'")
            if not await cur.fetchone():
                await cur.execute("ALTER TABLE leads ADD COLUMN industry VARCHAR(255)")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'location'")
            if not await cur.fetchone():
                await cur.execute("ALTER TABLE leads ADD COLUMN location VARCHAR(255)")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'social_media_links'")
            if await cur.fetchone():
                await cur.execute("ALTER TABLE leads DROP COLUMN social_media_links")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'company_description'")
            if await cur.fetchone():
                await cur.execute("ALTER TABLE leads DROP COLUMN company_description")

            # Alter email and contact_no to JSON type if they are not already
            await cur.execute("SHOW COLUMNS FROM leads LIKE 'email'")
            email_col = await cur.fetchone()
            if email_col and email_col[1] != 'json':
                await cur.execute("ALTER TABLE leads MODIFY COLUMN email JSON")

            await cur.execute("SHOW COLUMNS FROM leads LIKE 'contact_no'")
            contact_no_col = await cur.fetchone()
            if contact_no_col and contact_no_col[1] != 'json':
                await cur.execute("ALTER TABLE leads MODIFY COLUMN contact_no JSON")

            # Add last_scraped column if it doesn't exist
            await cur.execute("SHOW COLUMNS FROM leads LIKE 'last_scraped'")
            if not await cur.fetchone():
                await cur.execute("ALTER TABLE leads ADD COLUMN last_scraped DATETIME")

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
            INSERT INTO leads (company_name, website, email, contact_no, industry, location, qualified, lead_score, reasoning, signals, red_flags, source, search_tag, scraped_content_preview, last_updated, last_scraped, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
                company_name=VALUES(company_name), email=VALUES(email), contact_no=VALUES(contact_no), industry=VALUES(industry), location=VALUES(location),
                qualified=VALUES(qualified), lead_score=VALUES(lead_score), reasoning=VALUES(reasoning),
                signals=VALUES(signals), red_flags=VALUES(red_flags), source=VALUES(source),
                search_tag=VALUES(search_tag), scraped_content_preview=VALUES(scraped_content_preview),
                last_updated=VALUES(last_updated), last_scraped=VALUES(last_scraped), status=VALUES(status);
            """
            await cur.execute(sql, (
                lead.get("company_name"),
                lead.get("website"),
                json.dumps(lead.get("email", [])),
                json.dumps(lead.get("contact_no", [])),
                lead.get("industry"),
                lead.get("location"),
                lead.get("qualified"),
                lead.get("lead_score"),
                lead.get("reasoning"),
                json.dumps(lead.get("signals", [])),
                json.dumps(lead.get("red_flags", [])),
                lead.get("source"),
                lead.get("search_tag"),
                lead.get("scraped_content_preview"),
                lead.get("last_updated"),
                lead.get("last_updated"),  # Using last_updated for last_scraped as well
                lead.get("status", "New")
            ))

async def load_all_leads_from_db(
    page: int = 1,
    limit: int = 10,
    sort_by: str = "last_updated",
    sort_order: str = "DESC",
    filters: Dict[str, Any] = None
) -> Dict[str, Any]:
    pool = await get_pool()
    leads = []
    offset = (page - 1) * limit

    # Base query
    base_query = "SELECT * FROM leads"
    count_query = "SELECT COUNT(*) as total FROM leads"
    where_clauses = []
    params = []

    if filters:
        if filters.get("company_name"):
            where_clauses.append("company_name LIKE %s")
            params.append(f'%{filters.get("company_name")}%')
        if filters.get("source"):
            where_clauses.append("source = %s")
            params.append(filters.get("source"))
        if filters.get("qualified"):
            where_clauses.append("qualified = %s")
            params.append(filters.get("qualified"))
        if filters.get("min_score"):
            where_clauses.append("lead_score >= %s")
            params.append(int(filters.get("min_score")))
        if filters.get("start_date"):
            where_clauses.append("last_updated >= %s")
            params.append(filters.get("start_date"))
        if filters.get("end_date"):
            where_clauses.append("last_updated <= %s")
            params.append(filters.get("end_date"))

    if where_clauses:
        base_query += " WHERE " + " AND ".join(where_clauses)
        count_query += " WHERE " + " AND ".join(where_clauses)

    # Sorting
    if sort_by and sort_order:
        base_query += f" ORDER BY {sort_by} {sort_order}"

    # Pagination
    base_query += " LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Get total count
            await cur.execute(count_query, params[:-2]) # Exclude limit and offset from count
            total_row = await cur.fetchone()
            total = total_row['total']

            # Get paginated leads
            await cur.execute(base_query, params)
            rows = await cur.fetchall()
            for row in rows:
                # Deserialize JSON fields
                if row.get('email'):
                    row['email'] = json.loads(row['email'])
                if row.get('contact_no'):
                    row['contact_no'] = json.loads(row['contact_no'])
                if row.get('signals'):
                    row['signals'] = json.loads(row['signals'])
                if row.get('red_flags'):
                    row['red_flags'] = json.loads(row['red_flags'])
                leads.append(dict(row))
    
    return {"total": total, "leads": leads}

async def get_leads_stats() -> Dict[str, Any]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Total leads
            await cur.execute("SELECT COUNT(*) as total_leads FROM leads")
            total_leads = (await cur.fetchone())['total_leads']

            # Leads by qualification
            await cur.execute("SELECT qualified, COUNT(*) as count FROM leads GROUP BY qualified")
            leads_by_qualification = {row['qualified']: row['count'] for row in await cur.fetchall()}

            # Leads by source
            await cur.execute("SELECT source, COUNT(*) as count FROM leads GROUP BY source")
            leads_by_source = {row['source']: row['count'] for row in await cur.fetchall()}

            return {
                "total_leads": total_leads,
                "leads_by_qualification": leads_by_qualification,
                "leads_by_source": leads_by_source
            }


async def get_lead_by_website_from_db(website_url: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM leads WHERE website = %s", (website_url,))
            row = await cur.fetchone()
            if row:
                # Deserialize JSON fields
                if row.get('email'):
                    row['email'] = json.loads(row['email'])
                if row.get('contact_no'):
                    row['contact_no'] = json.loads(row['contact_no'])
                if row.get('signals'):
                    row['signals'] = json.loads(row['signals'])
                if row.get('red_flags'):
                    row['red_flags'] = json.loads(row['red_flags'])
                return dict(row)
    return None

async def get_lead_by_id_from_db(lead_id: int) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            await cur.execute("SELECT * FROM leads WHERE id = %s", (lead_id,))
            row = await cur.fetchone()
            if row:
                # Deserialize JSON fields
                if row.get('email'):
                    row['email'] = json.loads(row['email'])
                if row.get('contact_no'):
                    row['contact_no'] = json.loads(row['contact_no'])
                if row.get('signals'):
                    row['signals'] = json.loads(row['signals'])
                if row.get('red_flags'):
                    row['red_flags'] = json.loads(row['red_flags'])
                return dict(row)
    return None

async def update_lead_in_db(lead_id: int, lead_data: Dict[str, Any]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            sql = """
            UPDATE leads
            SET 
                company_name = %s, 
                website = %s, 
                qualified = %s, 
                lead_score = %s,
                email = %s,
                contact_no = %s,
                industry = %s,
                location = %s,
                status = %s
            WHERE id = %s;
            """
            await cur.execute(sql, (
                lead_data.get("company_name"),
                lead_data.get("website"),
                lead_data.get("qualified"),
                lead_data.get("lead_score"),
                json.dumps(lead_data.get("email", [])),
                json.dumps(lead_data.get("contact_no", [])),
                lead_data.get("industry"),
                lead_data.get("location"),
                lead_data.get("status"),
                lead_id
            ))

async def delete_lead_from_db(lead_id: int):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            await cur.execute("DELETE FROM leads WHERE id = %s", (lead_id,))

async def bulk_delete_leads(lead_ids: List[int]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Using a format string to create placeholders for the IN clause
            placeholders = ', '.join(['%s'] * len(lead_ids))
            sql = f"DELETE FROM leads WHERE id IN ({placeholders})"
            await cur.execute(sql, lead_ids)

async def bulk_update_lead_status(lead_ids: List[int], status: str):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            placeholders = ', '.join(['%s'] * len(lead_ids))
            sql = f"UPDATE leads SET status = %s WHERE id IN ({placeholders})"
            # The status is the first parameter, followed by the list of IDs
            await cur.execute(sql, [status] + lead_ids)



# --- Main entry point to initialize ---
async def get_scraped_data_from_cache(website_url: str) -> Optional[Dict[str, Any]]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor(aiomysql.DictCursor) as cur:
            # Check for cached data within the last X days
            await cur.execute(
                f"SELECT email, contact_no, last_scraped FROM leads WHERE website = %s AND last_scraped >= NOW() - INTERVAL {CACHE_EXPIRATION_DAYS} DAY",
                (website_url,)
            )
            row = await cur.fetchone()
            if row:
                return {
                    "emails": json.loads(row["email"]) if row["email"] else [],
                    "contact_no": json.loads(row["contact_no"]) if row["contact_no"] else [],
                    "last_scraped": row["last_scraped"]
                }
    return None

async def save_scraped_data_to_cache(website_url: str, data: Dict[str, Any]):
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.cursor() as cur:
            # Use INSERT ... ON DUPLICATE KEY UPDATE to save or update cache
            sql = """
            INSERT INTO leads (website, email, contact_no, last_scraped, company_name, scraped_content_preview)
            VALUES (%s, %s, %s, NOW(), %s, %s)
            ON DUPLICATE KEY UPDATE
                email=VALUES(email),
                contact_no=VALUES(contact_no),
                last_scraped=NOW(),
                company_name=VALUES(company_name),
                scraped_content_preview=VALUES(scraped_content_preview);
            """
            await cur.execute(sql, (website_url, json.dumps(data.get("emails", [])), json.dumps(data.get("contact_no", [])), data.get("company_name"), data.get("content_preview")))

# --- Main entry point to initialize ---
async def initialize_database():
    await create_tables()

if __name__ == '__main__':
    asyncio.run(initialize_database())
    print("Database and tables should be ready.")
