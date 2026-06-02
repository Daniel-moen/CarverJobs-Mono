import time
from datetime import datetime, timedelta, timezone

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import CreditAccount, Subscription
from app.settings import settings


def _get_or_create_account(db: Session, user_key: str) -> CreditAccount:
    account = db.query(CreditAccount).filter(CreditAccount.user_key == user_key).first()
    if account:
        _maybe_reset_monthly(db, account)
        return account

    initial_balance = settings.FREE_MONTHLY_TOKENS if is_subscribed(db, user_key) else settings.FREE_SIGNUP_TOKENS
    account = CreditAccount(
        user_key=user_key,
        balance=initial_balance,
        last_reset_at=datetime.now(timezone.utc),
    )
    db.add(account)
    for attempt in range(3):
        try:
            db.commit()
            break
        except OperationalError:
            db.rollback()
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
            db.add(account)
    db.refresh(account)
    return account


def _maybe_reset_monthly(db: Session, account: CreditAccount) -> None:
    """Grant the monthly token allowance if 30+ days since last reset.

    Only Pro (subscribed) users receive the monthly token top-up.
    """
    now = datetime.now(timezone.utc)
    last = account.last_reset_at
    subscribed = is_subscribed(db, account.user_key)
    if last is None:
        # Legacy account — seed it now, but only for subscribers.
        if subscribed:
            account.balance = max(account.balance, settings.FREE_MONTHLY_TOKENS)
        account.last_reset_at = now
        db.commit()
        return
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if now - last >= timedelta(days=30):
        if subscribed:
            account.balance = max(account.balance, settings.FREE_MONTHLY_TOKENS)
        account.last_reset_at = now
        db.commit()


def is_subscribed(db: Session, user_key: str) -> bool:
    """Return True if the user has an active paid subscription."""
    return (
        db.query(Subscription)
        .filter(Subscription.user_key == user_key, Subscription.status == "active")
        .first()
    ) is not None


def get_credit_balance(db: Session, user_key: str) -> int:
    return _get_or_create_account(db, user_key).balance


def add_credits(db: Session, user_key: str, amount: int = 1) -> int:
    if amount < 0:
        raise ValueError("amount must be non-negative")

    account = _get_or_create_account(db, user_key)
    account.balance += amount
    db.commit()
    db.refresh(account)
    return account.balance


def award_job_post_credit(db: Session, user_key: str) -> dict:
    """Grant +1 free token for posting a job, capped per 30-day window.

    Replaces the old unlimited "post a job → get a token" loop. The cap
    (FREE_JOB_POST_TOKENS_PER_MONTH) is shared across web + WhatsApp because it
    keys off the same credit account. Returns:
        {"granted": bool, "balance": int, "remaining": int}
    where ``remaining`` is how many more free tokens can still be earned this window.
    """
    cap = settings.FREE_JOB_POST_TOKENS_PER_MONTH
    account = _get_or_create_account(db, user_key)

    now = datetime.now(timezone.utc)
    start = account.job_post_window_start
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if start is None or now - start >= timedelta(days=30):
        account.job_post_tokens_earned = 0
        account.job_post_window_start = now

    if account.job_post_tokens_earned >= cap:
        db.commit()
        return {"granted": False, "balance": account.balance, "remaining": 0}

    account.balance += 1
    account.job_post_tokens_earned += 1
    db.commit()
    db.refresh(account)
    return {
        "granted": True,
        "balance": account.balance,
        "remaining": max(0, cap - account.job_post_tokens_earned),
    }


def spend_credits(db: Session, user_key: str, amount: int = 1) -> int | None:
    if amount < 0:
        raise ValueError("amount must be non-negative")

    for attempt in range(3):
        try:
            account = _get_or_create_account(db, user_key)
            if account.balance < amount:
                return None
            account.balance -= amount
            db.commit()
            db.refresh(account)
            return account.balance
        except OperationalError:
            db.rollback()
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
