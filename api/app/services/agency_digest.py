"""Weekly jobs-intel digest for crew agencies — the concierge revenue test.

The 22 Sep 2026 review put a hand-sent weekly digest ahead of any new
self-serve product: agencies in Cape Town, Antibes, Palma and Fort Lauderdale
already pay for market visibility, and Carver already scrapes ~250 structured
roles a month. This module turns one week of that scrape into something the
founder can send in a single call — no dashboard, no login, no integration.

What the digest contains:

* every job **posted** in the window (open *and* since-expired — the value is
  "what hit the market this week", not "what is still live"),
* grouped by role family (deck / interior / engineering / galley / other),
* this week vs last week (volume, salary transparency, top locations, top roles),
* up to three anonymised crew profiles matching the week's most-posted role.

What it deliberately never contains: recruiter emails, phone numbers,
application URLs, or anything that identifies a crew member (no name, slug,
phone or email). Contact details are the paid layer — the digest sells the
market picture, the agency still comes to Carver to reach anyone in it.

Renderers are pure functions of the built `DigestData`, so the same week can be
pasted into WhatsApp (`render_markdown`) or emailed/printed (`render_html`).
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.models import CrewProfile, Job
from app.services.role_taxonomy import (
    RELATED_ADJACENT,
    normalize_role,
    role_department,
    roles_related,
)

# ── Regions ─────────────────────────────────────────────────────────────────
#
# Job locations are free text scraped from posts ("Antibes, France", "Fort
# Lauderdale FL", "Cape Town / SA"), so the regional cut is a small curated
# keyword map rather than anything structured. Deliberately short: it only has
# to separate the four markets the digest is sold into.

REGIONS: tuple[str, ...] = ("med", "americas", "za", "other")

REGION_LABELS: dict[str, str] = {
    "med": "Mediterranean",
    "americas": "Americas & Caribbean",
    "za": "South Africa",
    "other": "Elsewhere",
}

_REGION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "med": (
        "med", "mediterranean", "antibes", "palma", "mallorca", "majorca",
        "barcelona", "genoa", "genova", "monaco", "cannes", "nice",
        "la ciotat", "golfe juan", "sardinia", "olbia", "italy", "spain",
        "france", "greece", "croatia",
    ),
    "americas": (
        "fort lauderdale", "ft lauderdale", "florida", "miami",
        "west palm beach", "newport", "caribbean", "antigua", "st maarten",
        "sint maarten", "saint maarten", "bahamas", "usa", "united states",
    ),
    "za": ("cape town", "durban", "south africa", "johannesburg", "richards bay"),
}

# Longest keyword first so "south africa" beats a stray "africa"-style match and
# "fort lauderdale" beats "florida" when a location carries both.
_REGION_INDEX: list[tuple[str, re.Pattern[str]]] = sorted(
    (
        (region, re.compile(r"(?<![a-z])" + re.escape(keyword) + r"(?![a-z])"))
        for region, keywords in _REGION_KEYWORDS.items()
        for keyword in keywords
    ),
    key=lambda item: len(item[1].pattern),
    reverse=True,
)


def region_of(location: str | None) -> str:
    """Map a free-text job/crew location to one of REGIONS ("other" if unknown)."""
    if not location:
        return "other"
    text = str(location).strip().lower()
    if not text:
        return "other"
    for region, pattern in _REGION_INDEX:
        if pattern.search(text):
            return region
    return "other"


def region_label(region: str | None) -> str:
    """Human label for a region code; "All regions" for None."""
    if not region:
        return "All regions"
    return REGION_LABELS.get(region, REGION_LABELS["other"])


# ── Role families ───────────────────────────────────────────────────────────

ROLE_FAMILIES: tuple[str, ...] = ("deck", "interior", "engineering", "galley", "other")

ROLE_FAMILY_LABELS: dict[str, str] = {
    "deck": "Deck",
    "interior": "Interior",
    "engineering": "Engineering",
    "galley": "Galley",
    "other": "Other",
}

# role_taxonomy departments -> digest families (medical has no family of its own).
_DEPARTMENT_FAMILY: dict[str, str] = {
    "deck": "deck",
    "engine": "engineering",
    "interior": "interior",
    "galley": "galley",
}

# Fallback for jobs the taxonomy doesn't recognise but that carry a department.
_DEPARTMENT_WORDS: tuple[tuple[str, str], ...] = (
    ("deck", "deck"),
    ("engineer", "engineering"),
    ("engine", "engineering"),
    ("technical", "engineering"),
    ("interior", "interior"),
    ("service", "interior"),
    ("galley", "galley"),
    ("culinary", "galley"),
    ("chef", "galley"),
)


def role_family_of(job: Job) -> str:
    """Role family for a job — taxonomy first, job.department as the fallback."""
    department = role_department(job.role) or role_department(job.title)
    if department:
        return _DEPARTMENT_FAMILY.get(department, "other")
    raw = (job.department or "").strip().lower()
    for word, family in _DEPARTMENT_WORDS:
        if word in raw:
            return family
    return "other"


def role_label_of(job: Job) -> str:
    """Display role for the "top roles" tally — canonical where possible."""
    canonical = normalize_role(job.role) or normalize_role(job.title)
    if canonical:
        return canonical.replace("_", " ").title()
    raw = (job.role or job.title or "").strip()
    return raw.title() if raw else "Unspecified"


# ── Apply route (type only — never the actual contact) ──────────────────────

_FACEBOOK_HOSTS = ("facebook.com", "fb.com", "fb.me", "fb.watch")

APPLY_ROUTE_LABELS: dict[str, str] = {
    "email": "apply by email",
    "facebook": "posted in a Facebook group",
    "website": "apply on a website",
    "unlisted": "no public apply route",
}


def apply_route_of(job: Job) -> str:
    """One of email / facebook / website / unlisted.

    The *type* of route is market intel (a Facebook-only week means agencies
    are not advertising); the address itself is the paid layer and never leaves
    this module.
    """
    url = (job.application_url or "").strip().lower()
    if any(host in url for host in _FACEBOOK_HOSTS):
        return "facebook"
    if (job.contact_email or "").strip():
        return "email"
    if url:
        return "website"
    return "unlisted"


# ── Formatting helpers ──────────────────────────────────────────────────────


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _money(amount: float) -> str:
    return f"{int(round(amount)):,}"


def _salary_text(job: Job) -> str | None:
    """Mirrors the public board's salary line; None when the scrape had none."""
    code = "".join(ch for ch in (job.salary_currency or "") if ch.isalpha()).upper()[:6] or "EUR"
    low = job.salary_min if job.salary_min and job.salary_min > 0 else None
    high = job.salary_max if job.salary_max and job.salary_max > 0 else None
    if low and high and high > low:
        return f"{code} {_money(low)}–{_money(high)} / month"
    if low:
        return f"{code} {_money(low)} / month"
    if high:
        return f"{code} up to {_money(high)} / month"
    return None


