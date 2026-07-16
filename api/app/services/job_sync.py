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

Image-only posts (no text, just a photo) are routed through the vision reviewer
instead of the text reviewer; their content_hash is the SHA-256 of the image
bytes (Facebook CDN URLs are signed/expiring, so URL hashing can't dedup them).

The content_hash catches the same post shared across multiple Facebook groups.
The job_fingerprint catches the same position re-posted with different text.
"""
import hashlib
import json
import re
import urllib.error
import urllib.request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.logger import get_logger
from app.models import Job, RejectedPost
from app.services.ai_client import review_job_image
from app.services.ai_job_reviewer import _SYSTEM_PROMPT, review_post

log = get_logger("carver.job_sync")

# Sources that come from dedicated job boards — already confirmed jobs,
# classification pre-filter is skipped, auto-apply is enabled when email present.
_TRUSTED_SOURCES = {"dockwalk", "workonayacht", "vikingcrew", "faststream"}

# Keys the Facebook actor uses to carry a media payload. Grounded in a real
# prod dataset: photo posts carry a list under "attachments", each photo dict
# holding the full image at ["photo_image"]["uri"] with a ["thumbnail"]
# fallback. An image-only post (media, no text) still carries a job, so it is
# routed to the vision reviewer rather than dropped as an empty record.
_MEDIA_KEYS = ("attachments",)

# Vision-review guards for scraped image posts.
_MAX_IMAGE_REVIEWS_PER_RUN = 20        # cap OpenAI vision calls per sync_jobs run
_MAX_IMAGE_BYTES = 8 * 1024 * 1024     # 8 MB cap on a downloaded post image
_IMAGE_DOWNLOAD_TIMEOUT = 30           # seconds for a single image download


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


def _has_media(item: dict) -> bool:
    """True if the raw item carries any image/attachment payload."""
    return any(item.get(k) for k in _MEDIA_KEYS)


def _first_image_url(item: dict) -> str | None:
    """First usable image URL from a Facebook post's attachments.

    Observed shape (Apify actor): item["attachments"] is a list of dicts; a
    photo attachment carries the full image at ["photo_image"]["uri"] with a
    lower-res ["thumbnail"] fallback. Non-photo attachments (media sets, shared
    links) have neither and are skipped.
    """
    attachments = item.get("attachments")
    if not isinstance(attachments, list):
        return None
    for att in attachments:
        if not isinstance(att, dict):
            continue
        photo = att.get("photo_image")
        if isinstance(photo, dict) and photo.get("uri"):
            return str(photo["uri"])
        thumb = att.get("thumbnail")
        if thumb:
            return str(thumb)
    return None


def _sniff_image_mime(data: bytes, content_type: str | None) -> str | None:
    """Return a supported image MIME (jpeg/png/webp) from magic bytes, falling
    back to the Content-Type header, else None for unsupported formats.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    ct = (content_type or "").split(";")[0].strip().lower()
    return ct if ct in ("image/jpeg", "image/png", "image/webp") else None


def _download_image(url: str) -> tuple[bytes, str] | None:
    """Download an image URL, returning (bytes, mime_type) when it is a
    supported format within the size cap, else None.

    Never raises: network errors, oversize payloads, and unsupported formats
    all return None so the caller simply skips the item.
    """
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "carver-scraper/1.0"})
        with urllib.request.urlopen(req, timeout=_IMAGE_DOWNLOAD_TIMEOUT) as resp:
            data = resp.read(_MAX_IMAGE_BYTES + 1)
            content_type = resp.headers.get("Content-Type")
    except (urllib.error.URLError, OSError, ValueError):
        return None
    if not data or len(data) > _MAX_IMAGE_BYTES:
        return None
    mime = _sniff_image_mime(data, content_type)
    if not mime:
        return None
    return data, mime


