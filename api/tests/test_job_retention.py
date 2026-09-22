"""Tests for the two-tier job retention policy (services/job_retention.py)."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Job
from app.services.job_retention import fb_expire_after_days, purge_stale_jobs
from app.settings import settings

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


def _make_job(
    session, *, status="open", age_days=0, title="Deckhand",
    source="manual", application_url=None,
):
    """Insert a job, then back-date created_at to `age_days` ago."""
    job = Job(
        title=title, role="Deckhand", yacht="MY Test", location="Monaco", status=status,
        source=source, application_url=application_url,
    )
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


# ── Facebook-group jobs expire on a shorter clock ─────────────────────────────
# A vacancy posted in a crew group is filled in days; showing a three-week-old
# group post as live supply is how the board starts lying to crew.

def test_facebook_job_expires_after_14_days(db):
    job_id = _make_job(db, status="open", age_days=20, source="apify")

    counts = purge_stale_jobs(db)

    assert counts["expired"] == 1
    assert db.get(Job, job_id).status == "expired"


def test_facebook_job_under_14_days_is_untouched(db):
    job_id = _make_job(db, status="open", age_days=10, source="apify")

    assert purge_stale_jobs(db)["expired"] == 0
    assert db.get(Job, job_id).status == "open"


def test_job_board_job_keeps_the_30_day_clock(db):
    """Same age that expires a Facebook job must NOT expire a board listing."""
    job_id = _make_job(db, status="open", age_days=20, source="workonayacht")

    assert purge_stale_jobs(db)["expired"] == 0
    assert db.get(Job, job_id).status == "open"


def test_facebook_url_counts_even_when_source_is_manual(db):
    """Group posts imported by hand carry a facebook.com link, not source=apify."""
    job_id = _make_job(
        db, status="open", age_days=20, source="manual",
        application_url="https://www.facebook.com/groups/123/posts/456",
    )

    assert purge_stale_jobs(db)["expired"] == 1
    assert db.get(Job, job_id).status == "expired"


def test_null_source_and_url_still_expire_on_the_long_clock(db):
    """NULL IN (...) is NULL in SQL, not false — the non-FB pass must still match."""
    job_id = _make_job(db, status="open", age_days=45, source=None, application_url=None)

    assert purge_stale_jobs(db)["expired"] == 1
    assert db.get(Job, job_id).status == "expired"


def test_both_clocks_run_in_one_pass(db):
    fb_stale = _make_job(db, status="open", age_days=20, source="apify")
    fb_fresh = _make_job(db, status="open", age_days=3, source="apify")
    board_mid = _make_job(db, status="open", age_days=20, source="workonayacht")
    board_stale = _make_job(db, status="open", age_days=40, source="workonayacht")

    counts = purge_stale_jobs(db)

    assert counts["expired"] == 2
    assert db.get(Job, fb_stale).status == "expired"
    assert db.get(Job, fb_fresh).status == "open"
    assert db.get(Job, board_mid).status == "open"
    assert db.get(Job, board_stale).status == "expired"


def test_fb_expiry_days_is_configurable(db, monkeypatch):
    monkeypatch.setattr(settings, "JOB_EXPIRE_AFTER_DAYS_FB", 7)
    job_id = _make_job(db, status="open", age_days=10, source="apify")

    assert purge_stale_jobs(db)["expired"] == 1
    assert db.get(Job, job_id).status == "expired"


def test_defaults_to_14_days(monkeypatch):
    assert settings.JOB_EXPIRE_AFTER_DAYS_FB == 14
    assert fb_expire_after_days() == 14


def test_falls_back_to_the_env_var_without_the_setting(db, monkeypatch):
    """Keeps working against a settings build that predates the setting."""
    # The attribute lives on the Settings class, so blank it on the instance
    # rather than deleting it — same effect as a build that never declared it.
    monkeypatch.setattr(settings, "JOB_EXPIRE_AFTER_DAYS_FB", None)
    monkeypatch.setenv("JOB_EXPIRE_AFTER_DAYS_FB", "7")

    assert fb_expire_after_days() == 7

    job_id = _make_job(db, status="open", age_days=10, source="apify")
    assert purge_stale_jobs(db)["expired"] == 1
    assert db.get(Job, job_id).status == "expired"
