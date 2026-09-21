"""Tests for the fingerprint dedup scope in job_sync.

The fingerprint (role|location|start_date|employer) used to be treated as
globally unique forever, so a repeat vacancy — "Stewardess / Antibes / ASAP" —
could only ever be ingested once per retention window. These tests pin the
scoped behaviour: a fingerprint only blocks while the job it belongs to is
still live (active status, posted inside _FINGERPRINT_WINDOW_DAYS).
"""
from datetime import datetime, timedelta, timezone

import app.services.job_sync as job_sync
from app.models import Job
from app.services.job_sync import _job_fingerprint, sync_jobs
from tests.conftest import _TestingSession


def _ai(**overrides):
    """AI-extracted fields for a plain stewardess job."""
    fields = {
        "title": "Stewardess",
        "role": "Stewardess",
        "location": "Antibes",
        "start_date": "ASAP",
        "yacht": "MY Aurora",
    }
    fields.update(overrides)
    return fields


def _review_stub(by_text):
    """review_post stand-in returning the AI fields mapped to each post text."""
    def _stub(post_text, post_url, api_key, model, trusted_source=False):
        return by_text[post_text]
    return _stub


def _sync(db, items):
    return sync_jobs(db, items, openai_api_key="k", openai_model="m", source="apify")


def _item(text, n):
    return {"text": text, "url": f"https://facebook.com/groups/x/{n}"}


def _backdate(db, job_id, days):
    """Age a stored job so it falls outside the live fingerprint window."""
    job = db.get(Job, job_id)
    job.created_at = datetime.now(timezone.utc) - timedelta(days=days)
    db.commit()


# ── Fingerprint key ──────────────────────────────────────────────────────────

def test_fingerprint_is_none_for_identityless_triples():
    """Unknown location or the generic "Crew" role carry no identity."""
    assert _job_fingerprint("Stewardess", "Unknown", "ASAP") is None
    assert _job_fingerprint("Stewardess", None, "ASAP") is None
    assert _job_fingerprint("Crew", "Antibes", "ASAP") is None
    assert _job_fingerprint("Stewardess", "Antibes", "ASAP") is not None


def test_employer_changes_the_fingerprint():
    """Two boats hiring the same role in the same port are different jobs."""
    a = _job_fingerprint("Stewardess", "Antibes", "ASAP", "MY Aurora")
    b = _job_fingerprint("Stewardess", "Antibes", "ASAP", "MY Bella")
    assert a != b
    # A placeholder vessel name is dropped, not hashed.
    assert (
        _job_fingerprint("Stewardess", "Antibes", "ASAP", "Private Yacht")
        == _job_fingerprint("Stewardess", "Antibes", "ASAP")
    )


# ── Scope: age ───────────────────────────────────────────────────────────────

def test_same_triple_twenty_days_apart_is_ingested(monkeypatch):
    """A repeat vacancy outside the live window is new supply, not a dupe."""
    db = _TestingSession()
    try:
        first, second = "Stew wanted in Antibes, start ASAP", "Looking for a stewardess, Antibes, asap"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(),
            second: _ai(title="Stewardess wanted"),
        }))

        assert _sync(db, [_item(first, 1)]) == (1, 0, 0)
        _backdate(db, db.query(Job.id).scalar(), 20)

        assert _sync(db, [_item(second, 2)]) == (1, 0, 0)

        jobs = db.query(Job).order_by(Job.id).all()
        assert len(jobs) == 2
        # The unique fingerprint column is handed to the fresh posting.
        assert jobs[0].job_fingerprint is None
        assert jobs[1].job_fingerprint == _job_fingerprint("Stewardess", "Antibes", "ASAP", "MY Aurora")
    finally:
        db.close()


def test_same_triple_same_week_is_deduped(monkeypatch):
    """Inside the live window the fingerprint still collapses reposts."""
    db = _TestingSession()
    try:
        first, second = "Stew wanted in Antibes, start ASAP", "Antibes stewardess needed asap!!"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(),
            second: _ai(title="Stewardess wanted"),
        }))

        assert _sync(db, [_item(first, 1)]) == (1, 0, 0)
        _backdate(db, db.query(Job.id).scalar(), 5)

        assert _sync(db, [_item(second, 2)]) == (0, 1, 0)
        assert db.query(Job).count() == 1
    finally:
        db.close()


def test_closed_job_does_not_block_ingestion(monkeypatch):
    """A filled/expired listing releases its fingerprint even when recent."""
    db = _TestingSession()
    try:
        first, second = "Stew wanted in Antibes, start ASAP", "Stewardess role, Antibes, asap start"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(),
            second: _ai(title="Stewardess opening"),
        }))

        assert _sync(db, [_item(first, 1)]) == (1, 0, 0)
        job = db.query(Job).one()
        job.status = "expired"
        db.commit()

        assert _sync(db, [_item(second, 2)]) == (1, 0, 0)
        assert db.query(Job).count() == 2
    finally:
        db.close()


