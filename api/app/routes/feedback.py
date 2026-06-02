from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import metrics, models
from app.database import get_db
from app.logger import get_logger
from app.schemas import FeedbackStatusResponse, FeedbackSubmitRequest, FeedbackSubmitResponse
from app.security import require_session
from app.services.credits import add_credits, get_credit_balance
from app.services.feedback_settings import (
    FEEDBACK_CAMPAIGN,
    FEEDBACK_REWARD_TOKENS,
    feedback_is_eligible,
)

log = get_logger("carver.feedback")
router = APIRouter(prefix="/feedback", tags=["feedback"])
_limiter = Limiter(key_func=get_remote_address)


@router.get("/status", response_model=FeedbackStatusResponse)
def feedback_status(
    source: str = "website_popup",
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session.get("sub", "")
    safe_source = "whatsapp_message" if source == "whatsapp_message" else "website_popup"
    eligible, setting = feedback_is_eligible(db, user_key=user_key, source=safe_source)
    submitted = (
        db.query(models.FeedbackSubmission.id)
        .filter(
            models.FeedbackSubmission.user_key == user_key,
            models.FeedbackSubmission.campaign == FEEDBACK_CAMPAIGN,
        )
        .first()
    ) is not None
    return {
        "ok": True,
        "submitted": submitted,
        "eligible": eligible,
        "force_prompt": eligible and setting.target_mode == "specific",
        "target_mode": setting.target_mode,
        "reward_amount": FEEDBACK_REWARD_TOKENS,
    }


@router.post("/submit", response_model=FeedbackSubmitResponse, status_code=status.HTTP_201_CREATED)
@_limiter.limit("5/minute")
def submit_feedback(
    request: Request,
    payload: FeedbackSubmitRequest,
    session: dict = Depends(require_session),
    db: Session = Depends(get_db),
):
    user_key = session.get("sub", "")
    if not user_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required.")

    eligible, _setting = feedback_is_eligible(db, user_key=user_key, source=payload.source)
    if not eligible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Feedback reward is not available for this account right now.",
        )

    existing = (
        db.query(models.FeedbackSubmission.id)
        .filter(
            models.FeedbackSubmission.user_key == user_key,
            models.FeedbackSubmission.campaign == FEEDBACK_CAMPAIGN,
        )
        .first()
    )
    if existing:
        return {
            "ok": True,
            "submitted": True,
            "reward_granted": False,
            "reward_amount": FEEDBACK_REWARD_TOKENS,
            "credits_balance": get_credit_balance(db, user_key),
        }

    submission = models.FeedbackSubmission(
        user_key=user_key,
        campaign=FEEDBACK_CAMPAIGN,
        source=payload.source,
        rating=payload.rating,
        liked=payload.liked,
        improved=payload.improved,
        confusing=payload.confusing,
        recommend=payload.recommend,
        anything_else=payload.anything_else,
        reward_amount=FEEDBACK_REWARD_TOKENS,
        rewarded=FEEDBACK_REWARD_TOKENS > 0,
    )
    db.add(submission)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return {
            "ok": True,
            "submitted": True,
            "reward_granted": False,
            "reward_amount": FEEDBACK_REWARD_TOKENS,
            "credits_balance": get_credit_balance(db, user_key),
        }

    if FEEDBACK_REWARD_TOKENS > 0:
        credits_balance = add_credits(db, user_key, amount=FEEDBACK_REWARD_TOKENS)
    else:
        db.commit()
        credits_balance = get_credit_balance(db, user_key)
    metrics.increment("feedback_submissions")
    log.info(
        "Feedback submitted | user=%s | source=%s | reward=%d",
        user_key,
        payload.source,
        FEEDBACK_REWARD_TOKENS,
    )
    return {
        "ok": True,
        "submitted": True,
        "reward_granted": FEEDBACK_REWARD_TOKENS > 0,
        "reward_amount": FEEDBACK_REWARD_TOKENS,
        "credits_balance": credits_balance,
    }
