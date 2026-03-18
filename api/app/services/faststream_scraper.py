"""
Faststream Recruitment yacht/marine crew job scraper.

Faststream publishes a machine-readable XML sitemap of all live jobs at
  https://www.faststream.com/job/sitemap.xml

This is far more reliable than scraping JS-rendered listing pages (which
return no job links in static HTML). The sitemap gives us all 180+ live
roles; we filter to maritime/yacht-crew positions by URL slug keyword,
then fetch each detail page via Playwright to get:
  - Full job description (loaded dynamically by JS)
  - Recruiter contact email (also JS-rendered, e.g. joeleen.rowe@faststream.com)
  - Contact name (e.g. "Joeleen Rowe, Lead Recruitment Consultant")

Registered as source="faststream" in the jobs table.
"""
import re
import urllib.request

from app.logger import get_logger
from app.services.playwright_fetch import fetch_many

log = get_logger("carver.faststream")

_SITEMAP_URL = "https://www.faststream.com/job/sitemap.xml"
_BASE_URL = "https://www.faststream.com"
_REQUEST_TIMEOUT = 30.0
_MAX_LISTINGS = 60
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# URL slug must contain one of these to be kept (yacht-specific only)
_YACHT_KEYWORDS = {
    "yacht", "superyacht", "super-yacht",
}

# Supplementary keywords — only kept when combined with a yacht keyword above
# or when the slug strongly implies on-board yacht crew
_CREW_SECONDARY = {
    "captain", "chief-stew", "deckhand", "bosun", "purser", "galley",
    "chief-stew", "stew", "steward",
}

# Always skip these even if they contain a yacht keyword
_SKIP_SLUGS = {
    "sous-chef", "sales", "consultant", "advisory", "manager",
    "shore", "shoreside", "office", "accounts", "finance",
}


def _is_crew_url(url: str) -> bool:
    """Keep only on-board yacht/superyacht crew roles from Faststream."""
    slug = url.lower()
    if any(skip in slug for skip in _SKIP_SLUGS):
        return False
    # Must contain a yacht-specific keyword
    return any(kw in slug for kw in _YACHT_KEYWORDS)


def _fetch_job_urls_from_sitemap() -> list[str]:
    """Fetch the Faststream job sitemap and return filtered crew job URLs."""
    req = urllib.request.Request(
        _SITEMAP_URL,
        headers={"User-Agent": _USER_AGENT, "Accept": "text/xml,application/xml,*/*"},
    )
    with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
        xml = resp.read(1_000_000).decode(errors="replace")
    all_urls = re.findall(r"<loc>(https://www\.faststream\.com/job/[^<]+)</loc>", xml)
    crew_urls = [u for u in all_urls if _is_crew_url(u)]
    log.info("Faststream sitemap: total=%d  crew-relevant=%d", len(all_urls), len(crew_urls))
    return crew_urls


def _extract_email_from_rendered(html: str) -> str | None:
    """
    Extract recruiter contact email from a Playwright-rendered Faststream page.

    Faststream renders recruiter emails in patterns like:
      "Contact Email: joeleen.rowe@faststream.com"
    All emails on a Faststream page ARE faststream.com addresses — these are
    the recruiter's direct email, which is exactly what we want.
    """
    # Look for "Contact Email:" pattern first (most reliable)
    for m in re.finditer(r'Contact\s+Email\s*:\s*([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})', html, re.IGNORECASE):
        return m.group(1).strip()
    # Fall back to any email in the rendered HTML (recruiter contact)
    for m in re.finditer(r'href=["\']mailto:([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})["\']', html, re.IGNORECASE):
        return m.group(1).strip()
    # General scan
    for m in _EMAIL_RE.finditer(html):
        return m.group(0)
    return None


def _parse_detail(url: str, html: str) -> dict | None:
    """
    Parse a Playwright-rendered Faststream job page.

    Extracts the full job description and recruiter contact email from
    the JS-rendered page content.
    """
    # Strip script/style blocks
    clean = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", clean)
    text = re.sub(r"\s+", " ", text).strip()

    # Guard against Cloudflare / security challenge pages
    if "cloudflare" in text.lower() or "security verification" in text.lower() or "just a moment" in text.lower():
        log.debug("Faststream: Cloudflare block detected | url=%s", url)
        return None

    if not text or len(text) < 200:
        return None

    email = _extract_email_from_rendered(html)

    return {
        "url": url,
        "text": text[:5000],
        "contact_email": email,
        "source": "faststream",
    }


class FaststreamScraper:
    """
    Scraper for Faststream.com yacht/marine crew job listings.

    Uses the published XML sitemap to discover live job URLs, then fetches
    each page via Playwright to get the full JS-rendered job description and
    the recruiter's direct contact email.
    """

    def scrape(self) -> list[dict]:
        """
        Fetch Faststream yacht crew job listings and return raw item dicts.

        Does not raise — returns an empty list on any failure.
        """
        try:
            log.info("Faststream: fetching job sitemap | url=%s", _SITEMAP_URL)
            job_urls = _fetch_job_urls_from_sitemap()

            if not job_urls:
                log.warning("Faststream: no crew job URLs found in sitemap")
                return []

            urls_to_fetch = job_urls[:_MAX_LISTINGS]
            log.info("Faststream: fetching %d detail pages via Playwright", len(urls_to_fetch))

            # Fetch all detail pages in a single browser session for efficiency
            pages = fetch_many(urls_to_fetch, page_timeout=20_000)

            results: list[dict] = []
            for url, html in pages:
                if not html:
                    continue
                item = _parse_detail(url, html)
                if item:
                    results.append(item)

            log.info("Faststream: scraped %d job listings", len(results))
            return results

        except Exception as exc:
            log.error("Faststream unexpected error | error=%s", exc)
            return []
