"""
APIFY scraper service — runs Facebook group scraper actors and returns raw items.

Uses only stdlib (urllib) to stay dependency-free, consistent with the rest of
the codebase.  All failures raise a typed ApifyError subclass so callers can
map them to specific CRV-6xxx error codes.
"""
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from app.logger import get_logger

log = get_logger("carver.apify")

APIFY_BASE_URL = "https://api.apify.com/v2"
_DEFAULT_POLL_INTERVAL = 10   # seconds between run-status polls
_DEFAULT_RUN_TIMEOUT = 600    # seconds before giving up on a run
_DEFAULT_REQUEST_TIMEOUT = 30 # seconds for a single HTTP call


# ── Typed exceptions ─────────────────────────────────────────────────────────

class ApifyError(Exception):
    """Base class for all APIFY-related errors."""
    def __init__(self, message: str, code: str | None = None) -> None:
        super().__init__(message)
        self.code = code


class ApifyKeyMissingError(ApifyError):
    """APIFY API key is not set in the environment."""


class ApifyActorMissingError(ApifyError):
    """No APIFY actor IDs are configured (APIFY_ACTOR_IDS is empty)."""


class ApifyRunFailedError(ApifyError):
    """An actor run finished with a non-SUCCEEDED terminal status."""


class ApifyTimeoutError(ApifyError):
    """An actor run did not complete within the configured timeout window."""


class ApifyHTTPError(ApifyError):
    """APIFY API returned a non-2xx HTTP response."""


class ApifyNetworkError(ApifyError):
    """Network or DNS error reaching api.apify.com."""


# ── Client ───────────────────────────────────────────────────────────────────

