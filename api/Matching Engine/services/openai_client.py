import json
import urllib.error
import urllib.request

from interfaces import LLMClient


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
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI API HTTP error: {exc.code} {error_detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"OpenAI API connection error: {exc.reason}") from exc

        parsed = json.loads(raw)
        try:
            return parsed["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected OpenAI response: {raw}") from exc
