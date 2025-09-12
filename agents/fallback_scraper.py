import re, asyncio
from crawl4ai import AsyncWebCrawler
from core.google_search import google_search
from db.database import get_scraped_data_from_cache, save_scraped_data_to_cache

EMAIL_REGEX = r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
CONTACT_NO_REGEX = r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}"


def clean_contact_numbers(numbers):
    """Remove junk like timestamps, IDs and keep only valid-looking phone numbers."""
    cleaned = []
    for num in numbers:
        num = re.sub(r"[^\d+]", "", num)  # keep digits and +
        if len(num) < 7 or len(num) > 15:
            continue  # reject too short/too long
        if num.startswith("+") or num.startswith("0"):
            cleaned.append(num)
    return list(set(cleaned))


async def extract_from_html(url: str) -> dict:
    """Regex scrape directly from raw HTML + Markdown (backup if AI missed)."""
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url, parser="playwright")
        html = result.html or ""
        markdown = result.markdown or ""
        combined = html + "\n" + markdown

        emails = set(re.findall(EMAIL_REGEX, combined))
        contact_no = set(re.findall(CONTACT_NO_REGEX, combined))

        # Also catch mailto: and tel:
        emails.update(re.findall(r'href=[\'"]mailto:([^\'"]+)', html))
        contact_no.update(re.findall(r'href=[\'"]tel:([^\'"]+)', html))

        return {
            "emails": list(emails),
            "contact_no": clean_contact_numbers(contact_no),
            "markdown": markdown,
        }


async def extract_from_google(company_name: str, website: str) -> dict:
    """Google dork for missing contact info."""
    queries = [
        f'site:{website} email',
        f'"{company_name}" contact email',
        f'"{company_name}" phone number'
    ]
    emails, contact_no = set(), set()
    for q in queries:
        results = await google_search(q, max_results=5)
        for r in results:
            snippet = r.get("snippet", "") + " " + r.get("url", "")
            emails.update(re.findall(EMAIL_REGEX, snippet))
            contact_no.update(re.findall(CONTACT_NO_REGEX, snippet))
    return {
        "emails": list(emails),
        "contact_no": clean_contact_numbers(contact_no),
    }


async def extract_from_contact_pages(base_url: str) -> dict:
    """Try common contact/about/help pages."""
    suffixes = [
        "contact", "contact-us", "about", "about-us", "team",
        "support", "help", "reach-us", "get-in-touch"
    ]
    found_emails, found_contact_no = set(), set()
    async with AsyncWebCrawler() as crawler:
        for s in suffixes:
            try:
                result = await crawler.arun(url=f"{base_url.rstrip('/')}/{s}", parser="playwright")
                html = result.html or ""
                found_emails.update(re.findall(EMAIL_REGEX, html))
                found_contact_no.update(re.findall(CONTACT_NO_REGEX, html))

                # Capture mailto/tel links
                found_emails.update(re.findall(r'href=[\'"]mailto:([^\'"]+)', html))
                found_contact_no.update(re.findall(r'href=[\'"]tel:([^\'"]+)', html))
            except:
                continue
    return {
        "emails": list(found_emails),
        "contact_no": clean_contact_numbers(found_contact_no),
    }


async def initial_scrape(url: str) -> dict:
    """Quickly scrapes the main URL without Playwright for initial data."""
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
        html = result.html or ""
        markdown = result.markdown or ""
        combined = html + "\n" + markdown

        emails = set(re.findall(EMAIL_REGEX, combined))
        contact_no = set(re.findall(CONTACT_NO_REGEX, combined))

        emails.update(re.findall(r'href=["\"]mailto:([^"\\]+)', html))
        contact_no.update(re.findall(r'href=["\"]tel:([^"\\]+)', html))

        return {
            "emails": list(emails),
            "contact_no": clean_contact_numbers(contact_no),
            "markdown": markdown,
        }


async def enrich_lead(url: str, company_name: str = "") -> dict:
    """Enriches a lead with missing info using deep scraping techniques."""
    final_data = {"emails": [], "contact_no": []}

    # Step 1: Deep scrape the main URL with Playwright
    html_data = await extract_from_html(url)
    final_data["emails"].extend(html_data["emails"])
    final_data["contact_no"].extend(html_data["contact_no"])

    # Step 2: Google dork for contacts if still missing
    if not final_data["emails"] or not final_data["contact_no"]:
        dork_data = await extract_from_google(company_name, url)
        final_data["emails"].extend(dork_data["emails"])
        final_data["contact_no"].extend(dork_data["contact_no"])

    # Step 3: Crawl contact/about pages with Playwright if still missing
    if not final_data["emails"] or not final_data["contact_no"]:
        contact_data = await extract_from_contact_pages(url)
        final_data["emails"].extend(contact_data["emails"])
        final_data["contact_no"].extend(contact_data["contact_no"])

    # Final cleanup
    final_data["emails"] = list(set(final_data["emails"]))
    final_data["contact_no"] = clean_contact_numbers(final_data["contact_no"])

    return final_data
