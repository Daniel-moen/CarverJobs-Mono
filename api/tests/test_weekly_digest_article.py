"""Tests for the public weekly "Superyacht jobs this week" article.

Two properties carry the most weight:

  * the article is *public* content built from scraped posts, so no recruiter
    e-mail, phone number or application URL may survive into any block, and
  * the slug is deterministic per ISO week, so the Monday loop and the manual
    endpoint upsert the same row instead of publishing duplicates.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models import Article, Job
from app.routes.job_board import job_slug
from app.services.weekly_digest_article import (
    MIN_JOBS_FOR_ARTICLE,
    build_weekly_article,
    previous_completed_week,
    publish_weekly_article,
    render_markdown,
    week_slug,
    week_window,
)
from app.settings import settings
from tests.conftest import _TestingSession

# Self-contained in-memory DB for the service-level tests; the route tests use
# the shared `client` fixture and its own override.
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

_TOKEN = "test-agent-token-do-not-use-in-prod"

WEEK = "2026-W38"                                          # Mon 14 – Sun 20 Sep 2026
SINCE = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)
UNTIL = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=_engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


def _job(
    session,
    *,
    title="Deckhand",
    role="Deckhand",
    location="Antibes, France",
    created_at=None,
    status="open",
    salary_min=None,
    salary_max=None,
    currency="EUR",
    contact_email=None,
    application_url=None,
):
    job = Job(
        title=title,
        role=role,
        yacht="MY Test",
        location=location,
        status=status,
        salary_currency=currency,
        salary_min=salary_min,
        salary_max=salary_max,
        contact_email=contact_email,
        application_url=application_url,
    )
    session.add(job)
    session.commit()
    # server_default stamps "now" — back-date explicitly for window tests.
    job.created_at = created_at or (SINCE + timedelta(days=1))
    session.commit()
    return job


def _seed_week(session, count=6):
    roles = [
        ("Deckhand", "deck", "Antibes, France"),
        ("Bosun", "deck", "Palma"),
        ("Chief Stewardess", "interior", "Antibes, France"),
        ("2nd Stewardess", "interior", "Monaco"),
        ("Sous Chef", "galley", "Fort Lauderdale, FL"),
        ("Chief Engineer", "engineering", "Cape Town"),
        ("Deckhand", "deck", "Genoa, Italy"),
        ("Purser", "interior", "Palma"),
    ]
    out = []
    for i in range(count):
        role, _family, location = roles[i % len(roles)]
        out.append(
            _job(
                session,
                title=role,
                role=role,
                location=location,
                created_at=SINCE + timedelta(days=i % 7, hours=3),
            )
        )
    return out


def _all_text(data) -> str:
    """Every character the article will render, as one blob."""
    parts = [data.title, data.description, data.slug, " ".join(data.keywords)]
    for block in data.body:
        if block.get("text"):
            parts.append(block["text"])
        parts += block.get("items") or []
    return "\n".join(parts)


# ── Week arithmetic ─────────────────────────────────────────────────────────

def test_week_window_is_monday_to_monday():
    since, until = week_window(WEEK)
    assert since == SINCE
    assert until == UNTIL


def test_week_slug_is_deterministic_and_lowercase():
    assert week_slug(WEEK) == "superyacht-jobs-this-week-2026-w38"
    assert week_slug("2026-w38") == week_slug("2026-W38")
    # Single-digit weeks are zero-padded so the slug never forks.
    assert week_slug("2026-W7") == "superyacht-jobs-this-week-2026-w07"


@pytest.mark.parametrize(
    "now,expected",
    [
        # Monday 00:30 of W39 — the completed week is W38.
        (datetime(2026, 9, 21, 0, 30, tzinfo=timezone.utc), "2026-W38"),
        # Sunday night of W39 — still W38, W39 has not finished.
        (datetime(2026, 9, 27, 23, 59, tzinfo=timezone.utc), "2026-W38"),
        # Monday 00:00 of W40 — W39 is now complete.
        (datetime(2026, 9, 28, 0, 0, tzinfo=timezone.utc), "2026-W39"),
    ],
)
def test_previous_completed_week(now, expected):
    assert previous_completed_week(now) == expected


def test_bad_week_rejected(db):
    with pytest.raises(ValueError):
        build_weekly_article(db, "not-a-week")
    with pytest.raises(ValueError):
        build_weekly_article(db, "2026-W99")


# ── build_weekly_article ────────────────────────────────────────────────────

def test_builds_headline_and_shape_from_fixture(db):
    _seed_week(db, 6)
    # Previous week, for the week-on-week line.
    _job(db, role="Deckhand", created_at=SINCE - timedelta(days=2))
    _job(db, role="Chef", created_at=SINCE - timedelta(days=4))

    data = build_weekly_article(db, WEEK)

    assert data.slug == "superyacht-jobs-this-week-2026-w38"
    assert data.title == "Superyacht jobs this week — 6 new roles (14–20 Sep 2026)"
    assert data.date == "2026-09-21"          # the Monday it is published
    assert data.week == WEEK
    assert data.job_count == 6
    assert data.published is True
    assert 1 <= data.read_minutes <= 60

    # Week-on-week totals come straight from the agency digest.
    intro = data.body[0]["text"]
    assert "6 new superyacht crew roles" in intro
    assert "The week before had 2 (+4)." in intro

    headings = [b["text"] for b in data.body if b["type"] == "h2"]
    assert "Where the jobs are" in headings
    assert "Get the roles that match your ticket" in headings
    assert any(h.startswith("Deck (") for h in headings)
    assert any(h.startswith("Interior (") for h in headings)

    # Only the block types routes/articles.py accepts.
    assert {b["type"] for b in data.body} <= {"p", "h2", "ul"}
    assert all(len(b["items"]) <= 20 for b in data.body if b["type"] == "ul")
    assert all(
        len(item) <= 500
        for b in data.body
        if b["type"] == "ul"
        for item in b["items"]
    )
    assert len(data.title) <= 200
    assert len(data.description) <= 400
    assert len(data.keywords) <= 20


def test_every_open_job_links_to_its_board_page(db):
    jobs = _seed_week(db, 6)

    data = build_weekly_article(db, WEEK)
    blob = _all_text(data)

    for job in jobs:
        assert f"/jobs/board/{job_slug(job)}" in blob
    # And the board itself is linked from the CTA.
    assert "jobcarver.co/jobs/board" in blob


def test_job_line_carries_title_location_salary_and_day(db):
    _seed_week(db, 5)
    job = _job(
        db,
        title="Chief Stewardess",
        role="Stewardess",
        location="Palma",
        salary_min=4500,
        salary_max=5000,
        created_at=SINCE + timedelta(hours=9),  # Mon 14 Sep
    )

    data = build_weekly_article(db, WEEK)
    line = next(
        item
        for block in data.body
        if block["type"] == "ul"
        for item in block["items"]
        if f"/jobs/board/{job_slug(job)}" in item
    )

    assert line.startswith("Chief Stewardess · Palma · EUR 4,500–5,000 / month")
    assert "posted Mon 14 Sep" in line


def test_filled_roles_are_listed_but_not_linked(db):
    _seed_week(db, 5)
    filled = _job(db, title="Cook", role="Cook", status="filled", location="Nice")

    data = build_weekly_article(db, WEEK)
    blob = _all_text(data)

    assert "Cook" in blob
    # The board 410s anything that is not `open`, so it must not be linked.
    assert f"/jobs/board/{job_slug(filled)}" not in blob
    assert "no longer listed" in blob


def test_no_contact_details_ever_reach_the_article(db):
    _seed_week(db, 5)
    _job(
        db,
        title="Deckhand — CV to crew@agency.com or +33 6 12 34 56 78",
        role="Deckhand",
        location="Antibes, France",
        contact_email="recruiter@yachtcrew.com",
        application_url="https://agency.example.com/apply/123",
    )

    data = build_weekly_article(db, WEEK)
    blob = _all_text(data)

    assert "crew@agency.com" not in blob
    assert "recruiter@yachtcrew.com" not in blob
    assert "agency.example.com" not in blob
    assert "+33 6 12 34 56 78" not in blob
    assert "@" not in blob.replace("wa.me", "")  # no address survives anywhere
    # The only outbound links are Carver's own.
    assert "hidden" in blob  # the board's redaction marker did the work


def test_tone_has_no_exclamation_marks(db):
    _seed_week(db, 6)
    data = build_weekly_article(db, WEEK)
    assert "!" not in _all_text(data)


def test_cta_links_to_whatsapp_with_article_tag(db):
    _seed_week(db, 5)
    data = build_weekly_article(db, WEEK)
    blob = _all_text(data)

    assert "https://wa.me/27688516141?text=" in blob
    # "· article" is the attribution token the WhatsApp backend parses.
    assert "%20%C2%B7%20article" in blob


def test_where_the_jobs_are_reports_top_locations(db):
    for i in range(6):
        _job(
            db,
            role="Deckhand",
            location="Antibes, France" if i < 4 else "Palma",
            created_at=SINCE + timedelta(days=i % 7),
        )

    data = build_weekly_article(db, WEEK)
    idx = next(
        i for i, b in enumerate(data.body)
        if b["type"] == "h2" and b["text"] == "Where the jobs are"
    )
    paragraph = data.body[idx + 1]["text"]

    assert "Antibes, France (4)" in paragraph
    assert "Palma (2)" in paragraph
    assert "Deckhand (6)" in paragraph


# ── publish_weekly_article ──────────────────────────────────────────────────

def test_publish_creates_a_published_indexable_row(db):
    _seed_week(db, 6)

    row = publish_weekly_article(db, WEEK)

    assert row is not None
    assert row.slug == "superyacht-jobs-this-week-2026-w38"
    assert row.published is True
    assert row.date == "2026-09-21"
    body = json.loads(row.body_json)
    assert body and {b["type"] for b in body} <= {"p", "h2", "ul"}
    assert json.loads(row.keywords_json)


def test_publish_is_idempotent_per_week(db):
    _seed_week(db, 6)

    first = publish_weekly_article(db, WEEK)
    first_id = first.id

    # A seventh role lands, then the week is re-run.
    _job(db, role="Purser", location="Palma", created_at=SINCE + timedelta(days=2))
    second = publish_weekly_article(db, WEEK)

    assert db.query(Article).count() == 1
    assert second.id == first_id
    assert "7 new roles" in second.title


def test_publish_skips_a_thin_week(db):
    _seed_week(db, MIN_JOBS_FOR_ARTICLE - 1)

    assert publish_weekly_article(db, WEEK) is None
    assert db.query(Article).count() == 0

    # …unless the caller explicitly lowers the bar.
    assert publish_weekly_article(db, WEEK, min_jobs=0) is not None


def test_publish_skip_if_exists_leaves_the_row_alone(db):
    _seed_week(db, 6)
    first = publish_weekly_article(db, WEEK)

    _job(db, role="Purser", created_at=SINCE + timedelta(days=2))
    assert publish_weekly_article(db, WEEK, skip_if_exists=True) is None

    db.refresh(first)
    assert "6 new roles" in first.title


def test_render_markdown_preview(db):
    _seed_week(db, 6)
    text = render_markdown(build_weekly_article(db, WEEK))
    assert text.startswith("# Superyacht jobs this week — 6 new roles")
    assert "## Where the jobs are" in text


# ── Route: POST /agent/articles/weekly-digest ───────────────────────────────

@pytest.fixture(autouse=True)
def _set_agent_token(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_API_TOKEN", _TOKEN)


@pytest.fixture()
def _force_db_ready(client):
    app.state.db_ready = True
    yield


def _auth():
    return {"Authorization": f"Bearer {_TOKEN}"}


def _seed_route_jobs(count=6):
    session = _TestingSession()
    try:
        for i in range(count):
            job = Job(
                title=f"Deckhand {i}",
                role="Deckhand",
                yacht="MY Test",
                location="Antibes, France",
                status="open",
                salary_currency="EUR",
            )
            session.add(job)
            session.commit()
            job.created_at = SINCE + timedelta(days=i % 7, hours=2)
            session.commit()
    finally:
        session.close()


def test_route_requires_agent_token(client, _force_db_ready):
    resp = client.post(f"/agent/articles/weekly-digest?week={WEEK}")
    assert resp.status_code == 401


def test_route_rejects_a_bad_week(client, _force_db_ready):
    resp = client.post("/agent/articles/weekly-digest?week=2026-W99", headers=_auth())
    assert resp.status_code == 400


def test_route_publishes_and_the_article_appears_everywhere(client, _force_db_ready):
    _seed_route_jobs(6)

    resp = client.post(f"/agent/articles/weekly-digest?week={WEEK}", headers=_auth())
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["ok"] is True and payload["published"] is True
    slug = payload["article"]["slug"]
    assert slug == "superyacht-jobs-this-week-2026-w38"

    # Listed by the JSON API…
    listed = client.get("/articles").json()["articles"]
    assert any(a["slug"] == slug for a in listed)
    # …served by the SSR page, with the job links in the raw HTML…
    page = client.get(f"/articles/{slug}/page.html")
    assert page.status_code == 200
    assert "/jobs/board/" in page.text
    assert "wa.me/27688516141" in page.text
    # …and picked up by the article sitemap.
    assert slug in client.get("/articles/sitemap.xml").text


def test_route_is_idempotent(client, _force_db_ready):
    _seed_route_jobs(6)

    first = client.post(f"/agent/articles/weekly-digest?week={WEEK}", headers=_auth())
    second = client.post(f"/agent/articles/weekly-digest?week={WEEK}", headers=_auth())

    assert first.status_code == second.status_code == 200
    slugs = [a["slug"] for a in client.get("/articles").json()["articles"]]
    assert slugs.count("superyacht-jobs-this-week-2026-w38") == 1


def test_route_reports_a_skipped_thin_week(client, _force_db_ready):
    _seed_route_jobs(MIN_JOBS_FOR_ARTICLE - 1)

    resp = client.post(f"/agent/articles/weekly-digest?week={WEEK}", headers=_auth())
    assert resp.status_code == 200
    assert resp.json()["published"] is False
    assert client.get("/articles").json()["articles"] == []

    forced = client.post(
        f"/agent/articles/weekly-digest?week={WEEK}&force=true", headers=_auth()
    )
    assert forced.json()["published"] is True
