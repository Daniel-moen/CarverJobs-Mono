import base64
import json
import urllib.error
from urllib.parse import parse_qs

from app.services import ai_client, mixpanel_server


class _FakeResponse:
    status = 200

    def __init__(self, payload: dict | None = None) -> None:
        self._payload = payload or {"ok": True}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _mixpanel_events_from_request(req):
    qs = parse_qs(req.data.decode())
    return json.loads(base64.b64decode(qs["data"][0]))


def test_call_openai_sends_mixpanel_llm_event(monkeypatch):
    captured_requests = []
    openai_payload = {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
    }

    def fake_urlopen(req, timeout):
        captured_requests.append((req, timeout))
        if req.full_url == ai_client._OPENAI_URL:
            return _FakeResponse(openai_payload)
        return _FakeResponse()

    monkeypatch.setenv("MIXPANEL_PROJECT_TOKEN", "mp_test_token")
    monkeypatch.setenv("MIXPANEL_API_HOST", "https://api.mixpanel.com")
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mixpanel_server.urllib.request, "urlopen", fake_urlopen)

    result = ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say hello"}],
        model="gpt-4o-mini",
        max_tokens=20,
    )

    assert result == "hello"
    assert len(captured_requests) == 2
    mp_req, _timeout = captured_requests[1]
    assert str(mp_req.full_url) == "https://api.mixpanel.com/track"
    events = _mixpanel_events_from_request(mp_req)
    assert len(events) == 1
    assert events[0]["event"] == "openai_chat_completion"
    props = events[0]["properties"]
    assert props["token"] == "mp_test_token"
    assert props["distinct_id"] == "carver-api"
    assert props["model"] == "gpt-4o-mini"
    assert props["provider"] == "openai"
    assert props["input_tokens"] == 12
    assert props["output_tokens"] == 3
    assert props["total_tokens"] == 15
    assert props["is_error"] is False
    assert "input_messages" not in props
    assert "output_content" not in props


def test_call_openai_does_not_fail_when_mixpanel_capture_fails(monkeypatch):
    openai_payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    def fake_urlopen(req, timeout):
        if req.full_url == ai_client._OPENAI_URL:
            return _FakeResponse(openai_payload)
        raise urllib.error.URLError("mixpanel down")

    monkeypatch.setenv("MIXPANEL_PROJECT_TOKEN", "mp_test_token")
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(mixpanel_server.urllib.request, "urlopen", fake_urlopen)

    assert ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say ok"}],
    ) == "ok"


def test_call_openai_skips_mixpanel_without_token(monkeypatch):
    captured_requests = []
    openai_payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    def fake_urlopen(req, timeout):
        captured_requests.append(req)
        return _FakeResponse(openai_payload)

    monkeypatch.delenv("MIXPANEL_PROJECT_TOKEN", raising=False)
    monkeypatch.delenv("MIXPANEL_TOKEN", raising=False)
    monkeypatch.delenv("VITE_MIXPANEL_TOKEN", raising=False)
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)

    assert ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say ok"}],
    ) == "ok"
    assert len(captured_requests) == 1
