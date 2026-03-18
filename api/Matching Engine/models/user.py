from dataclasses import dataclass, field


@dataclass(frozen=True)
class UserProfile:
    user_id: str
    desired_role: str
    location: str
    desired_pay_min: float
    desired_length: str
    skills: list[str] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    years_experience: float = 0.0
    languages: list[str] = field(default_factory=list)
    nationality: str = ""
    rotation_preference: str = ""
    available_from: str = ""
    salary_max: float = 0.0
    bio: str = ""
    job_history: list[dict] = field(default_factory=list)

