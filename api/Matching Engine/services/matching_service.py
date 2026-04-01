import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from interfaces import BatchStrategy, LLMClient
from models.job import JobPosting
from models.match_result import JobMatch
from models.user import UserProfile
from services.prompt_builder import PromptBuilder

log = logging.getLogger("carver.matching_engine")

_FENCE_RE = re.compile(r"```(?:json)?\s*\n?(.*?)\n?\s*```", re.DOTALL)


def _extract_json(text: str) -> str:
    """Strip markdown fences and leading/trailing garbage around JSON."""
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

        valid_job_ids = {job.job_id for job in jobs}
        all_matches: list[JobMatch] = []

        if len(batches) <= 1:
            for batch_index, batch in enumerate(batches, start=1):
                matches = self._process_batch(batch_index, user, batch, valid_job_ids)
                all_matches.extend(matches)
        else:
            with ThreadPoolExecutor(max_workers=min(len(batches), 4)) as pool:
                futures = {
                    pool.submit(self._process_batch, i, user, batch, valid_job_ids): i
                    for i, batch in enumerate(batches, start=1)
                }
                for future in as_completed(futures):
                    batch_idx = futures[future]
                    try:
                        all_matches.extend(future.result())
                    except Exception:
                        log.exception("Batch %d failed, skipping", batch_idx)

        deduped: dict[str, JobMatch] = {}
        for match in all_matches:
            existing = deduped.get(match.job_id)
            if existing is None or match.compatibility > existing.compatibility:
                deduped[match.job_id] = match

        results = sorted(deduped.values(), key=lambda x: x.compatibility, reverse=True)
        matched_count = sum(1 for r in results if r.matched)
        top_compat = results[0].compatibility if results else 0
        log.info("Match complete | user_id=%s | total=%d | matched_true=%d | top_compat=%.0f",
                 user.user_id, len(results), matched_count, top_compat)
        return results

    def _process_batch(
        self,
        batch_index: int,
        user: UserProfile,
        batch: list[JobPosting],
        valid_job_ids: set[str],
    ) -> list[JobMatch]:
        job_ids = [job.job_id for job in batch]
        log.info("Batch %d | jobs=%s", batch_index, job_ids)
        prompt = self._prompt_builder.build(user, batch)
        response_text = self._llm_client.generate(prompt)
        log.info("Batch %d raw response length=%d | %s", batch_index, len(response_text or ""), (response_text or "")[:400])
        matches = self._parse_matches(response_text, valid_job_ids)
        log.info("Batch %d parsed | matches=%d | matched_true=%d | avg_compat=%.0f",
                 batch_index, len(matches),
                 sum(1 for m in matches if m.matched),
                 sum(m.compatibility for m in matches) / max(len(matches), 1))
        return matches

    def _parse_matches(self, response_text: str, valid_job_ids: set[str] | None = None) -> list[JobMatch]:
        cleaned = _extract_json(response_text)
        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            log.error("Model did not return valid JSON | raw=%r", (response_text or "")[:500])
            return []

        raw_matches = payload.get("matched_jobs", [])
        if not isinstance(raw_matches, list):
            log.error("matched_jobs is not a list | type=%s", type(raw_matches).__name__)
            return []

        matches: list[JobMatch] = []
        for item in raw_matches:
            try:
                job_id = str(item.get("job_id", ""))
                if not job_id:
                    continue
                if valid_job_ids and job_id not in valid_job_ids:
                    log.warning("LLM returned unknown job_id=%s, skipping", job_id)
                    continue
                compatibility = float(item.get("compatibility", 0))
                compatibility = max(0.0, min(100.0, compatibility))
                matches.append(
                    JobMatch(
                        job_id=job_id,
                        matched=bool(item.get("matched", False)),
                        compatibility=compatibility,
                        reason=str(item.get("reason", "")),
                        strengths=[str(x) for x in item.get("strengths", []) or []],
                        gaps=[str(x) for x in item.get("gaps", []) or []],
                        factor_scores={
                            str(k): max(0.0, min(100.0, float(v)))
                            for k, v in (item.get("factor_scores") or {}).items()
                        },
                    )
                )
            except (TypeError, ValueError, AttributeError) as exc:
                log.warning("Skipping malformed match item | error=%s | item=%r", exc, str(item)[:200])
        return matches

