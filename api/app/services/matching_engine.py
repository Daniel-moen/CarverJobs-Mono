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
from typing import Any, Callable

from app.services.ai_client import AIClientError, call_openai

log = logging.getLogger("carver.matching_engine")

BATCH_SIZE = 8
MATCH_THRESHOLD = 30
MAX_WORKERS = 4
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
    certifications_required: str = ""
    languages_required: str = ""
    description: str = ""
    status: str = "open"


@dataclass
class MatchResult:
    job_id: int
    matched: bool
    compatibility: float
    reason: str = ""
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)


ProgressCallback = Callable[[int, int, int, int, int], None]
"""(jobs_scanned, total_jobs, matches_so_far, batch_num, total_batches)"""


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
            "certifications_required": j.certifications_required,
            "languages_required": j.languages_required,
            "description": (j.description or "")[:400],
        }
        if getattr(j, "status", None) == "priority":
            job_entry["status"] = "priority"
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
                "Jobs with status=priority should receive a +10 compatibility boost (they are urgent hires looking for crew now).",
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
    """Score every job in the DB against the candidate.

    Jobs are split into batches and processed concurrently (up to MAX_WORKERS
    threads). Returns all results sorted by compatibility descending.
    """
    if not jobs:
        return []

    total_jobs = len(jobs)
    batches = [jobs[i:i + batch_size] for i in range(0, total_jobs, batch_size)]
    total_batches = len(batches)
    log.info("Matching start | candidate=%s | jobs=%d | batches=%d",
             candidate.user_key, total_jobs, total_batches)

    valid_ids = {j.job_id for j in jobs}
    all_results: list[MatchResult] = []
    jobs_scanned = 0

    def _process_batch(batch_idx: int, batch: list[JobSummary]) -> tuple[int, list[MatchResult]]:
        prompt = _build_prompt(candidate, batch)
        response_text = _call_openai(api_key, model, prompt, job_count=len(batch))
        batch_results = _parse_batch(response_text, valid_ids)
        if len(batch_results) < len(batch):
            log.warning(
                "Batch %d incomplete parse | expected=%d | parsed=%d",
                batch_idx, len(batch), len(batch_results),
            )
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

    deduped: dict[int, MatchResult] = {}
    for r in all_results:
        existing = deduped.get(r.job_id)
        if existing is None or r.compatibility > existing.compatibility:
            deduped[r.job_id] = r

    candidate_gender = _normalise_gender(candidate.sex)
    jobs_by_id = {j.job_id: j for j in jobs}
    gender_filtered = 0
    if candidate_gender:
        for result in deduped.values():
            job = jobs_by_id.get(result.job_id)
            if not job:
                continue
            required_gender = _job_gender_requirement(job)
            if required_gender and required_gender != candidate_gender:
                gender_filtered += 1
                result.matched = False
                result.compatibility = min(result.compatibility, 5.0)
                result.reason = f"Filtered out: job specifies {required_gender} candidates."
                result.strengths = []
                result.gaps = [f"Gender requirement mismatch ({required_gender} only)."]
                result.factor_scores = {}

    results = sorted(deduped.values(), key=lambda x: x.compatibility, reverse=True)
    matched_count = sum(1 for r in results if r.matched)
    log.info("Matching complete | candidate=%s | total=%d | matched=%d | gender_filtered=%d | top=%.0f",
             candidate.user_key, len(results), matched_count, gender_filtered,
             results[0].compatibility if results else 0)
    return results
