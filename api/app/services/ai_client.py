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
import base64
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
    messages: list[dict[str, Any]],
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
    effective_max = max(max_tokens * 4, 4096) if _gpt5 else max_tokens
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": effective_max,
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
                log.error("OpenAI unexpected shape | body=%s", json.dumps(body)[:600])
                raise AIResponseError(
                    f"OpenAI returned an unexpected response shape: {exc}",
                    crv_code="CRV-3006",
                ) from exc

            if not content or not content.strip():
                usage = body.get("usage", {})
                finish = body.get("choices", [{}])[0].get("finish_reason", "?")
                log.error(
                    "OpenAI empty content | finish_reason=%s | usage=%s | model=%s",
                    finish, json.dumps(usage), model,
                )
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


def review_job_images(
    *,
    api_key: str,
    images: list[tuple[bytes, str]],
    model: str = "gpt-4o-mini",
    system_prompt: str,
) -> str:
    """Read one or more screenshots with AI vision; return raw JSON (same schema as text reviewer)."""
    if not images:
        raise AIResponseError("No images provided.", crv_code="CRV-3006")
    for image_bytes, _mime in images:
        if not image_bytes:
            raise AIResponseError("Image bytes are empty.", crv_code="CRV-3006")

    if len(images) == 1:
        intro = (
            "Read this screenshot of a yacht crew job posting. "
            "Analyse the visible content and return the JSON result."
        )
    else:
        intro = (
            "Read these screenshots of a yacht crew job posting. "
            "They may be separate parts of the same listing — combine details across all images. "
            "Analyse the visible content and return a single JSON result."
        )

    content: list[dict[str, Any]] = [{"type": "text", "text": intro}]
    for image_bytes, mime_type in images:
        b64 = base64.b64encode(image_bytes).decode("ascii")
        data_url = f"data:{mime_type};base64,{b64}"
        content.append({"type": "image_url", "image_url": {"url": data_url}})

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": content},
    ]
    max_tokens = 1800 if len(images) > 1 else 1500
    return call_openai(
        api_key=api_key,
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=0.1,
        response_format={"type": "json_object"},
    )


def review_job_image(
    *,
    api_key: str,
    image_bytes: bytes,
    mime_type: str,
    model: str = "gpt-4o-mini",
    system_prompt: str,
) -> str:
    """Read a single screenshot (convenience wrapper around review_job_images)."""
    return review_job_images(
        api_key=api_key,
        images=[(image_bytes, mime_type)],
        model=model,
        system_prompt=system_prompt,
    )
