"""
Background health checker — runs every 5 minutes, probes each component,
stores results so /status/services always serves fresh cached data.
"""
import asyncio
from collections import deque
from datetime import datetime, timezone

import requests as _requests

from app.error_codes import CRV_1001, CRV_2001, CRV_3001, CRV_3002, CRV_3003, CRV_3005
from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.healthchecker")

INTERVAL_SECONDS = 300   # 5 minutes
MAX_HISTORY = 48         # 48 × 5 min = 4 hours of history per service

_results: dict = {}
_last_run: datetime | None = None
# Rolling history per service: deque of {"connected": bool, "checked_at": str}
_history: dict[str, deque] = {}


def get_cached_results() -> tuple[dict, datetime | None]:
    return _results, _last_run


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ok(detail: str) -> dict:
    return {"connected": True, "detail": detail, "checked_at": _ts()}


def _fail(detail: str, code: str) -> dict:
    return {"connected": False, "detail": detail, "code": code, "checked_at": _ts()}


def _check_api() -> dict:
    return _ok("API process is running")


def _check_auth() -> dict:
    insecure = not settings.SECRET_KEY or settings.SECRET_KEY == "change-me-in-production"
    if insecure:
        log.warning("Default SECRET_KEY is in use — change it before production deployment")
        return {
            "connected": True,
            "detail": "Session auth enabled — default secret key in use (see CRV-2001)",
            "code": CRV_2001,
            "checked_at": _ts(),
        }
    return _ok("Session auth enabled")


def _check_database() -> dict:
    try:
        from app.database import SessionLocal
        db = SessionLocal()
        db.execute(__import__("sqlalchemy").text("SELECT 1"))
        db.close()
        return _ok("Database reachable")
    except Exception as exc:
        log.error("DB health check failed: %s", exc)
        return _fail("Service unavailable", CRV_1001)


def _check_google() -> dict:
    configured = bool(settings.GOOGLE_OAUTH_CLIENT_ID)
    if configured:
        return _ok("Configured")
    return {"connected": False, "detail": "Not configured", "checked_at": _ts()}


def _check_job_pipeline() -> dict:
    """Throughput check, not connectivity: the scraper can be 'up' while silently
    producing nothing (dead actor, dedupe absorbing everything, stalled loop).
    Stale job supply is a product outage even when every service is reachable."""
    try:
        from datetime import timedelta

        from sqlalchemy import func

        from app.database import SessionLocal
        from app.models import Job

        db = SessionLocal()
        try:
            newest = db.query(func.max(Job.created_at)).scalar()
            cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.JOB_FRESHNESS_ALERT_HOURS)
            new_in_window = (
                db.query(func.count(Job.id)).filter(Job.created_at >= cutoff).scalar() or 0
            )
        finally:
            db.close()

        if newest is None:
            return _fail("No jobs have ever been ingested", "CRV-6006")
        if new_in_window == 0:
            newest_aware = newest if newest.tzinfo else newest.replace(tzinfo=timezone.utc)
            hours_stale = int((datetime.now(timezone.utc) - newest_aware).total_seconds() // 3600)
            log.error(
                "Job pipeline stale — no new jobs in %dh (threshold %dh)",
                hours_stale, settings.JOB_FRESHNESS_ALERT_HOURS,
            )
            return _fail(
                f"No new jobs ingested in {hours_stale}h "
                f"(alert threshold: {settings.JOB_FRESHNESS_ALERT_HOURS}h) — check the scrapers",
                "CRV-6006",
            )
        return _ok(f"{new_in_window} new job{'s' if new_in_window != 1 else ''} in the last {settings.JOB_FRESHNESS_ALERT_HOURS}h")
    except Exception as exc:
        log.error("Job pipeline health check failed: %s", exc)
        return _fail("Could not check job pipeline", CRV_1001)


def _check_openai() -> dict:
    if not settings.OPENAI_API_KEY:
        return _fail("Not configured", CRV_3001)
    model = settings.OPENAI_MODEL
    try:
        resp = _requests.get(
            "https://api.openai.com/v1/models",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            timeout=8,
        )
        if resp.status_code == 200:
            return _ok(f"Reachable ({model})")
        log.warning("OpenAI health check returned HTTP %d", resp.status_code)
        return _fail("Service unavailable", CRV_3003)
    except _requests.Timeout:
        log.warning("OpenAI health check timed out")
        return _fail("Request timed out", CRV_3002)
    except Exception as exc:
        log.error("OpenAI health check error: %s", exc)
        return _fail("Service unavailable", CRV_3005)


def _record_history(name: str, connected: bool, checked_at: str) -> None:
    if name not in _history:
        _history[name] = deque(maxlen=MAX_HISTORY)
    _history[name].append({"connected": connected, "checked_at": checked_at})


def run_checks() -> dict:
    global _results, _last_run
    log.info("Running health checks…")
    openai = _check_openai()
    raw = {
        "api":          _check_api(),
        "auth_session": _check_auth(),
        "database":     _check_database(),
        "google_login": _check_google(),
        "job_pipeline": _check_job_pipeline(),
        "openai_ai":    openai,
        "ai_interview": {
            "connected": openai["connected"],
            "detail": "Ready" if openai["connected"] else "Requires OpenAI to be connected",
            "checked_at": _ts(),
        },
    }
    # Append to rolling history and embed the history list in each service result.
    _results = {}
    for name, info in raw.items():
        _record_history(name, info["connected"], info["checked_at"])
        _results[name] = {**info, "history": list(_history[name])}

    _last_run = datetime.now(timezone.utc)
    statuses = {k: ("✓" if v["connected"] else "✗") for k, v in _results.items()}
    log.info("Health check done | %s", " | ".join(f"{k}={v}" for k, v in statuses.items()))
    return _results


async def health_check_loop():
    await asyncio.to_thread(run_checks)
    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        await asyncio.to_thread(run_checks)
