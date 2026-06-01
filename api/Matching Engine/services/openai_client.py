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
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-5.4-mini",
        base_url: str = "https://api.openai.com/v1",
        temperature: float | None = None,
        max_tokens: int | None = 2048,
        seed: int | None = 7,
    ) -> None:
        normalized_api_key = "".join(ch for ch in api_key.strip() if ch.isprintable() and not ch.isspace())
        if not normalized_api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = normalized_api_key
        self._model = model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._seed = seed
        base = base_url.rstrip("/")
        self._url = base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def generate(self, user_prompt: str, system_prompt: str | None = None) -> str:
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": user_prompt})
        body: dict = {
            "model": self._model,
            "messages": messages,
            "response_format": {"type": "json_object"},
        }
        # GPT-5 family rejects non-default temperature; only send it when configured.
        if self._temperature is not None:
            body["temperature"] = self._temperature
        if self._max_tokens is not None:
            body["max_completion_tokens"] = self._max_tokens
        if self._seed is not None:
            body["seed"] = self._seed
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
