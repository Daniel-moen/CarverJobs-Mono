"""
Signed-token CSRF protection.

How it works:
  1. Every GET/HEAD response includes an X-CSRF-Token header containing
     an HMAC-signed, time-stamped token.
  2. The frontend stores this token in memory and sends it back on every
     mutating request (POST / PATCH / DELETE / PUT) via X-CSRF-Token.
  3. The server verifies the signature and checks the token hasn't expired.
  4. An attacker on another origin can't read the response header
     (CORS blocks it unless exposed), so they can't forge the token.

This replaces the double-submit cookie pattern which breaks when the
frontend and API are on different ports (cross-origin cookie issues).
"""
import hashlib
import hmac
import time

from fastapi import HTTPException, Request, status

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.csrf")

CSRF_HEADER_NAME = "X-CSRF-Token"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_EXEMPT_PATHS = frozenset({"/health", "/admin/analytics", "/auth/login", "/auth/google", "/auth/waitlist", "/whatsapp/webhook", "/subscription/notify"})
_TOKEN_MAX_AGE = settings.SESSION_TTL_SECONDS


def _sign(timestamp: str) -> str:
    return hmac.new(
        settings.SECRET_KEY.encode(),
        timestamp.encode(),
        hashlib.sha256,
    ).hexdigest()[:32]


def generate_csrf_token() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def _verify_token(token: str) -> bool:
    parts = token.split(".", 1)
    if len(parts) != 2:
        return False
    ts, sig = parts
    if not hmac.compare_digest(sig, _sign(ts)):
        return False
    try:
        age = int(time.time()) - int(ts)
        return 0 <= age <= _TOKEN_MAX_AGE
    except (ValueError, OverflowError):
        return False


def check_csrf(request: Request) -> None:
    if request.method in _SAFE_METHODS:
        return
    if request.url.path in _EXEMPT_PATHS:
        return

    token_header = request.headers.get(CSRF_HEADER_NAME, "")

    if not token_header:
        log.warning(
            "CSRF token missing | path=%s | method=%s",
            request.url.path,
            request.method,
        )
        raise _csrf_error("CSRF token missing")

    if not _verify_token(token_header):
        log.warning("CSRF token invalid | path=%s | method=%s", request.url.path, request.method)
        raise _csrf_error("CSRF token invalid")


def _csrf_error(detail: str):
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=detail,
    )
