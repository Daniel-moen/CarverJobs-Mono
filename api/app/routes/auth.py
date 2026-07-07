import hmac

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud, flags, metrics, models
from app.analytics import record_server_event
from app.error_codes import CRV_2002, CRV_2007, CRV_2008, CRV_2009
from app.database import get_db
from app.logger import get_logger
from app.schemas import AgencySignupRequest, GoogleLoginRequest, LoginRequest, SignupRequest, UserCreate, WaitlistSignupRequest
from app.security import issue_session_token, optional_session, require_session, verify_password
from app.services.credits import get_credit_balance
from app.settings import settings

log = get_logger("carver.auth")
router = APIRouter(prefix="/auth", tags=["auth"])
_limiter = Limiter(key_func=get_remote_address)

# Safari/iOS can be strict about cross-site cookies; SameSite=None must
# be paired with Secure=true or browsers will ignore the cookie.
SESSION_SAMESITE = "none" if settings.SESSION_SECURE_COOKIE else "lax"

def _set_session_cookie(response: Response, token: str) -> None:
  response.set_cookie(
    key=settings.SESSION_COOKIE_NAME,
    value=token,
    httponly=True,
    secure=settings.SESSION_SECURE_COOKIE,
    samesite=SESSION_SAMESITE,
    max_age=settings.SESSION_TTL_SECONDS,
    path="/",
  )


def _google_auth_enabled() -> bool:
  return bool(settings.GOOGLE_OAUTH_CLIENT_ID)


def _google_email_allowed(email: str, verified: bool) -> bool:
  if settings.GOOGLE_REQUIRE_VERIFIED_EMAIL and not verified:
    log.warning("Google login rejected: email not verified | email=%s", email)
    return False
  email_lc = email.lower().strip()
  if not email_lc:
    return False
  if settings.GOOGLE_ALLOWED_EMAILS or settings.GOOGLE_ALLOWED_DOMAIN:
    if email_lc in settings.GOOGLE_ALLOWED_EMAILS:
      return True
    if settings.GOOGLE_ALLOWED_DOMAIN and email_lc.endswith(f"@{settings.GOOGLE_ALLOWED_DOMAIN}"):
      return True
    return False
  # No allowlist/domain configured: allow any verified Google account.
  return True


@router.get("/providers")
def auth_providers():
  enabled = _google_auth_enabled()
  log.debug("Providers queried | google_enabled=%s", enabled)
  return {
    "ok": True,
    "google": {
      "enabled": enabled,
      "client_id": settings.GOOGLE_OAUTH_CLIENT_ID if enabled else None,
    },
  }


@router.post("/waitlist", status_code=status.HTTP_201_CREATED)
@_limiter.limit("5/minute")
def signup_waitlist(request: Request, payload: WaitlistSignupRequest, db: Session = Depends(get_db)):
  email = payload.email.strip().lower()
  if not email:
    raise HTTPException(
      status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
      detail="Email is required.",
    )

  try:
    db.add(models.WaitlistSignup(email=email, source="website"))
    db.commit()
  except IntegrityError:
    db.rollback()
    # Keep response neutral to avoid leaking membership details.
    return {"ok": True}

  return {"ok": True}


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@_limiter.limit("5/minute")
def signup(request: Request, payload: SignupRequest, response: Response, db: Session = Depends(get_db)):
  if not flags.is_enabled("user_registration"):
    metrics.increment("feature_blocked")
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="Registration is temporarily disabled.",
    )

  email = payload.email.strip().lower()
  existing = crud.get_user_by_email(db, email)
  if existing:
    log.warning("Signup failed: email exists | email=%s", email)
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="An account with this email already exists.",
      headers={"X-Error-Code": CRV_2009},
    )

  user = crud.create_user(db, UserCreate(
    email=email,
    full_name=payload.full_name.strip(),
    password=payload.password,
    role="crew",
  ))

  token = issue_session_token({"sub": email, "role": "crew", "user_id": user.id})
  _set_session_cookie(response, token)
  metrics.increment("signups_success")
  record_server_event(email, "web_signup", "password")
  log.info("Signup success | id=%d | email=%s", user.id, email)
  return {"ok": True, "user": {"id": user.id, "email": email, "role": "crew"}}


@router.post("/signup-agency", status_code=status.HTTP_201_CREATED)
@_limiter.limit("5/minute")
def signup_agency(request: Request, payload: AgencySignupRequest, response: Response, db: Session = Depends(get_db)):
  if not flags.is_enabled("user_registration"):
    metrics.increment("feature_blocked")
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="Registration is temporarily disabled.",
    )

  email = payload.email.strip().lower()
  existing = crud.get_user_by_email(db, email)
  if existing:
    log.warning("Agency signup failed: email exists | email=%s", email)
    raise HTTPException(
      status_code=status.HTTP_409_CONFLICT,
      detail="An account with this email already exists.",
      headers={"X-Error-Code": CRV_2009},
    )

  user = crud.create_agency_user(
    db,
    email=email,
    full_name=payload.full_name,
    agency_name=payload.agency_name,
    password=payload.password,
  )

  token = issue_session_token({"sub": email, "role": "agency", "user_id": user.id})
  _set_session_cookie(response, token)
  metrics.increment("signups_success")
  log.info("Agency signup success | id=%d | email=%s | agency=%s", user.id, email, user.agency_name)
  return {"ok": True, "user": {"id": user.id, "email": email, "role": "agency", "agency_name": user.agency_name}}


