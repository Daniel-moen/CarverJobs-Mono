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


def test_capture_whatsapp_mixpanel_event_sends_outbound_metadata(monkeypatch):
    captured_requests = []

    def fake_urlopen(req, timeout):
        captured_requests.append((req, timeout))
        return _FakeResponse()

    monkeypatch.setenv("MIXPANEL_PROJECT_TOKEN", "mp_test")
    monkeypatch.setattr(mixpanel_server.urllib.request, "urlopen", fake_urlopen)

    whatsapp._capture_whatsapp_mixpanel_event(
        "27821234567",
        "outbound",
        "interactive_button",
        "reply body",
        meta_message_id="wamid.out",
        graph_phone_number_id="12345",
        payload={"status_code": 200, "buttons": [{"id": "btn_menu"}]},
    )

    events = _mixpanel_events_from_request(captured_requests[0][0])
    props = events[0]["properties"]

    assert events[0]["event"] == "whatsapp_message_sent"
    assert props["direction"] == "outbound"
    assert props["message_type"] == "interactive_button"
    assert props["message_length"] == len("reply body")
    assert props["meta_message_id"] == "wamid.out"
    assert props["graph_phone_number_id"] == "12345"
    assert props["status_code"] == 200
    assert props["success"] is True
    assert props["button_count"] == 1
    assert "reply body" not in json.dumps(props)


def test_record_unsupported_inbound_whatsapp_message_tracks_mixpanel_without_content(monkeypatch):
    captured = []

    def fake_track(**kwargs):
        captured.append(kwargs)

    monkeypatch.setattr(whatsapp, "mixpanel_track", fake_track)

    class FakeSession:
        def add(self, obj):
            pass

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(whatsapp, "SessionLocal", lambda: FakeSession())

    whatsapp._record_unsupported_inbound_whatsapp_message(
        "27821234567",
        "location",
        "12345",
        "wamid.location",
        reason="unsupported_message_type",
    )

    assert len(captured) == 1
    event = captured[0]
    assert event["event"] == "whatsapp_message_received"
    assert event["distinct_id"].startswith("whatsapp:")
    assert event["properties"]["direction"] == "inbound"
    assert event["properties"]["message_type"] == "location"
    assert event["properties"]["message_length"] == 0
    assert event["properties"]["meta_message_id"] == "wamid.location"
    assert event["properties"]["graph_phone_number_id"] == "12345"
