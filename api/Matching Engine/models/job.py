from dataclasses import dataclass, field


@dataclass(frozen=True)
class JobPosting:
    job_id: str
    title: str
    role: str
    location: str
    pay: float
    length: str
    description: str
    required_skills: list[str] = field(default_factory=list)
    preferred_certifications: list[str] = field(default_factory=list)

