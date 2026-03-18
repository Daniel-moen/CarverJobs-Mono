from dataclasses import dataclass, field
from datetime import datetime, timezone

from models.job import JobPosting
from models.match_result import JobMatch
from models.user import UserProfile


@dataclass(frozen=True)
class MatchRequest:
    request_id: str
    user: UserProfile
    jobs: list[JobPosting]
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class MatchResult:
    request_id: str
    matches: list[JobMatch]
    started_at: datetime
    finished_at: datetime
    error: str | None = None
