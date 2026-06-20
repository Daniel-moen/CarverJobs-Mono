"""Capability-aware canary routing to the Go port (jobcarver-go).

Runs the Go server *alongside* this Python API and serves a slice of live
traffic from it, so the Go rewrite is exercised by real users before full
cutover. Routing rules (see ``GoCanaryMiddleware._decide``):

* **Unimplemented routes always stay on Python.** Any path whose feature is
  still stubbed in Go (AI, Yoco checkout, scrapers, Google login, AI job-submit,
  WhatsApp/Telnyx) is listed in ``GO_UNIMPLEMENTED_PREFIXES`` and never routed.
* **Flagged users → Go** for every Go-implemented route. Mark a user via
  ``PATCH /admin/users/{id}/routing`` (see ``routes/admin.py``); the flag lives in
  ``users.route_to_go`` and a memory registry (``flagged``).
* **Everyone else → Go ~``GO_ROUTING_PERCENT``%** of the time (stable per user),
  for Go-implemented routes only.

When a request is routed to Go, **Go serves the response**. Python and Go use
different session-token formats, so the proxy mints a *native Go* session cookie
(and CSRF token) from the principal Python authenticated. If Go errors, times
out, or 5xx's, the request transparently **falls back to Python** so users are
never impacted.

OFF by default (``GO_ROUTING_ENABLED``) and a no-op until ``GO_UPSTREAM_URL`` is
set. See ``jobcarver-go/SHADOW.md`` (Canary section).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import random
import threading
import time

import httpx
from starlette.requests import Request

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.canary")

# Hop-by-hop headers that must not be copied between connections (RFC 7230 §6.1).
_HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-length",
})

# Largest request body we'll buffer to forward. Bigger requests stay on Python
# (uploads live under /documents which is unimplemented-in-Go anyway).
_MAX_FORWARD_BYTES = 5 * 1024 * 1024


# ── Go-compatible token minting (mirrors jobcarver-go/internal/security) ──────

def _b64url(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode("ascii")


def mint_go_session(principal: dict) -> str:
    """Build a token jobcarver-go will verify: ``<payload>.<ts>.<sig>`` where the
    HMAC is over ``carver-session|<payload>.<ts>`` (the Go ``salt|msg`` scheme)."""
    payload = {k: principal[k] for k in ("sub", "role", "user_id", "provider") if k in principal}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    p = _b64url(raw)
    ts = str(int(time.time()))
    msg = f"{p}.{ts}"
    mac = hmac.new(settings.SECRET_KEY.encode(), b"carver-session|" + msg.encode(), hashlib.sha256).digest()
    return f"{msg}.{_b64url(mac)}"


def mint_go_csrf() -> str:
    """Build a CSRF token jobcarver-go will accept: ``<ts>.<hex16>``."""
    ts = str(int(time.time()))
    sig = hmac.new(settings.SECRET_KEY.encode(), ts.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{ts}.{sig}"


# ── Flagged-user registry (per-user "always Go") ──────────────────────────────

class _FlaggedRegistry:
    """In-memory set of user IDs pinned to Go, mirrored to users.route_to_go."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ids: set[int] = set()

    def load(self, ids) -> None:
        with self._lock:
            self._ids = {int(i) for i in ids}

    def set(self, user_id: int, on: bool) -> None:
        with self._lock:
            if on:
                self._ids.add(int(user_id))
            else:
                self._ids.discard(int(user_id))

    def has(self, user_id: int) -> bool:
        with self._lock:
            return int(user_id) in self._ids

    def all(self) -> list[int]:
        with self._lock:
            return sorted(self._ids)


flagged = _FlaggedRegistry()


def load_flagged_users() -> None:
    """Populate the registry from the DB at startup. Never raises."""
    try:
        from app.database import SessionLocal
        from app.models import User
        db = SessionLocal()
        try:
            ids = [row[0] for row in db.query(User.id).filter(User.route_to_go.is_(True)).all()]
            flagged.load(ids)
            if ids:
                log.info("canary flagged users loaded", count=len(ids))
        finally:
            db.close()
    except Exception:
        log.debug("could not load flagged users (table may not be ready)", exc_info=True)


# ── Middleware ────────────────────────────────────────────────────────────────

