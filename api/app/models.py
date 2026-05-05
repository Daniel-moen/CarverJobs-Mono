from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, UniqueConstraint, func

from app.database import Base


class Job(Base):
  __tablename__ = "jobs"

  id = Column(Integer, primary_key=True, index=True)
  title = Column(String(160), nullable=False)
  role = Column(String(120), nullable=False)
  yacht = Column(String(120), nullable=False)
  yacht_type = Column(String(80), nullable=True)
  yacht_length_m = Column(Integer, nullable=True)
  vessel_flag = Column(String(60), nullable=True)
  vessel_itinerary = Column(String(200), nullable=True)
  department = Column(String(60), nullable=True)
  rank_level = Column(String(60), nullable=True)
  location = Column(String(120), nullable=False)
  start_date = Column(String(40), nullable=True)
  contract_type = Column(String(60), nullable=True)
  leave_structure = Column(String(60), nullable=True)
  rotation = Column(String(50), nullable=True)
  season = Column(String(60), nullable=True)
  salary_currency = Column(String(10), nullable=True, default="EUR")
  salary_min = Column(Float, nullable=True)
  salary_max = Column(Float, nullable=True)
  tips_bonus = Column(String(120), nullable=True)
  visa_support = Column(Boolean, nullable=False, default=False)
  accommodation = Column(String(120), nullable=True)
  travel_reimbursement = Column(Boolean, nullable=False, default=False)
  experience_required_years = Column(Integer, nullable=True)
  minimum_license = Column(String(120), nullable=True)
  certifications_required = Column(Text, nullable=True)
  languages_required = Column(String(200), nullable=True)
  description = Column(Text, nullable=True)
  responsibilities = Column(Text, nullable=True)
  requirements = Column(Text, nullable=True)
  benefits = Column(Text, nullable=True)
  contact_email = Column(String(160), nullable=True)
  application_url = Column(String(260), nullable=True)
  recruiter_name = Column(String(120), nullable=True)
  recruiter_agency = Column(String(120), nullable=True)
  urgent_hire = Column(Boolean, nullable=False, default=False)
  status = Column(String(50), nullable=False, default="open", index=True)
  auto_apply_enabled = Column(Boolean, nullable=False, default=False)
  # "apify" = scraped automatically | "manual" = added via admin API
  source = Column(String(50), nullable=True, default="manual", index=True)
  # When a job is submitted by a logged-in user (crew or agency), record who.
  # NULL for scraped/admin-seeded jobs. Used for the agency dashboard and audit/abuse triage.
  posted_by_user_id = Column(Integer, nullable=True, index=True)
  posted_by_agency = Column(String(160), nullable=True, index=True)
  # SHA-256 of the raw post text — prevents same post being saved twice even
  # if it was shared across multiple Facebook groups (different URL, same content).
  content_hash = Column(String(64), nullable=True, unique=True, index=True)
  # SHA-256 of normalised role|location|start_date — catches the same position
  # re-posted by a different recruiter with different wording.
  job_fingerprint = Column(String(64), nullable=True, unique=True, index=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class User(Base):
  __tablename__ = "users"

  id = Column(Integer, primary_key=True, index=True)
  email = Column(String(160), unique=True, nullable=False, index=True)
  full_name = Column(String(120), nullable=False)
  role = Column(String(50), nullable=False, default="crew")
  phone = Column(String(40), nullable=True)
  nationality = Column(String(80), nullable=True)
  years_experience = Column(Integer, nullable=True)
  current_location = Column(String(120), nullable=True)
  gender = Column(String(20), nullable=True)
  password_hash = Column(String(256), nullable=False)
  is_active = Column(Boolean, nullable=False, default=True)
  is_subscribed = Column(Boolean, nullable=False, default=False)
  early_bird = Column(Boolean, nullable=False, default=False)
  # Set when role == "agency": the agency/recruitment-firm name shown on jobs they post.
  agency_name = Column(String(160), nullable=True, index=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class Document(Base):
  __tablename__ = "documents"

  id = Column(Integer, primary_key=True, index=True)
  # Identifies the owner — the session `sub` (admin username or Google email).
  user_key = Column(String(160), nullable=False, index=True)
  # One of: cv, references, passport, stcw, eng1, photo
  doc_type = Column(String(20), nullable=False)
  original_name = Column(String(260), nullable=False)
  # UUID-based filename stored on disk — never the original name.
  stored_name = Column(String(80), nullable=False)
  # AI-extracted summary of the document contents (set once after upload).
  scanned_text = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

  __table_args__ = (
    UniqueConstraint("user_key", "doc_type", name="uq_document_user_doctype"),
  )


class CrewProfile(Base):
  __tablename__ = "crew_profiles"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), unique=True, nullable=False, index=True)
  profile_slug = Column(String(16), unique=True, nullable=False, index=True)
  first_name = Column(String(120), nullable=True)
  last_name = Column(String(120), nullable=True)
  sex = Column(String(20), nullable=True)
  phone = Column(String(40), nullable=True)
  nationality = Column(String(80), nullable=True)
  current_location = Column(String(120), nullable=True)
  desired_role = Column(String(120), nullable=True)
  contract_type = Column(String(60), nullable=True)
  preferred_locations = Column(String(200), nullable=True)
  rotation_preference = Column(String(60), nullable=True)
  years_experience = Column(String(20), nullable=True)
  available_from = Column(String(60), nullable=True)
  salary_min = Column(String(20), nullable=True)
  salary_max = Column(String(20), nullable=True)
  certifications = Column(Text, nullable=True)
  languages = Column(String(200), nullable=True)
  bio = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class JobHistoryEntry(Base):
  __tablename__ = "job_history"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), nullable=False, index=True)
  yacht_name = Column(String(120), nullable=False)
  yacht_type = Column(String(80), nullable=True)
  role = Column(String(120), nullable=False)
  start_date = Column(String(40), nullable=True)
  end_date = Column(String(40), nullable=True)
  description = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class WhatsAppSession(Base):
  __tablename__ = "whatsapp_sessions"

  phone_number = Column(String(30), primary_key=True)
  # "onboarding" while AI is collecting initial profile fields; "chat" afterwards
  mode = Column(String(20), nullable=False, default="onboarding")
  # JSON array of {"role": "user"|"assistant", "content": "..."} — kept for AI context
  history = Column(Text, nullable=False, default="[]")
  # JSON object of profile fields collected so far during onboarding
  partial_profile = Column(Text, nullable=False, default="{}")
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class WhatsAppMessage(Base):
  __tablename__ = "whatsapp_messages"

  id = Column(Integer, primary_key=True, index=True)
  phone_number = Column(String(30), nullable=False, index=True)
  direction = Column(String(10), nullable=False, index=True)  # inbound | outbound
  message_type = Column(String(30), nullable=False, default="text")
  content = Column(Text, nullable=True)
  meta_message_id = Column(String(120), unique=True, nullable=True, index=True)
  graph_phone_number_id = Column(String(80), nullable=True)
  payload_json = Column(Text, nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class WhatsAppMagicToken(Base):
  __tablename__ = "whatsapp_magic_tokens"

  token = Column(String(32), primary_key=True)
  phone_number = Column(String(30), nullable=False, index=True)
  expires_at = Column(DateTime(timezone=True), nullable=False)
  used = Column(Boolean, nullable=False, default=False)
  redirect_to = Column(String(120), nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AnalyticsEvent(Base):
  __tablename__ = "analytics_events"

  id = Column(Integer, primary_key=True, index=True)
  session_id = Column(String(40), nullable=False, index=True)
  event_type = Column(String(30), nullable=False, index=True)
  page = Column(String(80), nullable=True)
  label = Column(String(120), nullable=True)
  value = Column(String(200), nullable=True)
  error_code = Column(String(20), nullable=True)
  client_ts = Column(String(30), nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class ErrorLog(Base):
  __tablename__ = "error_logs"

  id = Column(Integer, primary_key=True, index=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
  level = Column(String(10), nullable=False, default="error")
  status_code = Column(Integer, nullable=True)
  crv_code = Column(String(20), nullable=True)
  method = Column(String(10), nullable=True)
  path = Column(String(300), nullable=True)
  module = Column(String(60), nullable=True)
  message = Column(Text, nullable=False)
  traceback = Column(Text, nullable=True)
  request_id = Column(String(20), nullable=True)
  client_ip = Column(String(60), nullable=True)
  ai_analysis = Column(Text, nullable=True)


class WaitlistSignup(Base):
  __tablename__ = "waitlist_signups"

  id = Column(Integer, primary_key=True, index=True)
  email = Column(String(160), unique=True, nullable=False, index=True)
  source = Column(String(40), nullable=False, default="website")
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)


class Subscription(Base):
  __tablename__ = "subscriptions"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), nullable=False, index=True)
  m_payment_id = Column(String(64), unique=True, nullable=False, index=True)
  payment_token = Column(String(120), nullable=True)  # Yoco payment id (from webhook)
  checkout_id = Column(String(120), nullable=True)    # Yoco checkout session id (from create response)
  status = Column(String(20), nullable=False, default="pending")
  amount = Column(String(20), nullable=False)
  frequency = Column(Integer, nullable=False, default=3)
  next_billing_date = Column(String(40), nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class CreditAccount(Base):
  __tablename__ = "credit_accounts"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), unique=True, nullable=False, index=True)
  balance = Column(Integer, nullable=False, default=0)
  # Tracks when the free monthly token grant was last applied.
  last_reset_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class FeedbackSubmission(Base):
  __tablename__ = "feedback_submissions"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), nullable=False, index=True)
  campaign = Column(String(80), nullable=False, default="feedback_2_tokens", index=True)
  source = Column(String(40), nullable=False, default="website_popup", index=True)
  rating = Column(Integer, nullable=False)
  liked = Column(Text, nullable=True)
  improved = Column(Text, nullable=True)
  confusing = Column(Text, nullable=True)
  recommend = Column(String(20), nullable=True)
  anything_else = Column(Text, nullable=True)
  reward_amount = Column(Integer, nullable=False, default=2)
  rewarded = Column(Boolean, nullable=False, default=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)

  __table_args__ = (
    UniqueConstraint("user_key", "campaign", name="uq_feedback_user_campaign"),
  )

