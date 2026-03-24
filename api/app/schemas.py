import re
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ── Reusable annotated types ──────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

ShortStr   = Annotated[str, Field(min_length=1, max_length=120)]
MedStr     = Annotated[str, Field(min_length=1, max_length=200)]
LongStr    = Annotated[str, Field(min_length=1, max_length=5000)]
OptShort   = Annotated[Optional[str], Field(default=None, max_length=120)]
OptMed     = Annotated[Optional[str], Field(default=None, max_length=260)]
OptLong    = Annotated[Optional[str], Field(default=None, max_length=5000)]

# Valid user roles — extend this list when new roles are introduced.
_VALID_USER_ROLES  = {"crew", "admin"}
# Valid job statuses.
_VALID_JOB_STATUSES = {"open", "closed", "priority", "filled", "draft"}


# ── Auth schemas ──────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: Annotated[str, Field(min_length=1, max_length=80)]
    password: Annotated[str, Field(min_length=1, max_length=256)]


class GoogleLoginRequest(BaseModel):
    # Google ID tokens are JWT strings — allow up to 4 KB.
    id_token: Annotated[str, Field(min_length=1, max_length=4096)]


class WaitlistSignupRequest(BaseModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v


class SignupRequest(BaseModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]
    full_name: Annotated[str, Field(min_length=1, max_length=120)]
    password: Annotated[str, Field(min_length=8, max_length=256)]

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Full name is required")
        return v


# ── Interview schemas ─────────────────────────────────────────────────────────

class InterviewMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=0, max_length=4000)]


class InterviewRequest(BaseModel):
    user_message: Annotated[str, Field(default="", max_length=4000)] = ""
    history: Annotated[list[InterviewMessage], Field(default_factory=list, max_length=50)] = []
    profile: dict[str, str] = {}

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, v: dict) -> dict:
        if len(v) > 50:
            raise ValueError("profile may not have more than 50 fields")
        for k, val in v.items():
            if len(k) > 60 or len(str(val)) > 500:
                raise ValueError("profile keys/values are too long")
        return v


class InterviewResponse(BaseModel):
    message: str
    updates: dict[str, str] = {}


# ── User schemas ──────────────────────────────────────────────────────────────

class UserBase(BaseModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]
    full_name: ShortStr
    role: Annotated[str, Field(default="crew", max_length=50)] = "crew"
    phone: OptShort = None
    nationality: OptShort = None
    years_experience: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    current_location: OptShort = None
    is_active: bool = True
    is_subscribed: bool = False

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: str) -> str:
        if v not in _VALID_USER_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(_VALID_USER_ROLES))}")
        return v


class UserCreate(UserBase):
    password: Annotated[str, Field(min_length=8, max_length=256)]


class UserUpdate(BaseModel):
    full_name: Optional[ShortStr] = None
    role: Annotated[Optional[str], Field(default=None, max_length=50)] = None
    phone: OptShort = None
    nationality: OptShort = None
    years_experience: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    current_location: OptShort = None
    password: Annotated[Optional[str], Field(default=None, min_length=8, max_length=256)] = None
    is_active: Optional[bool] = None
    is_subscribed: Optional[bool] = None

    @field_validator("role")
    @classmethod
    def _validate_role(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_USER_ROLES:
            raise ValueError(f"role must be one of: {', '.join(sorted(_VALID_USER_ROLES))}")
        return v


class UserRead(UserBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Job schemas ───────────────────────────────────────────────────────────────

class JobBase(BaseModel):
    title:                   ShortStr
    role:                    ShortStr
    yacht:                   ShortStr
    yacht_type:              OptShort = None
    yacht_length_m:          Annotated[Optional[int], Field(default=None, ge=1, le=600)] = None
    vessel_flag:             OptShort = None
    vessel_itinerary:        OptMed = None
    department:              OptShort = None
    rank_level:              OptShort = None
    location:                ShortStr
    start_date:              OptShort = None
    contract_type:           OptShort = None
    leave_structure:         OptShort = None
    rotation:                OptShort = None
    season:                  OptShort = None
    salary_currency:         Annotated[Optional[str], Field(default="EUR", max_length=10)] = "EUR"
    salary_min:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
    salary_max:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
    tips_bonus:              OptShort = None
    visa_support:            bool = False
    accommodation:           OptShort = None
    travel_reimbursement:    bool = False
    experience_required_years: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    minimum_license:         OptShort = None
    certifications_required: OptLong = None
    languages_required:      OptMed = None
    description:             OptLong = None
    responsibilities:        OptLong = None
    requirements:            OptLong = None
    benefits:                OptLong = None
    contact_email:           Annotated[Optional[str], Field(default=None, max_length=160)] = None
    application_url:         OptMed = None
    recruiter_name:          OptShort = None
    recruiter_agency:        OptShort = None
    urgent_hire:             bool = False
    status:                  Annotated[str, Field(default="open", max_length=50)] = "open"
    auto_apply_enabled:      bool = False

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: str) -> str:
        if v not in _VALID_JOB_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_JOB_STATUSES))}")
        return v

    @field_validator("contact_email", mode="before")
    @classmethod
    def _validate_contact_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = str(v).strip()
            if v and not _EMAIL_RE.match(v.lower()):
                return None
        return v or None


