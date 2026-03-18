"""
Viking Crew job scraper.

Viking Crew (vikingcrew.com) is one of the world's largest yacht and
superyacht crew recruitment agencies, with hundreds of live vacancies
across all departments and vessel types.

Scraping strategy:
  1. Fetch the vacancies/jobs listing page (Playwright) to find job URLs.
  2. Fetch each job detail page via httpx and extract description + email.
  3. Return items in the standard sync_jobs() format.

Uses httpx + stdlib re + Playwright (app.services.playwright_fetch).
"""
import re

import httpx

from app.logger import get_logger
from app.services.playwright_fetch import fetch_rendered

log = get_logger("carver.vikingcrew")

_LISTING_URL = "https://www.vikingcrew.com/job-search/"
_BASE_URL = "https://www.vikingcrew.com"
_REQUEST_TIMEOUT = 30.0
_MAX_LISTINGS = 50
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SITE_DOMAIN = "vikingcrew.com"


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

    Filters out the site's own domain addresses.
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
    Extract individual job page paths from the Viking Crew listing page.

    Viking Crew typically uses paths like /vacancies/job-title-id or /jobs/slug.
    """
    patterns = [
        r'href="(/vacancies/[a-zA-Z0-9\-_]+(?:/[a-zA-Z0-9\-_]+)*/?)(?:["\?#])',
        r'href="(/jobs/[a-zA-Z0-9\-_]+(?:/[a-zA-Z0-9\-_]+)*/?)(?:["\?#])',
        r'href="(/vacancy/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
        r'href="(/job-detail/[a-zA-Z0-9\-_/]+/?)(?:["\?#])',
    ]
    seen: set[str] = set()
    results: list[str] = []
    for pattern in patterns:
        for path in re.findall(pattern, html, re.IGNORECASE):
            # Skip the listing page itself
            if path.rstrip("/") in ("/vacancies", "/jobs"):
                continue
            if path in seen:
                continue
            seen.add(path)
            results.append(f"{_BASE_URL}{path}")
    return results


def _fetch_detail(client: httpx.Client, url: str) -> dict | None:
    """Fetch a single Viking Crew job page and extract text + email."""
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
            "source": "vikingcrew",
        }
    except Exception as exc:
        log.debug("Viking Crew detail fetch failed | url=%s | error=%s", url, exc)
        return None


class VikingCrewScraper:
    """
    Scraper for Viking Crew (vikingcrew.com) yacht crew job listings.

    Uses a local headless Chromium browser (Playwright) to render the
    JS-heavy listing page. Individual detail pages are fetched via httpx.
    """

    def __init__(self, listing_url: str = _LISTING_URL, scrape_do_token: str = "") -> None:
        self._url = listing_url
        # scrape_do_token kept for interface compatibility but no longer used

    def scrape(self) -> list[dict]:
        """
        Fetch Viking Crew job listings and return raw item dicts for sync_jobs().

        Does not raise — returns an empty list on any failure.
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            log.info("Viking Crew: fetching listing page via Playwright | url=%s", self._url)
            html = fetch_rendered(self._url, wait_for="[class*='job'], [class*='vacancy'], article")
            job_urls = _extract_job_urls(html)
            log.info("Viking Crew: found %d job URLs", len(job_urls))

            if not job_urls:
                log.warning("Viking Crew: no job URLs found — site structure may have changed")
                return []

            results: list[dict] = []
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                for url in job_urls[:_MAX_LISTINGS]:
                    item = _fetch_detail(client, url)
                    if item:
                        results.append(item)

            log.info("Viking Crew: scraped %d job listings", len(results))
            return results

        except Exception as exc:
            log.warning("Viking Crew scrape failed | error=%s", exc)
            return []
