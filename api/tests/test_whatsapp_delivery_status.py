"""Meta `statuses` callbacks: delivery receipts for outbound WhatsApp sends.

Before this the webhook dropped every status on the floor, so a paid template
blast left no evidence of whether it was delivered, read, or refused.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.models import WhatsAppMessage
from app.routes import whatsapp
from app.settings import settings

from tests.conftest import _TestingSession


@pytest.fixture(autouse=True)
def _wa_test_db(monkeypatch):
    """Status processing owns its own session — point it at the test DB."""
    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    whatsapp._SEEN_MSG_IDS.clear()
    whatsapp._SEEN_MSG_IDS_ORDER.clear()


@pytest.fixture(autouse=True)
def _wa_configured(monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "123", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_IDS", ["123"], raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(settings, "META_APP_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "test", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_MAINTENANCE_MODE", False, raising=False)


@pytest.fixture()
def events(monkeypatch):
    """Capture server-side funnel events instead of writing the real DB."""
    captured: list[tuple[str, str, str | None]] = []
    monkeypatch.setattr(
        whatsapp, "record_server_event",
        lambda key, name, value=None: captured.append((key, name, value)),
    )
    return captured


def _seed(
    meta_id: str,
    *,
    direction: str = "outbound",
    message_type: str = "template",
    phone: str = "27820001234",
    payload_json: str | None = None,
    created_at: datetime | None = None,
) -> None:
    db = _TestingSession()
    try:
        db.add(WhatsAppMessage(
            phone_number=phone,
            direction=direction,
            message_type=message_type,
            content="Hi there — 3 new jobs landed.",
            meta_message_id=meta_id,
            graph_phone_number_id="123",
            payload_json=payload_json,
            created_at=created_at or datetime.now(timezone.utc),
        ))
        db.commit()
    finally:
        db.close()


def _row(meta_id: str) -> WhatsAppMessage:
    db = _TestingSession()
    try:
        return db.query(WhatsAppMessage).filter(
            WhatsAppMessage.meta_message_id == meta_id
        ).one()
    finally:
        db.close()


def _status_payload(*items: dict) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "123"},
                    "statuses": list(items),
                }
            }]
        }]
    }


def _status(meta_id: str, state: str, **extra) -> dict:
    item = {
        "id": meta_id,
        "status": state,
        "timestamp": "1758499200",  # 2025-09-22T00:00:00Z
        "recipient_id": "27820001234",
    }
    item.update(extra)
    return item


def test_status_only_payload_returns_200_without_message_pipeline(client, events):
    """A statuses-only callback must not touch the message pipeline."""
    _seed("wamid.status-only")

    with patch.object(whatsapp, "_process_whatsapp_message", AsyncMock()) as process_mock:
        resp = client.post("/webhooks/whatsapp", json=_status_payload(
            _status("wamid.status-only", "delivered"),
        ))

    assert resp.status_code == 200
    process_mock.assert_not_called()
    assert _row("wamid.status-only").status == "delivered"


def test_status_moves_forward_only(client, events):
    """sent → delivered → read climbs; a replayed earlier rung is ignored."""
    _seed("wamid.ladder")

    for state in ("sent", "delivered", "read"):
        assert client.post("/webhooks/whatsapp", json=_status_payload(
            _status("wamid.ladder", state),
        )).status_code == 200
    assert _row("wamid.ladder").status == "read"

    # Meta retries re-deliver earlier rungs out of order — they must not
    # walk the row backwards or re-fire the funnel event.
    client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.ladder", "delivered"),
    ))
    row = _row("wamid.ladder")
    assert row.status == "read"
    assert row.status_at is not None

    names = [name for _key, name, _value in events]
    assert names == ["wa_message_delivered", "wa_message_read"]


def test_failed_status_records_error_and_emits_event(client, events):
    _seed("wamid.failed")

    # The app logs through structlog, whose records keep the format string and
    # args apart — render them here to assert on the line an operator reads.
    with patch.object(whatsapp.log, "warning") as warn:
        resp = client.post("/webhooks/whatsapp", json=_status_payload(
            _status("wamid.failed", "failed", errors=[{
                "code": 131049,
                "title": "Message not delivered",
                "error_data": {"details": "healthy ecosystem engagement limit"},
            }]),
        ))

    assert resp.status_code == 200
    row = _row("wamid.failed")
    assert row.status == "failed"
    assert row.status_error == (
        "131049: Message not delivered — healthy ecosystem engagement limit"
    )
    assert ("27820001234", "wa_message_failed", "131049") in events

    logged = "\n".join(
        str(call.args[0]) % tuple(call.args[1:]) for call in warn.call_args_list
    )
    assert "****1234" in logged            # phone masked to last 4
    assert "27820001234" not in logged
    assert "type=template" in logged
    assert "code=131049" in logged
    assert "cannot receive marketing templates" in logged


def test_failed_overwrites_a_delivered_row(client, events):
    _seed("wamid.late-fail")
    client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.late-fail", "delivered"),
    ))
    client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.late-fail", "failed", errors=[{"code": 470, "title": "Re-engagement"}]),
    ))

    row = _row("wamid.late-fail")
    assert row.status == "failed"
    assert row.status_error == "470: Re-engagement"


def test_unknown_message_id_is_a_noop(client, events):
    resp = client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.never-sent", "delivered"),
    ))

    assert resp.status_code == 200
    assert events == []
    db = _TestingSession()
    try:
        assert db.query(WhatsAppMessage).count() == 0
    finally:
        db.close()


def test_conversational_reply_updates_status_without_an_event(client, events):
    """Receipts for ordinary bot replies are recorded but not counted."""
    _seed("wamid.reply", message_type="text", payload_json='{"status_code": 200}')

    client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.reply", "read"),
    ))

    assert _row("wamid.reply").status == "read"
    assert events == []


def test_proactive_loop_payload_source_does_emit(client, events):
    _seed("wamid.winback", message_type="text", payload_json='{"source": "window_winback"}')

    client.post("/webhooks/whatsapp", json=_status_payload(
        _status("wamid.winback", "delivered"),
    ))

    assert [name for _k, name, _v in events] == ["wa_message_delivered"]


def test_mixed_payload_processes_messages_and_statuses(client, events):
    _seed("wamid.mixed-out")

    payload = {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": "123"},
                    "statuses": [_status("wamid.mixed-out", "delivered")],
                    "messages": [{
                        "type": "text",
                        "from": "27820009999",
                        "id": "wamid.mixed-in",
                        "text": {"body": "match"},
                    }],
                }
            }]
        }]
    }

    with patch.object(whatsapp, "_process_whatsapp_message", AsyncMock()) as process_mock:
        resp = client.post("/webhooks/whatsapp", json=payload)

    assert resp.status_code == 200
    process_mock.assert_called_once()
    assert _row("wamid.mixed-out").status == "delivered"


def test_malformed_status_does_not_block_the_rest(client, events):
    _seed("wamid.survivor")

    resp = client.post("/webhooks/whatsapp", json=_status_payload(
        {"status": "delivered"},               # no id
        {"id": "wamid.survivor"},              # no status
        _status("wamid.survivor", "delivered"),
    ))

    assert resp.status_code == 200
    assert _row("wamid.survivor").status == "delivered"


def test_outbound_status_summary_counts_templates_only(client):
    now = datetime.now(timezone.utc)
    _seed("wamid.sum-1")
    _seed("wamid.sum-2")
    _seed("wamid.sum-3")
    _seed("wamid.sum-old", created_at=now - timedelta(days=9))
    _seed("wamid.sum-reply", message_type="text")

    for meta_id, state in (("wamid.sum-1", "read"), ("wamid.sum-2", "delivered")):
        client.post("/webhooks/whatsapp", json=_status_payload(_status(meta_id, state)))

    db = _TestingSession()
    try:
        summary = whatsapp.outbound_status_summary(db, now - timedelta(days=1))
    finally:
        db.close()

    assert summary["read"] == 1
    assert summary["delivered"] == 1
    assert summary["pending"] == 1      # wamid.sum-3, no receipt yet
    assert summary["failed"] == 0
    assert summary["total"] == 3        # the 9-day-old send and the reply are excluded
