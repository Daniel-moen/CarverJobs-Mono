"""
Scrape.do scraper service — fetches web pages via the scrape.do proxy API
and extracts structured data from the HTML.

Uses only stdlib (urllib, html.parser, re, json) — no additional dependencies.
All failures raise a typed ScrapeDoError subclass so callers can map them to
specific error codes.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import Any

from app.logger import get_logger

log = get_logger("carver.scrape_do")

SCRAPE_DO_BASE_URL = "https://api.scrape.do/"
_DEFAULT_REQUEST_TIMEOUT = 60  # scrape.do can be slower with JS rendering


# ── Typed exceptions ──────────────────────────────────────────────────────────

class ScrapeDoError(Exception):
    """Base class for all scrape.do-related errors."""
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ScrapeDoKeyMissingError(ScrapeDoError):
    """SCRAPE_DO_TOKEN is not set in the environment."""


class ScrapeDoURLMissingError(ScrapeDoError):
    """No URLs are configured to scrape."""


class ScrapeDoHTTPError(ScrapeDoError):
    """scrape.do returned a non-2xx HTTP response."""


class ScrapeDoNetworkError(ScrapeDoError):
    """Network or DNS error reaching api.scrape.do."""


# ── HTML parsing helpers ──────────────────────────────────────────────────────

class _MetaTagParser(HTMLParser):
    """Collect <meta> OG/name tags and <title> text from an HTML document."""

    def __init__(self) -> None:
        super().__init__()
        self.og: dict[str, str] = {}
        self.meta: dict[str, str] = {}
        self.title: str = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v for k, v in attrs if v is not None}
        if tag == "meta":
            prop = a.get("property", "")
            name = a.get("name", "")
            content = a.get("content", "")
            if prop.startswith("og:"):
                self.og[prop[3:]] = content
            elif name:
                self.meta[name] = content
        elif tag == "title":
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False


def _extract_fb_group_id(html: str) -> str | None:
    """Pull the numeric Facebook group ID out of app-link meta tags."""
    m = re.search(r'fb://group[/?](\d+)', html)
    return m.group(1) if m else None


def _extract_member_count(html: str) -> str | None:
    """Try to find a member/follower count mentioned in the HTML."""
    m = re.search(r'([\d,]+)\s*(?:members?|followers?)', html, re.IGNORECASE)
    return m.group(0) if m else None


def _parse_facebook_group(url: str, html: str) -> dict:
    """Parse a Facebook group page into a structured dict."""
    parser = _MetaTagParser()
    parser.feed(html)

    group_id = _extract_fb_group_id(html)
    member_count = _extract_member_count(html)

    return {
        "url": url,
        "source": "scrape_do",
        "platform": "facebook_group",
        "group_id": group_id,
        "title": parser.og.get("title") or parser.title.strip() or None,
        "description": (
            parser.og.get("description")
            or parser.meta.get("description")
            or None
        ),
        "image_url": parser.og.get("image") or None,
        "canonical_url": parser.og.get("url") or url,
        "member_count_text": member_count,
        "raw_html_length": len(html),
    }


def _parse_generic(url: str, html: str) -> dict:
    """Parse any page into a generic structured dict from OG/meta tags."""
    parser = _MetaTagParser()
    parser.feed(html)

    return {
        "url": url,
        "source": "scrape_do",
        "title": parser.og.get("title") or parser.title.strip() or None,
        "description": (
            parser.og.get("description")
            or parser.meta.get("description")
            or None
        ),
        "image_url": parser.og.get("image") or None,
        "canonical_url": parser.og.get("url") or url,
        "raw_html_length": len(html),
    }


# ── Client ────────────────────────────────────────────────────────────────────

class ScrapeDoScraper:
    """
    Thin HTTP client for the scrape.do REST API.

    Responsibilities:
      1. Fetch each configured URL via scrape.do (with optional JS rendering
         and residential proxy rotation).
      2. Parse the returned HTML for structured data (OG tags, group metadata).
      3. Return aggregated results to the caller.
    """

    def __init__(
        self,
        token: str,
        urls: list[str],
        render: bool = False,
        super_mode: bool = True,
        geo_code: str = "us",
    ) -> None:
        self._token = token
        self._urls = [u.strip() for u in urls if u.strip()]
        self._render = render
        self._super_mode = super_mode
        self._geo_code = geo_code

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _fetch(self, url: str) -> str:
        """Fetch one URL through the scrape.do proxy and return raw HTML."""
        params: dict[str, str] = {"token": self._token, "url": url}
        if self._render:
            params["render"] = "true"
        if self._super_mode:
            params["super"] = "true"
        if self._geo_code:
            params["geoCode"] = self._geo_code

        full_url = f"{SCRAPE_DO_BASE_URL}?{urllib.parse.urlencode(params)}"
        log.info("Fetching via scrape.do | url=%s render=%s super=%s", url, self._render, self._super_mode)

        req = urllib.request.Request(full_url, headers={"Accept": "text/html,application/xhtml+xml"})
        try:
            with urllib.request.urlopen(req, timeout=_DEFAULT_REQUEST_TIMEOUT) as resp:
                html = resp.read().decode(errors="replace")
                log.info("Fetch OK | url=%s | bytes=%d", url, len(html))
                return html
        except urllib.error.HTTPError as exc:
            snippet = exc.read().decode(errors="replace")[:300]
            raise ScrapeDoHTTPError(
                f"scrape.do returned HTTP {exc.code} for {url!r}: {snippet}",
                code=f"HTTP-{exc.code}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ScrapeDoNetworkError(
                f"scrape.do network error fetching {url!r}: {exc.reason}"
            ) from exc

    def _parse(self, url: str, html: str) -> dict:
        """Route URL to the appropriate HTML parser."""
        if "facebook.com/groups" in url:
            return _parse_facebook_group(url, html)
        return _parse_generic(url, html)

    # ── Public API ────────────────────────────────────────────────────────────

    def scrape_all(self) -> list[dict]:
        """
        Fetch and parse every configured URL. Returns a list of structured dicts.

        Raises:
            ScrapeDoKeyMissingError  — SCRAPE_DO_TOKEN not set
            ScrapeDoURLMissingError  — SCRAPE_DO_URLS is empty
            ScrapeDoHTTPError        — scrape.do returned a non-2xx response
            ScrapeDoNetworkError     — could not reach api.scrape.do
            ScrapeDoError            — any other scrape.do-related failure
        """
        if not self._token:
            raise ScrapeDoKeyMissingError(
                "SCRAPE_DO_TOKEN is not set. Add it to your .env file."
            )
        if not self._urls:
            raise ScrapeDoURLMissingError(
                "SCRAPE_DO_URLS is not configured. "
                "Add a comma-separated list of URLs to scrape to your .env."
            )

        results: list[dict] = []
        for url in self._urls:
            try:
                html = self._fetch(url)
                parsed = self._parse(url, html)
                results.append(parsed)
                log.info("Parsed OK | url=%s | title=%r", url, parsed.get("title"))
            except ScrapeDoError:
                raise
            except Exception as exc:
                raise ScrapeDoError(
                    f"Unexpected error while scraping {url!r}: {exc}"
                ) from exc

        log.info("All URLs scraped | total=%d", len(results))
        return results
