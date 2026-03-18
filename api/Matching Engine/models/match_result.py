from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobMatch:
    job_id: str
    compatibility: float
    matched: bool
    reason: str
    strengths: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    factor_scores: dict[str, float] = field(default_factory=dict)

