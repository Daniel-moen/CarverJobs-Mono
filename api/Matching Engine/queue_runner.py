import json

from config import Settings
from models.job import JobPosting
from models.user import UserProfile
from queueing import MatchQueue
from services.openai_client import OpenAIClient
from services.matching_service import MatchingService
from services.prompt_builder import PromptBuilder
from utils.batching import FixedSizeBatchStrategy


def build_queue(settings: Settings) -> MatchQueue:
    service = MatchingService(
        llm_client=OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model),
        batch_strategy=FixedSizeBatchStrategy(batch_size=settings.batch_size),
        prompt_builder=PromptBuilder(),
        verbose=settings.verbose,
    )
    return MatchQueue(
        matching_service=service,
        max_queue_size=settings.queue_max_size,
        worker_count=settings.queue_workers,
    )


if __name__ == "__main__":
    settings = Settings()
    queue = build_queue(settings)

    user_a = UserProfile(
        user_id="user-A",
        desired_role="Deckhand",
        location="Fort Lauderdale",
        desired_pay_min=3000,
        desired_length="Permanent",
        skills=["service", "safety"],
        years_experience=2,
    )
    user_b = UserProfile(
        user_id="user-B",
        desired_role="Engineer",
        location="Monaco",
        desired_pay_min=4500,
        desired_length="Seasonal",
        skills=["engineering", "maintenance"],
        years_experience=5,
    )

    jobs = [
        JobPosting(
            job_id="job-1",
            title="Deckhand",
            role="Deckhand",
            location="Fort Lauderdale",
            pay=3800,
            length="Permanent",
            description="Deck operations",
        ),
        JobPosting(
            job_id="job-2",
            title="Engineer",
            role="Engineer",
            location="Monaco",
            pay=5200,
            length="Seasonal",
            description="Engineering systems",
        ),
    ]

    future_a = queue.submit(user_a, jobs, metadata={"source": "queue_runner"})
    future_b = queue.submit(user_b, jobs, metadata={"source": "queue_runner"})

    result_a = future_a.result(timeout=120)
    result_b = future_b.result(timeout=120)

    print("RESULT_A", json.dumps([m.__dict__ for m in result_a.matches], indent=2))
    print("RESULT_B", json.dumps([m.__dict__ for m in result_b.matches], indent=2))

    queue.shutdown()
