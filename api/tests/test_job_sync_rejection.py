"""Unit tests for the rejected-post cache, cheap pre-filter, and image-review
path in job_sync."""
import hashlib

import app.services.job_sync as job_sync
from app.models import Job, RejectedPost
from app.services.job_sync import _content_hash, sync_jobs
from tests.conftest import _TestingSession

_JOB_JSON = (
    '{"is_job": true, "title": "Stewardess", "role": "Stewardess", '
    '"location": "Antibes", "start_date": "ASAP"}'
)


def _image_item(url, fbid="123"):
    """Raw Apify item shaped like a real image-only Facebook post (no text)."""
    return {
        "url": url,
        "attachments": [
            {
                "__typename": "Photo",
                "thumbnail": f"https://scontent.xx.fbcdn.net/thumb_{fbid}.jpg",
                "photo_image": {"uri": f"https://scontent.xx.fbcdn.net/full_{fbid}.jpg"},
            }
        ],
    }


def _review_stub(calls, return_value=None):
    """Stand-in for review_post that records each call and returns a fixed value."""
    def _stub(post_text, post_url, api_key, model, trusted_source=False):
        calls.append(post_text)
        return return_value
    return _stub


def test_rejected_hash_short_circuits_before_ai(monkeypatch):
    """A cached rejection skips the item without ever calling the AI reviewer."""
    db = _TestingSession()
    try:
        text = "This is a spammy non-job post about nothing in particular"
        db.add(RejectedPost(content_hash=_content_hash(text), reason="not_a_job"))
        db.commit()

        calls: list[str] = []
        monkeypatch.setattr(job_sync, "review_post", _review_stub(calls))

        created, skipped, errors = sync_jobs(
            db,
            [{"text": text, "url": "https://facebook.com/groups/x/1"}],
            openai_api_key="k",
            openai_model="m",
            source="apify",
        )

        assert calls == []            # AI never called
        assert (created, skipped, errors) == (0, 1, 0)
    finally:
        db.close()


def test_rejection_recorded_when_review_returns_none(monkeypatch):
    """When review_post returns None, the hash is cached as a rejection."""
    db = _TestingSession()
    try:
        text = "Just some general chatter in the group, not a hiring post"
        calls: list[str] = []
        monkeypatch.setattr(job_sync, "review_post", _review_stub(calls, return_value=None))

        created, skipped, errors = sync_jobs(
            db,
            [{"text": text, "url": "https://facebook.com/groups/x/2"}],
            openai_api_key="k",
            openai_model="m",
            source="apify",
        )

        assert calls == [text]        # AI consulted exactly once
        assert (created, skipped, errors) == (0, 1, 0)
        row = (
            db.query(RejectedPost)
            .filter(RejectedPost.content_hash == _content_hash(text))
            .one()
        )
        assert row.reason == "not_a_job"
    finally:
        db.close()


def test_error_and_empty_records_are_filtered(monkeypatch):
    """Dead-group error records and empty items are skipped before any AI call."""
    db = _TestingSession()
    try:
        calls: list[str] = []
        monkeypatch.setattr(job_sync, "review_post", _review_stub(calls))

        items = [
            {
                "error": "no_items",
                "errorDescription": "group is dead",
                "url": "https://facebook.com/groups/dead",
            },
            {"text": "   "},   # whitespace only, no media
        ]
        created, skipped, errors = sync_jobs(
            db, items, openai_api_key="k", openai_model="m", source="apify",
        )

        assert calls == []            # neither item reached the AI reviewer
        assert (created, skipped, errors) == (0, 2, 0)
    finally:
        db.close()


def test_image_only_post_routes_to_vision_not_text_reviewer(monkeypatch):
    """A post with media but no text is routed to the vision reviewer, never
    the text reviewer, and is not dropped by the empty-record pre-filter."""
    db = _TestingSession()
    try:
        text_calls: list[str] = []
        monkeypatch.setattr(job_sync, "review_post", _review_stub(text_calls))
        # Vision path: fake download + a non-job verdict so nothing is inserted.
        monkeypatch.setattr(job_sync, "_download_image", lambda url: (b"\xff\xd8\xffJPEGBYTES", "image/jpeg"))
        monkeypatch.setattr(
            job_sync, "review_job_image",
            lambda **kw: '{"is_job": false}',
        )

        items = [_image_item("https://facebook.com/groups/x/3")]
        created, skipped, errors = sync_jobs(
            db, items, openai_api_key="k", openai_model="m", source="apify",
        )

        assert text_calls == []                    # text reviewer never called
        assert (created, skipped, errors) == (0, 1, 0)
    finally:
        db.close()


