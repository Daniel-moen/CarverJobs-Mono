import json
import sys
from pathlib import Path

# Ensure imports resolve for both Matching Engine and app modules.
ENGINE_DIR = Path(__file__).resolve().parent
API_ROOT = ENGINE_DIR.parent
sys.path.insert(0, str(ENGINE_DIR))
sys.path.insert(0, str(API_ROOT))

from app.database import SessionLocal
from app.models import Job, User
from config import Settings
from models.job import JobPosting
from models.user import UserProfile
from services.openai_client import OpenAIClient
from services.matching_service import MatchingService
from services.prompt_builder import PromptBuilder
from utils.batching import FixedSizeBatchStrategy


def to_user_profile(user: User) -> UserProfile:
    return UserProfile(
        user_id=str(user.id),
        desired_role=user.role or "",
        location=user.current_location or "Unknown",
        desired_pay_min=0.0,
        desired_length="Permanent",
        skills=[],
        certifications=[],
        years_experience=float(user.years_experience or 0),
    )


def to_job_posting(job: Job) -> JobPosting:
    pay = float(job.salary_max or job.salary_min or 0.0)
    return JobPosting(
        job_id=str(job.id),
        title=job.title,
        role=job.role or "",
        location=job.location,
        pay=pay,
        length=job.contract_type or "Unknown",
        description=job.description or "",
        required_skills=[],
        preferred_certifications=[],
    )


def build_matching_service(settings: Settings) -> MatchingService:
    return MatchingService(
        llm_client=OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model),
        batch_strategy=FixedSizeBatchStrategy(batch_size=settings.batch_size),
        prompt_builder=PromptBuilder(),
        verbose=settings.verbose,
    )


def run_db_live_test(limit_jobs: int = 20) -> None:
    settings = Settings()
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.is_active.is_(True)).order_by(User.id.asc()).first()
        jobs = db.query(Job).filter(Job.status.in_(["open", "priority"])).order_by(Job.id.asc()).limit(limit_jobs).all()
    finally:
        db.close()

    if not user:
        raise RuntimeError("No active users found in DB.")
    if not jobs:
        raise RuntimeError("No open/priority jobs found in DB.")

    user_profile = to_user_profile(user)
    job_postings = [to_job_posting(job) for job in jobs]

    print(f"[DB TEST] user_id={user_profile.user_id} location={user_profile.location} years_experience={user_profile.years_experience}")
    print(f"[DB TEST] jobs_loaded={len(job_postings)}")

    service = build_matching_service(settings)
    results = service.match_user_to_jobs(user_profile, job_postings)
    print(json.dumps([result.__dict__ for result in results], indent=2))


if __name__ == "__main__":
    run_db_live_test()
