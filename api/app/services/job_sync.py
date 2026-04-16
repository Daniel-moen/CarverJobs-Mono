"""
Job sync service — runs AI review on each raw item, filters out non-job posts,
and upserts confirmed job listings into the database.

Flow per item:
  1. Compute SHA-256 of the raw post text — skip if already seen (no AI call).
  2. Compute job fingerprint (role|location|start_date) — skip if same position
     already stored under different wording.
  3. Call ChatGPT to determine if the post is a genuine job offer (skipped for
     trusted web sources like Dockwalk / WorkOnAYacht).
  4. If yes, merge AI-extracted fields with raw item metadata.
  5. Insert into the jobs table with the source, content_hash, and job_fingerprint.

The content_hash catches the same post shared across multiple Facebook groups.
The job_fingerprint catches the same position re-posted with different text.
"""
import hashlib
import re
from sqlalchemy.orm import Session

from app.logger import get_logger
from app.models import Job
from app.services.ai_job_reviewer import review_post

log = get_logger("carver.job_sync")

# Sources that come from dedicated job boards — already confirmed jobs,
# classification pre-filter is skipped, auto-apply is enabled when email present.
_TRUSTED_SOURCES = {"dockwalk", "workonayacht", "vikingcrew", "faststream"}


class JobSyncError(Exception):
    """Raised when the database commit fails during job sync."""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        f = float(value)
        return f if 0 <= f <= 10_000_000 else None
    except (TypeError, ValueError):
        return None


def _safe_int(value: object, lo: int = 0, hi: int = 9999) -> int | None:
    if value is None:
        return None
    try:
        i = int(value)
        return i if lo <= i <= hi else None
    except (TypeError, ValueError):
        return None


def _trunc(value: object, maxlen: int) -> str | None:
    if not value:
        return None
    s = str(value).strip()
    return s[:maxlen] if s else None


def _content_hash(post_text: str) -> str:
    """
    SHA-256 of the normalised post text.
    Normalise to strip leading/trailing whitespace and collapse internal runs of
    whitespace so trivial formatting differences don't create different hashes.
    """
    normalised = " ".join(post_text.split())
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def _job_fingerprint(role: str | None, location: str | None, start_date: str | None) -> str | None:
    """
    SHA-256 of normalised role|location|start_date.

    Catches the same position re-posted by a different recruiter with different
    wording: same role, same location, same start → same fingerprint.
    Returns None if both role and location are missing (insufficient signal).
    """
    r = (role or "").strip().lower()
    l = (location or "").strip().lower()
    d = (start_date or "").strip().lower()
    if not r and not l:
        return None
    raw = f"{r}|{l}|{d}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _extract_email(text: str) -> str | None:
    """Pull the first email address out of a block of text."""
    if not text:
        return None
    m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else None


# ── Core mapping ──────────────────────────────────────────────────────────────

def _build_job_fields(ai: dict, raw: dict, source: str) -> dict:
    """
    Merge AI-extracted fields with raw item metadata.
    AI fields take precedence; raw item provides fallbacks and URL/timestamp data.
    """
    app_url = _trunc(raw.get("url") or raw.get("facebookUrl"), 260)

    # Contact email: prefer AI extraction, then raw item hint, then regex on text
    contact_email = (
        _trunc(ai.get("contact_email"), 160)
        or _trunc(raw.get("contact_email"), 160)
        or _extract_email(raw.get("text", ""))
    )

    recruiter_name = (
        _trunc(ai.get("recruiter_name"), 120)
        or _trunc(raw.get("user", {}).get("name"), 120)
    )
    if recruiter_name and "anonymous" in recruiter_name.lower():
        recruiter_name = None

    # auto_apply_enabled: True for trusted sources that have a contact email
    is_trusted = source in _TRUSTED_SOURCES
    auto_apply = is_trusted and bool(contact_email)

    return {
        "title":                     _trunc(ai.get("title"), 160) or "Yacht Crew Position",
        "role":                      _trunc(ai.get("role"), 120) or "Crew",
        "yacht":                     _trunc(ai.get("yacht"), 120) or "Private Yacht",
        "location":                  _trunc(ai.get("location"), 120) or "Unknown",

        "yacht_type":                _trunc(ai.get("yacht_type"), 80),
        "yacht_length_m":            _safe_int(ai.get("yacht_length_m"), 1, 600),
        "vessel_flag":               _trunc(ai.get("vessel_flag"), 60),
        "vessel_itinerary":          _trunc(ai.get("vessel_itinerary"), 200),

        "department":                _trunc(ai.get("department"), 60),
        "rank_level":                _trunc(ai.get("rank_level"), 60),
        "start_date":                _trunc(ai.get("start_date"), 40),
        "contract_type":             _trunc(ai.get("contract_type"), 60),
        "leave_structure":           _trunc(ai.get("leave_structure"), 60),
        "rotation":                  _trunc(ai.get("rotation"), 50),
        "season":                    _trunc(ai.get("season"), 60),

        "salary_currency":           _trunc(ai.get("salary_currency"), 10) or "EUR",
        "salary_min":                _safe_float(ai.get("salary_min")),
        "salary_max":                _safe_float(ai.get("salary_max")),
        "tips_bonus":                _trunc(ai.get("tips_bonus"), 120),

        "visa_support":              bool(ai.get("visa_support", False)),
        "accommodation":             _trunc(ai.get("accommodation"), 120),
        "travel_reimbursement":      bool(ai.get("travel_reimbursement", False)),

        "experience_required_years": _safe_int(ai.get("experience_required_years"), 0, 80),
        "minimum_license":           _trunc(ai.get("minimum_license"), 120),
        "certifications_required":   _trunc(ai.get("certifications_required"), 5000),
        "languages_required":        _trunc(ai.get("languages_required"), 200),

        "description":               _trunc(ai.get("description"), 5000),
        "responsibilities":          _trunc(ai.get("responsibilities"), 5000),
        "requirements":              _trunc(ai.get("requirements"), 5000),
        "benefits":                  _trunc(ai.get("benefits"), 5000),

        "contact_email":             contact_email,
        "application_url":           app_url,
        "recruiter_name":            recruiter_name,
        "recruiter_agency":          _trunc(ai.get("recruiter_agency"), 120),

        "urgent_hire":               bool(ai.get("urgent_hire", False)),
        "status":                    "open",
        "auto_apply_enabled":        auto_apply,
        "source":                    source,
        "content_hash":              None,   # filled by caller
        "job_fingerprint":           None,   # filled by caller
    }


