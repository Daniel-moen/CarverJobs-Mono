from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app import crud, schemas
from app.database import get_db
from app.logger import get_logger
from app.security import require_admin_session

log = get_logger("carver.jobs")
router = APIRouter(prefix="/jobs", tags=["jobs"], dependencies=[Depends(require_admin_session)])


@router.get("", response_model=list[schemas.JobRead])
def list_jobs(db: Session = Depends(get_db)):
    jobs = crud.list_jobs(db)
    log.info("Jobs listed | count=%d", len(jobs))
    return jobs


@router.post("", response_model=schemas.JobRead, status_code=status.HTTP_201_CREATED)
def create_job(payload: schemas.JobCreate, db: Session = Depends(get_db)):
    job = crud.create_job(db, payload)
    log.info("Job created | id=%d | title=%s", job.id, job.title)
    return job


@router.get("/{job_id}", response_model=schemas.JobRead)
def get_job(job_id: int, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.patch("/{job_id}", response_model=schemas.JobRead)
def update_job(job_id: int, payload: schemas.JobUpdate, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job update failed: not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    updated = crud.update_job(db, job, payload)
    log.info("Job updated | id=%d", job_id)
    return updated


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_job(job_id: int, db: Session = Depends(get_db)):
    job = crud.get_job(db, job_id)
    if not job:
        log.warning("Job delete failed: not found | id=%d", job_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    crud.delete_job(db, job)
    log.info("Job deleted | id=%d", job_id)
    return None
