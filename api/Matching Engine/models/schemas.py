from dataclasses import asdict
from typing import Any

from .job import JobPosting
from .user import UserProfile


def user_to_dict(user: UserProfile) -> dict[str, Any]:
    return asdict(user)


def jobs_to_dict(jobs: list[JobPosting]) -> list[dict[str, Any]]:
    return [asdict(job) for job in jobs]

