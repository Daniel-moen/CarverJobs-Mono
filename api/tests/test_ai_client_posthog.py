import json
import urllib.error

from app.services import ai_client


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


def test_call_openai_sends_posthog_llm_generation(monkeypatch):
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

    monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
    monkeypatch.setenv("POSTHOG_HOST", "https://us.i.posthog.com")
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)

    result = ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say hello"}],
        model="gpt-4o-mini",
        max_tokens=20,
    )

    assert result == "hello"
    assert len(captured_requests) == 2
    posthog_request = captured_requests[1][0]
    payload = json.loads(posthog_request.data.decode())
    assert posthog_request.full_url == "https://us.i.posthog.com/i/v0/e/"
    assert payload["api_key"] == "phc_test"
    assert payload["event"] == "$ai_generation"
    assert payload["properties"]["$ai_model"] == "gpt-4o-mini"
    assert payload["properties"]["$ai_provider"] == "openai"
    assert payload["properties"]["$ai_input_tokens"] == 12
    assert payload["properties"]["$ai_output_tokens"] == 3
    assert payload["properties"]["$ai_total_tokens"] == 15
    assert payload["properties"]["$ai_is_error"] is False
    assert "$ai_input" not in payload["properties"]
    assert "$ai_output_choices" not in payload["properties"]


def test_call_openai_does_not_fail_when_posthog_capture_fails(monkeypatch):
    openai_payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    def fake_urlopen(req, timeout):
        if req.full_url == ai_client._OPENAI_URL:
            return _FakeResponse(openai_payload)
        raise urllib.error.URLError("posthog down")

    monkeypatch.setenv("POSTHOG_API_KEY", "phc_test")
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)

    assert ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say ok"}],
    ) == "ok"


def test_call_openai_skips_posthog_without_api_key(monkeypatch):
    captured_requests = []
    openai_payload = {
        "choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }

    def fake_urlopen(req, timeout):
        captured_requests.append(req)
        return _FakeResponse(openai_payload)

    monkeypatch.delenv("POSTHOG_API_KEY", raising=False)
    monkeypatch.delenv("POSTHOG_PROJECT_API_KEY", raising=False)
    monkeypatch.delenv("VITE_POSTHOG_KEY", raising=False)
    monkeypatch.setattr(ai_client.urllib.request, "urlopen", fake_urlopen)

    assert ai_client.call_openai(
        api_key="sk-test",
        messages=[{"role": "user", "content": "Say ok"}],
    ) == "ok"
    assert len(captured_requests) == 1