# ── Sync entry point ──────────────────────────────────────────────────────────

def sync_jobs(
    db: Session,
    items: list[dict],
    openai_api_key: str,
    openai_model: str,
    source: str = "apify",
) -> tuple[int, int, int]:
    """
    Run AI review on each item and upsert confirmed job listings.

    For trusted web sources (dockwalk, workonayacht):
      - Skips the "is this even a job?" classification step.
      - Sets auto_apply_enabled=True when contact_email is present.
      - Skips items that have neither contact_email nor application_url.

    Deduplication layers:
      1. content_hash          — same raw text (catches cross-group reposts)
      2. job_fingerprint       — same role+location+start_date (catches re-worded reposts)
      3. application_url       — belt-and-braces URL match
      4. title+role+location   — catches same job re-scraped with different text/start_date

    Returns (created, skipped, errors).
    Raises JobSyncError if the final DB commit fails.
    """
    created = skipped = errors = 0
    is_trusted = source in _TRUSTED_SOURCES

    for item in items:
        post_url = item.get("url") or item.get("facebookUrl") or ""
        post_text = item.get("text") or ""

        # Trusted sources: skip items with no contact method up-front
        if is_trusted:
            has_email = bool(item.get("contact_email") or _extract_email(post_text))
            has_form = bool(post_url)
            if not has_email and not has_form:
                skipped += 1
                log.debug("Skipped (no contact method) | source=%s | url=%s", source, post_url)
                continue

        try:
            # Step 1: Hash the raw text — skip BEFORE calling AI (saves credits)
            h = _content_hash(post_text) if post_text else None
            if h:
                already_exists = db.query(Job.id).filter(Job.content_hash == h).first()
                if already_exists:
                    skipped += 1
                    log.info("Duplicate skipped (hash) | hash=%s | url=%s", h[:12], post_url)
                    continue

            # Step 2: AI review — classification + field extraction
            ai_fields = review_post(
                post_text, post_url, openai_api_key, openai_model,
                trusted_source=is_trusted,
            )
            if ai_fields is None:
                skipped += 1
                log.info("Skipped (not a job post) | url=%s", post_url)
                continue

            # Step 3: Build fields, attach hashes
            fields = _build_job_fields(ai_fields, item, source)
            fields["content_hash"] = h

            fp = _job_fingerprint(
                fields.get("role"),
                fields.get("location"),
                fields.get("start_date"),
            )
            fields["job_fingerprint"] = fp

            # Step 4: Fingerprint dedup — same position, different wording
            if fp:
                exists = db.query(Job.id).filter(Job.job_fingerprint == fp).first()
                if exists:
                    skipped += 1
                    log.debug(
                        "Duplicate skipped (fingerprint) | fp=%s | url=%s", fp[:12], post_url
                    )
                    continue

            # Step 5: application_url dedup — belt-and-braces
            if fields.get("application_url"):
                exists = (
                    db.query(Job.id)
                    .filter(Job.application_url == fields["application_url"])
                    .first()
                )
                if exists:
                    skipped += 1
                    log.debug("Duplicate skipped (url) | url=%s", fields["application_url"])
                    continue

            # Step 6: title+role+location dedup — catches same job re-scraped from a
            # different URL with slightly different text or start_date phrasing
            if fields.get("title") and fields.get("role") and fields.get("location"):
                exists = (
                    db.query(Job.id)
                    .filter(
                        Job.title == fields["title"],
                        Job.role == fields["role"],
                        Job.location == fields["location"],
                    )
                    .first()
                )
                if exists:
                    skipped += 1
                    log.debug(
                        "Duplicate skipped (title+role+location) | title=%r | url=%s",
                        fields["title"], post_url,
                    )
                    continue

            # Step 7: Insert
            db.add(Job(**fields))
            db.flush()
            created += 1
            log.info(
                "Job staged | source=%s | title=%r | role=%r | hash=%s | url=%s",
                source,
                fields["title"],
                fields["role"],
                (h or "")[:12],
                post_url,
            )

        except Exception as exc:
            errors += 1
            log.error("Failed to process item | source=%s | url=%s | error=%s", source, post_url, exc)

    try:
        db.commit()
    except Exception as exc:
        db.rollback()
        raise JobSyncError(f"Database commit failed during job sync: {exc}") from exc

    log.info(
        "Job sync complete | source=%s | created=%d | skipped=%d | errors=%d",
        source, created, skipped, errors,
    )
    return created, skipped, errors