def _day(value: datetime | None) -> str:
    when = _as_utc(value)
    return when.strftime("%a %-d %b") if when else ""


def _date_range(since: datetime, until: datetime) -> str:
    """"15–21 Sep 2026" — `until` is exclusive, so show the last included day."""
    start = _as_utc(since)
    end = _as_utc(until) - timedelta(seconds=1)
    if start.year == end.year and start.month == end.month:
        return f"{start.strftime('%-d')}–{end.strftime('%-d %b %Y')}"
    if start.year == end.year:
        return f"{start.strftime('%-d %b')} – {end.strftime('%-d %b %Y')}"
    return f"{start.strftime('%-d %b %Y')} – {end.strftime('%-d %b %Y')}"


def _split_list(value: str | None) -> list[str]:
    """Split a free-text cert/language list the way the crew profile stores it."""
    if not value:
        return []
    parts = [p.strip() for p in str(value).replace("\n", ",").replace(";", ",").split(",")]
    skip = {"none", "n/a", "na", "-", "nil", "none yet"}
    return [p for p in parts if p and p.lower() not in skip]


def _signed(value: int) -> str:
    return f"+{value}" if value > 0 else str(value)


# ── Data model ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class DigestJob:
    """One scraped role, stripped of every way to contact the recruiter."""

    id: int
    title: str
    role: str | None
    role_family: str
    location: str
    region: str
    vessel_size: str | None
    salary: str | None
    contract_type: str | None
    posted_at: datetime | None
    apply_route: str
    still_open: bool

    @property
    def posted_date(self) -> str:
        when = _as_utc(self.posted_at)
        return when.date().isoformat() if when else ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "role": self.role,
            "role_family": self.role_family,
            "location": self.location,
            "region": self.region,
            "vessel_size": self.vessel_size,
            "salary": self.salary,
            "contract_type": self.contract_type,
            "posted_date": self.posted_date,
            "apply_route": self.apply_route,
            "still_open": self.still_open,
        }


