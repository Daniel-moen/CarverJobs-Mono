import json

from interfaces import LLMClient
from models.job import JobPosting
from models.user import UserProfile
from queueing import MatchQueue
from services.matching_service import MatchingService
from services.prompt_builder import PromptBuilder
from utils.batching import FixedSizeBatchStrategy


class FakeLLM(LLMClient):
    def generate(self, prompt: str) -> str:
        payload = {
            "matched_jobs": [
                {
                    "job_id": "job-1",
                    "matched": True,
                    "compatibility": 88,
                    "reason": "Strong location + pay",
                    "strengths": ["Location match", "Pay meets minimum"],
                    "gaps": [],
                    "factor_scores": {
                        "location": 100,
                        "pay": 80,
                        "length": 70,
                        "skills": 70,
                        "certifications": 70,
                        "experience": 70,
                    },
                }
            ]
        }
        return json.dumps(payload)


def build_service() -> MatchingService:
    return MatchingService(
        llm_client=FakeLLM(),
        batch_strategy=FixedSizeBatchStrategy(batch_size=5),
        prompt_builder=PromptBuilder(),
        verbose=False,
    )


def test_queue_submit_and_result() -> None:
    service = build_service()
    queue = MatchQueue(matching_service=service, max_queue_size=10, worker_count=1)

    user = UserProfile(
        user_id="u1",
        desired_role="Deckhand",
        location="Fort Lauderdale",
        desired_pay_min=3000,
        desired_length="Permanent",
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
        )
    ]

    future = queue.submit(user, jobs)
    result = future.result(timeout=5)

    assert result.request_id
    assert result.error is None
    assert len(result.matches) == 1
    assert result.matches[0].job_id == "job-1"

    queue.shutdown()
