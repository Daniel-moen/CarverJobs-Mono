import json

from app.routes import whatsapp


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def test_capture_whatsapp_posthog_event_sends_channel_metadata_without_content(monkeypatch):
    captured_requests = []

    def fake_urlopen(req, timeout):
        captured_requests.append((req, timeout))
        return _FakeResponse()

    monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setattr(whatsapp.urllib.request, "urlopen", fake_urlopen)

    whatsapp._capture_whatsapp_posthog_event(
        "27821234567",
        "inbound",
        "text",
        "secret message body",
        meta_message_id="wamid.test",
        graph_phone_number_id="12345",
    )

    assert len(captured_requests) == 1
    req, timeout = captured_requests[0]
    payload = json.loads(req.data.decode())
    props = payload["properties"]

    assert req.full_url == "https://us.i.posthog.com/i/v0/e/"
    assert timeout == 2
    assert payload["api_key"] == "phc_test"
    assert payload["event"] == "whatsapp_message_received"
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
    assert "text" not in props


def test_capture_whatsapp_posthog_event_skips_without_key(monkeypatch):
    captured_requests = []

    def fake_urlopen(req, timeout):
        captured_requests.append(req)
        return _FakeResponse()

    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_PROJECT_API_KEY", raising=False)
    monkeypatch.delenv("VITE_POSTHOG_KEY", raising=False)
    monkeypatch.setattr(whatsapp.urllib.request, "urlopen", fake_urlopen)

    whatsapp._capture_whatsapp_posthog_event("27821234567", "outbound", "text", "hello")

    assert captured_requests == []
