import secrets

from sqlalchemy.orm import Session

from app import models, schemas
from app.security import hash_password


def list_jobs(db: Session):
  jobs = db.query(models.Job).order_by(models.Job.created_at.desc()).all()
  seen: set[tuple[str, str]] = set()
  deduped: list[models.Job] = []

  for job in jobs:
    key: tuple[str, str] | None = None
    if job.content_hash:
      key = ("content_hash", job.content_hash)
    elif job.job_fingerprint:
      key = ("job_fingerprint", job.job_fingerprint)
    elif job.application_url:
      key = ("application_url", job.application_url.strip().lower())
    else:
      fallback = "|".join([
        (job.title or "").strip().lower(),
        (job.role or "").strip().lower(),
        (job.yacht or "").strip().lower(),
        (job.location or "").strip().lower(),
        (job.start_date or "").strip().lower(),
      ])
      if fallback.strip("|"):
        key = ("fallback", fallback)

    if key and key in seen:
      continue
    if key:
      seen.add(key)
    deduped.append(job)

  return deduped


def get_job(db: Session, job_id: int):
  return db.query(models.Job).filter(models.Job.id == job_id).first()


def create_job(db: Session, payload: schemas.JobCreate):
  fields = payload.model_dump()
  fields["source"] = "manual"
  job = models.Job(**fields)
  db.add(job)
  db.commit()
  db.refresh(job)
  return job


def update_job(db: Session, job: models.Job, payload: schemas.JobUpdate):
  changes = payload.model_dump(exclude_unset=True)
  for field, value in changes.items():
    setattr(job, field, value)
  db.commit()
  db.refresh(job)
  return job


def delete_job(db: Session, job: models.Job):
  db.delete(job)
  db.commit()


def list_users(db: Session):
  return db.query(models.User).order_by(models.User.created_at.desc()).all()


def get_user(db: Session, user_id: int):
  return db.query(models.User).filter(models.User.id == user_id).first()


def get_user_by_email(db: Session, email: str):
  return db.query(models.User).filter(models.User.email == email).first()


EARLY_BIRD_LIMIT = 100


def _is_early_bird(db: Session) -> bool:
  cutoff_user = (
    db.query(models.User.id)
    .order_by(models.User.id.asc())
    .offset(EARLY_BIRD_LIMIT - 1)
    .limit(1)
    .first()
  )
  return cutoff_user is None


def create_user(db: Session, payload: schemas.UserCreate):
  user = models.User(
    email=payload.email.lower().strip(),
    full_name=payload.full_name,
    role=payload.role,
    phone=payload.phone,
    nationality=payload.nationality,
    years_experience=payload.years_experience,
    current_location=payload.current_location,
    gender=payload.gender,
    is_active=payload.is_active,
    password_hash=hash_password(payload.password),
    early_bird=_is_early_bird(db),
  )
  db.add(user)
  db.commit()
  db.refresh(user)
  return user


def create_google_user(db: Session, email: str, full_name: str):
  """Create a crew user for Google login with an unusable random password."""
  user = models.User(
    email=email.lower().strip(),
    full_name=full_name.strip() or email.split("@")[0],
    role="crew",
    is_active=True,
    password_hash=hash_password(secrets.token_urlsafe(32)),
    early_bird=_is_early_bird(db),
  )
  db.add(user)
  db.commit()
  db.refresh(user)
  return user


def update_user(db: Session, user: models.User, payload: schemas.UserUpdate):
  changes = payload.model_dump(exclude_unset=True)
  if "password" in changes:
    user.password_hash = hash_password(changes.pop("password"))
  for field, value in changes.items():
    setattr(user, field, value)
  db.commit()
  db.refresh(user)
  return user


def delete_user(db: Session, user: models.User):
  db.delete(user)
  db.commit()