@dataclass(frozen=True)
class DigestCrew:
    """An anonymised crew profile — no name, slug, phone or email, ever."""

    desired_role: str
    nationality: str | None
    years_experience: str | None
    certs_count: int
    region: str

    @property
    def region_name(self) -> str:
        return region_label(self.region)

    def to_dict(self) -> dict:
        return {
            "desired_role": self.desired_role,
            "nationality": self.nationality,
            "years_experience": self.years_experience,
            "certs_count": self.certs_count,
            "region": self.region,
            "region_label": self.region_name,
        }


@dataclass(frozen=True)
class DigestTotals:
    jobs: int
    with_salary: int
    top_locations: list[tuple[str, int]]
    top_roles: list[tuple[str, int]]

    @property
    def salary_pct(self) -> int:
        return round(100 * self.with_salary / self.jobs) if self.jobs else 0

    def to_dict(self) -> dict:
        return {
            "jobs": self.jobs,
            "with_salary": self.with_salary,
            "salary_pct": self.salary_pct,
            "top_locations": [{"name": n, "count": c} for n, c in self.top_locations],
            "top_roles": [{"name": n, "count": c} for n, c in self.top_roles],
        }


@dataclass(frozen=True)
class DigestData:
    since: datetime
    until: datetime
    region: str | None
    generated_at: datetime
    jobs: list[DigestJob]
    groups: list[tuple[str, list[DigestJob]]]
    totals: DigestTotals
    previous: DigestTotals
    top_role: str | None
    crew: list[DigestCrew]

    @property
    def region_name(self) -> str:
        return region_label(self.region)

    @property
    def period(self) -> str:
        return _date_range(self.since, self.until)

    @property
    def jobs_delta(self) -> int:
        return self.totals.jobs - self.previous.jobs

    @property
    def salary_pct_delta(self) -> int:
        return self.totals.salary_pct - self.previous.salary_pct

    @property
    def title(self) -> str:
        return f"Superyacht jobs intel — {self.period}"

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "since": _as_utc(self.since).isoformat(),
            "until": _as_utc(self.until).isoformat(),
            "period": self.period,
            "region": self.region,
            "region_label": self.region_name,
            "generated_at": _as_utc(self.generated_at).isoformat(),
            "totals": self.totals.to_dict(),
            "previous": self.previous.to_dict(),
            "jobs_delta": self.jobs_delta,
            "salary_pct_delta": self.salary_pct_delta,
            "groups": [
                {
                    "family": family,
                    "label": ROLE_FAMILY_LABELS[family],
                    "count": len(items),
                    "jobs": [j.to_dict() for j in items],
                }
                for family, items in self.groups
            ],
            "top_role": self.top_role,
            "crew": [c.to_dict() for c in self.crew],
        }


# ── Build ───────────────────────────────────────────────────────────────────

_TOP_N = 3
# How many discoverable profiles to scan for the crew teaser before giving up.
_CREW_SCAN_LIMIT = 400


def _window_jobs(db: Session, since: datetime, until: datetime, region: str | None) -> list[Job]:
    """Every job *created* in the window — status is irrelevant here.

    A role posted on Monday and filled on Thursday is exactly the kind of
    movement agencies pay to see, so expired/filled rows stay in.
    """
    rows = (
        db.query(Job)
        .filter(Job.created_at >= since, Job.created_at < until)
        .order_by(Job.created_at.desc())
        .all()
    )
    if region:
        rows = [j for j in rows if region_of(j.location) == region]
    return rows


def _to_digest_job(job: Job) -> DigestJob:
    return DigestJob(
        id=job.id,
        title=(job.title or job.role or "Untitled role").strip(),
        role=(job.role or None),
        role_family=role_family_of(job),
        location=(job.location or "").strip(),
        region=region_of(job.location),
        vessel_size=f"{job.yacht_length_m}m" if job.yacht_length_m else None,
        salary=_salary_text(job),
        contract_type=(job.contract_type or None),
        posted_at=job.created_at,
        apply_route=apply_route_of(job),
        still_open=(job.status or "") in ("open", "priority"),
    )


