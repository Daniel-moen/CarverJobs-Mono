import json

from config import Settings
from models.job import JobPosting
from models.user import UserProfile
from services.openai_client import OpenAIClient
from services.matching_service import MatchingService
from services.prompt_builder import PromptBuilder
from utils.batching import FixedSizeBatchStrategy


def build_matching_service() -> MatchingService:
    settings = Settings()
    openai_client = OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
    batch_strategy = FixedSizeBatchStrategy(batch_size=settings.batch_size)
    prompt_builder = PromptBuilder()
    return MatchingService(
        llm_client=openai_client,
        batch_strategy=batch_strategy,
        prompt_builder=prompt_builder,
        verbose=settings.verbose,
    )


if __name__ == "__main__":
    user = UserProfile(
        user_id="user-1",
        desired_role="Backend Engineer",
        location="San Francisco, CA",
        desired_pay_min=120000,
        desired_length="full-time",
        skills=["python", "fastapi", "sql"],
        certifications=["aws-certified-developer"],
        years_experience=4,
    )

    jobs = [
        JobPosting(
            job_id="job-1",
            title="Backend Engineer",
            role="Backend Engineer",
            location="San Francisco, CA",
            pay=140000,
            length="full-time",
            description="Build scalable APIs",
            required_skills=["python", "sql"],
            preferred_certifications=["aws-certified-developer"],
        ),
        JobPosting(
            job_id="job-2",
            title="Data Analyst",
            role="Data Analyst",
            location="Remote",
            pay=95000,
            length="contract",
            description="Analyze reporting pipelines",
            required_skills=["sql", "tableau"],
        ),
    ]

    service = build_matching_service()
    results = service.match_user_to_jobs(user, jobs)
    print(json.dumps([result.__dict__ for result in results], indent=2))

