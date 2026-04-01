import secrets

from sqlalchemy.orm import Session

from app import models, schemas
from app.security import hash_password


def list_jobs(db: Session):
  return db.query(models.Job).order_by(models.Job.created_at.desc()).all()


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
