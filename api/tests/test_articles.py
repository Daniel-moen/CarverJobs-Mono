"""Tests for /articles — SSR HTML, JSON API, and related-article linking.

Key SEO assertion: every page must have its content and internal links
present in the raw HTML response (no JavaScript execution). Each test
calls `.text` on the response directly — that is exactly what a crawler
receives.
"""

import pytest

from app.main import app
from app.settings import settings


_TOKEN = "test-agent-token-do-not-use-in-prod"


@pytest.fixture(autouse=True)
def _set_agent_token(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_API_TOKEN", _TOKEN)


@pytest.fixture(autouse=True)
def _force_db_ready(client):
    """Skip the startup-ready gate; the in-memory DB is created synchronously.

    Depends on `client` so we run *after* the TestClient lifespan has
    (re)initialised `app.state.db_ready = False`.
    """
    app.state.db_ready = True
    yield


def _auth():
    return {"Authorization": f"Bearer {_TOKEN}"}


def _payload(slug, *, title=None, keywords=None, body=None, description=None):
    return {
        "slug": slug,
        "title": title or f"Guide {slug}",
        "description": description or f"A short guide about {slug}.",
        "date": "2026-01-15",
        "read_minutes": 4,
        "keywords": keywords if keywords is not None else ["yacht", "crew"],
        "body": body
        or [
            {"type": "h2", "text": "Overview"},
            {"type": "p", "text": f"Article body for {slug}."},
            {"type": "ul", "items": ["First point", "Second point"]},
        ],
        "published": True,
    }


# ── API: create / list / get ────────────────────────────────────────────────

def test_create_article_requires_agent_token(client):
    resp = client.post("/agent/articles", json=_payload("hello-world"))
    assert resp.status_code == 401


def test_create_article_with_token(client):
    resp = client.post(
        "/agent/articles", json=_payload("how-to-get-yacht-job"), headers=_auth()
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["created"] is True
    assert body["article"]["slug"] == "how-to-get-yacht-job"


def test_list_articles_json(client):
    client.post("/agent/articles", json=_payload("alpha"), headers=_auth())
    client.post("/agent/articles", json=_payload("beta"), headers=_auth())

    resp = client.get("/articles")
    assert resp.status_code == 200
    slugs = {a["slug"] for a in resp.json()["articles"]}
    assert slugs == {"alpha", "beta"}


def test_get_article_by_slug(client):
    client.post(
        "/agent/articles", json=_payload("how-to-get-yacht-job"), headers=_auth()
    )
    resp = client.get("/articles/how-to-get-yacht-job")
    assert resp.status_code == 200
    assert resp.json()["article"]["slug"] == "how-to-get-yacht-job"


def test_unpublished_articles_are_hidden_from_public(client):
    payload = _payload("draft")
    payload["published"] = False
    client.post("/agent/articles", json=payload, headers=_auth())

    assert client.get("/articles").json()["articles"] == []
    assert client.get("/articles/draft").status_code == 404


def test_invalid_slug_in_payload_rejected(client):
    payload = _payload("Has Spaces")  # triggers field validator
    resp = client.post("/agent/articles", json=payload, headers=_auth())
    assert resp.status_code == 422


# ── SSR: articles list page (/articles/list.html) ───────────────────────────

def test_list_html_contains_every_article_link_in_raw_html(client):
    slugs = ["how-to-get-yacht-job", "season-timeline", "cv-tips"]
    for s in slugs:
        client.post("/agent/articles", json=_payload(s), headers=_auth())

    resp = client.get("/articles/list.html")
    assert resp.status_code == 200
    html = resp.text
    assert resp.headers["content-type"].startswith("text/html")

    # Every article link must be in the initial HTML — no JS required.
    for s in slugs:
        assert f'href="/articles/{s}"' in html

    # SEO tags must be present.
    assert "<title>Articles — Carver</title>" in html
    assert '<meta name="description"' in html
    assert '<link rel="canonical"' in html
    assert '<meta name="robots" content="index, follow' in html
    assert '"@type": "CollectionPage"' in html


def test_list_html_handles_empty_state(client):
    resp = client.get("/articles/list.html")
    assert resp.status_code == 200
    # Page still renders with SEO meta, just without articles.
    assert "<title>Articles — Carver</title>" in resp.text
    assert "No articles have been published yet" in resp.text


def test_list_html_escapes_author_content(client):
    payload = _payload(
        "xss-attempt",
        title="<script>alert(1)</script> evil",
        description='" onload="alert(1)',
    )
    client.post("/agent/articles", json=payload, headers=_auth())

    resp = client.get("/articles/list.html")
    # Raw script tag must never appear in rendered output.
    assert "<script>alert(1)</script>" not in resp.text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in resp.text


# ── SSR: single article page (/articles/{slug}/page.html) ───────────────────

def test_article_page_content_present_without_js(client):
    client.post(
        "/agent/articles",
        json=_payload(
            "how-to-get-yacht-job",
            title="How to get a yacht job",
            description="A guide for green crew.",
            body=[
                {"type": "h2", "text": "Step one"},
                {"type": "p", "text": "Walk the docks."},
                {"type": "ul", "items": ["Bring your CV", "Stay polite"]},
            ],
        ),
        headers=_auth(),
    )
    resp = client.get("/articles/how-to-get-yacht-job/page.html")
    assert resp.status_code == 200
    html = resp.text

    # Content is present in the raw HTML response.
    assert "<h1" in html and "How to get a yacht job" in html
    assert "<h2>Step one</h2>" in html
    assert "<p>Walk the docks.</p>" in html
    assert "<li>Bring your CV</li>" in html

    # SEO essentials.
    assert "<title>How to get a yacht job — Carver</title>" in html
    assert '<meta name="description" content="A guide for green crew."' in html
    assert '<link rel="canonical"' in html
    assert '"@type": "Article"' in html


def test_article_page_includes_related_articles(client):
    # Seed a shared-keyword cluster plus one unrelated article.
    client.post(
        "/agent/articles",
        json=_payload("how-to-get-yacht-job", keywords=["yacht", "career", "crew"]),
        headers=_auth(),
    )
    client.post(
        "/agent/articles",
        json=_payload("season-timeline", keywords=["yacht", "season"]),
        headers=_auth(),
    )
    client.post(
        "/agent/articles",
        json=_payload("cv-tips", keywords=["career", "crew"]),
        headers=_auth(),
    )
    client.post(
        "/agent/articles",
        json=_payload("unrelated-topic", keywords=["cooking"]),
        headers=_auth(),
    )

    resp = client.get("/articles/how-to-get-yacht-job/page.html")
    html = resp.text

    # Related block present with at least 2 sibling links (internal linking).
    assert 'aria-label="Related articles"' in html
    # Cluster partners are linked.
    assert 'href="/articles/season-timeline"' in html
    assert 'href="/articles/cv-tips"' in html


def test_article_page_404_for_unknown_slug(client):
    resp = client.get("/articles/does-not-exist/page.html")
    assert resp.status_code == 404


def test_article_page_404_for_malformed_slug(client):
    # Uppercase / spaces must not hit the DB path — strict regex rejects first.
    resp = client.get("/articles/BAD_SLUG/page.html")
    assert resp.status_code == 404


# ── Agent: update + delete ──────────────────────────────────────────────────

def test_upsert_updates_existing_article(client):
    client.post(
        "/agent/articles",
        json=_payload("alpha", title="Original"),
        headers=_auth(),
    )
    resp = client.post(
        "/agent/articles",
        json=_payload("alpha", title="Revised"),
        headers=_auth(),
    )
    assert resp.json()["created"] is False
    assert resp.json()["article"]["title"] == "Revised"


def test_delete_requires_token_and_works(client):
    client.post("/agent/articles", json=_payload("alpha"), headers=_auth())
    assert client.delete("/agent/articles/alpha").status_code == 401
    resp = client.delete("/agent/articles/alpha", headers=_auth())
    assert resp.status_code == 200
    assert client.get("/articles/alpha").status_code == 404
