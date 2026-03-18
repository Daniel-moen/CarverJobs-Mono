import json

from models.job import JobPosting
from models.schemas import jobs_to_dict, user_to_dict
from models.user import UserProfile


class PromptBuilder:
    def build(self, user: UserProfile, jobs: list[JobPosting]) -> str:
        payload = {
            "rules": {
                "priority_order": ["role", "location", "pay", "length", "certifications", "experience", "languages"],
                "matched_threshold": 75,
                "instructions": [
                    # Role — hard gate
                    "ROLE IS A HARD GATE. The job role must be the same department AND seniority as the user's desired_role.",
                    "If the role does not match, set matched=false and compatibility <= 20 — no exceptions.",
                    "Examples of disqualifying mismatches: desired=Deckhand → job=Stewardess; desired=Chef → job=Engineer; desired=Captain → job=Bosun.",
                    "A role is only acceptable if it is in the exact same department (Deck, Interior/Stew, Engine, Galley, Bridge) AND within one seniority level.",
                    # Matched threshold
                    "Set matched=true ONLY if compatibility >= 75. Below 75 always set matched=false.",
                    "Compatibility should reflect true real-world hirability — be honest and conservative.",
                    # Experience
                    "Use the user's bio and job_history as primary evidence of real-world experience — weight this at least as heavily as stated years_experience.",
                    "If the job requires senior experience (Chief, Captain, HOD) and the user lacks it in their history, penalise heavily.",
                    # Certifications
                    "Required certifications are a near-hard requirement for officer and senior roles. Missing a required cert reduces compatibility by at least 20 points.",
                    # Pay
                    "If the job pay is more than 30% below the user's desired_pay_min, reduce compatibility by 15 points.",
                    # Location
                    "Prefer location alignment. If neither preferred_locations nor current_location overlaps with the job location region, reduce compatibility by 10 points.",
                    # Output format
                    "Return JSON only. No markdown, no extra text.",
                    "Every job must have: matched(boolean), compatibility(0-100 integer), reason(1-2 sentences), strengths(list), gaps(list), factor_scores.",
                    "factor_scores keys: role, location, pay, length, skills, certifications, experience — all 0-100 integers.",
                    "reason must explain the single most important factor — be specific, not generic.",
                ],
            },
            "user": user_to_dict(user),
            "jobs": jobs_to_dict(jobs),
            "response_schema": {
                "matched_jobs": [
                    {
                        "job_id": "string",
                        "matched": "boolean",
                        "compatibility": "number",
                        "reason": "string",
                        "strengths": ["string"],
                        "gaps": ["string"],
                        "factor_scores": {
                            "role": "number",
                            "location": "number",
                            "pay": "number",
                            "length": "number",
                            "skills": "number",
                            "certifications": "number",
                            "experience": "number",
                        },
                    }
                ]
            },
        }
        return (
            "You are a strict superyacht crew job matching engine. Your job is to protect candidates from wasted applications — only surface genuinely strong fits.\n"
            "Output must be strict JSON matching the provided schema. No markdown, no extra text.\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )

