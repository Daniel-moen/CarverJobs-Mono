"""
Yotspot.com job scraper (registered as the "workonayacht" source).

Yotspot is the largest public yacht crew job board, with 2,300+ live listings
available without authentication. www.workonayacht.com redirected here.

Yotspot blocks direct bot access (403). The listing page is fetched via a
local headless Chromium browser (Playwright). Individual profile pages are
still accessible via plain httpx.

Scraping strategy:
  1. Fetch the job-search listing page (Playwright) to get job profile IDs.
  2. Fetch each profile page directly via httpx to get full description + email.
  3. Return items in the standard sync_jobs() format.

Uses httpx + stdlib re + Playwright (app.services.playwright_fetch).
"""
import re

import httpx

from app.logger import get_logger
from app.services.playwright_fetch import fetch_many, fetch_rendered

log = get_logger("carver.workonayacht")

_LISTING_URL = "https://www.yotspot.com/job-search.html"
_PROFILE_BASE = "https://www.yotspot.com/job-profile/"
_REQUEST_TIMEOUT = 30.0
_MAX_LISTINGS = 60
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
_SITE_DOMAIN = "yotspot.com"


def _extract_email(html: str) -> str | None:
    """
    Extract a contact email from raw HTML:
      1. mailto: href attributes
      2. JSON-LD "email" field
      3. Full-text scan fallback
    Filters out yotspot.com domain addresses.
    """
    for m in re.finditer(r'href=["\']mailto:([^"\'?\s]+)', html, re.IGNORECASE):
        email = m.group(1).strip()
        if email and _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email
    for m in re.finditer(r'"email"\s*:\s*"([^"]+)"', html, re.IGNORECASE):
        email = m.group(1).strip()
        if _EMAIL_RE.match(email) and _SITE_DOMAIN not in email:
            return email
    clean = re.sub(r"<[^>]+>", " ", html)
    for m in _EMAIL_RE.finditer(clean):
        email = m.group(0)
        if _SITE_DOMAIN not in email:
            return email
    return None


def _extract_job_ids(html: str) -> list[str]:
    """
    Extract Yotspot job profile IDs from the job-search HTML.

    Yotspot listing links look like:
      /job-profile/3928767.html?js=1
    """
    return re.findall(r"/job-profile/(\d+)\.html", html)


def _fetch_profile_text(client: httpx.Client, job_id: str) -> dict | None:
    """
    Fetch an individual Yotspot job profile page and extract all relevant text.

    Returns a raw item dict compatible with sync_jobs(), or None on failure.
    """
    url = f"{_PROFILE_BASE}{job_id}.html"
    try:
        resp = client.get(url, timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
        html = resp.text

        html_clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", html_clean)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        if not text or len(text) < 100:
            return None

        return {
            "url": url,
            "text": text[:5000],
            "contact_email": _extract_email(html),
            "source": "workonayacht",
        }

    except httpx.HTTPStatusError as exc:
        log.debug("Yotspot profile fetch failed | status=%d | id=%s", exc.response.status_code, job_id)
        return None
    except httpx.RequestError as exc:
        log.debug("Yotspot profile request error | error=%s | id=%s", exc, job_id)
        return None
    except Exception as exc:
        log.warning("Yotspot profile unexpected error | error=%s | id=%s", exc, job_id)
        return None


class WorkOnAYachtScraper:
    """
    Scraper for Yotspot.com yacht crew job listings.

    Uses a local headless Chromium browser (Playwright) to bypass Yotspot's
    bot detection on the listing page. Individual profile pages are fetched
    directly via httpx.

    Registered as source="workonayacht" in the jobs table.
    """

    def __init__(self, listing_url: str = _LISTING_URL, scrape_do_token: str = "") -> None:
        self._url = listing_url
        # scrape_do_token kept for interface compatibility but no longer used

    def scrape(self) -> list[dict]:
        """
        Fetch Yotspot job listings and return raw item dicts for sync_jobs().

        Strategy:
          1. Use Playwright to render the listing page (establishes session).
          2. Fetch each profile URL within the same browser session so Yotspot's
             anti-bot (TLS fingerprint + session binding) is satisfied.
             Plain httpx gets 403 even with cookies — the session must stay within
             the same Playwright browser context.

        Does not raise — returns an empty list on any failure.
        """
        try:
            log.info("Yotspot: fetching listing page via Playwright | url=%s", self._url)
            # Yotspot loads ad/analytics traffic that never lets the network go
            # idle, so the default "networkidle" wait times out (30 s) and the
            # listing comes back empty. "domcontentloaded" fires as soon as the
            # DOM (which already contains the job-profile links) is parsed.
            listing_html = fetch_rendered(
                self._url,
                wait_for=".job-search-result, [class*='job']",
                wait_until="domcontentloaded",
            )

            job_ids = _extract_job_ids(listing_html)
            seen: set[str] = set()
            unique_ids: list[str] = []
            for jid in job_ids:
                if jid not in seen:
                    seen.add(jid)
                    unique_ids.append(jid)

            log.info("Yotspot: found %d unique job IDs", len(unique_ids))

            if not unique_ids:
                log.warning("Yotspot: no job IDs found — site may have changed structure")
                return []

            # Fetch all profile pages in the same browser session (shared TLS + cookies)
            profile_urls = [
                f"{_PROFILE_BASE}{job_id}.html" for job_id in unique_ids[:_MAX_LISTINGS]
            ]
            fetched_pages = fetch_many(profile_urls, first_url=self._url)

            results: list[dict] = []
            for url, html in fetched_pages:
                if not html:
                    continue
                html_clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
                text = re.sub(r"<[^>]+>", " ", html_clean)
                text = re.sub(r"[ \t]+", " ", text)
                text = re.sub(r"\n{3,}", "\n\n", text)
                text = text.strip()
                # Reject Cloudflare / anti-bot challenge pages
                if any(kw in text.lower() for kw in ("cloudflare", "security verification", "just a moment", "ray id")):
                    log.debug("Yotspot: Cloudflare block detected | url=%s", url)
                    continue
                if len(text) < 200:
                    continue
                results.append({
                    "url": url,
                    "text": text[:5000],
                    "contact_email": _extract_email(html),
                    "source": "workonayacht",
                })

            log.info("Yotspot: scraped %d job profiles", len(results))
            return results

        except Exception as exc:
            log.error("Yotspot unexpected error | error=%s", exc)
            return []
