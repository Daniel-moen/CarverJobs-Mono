"""Tests for Telnyx webhook signature enforcement."""

from app.settings import settings


def test_telnyx_webhook_rejects_unsigned_request_without_public_key(client, monkeypatch):
    monkeypatch.setattr(settings, "TELNYX_PUBLIC_KEY", "")

    resp = client.post(
        "/telnyx/webhook",
        json={
            "data": {
                "event_type": "message.received",
                "payload": {
                    "id": "msg-1",
                    "from": {"phone_number": "+15550000001"},
                    "to": [{"phone_number": "+15550000002"}],
                    "text": "123456",
                },
            }
        },
    )

    assert resp.status_code == 403
