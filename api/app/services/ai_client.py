"""
Unified OpenAI client — single sync wrapper used by all modules that call OpenAI.

All callers (ai_job_reviewer, crew_match draft-email) go through here so that
timeout config, retry on 429, error logging, and CRV code mapping live in one place.

Uses only stdlib (urllib, json) — no extra dependencies.
"""
import json
import os
import time
import urllib.error
import urllib.request
import base64
from typing import Any
from uuid import uuid4

from app.logger import get_logger

log = get_logger("carver.ai_client")

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_REQUEST_TIMEOUT = 45       # seconds per HTTP call
_MAX_RETRIES = 2            # extra attempts on 429 rate-limit
_RETRY_DELAY = 5.0          # seconds to wait before retry
_POSTHOG_CAPTURE_TIMEOUT = 2


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


# ── PostHog LLM usage capture ─────────────────────────────────────────────────

def _posthog_config() -> tuple[str, str, bool]:
    api_key = (
        os.getenv("POSTHOG_API_KEY")
        or os.getenv("POSTHOG_PROJECT_API_KEY")
        or os.getenv("VITE_POSTHOG_KEY")
        or ""
    ).strip()
    host = (
        os.getenv("POSTHOG_HOST")
        or os.getenv("VITE_POSTHOG_HOST")
        or "https://us.i.posthog.com"
    ).strip().rstrip("/")
    capture_content = os.getenv("POSTHOG_LLM_CAPTURE_CONTENT", "false").lower() == "true"
    return api_key, host, capture_content


