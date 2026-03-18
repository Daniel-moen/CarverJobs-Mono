import json
import logging

from interfaces import BatchStrategy, LLMClient
from models.job import JobPosting
from models.match_result import JobMatch
from models.user import UserProfile
from services.prompt_builder import PromptBuilder

log = logging.getLogger("carver.matching_engine")


class MatchingService:
    def __init__(
        self,
        llm_client: LLMClient,
        batch_strategy: BatchStrategy,
        prompt_builder: PromptBuilder,
        verbose: bool = False,
    ) -> None:
        self._llm_client = llm_client
        self._batch_strategy = batch_strategy
        self._prompt_builder = prompt_builder
        self._verbose = verbose

    def match_user_to_jobs(self, user: UserProfile, jobs: list[JobPosting]) -> list[JobMatch]:
        batches = self._batch_strategy.split(jobs)
        log.info("Starting match | user_id=%s | jobs=%d | batches=%d", user.user_id, len(jobs), len(batches))
        all_matches: list[JobMatch] = []
        for batch_index, batch in enumerate(batches, start=1):
            job_ids = [job.job_id for job in batch]
            log.debug("Batch %d | jobs=%s", batch_index, job_ids)
            prompt = self._prompt_builder.build(user, batch)
            response_text = self._llm_client.generate(prompt)
            log.debug("Batch %d raw response | %r", batch_index, response_text[:300] if response_text else "")
            all_matches.extend(self._parse_matches(response_text))

        deduped: dict[str, JobMatch] = {}
        for match in all_matches:
            existing = deduped.get(match.job_id)
            if existing is None or match.compatibility > existing.compatibility:
                deduped[match.job_id] = match

        results = sorted(deduped.values(), key=lambda x: x.compatibility, reverse=True)
        log.info("Match complete | user_id=%s | matched=%d", user.user_id, len(results))
        return results

    def _parse_matches(self, response_text: str) -> list[JobMatch]:
        try:
            payload = json.loads(response_text)
        except json.JSONDecodeError as exc:
            log.error("Model did not return valid JSON | raw=%r", (response_text or "")[:300])
            raise RuntimeError("Model did not return valid JSON") from exc

        raw_matches = payload.get("matched_jobs", [])
        matches: list[JobMatch] = []
        for item in raw_matches:
            matches.append(
                JobMatch(
                    job_id=str(item["job_id"]),
                    matched=bool(item["matched"]),
                    compatibility=float(item["compatibility"]),
                    reason=str(item["reason"]),
                    strengths=[str(x) for x in item.get("strengths", [])],
                    gaps=[str(x) for x in item.get("gaps", [])],
                    factor_scores={
                        str(k): float(v)
                        for k, v in (item.get("factor_scores", {}) or {}).items()
                    },
                )
            )
        return matches

