"""Weekly public "Superyacht jobs this week" article — the scraper as top-of-funnel.

Item #24 of the 22 Sep 2026 review: Carver scrapes ~75 roles a week and the
only public surface for them is the job board. A dated, indexable article that
lists the week's roles by department gives search engines a fresh page every
Monday, gives the board 75 new internal links a week, and gives the WhatsApp
bot a reason for somebody to open it.

It is the *public-safe* twin of `services/agency_digest.py` and is built from
exactly the same window of scraped rows, with three differences:

  * every job links to its public page at ``/jobs/board/{slug}`` (same slug the
    board itself serves, via ``routes.job_board.job_slug``),
  * nothing that could contact anybody survives — titles and locations go
    through the board's ``_scrub``/``_loc`` rules, and recruiter e-mail, phone
    and application URL are never read at all,
  * no crew profiles appear; the agency digest's anonymised crew teaser is a
    sales asset, not a public one.

Storage reuses the existing `articles` table as-is. The slug is deterministic
per ISO week (``superyacht-jobs-this-week-2026-w38``), so a re-run updates the
same row rather than publishing a duplicate, and the article appears at
``/articles``, in ``/articles/sitemap.xml`` and on the SSR page like any other.

The background loop is gated on the ``WEEKLY_DIGEST_ARTICLE_ENABLED`` env var
(default on), read with ``os.getenv`` here rather than through settings.py.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.logger import get_logger
from app.models import Article, Job
from app.routes.job_board import (
    OPEN_STATUS,
    _loc,
    _scrub_short,
    job_slug,
    salary_text,
)
from app.services.agency_digest import (
    ROLE_FAMILIES,
    ROLE_FAMILY_LABELS,
    build_digest,
    role_family_of,
)
from app.settings import settings

log = get_logger("carver.weekly_digest_article")


# ── Configuration ───────────────────────────────────────────────────────────

#: Env flag for the background loop. Lives here (os.getenv) rather than in
#: settings.py — move it into Settings when that file is next touched.
ENV_ENABLED = "WEEKLY_DIGEST_ARTICLE_ENABLED"

_TRUTHY = {"1", "true", "yes", "on"}

#: A week with almost nothing in it makes a thin page, which is worse than no
#: page at all for a site that wants to rank.
MIN_JOBS_FOR_ARTICLE = 5

#: Deterministic slug per ISO week — the whole idempotency story.
SLUG_PREFIX = "superyacht-jobs-this-week"

#: Let DB init and the first scrape settle before the first publish attempt.
BOOT_DELAY_SECONDS = 10 * 60
#: Re-check every 6h so a Monday 00:00 UTC week boundary is picked up same-day.
CHECK_INTERVAL_SECONDS = 6 * 60 * 60

# Mirrors the validation limits in routes/articles.py. Kept as local constants
# so a body built here can never be rejected by the article schema.
_MAX_TITLE = 200
_MAX_DESCRIPTION = 400
_MAX_LIST_ITEM = 500
_MAX_LIST_ITEMS = 20
_MAX_KEYWORDS = 20
_MAX_KEYWORD_LEN = 80

#: Hard ceiling on listed roles so a freak week cannot blow the 200-block cap.
_MAX_LISTED_JOBS = 180

_WEEK_RE = re.compile(r"^(\d{4})-W(\d{1,2})$", re.IGNORECASE)

_WHATSAPP_NUMBER = "27688516141"
#: Trailing token the WhatsApp backend reads for attribution — keep it last.
_WA_TAG = "· article"
_WA_PREFILL = f"Hi Carver — send me the superyacht jobs that match my ticket. {_WA_TAG}"


def _enabled() -> bool:
    return (os.getenv(ENV_ENABLED, "true") or "").strip().lower() in _TRUTHY


# ── Week helpers ────────────────────────────────────────────────────────────


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def normalise_week(week: str) -> str:
    """Canonical "YYYY-Www" (zero-padded) — raises ValueError on anything else."""
    match = _WEEK_RE.match((week or "").strip())
    if not match:
        raise ValueError("week must look like 2026-W38 (ISO year-week).")
    year, number = int(match.group(1)), int(match.group(2))
    try:
        datetime.fromisocalendar(year, number, 1)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO week: {week}.") from exc
    return f"{year}-W{number:02d}"


def week_window(week: str) -> tuple[datetime, datetime]:
    """ISO week -> [Monday 00:00 UTC, next Monday 00:00 UTC) — `until` exclusive."""
    canonical = normalise_week(week)
    year, number = int(canonical[:4]), int(canonical[6:])
    monday = datetime.fromisocalendar(year, number, 1).replace(tzinfo=timezone.utc)
    return monday, monday + timedelta(days=7)


def previous_completed_week(now: datetime | None = None) -> str:
    """The last ISO week that has fully finished.

    Seven days back always lands inside it: at Monday 00:00 of week W that is
    the Monday of W-1, and at Sunday 23:59 of W it is the Sunday of W-1.
    """
    moment = _as_utc(now) or datetime.now(timezone.utc)
    year, number, _ = (moment - timedelta(days=7)).isocalendar()
    return f"{year}-W{number:02d}"


def week_slug(week: str) -> str:
    """`superyacht-jobs-this-week-2026-w38` — stable, so re-runs upsert."""
    return f"{SLUG_PREFIX}-{normalise_week(week).lower()}"


# ── Public links ────────────────────────────────────────────────────────────


def _site_origin() -> str:
    base = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not base or base.startswith("http://localhost"):
        return "https://jobcarver.co"
    return base


def _public_url(path: str) -> str:
    """A link the article renderer will turn into an anchor.

    `_linkify` in routes/articles.py anchors both `https://…` runs and bare
    `jobcarver.co/…` runs. The bare form reads far better inside a list of 75
    roles, so it is preferred whenever the site really is jobcarver.co.
    """
    origin = _site_origin()
    host = origin.split("://", 1)[-1]
    return f"{host}{path}" if host == "jobcarver.co" else f"{origin}{path}"


def job_url(job: Job) -> str:
    """Public board URL for one job — same slug the board serves."""
    return _public_url(f"/jobs/board/{job_slug(job)}")


def board_url() -> str:
    return _public_url("/jobs/board")


def whatsapp_url() -> str:
    text = urllib.parse.quote(_WA_PREFILL, safe="")
    return f"https://wa.me/{_WHATSAPP_NUMBER}?text={text}"


# ── Formatting ──────────────────────────────────────────────────────────────


def _posted_day(value: datetime | None) -> str:
    when = _as_utc(value)
    return when.strftime("%a %-d %b") if when else ""


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


def _is_open(job: Job) -> bool:
    """Only `open` rows get a link — the board 410s everything else."""
    return (job.status or "").strip().lower() == OPEN_STATUS


def _job_line(job: Job) -> str:
    """`Title · Location · Salary · posted Mon 14 Sep · jobcarver.co/jobs/board/…`.

    Every field is scrubbed by the board's own helpers; recruiter e-mail, phone
    and application URL are not read at all.
    """
    bits = [_scrub_short(job.title or job.role, 120) or "Superyacht crew role"]
    location = _loc(job, 60)
    if location:
        bits.append(location)
    salary = salary_text(job)
    if salary:
        bits.append(salary)
    day = _posted_day(job.created_at)
    if day:
        bits.append(f"posted {day}")

    tail = job_url(job) if _is_open(job) else "no longer listed"
    head = " · ".join(bits)
    budget = _MAX_LIST_ITEM - len(tail) - 3
    if len(head) > budget:
        # Trim the prose, never the URL — a truncated link is a broken link.
        head = head[: max(0, budget)].rstrip(" ·")
    return f"{head} · {tail}"


def _ul_blocks(items: list[str]) -> list[dict]:
    """Split a role list into `ul` blocks that respect the 20-item cap."""
    return [
        {"type": "ul", "items": items[i : i + _MAX_LIST_ITEMS]}
        for i in range(0, len(items), _MAX_LIST_ITEMS)
    ]


def _counts_phrase(pairs: list[tuple[str, int]]) -> str:
    return ", ".join(f"{name} ({count})" for name, count in pairs)


# ── Data model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ArticleData:
    """Exactly the shape routes/articles.py stores — no new columns, no new table."""

    slug: str
    title: str
    description: str
    date: str
    read_minutes: int
    keywords: list[str]
    body: list[dict]
    week: str
    job_count: int
    published: bool = True

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "title": self.title,
            "description": self.description,
            "date": self.date,
            "read_minutes": self.read_minutes,
            "keywords": list(self.keywords),
            "body": [dict(block) for block in self.body],
            "published": self.published,
            "week": self.week,
            "job_count": self.job_count,
        }


# ── Build ───────────────────────────────────────────────────────────────────


def _window_jobs(db: Session, since: datetime, until: datetime) -> list[Job]:
    """Every job posted in the window, newest first — filled ones included.

    Same filter as `agency_digest._window_jobs`; the rows are re-read here
    because the public listing needs the real `Job` (for the board slug, the
    scrub rules and the open/filled split), not the digest's stripped copy.
    """
    return (
        db.query(Job)
        .filter(Job.created_at >= since, Job.created_at < until)
        .order_by(Job.created_at.desc(), Job.id.desc())
        .all()
    )


def _keywords(totals, period: str) -> list[str]:
    out = ["superyacht jobs", "yacht crew jobs", "superyacht jobs this week", period]
    out += [name for name, _ in totals.top_roles]
    out += [f"yacht jobs {name}" for name, _ in totals.top_locations]
    seen: set[str] = set()
    cleaned: list[str] = []
    for keyword in out:
        text = " ".join(str(keyword).split())[:_MAX_KEYWORD_LEN].strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        cleaned.append(text)
    return cleaned[:_MAX_KEYWORDS]


def _read_minutes(body: list[dict]) -> int:
    words = 0
    for block in body:
        if block.get("text"):
            words += len(block["text"].split())
        for item in block.get("items") or []:
            words += len(item.split())
    return max(2, min(12, round(words / 220) or 2))


def build_weekly_article(db: Session, week: str | None = None) -> ArticleData:
    """Build the public article for one ISO week. Pure read — writes nothing."""
    target = normalise_week(week) if week else previous_completed_week()
    since, until = week_window(target)

    # The digest supplies the week-on-week arithmetic and the top
    # locations/roles tallies; the rows supply the listing.
    digest = build_digest(db, since, until)
    rows = _window_jobs(db, since, until)[:_MAX_LISTED_JOBS]

    totals, previous = digest.totals, digest.previous
    period = digest.period
    count = totals.jobs
    plural = "s" if count != 1 else ""

    title = f"Superyacht jobs this week — {count} new role{plural} ({period})"[:_MAX_TITLE]

    body: list[dict] = []

    intro = (
        f"Carver logged {count} new superyacht crew role{plural} between {period}. "
        f"The week before had {previous.jobs} "
        f"({_signed(digest.jobs_delta)})."
    )
    if count:
        intro += (
            f" {totals.salary_pct}% of this week's posts published a salary "
            f"({totals.with_salary} of {count})."
        )
    body.append({"type": "p", "text": intro})
    body.append(
        {
            "type": "p",
            "text": (
                "Each role below links to its full listing on the Carver job board. "
                "Roles are listed as they were posted, including the ones that have "
                "already been filled — the point is what reached the market this week."
            ),
        }
    )

    grouped: dict[str, list[Job]] = {family: [] for family in ROLE_FAMILIES}
    for job in rows:
        grouped[role_family_of(job)].append(job)

    listed = 0
    for family in ROLE_FAMILIES:
        items = grouped[family]
        if not items:
            continue
        listed += len(items)
        body.append({"type": "h2", "text": f"{ROLE_FAMILY_LABELS[family]} ({len(items)})"})
        body += _ul_blocks([_job_line(job) for job in items])

    if not listed:
        body.append(
            {
                "type": "h2",
                "text": "No roles were posted this week",
            }
        )
        body.append(
            {
                "type": "p",
                "text": (
                    "Nothing new reached the market in this window. The open roles "
                    f"from earlier weeks are still on the board at {board_url()}."
                ),
            }
        )

    # ── Where the jobs are ──
    body.append({"type": "h2", "text": "Where the jobs are"})
    where_bits: list[str] = []
    if totals.top_locations:
        where_bits.append(
            "The most-posted locations this week were "
            f"{_counts_phrase(totals.top_locations)}."
        )
    if totals.top_roles:
        where_bits.append(
            f"The most-posted roles were {_counts_phrase(totals.top_roles)}."
        )
    if not where_bits:
        where_bits.append("No location or role stood out in this window.")
    open_now = sum(1 for job in rows if _is_open(job))
    where_bits.append(
        f"{open_now} of the {len(rows)} role{'s' if len(rows) != 1 else ''} listed here "
        "were still open when this page was built."
        if rows
        else "Nothing from this week is still listed."
    )
    body.append({"type": "p", "text": " ".join(where_bits)})

    # ── Closing CTA ──
    body.append({"type": "h2", "text": "Get the roles that match your ticket"})
    body.append(
        {
            "type": "p",
            "text": (
                "Every open role above sits on the public board at "
                f"{board_url()}, with the full post and no login."
            ),
        }
    )
    body.append(
        {
            "type": "p",
            "text": (
                "To get only the roles that fit your ticket, experience and dates, "
                f"message Carver on WhatsApp: {whatsapp_url()}. It asks for your role, "
                "ticket and availability, then sends the matches. The first five match "
                "runs are free and no card is needed. Recruiter contact details are "
                "never published on these pages."
            ),
        }
    )

    description = (
        f"The {count} superyacht crew role{plural} posted between {period} — deck, "
        "interior, galley and engineering, each with location, salary where stated "
        "and a link to the full listing."
    )[:_MAX_DESCRIPTION]

    return ArticleData(
        slug=week_slug(target),
        title=title,
        description=description,
        date=until.date().isoformat(),
        read_minutes=_read_minutes(body),
        keywords=_keywords(totals, period),
        body=body,
        week=target,
        job_count=count,
    )


# ── Publish ─────────────────────────────────────────────────────────────────


def publish_weekly_article(
    db: Session,
    week: str | None = None,
    *,
    min_jobs: int = MIN_JOBS_FOR_ARTICLE,
    skip_if_exists: bool = False,
) -> Article | None:
    """Upsert the week's article. Idempotent — the slug is derived from the week.

    Returns the stored row, or None when the week was skipped (too thin, or
    already published and `skip_if_exists`).
    """
    target = normalise_week(week) if week else previous_completed_week()
    slug = week_slug(target)

    row = db.query(Article).filter(Article.slug == slug).first()
    if row is not None and skip_if_exists:
        log.info("Weekly jobs article already published | week=%s | slug=%s", target, slug)
        return None

    data = build_weekly_article(db, target)
    if data.job_count < min_jobs:
        log.info(
            "Weekly jobs article skipped | week=%s | jobs=%d < min=%d | "
            "too thin to publish as an indexable page",
            target,
            data.job_count,
            min_jobs,
        )
        return None

    created = row is None
    if row is None:
        row = Article(slug=slug)
        db.add(row)

    row.title = data.title
    row.description = data.description
    row.date = data.date
    row.read_minutes = data.read_minutes
    row.keywords_json = json.dumps(data.keywords)
    row.body_json = json.dumps(data.body)
    row.published = data.published

    db.commit()
    db.refresh(row)
    log.info(
        "Weekly jobs article %s | week=%s | slug=%s | jobs=%d",
        "created" if created else "updated",
        target,
        slug,
        data.job_count,
    )
    return row


def run_weekly_digest_article_once(week: str | None = None) -> Article | None:
    """One publish attempt against a fresh session — what the loop calls."""
    db = SessionLocal()
    try:
        return publish_weekly_article(db, week, skip_if_exists=True)
    finally:
        db.close()


async def weekly_digest_article_loop() -> None:
    """Background asyncio task started at API startup.

    Publishes the previous completed ISO week once, then re-checks every 6h so
    the Monday 00:00 UTC boundary is never missed by more than one cycle.
    """
    if not _enabled():
        log.info("Weekly jobs article loop disabled (%s=false)", ENV_ENABLED)
        return

    await asyncio.sleep(BOOT_DELAY_SECONDS)
    while True:
        try:
            await asyncio.to_thread(run_weekly_digest_article_once)
        except Exception as exc:  # never let a bad week kill the loop
            log.error("Weekly jobs article publish failed | error=%s", exc)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)


# ── Debug renderer ──────────────────────────────────────────────────────────


def render_markdown(data: ArticleData) -> str:
    """Plain markdown of the stored blocks — for previewing a week in a shell."""
    lines: list[str] = [f"# {data.title}", "", f"_{data.description}_", ""]
    for block in data.body:
        if block.get("type") == "h2":
            lines += [f"## {block['text']}", ""]
        elif block.get("type") == "p":
            lines += [block["text"], ""]
        elif block.get("type") == "ul":
            lines += [f"- {item}" for item in block.get("items") or []]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"
