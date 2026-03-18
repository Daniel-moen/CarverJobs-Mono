import secrets
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.logger import get_logger
from app.models import CrewProfile, Document, JobHistoryEntry
from app.schemas import CrewProfileRead, CrewProfileSave, PublicProfileResponse, JobHistoryRead
from app.security import require_session
from app.settings import settings

log = get_logger("carver.profile")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/profile", tags=["profile"])
public_router = APIRouter(tags=["public-profile"])


def _generate_slug() -> str:
    return secrets.token_urlsafe(6)


@router.post("/save", status_code=status.HTTP_200_OK)
@_limiter.limit("30/minute")
def save_profile(
    request: Request,
    body: CrewProfileSave,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    existing = db.query(CrewProfile).filter(CrewProfile.user_key == user_key).first()

    if existing:
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(existing, field, value)
        db.commit()
        db.refresh(existing)
        log.info("Profile updated | user=%s", user_key)
        return CrewProfileRead.model_validate(existing)

    slug = _generate_slug()
    while db.query(CrewProfile).filter(CrewProfile.profile_slug == slug).first():
        slug = _generate_slug()

    profile = CrewProfile(
        user_key=user_key,
        profile_slug=slug,
        **body.model_dump(exclude_unset=True),
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)
    log.info("Profile created | user=%s | slug=%s", user_key, slug)
    return CrewProfileRead.model_validate(profile)


@router.get("/me")
def get_my_profile(
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session["sub"]
    profile = db.query(CrewProfile).filter(CrewProfile.user_key == user_key).first()
    if not profile:
        return {"profile": None}
    return {"profile": CrewProfileRead.model_validate(profile)}


@public_router.get("/p/{slug}")
def get_public_profile(
    slug: str,
    db: Session = Depends(get_db),
):
    if len(slug) > 16:
        raise HTTPException(status_code=400, detail="Invalid slug.")

    profile = db.query(CrewProfile).filter(CrewProfile.profile_slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    docs = db.query(Document).filter(Document.user_key == profile.user_key).all()
    doc_types = {d.doc_type for d in docs}

    photo_doc = next((d for d in docs if d.doc_type == "photo"), None)
    photo_url = f"/p/{slug}/photo" if photo_doc else None

    job_entries = (
        db.query(JobHistoryEntry)
        .filter(JobHistoryEntry.user_key == profile.user_key)
        .order_by(JobHistoryEntry.id.desc())
        .all()
    )

    return PublicProfileResponse(
        first_name=profile.first_name,
        last_name=profile.last_name,
        nationality=profile.nationality,
        current_location=profile.current_location,
        desired_role=profile.desired_role,
        contract_type=profile.contract_type,
        preferred_locations=profile.preferred_locations,
        rotation_preference=profile.rotation_preference,
        years_experience=profile.years_experience,
        available_from=profile.available_from,
        certifications=profile.certifications,
        languages=profile.languages,
        bio=profile.bio,
        has_cv="cv" in doc_types,
        has_references="references" in doc_types,
        has_photo="photo" in doc_types,
        photo_url=photo_url,
        job_history=[JobHistoryRead.model_validate(j) for j in job_entries],
    )


@public_router.get("/p/{slug}/photo")
def get_public_photo(
    slug: str,
    db: Session = Depends(get_db),
):
    """Serve the profile photo for a public profile (images only)."""
    if len(slug) > 16:
        raise HTTPException(status_code=400, detail="Invalid slug.")

    profile = db.query(CrewProfile).filter(CrewProfile.profile_slug == slug).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found.")

    doc = (
        db.query(Document)
        .filter(Document.user_key == profile.user_key, Document.doc_type == "photo")
        .first()
    )
    if not doc:
        raise HTTPException(status_code=404, detail="No photo uploaded.")

    upload_dir = settings.UPLOAD_DIR
    file_path = (upload_dir / doc.stored_name).resolve()
    if not str(file_path).startswith(str(upload_dir.resolve())):
        raise HTTPException(status_code=400, detail="Invalid file path.")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File missing on server.")

    suffix = file_path.suffix.lower()
    media_type = "image/png" if suffix == ".png" else "image/jpeg"
    return FileResponse(path=str(file_path), media_type=media_type)
