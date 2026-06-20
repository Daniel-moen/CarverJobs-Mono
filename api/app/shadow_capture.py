"""Shadow-traffic capture middleware.

Records real requests (and Python's response status) to a newline-delimited JSON
corpus so the Go port in ``jobcarver-go`` can be *replayed* against the same
traffic and structurally diffed before we cut over. See ``jobcarver-go/SHADOW.md``.

Design notes
------------
* **Off by default.** ``install_shadow_capture`` only wires the middleware when
  ``SHADOW_CAPTURE_ENABLED`` is true, so production carries zero overhead unless
  explicitly switched on.
* **Pure-ASGI**, not ``BaseHTTPMiddleware``: that's the only reliable way to
  buffer the request body without consuming the stream the downstream handler
  needs. We tee ``receive`` (request body) and ``send`` (response start/body).
* **Never breaks the response.** All capture work is wrapped in try/except and
  the record is written *after* the response has been sent to the client, on a
  worker thread, so a slow disk can't add latency to the request path.
* **Principal, not cookie.** Python sessions are ``itsdangerous``-signed and the
  Go port uses a different token format, so a raw cookie would never validate on
  Go. We instead resolve and store the *principal* (sub/role/user_id) that Python
  authenticated; the replay tool mints an equivalent native Go session from it.
* **Secret-aware.** Cookie/Authorization headers are dropped and configured JSON
  body fields (passwords, tokens) are redacted. The corpus still contains request
  bodies — treat the file as sensitive.
"""
from __future__ import annotations

import asyncio
import base64
import json
import random
import threading
import time
from typing import Any

from starlette.requests import Request

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.shadow")

# Request headers worth keeping for faithful replay. Everything else (notably
# Cookie and Authorization) is dropped — identity travels via ``principal``.
_KEEP_HEADERS = frozenset({
    "content-type", "accept", "accept-language", "user-agent",
    "origin", "referer", "x-request-id", "x-csrf-token",
})

# JSON body keys whose values are replaced with "[REDACTED]" before writing.
_REDACT_FIELDS = frozenset({
    "password", "current_password", "new_password", "otp", "code",
    "token", "id_token", "access_token", "secret", "credential", "api_key",
})

_write_lock = threading.Lock()


def _redact_body(raw: bytes, content_type: str) -> tuple[bytes, bool]:
    """Redact sensitive fields in a JSON body. Returns (body, redacted?)."""
    if "application/json" not in content_type.lower():
        return raw, False
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return raw, False
    if not isinstance(data, dict):
        return raw, False
    redacted = False
    for key in list(data.keys()):
        if key.lower() in _REDACT_FIELDS and data[key] not in (None, ""):
            data[key] = "[REDACTED]"
            redacted = True
    if not redacted:
        return raw, False
    return json.dumps(data).encode("utf-8"), True


def _filter_headers(scope_headers: list[tuple[bytes, bytes]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in scope_headers:
        name = k.decode("latin-1").lower()
        if name in _KEEP_HEADERS:
            out[name] = v.decode("latin-1")
    return out


def _write_record(record: dict[str, Any]) -> None:
    """Append one JSONL record. Runs on a worker thread; never raises upward."""
    try:
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
        with _write_lock:
            with open(settings.SHADOW_CAPTURE_FILE, "a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except Exception:
        log.debug("shadow capture write failed", exc_info=True)


class ShadowCaptureMiddleware:
    """Pure-ASGI middleware that tees request/response for offline replay."""

    def __init__(self, app):
        self.app = app
        self._exclude = tuple(settings.SHADOW_CAPTURE_EXCLUDE_PREFIXES)
        self._max_body = settings.SHADOW_CAPTURE_MAX_BODY_BYTES
        self._sample = settings.SHADOW_CAPTURE_SAMPLE_RATE
        self._capture_resp_body = settings.SHADOW_CAPTURE_RESPONSE_BODY

    def _eligible(self, scope) -> bool:
        if scope["type"] != "http":
            return False
        path = scope.get("path", "")
        if any(path.startswith(p) for p in self._exclude):
            return False
        if self._sample < 1.0 and random.random() > self._sample:
            return False
        return True

    async def __call__(self, scope, receive, send):
        if not self._eligible(scope):
            await self.app(scope, receive, send)
            return

        body_chunks: list[bytes] = []
        body_size = 0
        body_truncated = False

        async def recv():
            nonlocal body_size, body_truncated
            message = await receive()
            if message["type"] == "http.request":
                chunk = message.get("body", b"")
                if body_size < self._max_body:
                    take = self._max_body - body_size
                    body_chunks.append(chunk[:take])
                    if len(chunk) > take:
                        body_truncated = True
                elif chunk:
                    body_truncated = True
                body_size += len(chunk)
            return message

        resp = {"status": 0, "content_type": "", "body": bytearray()}

        async def snd(message):
            if message["type"] == "http.response.start":
                resp["status"] = message["status"]
                for k, v in message.get("headers", []):
                    if k.decode("latin-1").lower() == "content-type":
                        resp["content_type"] = v.decode("latin-1")
            elif message["type"] == "http.response.body" and self._capture_resp_body:
                if len(resp["body"]) < self._max_body:
                    resp["body"].extend(message.get("body", b"")[: self._max_body])
            await send(message)

        await self.app(scope, recv, snd)

        # Build + persist the record after the response is fully sent.
        try:
            await self._persist(scope, b"".join(body_chunks), body_truncated, resp)
        except Exception:
            log.debug("shadow capture failed", exc_info=True)

    async def _persist(self, scope, body: bytes, truncated: bool, resp: dict) -> None:
        headers = scope.get("headers", [])
        content_type = ""
        for k, v in headers:
            if k.decode("latin-1").lower() == "content-type":
                content_type = v.decode("latin-1")
                break

        body, redacted = _redact_body(body, content_type) if body else (body, False)

        # Resolve the authenticated principal Python saw (cookie/Bearer/auto-admin).
        principal = None
        try:
            from app.security import optional_session
            principal = optional_session(Request(scope))
        except Exception:
            principal = None

        record: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request_id": _header(headers, "x-request-id"),
            "method": scope.get("method", ""),
            "path": scope.get("path", ""),
            "query": scope.get("query_string", b"").decode("latin-1"),
            "headers": _filter_headers(headers),
            "body_b64": base64.b64encode(body).decode("ascii") if body else "",
            "body_truncated": truncated,
            "body_redacted": redacted,
            "principal": principal,
            "response": {
                "status": resp["status"],
                "content_type": resp["content_type"],
                "body_b64": (
                    base64.b64encode(bytes(resp["body"])).decode("ascii")
                    if self._capture_resp_body and resp["body"]
                    else ""
                ),
            },
        }
        await asyncio.to_thread(_write_record, record)


def _header(headers: list[tuple[bytes, bytes]], name: str) -> str:
    for k, v in headers:
        if k.decode("latin-1").lower() == name:
            return v.decode("latin-1")
    return ""


def install_shadow_capture(app) -> None:
    """Install the capture middleware iff SHADOW_CAPTURE_ENABLED. No-op otherwise."""
    if not settings.SHADOW_CAPTURE_ENABLED:
        return
    app.add_middleware(ShadowCaptureMiddleware)
    log.warning(
        "shadow_capture_enabled",
        file=settings.SHADOW_CAPTURE_FILE,
        sample_rate=settings.SHADOW_CAPTURE_SAMPLE_RATE,
        response_body=settings.SHADOW_CAPTURE_RESPONSE_BODY,
    )
