"""Tests for the weekly agency jobs-intel digest.

The load-bearing assertion is the paywall boundary: the digest sells the market
picture, never the way to reach anyone in it. No recruiter email, phone or
application URL, and no crew name, slug, phone or email may appear in any
rendering (markdown, HTML or JSON).
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.main import app
from app.models import CrewProfile, Job
from app.services.agency_digest import (
    apply_route_of,
    build_digest,
    region_of,
    render_html,
    render_markdown,
    role_family_of,
)
from app.routes import digest as digest_route
from app.settings import settings

# The digest router is registered here rather than relying on main.py: the
# `app.include_router(digest.router)` line is part of the same change set and
# this keeps the route tests honest either way (idempotent if main.py has it).
if not any(getattr(r, "path", "") == "/agent/digest" for r in app.routes):
    app.include_router(digest_route.router)

# Self-contained in-memory DB for the service-level tests (route tests use the
# shared `client` fixture and its own override).
_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)

_TOKEN = "test-agent-token-do-not-use-in-prod"

# Fixed window so "previous week" arithmetic is deterministic.
NOW = datetime(2026, 9, 21, 12, 0, tzinfo=timezone.utc)   # Mon 21 Sep 2026
SINCE = datetime(2026, 9, 14, 0, 0, tzinfo=timezone.utc)  # Mon 14 Sep
UNTIL = datetime(2026, 9, 21, 0, 0, tzinfo=timezone.utc)  # Mon 21 Sep (exclusive)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=_engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


def _job(session, *, title="Deckhand", role="Deckhand", location="Antibes, France",
         created_at=None, status="open", salary_min=None, salary_max=None,
         currency="EUR", length=None, contract="Rotational",
         contact_email=None, application_url=None, commit=True):
    job = Job(
        title=title,
        role=role,
        yacht="MY Test",
        location=location,
        status=status,
        contract_type=contract,
        salary_currency=currency,
        salary_min=salary_min,
        salary_max=salary_max,
        yacht_length_m=length,
        contact_email=contact_email,
        application_url=application_url,
    )
    session.add(job)
    session.commit()
    # server_default stamps "now" — back-date explicitly for window tests.
    job.created_at = created_at or (SINCE + timedelta(days=1))
    if commit:
        session.commit()
    return job


def _profile(session, *, key="+27820000001", role="Deckhand", location="Cape Town",
             nationality="South African", years="4", certs="STCW, ENG1, Powerboat 2",
             discoverable=True, first="Thandi", last="Nkosi", slug=None):
    profile = CrewProfile(
        user_key=key,
        profile_slug=slug or key[-8:],
        first_name=first,
        last_name=last,
        phone=key,
        nationality=nationality,
        current_location=location,
        desired_role=role,
        years_experience=years,
        certifications=certs,
        discoverable=discoverable,
    )
    session.add(profile)
    session.commit()
    return profile


# ── region_of ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "location,expected",
    [
        ("Antibes, France", "med"),
        ("Palma de Mallorca", "med"),
        ("Barcelona", "med"),
        ("Genoa, Italy", "med"),
        ("Med season", "med"),
        ("Fort Lauderdale, FL", "americas"),
        ("Florida", "americas"),
        ("Caribbean / Antigua", "americas"),
        ("St Maarten", "americas"),
        ("Cape Town", "za"),
        ("Durban, South Africa", "za"),
        ("Auckland, New Zealand", "other"),
        ("", "other"),
        (None, "other"),
    ],
)
def test_region_of_mapping(location, expected):
    assert region_of(location) == expected


def test_role_family_grouping():
    class _Stub:
        department = None

        def __init__(self, role, title=""):
            self.role = role
            self.title = title

    assert role_family_of(_Stub("Bosun")) == "deck"
    assert role_family_of(_Stub("2nd Stewardess")) == "interior"
    assert role_family_of(_Stub("Chief Engineer")) == "engineering"
    assert role_family_of(_Stub("Sous Chef")) == "galley"
    assert role_family_of(_Stub("Dive Instructor")) == "other"


def test_apply_route_type_only():
    class _Stub:
        def __init__(self, email=None, url=None):
            self.contact_email = email
            self.application_url = url

    assert apply_route_of(_Stub(url="https://www.facebook.com/groups/123/posts/9")) == "facebook"
    assert apply_route_of(_Stub(email="crew@agency.com")) == "email"
    assert apply_route_of(_Stub(url="https://agency.com/apply")) == "website"
    assert apply_route_of(_Stub()) == "unlisted"


# ── build_digest ────────────────────────────────────────────────────────────

def test_week_totals_against_previous_week(db):
    # In window: 4 jobs, 2 with a salary.
    _job(db, role="Deckhand", salary_min=3000, salary_max=3500)
    _job(db, role="Deckhand")
    _job(db, role="Stewardess", location="Palma", salary_min=3200)
    _job(db, role="Chef", location="Monaco")
    # Previous week: 2 jobs, none with a salary.
    _job(db, role="Deckhand", created_at=SINCE - timedelta(days=2))
    _job(db, role="Bosun", created_at=SINCE - timedelta(days=5))
    # Outside both windows entirely.
    _job(db, role="Purser", created_at=SINCE - timedelta(days=30))

    digest = build_digest(db, SINCE, UNTIL)

    assert digest.totals.jobs == 4
    assert digest.totals.with_salary == 2
    assert digest.totals.salary_pct == 50
    assert digest.previous.jobs == 2
    assert digest.previous.salary_pct == 0
    assert digest.jobs_delta == 2
    assert digest.salary_pct_delta == 50
    assert digest.totals.top_roles[0] == ("Deckhand", 2)
    assert digest.totals.top_locations[0] == ("Antibes, France", 2)


def test_expired_jobs_still_count_as_posted(db):
    _job(db, role="Deckhand", status="open")
    _job(db, role="Stewardess", status="expired")
    _job(db, role="Chef", status="filled")

    digest = build_digest(db, SINCE, UNTIL)

    assert digest.totals.jobs == 3
    closed = [j for j in digest.jobs if not j.still_open]
    assert len(closed) == 2


def test_region_filter_scopes_jobs(db):
    _job(db, role="Deckhand", location="Antibes, France")
    _job(db, role="Stewardess", location="Cape Town")
    _job(db, role="Chef", location="Fort Lauderdale, FL")

    assert build_digest(db, SINCE, UNTIL, region="za").totals.jobs == 1
    assert build_digest(db, SINCE, UNTIL, region="med").totals.jobs == 1
    assert build_digest(db, SINCE, UNTIL).totals.jobs == 3


def test_grouped_by_role_family(db):
    _job(db, role="Deckhand")
    _job(db, role="Bosun")
    _job(db, role="Chief Stewardess")
    _job(db, role="2nd Engineer")

    digest = build_digest(db, SINCE, UNTIL)
    grouped = {family: len(items) for family, items in digest.groups}

    assert grouped == {"deck": 2, "interior": 1, "engineering": 1}
    # Families are emitted in a fixed order: deck, interior, engineering, …
    assert [f for f, _ in digest.groups] == ["deck", "interior", "engineering"]


def test_crew_teaser_is_anonymous_and_respects_discoverable(db):
    _job(db, role="Deckhand", location="Cape Town")
    _job(db, role="Deckhand", location="Cape Town")
    _profile(db, key="+27820000001", role="Deckhand", location="Cape Town")
    _profile(db, key="+27820000002", role="Bosun", location="Durban")
    _profile(db, key="+27820000003", role="Deckhand", location="Cape Town",
             discoverable=False, first="Hidden")
    _profile(db, key="+27820000004", role="Chef", location="Cape Town")

    digest = build_digest(db, SINCE, UNTIL, region="za")

    assert digest.top_role == "Deckhand"
    # Deckhand + Bosun (adjacent in the deck department); never the chef, never
    # the undiscoverable profile.
    assert len(digest.crew) == 2
    assert {c.desired_role for c in digest.crew} == {"Deckhand", "Bosun"}
    assert all(c.certs_count == 3 for c in digest.crew)
    assert all(c.region == "za" for c in digest.crew)
    payload = str([c.to_dict() for c in digest.crew])
    for secret in ("Thandi", "Nkosi", "+2782", "Hidden"):
        assert secret not in payload


def test_crew_teaser_capped_at_three(db):
    _job(db, role="Stewardess", location="Palma")
    for i in range(5):
        _profile(db, key=f"+3460000000{i}", role="Stewardess", location="Palma")

    digest = build_digest(db, SINCE, UNTIL, region="med")
    assert len(digest.crew) == 3


# ── contact-detail exclusion (the paywall boundary) ─────────────────────────

_SECRETS = ("recruiter@agency.com", "+33600112233", "https://apply.agency.com/role/9")


def test_digest_never_exposes_contact_details(db):
    _job(
        db,
        role="Deckhand",
        location="Antibes, France",
        contact_email="recruiter@agency.com",
        application_url="https://apply.agency.com/role/9",
        salary_min=3000,
    )
    _profile(db, key="+33600112233", role="Deckhand", location="Antibes")

    digest = build_digest(db, SINCE, UNTIL)
    renderings = [
        render_markdown(digest),
        render_html(digest),
        str(digest.to_dict()),
    ]

    for text in renderings:
        for secret in _SECRETS:
            assert secret not in text
        # The apply *route type* is fine — that is the intel.
        assert "Deckhand" in text


# ── renderers ───────────────────────────────────────────────────────────────

def test_render_markdown_shape(db):
    _job(db, role="Deckhand", location="Antibes, France", salary_min=3000,
         salary_max=3500, length=48)
    _job(db, role="Deckhand", location="Antibes, France")
    _job(db, role="Chief Stewardess", location="Palma", status="expired")
    _profile(db, key="+33600112299", role="Deckhand", location="Antibes")

    md = render_markdown(build_digest(db, SINCE, UNTIL))

    assert md.startswith("# Superyacht jobs intel — 14–20 Sep 2026")
    assert "## This week at a glance" in md
    assert "**3 roles posted**" in md
    assert "## Deck (2)" in md
    assert "## Interior (1)" in md
    assert "48m" in md
    assert "EUR 3,000–3,500 / month" in md
    assert "salary not published" in md
    assert "already off the market" in md
    assert "Crew on Carver for Deckhand roles" in md
    assert md.rstrip().endswith(
        "Compiled by CARVER · jobcarver.co · reply to this email to talk"
    )


def test_render_markdown_handles_empty_week(db):
    md = render_markdown(build_digest(db, SINCE, UNTIL))
    assert "No roles were posted in this window." in md
    assert "Compiled by CARVER" in md


def test_render_html_is_standalone_and_escaped(db):
    _job(db, role="Deckhand", title="Deckhand <script>alert(1)</script>",
         location="Antibes, France", salary_min=3000)

    out = render_html(build_digest(db, SINCE, UNTIL))

    assert out.startswith("<!doctype html>")
    assert '<meta name="viewport"' in out
    assert "<style>" in out and "@media print" in out
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out
    assert "Compiled by CARVER" in out
    assert "jobcarver.co" in out


# ── route ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _set_agent_token(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_API_TOKEN", _TOKEN)


def _auth():
    return {"Authorization": f"Bearer {_TOKEN}"}


def _seed_via_client(client, **kwargs):
    """Insert a job through the app's own (conftest-overridden) session."""
    from app.database import get_db

    gen = app.dependency_overrides[get_db]()
    session = next(gen)
    try:
        job = _job(session, **kwargs)
        return job.id
    finally:
        gen.close()