def test_image_job_creates_row_with_byte_hash(monkeypatch):
    """An image post the vision reviewer accepts becomes a Job whose
    content_hash is the SHA-256 of the downloaded image bytes."""
    db = _TestingSession()
    try:
        img_bytes = b"\xff\xd8\xff" + b"REALIMAGEBYTES"
        monkeypatch.setattr(job_sync, "_download_image", lambda url: (img_bytes, "image/jpeg"))
        monkeypatch.setattr(job_sync, "review_job_image", lambda **kw: _JOB_JSON)

        created, skipped, errors = sync_jobs(
            db, [_image_item("https://facebook.com/groups/x/10")],
            openai_api_key="k", openai_model="m", source="apify",
        )

        assert (created, skipped, errors) == (1, 0, 0)
        job = db.query(Job).one()
        assert job.content_hash == hashlib.sha256(img_bytes).hexdigest()
        assert job.role == "Stewardess"
    finally:
        db.close()


def test_image_rejection_recorded_with_image_reason(monkeypatch):
    """A non-job image is cached in rejected_posts under the byte hash with the
    image-specific reason so it isn't re-sent to OpenAI next run."""
    db = _TestingSession()
    try:
        img_bytes = b"\x89PNG\r\n\x1a\n" + b"NOTAJOB"
        monkeypatch.setattr(job_sync, "_download_image", lambda url: (img_bytes, "image/png"))
        monkeypatch.setattr(job_sync, "review_job_image", lambda **kw: '{"is_job": false}')

        created, skipped, errors = sync_jobs(
            db, [_image_item("https://facebook.com/groups/x/11")],
            openai_api_key="k", openai_model="m", source="apify",
        )

        assert (created, skipped, errors) == (0, 1, 0)
        row = (
            db.query(RejectedPost)
            .filter(RejectedPost.content_hash == hashlib.sha256(img_bytes).hexdigest())
            .one()
        )
        assert row.reason == "not_a_job_image"
    finally:
        db.close()


def test_rejected_image_hash_short_circuits_before_vision(monkeypatch):
    """A cached image rejection skips the item without calling the vision AI."""
    db = _TestingSession()
    try:
        img_bytes = b"\xff\xd8\xff" + b"SEENBEFORE"
        db.add(RejectedPost(content_hash=hashlib.sha256(img_bytes).hexdigest(), reason="not_a_job_image"))
        db.commit()

        monkeypatch.setattr(job_sync, "_download_image", lambda url: (img_bytes, "image/jpeg"))
        vision_calls = {"n": 0}

        def _vision(**kw):
            vision_calls["n"] += 1
            return _JOB_JSON

        monkeypatch.setattr(job_sync, "review_job_image", _vision)

        created, skipped, errors = sync_jobs(
            db, [_image_item("https://facebook.com/groups/x/12")],
            openai_api_key="k", openai_model="m", source="apify",
        )

        assert vision_calls["n"] == 0              # AI never called
        assert (created, skipped, errors) == (0, 1, 0)
    finally:
        db.close()


def test_image_review_cap_respected(monkeypatch):
    """No more than _MAX_IMAGE_REVIEWS_PER_RUN vision calls happen per run."""
    db = _TestingSession()
    try:
        cap = job_sync._MAX_IMAGE_REVIEWS_PER_RUN
        # Unique bytes per url so dedup never collapses items before the cap.
        monkeypatch.setattr(
            job_sync, "_download_image",
            lambda url: (b"\xff\xd8\xff" + url.encode(), "image/jpeg"),
        )
        vision_calls = {"n": 0}

        def _vision(**kw):
            vision_calls["n"] += 1
            return '{"is_job": false}'

        monkeypatch.setattr(job_sync, "review_job_image", _vision)

        items = [_image_item(f"https://facebook.com/groups/x/{i}", fbid=str(i)) for i in range(cap + 5)]
        created, skipped, errors = sync_jobs(
            db, items, openai_api_key="k", openai_model="m", source="apify",
        )

        assert vision_calls["n"] == cap            # capped
        assert created == 0
        assert skipped == cap + 5                  # every item skipped (rejected or capped)
        assert errors == 0
    finally:
        db.close()


def test_image_download_failure_skipped_gracefully(monkeypatch):
    """An oversize / unsupported / failed download is skipped, never an error,
    and never reaches the vision AI."""
    db = _TestingSession()
    try:
        monkeypatch.setattr(job_sync, "_download_image", lambda url: None)
        vision_calls = {"n": 0}
        monkeypatch.setattr(
            job_sync, "review_job_image",
            lambda **kw: vision_calls.__setitem__("n", vision_calls["n"] + 1) or _JOB_JSON,
        )

        created, skipped, errors = sync_jobs(
            db, [_image_item("https://facebook.com/groups/x/13")],
            openai_api_key="k", openai_model="m", source="apify",
        )

        assert vision_calls["n"] == 0
        assert (created, skipped, errors) == (0, 1, 0)
    finally:
        db.close()
