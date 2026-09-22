"""
Scraper scheduler — runs a full scrape cycle every SCRAPE_INTERVAL_HOURS (24h).

Cycle includes:
  1. Facebook groups via Apify (raw fetch, no date filter sent to actor).
  2. WorkOnAYacht.com / Yotspot job listings (if enabled).
  3. Faststream (if enabled).

Dockwalk, CrewFinders, Viking Crew and Reed/SuperYachtTimes were removed in
Sep 2026: all four sources stopped returning listings (layout changes and
bot-walls), so their scrapers were dead weight that made the cycle look busier
than it was. Their scraper modules are gone — do not re-add a call here without
re-adding a working scraper.

Deduplication is handled by job_sync (content_hash, job_fingerprint, URL).
State is held in-memory and exposed via get_scraper_state() for the
/scraper/status admin endpoint.

A cycle that fails, or that produces no new jobs several runs in a row, pages
the operator over WhatsApp (services/ops_alerts) — the dead-Apify outage that
ran for months was invisible precisely because nothing here ever spoke up.
"""
import asyncio
from datetime import datetime, timezone

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.scheduler")

# Tunable because Apify bills per run: drop the frequency when credit is tight,
# raise it when job flow matters more. Keep it under JOB_FRESHNESS_ALERT_HOURS
# (48h) or /status/services will flag the pipeline stale between healthy runs.
SCRAPE_INTERVAL_SECONDS = settings.SCRAPE_INTERVAL_HOURS * 60 * 60

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

# Consecutive cycles that created nothing before the operator is paged. One
# empty cycle is normal (quiet weekend, everything deduped); three in a row at
# a 24h interval means the supply side is dead, which is the outage that went
# unnoticed for months. Alerts fire once when the streak is reached, not on
# every cycle after it — steady-state nagging is how a channel gets muted.
_ZERO_RUN_ALERT_THRESHOLD = 3
_zero_run_streak = 0


def reset_alert_state() -> None:
    """Clear the zero-result streak. Test seam; also used by manual triggers."""
    global _zero_run_streak
    _zero_run_streak = 0


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
      2. WorkOnAYacht.com / Yotspot (if WORKONAYACHT_ENABLED).
      3. Faststream (if FASTSTREAM_ENABLED).

    All errors are caught, logged with their CRV code, and stored in _state
    so /scraper/status always reflects the latest outcome. They are also
    collected locally so the cycle can page the operator once at the end.

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
        # Human-readable failures from THIS cycle (per-source, not per-item), so
        # the ops alert reports what actually broke instead of "something did".
        failures: list[str] = []

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
                failures.append(_set_error(CRV_6001, exc))
            except ApifyActorMissingError as exc:
                failures.append(_set_error(CRV_6002, exc))
            except ApifyTimeoutError as exc:
                failures.append(_set_error(CRV_6003, exc))
            except ApifyRunFailedError as exc:
                failures.append(_set_error(CRV_6004, exc))
            except (ApifyHTTPError, ApifyNetworkError, ApifyError) as exc:
                failures.append(_set_error(CRV_6005, exc))
            except JobSyncError as exc:
                failures.append(_set_error(CRV_6006, exc))
            except Exception as exc:
                failures.append(_set_error(CRV_6006, exc))
                log.exception("Apify scrape failed with unexpected error | %s", exc)
        else:
            log.info("Apify scraper disabled by feature flag — skipping")

        # ── 2. WorkOnAYacht / Yotspot ─────────────────────────────────────────
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
                failures.append(f"WorkOnAYacht scrape failed: {exc}")

        # ── 3. Faststream ─────────────────────────────────────────────────────
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
                failures.append(f"Faststream scrape failed: {exc}")

        # ── Finalise state ────────────────────────────────────────────────────
        # Derived from THIS cycle's failures, not from the leftover value: the
        # old `!= "error"` guard made one bad cycle pin last_status to "error"
        # for the life of the process, so /scraper/status never recovered.
        _state["last_status"] = "error" if failures else "ok"

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

    # Outside the lock: paging the operator must not hold up the next cycle.
    await _alert_on_cycle_outcome(total_created, total_fetched, failures)


def _set_error(code: str, exc: Exception) -> str:
    """Record a fatal source error in _state and return a one-line description."""
    _state["last_status"] = "error"
    _state["last_error"] = {"code": code, "detail": str(exc)}
    log.error("Scrape failed | code=%s | %s", code, exc)
    return f"Apify scrape failed ({code}): {exc}"


async def _alert_on_cycle_outcome(
    created: int, fetched: int, failures: list[str]
) -> None:
    """Page the operator when a cycle breaks, or when supply has dried up.

    Two triggers, both deliberately quiet:
      * any source failed this cycle — one message listing them. Cycles are a
        day apart, so this is at most one message a day.
      * _ZERO_RUN_ALERT_THRESHOLD cycles in a row created no jobs — one message
        when the streak is reached, then silence until something is created
        again. Ongoing staleness is already covered by the job_pipeline health
        check, which alerts on its own ok→failed flip.

    Never raises: the scrape loop must survive a broken alert channel.
    """
    global _zero_run_streak

    if created > 0:
        _zero_run_streak = 0
    else:
        _zero_run_streak += 1

    lines: list[str] = []
    if failures:
        lines.append("Scrape cycle had failures:")
        lines += [f"• {f}" for f in failures]
    if _zero_run_streak == _ZERO_RUN_ALERT_THRESHOLD:
        lines.append(
            f"No new jobs created in {_zero_run_streak} consecutive scrape cycles "
            f"(last cycle fetched {fetched} raw item(s)). The supply side looks dead — "
            "check the Apify actors and the Facebook groups."
        )
    if not lines:
        return

    try:
        from app.services.ops_alerts import notify_ops
        await notify_ops("\n".join(lines))
    except Exception as exc:
        log.error("Scrape cycle ops alert failed | %s", exc)


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