class GoCanaryMiddleware:
    def __init__(self, app):
        self.app = app
        self._unimplemented = tuple(p for p in settings.GO_UNIMPLEMENTED_PREFIXES if p)
        self._percent = max(0, min(100, settings.GO_ROUTING_PERCENT))
        self._upstream = settings.GO_UPSTREAM_URL.rstrip("/")
        self._client = httpx.AsyncClient(timeout=settings.GO_ROUTING_TIMEOUT_SECONDS)

    def _is_unimplemented(self, path: str) -> bool:
        return any(path == p or path.startswith(p) for p in self._unimplemented)

    def _decide(self, principal: dict | None, path: str) -> bool:
        """True → serve from Go. Assumes the route is already Go-implemented."""
        if principal:
            uid = principal.get("user_id")
            if uid is not None and flagged.has(uid):
                return True
            if uid is not None:
                return _stable_bucket(str(uid)) < self._percent
        # Anonymous: per-request sample.
        return random.random() * 100 < self._percent

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not self._upstream or self._is_unimplemented(path):
            return await self.app(scope, receive, send)

        # Resolve identity from the cookie without touching the body.
        principal = None
        try:
            from app.security import optional_session
            principal = optional_session(Request(scope))
        except Exception:
            principal = None

        if not self._decide(principal, path):
            return await self.app(scope, receive, send)

        # Oversized/streamed bodies stay on Python rather than buffering.
        if _content_length(scope) > _MAX_FORWARD_BYTES:
            return await self.app(scope, receive, send)

        body = await _read_body(receive)
        try:
            resp = await self._forward(scope, body, principal)
            if resp.status_code >= 500:
                log.warning("canary go 5xx — falling back to python",
                            path=path, status=resp.status_code)
                return await self.app(scope, _replay_receive(body), send)
        except Exception as exc:
            log.warning("canary go request failed — falling back to python",
                        path=path, error=str(exc))
            return await self.app(scope, _replay_receive(body), send)

        await _send_upstream_response(send, resp)

    async def _forward(self, scope, body: bytes, principal: dict | None) -> httpx.Response:
        method = scope["method"]
        path = scope["path"]
        qs = scope.get("query_string", b"").decode("latin-1")
        url = self._upstream + path + (("?" + qs) if qs else "")

        headers: dict[str, str] = {}
        for k, v in scope.get("headers", []):
            name = k.decode("latin-1").lower()
            if name in _HOP_BY_HOP or name in ("host", "cookie", "x-csrf-token"):
                continue
            headers[name] = v.decode("latin-1")

        if principal:
            headers["cookie"] = f"{settings.SESSION_COOKIE_NAME}={mint_go_session(principal)}"
            if method in ("POST", "PUT", "PATCH", "DELETE"):
                headers["x-csrf-token"] = mint_go_csrf()
        headers["x-carver-canary"] = "1"

        return await self._client.request(method, url, content=body, headers=headers)


def _stable_bucket(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100


def _content_length(scope) -> int:
    for k, v in scope.get("headers", []):
        if k.decode("latin-1").lower() == "content-length":
            try:
                return int(v)
            except ValueError:
                return 0
    return 0


async def _read_body(receive) -> bytes:
    chunks = []
    while True:
        msg = await receive()
        if msg["type"] == "http.request":
            chunks.append(msg.get("body", b""))
            if not msg.get("more_body", False):
                break
        elif msg["type"] == "http.disconnect":
            break
    return b"".join(chunks)


def _replay_receive(body: bytes):
    """Receive callable that replays the buffered body to the Python app."""
    sent = False

    async def receive():
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.request", "body": b"", "more_body": False}

    return receive


async def _send_upstream_response(send, resp: httpx.Response) -> None:
    out_headers = []
    for k, v in resp.headers.items():
        if k.lower() in _HOP_BY_HOP:
            continue
        out_headers.append((k.encode("latin-1"), v.encode("latin-1")))
    body = resp.content
    out_headers.append((b"content-length", str(len(body)).encode()))
    out_headers.append((b"x-carver-backend", b"go"))
    await send({"type": "http.response.start", "status": resp.status_code, "headers": out_headers})
    await send({"type": "http.response.body", "body": body})


def install_go_canary(app) -> None:
    """Install canary routing iff enabled + upstream configured. No-op otherwise."""
    if not settings.GO_ROUTING_ENABLED:
        return
    if not settings.GO_UPSTREAM_URL:
        log.warning("GO_ROUTING_ENABLED but GO_UPSTREAM_URL is empty — canary disabled")
        return
    app.add_middleware(GoCanaryMiddleware)
    log.warning("go_canary_enabled", upstream=settings.GO_UPSTREAM_URL,
                percent=settings.GO_ROUTING_PERCENT,
                unimplemented=list(settings.GO_UNIMPLEMENTED_PREFIXES))
