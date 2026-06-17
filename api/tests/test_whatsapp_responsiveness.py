"""Responsiveness tests for the WhatsApp hot path.

Focus: the user gets an *instant* acknowledgement before slow download / AI
extraction work runs, for both image and job-text submissions. Also covers the
type-specific ack copy and the pooled/keep-alive HTTP client config.
"""
import asyncio

import httpx

from app.routes import whatsapp


class _FakeDB:
    def commit(self):
        pass

    def close(self):
        pass


class _FakeSession:
    def __init__(self, mode="job_submit"):
        self.mode = mode


def _patch_common(monkeypatch, calls):
    """Wire up the shared collaborators so we can observe call ordering."""
    monkeypatch.setattr(whatsapp, "SessionLocal", lambda: _FakeDB())
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "_get_or_create_session", lambda phone, db: _FakeSession())
    monkeypatch.setattr(whatsapp.settings, "OPENAI_API_KEY", "test-key")

    async def fake_send(to, text):
        calls.append(("send", text))

    async def fake_buttons(to, body, buttons):
        calls.append(("buttons", body))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)


def test_image_submission_acks_before_slow_work(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls)

    async def fake_image_submit(phone, media_id, db):
        calls.append(("process_image", media_id))

    monkeypatch.setattr(whatsapp, "_process_job_image_submission", fake_image_submit)

    asyncio.run(
        whatsapp._process_media_message(
            "27821234567", "media-123", graph_phone_number_id="12345", inbound_message_type="image"
        )
    )

    labels = [c[0] for c in calls]
    # The instant ack must be sent before the slow download/AI parse runs.
    assert "send" in labels and "process_image" in labels
    assert labels.index("send") < labels.index("process_image")

    ack_text = next(text for label, text in calls if label == "send")
    assert "📸" in ack_text  # image-specific copy


def test_job_text_submission_acks_before_slow_work(monkeypatch):
    calls = []
    _patch_common(monkeypatch, calls)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (False, None))

    async def fake_text_submit(phone, text, db):
        calls.append(("process_text", text))

    monkeypatch.setattr(whatsapp, "_process_job_text_submission", fake_text_submit)

    asyncio.run(
        whatsapp._process_whatsapp_message(
            "27821234567", "Captain wanted on 50m motor yacht", graph_phone_number_id="12345"
        )
    )

    labels = [c[0] for c in calls]
    assert "send" in labels and "process_text" in labels
    assert labels.index("send") < labels.index("process_text")

    ack_text = next(text for label, text in calls if label == "send")
    assert "📝" in ack_text  # text-specific copy


def test_job_review_wait_is_type_specific(monkeypatch):
    sent = []

    async def fake_send(to, text):
        sent.append(text)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)

    asyncio.run(whatsapp._send_job_review_wait("27821234567", "image"))
    asyncio.run(whatsapp._send_job_review_wait("27821234567", "text"))
    asyncio.run(whatsapp._send_job_review_wait("27821234567"))  # default

    assert "📸" in sent[0]
    assert "📝" in sent[1]
    assert sent[2] == sent[1]  # default falls back to the text ack


def test_no_duplicate_ack_in_image_flow(monkeypatch):
    """Exactly one ack should precede processing — no double-send."""
    calls = []
    _patch_common(monkeypatch, calls)

    async def fake_image_submit(phone, media_id, db):
        calls.append(("process_image", media_id))

    monkeypatch.setattr(whatsapp, "_process_job_image_submission", fake_image_submit)

    asyncio.run(
        whatsapp._process_media_message(
            "27821234567", "media-123", graph_phone_number_id="12345", inbound_message_type="image"
        )
    )

    process_idx = [c[0] for c in calls].index("process_image")
    acks_before = [c for c in calls[:process_idx] if c[0] == "send"]
    assert len(acks_before) == 1


def test_http_client_uses_pooling_and_split_timeouts():
    # Keep-alive connection pooling for outbound Meta Graph API calls.
    limits = whatsapp._HTTP_LIMITS
    assert limits.max_keepalive_connections and limits.max_keepalive_connections > 0
    assert limits.max_connections and limits.max_connections >= limits.max_keepalive_connections
    assert limits.keepalive_expiry and limits.keepalive_expiry > 0

    # Short connect timeout, longer read/write — no longer than the old flat 20s.
    timeout = whatsapp._HTTP_TIMEOUT
    assert timeout.connect == 5.0
    assert timeout.read == 20.0
    assert timeout.write == 20.0

    assert isinstance(whatsapp._http, httpx.AsyncClient)
