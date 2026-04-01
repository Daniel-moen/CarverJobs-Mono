"""Unified Matching Engine — batches all jobs against a candidate via OpenAI.

Fetches every open/priority job from the database, splits them into batches,
scores each batch concurrently with the LLM, then merges and deduplicates.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("carver.matching_engine")

BATCH_SIZE = 10
MATCH_THRESHOLD = 35
MAX_WORKERS = 4
_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)
_RETRYABLE_CODES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 1.5


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


# ── OpenAI caller (stdlib only — no extra deps) ─────────────────────────────

def _call_openai(api_key: str, model: str, prompt: str) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "response_format": {"type": "json_object"},
    }
    data = json.dumps(body).encode("utf-8")
    url = "https://api.openai.com/v1/chat/completions"

    last_error: Exception | None = None
    for attempt in range(_MAX_RETRIES):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                raw = resp.read().decode("utf-8")
            parsed = json.loads(raw)
            return parsed["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in _RETRYABLE_CODES and attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2 ** attempt)
                log.warning("OpenAI %d (attempt %d/%d), retrying in %.1fs",
                            exc.code, attempt + 1, _MAX_RETRIES, delay)
                time.sleep(delay)
                continue
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"OpenAI HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            last_error = exc
            if attempt < _MAX_RETRIES - 1:
                delay = _BASE_DELAY * (2 ** attempt)
                log.warning("OpenAI connection error (attempt %d/%d): %s",
                            attempt + 1, _MAX_RETRIES, exc.reason)
                time.sleep(delay)
                continue
            raise RuntimeError(f"OpenAI connection error: {exc.reason}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("Unexpected OpenAI response structure") from exc

    raise RuntimeError(f"OpenAI failed after {_MAX_RETRIES} attempts") from last_error


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
        jobs_list.append({
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
        })

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
                "Same-department roles at different seniority levels ARE valid matches — score them 30-65 depending on experience gap.",
                "Dual roles like Deck/Stew should match BOTH Deck and Interior departments.",
                f"Set matched=true if compatibility >= {MATCH_THRESHOLD}. Be GENEROUS — if the candidate could reasonably apply and have a shot, mark it matched.",
                "Use the candidate's bio, job_history, and document_summary as the primary evidence of capability. If their history or documents show they can do the job, score high.",
                "Do NOT over-penalise for missing certifications unless the job explicitly requires them for safety-critical roles (Captain, Engineer, Officer).",
                "Location flexibility: yachting is a global industry — location mismatches should only reduce by 3-5 points, not disqualify.",
                "Pay mismatches: only reduce if the job pay is drastically (>50%) below the candidate's minimum.",
                "If the candidate has relevant experience for the role, that should outweigh minor gaps in listed requirements.",
                "AIM to find at least 5+ matches if the candidate has any relevant experience. Be helpful, not punitive.",
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
            results.append(MatchResult(
                job_id=job_id,
                matched=bool(item.get("matched", False)),
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
        response_text = _call_openai(api_key, model, prompt)
        return batch_idx, _parse_batch(response_text, valid_ids)

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

    results = sorted(deduped.values(), key=lambda x: x.compatibility, reverse=True)
    matched_count = sum(1 for r in results if r.matched)
    log.info("Matching complete | candidate=%s | total=%d | matched=%d | top=%.0f",
             candidate.user_key, len(results), matched_count,
             results[0].compatibility if results else 0)
    return results
