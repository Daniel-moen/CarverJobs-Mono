"""Tests for the public job board (routes/job_board.py).

The board is the SEO acquisition surface, so every assertion is made against
the raw response text — that is exactly what a crawler receives, with no
JavaScript executed.

Two properties matter most and are asserted repeatedly:
  * scraped recruiter contact details must never reach a public page, and
  * scraped text is hostile input, so it must be HTML-escaped.
"""

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import pytest

from app.main import app
from app.models import Job
from app.routes import job_board
from tests.conftest import _TestingSession

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


@pytest.fixture(autouse=True)
def _force_db_ready(client):
    """Skip the startup-ready gate; the in-memory DB is created synchronously."""
    app.state.db_ready = True
    yield


def _make_job(
    *,
    title="Chief Stewardess",
    role="Stewardess",
    location="Antibes, France",
    status="open",
    age_days=0,
    salary_min=4500.0,
    salary_max=5000.0,
    salary_currency="EUR",
    description=None,
    requirements=None,
    contact_email=None,
    **extra,
) -> int:
    db = _TestingSession()
    try:
        job = Job(
            title=title,
            role=role,
            yacht="MY Serenity",
            location=location,
            status=status,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_currency=salary_currency,
            description=description,
            requirements=requirements,
            contact_email=contact_email,
            **extra,
        )
        db.add(job)
        db.commit()
        if age_days:
            job.created_at = datetime.now(timezone.utc) - timedelta(days=age_days)
            db.commit()
        return job.id
    finally:
        db.close()


def _slug_for(job_id: int) -> str:
    db = _TestingSession()
    try:
        return job_board.job_slug(db.get(Job, job_id))
    finally:
        db.close()


# ── Board index ─────────────────────────────────────────────────────────────

def test_board_renders_open_jobs(client):
    job_id = _make_job(age_days=3)
    resp = client.get("/jobs/board")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    html = resp.text
    assert "Chief Stewardess" in html
    assert "Antibes, France" in html
    assert "EUR 4,500–5,000 / month" in html
    assert "3 days ago" in html
    assert f'href="/jobs/board/stewardess-antibes-france-{job_id}"' in html
    # SEO chrome
    assert '<link rel="canonical" href="https://jobcarver.co/jobs/board"' in html
    assert '"@type": "CollectionPage"' in html


def test_board_lists_newest_first(client):
    _make_job(title="Older Deckhand", role="Deckhand", age_days=10)
    _make_job(title="Newer Bosun", role="Bosun", age_days=1)
    html = client.get("/jobs/board").text
    assert html.index("Newer Bosun") < html.index("Older Deckhand")


def test_board_hides_non_open_jobs(client):
    _make_job(title="Filled Chef", status="filled")
    _make_job(title="Expired Deckhand", status="expired")
    _make_job(title="Live Engineer")
    html = client.get("/jobs/board").text
    assert "Live Engineer" in html
    assert "Filled Chef" not in html
    assert "Expired Deckhand" not in html


def test_board_empty_state(client):
    resp = client.get("/jobs/board")
    assert resp.status_code == 200
    assert "No open roles are listed right now" in resp.text


def test_board_has_whatsapp_and_signup_ctas(client):
    _make_job()
    html = client.get("/jobs/board").text
    assert "https://wa.me/27688516141?text=" in html
    # " · jobboard" percent-encoded — the source attribution suffix.
    assert "%20%C2%B7%20jobboard" in html
    assert 'href="/signup"' in html


def test_board_still_leaves_authenticated_jobs_api_alone(client):
    """`/jobs/board` must not shadow the existing auth-gated `/jobs` API."""
    _make_job()
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


# ── Detail page ─────────────────────────────────────────────────────────────

def test_job_page_renders(client):
    job_id = _make_job(
        age_days=1,
        description="Busy 50m charter yacht seeking an experienced chief stew.",
        requirements="STCW 95\nENG1 medical\n3 seasons on charter",
        start_date="ASAP",
        contract_type="permanent",
        experience_required_years=3,
    )
    slug = _slug_for(job_id)
    resp = client.get(f"/jobs/board/{slug}")

    assert resp.status_code == 200
    html = resp.text
    assert "Chief Stewardess" in html
    assert "Busy 50m charter yacht" in html
    assert "ENG1 medical" in html
    assert "Antibes, France" in html
    assert "EUR 4,500–5,000 / month" in html
    assert "yesterday" in html
    assert f'<link rel="canonical" href="https://jobcarver.co/jobs/board/{slug}"' in html
    assert '<meta property="og:title"' in html
    assert '<meta property="og:url" content="https://jobcarver.co/jobs/board/' in html
    assert "https://wa.me/27688516141?text=" in html
    assert "%20%C2%B7%20jobboard" in html
    assert 'href="/signup"' in html


