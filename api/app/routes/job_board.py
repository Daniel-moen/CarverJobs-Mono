"""
Public job board — the SEO acquisition surface.

Public (no auth), all server-rendered so crawlers and social previewers get
the full content in the initial response:

  GET /jobs/board              — index of every OPEN job, newest first.
  GET /jobs/board/{id-or-slug} — one open job (JSON-LD JobPosting + OG tags).
  GET /jobs/sitemap.xml        — the board plus every open job URL.

These are reached publicly at ``/jobs/board`` … via nginx proxy locations,
mirroring how ``/articles`` is proxied to ``/articles/list.html`` (see the
website nginx config). Canonical URLs therefore point at the public origin,
never at the API host.

Safety rules — this content is scraped from Facebook, so it is hostile input:

  * Every value is HTML-escaped before it is inlined, and the JSON-LD payload
    has every "</" escaped so it cannot break out of the <script> element.
  * Recruiter contact details are NEVER rendered. `contact_email`,
    `application_url`, `recruiter_name` and `recruiter_agency` are not read
    for public output at all, and free-text fields are additionally scrubbed
    of e-mail addresses, URLs and phone-like digit runs, because scraped posts
    routinely repeat the contact details inside the body. Applying goes
    through the WhatsApp CTA; contact details stay on the paid product surface.
  * Only `status == "open"` rows are exposed. A job that exists but is no
    longer open returns 410 Gone with a link back to the board, which is the
    correct SEO signal for a filled role; an unknown id returns 404.

No JavaScript is served on these pages (only the JSON-LD data block), so they
are fast on the phones the audience actually uses. Attribution happens in the
WhatsApp prefill, which always ends in " · jobboard".
"""

import html
import json
import re
import urllib.parse
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.orm import Session

from app.database import get_db
from app.logger import get_logger
from app.models import Job
from app.settings import settings

log = get_logger("carver.job_board")
_limiter = Limiter(key_func=get_remote_address)

# Registered BEFORE `routes.jobs.router` in main.py: that router owns the
# generic `/jobs/{job_id}` path, and Starlette matches routes in registration
# order, so `/jobs/board` and `/jobs/sitemap.xml` must come first.
public_router = APIRouter(prefix="/jobs", tags=["job-board"])


# ── Constants ───────────────────────────────────────────────────────────────

#: Public WhatsApp business number (E.164 digits, no "+").
WHATSAPP_NUMBER = "27688516141"
#: Suffix parsed into `WhatsAppSession.acquisition_source` (max 40 chars).
CTA_SOURCE = "jobboard"

OPEN_STATUS = "open"

_MAX_BOARD_ROWS = 300
_MAX_SITEMAP_ROWS = 2000
_MAX_RELATED = 6
_MAX_PREFILL_CHARS = 180
_MAX_DESCRIPTION_CHARS = 4000
_MAX_PARAGRAPHS = 40

_REDACTED = "[hidden — apply via WhatsApp]"

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+\s?@\s?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_URL_RE = re.compile(r"\b(?:https?://|www\.)\S+", re.IGNORECASE)
# Digit runs that look like a phone number. Applied with a callback so short
# runs (salary bands like "3500-4500", dates like "2026-05-01") survive.
_PHONE_RE = re.compile(r"\+?\d[\d\s().\-]{6,}\d")
_PHONE_MIN_DIGITS = 9

_SLUG_CHARS_RE = re.compile(r"[^a-z0-9]+")
# "chief-stewardess-antibes-42", or a bare "42".
_JOB_REF_RE = re.compile(r"^(?:[a-z0-9]+(?:-[a-z0-9]+)*-)?(\d{1,12})$")

_EMPLOYMENT_TYPES = {
    "permanent": "FULL_TIME",
    "full time": "FULL_TIME",
    "full-time": "FULL_TIME",
    "rotational": "FULL_TIME",
    "rotation": "FULL_TIME",
    "seasonal": "TEMPORARY",
    "season": "TEMPORARY",
    "temporary": "TEMPORARY",
    "temp": "TEMPORARY",
    "daywork": "TEMPORARY",
    "day work": "TEMPORARY",
    "relief": "TEMPORARY",
    "freelance": "CONTRACTOR",
    "contract": "CONTRACTOR",
    "part time": "PART_TIME",
    "part-time": "PART_TIME",
}