def _top(counts: dict[str, int], labels: dict[str, str] | None = None) -> list[tuple[str, int]]:
    ordered = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:_TOP_N]
    if labels is None:
        return ordered
    return [(labels.get(key, key), count) for key, count in ordered]


def _totals(jobs: list[Job]) -> DigestTotals:
    location_counts: dict[str, int] = {}
    location_labels: dict[str, str] = {}
    role_counts: dict[str, int] = {}
    with_salary = 0

    for job in jobs:
        if _salary_text(job):
            with_salary += 1
        location = (job.location or "").strip()
        if location:
            key = location.lower()
            location_counts[key] = location_counts.get(key, 0) + 1
            location_labels.setdefault(key, location)
        role = role_label_of(job)
        role_counts[role] = role_counts.get(role, 0) + 1

    return DigestTotals(
        jobs=len(jobs),
        with_salary=with_salary,
        top_locations=_top(location_counts, location_labels),
        top_roles=_top(role_counts),
    )


def _matching_crew(
    db: Session, role: str | None, region: str | None, limit: int = 3
) -> list[DigestCrew]:
    """Up to `limit` anonymised discoverable profiles for the week's top role."""
    if not role:
        return []
    profiles = (
        db.query(CrewProfile)
        .filter(CrewProfile.discoverable.is_(True), CrewProfile.desired_role.isnot(None))
        .order_by(CrewProfile.updated_at.desc())
        .limit(_CREW_SCAN_LIMIT)
        .all()
    )
    out: list[DigestCrew] = []
    for profile in profiles:
        desired = (profile.desired_role or "").strip()
        if not desired:
            continue
        if region and region_of(profile.current_location) != region:
            continue
        # Same role, or one seniority step away in the same department.
        if roles_related(role, desired) < RELATED_ADJACENT:
            continue
        out.append(
            DigestCrew(
                desired_role=desired,
                nationality=(profile.nationality or None),
                years_experience=(profile.years_experience or None),
                certs_count=len(_split_list(profile.certifications)),
                region=region_of(profile.current_location),
            )
        )
        if len(out) >= limit:
            break
    return out


def build_digest(
    db: Session,
    since: datetime,
    until: datetime,
    region: str | None = None,
) -> DigestData:
    """Assemble one week of jobs intel. Pure read — writes nothing."""
    since = _as_utc(since)
    until = _as_utc(until)
    span = until - since
    previous_since = since - span

    rows = _window_jobs(db, since, until, region)
    previous_rows = _window_jobs(db, previous_since, since, region)

    jobs = [_to_digest_job(job) for job in rows]
    groups = [
        (family, [j for j in jobs if j.role_family == family])
        for family in ROLE_FAMILIES
    ]
    groups = [(family, items) for family, items in groups if items]

    totals = _totals(rows)
    top_role = totals.top_roles[0][0] if totals.top_roles else None

    return DigestData(
        since=since,
        until=until,
        region=region,
        generated_at=datetime.now(timezone.utc),
        jobs=jobs,
        groups=groups,
        totals=totals,
        previous=_totals(previous_rows),
        top_role=top_role,
        crew=_matching_crew(db, top_role, region),
    )


# ── Renderers ───────────────────────────────────────────────────────────────

FOOTER = "Compiled by CARVER · jobcarver.co · reply to this email to talk"


def _job_facts(job: DigestJob) -> list[str]:
    facts = [job.location or "Location not stated"]
    if job.vessel_size:
        facts.append(job.vessel_size)
    if job.salary:
        facts.append(job.salary)
    else:
        facts.append("salary not published")
    if job.contract_type:
        facts.append(job.contract_type)
    facts.append(f"posted {_day(job.posted_at)}")
    facts.append(APPLY_ROUTE_LABELS.get(job.apply_route, job.apply_route))
    if not job.still_open:
        facts.append("already off the market")
    return facts


def _crew_facts(crew: DigestCrew) -> list[str]:
    facts = [crew.desired_role]
    if crew.nationality:
        facts.append(crew.nationality)
    if crew.years_experience:
        facts.append(f"{crew.years_experience} yrs experience")
    facts.append(f"{crew.certs_count} cert{'s' if crew.certs_count != 1 else ''} listed")
    facts.append(f"currently {crew.region_name}")
    return facts