def test_job_page_json_ld_is_valid_jobposting(client):
    job_id = _make_job(age_days=2, description="Great role on a busy charter boat.")
    html = client.get(f"/jobs/board/{_slug_for(job_id)}").text

    blocks = re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    )
    assert blocks, "no JSON-LD block rendered"
    payload = json.loads(blocks[0])
    assert payload["@type"] == "JobPosting"
    assert payload["title"] == "Chief Stewardess"
    assert payload["datePosted"]
    assert payload["validThrough"] > payload["datePosted"]
    assert payload["hiringOrganization"]["name"] == "Carver"
    assert payload["jobLocation"]["address"]["addressLocality"] == "Antibes, France"
    assert payload["baseSalary"]["currency"] == "EUR"
    assert payload["baseSalary"]["value"]["minValue"] == 4500.0
    assert payload["identifier"]["value"] == str(job_id)


def test_job_page_accepts_bare_id_and_canonicalises(client):
    job_id = _make_job()
    resp = client.get(f"/jobs/board/{job_id}")
    assert resp.status_code == 200
    # Canonical always points at the slugged URL, whatever form was requested.
    assert f'rel="canonical" href="https://jobcarver.co/jobs/board/{_slug_for(job_id)}"' in resp.text


def test_job_page_links_to_other_open_jobs(client):
    job_id = _make_job(title="Primary Role")
    _make_job(title="Second Role", role="Deckhand")
    html = client.get(f"/jobs/board/{_slug_for(job_id)}").text
    assert "Second Role" in html
    assert 'href="/jobs/board' in html


@pytest.mark.parametrize("status", ["closed", "expired", "filled", "archived"])
def test_closed_job_returns_410_with_board_link(client, status):
    job_id = _make_job(title="Gone Role", status=status)
    resp = client.get(f"/jobs/board/{job_id}")

    assert resp.status_code == 410
    assert resp.headers["content-type"].startswith("text/html")
    assert 'href="/jobs/board"' in resp.text
    assert "no longer open" in resp.text
    assert 'content="noindex, follow"' in resp.text
    # The dead listing's own content must not be re-published on the 410 page.
    assert "Gone Role" not in resp.text


def test_unknown_job_returns_404_html(client):
    resp = client.get("/jobs/board/999999")
    assert resp.status_code == 404
    assert 'href="/jobs/board"' in resp.text


def test_malformed_ref_returns_404(client):
    resp = client.get("/jobs/board/not-a-real-job")
    assert resp.status_code == 404


# ── Contact-detail leakage (the paid surface must stay paid) ────────────────

def test_contact_email_never_appears_on_public_pages(client):
    job_id = _make_job(
        title="Chief Engineer",
        role="Engineer",
        contact_email="recruiter@secretagency.com",
        description="Apply to recruiter@secretagency.com or WhatsApp +33 6 12 34 56 78.",
        requirements="Send CV to crew@agency.co.uk — see https://agency.co.uk/apply",
    )
    slug = _slug_for(job_id)

    for path in ("/jobs/board", f"/jobs/board/{slug}"):
        html = client.get(path).text
        assert "recruiter@secretagency.com" not in html
        assert "secretagency" not in html
        assert "crew@agency.co.uk" not in html
        assert "agency.co.uk" not in html
        assert "+33 6 12 34 56 78" not in html
        assert "33 6 12 34 56 78" not in html

    detail = client.get(f"/jobs/board/{slug}").text
    assert job_board._REDACTED in detail


def test_recruiter_identity_is_not_published(client):
    job_id = _make_job(
        recruiter_name="Jane Poacher",
        recruiter_agency="Poacher Crew Ltd",
        application_url="https://poacher.example/apply/123",
    )
    html = client.get(f"/jobs/board/{_slug_for(job_id)}").text
    assert "Jane Poacher" not in html
    assert "Poacher Crew Ltd" not in html
    assert "poacher.example" not in html


def test_salary_figures_are_not_mistaken_for_phone_numbers(client):
    job_id = _make_job(description="Package is 4500 - 5000 EUR per month, starting 2026-05-01.")
    html = client.get(f"/jobs/board/{_slug_for(job_id)}").text
    assert "4500 - 5000 EUR per month" in html
    assert "2026-05-01" in html


# ── Hostile input (scraped from Facebook) ───────────────────────────────────