# ── Text helpers ────────────────────────────────────────────────────────────

def _site_origin() -> str:
    base = (settings.FRONTEND_BASE_URL or "").strip().rstrip("/")
    if not base or base.startswith("http://localhost"):
        return "https://jobcarver.co"
    return base


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


def _redact_phone(match: re.Match) -> str:
    digits = sum(1 for ch in match.group(0) if ch.isdigit())
    return _REDACTED if digits >= _PHONE_MIN_DIGITS else match.group(0)


def _scrub(value: str | None) -> str:
    """Strip contact routes out of scraped free text before it is published.

    Removes e-mail addresses, URLs and phone-like digit runs. Scraped Facebook
    posts repeat the recruiter's contact details inside the body, and those
    belong to the paid surface, not to a public indexable page.
    """
    if not value:
        return ""
    text = _EMAIL_RE.sub(_REDACTED, str(value))
    text = _URL_RE.sub(_REDACTED, text)
    text = _PHONE_RE.sub(_redact_phone, text)
    return text.strip()


def _scrub_short(value: str | None, limit: int = 160) -> str:
    """Scrub a single-line field (title, role, location) and collapse space."""
    text = " ".join(_scrub(value).split())
    return text[:limit].strip()


def _slugify(value: str | None, limit: int = 60) -> str:
    slug = _SLUG_CHARS_RE.sub("-", (value or "").lower()).strip("-")
    return slug[:limit].strip("-")


def job_slug(job: Job) -> str:
    """Stable, human-readable slug: role-location-id."""
    parts = [p for p in (_slugify(job.role, 48), _slugify(job.location, 40)) if p]
    parts.append(str(job.id))
    return "-".join(parts)


