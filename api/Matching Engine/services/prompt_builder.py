import json

from models.job import JobPosting
from models.schemas import jobs_to_dict, user_to_dict
from models.user import UserProfile


class PromptBuilder:
    def build(self, user: UserProfile, jobs: list[JobPosting]) -> str:
        job_id_list = [j.job_id for j in jobs]

        payload = {
            "rules": {
                "priority_order": ["role", "location", "pay", "length", "certifications", "experience", "languages"],
                "matched_threshold": 60,
                "instructions": [
                    "ROLE IS A HARD GATE. The job role must be the same department AND seniority as the user's desired_role.",
                    "If the role does not match, set matched=false and compatibility <= 20 — no exceptions.",
                    "Examples of disqualifying mismatches: desired=Deckhand → job=Stewardess; desired=Chef → job=Engineer; desired=Captain → job=Bosun.",
                    "A role is only acceptable if it is in the exact same department (Deck, Interior/Stew, Engine, Galley, Bridge) AND within one seniority level.",
                    "Set matched=true ONLY if compatibility >= 60. Below 60 always set matched=false.",
                    "Compatibility should reflect true real-world hirability — be honest and conservative.",
                    "Use the user's bio and job_history as primary evidence of real-world experience — weight this at least as heavily as stated years_experience.",
                    "If the job requires senior experience (Chief, Captain, HOD) and the user lacks it in their history, penalise heavily.",
                    "Required certifications are a near-hard requirement for officer and senior roles. Missing a required cert reduces compatibility by at least 20 points.",
                    "If the job pay is more than 30% below the user's desired_pay_min, reduce compatibility by 15 points.",
                    "Prefer location alignment. If neither preferred_locations nor current_location overlaps with the job location region, reduce compatibility by 10 points.",
                    "Return JSON only. No markdown fences, no extra text, no commentary.",
                    f"You MUST return an entry for EVERY job. The valid job_id values are exactly: {json.dumps(job_id_list)}. Copy each job_id verbatim — do not invent, modify, or omit any.",
                    "Every entry must have: job_id(string, verbatim from input), matched(boolean), compatibility(integer 0-100), reason(1-2 sentences), strengths(list of strings), gaps(list of strings), factor_scores(object).",
                    "factor_scores keys: role, location, pay, length, skills, certifications, experience — all integers 0-100.",
                    "reason must explain the single most important factor — be specific, not generic.",
                ],
            },
            "user": user_to_dict(user),
            "jobs": jobs_to_dict(jobs),
            "response_schema": {
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
            },
        }
        return (
            "You are a strict superyacht crew job matching engine. Protect candidates from wasted applications — only surface genuinely strong fits.\n"
            "CRITICAL: Output ONLY raw JSON matching the schema below. No markdown code fences. No commentary before or after.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

