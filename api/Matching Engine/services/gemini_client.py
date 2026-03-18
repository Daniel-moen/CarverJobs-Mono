import json
import urllib.error
import urllib.request

from interfaces import LLMClient


class GeminiClient(LLMClient):
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash") -> None:
        normalized_api_key = "".join(ch for ch in api_key.strip() if ch.isprintable() and not ch.isspace())
        if not normalized_api_key:
            raise ValueError("Gemini API key is required")
        self._api_key = normalized_api_key
        self._url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
            f"?key={self._api_key}"
        )

    def generate(self, prompt: str) -> str:
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"response_mime_type": "application/json"},
        }
        request = urllib.request.Request(
            self._url,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            error_detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"Gemini API HTTP error: {exc.code} {error_detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API connection error: {exc.reason}") from exc

        parsed = json.loads(raw)
        try:
            return parsed["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Unexpected Gemini response: {raw}") from exc

