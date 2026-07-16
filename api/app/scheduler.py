"""
Scraper scheduler — runs a full scrape cycle every 12 hours.

Cycle includes:
  1. Facebook groups via Apify (raw fetch, no date filter sent to actor).
  2. Dockwalk.com job listings (if enabled).
  3. WorkOnAYacht.com job listings (if enabled).
  4. CrewFinders (if enabled).
  5. Viking Crew (if enabled).
  6. Faststream (if enabled).
  7. Reed/SuperYachtTimes (if enabled).

Deduplication is handled by job_sync (content_hash, job_fingerprint, URL).
State is held in-memory and exposed via get_scraper_state() for the
/scraper/status admin endpoint.
"""
import asyncio
from datetime import datetime, timezone

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.scheduler")

SCRAPE_INTERVAL_SECONDS = 12 * 60 * 60  # 12 hours

# ── In-memory state ──────────────────────────────────────────────────────────

_scrape_lock = asyncio.Lock()

_state: dict = {
    "running": False,
    "last_run_at": None,
    "last_status": "never_run",  # "ok" | "error" | "never_run"
    "last_error": None,          # {"code": "CRV-6xxx", "detail": "..."}
    "last_counts": None,         # {"created": n, "skipped": n, "errors": n}
    "next_run_at": None,
    "source_history": [],        # last 100 per-source run entries
}

_HISTORY_MAX = 100


def get_scraper_state() -> dict:
    s = dict(_state)
    s["source_history"] = list(_state["source_history"])
    return s


def _record_source(source: str, fetched: int, created: int, skipped: int) -> None:
    """Append a single source run result to the rolling history."""
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "fetched": fetched,
        "created": created,
        "skipped": skipped,
    }
    _state["source_history"].append(entry)
    if len(_state["source_history"]) > _HISTORY_MAX:
        _state["source_history"] = _state["source_history"][-_HISTORY_MAX:]


# ── Core scrape logic ────────────────────────────────────────────────────────

