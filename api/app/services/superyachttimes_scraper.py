"""
Reed.co.uk marine/yacht job scraper.

Reed.co.uk is the UK's largest job board and has a dedicated marine/yacht
section with yacht broker, captain, engineer, and crew roles. Job detail
pages are server-rendered, include full JSON-LD structured data, and are
accessible without JS rendering or authentication.

Note: Reed uses an on-site apply flow so recruiter emails are rarely exposed.
Jobs are stored with the Reed listing URL as application_url so crew can
apply directly.

Registered as source="reed" in the jobs table.

Uses only httpx (already in requirements) + stdlib re.
"""
import re

import httpx

from app.logger import get_logger

log = get_logger("carver.reed")

_SEARCH_URLS = [
    "https://www.reed.co.uk/jobs/superyacht-jobs",
    "https://www.reed.co.uk/jobs/yacht-captain-jobs",
    "https://www.reed.co.uk/jobs/yacht-crew-jobs",
]
_BASE_URL = "https://www.reed.co.uk"
_REQUEST_TIMEOUT = 30.0
_MAX_LISTINGS = 40
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# Job titles that clearly don't belong in a yacht crew context — skip them
_SKIP_TITLE_KEYWORDS = {
    "sous chef", "cruise consultant", "cruise sales", "cruise specialist", "cruise team",
    "luxury travel", "luxury villa", "luxury cruise", "travel consultant", "travel designer",
    "travel specialist", "marine claims", "marine cargo", "marine hull",
    "marine account", "model maker", "sc cleared", "propeller engineer",
    "naval architect", "boatyard", "ocean export", "freelance event crew",
    "operations assistant boating", "customer service assistant boating",
    "boat part sales", "divisional director", "junior yacht underwriter",
    "crew planner", "ex cabin", "cabin crew",
}

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SITE_DOMAIN = "reed.co.uk"


def _strip_html(html: str) -> str:
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", clean)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_email(html: str) -> str | None:
    for m in re.finditer(r'href=["\']mailto:([^"\'?\s]+)', html, re.IGNORECASE):
        email = m.group(1).strip()
        if email and _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email
    for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', html, re.IGNORECASE):
        email = m.group(1).strip()
        if _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email
    text = _strip_html(html)
    for m in _EMAIL_RE.finditer(text):
        email = m.group(0)
        if _SITE_DOMAIN not in email:
            return email
    return None


def _is_relevant_url(path: str) -> bool:
    """
    Pre-screen job URLs by slug before fetching the detail page.
    Reject jobs whose slug matches known irrelevant title patterns.
    """
    slug = path.lower().replace("-", " ")
    return not any(kw in slug for kw in _SKIP_TITLE_KEYWORDS)


def _extract_job_urls(html: str) -> list[str]:
    """Extract individual Reed job listing URLs from a search results page."""
    # Reed job links look like /jobs/job-title/12345678
    paths = re.findall(r'href="(/jobs/[a-zA-Z0-9\-]+/\d+)[^"]*"', html)
    seen: set[str] = set()
    results: list[str] = []
    for path in paths:
        if path not in seen and _is_relevant_url(path):
            seen.add(path)
            results.append(f"{_BASE_URL}{path}")
    return results


def _fetch_detail(client: httpx.Client, url: str) -> dict | None:
    """Fetch a single Reed job page and extract text + email."""
    try:
        resp = client.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text
        text = _strip_html(html)
        if not text or len(text) < 100:
            return None
        return {
            "url": url,
            "text": text[:5000],
            "contact_email": _extract_email(html),
            "source": "reed",
        }
    except Exception as exc:
        log.debug("Reed detail fetch failed | url=%s | error=%s", url, exc)
        return None


class SuperYachtTimesScraper:
    """
    Scraper for Reed.co.uk marine/yacht job listings.

    Registered under the 'superyachttimes' slot but targets Reed.co.uk
    which provides accessible server-rendered job pages.
    """

    def scrape(self) -> list[dict]:
        """
        Fetch Reed yacht/marine job listings and return raw item dicts.

        Does not raise — returns an empty list on any failure.
        """
        headers = {
            "User-Agent": _USER_AGENT,
            "Accept-Language": "en-GB,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        try:
            with httpx.Client(headers=headers, follow_redirects=True) as client:
                all_job_urls: list[str] = []
                seen_urls: set[str] = set()

                for search_url in _SEARCH_URLS:
                    try:
                        log.info("Reed: fetching search page | url=%s", search_url)
                        resp = client.get(search_url, timeout=_REQUEST_TIMEOUT)
                        resp.raise_for_status()
                        for url in _extract_job_urls(resp.text):
                            if url not in seen_urls:
                                seen_urls.add(url)
                                all_job_urls.append(url)
                    except Exception as exc:
                        log.debug("Reed search page failed | url=%s | error=%s", search_url, exc)

                log.info("Reed: found %d unique job URLs", len(all_job_urls))

                if not all_job_urls:
                    log.warning("Reed: no job URLs found")
                    return []

                results: list[dict] = []
                for url in all_job_urls[:_MAX_LISTINGS]:
                    item = _fetch_detail(client, url)
                    if item:
                        results.append(item)

                log.info("Reed: scraped %d job listings", len(results))
                return results

        except httpx.RequestError as exc:
            log.warning("Reed request error | error=%s", exc)
            return []
        except Exception as exc:
            log.error("Reed unexpected error | error=%s", exc)
            return []
