import re
from datetime import datetime
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class APIModel(BaseModel):
    """API request/response models: no extra JSON keys, no silent type coercion."""

    model_config = ConfigDict(extra="forbid", strict=True)


# ── Reusable annotated types ──────────────────────────────────────────────────
_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

ShortStr   = Annotated[str, Field(min_length=1, max_length=120)]
MedStr     = Annotated[str, Field(min_length=1, max_length=200)]
LongStr    = Annotated[str, Field(min_length=1, max_length=5000)]
OptShort   = Annotated[Optional[str], Field(default=None, max_length=120)]
OptMed     = Annotated[Optional[str], Field(default=None, max_length=260)]
OptLong    = Annotated[Optional[str], Field(default=None, max_length=5000)]

# Valid user roles — extend this list when new roles are introduced.
_VALID_USER_ROLES  = {"crew", "admin", "agency"}
# Valid job statuses.
_VALID_JOB_STATUSES = {"open", "closed", "priority", "filled", "draft"}


# ── Auth schemas ──────────────────────────────────────────────────────────────

class LoginRequest(APIModel):
    username: Annotated[str, Field(min_length=1, max_length=160)]  # supports both usernames and email addresses
    password: Annotated[str, Field(min_length=1, max_length=256)]


class GoogleLoginRequest(APIModel):
    # Google ID tokens are JWT strings — allow up to 4 KB.
    id_token: Annotated[str, Field(min_length=1, max_length=4096)]


