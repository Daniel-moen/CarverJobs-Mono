import base64
import json
from urllib.parse import parse_qs

from app.routes import whatsapp
from app.services import mixpanel_server


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _mixpanel_events_from_request(req):
    qs = parse_qs(req.data.decode())
    return json.loads(base64.b64decode(qs["data"][0]))


def test_capture_whatsapp_mixpanel_event_sends_channel_metadata_without_content(monkeypatch):
    captured_requests = []

    def fake_urlopen(req, timeout):
        captured_requests.append((req, timeout))
        return _FakeResponse()

    monkeypatch.setenv("MIXPANEL_PROJECT_TOKEN", "mp_test")
    monkeypatch.setenv("MIXPANEL_API_HOST", "https://api.mixpanel.com")
    monkeypatch.setattr(mixpanel_server.urllib.request, "urlopen", fake_urlopen)

    whatsapp._capture_whatsapp_mixpanel_event(
        "27821234567",
        "inbound",
        "text",
        "secret message body",
        meta_message_id="wamid.test",
        graph_phone_number_id="12345",
    )

    assert len(captured_requests) == 1
    req, timeout = captured_requests[0]
    events = _mixpanel_events_from_request(req)
    props = events[0]["properties"]

    assert str(req.full_url) == "https://api.mixpanel.com/track"
    assert timeout == 2
    assert events[0]["event"] == "whatsapp_message_received"
    assert props["token"] == "mp_test"
    assert props["channel"] == "whatsapp"
    assert props["source"] == "whatsapp"
    assert props["direction"] == "inbound"
    assert props["message_type"] == "text"
    assert props["message_length"] == len("secret message body")
    assert props["meta_message_id"] == "wamid.test"
    assert props["graph_phone_number_id"] == "12345"
    assert props["distinct_id"].startswith("whatsapp:")
    assert "27821234567" not in props["distinct_id"]
    assert "content" not in props
    assert "body" not in props


def test_capture_whatsapp_mixpanel_event_skips_without_token(monkeypatch):
    captured_requests = []

    def fake_urlopen(req, timeout):
        captured_requests.append(req)
        return _FakeResponse()

    monkeypatch.delenv("MIXPANEL_PROJECT_TOKEN", raising=False)
    monkeypatch.delenv("MIXPANEL_TOKEN", raising=False)
    monkeypatch.delenv("VITE_MIXPANEL_TOKEN", raising=False)
    monkeypatch.setattr(mixpanel_server.urllib.request, "urlopen", fake_urlopen)

    whatsapp._capture_whatsapp_mixpanel_event("27821234567", "outbound", "text", "hello")

    assert captured_requests == []
