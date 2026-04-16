from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CreditAccount, Subscription
from app.settings import settings


def _get_or_create_account(db: Session, user_key: str) -> CreditAccount:
    account = db.query(CreditAccount).filter(CreditAccount.user_key == user_key).first()
    if account:
        _maybe_reset_monthly(db, account)
        return account

    # New accounts start at 0 tokens. Only Pro subscribers receive the
    # monthly token allowance (granted via _maybe_reset_monthly).
    initial_balance = settings.FREE_MONTHLY_TOKENS if is_subscribed(db, user_key) else 0
    account = CreditAccount(
        user_key=user_key,
        balance=initial_balance,
        last_reset_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()
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


def spend_credits(db: Session, user_key: str, amount: int = 1) -> int | None:
    if amount < 0:
        raise ValueError("amount must be non-negative")

    account = _get_or_create_account(db, user_key)
    if account.balance < amount:
        return None

    account.balance -= amount
    db.commit()
    db.refresh(account)
    return account.balance
