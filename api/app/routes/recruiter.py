"""
Recruiter pay-per-unlock.

Agencies browse the crew candidate pool (no contact details shown) and spend
tokens to unlock a candidate's email/phone. Once unlocked, that contact stays
free to re-view. Token spend reuses the shared CreditAccount keyed by the
session email — the same currency crew buy on the subscription page.

`GET /recruiter/preview` is the one public route here: an anonymised shop
window for the candidate pool so an agency can see there ARE crew before it
is asked to create an account (22 Sep 2026 review — 2 agency accounts, 0
unlocks ever, because nobody ever reached the crew list).
"""
import re
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.analytics import record_server_event
from app.database import get_db
from app.logger import get_logger
from app.models import ContactUnlock, CrewProfile, Document, User
from app.schemas import (
    APIModel,
    RecruiterCandidate,
    RecruiterCandidateList,
    RecruiterUnlockResponse,
)
from app.security import require_agency_or_admin_session
from app.services.credits import add_credits, get_credit_balance, spend_credits
from app.settings import settings

log = get_logger("carver.recruiter")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/recruiter", tags=["recruiter"])

#: How many anonymised cards the public preview ever returns.
PREVIEW_LIMIT = 12


def _doc_flags(db: Session, user_key: str, slug: str) -> tuple[bool, bool, str | None]:
    """Return (has_cv, has_photo, photo_url) for a crew member."""
    doc_types = {
        d.doc_type
        for d in db.query(Document.doc_type).filter(Document.user_key == user_key).all()
    }
    photo_url = f"/p/{slug}/photo" if "photo" in doc_types else None
    return "cv" in doc_types, "photo" in doc_types, photo_url


def _resolve_contact(db: Session, profile: CrewProfile) -> tuple[str | None, str | None]:
    """Best-effort resolve a crew member's email + phone.

    Website crew are keyed by email; WhatsApp crew are keyed by phone number.
    """
    user = db.query(User).filter(User.email == profile.user_key).first()
    is_email_key = "@" in (profile.user_key or "")
    email = user.email if user else (profile.user_key if is_email_key else None)
    phone = profile.phone or (user.phone if user else None)
    if not phone and not is_email_key:
        phone = profile.user_key  # WhatsApp crew keyed by phone
    return email, phone


def _candidate(profile: CrewProfile, *, unlocked: bool, db: Session,
               with_contact: bool = False) -> RecruiterCandidate:
    has_cv, has_photo, photo_url = _doc_flags(db, profile.user_key, profile.profile_slug)
    email = phone = None
    if unlocked and with_contact:
        email, phone = _resolve_contact(db, profile)
    return RecruiterCandidate(
        profile_slug=profile.profile_slug,
        first_name=profile.first_name,
        last_name=profile.last_name,
        nationality=profile.nationality,
        current_location=profile.current_location,
        desired_role=profile.desired_role,
        contract_type=profile.contract_type,
        years_experience=profile.years_experience,
        available_from=profile.available_from,
        certifications=profile.certifications,
        languages=profile.languages,
        bio=profile.bio,
        has_cv=has_cv,
        has_photo=has_photo,
        photo_url=photo_url,
        unlocked=unlocked,
        email=email,
        phone=phone,
    )


# ── Public anonymised preview ────────────────────────────────────────────────

class CrewPreviewCard(APIModel):
    """One crew member as shown to a logged-out visitor.

    Deliberately not a `RecruiterCandidate`: no slug, no name, no bio, no
    photo URL, no certification text and no contact fields — nothing that
    could identify the person or be scraped into a competing database. The
    card is *derived* from `_candidate()` (see `_anonymise`) so any field
    added to the paid shape later has to be opted in here to escape.
    """
    initials: str = ""
    desired_role: Optional[str] = None
    nationality: Optional[str] = None
    region: Optional[str] = None
    years_experience: Optional[str] = None
    languages: Optional[str] = None
    certifications_count: int = 0
    available_from: Optional[str] = None
    has_cv: bool = False
    has_photo: bool = False


class CrewPreviewList(APIModel):
    candidates: Annotated[list[CrewPreviewCard], Field(default_factory=list)]
    total: int = 0
    unlock_cost: int = 0
    first_unlock_free: bool = True


def _initials(first: str | None, last: str | None) -> str:
    """"Alex Crew" → "A.C." — enough to make a card feel human, not a name."""
    letters = [part.strip()[0].upper() for part in (first, last) if (part or "").strip()]
    return "".join(f"{c}." for c in letters)


def _region(location: str | None) -> str | None:
    """Coarsen "Antibes, France" → "France" so a card is not a home address."""
    if not location:
        return None
    tail = location.split(",")[-1].strip() or location.strip()
    return tail[:60] or None


def _certification_count(certifications: str | None) -> int:
    if not certifications:
        return 0
    return len([c for c in re.split(r"[,;\n]+", certifications) if c.strip()])


def _anonymise(c: RecruiterCandidate) -> CrewPreviewCard:
    return CrewPreviewCard(
        initials=_initials(c.first_name, c.last_name),
        desired_role=c.desired_role,
        nationality=c.nationality,
        region=_region(c.current_location),
        years_experience=c.years_experience,
        languages=c.languages,
        certifications_count=_certification_count(c.certifications),
        available_from=c.available_from,
        has_cv=c.has_cv,
        has_photo=c.has_photo,
    )