def render_markdown(digest: DigestData) -> str:
    """Plain markdown — pastes cleanly into an email body or a WhatsApp message."""
    t, p = digest.totals, digest.previous
    lines: list[str] = [
        f"# {digest.title}",
        "",
        f"**{digest.region_name} · {digest.period}**",
        "",
        "## This week at a glance",
        "",
        f"- **{t.jobs} role{'s' if t.jobs != 1 else ''} posted** "
        f"(previous week {p.jobs}, {_signed(digest.jobs_delta)})",
        f"- **{t.salary_pct}% published a salary** "
        f"({t.with_salary} of {t.jobs}; previous week {p.salary_pct}%, "
        f"{_signed(digest.salary_pct_delta)} pts)",
    ]
    if t.top_locations:
        lines.append(
            "- Top locations: "
            + " · ".join(f"{name} ({count})" for name, count in t.top_locations)
        )
    if t.top_roles:
        lines.append(
            "- Most-posted roles: "
            + " · ".join(f"{name} ({count})" for name, count in t.top_roles)
        )
    lines.append("")

    if not digest.jobs:
        lines += ["_No roles were posted in this window._", ""]

    for family, items in digest.groups:
        lines += [f"## {ROLE_FAMILY_LABELS[family]} ({len(items)})", ""]
        for job in items:
            lines.append(f"- **{job.title}** — " + " · ".join(_job_facts(job)))
        lines.append("")

    if digest.crew:
        headline = digest.top_role or "this week's top role"
        lines += [
            f"## Crew on Carver for {headline} roles",
            "",
            "_Anonymised — reply and Carver will make the introduction._",
            "",
        ]
        for crew in digest.crew:
            lines.append("- " + " · ".join(_crew_facts(crew)))
        lines.append("")

    lines += [
        "---",
        "",
        "Recruiter contact details are not published in this digest — "
        "reply with the role and Carver will route your candidate to it.",
        "",
        FOOTER,
    ]
    return "\n".join(lines).rstrip() + "\n"


def _esc(value: str | None) -> str:
    return html.escape(value or "", quote=True)


# Same type system and brass accent as the article pages (Georgia headings,
# monospace eyebrows, --brass), on paper-white rather than the site's near-black:
# this page is emailed, forwarded and printed, and a dark ground survives none
# of those. The print block drops the card fills so it lands clean on A4.
_DIGEST_CSS = """
      :root { --bg:#fdfcfa; --text:#12161c; --muted:#5b6370; --brass:#8a6a2f; --line:#e6e1d8; --fill:#faf7f1; }
      *,*::before,*::after { box-sizing:border-box; }
      html,body { margin:0; padding:0; background:var(--bg); color:var(--text); font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; -webkit-font-smoothing:antialiased; }
      main { max-width:760px; margin:0 auto; padding:2.5rem 1.5rem 4rem; }
      .eyebrow { margin:0; font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:0.72rem; letter-spacing:0.14em; text-transform:uppercase; color:var(--brass); }
      h1 { margin:0.7rem 0 0; font-family:Georgia, "Times New Roman", serif; font-weight:400; font-size:clamp(1.7rem, 4vw, 2.4rem); line-height:1.1; letter-spacing:-0.02em; }
      .lede { margin:0.75rem 0 0; color:var(--muted); font-size:1rem; line-height:1.6; }
      h2 { font-family:Georgia, "Times New Roman", serif; font-weight:400; font-size:1.25rem; margin:2.5rem 0 0.9rem; letter-spacing:-0.01em; }
      .stats { list-style:none; margin:1.5rem 0 0; padding:1.1rem 1.25rem; border:1px solid var(--line); border-radius:12px; background:var(--fill); }
      .stats li { margin:0.4rem 0; color:var(--text); font-size:0.95rem; line-height:1.55; }
      .stats .delta { color:var(--muted); }
      .jobs { list-style:none; margin:0; padding:0; display:grid; gap:0.7rem; }
      .jobs li { border:1px solid var(--line); border-radius:10px; padding:0.85rem 1rem; }
      .jobs .role { margin:0; font-weight:600; font-size:1rem; line-height:1.35; }
      .jobs .facts { margin:0.35rem 0 0; color:var(--muted); font-size:0.86rem; line-height:1.55; }
      .jobs .closed { color:#9a4b2f; }
      .crew { list-style:none; margin:0; padding:0; display:grid; gap:0.55rem; }
      .crew li { border-left:3px solid var(--brass); padding:0.35rem 0 0.35rem 0.85rem; font-size:0.92rem; color:var(--text); line-height:1.5; }
      .note { margin:1rem 0 0; color:var(--muted); font-size:0.86rem; line-height:1.6; }
      .empty { color:var(--muted); font-size:0.95rem; }
      footer { margin-top:3rem; padding-top:1.25rem; border-top:1px solid var(--line); color:var(--muted); font-size:0.82rem; line-height:1.6; }
      footer strong { color:var(--text); font-weight:600; }
      @media (max-width:600px) {
        main { padding:1.75rem 1rem 3rem; }
        .jobs li { padding:0.75rem 0.85rem; }
      }
      @media print {
        :root { --fill:#fff; }
        main { max-width:none; padding:0; }
        .jobs li, .stats { break-inside:avoid; }
        a { color:var(--text); text-decoration:none; }
      }
"""