def _parse_job_ref(ref: str) -> int | None:
    """Accept `42` or `chief-stew-antibes-42`; return the trailing id."""
    match = _JOB_REF_RE.match((ref or "").strip().lower())
    if not match:
        return None
    try:
        job_id = int(match.group(1))
    except ValueError:
        return None
    return job_id if job_id > 0 else None


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def posted_ago(created_at: datetime | None, *, now: datetime | None = None) -> str:
    """Human relative age, e.g. "3 days ago"."""
    when = _as_utc(created_at)
    if when is None:
        return ""
    current = _as_utc(now) or datetime.now(timezone.utc)
    seconds = max(0.0, (current - when).total_seconds())
    days = int(seconds // 86400)
    if days < 1:
        hours = int(seconds // 3600)
        if hours < 1:
            return "just now"
        return "1 hour ago" if hours == 1 else f"{hours} hours ago"
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days} days ago"
    months = days // 30
    return "1 month ago" if months == 1 else f"{months} months ago"


def _iso_date(value: datetime | None) -> str:
    when = _as_utc(value)
    return when.date().isoformat() if when else ""


def _money(amount: float) -> str:
    return f"{int(round(amount)):,}"


def _currency(job: Job) -> str:
    code = "".join(ch for ch in (job.salary_currency or "") if ch.isalpha()).upper()
    return code[:6] or "EUR"


def salary_text(job: Job) -> str:
    """Display salary, or "" when the scrape produced no usable figure."""
    code = _currency(job)
    low = job.salary_min if job.salary_min and job.salary_min > 0 else None
    high = job.salary_max if job.salary_max and job.salary_max > 0 else None
    if low and high and high > low:
        return f"{code} {_money(low)}–{_money(high)} / month"
    if low:
        return f"{code} {_money(low)} / month"
    if high:
        return f"{code} up to {_money(high)} / month"
    return ""


def _join_bits(bits: list[str]) -> str:
    """Join the non-empty display fragments with a middot separator."""
    return " · ".join(bit for bit in bits if bit)


def _paragraphs(value: str | None) -> list[str]:
    """Scrubbed free text split into paragraphs, capped for page weight."""
    text = _scrub(value)[:_MAX_DESCRIPTION_CHARS]
    if not text:
        return []
    out = [" ".join(line.split()) for line in text.splitlines()]
    return [line for line in out if line][:_MAX_PARAGRAPHS]


def _bullets(value: str | None) -> list[str]:
    """Requirements-style text as list items (one per line or bullet char)."""
    text = _scrub(value)[:_MAX_DESCRIPTION_CHARS]
    if not text:
        return []
    raw = re.split(r"[\n\r]+|(?:^|\s)[•·*•]\s*", text)
    items = [" ".join(part.split()) for part in raw]
    return [item for item in items if item][:_MAX_PARAGRAPHS]


# ── CTA helpers ─────────────────────────────────────────────────────────────

def whatsapp_link(message: str) -> str:
    """wa.me deep link whose prefill always ends in " · jobboard"."""
    body = " ".join((message or "").split())[:_MAX_PREFILL_CHARS].strip()
    text = f"{body} · {CTA_SOURCE}" if body else f"Hi Carver · {CTA_SOURCE}"
    return f"https://wa.me/{WHATSAPP_NUMBER}?text={urllib.parse.quote(text)}"


def _job_whatsapp_link(job: Job) -> str:
    title = _scrub_short(job.title or job.role, 90)
    location = _scrub_short(job.location, 40)
    where = f" in {location}" if location else ""
    return whatsapp_link(f"Hi Carver, I'd like to apply for {title}{where} (ref {job.id})")


_BOARD_WHATSAPP_LINK_TEXT = "Hi Carver, I'm looking for superyacht work — send me matching jobs"


# ── Query helpers ───────────────────────────────────────────────────────────

def _open_jobs_query(db: Session):
    """Open rows only, newest first (shared by board, detail links, sitemap)."""
    return (
        db.query(Job)
        .filter(Job.status == OPEN_STATUS)
        .order_by(Job.created_at.desc(), Job.id.desc())
    )


# ── Shared chrome ───────────────────────────────────────────────────────────
#
# Mobile-first: a single column, 16px gutters, tap targets ≥44px, and the
# same dark brass palette the article pages use.

_STYLES = """
      :root { --bg:#05080c; --text:#e8e6e1; --muted:#8a8378; --brass:#d4b97a; --border:rgba(255,255,255,0.06); --wa:#25d366; }
      *,*::before,*::after { box-sizing: border-box; }
      html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing: antialiased; overflow-wrap:break-word; }
      a { color: var(--brass); }
      .nav { max-width:1280px; margin:0 auto; padding:1rem 1rem; display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border); }
      .brand { text-decoration:none; color:var(--text); font-weight:600; letter-spacing:0.04em; font-size:0.9rem; }
      .nav-links a { margin-left:0.9rem; color:var(--muted); text-decoration:none; font-size:0.85rem; }
      .nav-links a:hover { color: var(--text); }
      main { max-width:760px; margin:0 auto; padding:2rem 1rem 4rem; }
      .eyebrow { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--brass); margin:0; }
      h1 { margin:0.75rem 0 0; font-family: Georgia, "Times New Roman", serif; font-weight:300; font-size:clamp(1.75rem, 6vw, 2.6rem); line-height:1.08; letter-spacing:-0.025em; color:var(--text); }
      .lede { margin:1rem 0 0; color:var(--muted); font-size:1rem; line-height:1.6; max-width:36rem; }
      .crumbs { font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--muted); margin:0 0 1.25rem; }
      .crumbs a { color:inherit; text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.18); }
      .list { list-style:none; margin:2rem 0 0; padding:0; display:grid; gap:0.85rem; }
      .card { border:1px solid var(--border); border-radius:14px; transition: border-color 0.2s ease, background 0.2s ease; }
      .card:hover { border-color: rgba(212,185,122,0.35); background: rgba(212,185,122,0.04); }
      .card a { display:block; padding:1.1rem 1.15rem 1.2rem; text-decoration:none; color:inherit; min-height:44px; }
      .meta { margin:0 0 0.4rem; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:11px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted); }
      .card h2 { margin:0; font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.2rem; line-height:1.3; letter-spacing:-0.015em; color:var(--text); }
      .facts { margin:0.6rem 0 0; padding:0; list-style:none; display:flex; flex-wrap:wrap; gap:0.4rem 0.9rem; color:var(--muted); font-size:0.88rem; }
      .facts li { margin:0; }
      .salary { color:var(--brass); }
      .go { display:inline-block; margin-top:0.85rem; font-size:12.5px; color: var(--brass); }
      .cta-block { margin:2rem 0 0; padding:1.15rem 1.15rem 1.25rem; border:1px solid rgba(37,211,102,0.28); border-radius:14px; background:rgba(37,211,102,0.06); }
      .cta-block p { margin:0.6rem 0 0; color:var(--muted); font-size:0.9rem; line-height:1.55; }
      .cta-title { margin:0; font-size:0.95rem; color:var(--text); font-weight:600; }
      .cta-wa { display:block; margin-top:0.9rem; padding:0.95rem 1rem; min-height:48px; border-radius:11px; background:var(--wa); color:#04140a; text-align:center; text-decoration:none; font-weight:700; font-size:1rem; }
      .cta-wa:hover { filter:brightness(1.06); }
      .cta-second { display:block; margin-top:0.7rem; padding:0.8rem 1rem; min-height:44px; border-radius:11px; border:1px solid var(--border); color:var(--text); text-align:center; text-decoration:none; font-size:0.92rem; }
      .cta-second:hover { border-color: rgba(212,185,122,0.35); color:var(--brass); }
      .detail dl { margin:1.75rem 0 0; padding:0; display:grid; grid-template-columns:1fr; gap:0.75rem; }
      .detail dt { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size:11px; letter-spacing:0.12em; text-transform:uppercase; color:var(--muted); }
      .detail dd { margin:0.2rem 0 0; color:var(--text); font-size:0.98rem; }
      .section { margin-top:2.25rem; }
      .section h2 { font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.2rem; margin:0 0 0.75rem; color:var(--text); }
      .section p { margin:0 0 0.9rem; color:var(--muted); line-height:1.7; }
      .section ul { margin:0 0 1rem; padding-left:1.15rem; color:var(--muted); line-height:1.65; }
      .section li { margin:0.3rem 0; }
      .note { margin-top:1.5rem; color:var(--muted); font-size:0.82rem; line-height:1.55; }
      .more { margin-top:2.5rem; padding-top:1.5rem; border-top:1px solid var(--border); }
      .more h2 { font-family: Georgia, "Times New Roman", serif; font-weight:400; font-size:1.1rem; margin:0 0 1rem; }
      .more ul { list-style:none; padding:0; margin:0; display:grid; gap:0.6rem; }
      .more li { border:1px solid var(--border); border-radius:10px; }
      .more a { display:block; padding:0.8rem 0.95rem; color:var(--text); text-decoration:none; font-size:0.95rem; }
      .more a:hover { color:var(--brass); }
      .more .where { display:block; margin-top:0.25rem; color:var(--muted); font-size:0.82rem; }
      .foot { margin-top:2.5rem; padding-top:1.5rem; border-top:1px solid var(--border); }
      .back { color:var(--muted); font-size:0.85rem; text-decoration:none; border-bottom:1px dashed rgba(255,255,255,0.18); }
      .back:hover { color: var(--text); }
      .empty { color: var(--muted); font-size:1rem; }
      @media (min-width: 640px) { .detail dl { grid-template-columns:repeat(2, minmax(0,1fr)); gap:1rem 1.5rem; } main { padding:3rem 1.5rem 5rem; } .nav { padding:1rem 1.5rem; } }
"""

_NAV = """    <nav class="nav" aria-label="Primary">
      <a class="brand" href="/">CARVER</a>
      <div class="nav-links">
        <a href="/">Home</a>
        <a href="/jobs/board">Jobs</a>
        <a href="/articles">Articles</a>
      </div>
    </nav>"""


def _json_ld_block(payload: dict) -> str:
    """Serialise a JSON-LD payload that cannot escape its <script> element.

    `<`, `>` and `&` are emitted as JSON `\\uXXXX` escapes, so no scraped
    string can produce `</script>` (or an HTML entity) in the output. Parsers
    unescape them transparently.
    """
    safe = (
        json.dumps(payload, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    return f'<script type="application/ld+json">{safe}</script>'


def _cta_block(*, title: str, blurb: str, wa_href: str, wa_label: str) -> str:
    return f"""      <section class="cta-block" aria-label="Apply">
        <p class="cta-title">{_esc(title)}</p>
        <p>{_esc(blurb)}</p>
        <a class="cta-wa" href="{_esc(wa_href)}" rel="nofollow noopener" target="_blank">{_esc(wa_label)}</a>
        <a class="cta-second" href="/signup">Or sign up for job matches by role &amp; location</a>
      </section>"""


def _head(
    *,
    title: str,
    description: str,
    canonical: str,
    og_type: str,
    json_ld: str = "",
    robots: str = "index, follow, max-image-preview:large, max-snippet:-1",
) -> str:
    origin = _site_origin()
    title_html = _esc(title)
    description_html = _esc(description)
    return f"""  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover" />
    <title>{title_html}</title>
    <meta name="description" content="{description_html}" />
    <meta name="author" content="Carver" />
    <meta name="robots" content="{_esc(robots)}" />
    <meta name="theme-color" content="#05080c" />
    <meta name="color-scheme" content="dark" />
    <link rel="canonical" href="{_esc(canonical)}" />
    <link rel="icon" href="/favicon.svg" type="image/svg+xml" />
    <meta property="og:type" content="{_esc(og_type)}" />
    <meta property="og:site_name" content="Carver" />
    <meta property="og:title" content="{title_html}" />
    <meta property="og:description" content="{description_html}" />
    <meta property="og:url" content="{_esc(canonical)}" />
    <meta property="og:image" content="{_esc(origin)}/og-image.svg" />
    <meta property="og:locale" content="en_GB" />
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{title_html}" />
    <meta name="twitter:description" content="{description_html}" />
    <meta name="twitter:image" content="{_esc(origin)}/og-image.svg" />
    {json_ld}
    <style>{_STYLES}    </style>
  </head>"""


# ── Board (index) ───────────────────────────────────────────────────────────

def _render_board_html(rows: list[Job], *, now: datetime | None = None) -> str:
    origin = _site_origin()
    canonical = f"{origin}/jobs/board"
    count = len(rows)
    page_title = "Superyacht jobs — live crew vacancies | Carver"
    description = (
        f"{count} open superyacht crew jobs" if count else "Open superyacht crew jobs"
    ) + " — deckhand, stewardess, engineer, chef and captain roles. Apply on WhatsApp in seconds."

    if rows:
        cards: list[str] = []
        for job in rows:
            href = f"/jobs/board/{job_slug(job)}"
            title = _scrub_short(job.title or job.role, 140) or "Superyacht crew role"
            role = _scrub_short(job.role, 60)
            location = _scrub_short(job.location, 60)
            salary = salary_text(job)
            posted = posted_ago(job.created_at, now=now)
            facts = []
            if role:
                facts.append(f"<li>{_esc(role)}</li>")
            if location:
                facts.append(f"<li>{_esc(location)}</li>")
            if salary:
                facts.append(f'<li class="salary">{_esc(salary)}</li>')
            facts_html = (
                f'<ul class="facts">{"".join(facts)}</ul>' if facts else ""
            )
            cards.append(
                f'<li class="card">'
                f'<a href="{_esc(href)}">'
                f'<p class="meta">{_esc(posted)}</p>'
                f"<h2>{_esc(title)}</h2>"
                f"{facts_html}"
                f'<span class="go">View role &amp; apply &rarr;</span>'
                f"</a></li>"
            )
        list_html = "\n        ".join(cards)
        body_block = (
            f'<ul class="list" aria-label="Open superyacht jobs">\n        '
            f"{list_html}\n      </ul>"
        )
    else:
        body_block = (
            '<p class="empty">No open roles are listed right now. New vacancies land '
            "every day — message us on WhatsApp and we&rsquo;ll ping you the moment "
            "one matches your ticket.</p>"
        )

    json_ld = _json_ld_block(
        {
            "@context": "https://schema.org",
            "@type": "CollectionPage",
            "name": "Superyacht jobs",
            "description": "Live superyacht crew vacancies listed by Carver.",
            "url": canonical,
            "mainEntity": {
                "@type": "ItemList",
                "numberOfItems": count,
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": i + 1,
                        "url": f"{origin}/jobs/board/{job_slug(job)}",
                        "name": _scrub_short(job.title or job.role, 140)
                        or "Superyacht crew role",
                    }
                    for i, job in enumerate(rows)
                ],
            },
        }
    )

    cta = _cta_block(
        title="Apply in one message",
        blurb=(
            "Carver's WhatsApp bot takes your role, ticket and availability, then "
            "sends you only the jobs that fit. No CV upload, no account needed to start."
        ),
        wa_href=whatsapp_link(_BOARD_WHATSAPP_LINK_TEXT),
        wa_label="Apply via WhatsApp",
    )

    return f"""<!doctype html>
<html lang="en">
{_head(title=page_title, description=description, canonical=canonical, og_type="website", json_ld=json_ld)}
  <body>
{_NAV}
    <main>
      <p class="eyebrow">Carver job board</p>
      <h1>Live superyacht crew jobs</h1>
      <p class="lede">Every open role Carver is tracking right now, newest first. Deck, interior, galley and engineering — apply through WhatsApp in one message.</p>
{cta}
      {body_block}
      <p class="note">Carver sources roles from public crew networks and verifies them before listing. Recruiter contact details are never published here — apply through WhatsApp and Carver forwards your details to the right person.</p>
    </main>
  </body>
</html>
"""


# ── Detail page ─────────────────────────────────────────────────────────────

def _employment_type(job: Job) -> str | None:
    key = (job.contract_type or "").strip().lower()
    if not key:
        return None
    return _EMPLOYMENT_TYPES.get(key)


def _job_json_ld(job: Job, canonical: str, description_text: str) -> dict:
    origin = _site_origin()
    posted = _iso_date(job.created_at)
    payload: dict = {
        "@context": "https://schema.org",
        "@type": "JobPosting",
        "title": _scrub_short(job.title or job.role, 140) or "Superyacht crew role",
        "description": description_text
        or _scrub_short(job.title or job.role, 140)
        or "Superyacht crew role",
        "identifier": {
            "@type": "PropertyValue",
            "name": "Carver",
            "value": str(job.id),
        },
        "hiringOrganization": {
            "@type": "Organization",
            "name": "Carver",
            "sameAs": origin,
        },
        "url": canonical,
        "directApply": False,
    }
    if posted:
        payload["datePosted"] = posted
        expires = _as_utc(job.created_at)
        if expires:
            payload["validThrough"] = (
                expires + timedelta(days=settings.JOB_EXPIRE_AFTER_DAYS)
            ).date().isoformat()
    location = _scrub_short(job.location, 120)
    if location:
        payload["jobLocation"] = {
            "@type": "Place",
            "address": {"@type": "PostalAddress", "addressLocality": location},
        }
    employment = _employment_type(job)
    if employment:
        payload["employmentType"] = employment
    low = job.salary_min if job.salary_min and job.salary_min > 0 else None
    high = job.salary_max if job.salary_max and job.salary_max > 0 else None
    if low or high:
        value: dict = {"@type": "QuantitativeValue", "unitText": "MONTH"}
        if low and high and high > low:
            value["minValue"] = round(float(low), 2)
            value["maxValue"] = round(float(high), 2)
        else:
            value["value"] = round(float(low or high), 2)
        payload["baseSalary"] = {
            "@type": "MonetaryAmount",
            "currency": _currency(job),
            "value": value,
        }
    if job.experience_required_years:
        payload["experienceRequirements"] = {
            "@type": "OccupationalExperienceRequirements",
            "monthsOfExperience": int(job.experience_required_years) * 12,
        }
    return payload


def _render_job_html(
    job: Job, related: list[Job], *, now: datetime | None = None
) -> str:
    origin = _site_origin()
    slug = job_slug(job)
    canonical = f"{origin}/jobs/board/{slug}"

    title = _scrub_short(job.title or job.role, 140) or "Superyacht crew role"
    role = _scrub_short(job.role, 80)
    location = _scrub_short(job.location, 80)
    salary = salary_text(job)
    posted = posted_ago(job.created_at, now=now)
    posted_iso = _iso_date(job.created_at)

    description_paras = _paragraphs(job.description)
    description_text = " ".join(description_paras)
    requirement_items = _bullets(job.requirements)
    responsibility_items = _bullets(job.responsibilities)

    # Search snippets must not be a wall of "[hidden …]" markers, so the
    # redaction marker is dropped (not just escaped) for the meta description,
    # and a facts summary is used when little readable text is left.
    snippet = " ".join(description_text.replace(_REDACTED, " ").split())[:180].strip()
    summary = _join_bits([role, location, salary]) + " — apply via WhatsApp with Carver."
    meta_description = snippet if len(snippet) >= 60 else summary
    page_title = " — ".join(part for part in (title, location, "Carver") if part)
    lede_text = _join_bits([role, location, salary or "Salary not disclosed"])

    facts: list[str] = []

    def _fact(label: str, value: str) -> None:
        if value:
            facts.append(f"<div><dt>{_esc(label)}</dt><dd>{_esc(value)}</dd></div>")

    _fact("Role", role)
    _fact("Location", location)
    _fact("Salary", salary or "Not disclosed")
    _fact("Posted", posted)
    _fact("Start", _scrub_short(job.start_date, 60))
    _fact("Contract", _scrub_short(job.contract_type, 60))
    _fact("Rotation", _scrub_short(job.rotation, 60))
    _fact("Vessel", _scrub_short(job.yacht_type, 60))
    _fact("Department", _scrub_short(job.department, 60))
    _fact(
        "Experience",
        f"{int(job.experience_required_years)}+ years"
        if job.experience_required_years
        else "",
    )
    _fact("Minimum licence", _scrub_short(job.minimum_license, 120))
    _fact("Languages", _scrub_short(job.languages_required, 120))
    facts_html = f'<dl>{"".join(facts)}</dl>' if facts else ""

    sections: list[str] = []
    if description_paras:
        paras = "".join(f"<p>{_esc(p)}</p>" for p in description_paras)
        sections.append(
            f'<section class="section"><h2>About the role</h2>{paras}</section>'
        )
    if responsibility_items:
        items = "".join(f"<li>{_esc(i)}</li>" for i in responsibility_items)
        sections.append(
            f'<section class="section"><h2>Responsibilities</h2><ul>{items}</ul></section>'
        )
    if requirement_items:
        items = "".join(f"<li>{_esc(i)}</li>" for i in requirement_items)
        sections.append(
            f'<section class="section"><h2>Requirements</h2><ul>{items}</ul></section>'
        )
    certs = _bullets(job.certifications_required)
    if certs:
        items = "".join(f"<li>{_esc(i)}</li>" for i in certs)
        sections.append(
            f'<section class="section"><h2>Certificates</h2><ul>{items}</ul></section>'
        )
    sections_html = "\n        ".join(sections)

    related_html = ""
    if related:
        related_items: list[str] = []
        for other in related:
            other_href = _esc("/jobs/board/" + job_slug(other))
            other_title = _esc(
                _scrub_short(other.title or other.role, 120) or "Superyacht crew role"
            )
            other_where = _esc(
                _join_bits([_scrub_short(other.location, 60), salary_text(other)])
            )
            related_items.append(
                f'<li><a href="{other_href}">{other_title}'
                f'<span class="where">{other_where}</span></a></li>'
            )
        items = "".join(related_items)
        related_html = (
            '\n        <aside class="more" aria-label="More open roles">'
            f"<h2>More open roles</h2><ul>{items}</ul></aside>"
        )

    cta = _cta_block(
        title="Apply via WhatsApp",
        blurb=(
            "Tap below and Carver's bot picks it up straight away — it checks your "
            "ticket and experience against this role and puts you forward. "
            "Recruiter contact details stay private."
        ),
        wa_href=_job_whatsapp_link(job),
        wa_label="Apply via WhatsApp",
    )

    json_ld = _json_ld_block(_job_json_ld(job, canonical, description_text))
    time_html = (
        f'<time datetime="{_esc(posted_iso)}">{_esc(posted)}</time>'
        if posted_iso
        else _esc(posted)
    )

    return f"""<!doctype html>
<html lang="en">
{_head(title=page_title, description=meta_description, canonical=canonical, og_type="article", json_ld=json_ld)}
  <body>
{_NAV}
    <main class="detail">
      <article>
        <p class="crumbs">
          <a href="/jobs/board">Superyacht jobs</a> &middot; {time_html}
        </p>
        <h1>{_esc(title)}</h1>
        <p class="lede">{_esc(lede_text)}</p>
{cta}
        {facts_html}
        {sections_html}{related_html}
        <p class="note">Carver never publishes recruiter e-mail addresses or phone numbers. Apply through WhatsApp and your application goes straight to the right person.</p>
        <footer class="foot">
          <a class="back" href="/jobs/board">&larr; All open jobs</a>
        </footer>
      </article>
    </main>
  </body>
</html>
"""


def _render_status_page(
    *, status_title: str, heading: str, message: str, canonical_path: str = "/jobs/board"
) -> str:
    origin = _site_origin()
    canonical = f"{origin}{canonical_path}"
    return f"""<!doctype html>
<html lang="en">
{_head(title=f"{status_title} — Carver", description=message, canonical=canonical, og_type="website", robots="noindex, follow")}
  <body>
{_NAV}
    <main>
      <p class="eyebrow">Carver job board</p>
      <h1>{_esc(heading)}</h1>
      <p class="lede">{_esc(message)}</p>
      <p style="margin-top:2rem"><a class="cta-second" href="/jobs/board">Browse all open superyacht jobs</a></p>
      <p style="margin-top:0.7rem"><a class="cta-wa" href="{_esc(whatsapp_link(_BOARD_WHATSAPP_LINK_TEXT))}" rel="nofollow noopener" target="_blank">Get matched on WhatsApp</a></p>
    </main>
  </body>
</html>
"""


# ── Sitemap ─────────────────────────────────────────────────────────────────

def _render_sitemap(rows: list[Job]) -> str:
    origin = _site_origin()
    parts: list[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        "  <url>",
        f"    <loc>{html.escape(origin)}/jobs/board</loc>",
        "    <changefreq>daily</changefreq>",
        "    <priority>0.9</priority>",
        "  </url>",
    ]
    for job in rows:
        loc = f"{origin}/jobs/board/{job_slug(job)}"
        lastmod = _iso_date(job.updated_at) or _iso_date(job.created_at)
        parts.append("  <url>")
        parts.append(f"    <loc>{html.escape(loc)}</loc>")
        if lastmod:
            parts.append(f"    <lastmod>{html.escape(lastmod)}</lastmod>")
        parts.append("    <changefreq>daily</changefreq>")
        parts.append("    <priority>0.7</priority>")
        parts.append("  </url>")
    parts.append("</urlset>")
    parts.append("")
    return "\n".join(parts)


# ── Endpoints ───────────────────────────────────────────────────────────────
#
# `/board` and `/sitemap.xml` are literal paths; this router is registered
# before `routes.jobs.router` so its `/jobs/{job_id}` route cannot swallow them.

@public_router.get("/board", include_in_schema=False)
@_limiter.limit("60/minute")
def job_board_page(request: Request, db: Session = Depends(get_db)):
    """SSR HTML index of every open job. Proxied from `/jobs/board` by nginx."""
    rows = _open_jobs_query(db).limit(_MAX_BOARD_ROWS).all()
    return HTMLResponse(content=_render_board_html(rows))


@public_router.get("/sitemap.xml", include_in_schema=False)
@_limiter.limit("60/minute")
def job_board_sitemap(request: Request, db: Session = Depends(get_db)):
    rows = _open_jobs_query(db).limit(_MAX_SITEMAP_ROWS).all()
    return Response(content=_render_sitemap(rows), media_type="application/xml")


@public_router.get("/board/{ref}", include_in_schema=False)
@_limiter.limit("60/minute")
def job_board_detail(ref: str, request: Request, db: Session = Depends(get_db)):
    """SSR HTML page for one open job.

    410 Gone for a job that is no longer open (SEO hygiene: tells crawlers to
    drop the URL rather than keep retrying a soft 404), 404 for an unknown id.
    """
    job_id = _parse_job_ref(ref)
    if job_id is None:
        return HTMLResponse(
            content=_render_status_page(
                status_title="Job not found",
                heading="We couldn't find that job",
                message="That link doesn't match any role we list. Browse every open superyacht job instead.",
            ),
            status_code=404,
        )

    job = db.query(Job).filter(Job.id == job_id).first()
    if job is None:
        return HTMLResponse(
            content=_render_status_page(
                status_title="Job not found",
                heading="We couldn't find that job",
                message="That role isn't on the board. Browse every open superyacht job instead.",
            ),
            status_code=404,
        )

    if (job.status or "").strip().lower() != OPEN_STATUS:
        log.info("Job board gone | id=%s | status=%s", job.id, job.status)
        return HTMLResponse(
            content=_render_status_page(
                status_title="Position filled",
                heading="This position is no longer open",
                message="The role has been filled or withdrawn. Plenty of other berths are live right now.",
            ),
            status_code=410,
        )

    related = (
        _open_jobs_query(db).filter(Job.id != job.id).limit(_MAX_RELATED).all()
    )
    return HTMLResponse(content=_render_job_html(job, related))