class ApifyScraper:
    """
    Thin HTTP client for the APIFY REST API.

    Responsibilities:
      1. Start actor runs for each configured Facebook group scraper.
      2. Poll until each run reaches a terminal status.
      3. Fetch the resulting dataset items.
      4. Aggregate and return all items to the caller.
    """

    def __init__(
        self,
        api_key: str,
        actor_ids: list[str],
        start_urls: list[str] | None = None,
        max_items: int = 0,
        results_limit: int = 0,
        since: str | None = None,
        poll_interval: int = _DEFAULT_POLL_INTERVAL,
        run_timeout: int = _DEFAULT_RUN_TIMEOUT,
    ) -> None:
        self._api_key = api_key
        self._actor_ids = [a.strip() for a in actor_ids if a.strip()]
        self._start_urls = [u.strip() for u in (start_urls or []) if u.strip()]
        self._max_items = max_items         # 0 means unlimited
        self._results_limit = results_limit # per-group post cap (0 = actor default of 20)
        self._since = since                 # ISO datetime — only fetch posts newer than this
        self._poll_interval = poll_interval
        self._run_timeout = run_timeout

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _request(self, method: str, path: str, body: dict | None = None) -> Any:
        """Make a single authenticated request to the APIFY REST API."""
        url = f"{APIFY_BASE_URL}/{path.lstrip('/')}"
        params = urllib.parse.urlencode({"token": self._api_key})
        full_url = f"{url}?{params}"

        data = json.dumps(body).encode() if body is not None else None
        headers: dict[str, str] = {}
        if data:
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(full_url, data=data, headers=headers, method=method)

        try:
            with urllib.request.urlopen(req, timeout=_DEFAULT_REQUEST_TIMEOUT) as resp:
                raw = resp.read().decode()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            snippet = exc.read().decode(errors="replace")[:300]
            raise ApifyHTTPError(
                f"APIFY returned HTTP {exc.code}: {snippet}",
                code=f"HTTP-{exc.code}",
            ) from exc
        except urllib.error.URLError as exc:
            raise ApifyNetworkError(f"APIFY network error: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ApifyError(f"APIFY returned non-JSON response: {exc}") from exc

    def _start_run(self, actor_id: str) -> str:
        """POST to start an actor run and return the run ID."""
        log.info("Starting APIFY actor run | actor_id=%s | urls=%d", actor_id, len(self._start_urls))
        # APIFY URLs use ~ as the user/name separator, not /
        url_id = actor_id.replace("/", "~")
        # Pass startUrls as actor input if configured
        body: dict | None = None
        if self._start_urls or self._max_items or self._results_limit or self._since:
            body = {}
            if self._start_urls:
                body["startUrls"] = [{"url": u} for u in self._start_urls]
            if self._max_items > 0:
                body["maxItems"] = self._max_items
            if self._results_limit > 0:
                body["resultsLimit"] = self._results_limit
            if self._since:
                body["onlyPostsNewerThan"] = self._since
        resp = self._request("POST", f"/acts/{url_id}/runs", body=body)
        run_id = resp.get("data", {}).get("id")
        if not run_id:
            raise ApifyRunFailedError(
                f"APIFY did not return a run ID for actor {actor_id!r}. "
                "Check the actor ID and that the API key has permission to run it."
            )
        log.info("Actor run started | actor_id=%s | run_id=%s", actor_id, run_id)
        return run_id

    def _wait_for_run(self, run_id: str, actor_id: str) -> str:
        """
        Poll until the run reaches a terminal status.
        Returns the defaultDatasetId on success.
        Raises ApifyRunFailedError or ApifyTimeoutError on failure.
        """
        terminal_ok = {"SUCCEEDED"}
        terminal_bad = {"FAILED", "ABORTED", "TIMED-OUT"}
        deadline = time.monotonic() + self._run_timeout

        while time.monotonic() < deadline:
            resp = self._request("GET", f"/actor-runs/{run_id}")
            data = resp.get("data", {})
            run_status = data.get("status", "UNKNOWN")
            log.debug("Run poll | actor_id=%s | run_id=%s | status=%s", actor_id, run_id, run_status)

            if run_status in terminal_ok:
                dataset_id = data.get("defaultDatasetId")
                if not dataset_id:
                    raise ApifyRunFailedError(
                        f"Run {run_id} succeeded but returned no dataset ID."
                    )
                log.info("Run succeeded | run_id=%s | dataset_id=%s", run_id, dataset_id)
                return dataset_id

            if run_status in terminal_bad:
                raise ApifyRunFailedError(
                    f"Actor run {run_id} (actor={actor_id!r}) ended with status {run_status!r}."
                )

            time.sleep(self._poll_interval)

        raise ApifyTimeoutError(
            f"Actor run {run_id} (actor={actor_id!r}) did not complete within "
            f"{self._run_timeout}s. Check the APIFY console for details."
        )

    def _fetch_dataset(self, dataset_id: str) -> list[dict]:
        """GET all items from a dataset and return them as a list of dicts."""
        log.info("Fetching dataset items | dataset_id=%s", dataset_id)
        resp = self._request("GET", f"/datasets/{dataset_id}/items")
        # APIFY may return the items directly as a JSON array or wrapped in {"items": [...]}
        items: list[dict] = resp if isinstance(resp, list) else resp.get("items", [])
        log.info("Dataset fetched | dataset_id=%s | count=%d", dataset_id, len(items))
        return items

    # ── Public API ───────────────────────────────────────────────────────────

    def scrape_all(self) -> list[dict]:
        """
        Run every configured actor and return aggregated dataset items.

        Raises:
            ApifyKeyMissingError    — APIFY_API_KEY not set
            ApifyActorMissingError  — APIFY_ACTOR_IDS is empty
            ApifyRunFailedError     — an actor run ended in a bad state
            ApifyTimeoutError       — a run exceeded the timeout
            ApifyHTTPError          — APIFY returned a non-2xx response
            ApifyNetworkError       — could not reach api.apify.com
            ApifyError              — any other APIFY-related failure
        """
        if not self._api_key:
            raise ApifyKeyMissingError(
                "APIFY_API_KEY is not set. Add it to your .env file."
            )
        if not self._actor_ids:
            raise ApifyActorMissingError(
                "APIFY_ACTOR_IDS is not configured. "
                "Add a comma-separated list of Facebook group scraper actor IDs to your .env."
            )

        all_items: list[dict] = []
        for actor_id in self._actor_ids:
            try:
                run_id = self._start_run(actor_id)
                dataset_id = self._wait_for_run(run_id, actor_id)
                items = self._fetch_dataset(dataset_id)
                all_items.extend(items)
                log.info("Actor scrape complete | actor_id=%s | items=%d", actor_id, len(items))
            except ApifyError:
                raise
            except Exception as exc:
                raise ApifyError(
                    f"Unexpected error while running actor {actor_id!r}: {exc}"
                ) from exc

        log.info("All actors complete | total_items=%d", len(all_items))
        return all_items