def render_html(digest: DigestData) -> str:
    """Standalone, printable HTML — safe to paste into an email or save as PDF."""
    t, p = digest.totals, digest.previous
    title = _esc(digest.title)

    stats = [
        f"<li><strong>{t.jobs} role{'s' if t.jobs != 1 else ''} posted</strong> "
        f"<span class=\"delta\">· previous week {p.jobs} ({_signed(digest.jobs_delta)})</span></li>",
        f"<li><strong>{t.salary_pct}% published a salary</strong> "
        f"<span class=\"delta\">· {t.with_salary} of {t.jobs} · previous week {p.salary_pct}% "
        f"({_signed(digest.salary_pct_delta)} pts)</span></li>",
    ]
    if t.top_locations:
        joined = " · ".join(f"{_esc(name)} ({count})" for name, count in t.top_locations)
        stats.append(f"<li>Top locations: <strong>{joined}</strong></li>")
    if t.top_roles:
        joined = " · ".join(f"{_esc(name)} ({count})" for name, count in t.top_roles)
        stats.append(f"<li>Most-posted roles: <strong>{joined}</strong></li>")

    sections: list[str] = []
    if not digest.jobs:
        sections.append('<p class="empty">No roles were posted in this window.</p>')
    for family, items in digest.groups:
        rows = []
        for job in items:
            facts = " · ".join(_esc(fact) for fact in _job_facts(job))
            closed = "" if job.still_open else ' <span class="closed">·</span>'
            rows.append(
                f'<li><p class="role">{_esc(job.title)}</p>'
                f'<p class="facts">{facts}{closed}</p></li>'
            )
        sections.append(
            f"<h2>{_esc(ROLE_FAMILY_LABELS[family])} ({len(items)})</h2>"
            f'<ul class="jobs">{"".join(rows)}</ul>'
        )

    crew_html = ""
    if digest.crew:
        items = "".join(
            f'<li>{" · ".join(_esc(fact) for fact in _crew_facts(c))}</li>'
            for c in digest.crew
        )
        headline = _esc(digest.top_role) if digest.top_role else "this week&rsquo;s top"
        crew_html = (
            f"<h2>Crew on Carver for {headline} roles</h2>"
            f'<ul class="crew">{items}</ul>'
            '<p class="note">Anonymised on purpose — reply to this email and Carver '
            "makes the introduction.</p>"
        )

    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <meta name="robots" content="noindex, nofollow" />
    <title>{title}</title>
    <style>{_DIGEST_CSS}    </style>
  </head>
  <body>
    <main>
      <p class="eyebrow">Carver weekly · {_esc(digest.region_name)}</p>
      <h1>{title}</h1>
      <p class="lede">Every superyacht role Carver logged between {_esc(digest.period)},
        grouped by department — posted, filled and everything in between.</p>
      <ul class="stats">{"".join(stats)}</ul>
      {"".join(sections)}
      {crew_html}
      <footer>
        <p>Recruiter contact details are not published in this digest — reply with the
          role and Carver will route your candidate to it.</p>
        <p><strong>Compiled by CARVER</strong> · jobcarver.co · reply to this email to talk</p>
      </footer>
    </main>
  </body>
</html>
"""
