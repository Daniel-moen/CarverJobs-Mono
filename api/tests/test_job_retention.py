"""Tests for the two-tier job retention policy (services/job_retention.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Job
from app.services.job_retention import purge_stale_jobs

# Self-contained in-memory DB so the test doesn't depend on conftest internals.
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=_engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


def _make_job(session, *, status="open", age_days=0, title="Deckhand"):
    """Insert a job, then back-date created_at to `age_days` ago."""
    job = Job(title=title, role="Deckhand", yacht="MY Test", location="Monaco", status=status)
    session.add(job)
    session.commit()
    if age_days:
        job.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
        session.commit()
    return job.id


def test_fresh_job_untouched(db):
    job_id = _make_job(db, status="open", age_days=0)
    counts = purge_stale_jobs(db)
    assert counts == {"expired": 0, "deleted": 0}
    job = db.get(Job, job_id)
    assert job is not None
    assert job.status == "open"


def test_old_active_job_is_expired(db):
    # 45 days old > 30-day expire cutoff, but < 90-day delete cutoff.
    job_id = _make_job(db, status="open", age_days=45)
    counts = purge_stale_jobs(db)
    assert counts["expired"] == 1
    assert counts["deleted"] == 0
    job = db.get(Job, job_id)
    assert job is not None
    assert job.status == "expired"


def test_priority_job_is_expired(db):
    job_id = _make_job(db, status="priority", age_days=45)
    counts = purge_stale_jobs(db)
    assert counts["expired"] == 1
    assert db.get(Job, job_id).status == "expired"


def test_very_old_job_is_deleted(db):
    # 120 days old > 90-day delete cutoff.
    job_id = _make_job(db, status="open", age_days=120)
    counts = purge_stale_jobs(db)
    assert counts["deleted"] == 1
    assert db.get(Job, job_id) is None


def test_mixed_counts(db):
    fresh = _make_job(db, status="open", age_days=1)
    stale = _make_job(db, status="open", age_days=40)
    very_old = _make_job(db, status="expired", age_days=200)

    counts = purge_stale_jobs(db)

    assert counts == {"expired": 1, "deleted": 1}
    assert db.get(Job, fresh).status == "open"
    assert db.get(Job, stale).status == "expired"
    assert db.get(Job, very_old) is None