class FeedbackCampaignSetting(Base):
  __tablename__ = "feedback_campaign_settings"

  campaign = Column(String(80), primary_key=True)
  enabled = Column(Boolean, nullable=False, default=True)
  # all | website | whatsapp | specific | off
  target_mode = Column(String(20), nullable=False, default="all")
  # JSON array of user keys (email addresses for website users, phone numbers for WhatsApp users).
  target_user_keys_json = Column(Text, nullable=False, default="[]")
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )

class MatchSession(Base):
  __tablename__ = "match_sessions"

  id = Column(Integer, primary_key=True, index=True)
  user_key = Column(String(160), nullable=False, index=True)
  status = Column(String(20), nullable=False, default="running")
  total_jobs_scanned = Column(Integer, nullable=False, default=0)
  total_matched = Column(Integer, nullable=False, default=0)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False, index=True)
  completed_at = Column(DateTime(timezone=True), nullable=True)


class MatchSessionResult(Base):
  __tablename__ = "match_session_results"

  id = Column(Integer, primary_key=True, index=True)
  session_id = Column(Integer, nullable=False, index=True)
  job_id = Column(Integer, nullable=False)
  matched = Column(Boolean, nullable=False, default=False)
  compatibility = Column(Float, nullable=False, default=0.0)
  reason = Column(Text, nullable=True)
  strengths = Column(Text, nullable=True)
  gaps = Column(Text, nullable=True)
  factor_scores = Column(Text, nullable=True)


