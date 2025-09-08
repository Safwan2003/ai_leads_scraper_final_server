import re
import asyncio
from crawl4ai import AsyncWebCrawler
from core.google_search import google_search

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
PHONE_REGEX = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}"

def _format_phone_number(phone_candidate: str) -> str:
    """Strips a phone number to a canonical digits-only format."""
    digits = re.sub(r'\D', '', phone_candidate)
    if len(digits) == 10 and not phone_candidate.strip().startswith('+'):
        return f"1{digits}"
    if phone_candidate.strip().startswith('+') and len(digits) > 10:
        return digits
    if len(digits) >= 7:
        return digits
    return digits # Fallback

def _is_valid_phone(phone_candidate: str) -> bool:
    """Validates if a string is likely a real, usable phone number."""
    formatted_phone = _format_phone_number(phone_candidate)

    if not (7 <= len(formatted_phone) <= 15):
        return False

    if re.search(r'(\d)\1{4,}', formatted_phone):
        return False

    if formatted_phone in ['1234567', '12345678', '123456789', '987654321']:
        return False
        
    if formatted_phone.startswith(('000', '111', '555')) and len(formatted_phone) >= 10:
        if formatted_phone.startswith('55501'):
             return False

    return True

async def scrape_lead_website(url: str) -> str:
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            return result.markdown or ""
    except Exception as e:
        print(f"AI scrape error on {url}: {e}")
        return ""

async def extract_from_html(url: str) -> dict:
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            raw_html = result.html or ""
            
            emails = list(set(re.findall(EMAIL_REGEX, raw_html)))
            
            potential_phones = re.findall(PHONE_REGEX, raw_html)
            valid_phones = {_format_phone_number(p) for p in potential_phones if _is_valid_phone(p)}
            
            return {"emails": emails, "phones": list(valid_phones), "content_preview": raw_html[:500]}
    except Exception as e:
        print(f"HTML scrape error on {url}: {e}")
        return {"emails": [], "phones": [], "content_preview": ""}

async def extract_from_google(company_name: str, website: str) -> dict:
    queries = [
        f'site:{website} "contact" OR "email" OR "phone"',
        f'"{company_name}" contact email',
        f'"{company_name}" phone number'
    ]
    emails, phones = set(), set()
    for q in queries:
        try:
            results = await google_search(q, max_results=3)
            for r in results:
                snippet = r.get("snippet", "") + " " + r.get("url", "")
                emails.update(re.findall(EMAIL_REGEX, snippet))
                
                potential_phones = re.findall(PHONE_REGEX, snippet)
                for p in potential_phones:
                    if _is_valid_phone(p):
                        phones.add(_format_phone_number(p))

        except Exception as e:
            print(f"Google dork error for query '{q}': {e}")
    return {"emails": list(emails), "phones": list(phones)}

async def scrape_url(url: str, company_name: str = "") -> dict:
    print(f"[Scrape] Attempting primary scrape for {url}...")
    ai_scraper_task = asyncio.create_task(scrape_lead_website(url))
    html_task = asyncio.create_task(extract_from_html(url))
    
    ai_markdown, html_results = await asyncio.gather(ai_scraper_task, html_task)

    found_emails = set(html_results.get("emails", []))
    found_phones = set(html_results.get("phones", []))

    if ai_markdown:
        print(f"[Scrape] Primary scrape successful for {url}. Content length: {len(ai_markdown)}.")
    else:
        print(f"[Scrape] Primary scrape failed for {url}. Attempting HTML fallback for contacts.")

    google_results = {"emails": [], "phones": []}
    if not found_emails or not found_phones:
        print(f"[Scrape] Contacts missing from HTML. Using Google Dorking fallback for {url}.")
        google_results = await extract_from_google(company_name, url)
        found_emails.update(google_results.get("emails", []))
        found_phones.update(google_results.get("phones", []))
        if found_emails or found_phones:
            print(f"[Scrape] Google Dorking found contacts for {url}.")
        else:
            print(f"[Scrape] Google Dorking failed to find contacts for {url}.")

    fallback_contacts = {
        "emails": list(found_emails),
        "phones": list(found_phones)
    }

    if not ai_markdown:
        print(f"[Scrape] No AI markdown content. Generating fallback markdown for {url}.")
        fallback_markdown = f"""
Company Name: {company_name or 'N/A'}
Emails: {', '.join(fallback_contacts['emails'])}
Phones: {', '.join(fallback_contacts['phones'])}
Content Preview: {html_results.get('content_preview', '')}
"""
        ai_markdown = fallback_markdown

    return {
        "markdown": ai_markdown,
        "fallback_contacts": fallback_contacts
    }