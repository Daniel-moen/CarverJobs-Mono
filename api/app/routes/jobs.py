from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.logger import get_logger
from app.security import require_admin_session, require_session

log = get_logger("carver.jobs")
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[schemas.JobRead])
def list_jobs(
    limit: int = Query(default=crud.DEFAULT_JOB_LIMIT, ge=1, le=crud.MAX_JOB_LIMIT),
    include_inactive: bool = Query(default=False),
    _session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    # Normal users always get the active-only, capped listing. Only admins may
    # opt in to seeing inactive (expired/closed/filled/archived) jobs.
    allow_inactive = include_inactive and _session.get("role") == "admin"
    jobs = crud.list_jobs(db, limit=limit, include_inactive=allow_inactive)
    log.info("Jobs listed | count=%d | include_inactive=%s", len(jobs), allow_inactive)
    return jobs


@router.post("", response_model=schemas.JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
    payload: schemas.JobCreate,
    _session: dict = Depends(require_admin_session),
    db: Session = Depends(get_db),
):
    job = crud.create_job(db, payload)
    log.info("Job created | id=%d | title=%s", job.id, job.title)
    return job


@router.get("/{job_id}", response_model=schemas.JobRead)
def get_job(
    job_id: int,
    _session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=schemas.JobRead)
def update_job(
    job_id: int,
    payload: schemas.JobUpdate,
    _session: dict = Depends(require_admin_session),
    db: Session = Depends(get_db),
):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job update failed: not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    updated = crud.update_job(db, job, payload)
    log.info("Job updated | id=%d", job_id)
    return updated


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_job(
    job_id: int,
    _session: dict = Depends(require_admin_session),
    db: Session = Depends(get_db),
):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job delete failed: not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    crud.delete_job(db, job)
    log.info("Job deleted | id=%d", job_id)
    return None