class Article(Base):
  """SEO article pushed in by the authoring agent.

  `body_json` stores a JSON-encoded list of structured blocks — always rendered
  as escaped text by the frontend, never as raw HTML. `keywords_json` is a
  JSON-encoded list of strings used for the `keywords` meta tag.
  """

  __tablename__ = "articles"

  id = Column(Integer, primary_key=True, index=True)
  slug = Column(String(120), unique=True, nullable=False, index=True)
  title = Column(String(200), nullable=False)
  description = Column(String(400), nullable=False)
  # ISO date (YYYY-MM-DD) — kept as string to match how the frontend renders it.
  date = Column(String(20), nullable=False)
  read_minutes = Column(Integer, nullable=False, default=3)
  keywords_json = Column(Text, nullable=False, default="[]")
  body_json = Column(Text, nullable=False, default="[]")
  published = Column(Boolean, nullable=False, default=True, index=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )


class JobDraftEvent(Base):
  """One row per (user, job) when a crew member drafts an application email.

  Used to surface engagement counts on the agency dashboard. Unique on
  (job_id, user_key) so repeated drafts by the same crew member don't
  inflate the count.
  """

  __tablename__ = "job_drafts"

  id = Column(Integer, primary_key=True, index=True)
  job_id = Column(Integer, nullable=False, index=True)
  user_key = Column(String(160), nullable=False, index=True)
  created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
  updated_at = Column(
    DateTime(timezone=True),
    server_default=func.now(),
    onupdate=func.now(),
    nullable=False,
  )

  __table_args__ = (
    UniqueConstraint("job_id", "user_key", name="uq_job_drafts_job_user"),
  )
