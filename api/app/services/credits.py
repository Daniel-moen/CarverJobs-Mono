from sqlalchemy.orm import Session

from app.models import CreditAccount


def _get_or_create_account(db: Session, user_key: str) -> CreditAccount:
    account = db.query(CreditAccount).filter(CreditAccount.user_key == user_key).first()
    if account:
        return account

    account = CreditAccount(user_key=user_key, balance=0)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


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
