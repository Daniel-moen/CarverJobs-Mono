import asyncio
import traceback as _traceback
import uuid
from contextlib import asynccontextmanager
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.csrf import check_csrf, generate_csrf_token, CSRF_HEADER_NAME
from app.database import Base, engine, run_migrations, SessionLocal
from app import metrics, models
from app.error_codes import CRV_1003, CRV_1004, CRV_1006, STATUS_CODE_TO_CRV
from app.health_checker import health_check_loop
from app.logger import get_logger, setup_logging
from app.routes import admin, auth, crew_match, documents, health, interview, job_history, jobs, matching, profile, scraper, users, whatsapp
from app.scheduler import scraper_loop
from app.seed_users import ensure_default_user
from app.settings import settings, validate_production_settings

setup_logging()
log = get_logger("carver.api")

limiter = Limiter(key_func=get_remote_address)


def _init_database() -> None:
    """Create tables, run migrations, seed users. Never crashes the process."""
    try:
        validate_production_settings()
    except RuntimeError:
        log.exception("Production settings validation failed — refusing to start")
        raise
    try:
        Base.metadata.create_all(bind=engine)
        run_migrations()
        ensure_default_user()
        log.info("Database initialised successfully")
    except Exception:
        log.exception("Database initialisation failed — app will start but DB may be unavailable")


async def metrics_loop() -> None:
    while True:
        await asyncio.sleep(60)
        metrics.record_snapshot()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_database()
    log.info("Starting background health checker (interval=5m)")
    health_task = asyncio.create_task(health_check_loop())
    log.info("Starting background metrics recorder (interval=1m)")
    metrics_task = asyncio.create_task(metrics_loop())
    log.info("Starting APIFY scraper scheduler (interval=6h)")
    scraper_task = asyncio.create_task(scraper_loop())
    yield
    log.info("Shutting down background tasks…")
    for task in (health_task, metrics_task, scraper_task):
        task.cancel()
    await asyncio.gather(health_task, metrics_task, scraper_task, return_exceptions=True)
    log.info("Background tasks stopped")


app = FastAPI(title="CARVER API", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter


# ── Error persistence ───────────────────────────────────────────────────────

def _log_error_to_db(
    *,
    level: str = "error",
    status_code: int | None = None,
    crv_code: str | None = None,
    method: str | None = None,
    path: str | None = None,
    module: str | None = None,
    message: str,
    tb: str | None = None,
    request_id: str | None = None,
    client_ip: str | None = None,
) -> None:
    """Persist an error to error_logs. Never raises — logging must not break the response."""
    try:
        db = SessionLocal()
        try:
            db.add(models.ErrorLog(
                level=level,
                status_code=status_code,
                crv_code=crv_code,
                method=method,
                path=path,
                module=module,
                message=message[:2000],
                traceback=tb,
                request_id=request_id,
                client_ip=client_ip,
            ))
            db.commit()
            total = db.query(models.ErrorLog).count()
            if total > 200:
                cutoff_id = (
                    db.query(models.ErrorLog.id)
                    .order_by(models.ErrorLog.id.desc())
                    .offset(199)
                    .limit(1)
                    .scalar()
                )
                if cutoff_id:
                    db.query(models.ErrorLog).filter(models.ErrorLog.id < cutoff_id).delete(
                        synchronize_session=False
                    )
                    db.commit()
        finally:
            db.close()
    except Exception:
        pass


# ── Global exception handlers ───────────────────────────────────────────────

def _crv_response(status_code: int, detail: str, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"detail": detail, "code": code},
    )


def _extract_crv_code(exc: HTTPException) -> str | None:
    headers = getattr(exc, "headers", None) or {}
    code = headers.get("X-Error-Code", "")
    return code if code.startswith("CRV-") else None


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    log.warning("Validation error | path=%s | errors=%s", request.url.path, exc.errors())
    return _crv_response(422, "Invalid request data.", CRV_1003)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return _crv_response(429, "Too many requests. Please slow down.", CRV_1004)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    code = _extract_crv_code(exc) if isinstance(exc, HTTPException) else None
    if not code:
        code = STATUS_CODE_TO_CRV.get(exc.status_code, CRV_1006)
    detail = str(exc.detail) if exc.detail else "Something went wrong."
    if exc.status_code >= 500:
        _log_error_to_db(
            level="error",
            status_code=exc.status_code,
            crv_code=code,
            method=request.method,
            path=str(request.url.path),
            module=_route_module(request.url.path),
            message=detail,
            request_id=getattr(request.state, "request_id", None),
            client_ip=request.client.host if request.client else None,
        )
    return _crv_response(exc.status_code, detail, code)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    tb = _traceback.format_exc()
    log.exception("Unhandled exception | path=%s | %s", request.url.path, exc)
    _log_error_to_db(
        level="error",
        status_code=500,
        crv_code=CRV_1006,
        method=request.method,
        path=str(request.url.path),
        module=_route_module(request.url.path),
        message=str(exc),
        tb=tb,
        request_id=getattr(request.state, "request_id", None),
        client_ip=request.client.host if request.client else None,
    )
    return _crv_response(500, "Internal server error.", CRV_1006)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    req_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = req_id
    return response


