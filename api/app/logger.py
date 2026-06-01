"""
Structured logging — structlog with stdlib integration.

In development (APP_ENV != "production"):
  - Coloured console output with key=value fields
  - Human-readable timestamps

In production:
  - Compact JSON, one object per line
  - ISO-8601 timestamps
  - All log records are machine-parseable (Splunk, Datadog, CloudWatch, etc.)

Usage:
    from app.logger import get_logger
    log = get_logger("carver.job_sync")
    log.info("Job synced", job_id=job.id, source="dockwalk")

Bind per-request context in middleware:
    from app.logger import bind_request_id
    with bind_request_id(request_id):
        ...
"""
import logging
import sys

import structlog
from structlog.contextvars import bind_contextvars, clear_contextvars

from app.settings import settings


# ── Processors (shared by dev + prod) ─────────────────────────────────────────

_shared_processors: list = [
    structlog.stdlib.filter_by_level,
    structlog.stdlib.add_logger_name,
    structlog.stdlib.add_log_level,
    structlog.processors.TimeStamper(fmt="iso"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.UnicodeDecoder(),
    # Pull any bound contextvars (request_id, user_id, etc.) into every record
    structlog.contextvars.merge_contextvars,
]

# In dev we want nice formatting; in prod we want raw JSON.
if settings.APP_ENV == "production":
    _processors = _shared_processors + [
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer(),
    ]
else:
    _processors = _shared_processors + [
        structlog.processors.ExceptionPrettyPrinter(),
        structlog.dev.ConsoleRenderer(colors=True),
    ]


# ── Setup ────────────────────────────────────────────────────────────────────

def setup_logging(level: str = "INFO") -> None:
    """
    Configure structlog *and* stdlib logging so that everything emitted
    from either pipeline goes through the same chain and ends up formatted
    the same way on stdout.

    Safe to call multiple times — subsequent calls are no-ops.
    """
    root = logging.getLogger()
    if root.handlers:
        # Already configured (e.g. uvicorn has added its own handler).
        # Replace it with our own StreamHandler so JSON formatting wins.
        root.handlers.clear()

    # Wrap stdlib loggers so they pass through structlog processors
    structlog.configure(
        processors=_processors,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    # Use structlog's formatter for stdlib records too
    handler.setFormatter(structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True)
        if settings.APP_ENV != "production"
        else structlog.processors.JSONRenderer(),
        foreign_pre_chain=_shared_processors,
    ))
    root.addHandler(handler)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Keep uvicorn.access quiet; uvicorn.error still comes through
    logging.getLogger("uvicorn.access").propagate = False
    logging.getLogger("uvicorn.error").propagate = True


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structlog-wrapped logger.  Drop-in replacement for logging.getLogger."""
    return structlog.get_logger(name)


def bind_request_id(request_id: str | None) -> None:
    """
    Bind *request_id* to the current structlog contextvars scope.
    Every subsequent log line in this context will include the request_id.

    Call at the start of a request and clear with reset_context() afterwards.
    """
    if request_id is not None:
        bind_contextvars(request_id=request_id)


def reset_context() -> None:
    """Clear all bound structlog contextvars.  Call at the end of a request."""
    clear_contextvars()