def test_digest_route_requires_agent_token(client):
    app.state.db_ready = True
    assert client.get("/agent/digest").status_code == 401
    assert client.get(
        "/agent/digest", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_digest_route_default_window_markdown(client):
    app.state.db_ready = True
    _seed_via_client(client, role="Deckhand", created_at=datetime.now(timezone.utc) - timedelta(days=1))

    resp = client.get("/agent/digest", headers=_auth())

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "Superyacht jobs intel" in resp.text
    assert "## Deck (1)" in resp.text


def test_digest_route_week_and_formats(client):
    app.state.db_ready = True
    # 2026-W38 runs Mon 14 Sep – Sun 20 Sep 2026.
    _seed_via_client(client, role="Stewardess", location="Palma",
                     created_at=datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc),
                     contact_email="recruiter@agency.com")

    md = client.get("/agent/digest?week=2026-W38", headers=_auth())
    assert md.status_code == 200
    assert "## Interior (1)" in md.text
    assert "recruiter@agency.com" not in md.text

    html_resp = client.get("/agent/digest?week=2026-W38&format=html", headers=_auth())
    assert html_resp.status_code == 200
    assert html_resp.headers["content-type"].startswith("text/html")
    assert html_resp.text.startswith("<!doctype html>")

    js = client.get("/agent/digest?week=2026-W38&format=json&region=med", headers=_auth())
    assert js.status_code == 200
    body = js.json()
    assert body["ok"] is True
    assert body["region"] == "med"
    assert body["totals"]["jobs"] == 1
    assert body["groups"][0]["family"] == "interior"
    assert body["groups"][0]["jobs"][0]["apply_route"] == "email"
    assert "contact_email" not in str(body)


def test_digest_route_explicit_since_until(client):
    app.state.db_ready = True
    _seed_via_client(client, role="Deckhand",
                     created_at=datetime(2026, 9, 16, 9, 0, tzinfo=timezone.utc))
    _seed_via_client(client, role="Chef",
                     created_at=datetime(2026, 8, 1, 9, 0, tzinfo=timezone.utc))

    resp = client.get(
        "/agent/digest?since=2026-09-14T00:00:00Z&until=2026-09-21T00:00:00Z&format=json",
        headers=_auth(),
    )
    assert resp.status_code == 200
    assert resp.json()["totals"]["jobs"] == 1


def test_digest_route_rejects_bad_params(client):
    app.state.db_ready = True
    assert client.get("/agent/digest?week=nonsense", headers=_auth()).status_code == 400
    assert client.get("/agent/digest?week=2026-W99", headers=_auth()).status_code == 400
    assert client.get("/agent/digest?format=pdf", headers=_auth()).status_code == 400
    assert client.get("/agent/digest?region=asia", headers=_auth()).status_code == 400
    assert client.get(
        "/agent/digest?since=2026-09-21T00:00:00Z&until=2026-09-14T00:00:00Z",
        headers=_auth(),
    ).status_code == 400