_MODULE_PREFIXES = [
    "/auth", "/jobs", "/users", "/admin", "/matching",
    "/interview", "/documents", "/scraper", "/health", "/status",
    "/profile", "/job-history", "/p",
]


def _route_module(path: str) -> str:
    for prefix in _MODULE_PREFIXES:
        if path.startswith(prefix):
            return prefix.lstrip("/").split("/")[0]
    return "other"


@app.middleware("http")
async def request_logger(request: Request, call_next):
    start = time.perf_counter()
    req_id = getattr(request.state, "request_id", "-")
    log.info("→ %s %s | ip=%s | req=%s", request.method, request.url.path, request.client.host if request.client else "unknown", req_id)
    try:
        response = await call_next(request)
    except Exception as exc:
        tb = _traceback.format_exc()
        elapsed = round((time.perf_counter() - start) * 1000)
        module = _route_module(request.url.path)
        log.exception("✗ %s %s | UNHANDLED ERROR | %dms | req=%s | module=%s | %s", request.method, request.url.path, elapsed, req_id, module, exc)
        metrics.record_error_by_module(module, "5xx")
        _log_error_to_db(
            level="error",
            status_code=500,
            crv_code=CRV_1006,
            method=request.method,
            path=str(request.url.path),
            module=module,
            message=str(exc),
            tb=tb,
            request_id=req_id,
            client_ip=request.client.host if request.client else None,
        )
        return JSONResponse(status_code=500, content={"detail": "Internal server error.", "code": CRV_1006})
    elapsed = round((time.perf_counter() - start) * 1000)
    module = _route_module(request.url.path)
    level = log.warning if response.status_code >= 400 else log.info
    level("← %s %s | status=%d | %dms | req=%s | module=%s", request.method, request.url.path, response.status_code, elapsed, req_id, module)
    metrics.increment("requests_total")
    if not request.url.path.startswith("/interview/"):
        metrics.record_response_time(elapsed)
    if response.status_code == 429:
        metrics.increment("rate_limit_hits")
    elif 400 <= response.status_code < 500:
        metrics.increment("errors_4xx")
        metrics.record_error_by_module(module, "4xx")
    elif response.status_code >= 500:
        metrics.increment("errors_5xx")
        metrics.record_error_by_module(module, "5xx")
    return response


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    try:
        check_csrf(request)
    except Exception as exc:
        from fastapi import HTTPException as _HTTPException
        from app.error_codes import CRV_2006
        if isinstance(exc, _HTTPException):
            metrics.increment("csrf_rejections")
            error_resp = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail, "code": CRV_2006})
            error_resp.headers[CSRF_HEADER_NAME] = generate_csrf_token()
            return error_resp
        raise
    response = await call_next(request)
    if request.method in ("GET", "HEAD"):
        response.headers[CSRF_HEADER_NAME] = generate_csrf_token()
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' https://accounts.google.com; "
        "frame-src 'none'; "
        "object-src 'none'"
    )
    if settings.APP_ENV == "production" and request.headers.get("X-Forwarded-Proto") == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["X-CSRF-Token"],
)

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(users.router)
app.include_router(matching.router)
app.include_router(interview.router)
app.include_router(admin.router)
app.include_router(admin.public_router)
app.include_router(documents.router)
app.include_router(profile.router)
app.include_router(profile.public_router)
app.include_router(job_history.router)
app.include_router(crew_match.router)
app.include_router(scraper.router)
app.include_router(whatsapp.router)

log.info("CARVER API ready | env=%s | auto_login=%s", settings.APP_ENV, settings.AUTO_LOGIN_AS_ADMIN)
