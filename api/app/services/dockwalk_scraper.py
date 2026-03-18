"""
Dockwalk.com job scraper.

Dockwalk's job listings page is JavaScript-rendered (SPA). A direct HTTP fetch
returns only the page shell — no listings. The listing page is fetched via a
local headless Chromium browser (Playwright). Individual listing detail pages
are still fetched directly via httpx.

Uses httpx + stdlib html.parser + Playwright (app.services.playwright_fetch).
"""
import re
from html.parser import HTMLParser

import httpx

from app.logger import get_logger
from app.services.playwright_fetch import fetch_rendered

log = get_logger("carver.dockwalk")

_DEFAULT_URL = "https://www.dockwalk.com/jobs"
_REQUEST_TIMEOUT = 30.0
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class _TextExtractor(HTMLParser):
    """Minimal HTML → plain text extractor."""
    def __init__(self) -> None:
        super().__init__()
        self._parts: list[str] = []
        self._skip_tags = {"script", "style", "head", "noscript"}
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._skip_tags:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip:
            text = data.strip()
            if text:
                self._parts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._parts)


def _html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    return p.get_text()


def _extract_listings(html: str, base_url: str) -> list[dict]:
    """
    Parse job listing cards from Dockwalk HTML.

    Dockwalk listing HTML structure (when JS-rendered):
      Each job card contains: role title, location, salary, agency name, apply link.

    We attempt a best-effort regex extraction. Returns empty list if the page
    is a JS shell (no job cards found).
    """
    items: list[dict] = []

    # Match any /jobs/slug path (slug must be at least 3 chars to skip bare /jobs/ links)
    job_links = re.findall(
        r'href="(/jobs/[a-zA-Z0-9][a-zA-Z0-9\-_/]{2,}[a-zA-Z0-9]/?)"',
        html,
        re.IGNORECASE,
    )

    if not job_links:
        # Fallback: other common crew-job URL patterns
        job_links = re.findall(
            r'href="(/crew-jobs/[^"]+|/vacancies/[^"]+|/positions/[^"]+)"',
            html,
            re.IGNORECASE,
        )

    if not job_links:
        log.warning(
            "Dockwalk: no job listing links found — site may require JS rendering. "
            "Consider adding Dockwalk URL to APIFY_START_URLS instead."
        )
        return []

    seen = set()
    for path in job_links:
        if path in seen:
            continue
        seen.add(path)
        full_url = f"https://www.dockwalk.com{path}"
        items.append({
            "url": full_url,
            "text": "",        # filled by detail fetch
            "contact_email": None,
            "source": "dockwalk",
        })

    return items


def _fetch_detail(client: httpx.Client, url: str) -> dict:
    """Fetch an individual Dockwalk listing page and extract text + email."""
    try:
        resp = client.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        text = _html_to_text(resp.text)
        email_match = re.search(
            r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text
        )
        return {
            "url": url,
            "text": text[:5000],
            "contact_email": email_match.group(0) if email_match else None,
            "source": "dockwalk",
        }
    except Exception as exc:
        log.warning("Dockwalk detail fetch failed | url=%s | error=%s", url, exc)
        return {"url": url, "text": "", "contact_email": None, "source": "dockwalk"}


class DockwalkScraper:
    """
    Scraper for Dockwalk.com job listings.

    Uses a local headless Chromium browser (Playwright) to render the
    JS-heavy listing page. Individual detail pages are fetched via httpx.
    """

    def __init__(self, jobs_url: str = _DEFAULT_URL, scrape_do_token: str = "") -> None:
        self._url = jobs_url
        # scrape_do_token kept for interface compatibility but no longer used

    def scrape(self) -> list[dict]:
        """
        Fetch the Dockwalk jobs listing page, parse job cards, and fetch
        individual listing detail pages for full text and contact email.

        Returns a list of raw item dicts compatible with sync_jobs().
        Returns an empty list (does not raise) if the site is unreachable or
        returns no listings.
        """
        headers = {"User-Agent": _USER_AGENT, "Accept-Language": "en-US,en;q=0.9"}
        try:
            log.info("Dockwalk: fetching listing page via Playwright | url=%s", self._url)
            html = fetch_rendered(self._url, wait_for=".job-card, [class*='job'], article")

            listings = _extract_listings(html, self._url)
            if not listings:
                return []

            results: list[dict] = []
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                for item in listings[:30]:
                    detail = _fetch_detail(client, item["url"])
                    if detail["text"]:
                        results.append(detail)

            log.info("Dockwalk: scraped %d listings", len(results))
            return results

        except Exception as exc:
            log.error("Dockwalk unexpected error | error=%s", exc)
            return []
