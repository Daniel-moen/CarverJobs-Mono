"""
CrewFinders.com job scraper.

CrewFinders is one of the oldest and most established yacht crew placement
agencies, with a public job board listing positions for all departments.

Scraping strategy:
  1. Fetch the jobs listing page to find individual job URLs.
  2. Fetch each job detail page and extract full text + contact info.
  3. Return items in the standard sync_jobs() format.

Uses only httpx (already in requirements) + stdlib re.
"""
import re

import httpx

from app.logger import get_logger

log = get_logger("carver.crewfinders")

_BASE_URL = "https://www.crewfinders.com"
# CrewFinders publishes jobs across per-role category pages (static .shtml)
_CATEGORY_PAGES = [
    "https://www.crewfinders.com/yacht-captains.shtml",
    "https://www.crewfinders.com/yacht-chief-stew-purser-crew.shtml",
    "https://www.crewfinders.com/yacht-engineers.shtml",
    "https://www.crewfinders.com/yacht-chefs-cooks.shtml",
    "https://www.crewfinders.com/yacht-crew-job-positions.shtml",
]
_REQUEST_TIMEOUT = 30.0
_MAX_LISTINGS = 50
_USER_AGENT = (
    "Mozilla/5.0 (compatible; CarverBot/1.0; +https://carver.app)"
)


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SITE_DOMAIN = "crewfinders.com"


def _strip_html(html: str) -> str:
    """Strip HTML tags and collapse whitespace into plain text."""
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", clean)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_email(html: str) -> str | None:
    """
    Extract a contact email from raw HTML, trying the most reliable sources first:
      1. mailto: href attributes (most reliable — explicitly intended for contact)
      2. JSON-LD structured data (schema.org email field)
      3. Plain text scan of the full page body (fallback)

    Filters out the site's own domain addresses (info@, noreply@, etc.).
    """
    # 1. mailto: links
    for m in re.finditer(r'href=["\']mailto:([^"\'?\s]+)', html, re.IGNORECASE):
        email = m.group(1).strip()
        if email and _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email

    # 2. JSON-LD "email" field
    for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', html, re.IGNORECASE):
        email = m.group(1).strip()
        if _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email

    # 3. Full-text scan
    text = _strip_html(html)
    for m in _EMAIL_RE.finditer(text):
        email = m.group(0)
        if _SITE_DOMAIN not in email:
            return email

    return None


def _extract_job_urls(html: str) -> list[str]:
    """
    Extract individual job page paths from the CrewFinders listing page.

    Tries multiple common link patterns used by crew/job boards.
    """
    patterns = [
        r'href="(/jobs/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
        r'href="(/vacancies/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
        r'href="(/job/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
        r'href="(/crew-jobs/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
    ]
    seen: set[str] = set()
    results: list[str] = []
    for pattern in patterns:
        for path in re.findall(pattern, html, re.IGNORECASE):
            # Exclude the listing page itself and pagination links
            if path in seen or path.rstrip("/") in ("/jobs", "/vacancies"):
                continue
            seen.add(path)
            results.append(f"{_BASE_URL}{path}")
    return results


def _fetch_detail(client: httpx.Client, url: str) -> dict | None:
    """Fetch a single CrewFinders job page and extract text + email."""
    try:
        resp = client.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        text = _strip_html(html)
        if not text or len(text) < 80:
            return None
        return {
            "url": url,
            "text": text[:5000],
            "contact_email": _extract_email(html),
            "source": "crewfinders",
        }
    except Exception as exc:
        log.debug("CrewFinders detail fetch failed | url=%s | error=%s", url, exc)
        return None


class CrewFindersScraper:
    """
    Scraper for CrewFinders.com yacht crew job listings.

    CrewFinders publishes available positions across per-role static pages
    (e.g. /yacht-captains.shtml). We scrape all category pages and then
    follow any internal links that look like individual position entries.
    """

    def __init__(self) -> None:
        self._category_pages = _CATEGORY_PAGES

    def scrape(self) -> list[dict]:
        """
        Fetch CrewFinders job listings from all category pages.

        Does not raise — returns an empty list on any failure.
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            all_items: list[dict] = []
            seen_urls: set[str] = set()

            with httpx.Client(headers=headers, follow_redirects=True) as client:
                # Collect job URLs from all category pages
                all_job_urls: list[str] = []
                for cat_url in self._category_pages:
                    try:
                        log.info("CrewFinders: fetching category page | url=%s", cat_url)
                        resp = client.get(cat_url, timeout=_REQUEST_TIMEOUT)
                        resp.raise_for_status()
                        for u in _extract_job_urls(resp.text):
                            if u not in seen_urls:
                                seen_urls.add(u)
                                all_job_urls.append(u)
                        # Also treat the category page itself as a job item
                        # if it has substantial job content
                        item = _fetch_detail(client, cat_url)
                        if item and len(item.get("text", "")) > 200:
                            item["url"] = cat_url
                            all_items.append(item)
                    except Exception as exc:
                        log.debug("CrewFinders category fetch failed | url=%s | error=%s", cat_url, exc)

                log.info("CrewFinders: found %d additional job URLs across categories", len(all_job_urls))

                for url in all_job_urls[:_MAX_LISTINGS]:
                    item = _fetch_detail(client, url)
                    if item:
                        all_items.append(item)

            log.info("CrewFinders: scraped %d items total", len(all_items))
            return all_items

        except httpx.RequestError as exc:
            log.warning("CrewFinders request error | error=%s", exc)
            return []
        except Exception as exc:
            log.error("CrewFinders unexpected error | error=%s", exc)
            return []
