from app.database import SessionLocal
from app.models import User
from app.security import hash_password
from app.settings import settings


def ensure_default_user():
    # Never seed a test account in production — known credentials are a security risk.
    if settings.APP_ENV == "production":
        return

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == "test@carver.local").first()
        if existing:
            return
        user = User(
            email="test@carver.local",
            full_name="Test Crew User",
            role="crew",
            phone="+1-000-000-0000",
            nationality="Unknown",
            years_experience=2,
            current_location="Fort Lauderdale",
            password_hash=hash_password("test1234"),
            is_active=True,
        )
        db.add(user)
        db.commit()
    finally:
        db.close()