def test_scraped_html_is_escaped(client):
    job_id = _make_job(
        title='Deckhand <script>alert("xss")</script>',
        role="Deckhand",
        location='Palma" onmouseover="evil()',
        description="<img src=x onerror=alert(1)>",
    )
    for path in ("/jobs/board", f"/jobs/board/{_slug_for(job_id)}"):
        html = client.get(path).text
        assert "<script>alert" not in html
        assert "<img src=x" not in html
        assert 'onmouseover="evil()"' not in html
        assert "&lt;script&gt;" in html


def test_json_ld_cannot_break_out_of_script_tag(client):
    job_id = _make_job(description="</script><script>alert(1)</script>")
    html = client.get(f"/jobs/board/{_slug_for(job_id)}").text
    assert "</script><script>alert(1)" not in html
    # Angle brackets inside the JSON-LD payload are \uXXXX-escaped.
    assert "\\u003c/script\\u003e" in html
    # ...and the block still parses as JSON-LD.
    block = re.search(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.DOTALL
    ).group(1)
    assert json.loads(block)["@type"] == "JobPosting"


# ── Sitemap ─────────────────────────────────────────────────────────────────

def test_sitemap_is_valid_xml_with_open_jobs(client):
    open_id = _make_job(title="Open Bosun", role="Bosun", location="Palma")
    _make_job(title="Closed Chef", role="Chef", status="closed")

    resp = client.get("/jobs/sitemap.xml")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/xml")

    root = ET.fromstring(resp.text)
    assert root.tag == f"{_SITEMAP_NS}urlset"
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert "https://jobcarver.co/jobs/board" in locs
    assert f"https://jobcarver.co/jobs/board/bosun-palma-{open_id}" in locs
    assert not any("chef" in (loc or "") for loc in locs)
    # Every job entry carries a lastmod date.
    for url in root.iter(f"{_SITEMAP_NS}url"):
        loc = url.find(f"{_SITEMAP_NS}loc").text
        if loc != "https://jobcarver.co/jobs/board":
            assert url.find(f"{_SITEMAP_NS}lastmod") is not None


def test_sitemap_is_valid_xml_when_empty(client):
    resp = client.get("/jobs/sitemap.xml")
    assert resp.status_code == 200
    root = ET.fromstring(resp.text)
    locs = [el.text for el in root.iter(f"{_SITEMAP_NS}loc")]
    assert locs == ["https://jobcarver.co/jobs/board"]


# ── Pure helpers ────────────────────────────────────────────────────────────

def test_posted_ago_wording():
    now = datetime(2026, 9, 22, 12, 0, tzinfo=timezone.utc)
    ago = job_board.posted_ago
    assert ago(now - timedelta(minutes=5), now=now) == "just now"
    assert ago(now - timedelta(hours=1), now=now) == "1 hour ago"
    assert ago(now - timedelta(hours=5), now=now) == "5 hours ago"
    assert ago(now - timedelta(days=1), now=now) == "yesterday"
    assert ago(now - timedelta(days=3), now=now) == "3 days ago"
    assert ago(now - timedelta(days=65), now=now) == "2 months ago"
    assert ago(None) == ""
    # Naive datetimes (SQLite) are treated as UTC, not crashed on.
    assert ago(datetime(2026, 9, 19, 12, 0), now=now) == "3 days ago"


def test_job_slug_is_stable_and_url_safe():
    job = Job(id=42, title="X", role="Chief Stew/ardess", yacht="Y", location="Côte d'Azur!")
    slug = job_board.job_slug(job)
    assert slug == "chief-stew-ardess-c-te-d-azur-42"
    assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slug)
    assert job_board._parse_job_ref(slug) == 42
    assert job_board._parse_job_ref("42") == 42
    assert job_board._parse_job_ref("no-digits") is None
    assert job_board._parse_job_ref("../../etc/passwd") is None


def test_whatsapp_prefill_always_carries_the_source_tag():
    link = job_board.whatsapp_link("Hi Carver, I'd like to apply for Deckhand")
    assert link.startswith("https://wa.me/27688516141?text=")
    assert link.endswith("%20%C2%B7%20jobboard")
    assert job_board.whatsapp_link("").endswith("%20%C2%B7%20jobboard")


def test_salary_text_variants():
    def job(**kw):
        return Job(title="t", role="r", yacht="y", location="l", **kw)

    assert job_board.salary_text(job(salary_min=4000, salary_max=5000)) == "EUR 4,000–5,000 / month"
    assert job_board.salary_text(job(salary_min=4000, salary_max=None)) == "EUR 4,000 / month"
    assert job_board.salary_text(job(salary_min=None, salary_max=6000, salary_currency="USD")) == "USD up to 6,000 / month"
    assert job_board.salary_text(job()) == ""
