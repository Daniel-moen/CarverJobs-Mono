"""Maintenance mode: every inbound WhatsApp message gets the maintenance notice."""
from unittest.mock import AsyncMock, patch

from app.routes import whatsapp
from app.settings import settings


def _meta_payload(msg: dict) -> dict:
    return {
        "entry": [{
            "changes": [{
                "value": {
                    "metadata": {"phone_number_id": settings.WHATSAPP_PHONE_NUMBER_ID or "123"},
                    "messages": [msg],
                }
            }]
        }]
    }


def test_maintenance_mode_replies_with_notice(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_MAINTENANCE_MODE", True)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "123", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_IDS", ["123"], raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(settings, "META_APP_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "test", raising=False)

    sent: list[tuple[str, str]] = []

    async def fake_send(to: str, text: str) -> None:
        sent.append((to, text))

    with patch.object(whatsapp, "_send_whatsapp", fake_send), \
         patch.object(whatsapp, "_record_whatsapp_message", lambda *a, **k: None), \
         patch.object(whatsapp, "_process_whatsapp_message", AsyncMock()) as process_mock:
        resp = client.post(
            "/webhooks/whatsapp",
            json=_meta_payload({
                "type": "text",
                "from": "27820000001",
                "id": "wamid.maint-test-1",
                "text": {"body": "match"},
            }),
        )

    assert resp.status_code == 200
    process_mock.assert_not_called()
    assert len(sent) == 1
    assert sent[0][0] == "27820000001"
    assert "maintenance" in sent[0][1].lower()
    assert "reward" in sent[0][1].lower()


def test_maintenance_mode_off_processes_normally(client, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_MAINTENANCE_MODE", False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_ID", "123", raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_PHONE_NUMBER_IDS", ["123"], raising=False)
    monkeypatch.setattr(settings, "WHATSAPP_ACCESS_TOKEN", "test-token", raising=False)
    monkeypatch.setattr(settings, "META_APP_SECRET", "", raising=False)
    monkeypatch.setattr(settings, "APP_ENV", "test", raising=False)

    with patch.object(whatsapp, "_process_whatsapp_message", AsyncMock()) as process_mock, \
         patch.object(whatsapp, "_send_maintenance_notice", AsyncMock()) as notice_mock:
        resp = client.post(
            "/webhooks/whatsapp",
            json=_meta_payload({
                "type": "text",
                "from": "27820000002",
                "id": "wamid.maint-test-2",
                "text": {"body": "match"},
            }),
        )

    assert resp.status_code == 200
    notice_mock.assert_not_called()
    process_mock.assert_called_once()
