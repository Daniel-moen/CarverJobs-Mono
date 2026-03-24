import json
import logging
import time
import urllib.error
import urllib.request

from interfaces import LLMClient

log = logging.getLogger("carver.matching_engine.openai")

_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.5


class OpenAIClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini") -> None:
        normalized_api_key = "".join(ch for ch in api_key.strip() if ch.isprintable() and not ch.isspace())
        if not normalized_api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = normalized_api_key
        self._model = model
        self._url = "https://api.openai.com/v1/chat/completions"

    def generate(self, prompt: str) -> str:
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        data = json.dumps(body).encode("utf-8")

        last_error: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            request = urllib.request.Request(
                self._url,
                data=data,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self._api_key}",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    raw = response.read().decode("utf-8")
                parsed = json.loads(raw)
                return parsed["choices"][0]["message"]["content"]
            except urllib.error.HTTPError as exc:
                last_error = exc
                error_detail = exc.read().decode("utf-8", errors="ignore")
                if exc.code in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    log.warning("OpenAI %d (attempt %d/%d), retrying in %.1fs", exc.code, attempt + 1, _MAX_RETRIES, delay)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"OpenAI API HTTP error: {exc.code} {error_detail}") from exc
            except urllib.error.URLError as exc:
                last_error = exc
                if attempt < _MAX_RETRIES - 1:
                    delay = _BASE_DELAY * (2 ** attempt)
                    log.warning("OpenAI connection error (attempt %d/%d), retrying in %.1fs: %s", attempt + 1, _MAX_RETRIES, delay, exc.reason)
                    time.sleep(delay)
                    continue
                raise RuntimeError(f"OpenAI API connection error: {exc.reason}") from exc
            except (KeyError, IndexError, TypeError) as exc:
                raise RuntimeError(f"Unexpected OpenAI response structure") from exc

        raise RuntimeError(f"OpenAI API failed after {_MAX_RETRIES} attempts") from last_error
