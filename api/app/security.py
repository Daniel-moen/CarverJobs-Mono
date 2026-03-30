from typing import NotRequired, TypedDict, cast

import bcrypt
from fastapi import Depends, HTTPException, Request, status
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app.error_codes import CRV_2003, CRV_2004, CRV_2005
from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.security")
_serializer = URLSafeTimedSerializer(settings.SECRET_KEY, salt="carver-session")


class SessionPayload(TypedDict):
    """Signed session cookie payload (itsdangerous-serialized)."""

    sub: str
    role: str
    user_id: NotRequired[int]
    provider: NotRequired[str]


def hash_password(raw_password: str) -> str:
    """Hash a password using bcrypt. Returns the hashed string."""
    return bcrypt.hashpw(raw_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(raw_password: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(raw_password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def issue_session_token(payload: SessionPayload) -> str:
  return _serializer.dumps(payload)


def parse_session_token(token: str) -> SessionPayload:
  try:
    data = _serializer.loads(token, max_age=settings.SESSION_TTL_SECONDS)
    return cast(SessionPayload, data)
  except SignatureExpired as exc:
    log.warning("Session token expired")
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Session expired",
      headers={"X-Error-Code": CRV_2003},
    ) from exc
  except BadSignature as exc:
    log.warning("Session token invalid signature")
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Invalid session token",
      headers={"X-Error-Code": CRV_2004},
    ) from exc


def optional_session(request: Request) -> SessionPayload | None:
  """Return session payload if a valid cookie exists, else None (no exception)."""
  if settings.AUTO_LOGIN_AS_ADMIN:
    log.debug("Auto-login as admin active")
    return cast(SessionPayload, {"sub": settings.ADMIN_USERNAME, "role": "admin"})
  token = request.cookies.get(settings.SESSION_COOKIE_NAME)
  if not token:
    return None
  try:
    return parse_session_token(token)
  except HTTPException:
    return None


def require_session(request: Request) -> SessionPayload:
  session = optional_session(request)
  if session is None:
    log.debug("No session cookie on request | path=%s", request.url.path)
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Authentication required",
      headers={"X-Error-Code": CRV_2004},
    )
  return session


def require_admin_session(session: SessionPayload = Depends(require_session)) -> SessionPayload:
  if session.get("role") != "admin":
    log.warning("Admin access denied | sub=%s | role=%s", session.get("sub"), session.get("role"))
    raise HTTPException(
      status_code=status.HTTP_403_FORBIDDEN,
      detail="Admin access required",
      headers={"X-Error-Code": CRV_2005},
    )
  return session
