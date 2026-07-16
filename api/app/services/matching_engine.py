"""Unified Matching Engine — batches all jobs against a candidate via OpenAI.

Fetches every open/priority job from the database, splits them into batches,
scores each batch concurrently with the LLM, then merges and deduplicates.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Callable

from app.services.ai_client import AIClientError, call_openai
from app.services.role_taxonomy import normalize_roles, roles_related

log = logging.getLogger("carver.matching_engine")

BATCH_SIZE = 8
MATCH_THRESHOLD = 30
MAX_WORKERS = 4
# Deterministic prefilter: only the top N jobs (by role/location/recency) are
# sent to the LLM — this is what cuts spend 5-10x on a large job board.
PREFILTER_TOP_N = 40
# If fewer than this many jobs are role-related to the candidate, the taxonomy
# probably doesn't know their role — fall back to the most recent jobs instead.
PREFILTER_MIN_ROLE_MATCHES = 10
# Blend weights: LLM judgement vs deterministic sub-scores from structured fields.
LLM_BLEND_WEIGHT = 0.65
DETERMINISTIC_BLEND_WEIGHT = 0.35
# Applied in code (not by the LLM) to priority/urgent-hire jobs.
PRIORITY_BOOST = 10.0
# Ceiling for jobs the taxonomy confirms are in a different department than the
# candidate's desired role — no blend, boost or fallback may lift these into a
# recommendation. Same-department roles (deckhand -> bosun) are unaffected.
ROLE_MISMATCH_CAP = 15.0
# Result tiers by final compatibility.
TIER_STRONG_MIN = 75
TIER_GOOD_MIN = 50
_MATCH_MAX_TOKENS_PER_JOB = 400
_MATCH_MIN_MAX_TOKENS = 4096
_MATCH_REQUEST_TIMEOUT = 90
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_FEMALE_REQ_PATTERNS = (
    re.compile(r"\bfemale(?:\s+candidates?)?(?:\s+only)?\b"),
    re.compile(r"\bfemales?\s+only\b"),
    re.compile(r"\blady(?:\s+only)?\b"),
    re.compile(r"\bstewardess(?:es)?\b"),
)
_MALE_REQ_PATTERNS = (
    re.compile(r"\bmale(?:\s+candidates?)?(?:\s+only)?\b"),
    re.compile(r"\bmales?\s+only\b"),
    re.compile(r"\bgentleman(?:\s+only)?\b"),
    re.compile(r"\bsteward\b"),
)


# ── Data containers ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CandidateProfile:
    user_key: str
    first_name: str = ""
    last_name: str = ""
    sex: str = ""
    desired_role: str = ""
    location: str = ""
    preferred_locations: str = ""
    nationality: str = ""
    years_experience: str = ""
    salary_min: str = ""
    salary_max: str = ""
    contract_type: str = ""
    rotation_preference: str = ""
    available_from: str = ""
    certifications: list[str] = field(default_factory=list)
    languages: list[str] = field(default_factory=list)
    bio: str = ""
    job_history: list[dict[str, str]] = field(default_factory=list)
    document_summary: str = ""


@dataclass(frozen=True)
class JobSummary:
    job_id: int
    title: str
    role: str
    department: str = ""
    location: str = ""
    yacht_type: str = ""
    yacht_length_m: int | None = None
    start_date: str = ""
    contract_type: str = ""
    rotation: str = ""
    season: str = ""
    salary_min: float | None = None
    salary_max: float | None = None
    salary_currency: str = "EUR"
    experience_required_years: int | None = None
    minimum_license: str = ""
    rank_level: str = ""
    certifications_required: str = ""
    languages_required: str = ""
    description: str = ""
    requirements: str = ""
    responsibilities: str = ""
    urgent_hire: bool = False
    status: str = "open"
    created_at: datetime | None = None


@dataclass
class MatchResult:
    job_id: int
    matched: bool
    compatibility: float
    reason: str = ""
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)
    # "strong" (>=75), "good" (50-74), "stretch" (30-49), "" below threshold.
    tier: str = ""


ProgressCallback = Callable[[int, int, int, int, int], None]
"""(jobs_scanned, total_jobs, matches_so_far, batch_num, total_batches)"""


def tier_for(compatibility: float) -> str:
    """Bucket a final compatibility score into a user-facing tier."""
    if compatibility >= TIER_STRONG_MIN:
        return "strong"
    if compatibility >= TIER_GOOD_MIN:
        return "good"
    if compatibility >= MATCH_THRESHOLD:
        return "stretch"
    return ""


def _normalise_gender(value: str | None) -> str | None:
    if not value:
        return None
    v = str(value).strip().lower()
    if v in {"f", "female", "woman", "lady"}:
        return "female"
    if v in {"m", "male", "man", "gentleman"}:
        return "male"
    return None


def _job_gender_requirement(job: JobSummary) -> str | None:
    text = " ".join(
        part for part in [
            job.title,
            job.role,
            job.description,
            job.requirements,
            job.certifications_required,
            job.languages_required,
        ] if part
    ).lower()
    if not text:
        return None

    female_req = any(p.search(text) for p in _FEMALE_REQ_PATTERNS)
    male_req = any(p.search(text) for p in _MALE_REQ_PATTERNS)

    if female_req and not male_req:
        return "female"
    if male_req and not female_req:
        return "male"
    return None


def _gender_mismatch_result(job_id: int, required_gender: str) -> MatchResult:
    return MatchResult(
        job_id=job_id,
        matched=False,
        compatibility=0.0,
        reason=f"Filtered out: job specifies {required_gender} candidates.",
        gaps=[f"Gender requirement mismatch ({required_gender} only)."],
    )


# ── Deterministic prefilter ──────────────────────────────────────────────────
# Runs before any LLM spend: hard-excludes gender mismatches and keeps only
# the top N jobs by role relatedness, location overlap and recency.

_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")
_ASAP_RE = re.compile(r"\b(asap|immediate(?:ly)?|now)\b")
_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y",
    "%B %Y", "%b %Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y",
)
_ANYWHERE_TERMS = {"worldwide", "anywhere", "global", "flexible"}
# Relative weights for the deterministic composite; renormalised over
# whichever factors actually have data. Role is the heaviest factor — it is
# the primary filter, everything else is a tiebreaker.
_DETERMINISTIC_WEIGHTS = {
    "role": 0.4,
    "salary": 0.2,
    "experience": 0.2,
    "availability": 0.1,
    "location": 0.1,
}


def _parse_number(text: str | None) -> float | None:
    if text is None:
        return None
    match = _NUMBER_RE.search(str(text).replace(",", ""))
    return float(match.group(0)) if match else None


def _parse_date_guess(text: str | None) -> date | None:
    if not text:
        return None
    t = str(text).strip()
    if not t:
        return None
    if _ASAP_RE.search(t.lower()):
        return datetime.now(timezone.utc).date()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(t, fmt).date()
        except ValueError:
            continue
    return None


def _candidate_location_terms(candidate: CandidateProfile) -> list[str]:
    terms: list[str] = []
    for raw in (candidate.location, candidate.preferred_locations):
        if not raw:
            continue
        for part in re.split(r"[,/;]", raw):
            part = part.strip().lower()
            if len(part) >= 3 and part not in terms:
                terms.append(part)
    return terms


def _location_score(candidate: CandidateProfile, job: JobSummary) -> float | None:
    """100 on overlap, 40 otherwise (yachting is global), None if data missing."""
    terms = _candidate_location_terms(candidate)
    job_loc = (job.location or "").strip().lower()
    if not terms or not job_loc:
        return None
    if job_loc in _ANYWHERE_TERMS or any(t in _ANYWHERE_TERMS for t in terms):
        return 100.0
    for term in terms:
        if term in job_loc or job_loc in term:
            return 100.0
    return 40.0


def _salary_score(candidate: CandidateProfile, job: JobSummary) -> float | None:
    """How well the job's top pay covers the candidate's minimum (currency-naive)."""
    candidate_min = _parse_number(candidate.salary_min)
    job_top = job.salary_max if job.salary_max is not None else job.salary_min
    if not candidate_min or candidate_min <= 0 or not job_top or job_top <= 0:
        return None
    if job_top >= candidate_min:
        return 100.0
    return max(0.0, 100.0 * job_top / candidate_min)


def _experience_score(candidate: CandidateProfile, job: JobSummary) -> float | None:
    candidate_years = _parse_number(candidate.years_experience)
    required = job.experience_required_years
    if candidate_years is None or required is None:
        return None
    if required <= 0 or candidate_years >= required:
        return 100.0
    return max(0.0, 100.0 * candidate_years / required)


def _availability_score(candidate: CandidateProfile, job: JobSummary) -> float | None:
    available = _parse_date_guess(candidate.available_from)
    start = _parse_date_guess(job.start_date)
    if available is None or start is None:
        return None
    gap_days = (available - start).days
    if gap_days <= 0:
        return 100.0
    # Lose 2 points per day the candidate would keep the boat waiting.
    return max(0.0, 100.0 - gap_days * 2.0)


def _role_score(candidate: CandidateProfile, job: JobSummary) -> float | None:
    """100 same role, 70 adjacent seniority, 40 same department, 0 cross-department.

    None when either side is unknown to the taxonomy — an unrecognised role must
    not be punished, only a confirmed cross-department mismatch.
    """
    if not normalize_roles(candidate.desired_role) or not normalize_roles(_job_role_text(job)):
        return None
    return 100.0 * roles_related(candidate.desired_role, _job_role_text(job))


def _deterministic_factors(candidate: CandidateProfile, job: JobSummary) -> dict[str, float]:
    """Sub-scores (0-100) computed from structured fields; missing data = absent key."""
    scores = {
        "role": _role_score(candidate, job),
        "salary": _salary_score(candidate, job),
        "experience": _experience_score(candidate, job),
        "availability": _availability_score(candidate, job),
        "location": _location_score(candidate, job),
    }
    return {name: value for name, value in scores.items() if value is not None}


def _deterministic_composite(factors: dict[str, float]) -> float | None:
    """Weighted mean of available sub-scores; None when nothing is computable."""
    if not factors:
        return None
    total_weight = sum(_DETERMINISTIC_WEIGHTS[name] for name in factors)
    return sum(_DETERMINISTIC_WEIGHTS[name] * value for name, value in factors.items()) / total_weight


def _is_priority_job(job: JobSummary) -> bool:
    return job.status == "priority" or job.urgent_hire


def _recency_score(job: JobSummary, now: datetime) -> float:
    created = job.created_at
    if created is None:
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    age_days = max(0.0, (now - created).total_seconds() / 86400.0)
    return max(0.0, 1.0 - age_days / 30.0)


def _job_role_text(job: JobSummary) -> str:
    return f"{job.role or ''} {job.title or ''}".strip()


def prefilter_jobs(
    candidate: CandidateProfile,
    jobs: list[JobSummary],
    top_n: int = PREFILTER_TOP_N,
) -> tuple[list[JobSummary], list[MatchResult]]:
    """Cheap deterministic pre-filter run before any LLM spend.

    Returns (jobs worth sending to the LLM, results for hard-excluded jobs).
    Gender-mismatched jobs are excluded outright (with an explanatory
    MatchResult, so nothing is silently dropped). The rest are ranked by role
    relatedness (heaviest), location overlap and recency, keeping the top N.
    Priority/urgent-hire jobs are always kept. If the taxonomy recognises too
    few of the jobs (< PREFILTER_MIN_ROLE_MATCHES role-related), it falls back
    to the most recent N so an unknown role never blanks out matching.
    """
    excluded: list[MatchResult] = []
    candidate_gender = _normalise_gender(candidate.sex)
    eligible: list[JobSummary] = []
    for job in jobs:
        if candidate_gender:
            required = _job_gender_requirement(job)
            if required and required != candidate_gender:
                excluded.append(_gender_mismatch_result(job.job_id, required))
                continue
        eligible.append(job)

    if len(eligible) <= top_n:
        return eligible, excluded

    now = datetime.now(timezone.utc)
    scored: list[tuple[float, int, JobSummary]] = []
    role_related_count = 0
    for order, job in enumerate(eligible):
        relatedness = roles_related(candidate.desired_role, _job_role_text(job))
        if relatedness > 0:
            role_related_count += 1
        location = _location_score(candidate, job)
        location_component = 1.0 if location == 100.0 else 0.0
        score = 0.6 * relatedness + 0.2 * location_component + 0.2 * _recency_score(job, now)
        scored.append((score, order, job))

    if role_related_count < PREFILTER_MIN_ROLE_MATCHES:
        log.info(
            "Prefilter fallback | role-related=%d < %d — keeping %d most recent jobs",
            role_related_count, PREFILTER_MIN_ROLE_MATCHES, top_n,
        )
        by_recency = sorted(eligible, key=lambda j: _recency_score(j, now), reverse=True)
        selected = by_recency[:top_n]
    else:
        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = [job for _, _, job in scored[:top_n]]

    selected_ids = {j.job_id for j in selected}
    for job in eligible:
        if _is_priority_job(job) and job.job_id not in selected_ids:
            selected.append(job)
            selected_ids.add(job.job_id)

    log.info(
        "Prefilter | jobs=%d | eligible=%d | selected=%d | gender_excluded=%d | role_related=%d",
        len(jobs), len(eligible), len(selected), len(excluded), role_related_count,
    )
    return selected, excluded


# ── Score finalisation ───────────────────────────────────────────────────────

def _finalize_result(result: MatchResult, job: JobSummary, candidate: CandidateProfile) -> MatchResult:
    """Blend the LLM score with deterministic sub-scores, boost priority jobs.

    final = 0.65 * llm + 0.35 * deterministic composite (when structured data
    exists — factors with missing data are skipped and weights renormalised).
    The priority/urgent-hire +10 boost is applied here, in code, not by the LLM.
    Taxonomy-confirmed cross-department jobs are capped at ROLE_MISMATCH_CAP
    after the blend and boost, so pay/availability can never lift a chef job
    over the match threshold for a deckhand.
    """
    factors = _deterministic_factors(candidate, job)
    composite = _deterministic_composite(factors)
    if composite is not None:
        result.compatibility = float(round(
            LLM_BLEND_WEIGHT * result.compatibility
            + DETERMINISTIC_BLEND_WEIGHT * composite
        ))
        for name, value in factors.items():
            result.factor_scores.setdefault(f"det_{name}", round(value, 1))
    if _is_priority_job(job):
        result.compatibility += PRIORITY_BOOST
    if factors.get("role") == 0.0:
        result.compatibility = min(result.compatibility, ROLE_MISMATCH_CAP)
    result.compatibility = max(0.0, min(100.0, result.compatibility))
    result.matched = result.compatibility >= MATCH_THRESHOLD
    result.tier = tier_for(result.compatibility)
    return result


def _deterministic_fallback_result(candidate: CandidateProfile, job: JobSummary) -> MatchResult:
    """Result for a job the LLM never scored (even after retry) — no silent drops."""
    factors = _deterministic_factors(candidate, job)
    composite = _deterministic_composite(factors)
    result = MatchResult(
        job_id=job.job_id,
        matched=False,
        compatibility=float(round(composite)) if composite is not None else 0.0,
        reason="Scored on profile fit — the AI did not return a score for this job.",
        factor_scores={f"det_{name}": round(value, 1) for name, value in factors.items()},
    )
    if _is_priority_job(job):
        result.compatibility = min(100.0, result.compatibility + PRIORITY_BOOST)
    if factors.get("role") == 0.0:
        result.compatibility = min(result.compatibility, ROLE_MISMATCH_CAP)
    result.matched = result.compatibility >= MATCH_THRESHOLD
    result.tier = tier_for(result.compatibility)
    return result


# ── OpenAI caller ────────────────────────────────────────────────────────────

def _match_max_tokens(job_count: int) -> int:
    """Size completion budget so a full batch JSON response is not truncated."""
    return max(_MATCH_MIN_MAX_TOKENS, job_count * _MATCH_MAX_TOKENS_PER_JOB)


def _call_openai(api_key: str, model: str, prompt: str, *, job_count: int) -> str:
    try:
        return call_openai(
            api_key=api_key,
            messages=[{"role": "user", "content": prompt}],
            model=model,
            max_tokens=_match_max_tokens(job_count),
            temperature=0.3,
            response_format={"type": "json_object"},
            timeout=_MATCH_REQUEST_TIMEOUT,
        )
    except AIClientError as exc:
        raise RuntimeError(str(exc)) from exc


# ── Prompt builder ───────────────────────────────────────────────────────────

def _build_prompt(candidate: CandidateProfile, jobs: list[JobSummary]) -> str:
    job_ids = [j.job_id for j in jobs]

    candidate_dict: dict[str, Any] = {
        "name": f"{candidate.first_name} {candidate.last_name}".strip(),
        "sex": candidate.sex,
        "desired_role": candidate.desired_role,
        "current_location": candidate.location,
        "preferred_locations": candidate.preferred_locations,
        "nationality": candidate.nationality,
        "years_experience": candidate.years_experience,
        "salary_min": candidate.salary_min,
        "salary_max": candidate.salary_max,
        "contract_type": candidate.contract_type,
        "rotation_preference": candidate.rotation_preference,
        "available_from": candidate.available_from,
        "certifications": candidate.certifications,
        "languages": candidate.languages,
        "bio": candidate.bio[:500] if candidate.bio else "",
        "job_history": candidate.job_history[:8],
        "document_summary": candidate.document_summary[:800] if candidate.document_summary else "",
    }

    jobs_list = []
    for j in jobs:
        job_entry: dict[str, Any] = {
            "job_id": j.job_id,
            "title": j.title,
            "role": j.role,
            "department": j.department,
            "location": j.location,
            "yacht_type": j.yacht_type,
            "yacht_length_m": j.yacht_length_m,
            "start_date": j.start_date,
            "contract_type": j.contract_type,
            "rotation": j.rotation,
            "season": j.season,
            "salary_min": j.salary_min,
            "salary_max": j.salary_max,
            "salary_currency": j.salary_currency,
            "experience_required_years": j.experience_required_years,
            "minimum_license": j.minimum_license,
            "rank_level": j.rank_level,
            "certifications_required": j.certifications_required,
            "languages_required": j.languages_required,
            "description": (j.description or "")[:400],
            "requirements": (j.requirements or "")[:300],
            "responsibilities": (j.responsibilities or "")[:300],
        }
        if getattr(j, "status", None) == "priority":
            job_entry["status"] = "priority"
        if j.urgent_hire:
            job_entry["urgent_hire"] = True
        jobs_list.append(job_entry)

    payload = {
        "rules": {
            "priority_order": [
                "role", "experience", "certifications",
                "location", "pay", "contract_length", "languages",
            ],
            "matched_threshold": MATCH_THRESHOLD,
            "instructions": [
                "ROLE DEPARTMENT is the primary filter. The job must be in the same department or a closely related one.",
                "Departments: Deck, Interior/Stew, Engine, Galley, Bridge, Medical, Pursers.",
                "Cross-department mismatches (e.g. desired=Deckhand, job=Stewardess) must get compatibility <= 15.",
                "Same-department roles at different seniority levels ARE valid matches — score them 35-70 depending on experience gap. E.g. a Deckhand with 3+ years should match Bosun roles at 45-55.",
                "Adjacent roles within the same department should score highly: Bosun↔Deckhand, Chief Stew↔Stewardess, 2nd Engineer↔Chief Engineer, Sous Chef↔Head Chef.",
                "Dual roles like Deck/Stew should match BOTH Deck and Interior departments.",
                f"Set matched=true if compatibility >= {MATCH_THRESHOLD}. Be GENEROUS — if the candidate could reasonably apply and have a shot, mark it matched.",
                "Use the candidate's bio, job_history, and document_summary as the PRIMARY evidence of capability. Recent job history (last 2 roles) should carry the most weight — if they did the role before, score 70+.",
                "If the candidate held the exact same role on a previous vessel, that is a STRONG match (80+) regardless of other factors.",
                "Do NOT over-penalise for missing certifications unless the job explicitly requires them for safety-critical roles (Captain, Engineer, Officer). Partial cert matches (e.g. has STCW but not ENG1) should only reduce by 5-10 points.",
                "Location flexibility: yachting is a global industry — location mismatches should only reduce by 3-5 points, not disqualify.",
                "Pay mismatches: only reduce if the job pay is drastically (>50%) below the candidate's minimum.",
                "If the candidate has relevant experience for the role, that should outweigh minor gaps in listed requirements.",
                "AIM to find at least 5+ matches if the candidate has any relevant experience. Be helpful, not punitive.",
                "Gender requirements are strict. If a job explicitly specifies male/female-only (or uses gendered role labels like stewardess/steward), opposite-gender candidates must be matched=false with compatibility <= 5.",
                "Output ONLY raw JSON. No markdown fences, no extra text.",
                f"You MUST return exactly one entry for every job_id: {json.dumps(job_ids)}. Copy each job_id verbatim.",
                "Each entry: job_id (integer, verbatim), matched (boolean), compatibility (integer 0-100), reason (1-2 sentences), strengths (list), gaps (list), factor_scores (object).",
                "factor_scores keys: role, location, pay, contract, skills, certifications, experience — all integers 0-100.",
            ],
        },
        "candidate": candidate_dict,
        "jobs": jobs_list,
        "response_schema": {
            "matched_jobs": [{
                "job_id": "integer (verbatim from input)",
                "matched": "boolean",
                "compatibility": "integer 0-100",
                "reason": "string",
                "strengths": ["string"],
                "gaps": ["string"],
                "factor_scores": {
                    "role": "0-100", "location": "0-100", "pay": "0-100",
                    "contract": "0-100", "skills": "0-100",
                    "certifications": "0-100", "experience": "0-100",
                },
            }],
        },
    }

    return (
        "You are a superyacht crew job matching engine. "
        "Your goal is to help candidates find every job they could realistically apply for. "
        "Be thorough and generous — if there is a reasonable fit, surface it.\n"
        "CRITICAL: Output ONLY raw JSON matching the schema. No markdown code fences.\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


# ── Response parser ──────────────────────────────────────────────────────────

def _extract_json(text: str) -> str:
    if not text:
        return "{}"
    text = text.strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    if start > 0:
        text = text[start:]
    return text


def _parse_batch(response_text: str, valid_job_ids: set[int]) -> list[MatchResult]:
    cleaned = _extract_json(response_text)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError:
        log.error("LLM returned invalid JSON | raw=%s", (response_text or "")[:500])
        return []

    raw_matches = payload.get("matched_jobs", [])
    if not isinstance(raw_matches, list):
        log.error("matched_jobs is not a list | type=%s", type(raw_matches).__name__)
        return []

    results: list[MatchResult] = []
    for item in raw_matches:
        try:
            job_id = int(item.get("job_id", 0))
            if job_id not in valid_job_ids:
                log.warning("LLM returned unknown job_id=%s, skipping", job_id)
                continue
            compatibility = max(0.0, min(100.0, float(item.get("compatibility", 0))))
            matched = compatibility >= MATCH_THRESHOLD
            results.append(MatchResult(
                job_id=job_id,
                matched=matched,
                compatibility=compatibility,
                reason=str(item.get("reason", "")),
                strengths=[str(x) for x in (item.get("strengths") or [])],
                gaps=[str(x) for x in (item.get("gaps") or [])],
                factor_scores={
                    str(k): max(0.0, min(100.0, float(v)))
                    for k, v in (item.get("factor_scores") or {}).items()
                },
            ))
        except (TypeError, ValueError, AttributeError) as exc:
            log.warning("Skipping malformed match item: %s", exc)
    return results


# ── Core matching function ───────────────────────────────────────────────────

def match_candidate_to_jobs(
    *,
    api_key: str,
    model: str,
    candidate: CandidateProfile,
    jobs: list[JobSummary],
    batch_size: int = BATCH_SIZE,
    on_progress: ProgressCallback | None = None,
) -> list[MatchResult]:
    """Score the candidate against the job board.

    A deterministic prefilter (role taxonomy, location, recency, hard gender
    exclusion) picks the top jobs first so only those hit the LLM. Batches are
    processed concurrently (up to MAX_WORKERS threads); LLM scores are blended
    with deterministic sub-scores and jobs the LLM skips are retried once,
    then scored deterministically — nothing is silently dropped. Returns all
    results sorted by compatibility descending.
    """
    if not jobs:
        return []

    llm_jobs, excluded_results = prefilter_jobs(candidate, jobs)
    jobs_by_id = {j.job_id: j for j in llm_jobs}

    total_jobs = len(llm_jobs)
    batches = [llm_jobs[i:i + batch_size] for i in range(0, total_jobs, batch_size)]
    total_batches = len(batches)
    log.info("Matching start | candidate=%s | jobs=%d (of %d after prefilter) | batches=%d",
             candidate.user_key, total_jobs, len(jobs), total_batches)

    all_results: list[MatchResult] = []
    jobs_scanned = 0

    def _process_batch(batch_idx: int, batch: list[JobSummary]) -> tuple[int, list[MatchResult]]:
        batch_ids = {j.job_id for j in batch}
        prompt = _build_prompt(candidate, batch)
        response_text = _call_openai(api_key, model, prompt, job_count=len(batch))
        batch_results = _parse_batch(response_text, batch_ids)
        seen = {r.job_id for r in batch_results}

        missing = [j for j in batch if j.job_id not in seen]
        if missing:
            log.warning(
                "Batch %d missing %d job_ids — retrying once | ids=%s",
                batch_idx, len(missing), [j.job_id for j in missing],
            )
            try:
                retry_text = _call_openai(
                    api_key, model,
                    _build_prompt(candidate, missing),
                    job_count=len(missing),
                )
                for r in _parse_batch(retry_text, {j.job_id for j in missing}):
                    if r.job_id not in seen:
                        batch_results.append(r)
                        seen.add(r.job_id)
            except RuntimeError:
                log.exception("Batch %d retry for missing job_ids failed", batch_idx)

        for r in batch_results:
            _finalize_result(r, jobs_by_id[r.job_id], candidate)
        for job in batch:
            if job.job_id not in seen:
                log.warning(
                    "Batch %d job_id=%d still unscored after retry — using deterministic score",
                    batch_idx, job.job_id,
                )
                batch_results.append(_deterministic_fallback_result(candidate, job))
        return batch_idx, batch_results

    if len(batches) <= 1:
        for batch_idx, batch in enumerate(batches, start=1):
            log.info("Processing batch %d/%d (%d jobs)", batch_idx, total_batches, len(batch))
            try:
                _, batch_results = _process_batch(batch_idx, batch)
            except RuntimeError:
                log.exception("Batch %d failed — skipping", batch_idx)
                batch_results = []

            all_results.extend(batch_results)
            jobs_scanned += len(batch)
            log.info("Batch %d | parsed=%d | matched=%d",
                     batch_idx, len(batch_results),
                     sum(1 for r in batch_results if r.matched))
            if on_progress:
                on_progress(jobs_scanned, total_jobs,
                            sum(1 for r in all_results if r.matched),
                            batch_idx, total_batches)
    else:
        batch_results_map: dict[int, list[MatchResult]] = {}
        with ThreadPoolExecutor(max_workers=min(len(batches), MAX_WORKERS)) as pool:
            futures = {
                pool.submit(_process_batch, i, batch): (i, batch)
                for i, batch in enumerate(batches, start=1)
            }
            for future in as_completed(futures):
                idx, batch = futures[future]
                try:
                    _, results = future.result()
                    batch_results_map[idx] = results
                except Exception:
                    log.exception("Batch %d failed — skipping", idx)
                    batch_results_map[idx] = []

        for batch_idx in range(1, total_batches + 1):
            batch_res = batch_results_map.get(batch_idx, [])
            all_results.extend(batch_res)
            jobs_scanned += len(batches[batch_idx - 1])
            log.info("Batch %d | parsed=%d | matched=%d",
                     batch_idx, len(batch_res),
                     sum(1 for r in batch_res if r.matched))
            if on_progress:
                on_progress(jobs_scanned, total_jobs,
                            sum(1 for r in all_results if r.matched),
                            batch_idx, total_batches)

    all_results.extend(excluded_results)

    deduped: dict[int, MatchResult] = {}
    for r in all_results:
        existing = deduped.get(r.job_id)
        if existing is None or r.compatibility > existing.compatibility:
            deduped[r.job_id] = r

    results = sorted(deduped.values(), key=lambda x: x.compatibility, reverse=True)
    matched_count = sum(1 for r in results if r.matched)
    log.info("Matching complete | candidate=%s | total=%d | matched=%d | gender_filtered=%d | top=%.0f",
             candidate.user_key, len(results), matched_count, len(excluded_results),
             results[0].compatibility if results else 0)
    return results
