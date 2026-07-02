"""
Job retention — prunes the ever-growing `jobs` table.

Scrapers append to `jobs` on every cycle and nothing ever removes rows, so the
table grows without bound. This module applies a two-tier, age-based policy
(age measured from `Job.created_at`):

  1. Soft-expire — jobs still on active surfaces (`status in ("open","priority")`)
     older than JOB_EXPIRE_AFTER_DAYS are flipped to status ``"expired"``. The
     row is kept (preserving match history / audit), but the matching engine and
     job board only show ``status in ("open","priority")``, so the job vanishes
     from all client-facing surfaces. The ``"expired"`` string is a SHARED
     CONTRACT with the active-listing filters — do not change it.

  2. Hard-delete — any job older than JOB_DELETE_AFTER_DAYS is deleted outright,
     keeping the table small.

A background loop (`retention_loop`) runs this on a fixed interval, mirroring
`app.scheduler.scraper_loop`. It is crash-proof: a failed run is logged and the
loop continues.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.logger import get_logger
from app.models import Job, MatchSession
from app.settings import settings

log = get_logger("carver.retention")

# Statuses that appear on active client-facing surfaces (job board + matcher).
# Only these are eligible for soft-expiry. SHARED CONTRACT with Worker 3.
_ACTIVE_STATUSES = ("open", "priority")
_EXPIRED_STATUS = "expired"


def purge_stale_jobs(db: Session) -> dict[str, int]:
    """Apply the two-tier retention policy in bulk and return counts.

    Returns ``{"expired": n, "deleted": n}`` where ``expired`` is the number of
    active jobs flipped to ``"expired"`` and ``deleted`` the number of rows
    removed entirely.
    """
    now = datetime.now(timezone.utc)
    expire_cutoff = now - timedelta(days=settings.JOB_EXPIRE_AFTER_DAYS)
    delete_cutoff = now - timedelta(days=settings.JOB_DELETE_AFTER_DAYS)

    # 1. Soft-expire active jobs older than the expiry cutoff.
    expired = (
        db.query(Job)
        .filter(Job.status.in_(_ACTIVE_STATUSES), Job.created_at < expire_cutoff)
        .update({Job.status: _EXPIRED_STATUS}, synchronize_session=False)
    )

    # 2. Hard-delete anything older than the delete cutoff (any status).
    deleted = (
        db.query(Job)
        .filter(Job.created_at < delete_cutoff)
        .delete(synchronize_session=False)
    )

    db.commit()

    log.info(
        "Job retention complete | expired=%d | deleted=%d | "
        "expire_after_days=%d | delete_after_days=%d",
        expired, deleted,
        settings.JOB_EXPIRE_AFTER_DAYS, settings.JOB_DELETE_AFTER_DAYS,
    )
    return {"expired": expired, "deleted": deleted}


# Sessions left in "running" leak when the process restarts (or a background
# task dies) mid-run — they then look permanently in-progress to the UI and
# pollute funnel stats. Anything running this long has definitely crashed.
_STUCK_SESSION_TIMEOUT_HOURS = 2


def fail_stuck_match_sessions(db: Session) -> int:
    """Global janitor: flip long-abandoned 'running' match sessions to 'failed'.

    Complements crew_match's per-user cleanup, which only runs when that user
    revisits the site — WhatsApp-only users never trigger it.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_STUCK_SESSION_TIMEOUT_HOURS)
    stuck = (
        db.query(MatchSession)
        .filter(MatchSession.status == "running", MatchSession.created_at < cutoff)
        .update({MatchSession.status: "failed"}, synchronize_session=False)
    )
    db.commit()
    if stuck:
        log.warning("Failed %d stuck match session(s) older than %dh", stuck, _STUCK_SESSION_TIMEOUT_HOURS)
    return stuck


# ── Background loop ──────────────────────────────────────────────────────────

async def retention_loop() -> None:
    """Background asyncio task started at API startup.

    Runs once shortly after boot, then every JOB_RETENTION_INTERVAL_HOURS. Each
    iteration opens its own session and is wrapped in try/except so a single bad
    run never kills the loop.
    """
    from app.database import SessionLocal

    interval_seconds = settings.JOB_RETENTION_INTERVAL_HOURS * 60 * 60

    # Small initial delay so it doesn't contend with DB init / first scrape.
    await asyncio.sleep(60)

    while True:
        db = SessionLocal()
        try:
            purge_stale_jobs(db)
        except Exception as exc:
            log.error("Job retention run failed | error=%s", exc)
        finally:
            db.close()

        db = SessionLocal()
        try:
            fail_stuck_match_sessions(db)
        except Exception as exc:
            log.error("Stuck match-session janitor failed | error=%s", exc)
        finally:
            db.close()

        log.info(
            "Next job retention run in %dh", settings.JOB_RETENTION_INTERVAL_HOURS
        )
        await asyncio.sleep(interval_seconds)
