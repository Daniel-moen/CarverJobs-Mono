from fastapi import APIRouter, Depends

from app.health_checker import get_cached_results
from app.logger import get_logger
from app.security import require_session

log = get_logger("carver.health")
router = APIRouter(tags=["health"])


@router.get("/")
def root_health():
    # Fallback health route for platforms that probe "/" by default.
    return {"ok": True, "service": "api"}


@router.get("/health")
def health():
    log.debug("Health check")
    return {"ok": True, "service": "api"}


@router.get("/status/services")
def services_status(_session: dict = Depends(require_session)):
    services, last_run = get_cached_results()
    log.info("Status requested | last_run=%s", last_run.isoformat() if last_run else "never")
    return {
        "ok": True,
        "last_run": last_run.isoformat() if last_run else None,
        "next_run_seconds": 300,
        "services": services,
    }
