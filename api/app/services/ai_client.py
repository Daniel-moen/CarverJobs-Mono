"""
Unified OpenAI client — single sync wrapper used by all modules that call OpenAI.

All callers (ai_job_reviewer, crew_match draft-email) go through here so that
timeout config, retry on 429, error logging, and CRV code mapping live in one place.

Uses only stdlib (urllib, json) — no extra dependencies.
"""
import json
import time
import urllib.error
import urllib.request
from typing import Any

from app.logger import get_logger

log = get_logger("carver.ai_client")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_REQUEST_TIMEOUT = 45       # seconds per HTTP call
_MAX_RETRIES = 2            # extra attempts on 429 rate-limit
_RETRY_DELAY = 5.0          # seconds to wait before retry


# ── Typed exceptions ──────────────────────────────────────────────────────────

class AIClientError(Exception):
    """Base class for all AI client errors."""
    def __init__(self, message: str, crv_code: str | None = None) -> None:
        super().__init__(message)
        self.crv_code = crv_code


class AIKeyMissingError(AIClientError):
    """OPENAI_API_KEY is not set."""


class AITimeoutError(AIClientError):
    """Request to OpenAI timed out."""


class AIRateLimitError(AIClientError):
    """OpenAI returned HTTP 429 (quota/rate limit)."""


class AIHTTPError(AIClientError):
    """OpenAI returned a non-2xx response."""


class AINetworkError(AIClientError):
    """Network or DNS error reaching api.openai.com."""


class AIResponseError(AIClientError):
    """OpenAI returned an empty or unparseable response."""


# ── Core call ─────────────────────────────────────────────────────────────────

def call_openai(
    *,
    api_key: str,
    messages: list[dict[str, str]],
    model: str = "gpt-4o-mini",
    max_tokens: int = 1200,
    temperature: float = 0.1,
    response_format: dict[str, Any] | None = None,
) -> str:
    """
    Send a chat completion request to OpenAI and return the raw content string.

    Retries once on HTTP 429. All failures raise a typed AIClientError subclass.

    Args:
        api_key:         OpenAI API key.
        messages:        List of {"role": ..., "content": ...} dicts.
        model:           OpenAI model name.
        max_tokens:      Maximum tokens in the completion.
        temperature:     Sampling temperature (0.0–1.0).
        response_format: Optional response format dict, e.g. {"type": "json_object"}.

    Returns:
        The raw content string from choices[0].message.content.

    Raises:
        AIKeyMissingError    — api_key is empty
        AITimeoutError       — request timed out
        AIRateLimitError     — HTTP 429 after retries
        AIHTTPError          — other non-2xx HTTP response
        AINetworkError       — network / DNS failure
        AIResponseError      — response could not be parsed
    """
    if not api_key:
        raise AIKeyMissingError(
            "OPENAI_API_KEY is not set — cannot call OpenAI.",
            crv_code="CRV-3001",
        )

    _gpt5 = "gpt-5" in model
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if not _gpt5 and temperature != 1.0:
        payload["temperature"] = temperature
    if response_format is not None:
        payload["response_format"] = response_format

    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        _OPENAI_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    attempt = 0
    while True:
        attempt += 1
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                body = json.loads(resp.read().decode())

            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                raise AIResponseError(
                    f"OpenAI returned an unexpected response shape: {exc}",
                    crv_code="CRV-3006",
                ) from exc

            if not content or not content.strip():
                raise AIResponseError(
                    "OpenAI returned an empty content string.",
                    crv_code="CRV-3006",
                )

            return content

        except urllib.error.HTTPError as exc:
            snippet = exc.read().decode(errors="replace")[:300]

            if exc.code == 429:
                if attempt <= _MAX_RETRIES:
                    log.warning(
                        "OpenAI rate limit hit (429) — retrying in %.0fs | attempt=%d",
                        _RETRY_DELAY, attempt,
                    )
                    time.sleep(_RETRY_DELAY)
                    continue
                raise AIRateLimitError(
                    f"OpenAI quota/rate limit exceeded after {attempt} attempts. "
                    f"Response: {snippet}",
                    crv_code="CRV-3004",
                ) from exc

            log.error(
                "OpenAI HTTP error | status=%d | body=%s | attempt=%d",
                exc.code, snippet, attempt,
            )
            raise AIHTTPError(
                f"OpenAI returned HTTP {exc.code}: {snippet}",
                crv_code="CRV-3003",
            ) from exc

        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                log.error("OpenAI request timed out | attempt=%d", attempt)
                raise AITimeoutError(
                    f"OpenAI request timed out after {_REQUEST_TIMEOUT}s.",
                    crv_code="CRV-3002",
                ) from exc
            log.error("OpenAI network error | reason=%s | attempt=%d", exc.reason, attempt)
            raise AINetworkError(
                f"Could not reach OpenAI: {exc.reason}",
                crv_code="CRV-3005",
            ) from exc

        except json.JSONDecodeError as exc:
            raise AIResponseError(
                f"OpenAI returned non-JSON response: {exc}",
                crv_code="CRV-3006",
            ) from exc
