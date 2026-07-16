"""
Shared Playwright utility for fetching JS-rendered pages.

Uses headless Chromium via the sync Playwright API. Each call spawns and
closes its own browser instance — this is intentional to avoid state leakage
between scraper runs and keep memory usage predictable.

Usage:
    from app.services.playwright_fetch import fetch_rendered
    html = fetch_rendered("https://example.com", wait_for=".job-card")
"""
from __future__ import annotations

from app.logger import get_logger

log = get_logger("carver.playwright")

_DEFAULT_TIMEOUT = 30_000  # ms
_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Chromium args required for headless Docker environments
_CHROMIUM_ARGS = [
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-gpu",
    "--single-process",
]


def fetch_rendered(
    url: str,
    *,
    wait_for: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    return_cookies: bool = False,
    wait_until: str = "networkidle",
) -> str | tuple[str, dict[str, str]]:
    """
    Fetch a URL with a headless Chromium browser and return the rendered HTML.

    Args:
        url:            The URL to fetch.
        wait_for:       Optional CSS selector to wait for before capturing HTML.
                        If it doesn't appear within 5 s, HTML is returned as-is.
        timeout:        Navigation timeout in milliseconds (default 30 s).
        return_cookies: When True, returns (html, cookies_dict) instead of just html.
        wait_until:     Playwright navigation wait state — one of "load",
                        "domcontentloaded", "networkidle", "commit".
                        Defaults to "networkidle". Some sites (e.g. Yotspot) load
                        ad/analytics traffic that never lets the network go idle,
                        causing a 30 s timeout; those callers should pass
                        "domcontentloaded" instead.

    Returns:
        HTML string, or (html, cookies) tuple when return_cookies=True.

    Raises:
        Any Playwright or network error propagates to the caller.
    """
    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    log.info("Playwright: fetching | url=%s", url)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        try:
            page = browser.new_page(user_agent=_USER_AGENT)
            page.goto(url, timeout=timeout, wait_until=wait_until)
            if wait_for:
                try:
                    page.wait_for_selector(wait_for, timeout=5_000)
                except PWTimeout:
                    log.debug("Playwright: selector '%s' not found — returning current HTML", wait_for)
            html = page.content()
            log.info("Playwright: fetched OK | url=%s | bytes=%d", url, len(html))
            if return_cookies:
                raw_cookies = page.context.cookies()
                cookies = {c["name"]: c["value"] for c in raw_cookies}
                return html, cookies
            return html
        finally:
            browser.close()


def fetch_many(
    urls: list[str],
    *,
    first_url: str | None = None,
    timeout: int = _DEFAULT_TIMEOUT,
    page_timeout: int = 20_000,
) -> list[tuple[str, str]]:
    """
    Fetch multiple URLs in a single browser session (shared cookies/TLS state).

    Useful when a site ties session authentication to the original TLS connection
    (e.g. Yotspot — fetching the listing page first sets session cookies that
    must be reused for all profile page requests within the same browser context).

    Args:
        urls:         List of URLs to fetch.
        first_url:    Optional warm-up URL to visit before fetching urls.
                      Establishes a session (cookies, localStorage) that is then
                      shared for all subsequent pages.
        timeout:      Initial navigation timeout for first_url in ms.
        page_timeout: Per-page timeout for urls in ms (default 20 s).

    Returns:
        List of (url, html) tuples in the same order as urls.
        Failed pages return (url, "") instead of raising.
    """
    import random
    import time

    from playwright.sync_api import TimeoutError as PWTimeout
    from playwright.sync_api import sync_playwright

    results: list[tuple[str, str]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=_CHROMIUM_ARGS)
        try:
            context = browser.new_context(user_agent=_USER_AGENT)
            page = context.new_page()

            if first_url:
                log.info("Playwright session: warming up | url=%s", first_url)
                # Warm-up only needs to establish session cookies, so wait for the
                # DOM rather than full network idle — sites like Yotspot never reach
                # "networkidle" (persistent ad/analytics traffic) and would time out.
                page.goto(first_url, timeout=timeout, wait_until="domcontentloaded")
                log.info("Playwright session: warm-up OK | bytes=%d", len(page.content()))

            for i, url in enumerate(urls):
                # Rate-limit sequential requests: hammering profile pages back-to-back
                # in one session trips Cloudflare's "just a moment" challenge (observed
                # ~4/6 profiles blocked on Yotspot). A short randomised pause between
                # pages (not before the first) keeps the request cadence human-like.
                if i > 0:
                    time.sleep(random.uniform(2.0, 4.0))
                try:
                    log.debug("Playwright session: fetching | url=%s", url)
                    page.goto(url, timeout=page_timeout, wait_until="load")
                    html = page.content()
                    log.debug("Playwright session: OK | url=%s | bytes=%d", url, len(html))
                    results.append((url, html))
                except PWTimeout:
                    log.warning("Playwright session: timeout | url=%s", url)
                    results.append((url, ""))
                except Exception as exc:
                    log.warning("Playwright session: failed | url=%s | error=%s", url, exc)
                    results.append((url, ""))

        finally:
            browser.close()

    return results