def _safe_messages_for_posthog(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return messages without large binary/image payloads for optional content capture."""
    safe: list[dict[str, Any]] = []
    for message in messages:
        role = message.get("role")
        content = message.get("content")
        if isinstance(content, list):
            safe_content: list[dict[str, Any]] = []
            for item in content:
                if not isinstance(item, dict):
                    safe_content.append({"type": "unknown"})
                    continue
                if item.get("type") == "image_url":
                    safe_content.append({"type": "image_url", "image_url": {"url": "[redacted]"}})
                else:
                    safe_content.append(item)
            safe.append({"role": role, "content": safe_content})
        else:
            safe.append({"role": role, "content": content})
    return safe


def _capture_llm_generation(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    response_format: dict[str, Any] | None,
    latency_seconds: float,
    attempt: int,
    body: dict[str, Any] | None = None,
    content: str | None = None,
    http_status: int | None = None,
    error: str | None = None,
) -> None:
    api_key, host, capture_content = _posthog_config()
    if not api_key:
        return

    usage = body.get("usage", {}) if body else {}
    choices = body.get("choices", []) if body else []
    first_choice = choices[0] if choices else {}
    finish_reason = first_choice.get("finish_reason")

    properties: dict[str, Any] = {
        "distinct_id": os.getenv("POSTHOG_LLM_DISTINCT_ID", "carver-api"),
        "$ai_trace_id": uuid4().hex,
        "$ai_span_id": uuid4().hex,
        "$ai_span_name": os.getenv("POSTHOG_LLM_SPAN_NAME", "openai_chat_completion"),
        "$ai_model": model,
        "$ai_provider": "openai",
        "$ai_input_tokens": usage.get("prompt_tokens"),
        "$ai_output_tokens": usage.get("completion_tokens"),
        "$ai_total_tokens": usage.get("total_tokens"),
        "$ai_latency": round(latency_seconds, 3),
        "$ai_http_status": http_status,
        "$ai_base_url": "https://api.openai.com/v1",
        "$ai_request_url": _OPENAI_URL,
        "$ai_is_error": bool(error),
        "$ai_error": error,
        "$ai_stop_reason": finish_reason,
        "$ai_temperature": temperature,
        "$ai_stream": False,
        "$ai_max_tokens": max_tokens,
        "$ai_tokens_source": "sdk",
        "attempt": attempt,
        "response_format": response_format.get("type") if response_format else None,
    }
    if capture_content:
        properties["$ai_input"] = _safe_messages_for_posthog(messages)
        if content is not None:
            properties["$ai_output_choices"] = [{"role": "assistant", "content": content}]

    payload = {
        "api_key": api_key,
        "event": "$ai_generation",
        "properties": {key: value for key, value in properties.items() if value is not None},
    }
    req = urllib.request.Request(
        f"{host}/i/v0/e/",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_POSTHOG_CAPTURE_TIMEOUT):
            pass
    except Exception as exc:
        log.debug("PostHog LLM capture failed | error=%s", exc)


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
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT) as resp:
                http_status = getattr(resp, "status", 200)
                body = json.loads(resp.read().decode())

            try:
                content = body["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError) as exc:
                log.error("OpenAI unexpected shape | body=%s", json.dumps(body)[:600])
                _capture_llm_generation(
                    model=model,
                    messages=messages,
                    max_tokens=effective_max,
                    temperature=temperature,
                    response_format=response_format,
                    latency_seconds=time.perf_counter() - started,
                    attempt=attempt,
                    body=body,
                    http_status=http_status,
                    error=f"OpenAI returned an unexpected response shape: {exc}",
                )
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
                _capture_llm_generation(
                    model=model,
                    messages=messages,
                    max_tokens=effective_max,
                    temperature=temperature,
                    response_format=response_format,
                    latency_seconds=time.perf_counter() - started,
                    attempt=attempt,
                    body=body,
                    http_status=http_status,
                    error="OpenAI returned an empty content string.",
                )
                raise AIResponseError(
                    "OpenAI returned an empty content string.",
                    crv_code="CRV-3006",
                )
            _capture_llm_generation(
                model=model,
                messages=messages,
                max_tokens=effective_max,
                temperature=temperature,
                response_format=response_format,
                latency_seconds=time.perf_counter() - started,
                attempt=attempt,
                body=body,
                content=content,
                http_status=http_status,
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
                _capture_llm_generation(
                    model=model,
                    messages=messages,
                    max_tokens=effective_max,
                    temperature=temperature,
                    response_format=response_format,
                    latency_seconds=time.perf_counter() - started,
                    attempt=attempt,
                    http_status=exc.code,
                    error=f"OpenAI quota/rate limit exceeded after {attempt} attempts. Response: {snippet}",
                )
                raise AIRateLimitError(
                    f"OpenAI quota/rate limit exceeded after {attempt} attempts. "
                    f"Response: {snippet}",
                    crv_code="CRV-3004",
                ) from exc

            log.error(
                "OpenAI HTTP error | status=%d | body=%s | attempt=%d",
                exc.code, snippet, attempt,
            )
            _capture_llm_generation(
                model=model,
                messages=messages,
                max_tokens=effective_max,
                temperature=temperature,
                response_format=response_format,
                latency_seconds=time.perf_counter() - started,
                attempt=attempt,
                http_status=exc.code,
                error=f"OpenAI returned HTTP {exc.code}: {snippet}",
            )
            raise AIHTTPError(
                f"OpenAI returned HTTP {exc.code}: {snippet}",
                crv_code="CRV-3003",
            ) from exc

        except urllib.error.URLError as exc:
            if "timed out" in str(exc.reason).lower():
                log.error("OpenAI request timed out | attempt=%d", attempt)
                _capture_llm_generation(
                    model=model,
                    messages=messages,
                    max_tokens=effective_max,
                    temperature=temperature,
                    response_format=response_format,
                    latency_seconds=time.perf_counter() - started,
                    attempt=attempt,
                    error=f"OpenAI request timed out after {_REQUEST_TIMEOUT}s.",
                )
                raise AITimeoutError(
                    f"OpenAI request timed out after {_REQUEST_TIMEOUT}s.",
                    crv_code="CRV-3002",
                ) from exc
            log.error("OpenAI network error | reason=%s | attempt=%d", exc.reason, attempt)
            _capture_llm_generation(
                model=model,
                messages=messages,
                max_tokens=effective_max,
                temperature=temperature,
                response_format=response_format,
                latency_seconds=time.perf_counter() - started,
                attempt=attempt,
                error=f"Could not reach OpenAI: {exc.reason}",
            )
            raise AINetworkError(
                f"Could not reach OpenAI: {exc.reason}",
                crv_code="CRV-3005",
            ) from exc

        except json.JSONDecodeError as exc:
            _capture_llm_generation(
                model=model,
                messages=messages,
                max_tokens=effective_max,
                temperature=temperature,
                response_format=response_format,
                latency_seconds=time.perf_counter() - started,
                attempt=attempt,
                http_status=200,
                error=f"OpenAI returned non-JSON response: {exc}",
            )
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