@router.get("/preview", response_model=CrewPreviewList)
@_limiter.limit("30/minute")
def preview_candidates(request: Request, db: Session = Depends(get_db)):
    """Public, login-free, anonymised sample of the discoverable crew pool.

    Rate-limited like the other public GETs (articles, job board). No session
    is required and none is read — this is the page an agency sees *before*
    it signs up.
    """
    base = db.query(CrewProfile).filter(CrewProfile.discoverable.is_(True))
    total = base.count()
    profiles = base.order_by(CrewProfile.updated_at.desc()).limit(PREVIEW_LIMIT).all()
    cards = [
        _anonymise(_candidate(p, unlocked=False, db=db, with_contact=False))
        for p in profiles
    ]
    return CrewPreviewList(
        candidates=cards,
        total=total,
        unlock_cost=settings.RECRUITER_UNLOCK_COST_TOKENS,
        first_unlock_free=settings.FREE_SIGNUP_TOKENS >= settings.RECRUITER_UNLOCK_COST_TOKENS,
    )


@router.get("/candidates", response_model=RecruiterCandidateList)
@_limiter.limit("60/minute")
def list_candidates(
    request: Request,
    role: str | None = None,
    location: str | None = None,
    q: str | None = None,
    limit: int = 50,
    offset: int = 0,
    session: dict = Depends(require_agency_or_admin_session),
    db: Session = Depends(get_db),
):
    """Browse discoverable crew. Contact details are never returned here."""
    agency_key = session["sub"]
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    query = db.query(CrewProfile).filter(CrewProfile.discoverable.is_(True))
    if role:
        query = query.filter(CrewProfile.desired_role.ilike(f"%{role}%"))
    if location:
        query = query.filter(
            or_(
                CrewProfile.current_location.ilike(f"%{location}%"),
                CrewProfile.preferred_locations.ilike(f"%{location}%"),
            )
        )
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                CrewProfile.first_name.ilike(like),
                CrewProfile.last_name.ilike(like),
                CrewProfile.bio.ilike(like),
                CrewProfile.certifications.ilike(like),
            )
        )

    total = query.count()
    profiles = query.order_by(CrewProfile.updated_at.desc()).offset(offset).limit(limit).all()

    unlocked_keys = {
        row.crew_user_key
        for row in db.query(ContactUnlock.crew_user_key)
        .filter(ContactUnlock.agency_user_key == agency_key)
        .all()
    }

    candidates = [
        _candidate(
            p,
            unlocked=p.user_key in unlocked_keys,
            db=db,
            with_contact=p.user_key in unlocked_keys,
        )
        for p in profiles
    ]
    return RecruiterCandidateList(
        candidates=candidates,
        total=total,
        unlock_cost=settings.RECRUITER_UNLOCK_COST_TOKENS,
        balance=get_credit_balance(db, agency_key),
    )


@router.get("/unlocked", response_model=RecruiterCandidateList)
def list_unlocked(
    session: dict = Depends(require_agency_or_admin_session),
    db: Session = Depends(get_db),
):
    """List candidates this agency has already unlocked, with contact details."""
    agency_key = session["sub"]
    unlocks = (
        db.query(ContactUnlock)
        .filter(ContactUnlock.agency_user_key == agency_key)
        .order_by(ContactUnlock.created_at.desc())
        .all()
    )
    candidates = []
    for u in unlocks:
        profile = db.query(CrewProfile).filter(CrewProfile.user_key == u.crew_user_key).first()
        if profile:
            candidates.append(_candidate(profile, unlocked=True, db=db, with_contact=True))
    return RecruiterCandidateList(
        candidates=candidates,
        total=len(candidates),
        unlock_cost=settings.RECRUITER_UNLOCK_COST_TOKENS,
        balance=get_credit_balance(db, agency_key),
    )


@router.post("/candidates/{slug}/unlock", response_model=RecruiterUnlockResponse)
@_limiter.limit("30/minute")
def unlock_candidate(
    request: Request,
    slug: str,
    session: dict = Depends(require_agency_or_admin_session),
    db: Session = Depends(get_db),
):
    """Spend tokens to unlock a crew member's contact details (idempotent)."""
    if len(slug) > 16:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid slug.")

    agency_key = session["sub"]
    profile = (
        db.query(CrewProfile)
        .filter(CrewProfile.profile_slug == slug, CrewProfile.discoverable.is_(True))
        .first()
    )
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found.")

    existing = (
        db.query(ContactUnlock)
        .filter(
            ContactUnlock.agency_user_key == agency_key,
            ContactUnlock.crew_user_key == profile.user_key,
        )
        .first()
    )
    email, phone = _resolve_contact(db, profile)

    if existing:
        return RecruiterUnlockResponse(
            already_unlocked=True,
            cost=0,
            balance=get_credit_balance(db, agency_key),
            email=email,
            phone=phone,
        )

    cost = settings.RECRUITER_UNLOCK_COST_TOKENS
    remaining = spend_credits(db, agency_key, amount=cost)
    if remaining is None:
        record_server_event(agency_key, "paywall_hit", "recruiter")
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"You need {cost} tokens to unlock this candidate. Top up to continue.",
        )

    unlock = ContactUnlock(
        agency_user_key=agency_key,
        crew_user_key=profile.user_key,
        profile_slug=slug,
        cost_tokens=cost,
    )
    db.add(unlock)
    try:
        db.commit()
    except IntegrityError:
        # A concurrent request unlocked the same candidate first. Refund the
        # tokens we just spent and return the contact for free.
        db.rollback()
        balance = add_credits(db, agency_key, cost)
        log.info("Unlock race — refunded | agency=%s | slug=%s", agency_key, slug)
        return RecruiterUnlockResponse(
            already_unlocked=True, cost=0, balance=balance, email=email, phone=phone,
        )

    log.info("Contact unlocked | agency=%s | slug=%s | cost=%d", agency_key, slug, cost)
    return RecruiterUnlockResponse(
        already_unlocked=False,
        cost=cost,
        balance=remaining,
        email=email,
        phone=phone,
    )
