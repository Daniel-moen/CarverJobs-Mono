from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.logger import get_logger
from app.models import JobHistoryEntry
from app.schemas import JobHistoryCreate, JobHistoryRead, JobHistoryUpdate
from app.security import require_session

log = get_logger("carver.job_history")
_limiter = Limiter(key_func=get_remote_address)
router = APIRouter(prefix="/job-history", tags=["job-history"])

MAX_ENTRIES_PER_USER = 20


@router.get("")
def list_job_history(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    entries = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == user_key)
        .order_by(JobHistoryEntry.id.desc())
        .all()
    )
    return [JobHistoryRead.model_validate(e) for e in entries]


@router.post("", status_code=status.HTTP_201_CREATED)
@_limiter.limit("30/minute")
def create_job_history(
    request: Request,
    body: JobHistoryCreate,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    count = db.query(JobHistoryEntry).filter(JobHistoryEntry.user_key == user_key).count()
    if count >= MAX_ENTRIES_PER_USER:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {MAX_ENTRIES_PER_USER} job history entries allowed.",
        )

    entry = JobHistoryEntry(user_key=user_key, **body.model_dump())
    db.add(entry)
    db.commit()
    db.refresh(entry)
    log.info("Job history created | user=%s | id=%d", user_key, entry.id)
    return JobHistoryRead.model_validate(entry)


@router.patch("/{entry_id}", status_code=status.HTTP_200_OK)
@_limiter.limit("30/minute")
def update_job_history(
    request: Request,
    entry_id: int,
    body: JobHistoryUpdate,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    entry = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.id == entry_id, JobHistoryEntry.user_key == user_key)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(entry, field, value)
    db.commit()
    db.refresh(entry)
    log.info("Job history updated | user=%s | id=%d", user_key, entry.id)
    return JobHistoryRead.model_validate(entry)


@router.delete("/{entry_id}", status_code=status.HTTP_200_OK)
@_limiter.limit("30/minute")
def delete_job_history(
    request: Request,
    entry_id: int,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    entry = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.id == entry_id, JobHistoryEntry.user_key == user_key)
        .first()
    )
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found.")

    db.delete(entry)
    db.commit()
    log.info("Job history deleted | user=%s | id=%d", user_key, entry_id)
    return {"ok": True}