async def run_scrape_once(
    force: bool = False,
    startup: bool = False,
    web_only: bool = False,
) -> None:
    """
    Execute one full scrape cycle:
      1. Apify Facebook groups (with watermark-based date filtering).
      2. Dockwalk.com (if DOCKWALK_ENABLED).
      3. WorkOnAYacht.com (if WORKONAYACHT_ENABLED).

    All errors are caught, logged with their CRV code, and stored in _state
    so /scraper/status always reflects the latest outcome.

    force=True    — bypasses feature flags (used by manual trigger).
    startup=True  — marks this as the on-boot call; Apify is skipped unless
                    APIFY_SCRAPE_ON_STARTUP=true (default: false).
    web_only=True — skips Apify entirely regardless of flags (used by the
                    manual web-scraper trigger in the dashboard).
    """
    from app.database import SessionLocal
    from app.error_codes import (
        CRV_6001, CRV_6002, CRV_6003, CRV_6004, CRV_6005, CRV_6006,
    )
    from app.services.apify_scraper import (
        ApifyActorMissingError,
        ApifyError,
        ApifyHTTPError,
        ApifyKeyMissingError,
        ApifyNetworkError,
        ApifyRunFailedError,
        ApifyTimeoutError,
        ApifyScraper,
    )
    from app.services.job_sync import JobSyncError, sync_jobs

    from app import flags
    apify_enabled = (not web_only) and (force or flags.is_enabled("scraper")) and (
        not startup or settings.APIFY_SCRAPE_ON_STARTUP
    )
    web_enabled = force or flags.is_enabled("scraper_web")

    if not apify_enabled and not web_enabled:
        log.info("All scrapers disabled by feature flags — skipping cycle")
        return

    if _scrape_lock.locked():
        log.warning("Scrape already in progress — skipping this cycle")
        return

    async with _scrape_lock:
        _state["running"] = True
        _state["last_run_at"] = datetime.now(timezone.utc).isoformat()
        _state["last_error"] = None

        total_created = total_skipped = total_errors = 0
        total_fetched = 0

        # ── 1. Apify (Facebook groups — paid) ────────────────────────────────
        if apify_enabled:
            actor_ids = settings.APIFY_ACTOR_IDS
            log.info("Apify scrape starting | actors=%d", len(actor_ids))

            # Fetch raw posts — no date filter sent to Apify (onlyPostsNewerThan
            # does not reliably support ISO datetimes for this actor).
            # The three dedup layers in job_sync (content_hash, job_fingerprint,
            # application_url) handle re-fetching already-seen posts cheaply.
            scraper = ApifyScraper(
                api_key=settings.APIFY_API_KEY,
                actor_ids=actor_ids,
                start_urls=settings.APIFY_START_URLS,
                max_items=settings.APIFY_MAX_ITEMS,
                results_limit=settings.APIFY_RESULTS_LIMIT,
            )

            try:
                items: list[dict] = await asyncio.to_thread(scraper.scrape_all)
                total_fetched += len(items)
                log.info("Apify fetched %d raw items (before dedup)", len(items))

                def _sync_apify() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="apify",
                        )
                    finally:
                        db.close()

                created, skipped, errors = await asyncio.to_thread(_sync_apify)
                total_created += created
                total_skipped += skipped
                total_errors += errors
                _record_source("apify", len(items), created, skipped)

            except ApifyKeyMissingError as exc:
                _set_error(CRV_6001, exc)
            except ApifyActorMissingError as exc:
                _set_error(CRV_6002, exc)
            except ApifyTimeoutError as exc:
                _set_error(CRV_6003, exc)
            except ApifyRunFailedError as exc:
                _set_error(CRV_6004, exc)
            except (ApifyHTTPError, ApifyNetworkError, ApifyError) as exc:
                _set_error(CRV_6005, exc)
            except JobSyncError as exc:
                _set_error(CRV_6006, exc)
            except Exception as exc:
                _set_error(CRV_6006, exc)
                log.exception("Apify scrape failed with unexpected error | %s", exc)
        else:
            log.info("Apify scraper disabled by feature flag — skipping")

        # ── 2. Dockwalk ───────────────────────────────────────────────────────
        if web_enabled and settings.DOCKWALK_ENABLED:
            try:
                from app.services.dockwalk_scraper import DockwalkScraper
                dw_items: list[dict] = await asyncio.to_thread(
                    DockwalkScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape
                )
                total_fetched += len(dw_items)
                log.info("Dockwalk scrape complete | items=%d", len(dw_items))

                def _sync_dockwalk() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, dw_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="dockwalk",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_dockwalk)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("dockwalk", len(dw_items), c, s)
            except Exception as exc:
                log.error("Dockwalk scrape failed | error=%s", exc)

        # ── 3. WorkOnAYacht / Yotspot ─────────────────────────────────────────
        if web_enabled and settings.WORKONAYACHT_ENABLED:
            try:
                from app.services.workonayacht_scraper import WorkOnAYachtScraper
                woa_items: list[dict] = await asyncio.to_thread(
                    WorkOnAYachtScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape
                )
                total_fetched += len(woa_items)
                log.info("WorkOnAYacht scrape complete | items=%d", len(woa_items))

                def _sync_workonayacht() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, woa_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="workonayacht",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_workonayacht)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("workonayacht", len(woa_items), c, s)
            except Exception as exc:
                log.error("WorkOnAYacht scrape failed | error=%s", exc)

        # ── 4. CrewFinders ────────────────────────────────────────────────────
        if web_enabled and settings.CREWFINDERS_ENABLED:
            try:
                from app.services.crewfinders_scraper import CrewFindersScraper
                cf_items: list[dict] = await asyncio.to_thread(CrewFindersScraper().scrape)
                total_fetched += len(cf_items)
                log.info("CrewFinders scrape complete | items=%d", len(cf_items))

                def _sync_crewfinders() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, cf_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="crewfinders",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_crewfinders)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("crewfinders", len(cf_items), c, s)
            except Exception as exc:
                log.error("CrewFinders scrape failed | error=%s", exc)

        # ── 5. Viking Crew ────────────────────────────────────────────────────
        if web_enabled and settings.VIKINGCREW_ENABLED:
            try:
                from app.services.vikingcrew_scraper import VikingCrewScraper
                vc_items: list[dict] = await asyncio.to_thread(
                    VikingCrewScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape
                )
                total_fetched += len(vc_items)
                log.info("Viking Crew scrape complete | items=%d", len(vc_items))

                def _sync_vikingcrew() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, vc_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="vikingcrew",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_vikingcrew)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("vikingcrew", len(vc_items), c, s)
            except Exception as exc:
                log.error("Viking Crew scrape failed | error=%s", exc)

        # ── 6. Faststream ─────────────────────────────────────────────────────
        if web_enabled and settings.FASTSTREAM_ENABLED:
            try:
                from app.services.faststream_scraper import FaststreamScraper
                fs_items: list[dict] = await asyncio.to_thread(FaststreamScraper().scrape)
                total_fetched += len(fs_items)
                log.info("Faststream scrape complete | items=%d", len(fs_items))

                def _sync_faststream() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, fs_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="faststream",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_faststream)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("faststream", len(fs_items), c, s)
            except Exception as exc:
                log.error("Faststream scrape failed | error=%s", exc)

        # ── 7. Reed (registered as superyachttimes) ───────────────────────────
        if web_enabled and settings.SUPERYACHTTIMES_ENABLED:
            try:
                from app.services.superyachttimes_scraper import SuperYachtTimesScraper
                reed_items: list[dict] = await asyncio.to_thread(SuperYachtTimesScraper().scrape)
                total_fetched += len(reed_items)
                log.info("Reed scrape complete | items=%d", len(reed_items))

                def _sync_reed() -> tuple[int, int, int]:
                    db = SessionLocal()
                    try:
                        return sync_jobs(
                            db, reed_items,
                            openai_api_key=settings.OPENAI_API_KEY,
                            openai_model=settings.OPENAI_MODEL,
                            source="reed",
                        )
                    finally:
                        db.close()

                c, s, e = await asyncio.to_thread(_sync_reed)
                total_created += c
                total_skipped += s
                total_errors += e
                _record_source("reed", len(reed_items), c, s)
            except Exception as exc:
                log.error("Reed scrape failed | error=%s", exc)

        # ── Finalise state ────────────────────────────────────────────────────
        if _state.get("last_status") != "error":
            _state["last_status"] = "ok"

        _state["last_counts"] = {
            "items_fetched": total_fetched,
            "created": total_created,
            "skipped": total_skipped,
            "errors": total_errors,
        }
        log.info(
            "Scrape cycle complete | fetched=%d | created=%d | skipped=%d | errors=%d",
            total_fetched, total_created, total_skipped, total_errors,
        )

        _state["running"] = False


def _set_error(code: str, exc: Exception) -> None:
    _state["last_status"] = "error"
    _state["last_error"] = {"code": code, "detail": str(exc)}
    log.error("Scrape failed | code=%s | %s", code, exc)


# ── Background loop ──────────────────────────────────────────────────────────

async def scraper_loop() -> None:
    """
    Background asyncio task started at API startup.
    Runs web scrapers immediately on boot (Apify skipped unless
    APIFY_SCRAPE_ON_STARTUP=true), then the full cycle every 6 hours.
    """
    await run_scrape_once(startup=True)
    while True:
        next_ts = datetime.now(timezone.utc).timestamp() + SCRAPE_INTERVAL_SECONDS
        _state["next_run_at"] = (
            datetime.fromtimestamp(next_ts, tz=timezone.utc).isoformat()
        )
        log.info(
            "Next scrape in %dh | next_run_at=%s",
            SCRAPE_INTERVAL_SECONDS // 3600,
            _state["next_run_at"],
        )
        await asyncio.sleep(SCRAPE_INTERVAL_SECONDS)
        await run_scrape_once()