def _parse_image_review(raw_json: str) -> dict | None:
    """Parse the vision reviewer's JSON response; None if it isn't a JSON object."""
    try:
        parsed = json.loads(raw_json)
    except (json.JSONDecodeError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _record_rejection(db: Session, content_hash: str, reason: str = "not_a_job") -> None:
    """Cache an AI "not a job" verdict so the post isn't re-sent to OpenAI next
    cycle. A SAVEPOINT isolates the insert so a unique-hash race (a concurrent
    run recorded it first) rolls back only this row, never the staged jobs.
    """
    try:
        with db.begin_nested():
            db.add(RejectedPost(content_hash=content_hash, reason=reason))
    except IntegrityError:
        pass


def _finalize_job(
    db: Session,
    ai_fields: dict,
    item: dict,
    source: str,
    content_hash: str | None,
    post_url: str,
) -> bool:
    """Build a Job row from AI fields, run fingerprint/url/title dedup, and stage
    it. Returns True if staged, False if skipped as a duplicate. Shared by the
    text and image review paths so the post-AI dedup+insert logic lives once.
    """
    fields = _build_job_fields(ai_fields, item, source)
    fields["content_hash"] = content_hash

    fp = _job_fingerprint(
        fields.get("role"),
        fields.get("location"),
        fields.get("start_date"),
    )
    fields["job_fingerprint"] = fp

    # Fingerprint dedup — same position, different wording.
    if fp and db.query(Job.id).filter(Job.job_fingerprint == fp).first():
        log.debug("Duplicate skipped (fingerprint) | fp=%s | url=%s", fp[:12], post_url)
        return False

    # application_url dedup — belt-and-braces.
    if fields.get("application_url") and (
        db.query(Job.id).filter(Job.application_url == fields["application_url"]).first()
    ):
        log.debug("Duplicate skipped (url) | url=%s", fields["application_url"])
        return False

    # title+role+location dedup — catches the same job re-scraped with different
    # text or start_date phrasing.
    if fields.get("title") and fields.get("role") and fields.get("location") and (
        db.query(Job.id)
        .filter(
            Job.title == fields["title"],
            Job.role == fields["role"],
            Job.location == fields["location"],
        )
        .first()
    ):
        log.debug(
            "Duplicate skipped (title+role+location) | title=%r | url=%s",
            fields["title"], post_url,
        )
        return False

    db.add(Job(**fields))
    db.flush()
    log.info(
        "Job staged | source=%s | title=%r | role=%r | hash=%s | url=%s",
        source,
        fields["title"],
        fields["role"],
        (content_hash or "")[:12],
        post_url,
    )
    return True


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

    Image-only posts (no text, just a photo) are routed to the vision reviewer:
    the first attachment image is downloaded, hashed by bytes, dedup-checked, and
    read by OpenAI. Vision calls are capped at _MAX_IMAGE_REVIEWS_PER_RUN per run.

    Deduplication layers:
      1. content_hash          — same raw text, or image bytes for photo posts
      2. job_fingerprint       — same role+location+start_date (catches re-worded reposts)
      3. application_url       — belt-and-braces URL match
      4. title+role+location   — catches same job re-scraped with different text/start_date

    Returns (created, skipped, errors).
    Raises JobSyncError if the final DB commit fails.
    """
    created = skipped = errors = 0
    is_trusted = source in _TRUSTED_SOURCES
    image_reviews = 0          # vision calls made this run (capped)
    image_cap_logged = False   # ensures the cap-reached notice logs only once

    for item in items:
        post_url = item.get("url") or item.get("facebookUrl") or ""
        post_text = item.get("text") or ""

        # Cheap pre-filter: drop dead-group error records ({"error", ...}) and
        # fully empty items (no text and no media) before any work. Image-only
        # posts (media but no text) are kept for Phase 2 image review.
        if item.get("error") or (not post_text.strip() and not _has_media(item)):
            skipped += 1
            log.debug("Skipped (empty or error record) | source=%s | url=%s", source, post_url)
            continue

        # Trusted sources: skip items with no contact method up-front
        if is_trusted:
            has_email = bool(item.get("contact_email") or _extract_email(post_text))
            has_form = bool(post_url)
            if not has_email and not has_form:
                skipped += 1
                log.debug("Skipped (no contact method) | source=%s | url=%s", source, post_url)
                continue

        try:
            # ── Image-only post: no usable text but carries media → vision path
            if not post_text.strip() and _has_media(item):
                img_url = _first_image_url(item)
                if not img_url:
                    skipped += 1
                    log.debug("Skipped (image post, no usable image url) | url=%s", post_url)
                    continue

                downloaded = _download_image(img_url)
                if downloaded is None:
                    skipped += 1
                    log.debug(
                        "Skipped (image download failed / oversize / unsupported) | url=%s",
                        post_url,
                    )
                    continue
                img_bytes, mime_type = downloaded

                # content_hash = SHA-256 of the image BYTES (fbcdn URLs are
                # signed/expiring, so URL hashing can't dedup). Dedup order:
                # jobs → rejected_posts → only then spend an OpenAI vision call.
                h = hashlib.sha256(img_bytes).hexdigest()
                if db.query(Job.id).filter(Job.content_hash == h).first():
                    skipped += 1
                    log.info("Duplicate skipped (image hash) | hash=%s | url=%s", h[:12], post_url)
                    continue
                if db.query(RejectedPost.id).filter(RejectedPost.content_hash == h).first():
                    skipped += 1
                    log.info("Duplicate skipped (rejected image) | hash=%s | url=%s", h[:12], post_url)
                    continue

                if image_reviews >= _MAX_IMAGE_REVIEWS_PER_RUN:
                    if not image_cap_logged:
                        log.info(
                            "Image review cap reached (%d) — remaining image posts skipped this run",
                            _MAX_IMAGE_REVIEWS_PER_RUN,
                        )
                        image_cap_logged = True
                    skipped += 1
                    continue

                image_reviews += 1
                raw_json = review_job_image(
                    api_key=openai_api_key,
                    image_bytes=img_bytes,
                    mime_type=mime_type,
                    model=openai_model,
                    system_prompt=_SYSTEM_PROMPT,
                )
                parsed = _parse_image_review(raw_json)
                if not parsed or not parsed.get("is_job"):
                    _record_rejection(db, h, reason="not_a_job_image")
                    skipped += 1
                    log.info("Skipped (image not a job post) | url=%s", post_url)
                    continue
                parsed.pop("is_job", None)

                if _finalize_job(db, parsed, item, source, h, post_url):
                    created += 1
                else:
                    skipped += 1
                continue

            # ── Text path ────────────────────────────────────────────────────
            # Step 1: Hash the raw text — skip BEFORE calling AI (saves credits)
            h = _content_hash(post_text) if post_text else None
            if h:
                already_exists = db.query(Job.id).filter(Job.content_hash == h).first()
                if already_exists:
                    skipped += 1
                    log.info("Duplicate skipped (hash) | hash=%s | url=%s", h[:12], post_url)
                    continue
                rejected = db.query(RejectedPost.id).filter(RejectedPost.content_hash == h).first()
                if rejected:
                    skipped += 1
                    log.info("Duplicate skipped (rejected) | hash=%s | url=%s", h[:12], post_url)
                    continue

            # Step 2: AI review — classification + field extraction
            ai_fields = review_post(
                post_text, post_url, openai_api_key, openai_model,
                trusted_source=is_trusted,
            )
            if ai_fields is None:
                if h:
                    _record_rejection(db, h)
                skipped += 1
                log.info("Skipped (not a job post) | url=%s", post_url)
                continue

            # Step 3: shared dedup + insert (fingerprint / url / title)
            if _finalize_job(db, ai_fields, item, source, h, post_url):
                created += 1
            else:
                skipped += 1

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