# ── Scope: identityless triples ──────────────────────────────────────────────

def test_unknown_location_is_not_fingerprint_deduped(monkeypatch):
    """"Unknown" is a placeholder shared by thousands of posts."""
    db = _TestingSession()
    try:
        first, second = "Stew job, location TBC", "Another stewardess post, no location given"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(location=None, title="Stewardess A"),
            second: _ai(location=None, title="Stewardess B"),
        }))

        assert _sync(db, [_item(first, 1), _item(second, 2)]) == (2, 0, 0)
        jobs = db.query(Job).all()
        assert {j.location for j in jobs} == {"Unknown"}
        assert all(j.job_fingerprint is None for j in jobs)
    finally:
        db.close()


def test_generic_crew_role_is_not_fingerprint_deduped(monkeypatch):
    """The "Crew" fallback role is not an identity either."""
    db = _TestingSession()
    try:
        first, second = "Crew needed in Palma", "More crew wanted, Palma"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(role=None, location="Palma", title="Crew A"),
            second: _ai(role=None, location="Palma", title="Crew B"),
        }))

        assert _sync(db, [_item(first, 1), _item(second, 2)]) == (2, 0, 0)
        assert all(j.job_fingerprint is None for j in db.query(Job).all())
    finally:
        db.close()


# ── Scope: employer ──────────────────────────────────────────────────────────

def test_different_employer_is_not_a_duplicate(monkeypatch):
    """Same role, port and start date on two different boats — both ingested."""
    db = _TestingSession()
    try:
        first, second = "Stew for MY Aurora, Antibes ASAP", "Stew for MY Bella, Antibes ASAP"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(yacht="MY Aurora", title="Stewardess — Aurora"),
            second: _ai(yacht="MY Bella", title="Stewardess — Bella"),
        }))

        assert _sync(db, [_item(first, 1), _item(second, 2)]) == (2, 0, 0)
        fps = {j.job_fingerprint for j in db.query(Job).all()}
        assert len(fps) == 2 and None not in fps
    finally:
        db.close()


def test_same_employer_same_week_still_deduped(monkeypatch):
    """The employer only splits fingerprints — it doesn't disable them."""
    db = _TestingSession()
    try:
        first, second = "Stew for MY Aurora, Antibes ASAP", "MY Aurora needs a stew in Antibes asap"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(title="Stewardess — Aurora"),
            second: _ai(title="Stewardess wanted — Aurora"),
        }))

        assert _sync(db, [_item(first, 1), _item(second, 2)]) == (1, 1, 0)
        assert db.query(Job).count() == 1
    finally:
        db.close()


def test_unique_key_race_is_skipped_not_fatal(monkeypatch):
    """If another writer re-claims the fingerprint between check and insert,
    the row is skipped — the run's commit must not blow up."""
    db = _TestingSession()
    try:
        first, second = "Stew for MY Aurora, Antibes ASAP", "Stewardess, Antibes, asap start"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            first: _ai(title="Stewardess — Aurora"),
            second: _ai(title="Stewardess opening"),
        }))

        assert _sync(db, [_item(first, 1)]) == (1, 0, 0)
        _backdate(db, db.query(Job.id).scalar(), 20)
        # Simulate the stale holder keeping the key (a concurrent run re-claimed it).
        monkeypatch.setattr(job_sync, "_release_stale_fingerprint", lambda db, fp, url: False)

        assert _sync(db, [_item(second, 2)]) == (0, 1, 0)
        assert db.query(Job).count() == 1
    finally:
        db.close()


# ── Instrumentation ──────────────────────────────────────────────────────────

class _RecordingLog:
    """Captures log calls so the run summary can be asserted on."""

    def __init__(self):
        self.calls: list[tuple] = []

    def _record(self, *args, **kwargs):
        self.calls.append(args)

    debug = info = error = warning = _record