@router.post("/login")
@_limiter.limit("10/minute")
def login(request: Request, payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
  username = payload.username.strip()
  log.info("Login attempt | username=%s", username)

  # ── Admin login (constant-time comparison to prevent timing attacks) ──
  username_ok = hmac.compare_digest(username, settings.ADMIN_USERNAME)
  password_ok = hmac.compare_digest(payload.password, settings.ADMIN_PASSWORD)
  if username_ok and password_ok:
    token = issue_session_token({"sub": username, "role": "admin"})
    _set_session_cookie(response, token)
    metrics.increment("logins_success")
    log.info("Login success | username=%s", username)
    return {"ok": True, "user": {"username": username, "role": "admin"}}

  # ── Crew user login by email/password ──
  email = username.lower()
  user = crud.get_user_by_email(db, email)
  if user is not None and user.password_hash and verify_password(payload.password, user.password_hash):
    token = issue_session_token({"sub": user.email, "role": user.role, "user_id": user.id})
    _set_session_cookie(response, token)
    metrics.increment("logins_success")
    log.info("Login success | email=%s", user.email)
    return {"ok": True, "user": {"email": user.email, "role": user.role}}

  log.warning("Login failed | username=%s", username)
  metrics.increment("logins_failed")
  raise HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Invalid credentials",
    headers={"X-Error-Code": CRV_2002},
  )


@router.post("/google")
@_limiter.limit("10/minute")
def login_google(request: Request, payload: GoogleLoginRequest, response: Response, db: Session = Depends(get_db)):
  if not _google_auth_enabled():
    log.warning("Google login attempt but not configured")
    raise HTTPException(
      status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
      detail="Google login is not enabled",
      headers={"X-Error-Code": CRV_2007},
    )
  log.info("Google login attempt")
  try:
    token_info = id_token.verify_oauth2_token(
      payload.id_token,
      GoogleRequest(),
      settings.GOOGLE_OAUTH_CLIENT_ID,
      clock_skew_in_seconds=30,
    )
  except ValueError as exc:
    log.warning("Google token invalid: %s", exc)
    raise HTTPException(
      status_code=status.HTTP_401_UNAUTHORIZED,
      detail="Invalid Google token",
      headers={"X-Error-Code": CRV_2007},
    ) from exc

  email = str(token_info.get("email") or "").lower().strip()
  email_verified = bool(token_info.get("email_verified"))
  if not _google_email_allowed(email, email_verified):
    log.warning("Google login rejected: not in allowlist | email=%s", email)
    raise HTTPException(
      status_code=status.HTTP_403_FORBIDDEN,
      detail="Google account not allowed",
      headers={"X-Error-Code": CRV_2008},
    )

  user = crud.get_user_by_email(db, email)
  if user is None:
    full_name = str(token_info.get("name") or token_info.get("given_name") or "").strip()
    user = crud.create_google_user(db, email=email, full_name=full_name)
    record_server_event(email, "web_signup", "google")
    log.info("Google login created new user | id=%d | email=%s", user.id, email)

  token = issue_session_token({
    "sub": email,
    "role": user.role,
    "user_id": user.id,
    "provider": "google",
  })
  _set_session_cookie(response, token)
  metrics.increment("logins_success")
  log.info("Google login success | email=%s", email)
  return {
    "ok": True,
    "user": {"id": user.id, "email": email, "role": user.role, "provider": "google"},
  }


@router.post("/logout")
def logout(response: Response):
  log.info("Logout")
  response.delete_cookie(
    key=settings.SESSION_COOKIE_NAME,
    path="/",
    secure=settings.SESSION_SECURE_COOKIE,
    httponly=True,
    samesite=SESSION_SAMESITE,
  )
  return {"ok": True}


@router.get("/session")
def get_session(session: dict | None = Depends(optional_session), db: Session = Depends(get_db)):
  if session is None:
    return {"ok": True, "authenticated": False}
  log.debug("Session check | sub=%s", session.get("sub"))
  user_key = session.get("sub", "")
  # Admins always have full access; crew users check active subscription
  if session.get("role") == "admin":
    is_subscribed = True
  else:
    active_sub_exists = (
        db.query(models.Subscription.id)
        .filter(models.Subscription.user_key == user_key, models.Subscription.status == "active")
        .first()
    )
    is_subscribed = active_sub_exists is not None
  credits_balance = get_credit_balance(db, user_key) if user_key else 0
  early_bird = bool(
    db.query(models.User.early_bird)
    .filter(models.User.email == user_key)
    .scalar()
  ) if user_key else False
  agency_name = None
  if session.get("role") == "agency" and user_key:
    agency_name = (
      db.query(models.User.agency_name)
      .filter(models.User.email == user_key)
      .scalar()
    )
  return {
    "ok": True,
    "authenticated": True,
    "session": {
      **session,
      "is_subscribed": is_subscribed,
      "early_bird": early_bird,
      "credits_balance": credits_balance,
      "agency_name": agency_name,
    },
  }