class WaitlistSignupRequest(APIModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v


class SignupRequest(APIModel):
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


class AgencySignupRequest(APIModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]
    full_name: Annotated[str, Field(min_length=1, max_length=120)]
    agency_name: Annotated[str, Field(min_length=1, max_length=160)]
    password: Annotated[str, Field(min_length=8, max_length=256)]

    @field_validator("email")
    @classmethod
    def _validate_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Invalid email address")
        return v

    @field_validator("full_name", "agency_name")
    @classmethod
    def _strip_required(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("This field is required")
        return v


# ── Interview schemas ─────────────────────────────────────────────────────────

class InterviewMessage(APIModel):
    role: Literal["user", "assistant"]
    content: Annotated[str, Field(min_length=0, max_length=4000)]


class InterviewRequest(APIModel):
    user_message: Annotated[str, Field(default="", max_length=4000)] = ""
    history: Annotated[list[InterviewMessage], Field(default_factory=list, max_length=50)]
    profile: Annotated[dict[str, str], Field(default_factory=dict)]

    @field_validator("profile")
    @classmethod
    def _validate_profile(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 50:
            raise ValueError("profile may not have more than 50 fields")
        for k, val in v.items():
            if len(k) > 60 or len(str(val)) > 500:
                raise ValueError("profile keys/values are too long")
        return v


class InterviewResponse(APIModel):
    message: str
    updates: Annotated[dict[str, str], Field(default_factory=dict)]


# ── User schemas ──────────────────────────────────────────────────────────────

class UserBase(APIModel):
    email: Annotated[str, Field(min_length=5, max_length=160)]
    full_name: ShortStr
    role: Annotated[str, Field(default="crew", max_length=50)] = "crew"
    phone: OptShort = None
    nationality: OptShort = None
    years_experience: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    current_location: OptShort = None
    gender: Annotated[Optional[str], Field(default=None, max_length=20)] = None
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


class UserUpdate(APIModel):
    full_name: Optional[ShortStr] = None
    role: Annotated[Optional[str], Field(default=None, max_length=50)] = None
    phone: OptShort = None
    nationality: OptShort = None
    years_experience: Annotated[Optional[int], Field(default=None, ge=0, le=80)] = None
    current_location: OptShort = None
    gender: Annotated[Optional[str], Field(default=None, max_length=20)] = None
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

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


# ── Job schemas ───────────────────────────────────────────────────────────────

class JobBase(APIModel):
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


class AgencyJobFormRequest(APIModel):
    """Guided-form submission from an agency. Only the essentials are required."""
    title:                   ShortStr
    role:                    ShortStr
    yacht:                   ShortStr
    location:                ShortStr
    yacht_type:              OptShort = None
    yacht_length_m:          Annotated[Optional[int], Field(default=None, ge=1, le=600)] = None
    department:              OptShort = None
    rank_level:              OptShort = None
    start_date:              OptShort = None
    contract_type:           OptShort = None
    rotation:                OptShort = None
    season:                  OptShort = None
    salary_currency:         Annotated[Optional[str], Field(default="EUR", max_length=10)] = "EUR"
    salary_min:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
    salary_max:              Annotated[Optional[float], Field(default=None, ge=0, le=10_000_000)] = None
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
    urgent_hire:             bool = False

    @field_validator("contact_email", mode="before")
    @classmethod
    def _validate_contact_email(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            v = str(v).strip()
            if v and not _EMAIL_RE.match(v.lower()):
                return None
        return v or None


class JobUpdate(APIModel):
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

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


# ── Crew profile schemas ─────────────────────────────────────────────────────

_VALID_SEX_VALUES = {"male", "female", "other", "prefer_not_to_say"}


class CrewProfileSave(APIModel):
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

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


class PublicProfileResponse(APIModel):
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
    job_history: Annotated[list["JobHistoryRead"], Field(default_factory=list)]


# ── Job history schemas ──────────────────────────────────────────────────────

class JobHistoryCreate(APIModel):
    yacht_name: ShortStr
    yacht_type: OptShort = None
    role: ShortStr
    start_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    end_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    description: OptLong = None


class JobHistoryUpdate(APIModel):
    yacht_name: Optional[ShortStr] = None
    yacht_type: OptShort = None
    role: Optional[ShortStr] = None
    start_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    end_date: Annotated[Optional[str], Field(default=None, max_length=40)] = None
    description: OptLong = None


class JobHistoryRead(APIModel):
    id: int
    yacht_name: str
    yacht_type: Optional[str] = None
    role: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    description: Optional[str] = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


# ── Matching schemas ──────────────────────────────────────────────────────────

class MatchingRequest(APIModel):
    user_id:         Annotated[int, Field(ge=1)]
    job_limit:       Annotated[int, Field(default=20, ge=1, le=200)] = 20
    job_statuses:    Annotated[list[str], Field(default_factory=lambda: ["open", "priority"], max_length=10)]
    timeout_seconds: Annotated[int, Field(default=180, ge=5, le=600)] = 180


class MatchResultItem(APIModel):
    job_id:        str
    matched:       bool
    compatibility: Annotated[float, Field(ge=0.0, le=100.0)]
    reason:        str
    strengths:     Annotated[list[str], Field(default_factory=list)]
    gaps:          Annotated[list[str], Field(default_factory=list)]
    factor_scores: Annotated[dict[str, float], Field(default_factory=dict)]


class MatchingEnqueueResponse(APIModel):
    request_id: str
    queued:     bool


class MatchingRunResponse(APIModel):
    request_id: str
    credits_remaining: int = 0
    matches:    list[MatchResultItem]

# ── Feedback schemas ──────────────────────────────────────────────────────────

class FeedbackSubmitRequest(APIModel):
    source: Literal["website_popup", "whatsapp_message"] = "website_popup"
    rating: Annotated[int, Field(ge=1, le=5)]
    liked: Annotated[Optional[str], Field(default=None, max_length=1500)] = None
    improved: Annotated[Optional[str], Field(default=None, max_length=1500)] = None
    confusing: Annotated[Optional[str], Field(default=None, max_length=1500)] = None
    recommend: Literal["yes", "no", "maybe"] | None = None
    anything_else: Annotated[Optional[str], Field(default=None, max_length=1500)] = None

    @field_validator("liked", "improved", "confusing", "anything_else")
    @classmethod
    def _strip_optional_text(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        stripped = v.strip()
        return stripped or None


class FeedbackStatusResponse(APIModel):
    ok: bool
    submitted: bool
    eligible: bool = True
    force_prompt: bool = False
    target_mode: str = "all"
    reward_amount: int = 5


class FeedbackSubmitResponse(APIModel):
    ok: bool
    submitted: bool
    reward_granted: bool
    reward_amount: int = 5
    credits_balance: int


class FeedbackSettingsResponse(APIModel):
    ok: bool
    campaign: str
    enabled: bool
    target_mode: Literal["all", "website", "whatsapp", "specific", "off"]
    target_user_keys: Annotated[list[str], Field(default_factory=list, max_length=500)]
    reward_amount: int = 5


class FeedbackSettingsUpdate(APIModel):
    enabled: bool
    target_mode: Literal["all", "website", "whatsapp", "specific", "off"]
    target_user_keys: Annotated[list[str], Field(default_factory=list, max_length=500)] = []

    @field_validator("target_user_keys")
    @classmethod
    def _normalise_target_user_keys(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        normalised: list[str] = []
        for raw in v:
            key = str(raw).strip().lower()
            if not key or key in seen:
                continue
            if len(key) > 160:
                raise ValueError("Target user keys must be 160 characters or fewer")
            seen.add(key)
            normalised.append(key)
        return normalised


# ── Crew matching schemas ────────────────────────────────────────────────────

class CrewMatchJob(APIModel):
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

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


class CrewMatchAI(APIModel):
    reason: str = ""
    compatibility: float = 0.0
    strengths: Annotated[list[str], Field(default_factory=list)]
    gaps: Annotated[list[str], Field(default_factory=list)]


class CrewMatchItem(APIModel):
    job: CrewMatchJob
    ai: CrewMatchAI


class CrewMatchResponse(APIModel):
    matched: bool
    matches: Annotated[list[CrewMatchItem], Field(default_factory=list)]


class DraftEmailRequest(APIModel):
    job_id: Annotated[int, Field(ge=1)]
    prompt: str | None = Field(default=None, max_length=500)
    previous_body: str | None = Field(default=None, max_length=3000)


class DraftEmailResponse(APIModel):
    to: str
    subject: str
    body: str


# ── Match session schemas ────────────────────────────────────────────────────

class MatchSessionResultItem(APIModel):
    job: CrewMatchJob
    matched: bool
    compatibility: float
    reason: str = ""
    strengths: Annotated[list[str], Field(default_factory=list)]
    gaps: Annotated[list[str], Field(default_factory=list)]
    factor_scores: Annotated[dict[str, float], Field(default_factory=dict)]


class MatchSessionSummary(APIModel):
    id: int
    status: str
    total_jobs_scanned: int
    total_matched: int
    created_at: datetime
    completed_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True, extra="forbid", strict=True)


class MatchSessionDetail(APIModel):
    id: int
    status: str
    total_jobs_scanned: int
    total_matched: int
    created_at: datetime
    completed_at: Optional[datetime] = None
    results: Annotated[list[MatchSessionResultItem], Field(default_factory=list)]


class MatchSessionListResponse(APIModel):
    sessions: Annotated[list[MatchSessionSummary], Field(default_factory=list)]


class CrewMatchV2Response(APIModel):
    session_id: int
    matched: bool
    total_jobs_scanned: int
    total_matched: int
    credits_remaining: int = 0
    matches: Annotated[list[MatchSessionResultItem], Field(default_factory=list)]
