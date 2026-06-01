import json

from models.job import JobPosting
from models.schemas import jobs_to_dict, user_to_dict
from models.user import UserProfile

# Static instruction/schema payload. This never changes between batches or users,
# so it lives in the system message and forms a stable, cacheable prompt prefix.
_RULES = {
    "priority_order": ["role", "location", "pay", "length", "certifications", "experience", "languages"],
    "matched_threshold": 60,
    "instructions": [
        "ROLE is the most important factor. The job role should be in the same department as the user's desired_role.",
        "Cross-department mismatches (e.g. desired=Deckhand → job=Stewardess, desired=Chef → job=Engineer) should get compatibility <= 15.",
        "Same-department but different seniority (e.g. desired=Deckhand → job=Bosun) can still score 25-45 depending on experience.",
        "Departments: Deck, Interior/Stew, Engine, Galley, Bridge, Medical, Pursers.",
        "Set matched=true ONLY if compatibility >= 60. Below 60 always set matched=false.",
        "Compatibility should reflect true real-world hirability — be realistic but not overly punitive.",
        "Use the user's bio and job_history as primary evidence of real-world experience — weight this at least as heavily as stated years_experience.",
        "If the job requires senior experience (Chief, Captain, HOD) and the user lacks it in their history, penalise heavily.",
        "Required certifications are a near-hard requirement for officer and senior roles. Missing a required cert reduces compatibility by at least 15 points.",
        "If the job pay is more than 30% below the user's desired_pay_min, reduce compatibility by 10 points.",
        "Prefer location alignment. If neither preferred_locations nor current_location overlaps with the job location region, reduce compatibility by 5 points.",
        "Return JSON only. No markdown fences, no extra text, no commentary.",
        "You MUST return an entry for EVERY job in the input. Use the valid_job_ids list provided in the user message and copy each job_id verbatim — do not invent, modify, or omit any.",
        "Every entry must have: job_id(string, verbatim from input), matched(boolean), compatibility(integer 0-100), reason(1-2 sentences), strengths(list of strings), gaps(list of strings), factor_scores(object).",
        "factor_scores keys: role, location, pay, length, skills, certifications, experience — all integers 0-100.",
        "reason must explain the single most important factor — be specific, not generic.",
    ],
}

_RESPONSE_SCHEMA = {
    "matched_jobs": [
        {
            "job_id": "string (verbatim from input)",
            "matched": "boolean",
            "compatibility": "integer 0-100",
            "reason": "string",
            "strengths": ["string"],
            "gaps": ["string"],
            "factor_scores": {
                "role": "integer 0-100",
                "location": "integer 0-100",
                "pay": "integer 0-100",
                "length": "integer 0-100",
                "skills": "integer 0-100",
                "certifications": "integer 0-100",
                "experience": "integer 0-100",
            },
        }
    ]
}


class PromptBuilder:
    def __init__(self) -> None:
        # Precompute the static system prompt once — identical across every call,
        # so providers can cache this prefix and we avoid rebuilding it per batch.
        self._system_prompt = (
            "You are a strict superyacht crew job matching engine. Protect candidates from wasted applications — only surface genuinely strong fits.\n"
            "CRITICAL: Output ONLY raw JSON matching the schema below. No markdown code fences. No commentary before or after.\n"
            f"{json.dumps({'rules': _RULES, 'response_schema': _RESPONSE_SCHEMA}, ensure_ascii=False)}"
        )

    def build(self, user: UserProfile, jobs: list[JobPosting]) -> tuple[str, str]:
        """Return (system_prompt, user_prompt).

        The system prompt is static and cacheable; the user prompt carries the
        per-request user profile, jobs, and the exact set of valid job_ids.
        """
        user_payload = {
            "user": user_to_dict(user),
            "jobs": jobs_to_dict(jobs),
            "valid_job_ids": [j.job_id for j in jobs],
        }
        user_prompt = json.dumps(user_payload, ensure_ascii=False)
        return self._system_prompt, user_prompt