def test_sync_summary_counts_dupes_by_reason(monkeypatch):
    """The run summary breaks skipped-as-duplicate down by dedup layer."""
    db = _TestingSession()
    try:
        exact = "Stew for MY Aurora, Antibes ASAP"
        reworded = "MY Aurora needs a stew in Antibes asap"
        monkeypatch.setattr(job_sync, "review_post", _review_stub({
            exact: _ai(title="Stewardess — Aurora"),
            reworded: _ai(title="Stewardess wanted — Aurora"),
        }))

        assert _sync(db, [_item(exact, 1)]) == (1, 0, 0)

        recorder = _RecordingLog()
        monkeypatch.setattr(job_sync, "log", recorder)
        # Same text again (content_hash) + a reworded repost (fingerprint).
        assert _sync(db, [_item(exact, 1), _item(reworded, 2)]) == (0, 2, 0)

        summary = [c for c in recorder.calls if c and "Job sync complete" in str(c[0])]
        assert len(summary) == 1
        template, *args = summary[0]
        assert "dupes: content_hash=%d fingerprint=%d url=%d title=%d" in template
        # source, created, skipped, errors, then content_hash/fingerprint/url/title, released
        assert list(args) == ["apify", 0, 2, 0, 1, 1, 0, 0, 0]
    finally:
        db.close()


# ── The other writers: manual import + guided form ───────────────────────────
# sync_jobs is not the only thing that stages jobs. The manual text import, the
# screenshot import and the guided form all fingerprint rows too, and they all
# go through job_sync.claim_fingerprint so the key and its live-window scope
# are identical everywhere.

def _form_payload(**overrides):
    payload = {
        "title": "Stewardess wanted",
        "role": "Stewardess",
        "yacht": "MY Aurora",
        "location": "Antibes",
        "start_date": "ASAP",
        "description": "Summer season, Med.",
    }
    payload.update(overrides)
    return payload


def _backdate_all(days):
    """Age every stored job out of the live fingerprint window."""
    db = _TestingSession()
    try:
        for job in db.query(Job).all():
            job.created_at = datetime.now(timezone.utc) - timedelta(days=days)
        db.commit()
    finally:
        db.close()


def test_form_submit_of_stale_triple_is_accepted(client):
    """A 20-day-old listing must not block the same vacancy being posted again."""
    first = client.post("/jobs/submit/form", json=_form_payload())
    assert first.status_code == 201, first.text

    _backdate_all(20)

    second = client.post("/jobs/submit/form", json=_form_payload(
        title="Stewardess — immediate start",
        description="Reposted three weeks later.",
    ))
    assert second.status_code == 201, second.text

    db = _TestingSession()
    try:
        jobs = db.query(Job).order_by(Job.id).all()
        assert len(jobs) == 2
        # The UNIQUE fingerprint column is handed over to the fresh posting.
        assert jobs[0].job_fingerprint is None
        assert jobs[1].job_fingerprint == _job_fingerprint(
            "Stewardess", "Antibes", "ASAP", "MY Aurora"
        )
    finally:
        db.close()


def test_form_submit_of_live_triple_is_rejected(client):
    """Inside the live window the form still 409s on a reworded repost."""
    assert client.post("/jobs/submit/form", json=_form_payload()).status_code == 201

    second = client.post("/jobs/submit/form", json=_form_payload(
        title="Stew needed now", description="Same job, different words.",
    ))
    assert second.status_code == 409

    db = _TestingSession()
    try:
        assert db.query(Job).count() == 1
    finally:
        db.close()


def test_form_submit_passes_the_employer_into_the_key(client):
    """Two boats hiring the same role in the same port are both accepted."""
    assert client.post("/jobs/submit/form", json=_form_payload()).status_code == 201

    other = client.post("/jobs/submit/form", json=_form_payload(
        yacht="MY Bella", title="Stewardess — Bella", description="Different boat.",
    ))
    assert other.status_code == 201, other.text

    db = _TestingSession()
    try:
        fps = {j.job_fingerprint for j in db.query(Job).all()}
        assert len(fps) == 2 and None not in fps
    finally:
        db.close()


def test_manual_import_of_stale_triple_is_accepted(monkeypatch):
    """The manual text import shares the scope — and the employer segment."""
    from app.routes.scraper import _run_import_pipeline

    monkeypatch.setattr("app.routes.scraper.SessionLocal", _TestingSession)
    monkeypatch.setattr(
        "app.services.ai_job_reviewer.review_post",
        lambda post_text, post_url, api_key, model, trusted_source=False: _ai(
            title=f"Stewardess ({post_text[:6]})"
        ),
    )

    first = _run_import_pipeline(text="first wording", url="https://x.test/1")
    assert not isinstance(first, dict)

    # Still live → the repost is a duplicate.
    dupe = _run_import_pipeline(text="second wording", url="https://x.test/2")
    assert isinstance(dupe, dict) and dupe["duplicate"] is True

    _backdate_all(20)

    third = _run_import_pipeline(text="third wording", url="https://x.test/3")
    assert not isinstance(third, dict), third

    db = _TestingSession()
    try:
        assert db.query(Job).count() == 2
    finally:
        db.close()