class JobCreate(JobBase):
    pass


class JobUpdate(BaseModel):
    title:                   Optional[ShortStr] = None
    role:                    Optional[ShortStr] = None
    yacht:                   Optional[ShortStr] = None
    yacht_type:              OptShort = None
    yacht_length_m:          Annotated[Optional[int], Field(default=None, ge=1, le=600)] = None
    vessel_flag:             OptShort = None
    vessel_itinerary:        OptMed = None
    department:              OptShort = None
    rank_level:              OptShort = None
    location:                Optional[ShortStr] = None
    start_date:              OptShort = None
    contract_type:           OptShort = None
    leave_structure:         OptShort = None
    rotation:                OptShort = None
    season:                  OptShort = None
    salary_currency:         Annotated[Optional[str], Field(default=None, max_length=10)] = None
    salary_min:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
    salary_max:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
    tips_bonus:              OptShort = None
    visa_support:            Optional[bool] = None
    accommodation:           OptShort = None
    travel_reimbursement:    Optional[bool] = None
    experience_required_years: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    minimum_license:         OptShort = None
    certifications_required: OptLong = None
    languages_required:      OptMed = None
    description:             OptLong = None
    responsibilities:        OptLong = None
    requirements:            OptLong = None
    benefits:                OptLong = None
    contact_email:           Annotated[Optional[str], Field(default=None, max_length=160)] = None
    application_url:         OptMed = None
    recruiter_name:          OptShort = None
    recruiter_agency:        OptShort = None
    urgent_hire:             Optional[bool] = None
    status:                  Annotated[Optional[str], Field(default=None, max_length=50)] = None
    auto_apply_enabled:      Optional[bool] = None

    @field_validator("status")
    @classmethod
    def _validate_status(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _VALID_JOB_STATUSES:
            raise ValueError(f"status must be one of: {', '.join(sorted(_VALID_JOB_STATUSES))}")
        return v


class JobRead(JobBase):
    id: int
    source: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Crew profile schemas ─────────────────────────────────────────────────────

_VALID_SEX_VALUES = {"male", "female", "other", "prefer_not_to_say"}


class CrewProfileSave(BaseModel):
    first_name: OptShort = None
    last_name: OptShort = None
    sex: Annotated[Optional[str], Field(default=None, max_length=20)] = None
    phone: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    nationality: OptShort = None
    current_location: OptShort = None
    desired_role: OptShort = None
    contract_type: Annotated[Optional[str], Field(default=None, max_length=60)] = None
    preferred_locations: OptMed = None
    rotation_preference: Annotated[Optional[str], Field(default=None, max_length=60)] = None
    years_experience: Annotated[Optional[str], Field(default=None, max_length=20)] = None
    available_from: Annotated[Optional[str], Field(default=None, max_length=60)] = None
    salary_min: Annotated[Optional[str], Field(default=None, max_length=20)] = None
    salary_max: Annotated[Optional[str], Field(default=None, max_length=20)] = None
    certifications: OptLong = None
    languages: OptMed = None
    bio: OptLong = None

    @field_validator("sex")
    @classmethod
    def _validate_sex(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = v.strip().lower()
            if v and v not in _VALID_SEX_VALUES:
                raise ValueError(f"sex must be one of: {', '.join(sorted(_VALID_SEX_VALUES))}")
        return v or None


class CrewProfileRead(CrewProfileSave):
    profile_slug: str
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PublicProfileResponse(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    nationality: Optional[str] = None
    current_location: Optional[str] = None
    desired_role: Optional[str] = None
    contract_type: Optional[str] = None
    preferred_locations: Optional[str] = None
    rotation_preference: Optional[str] = None
    years_experience: Optional[str] = None
    available_from: Optional[str] = None
    certifications: Optional[str] = None
    languages: Optional[str] = None
    bio: Optional[str] = None
    has_cv: bool = False
    has_references: bool = False
    has_photo: bool = False
    photo_url: Optional[str] = None
    job_history: list["JobHistoryRead"] = []


# ── Job history schemas ──────────────────────────────────────────────────────

class JobHistoryCreate(BaseModel):
    yacht_name: ShortStr
    yacht_type: OptShort = None
    role: ShortStr
    start_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    end_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    description: OptLong = None


class JobHistoryUpdate(BaseModel):
    yacht_name: Optional[ShortStr] = None
    yacht_type: OptShort = None
    role: Optional[ShortStr] = None
    start_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    end_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    description: OptLong = None


class JobHistoryRead(BaseModel):
    id: int
    yacht_name: str
    yacht_type: Optional[str] = None
    role: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ── Matching schemas ──────────────────────────────────────────────────────────

class MatchingRequest(BaseModel):
    user_id:         Annotated[int, Field(ge=1)]
    job_limit:       Annotated[int, Field(default=20, ge=1, le=200)] = 20
    job_statuses:    Annotated[list[str], Field(default_factory=lambda: ["open", "priority"], max_length=10)] = ["open", "priority"]
    timeout_seconds: Annotated[int, Field(default=180, ge=5, le=600)] = 180


class MatchResultItem(BaseModel):
    job_id:        str
    matched:       bool
    compatibility: Annotated[float, Field(ge=0.0, le=100.0)]
    reason:        str
    strengths:     list[str] = []
    gaps:          list[str] = []
    factor_scores: dict[str, float] = {}


class MatchingEnqueueResponse(BaseModel):
    request_id: str
    queued:     bool


class MatchingRunResponse(BaseModel):
    request_id: str
    matches:    list[MatchResultItem]


# ── Crew matching schemas ────────────────────────────────────────────────────

class CrewMatchJob(BaseModel):
    id: int
    title: str
    role: str
    yacht: str
    location: str
    contract_type: Optional[str] = None
    salary_min: Optional[float] = None
    salary_max: Optional[float] = None
    salary_currency: Optional[str] = None
    contact_email: Optional[str] = None
    description: Optional[str] = None
    yacht_type: Optional[str] = None
    yacht_length_m: Optional[int] = None
    start_date: Optional[str] = None
    season: Optional[str] = None
    rotation: Optional[str] = None
    experience_required_years: Optional[int] = None
    certifications_required: Optional[str] = None
    languages_required: Optional[str] = None
    requirements: Optional[str] = None
    responsibilities: Optional[str] = None
    benefits: Optional[str] = None
    recruiter_name: Optional[str] = None
    recruiter_agency: Optional[str] = None
    application_url: Optional[str] = None
    urgent_hire: bool = False
    source: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CrewMatchAI(BaseModel):
    reason: str = ""
    compatibility: float = 0.0
    strengths: list[str] = []
    gaps: list[str] = []


class CrewMatchItem(BaseModel):
    job: CrewMatchJob
    ai: CrewMatchAI


class CrewMatchResponse(BaseModel):
    matched: bool
    matches: list[CrewMatchItem] = []


class DraftEmailRequest(BaseModel):
    job_id: Annotated[int, Field(ge=1)]


class DraftEmailResponse(BaseModel):
    to: str
    subject: str
    body: str


# ── Match session schemas ────────────────────────────────────────────────────

class MatchSessionResultItem(BaseModel):
    job: CrewMatchJob
    matched: bool
    compatibility: float
    reason: str = ""
    strengths: list[str] = []
    gaps: list[str] = []
    factor_scores: dict[str, float] = {}


class MatchSessionSummary(BaseModel):
    id: int
    status: str
    total_jobs_scanned: int
    total_matched: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class MatchSessionDetail(BaseModel):
    id: int
    status: str
    total_jobs_scanned: int
    total_matched: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    results: list[MatchSessionResultItem] = []


class MatchSessionListResponse(BaseModel):
    sessions: list[MatchSessionSummary] = []


class CrewMatchV2Response(BaseModel):
    session_id: int
    matched: bool
    total_jobs_scanned: int
    total_matched: int
    matches: list[MatchSessionResultItem] = []
