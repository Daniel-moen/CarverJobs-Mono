"""
Weekly agency jobs-intel digest.

GET /agent/digest — one week of scraped roles, rendered for sending.

The concierge revenue test from the 22 Sep 2026 review: the founder hand-sends
a weekly digest to crew agencies (Cape Town, Antibes, Palma, Fort Lauderdale),
free for three weeks, ~R1,000/mo after. This endpoint is the whole production
pipeline — one authenticated GET per agency per week:

    GET /agent/digest?week=2026-W38&region=za&format=md

Authenticated with the same static bearer token as /agent/stats
(AGENT_API_TOKEN), not the session system — it is a founder/agent tool.
"""

import re
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, PlainTextResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.error_codes import CRV_1003, CRV_5006
from app.logger import get_logger
from app.routes.agent_stats import _require_agent_token
from app.services.agency_digest import (
    REGIONS,
    build_digest,
    render_html,
    render_markdown,
)

log = get_logger("carver.digest")
_limiter = Limiter(key_func=get_remote_address)

router = APIRouter(prefix="/agent", tags=["agent"])

_FORMATS = ("md", "html", "json")
_DEFAULT_WINDOW = timedelta(days=7)
# A digest is a weekly artefact; anything past a quarter is a reporting job,
# not a send, and would scan the whole jobs table.
_MAX_WINDOW = timedelta(days=90)

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$", re.IGNORECASE)


def _bad_request(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=detail,
        headers={"X-Error-Code": CRV_1003},
    )


def _as_utc(value: datetime) -> datetime:
    """Treat naive query datetimes as UTC — the whole app stores UTC."""
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _week_window(week: str) -> tuple[datetime, datetime]:
    """ISO week ("2026-W38") -> [Monday 00:00 UTC, next Monday 00:00 UTC)."""
    match = _WEEK_RE.match(week.strip())
    if not match:
        raise _bad_request("week must look like 2026-W38 (ISO year-week).")
    year, number = int(match.group(1)), int(match.group(2))
    try:
        monday = datetime.fromisocalendar(year, number, 1)
    except ValueError as exc:
        raise _bad_request(f"Invalid ISO week: {week}.") from exc
    since = monday.replace(tzinfo=timezone.utc)
    return since, since + _DEFAULT_WINDOW


def _resolve_window(
    week: str | None, since: datetime | None, until: datetime | None
) -> tuple[datetime, datetime]:
    if week:
        if since or until:
            raise _bad_request("Pass either week, or since/until — not both.")
        return _week_window(week)

    if since is None and until is None:
        now = datetime.now(timezone.utc)
        return now - _DEFAULT_WINDOW, now

    if since is not None and until is None:
        start = _as_utc(since)
        return start, start + _DEFAULT_WINDOW
    if until is not None and since is None:
        end = _as_utc(until)
        return end - _DEFAULT_WINDOW, end

    start, end = _as_utc(since), _as_utc(until)
    if end <= start:
        raise _bad_request("until must be after since.")
    if end - start > _MAX_WINDOW:
        raise _bad_request("Window too wide (max 90 days).")
    return start, end


@router.get("/digest", dependencies=[Depends(_require_agent_token)])
@_limiter.limit("20/minute")
def get_agency_digest(
    request: Request,
    week: str | None = Query(None, description="ISO week, e.g. 2026-W38"),
    since: datetime | None = Query(None, description="Window start (UTC, inclusive)"),
    until: datetime | None = Query(None, description="Window end (UTC, exclusive)"),
    region: str | None = Query(None, description="med | americas | za | other"),
    format: str = Query("md", description="md | html | json"),
    db: Session = Depends(get_db),
):
    """Build one week of jobs intel, ready to send. Defaults to the last 7 days."""
    fmt = (format or "md").strip().lower()
    if fmt not in _FORMATS:
        raise _bad_request(f"format must be one of {', '.join(_FORMATS)}.")

    region_key = (region or "").strip().lower() or None
    if region_key and region_key not in REGIONS:
        raise _bad_request(f"region must be one of {', '.join(REGIONS)}.")

    window_since, window_until = _resolve_window(week, since, until)

    try:
        digest = build_digest(db, window_since, window_until, region=region_key)
    except Exception as exc:
        log.error("Digest build failed | since=%s | until=%s | %s",
                  window_since, window_until, exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not build the digest.",
            headers={"X-Error-Code": CRV_5006},
        ) from exc

    log.info(
        "Digest built | %s → %s | region=%s | jobs=%d | crew=%d | format=%s",
        window_since.date(), window_until.date(), region_key or "all",
        digest.totals.jobs, len(digest.crew), fmt,
    )

    if fmt == "html":
        return HTMLResponse(content=render_html(digest))
    if fmt == "md":
        return PlainTextResponse(
            content=render_markdown(digest),
            media_type="text/markdown; charset=utf-8",
        )
    return {"ok": True, **digest.to_dict()}
