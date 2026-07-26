import os
from pathlib import Path


def _load_dotenv(path: Path) -> None:
  """Load key=value pairs from a .env file into os.environ (skip if absent)."""
  if not path.is_file():
    return
  with path.open() as f:
    for line in f:
      line = line.strip()
      if not line or line.startswith("#") or "=" not in line:
        continue
      key, _, value = line.partition("=")
      key = key.strip()
      value = value.strip()
      if key and key not in os.environ:
        os.environ[key] = value


# Load api/.env when running locally (gitignored, never committed).
_load_dotenv(Path(__file__).resolve().parents[1] / ".env")


def _csv_env(name: str, default: str) -> list[str]:
  raw = os.getenv(name, default)
  return [item.strip() for item in raw.split(",") if item.strip()]

def _default_cors_origins() -> str:
  # Keep defaults explicit so production works even if CORS_ORIGINS is unset.
  defaults = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "https://jobcarver.co",
    "https://www.jobcarver.co",
  ]
  frontend_base = os.getenv("FRONTEND_BASE_URL", "").strip()
  if frontend_base:
    defaults.append(frontend_base)
  # Preserve order while removing duplicates.
  return ",".join(dict.fromkeys(defaults))


class Settings:
  APP_ENV = os.getenv("APP_ENV", "development")
  AUTO_LOGIN_AS_ADMIN = os.getenv("AUTO_LOGIN_AS_ADMIN", "false").lower() == "true"
  SECRET_KEY = os.getenv("SECRET_KEY", "change-me-in-production")
  SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "carver_session")
  SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
  SESSION_SECURE_COOKIE = os.getenv(
      "SESSION_SECURE_COOKIE",
      "true" if os.getenv("APP_ENV") == "production" else "false",
  ).lower() == "true"

  # Shadow traffic capture — records real requests to a JSONL corpus so the Go
  # port (jobcarver-go) can be replayed against them and diffed before cutover.
  # OFF by default; when off the middleware is not even installed (zero overhead).
  # See jobcarver-go/SHADOW.md.
  SHADOW_CAPTURE_ENABLED: bool = os.getenv("SHADOW_CAPTURE_ENABLED", "false").lower() == "true"
  SHADOW_CAPTURE_FILE: str = os.getenv("SHADOW_CAPTURE_FILE", "data/shadow_capture.jsonl")
  # Fraction of eligible requests to record (0.0–1.0). Lower it in high traffic.
  SHADOW_CAPTURE_SAMPLE_RATE: float = float(os.getenv("SHADOW_CAPTURE_SAMPLE_RATE", "1.0"))
  # Per-request body cap. Bodies larger than this are truncated (flagged in the record).
  SHADOW_CAPTURE_MAX_BODY_BYTES: int = int(os.getenv("SHADOW_CAPTURE_MAX_BODY_BYTES", str(64 * 1024)))
  # Also store Python's response body (heavier; off by default — structural diff
  # only needs status + content-type).
  SHADOW_CAPTURE_RESPONSE_BODY: bool = os.getenv("SHADOW_CAPTURE_RESPONSE_BODY", "false").lower() == "true"
  # Path prefixes never captured (health checks, static assets, capture noise).
  SHADOW_CAPTURE_EXCLUDE_PREFIXES: list[str] = _csv_env(
      "SHADOW_CAPTURE_EXCLUDE_PREFIXES",
      "/health,/metrics,/admin/dashboard/static",
  )

  # Go canary routing — serve a slice of live traffic from the Go port
  # (jobcarver-go) running alongside this API. OFF by default; no-op until
  # GO_UPSTREAM_URL is set. See jobcarver-go/SHADOW.md (Canary section).
  GO_ROUTING_ENABLED: bool = os.getenv("GO_ROUTING_ENABLED", "false").lower() == "true"
  # Base URL of the Go service (e.g. Railway private net: http://jobcarver-go.railway.internal:3000).
  GO_UPSTREAM_URL: str = os.getenv("GO_UPSTREAM_URL", "").strip()
  # Percentage of (Go-implemented) requests from non-flagged users to serve from Go.
  GO_ROUTING_PERCENT: int = int(os.getenv("GO_ROUTING_PERCENT", "20"))
  GO_ROUTING_TIMEOUT_SECONDS: float = float(os.getenv("GO_ROUTING_TIMEOUT_SECONDS", "15"))
  # Route prefixes whose feature is NOT yet implemented in Go — always served by
  # Python (see jobcarver-go/TODO.md). Edit as Go features land.
  GO_UNIMPLEMENTED_PREFIXES: list[str] = _csv_env(
      "GO_UNIMPLEMENTED_PREFIXES",
      "/auth/google,/jobs/submit/text,/jobs/submit/image,/scraper,/interview,"
      "/crew-match,/matching,/documents,/subscription,/telnyx,/webhooks,/wa/,/admin/jobs/review",
  )

  ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
  ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-this-password")
  GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
  GOOGLE_ALLOWED_EMAILS = [email.lower() for email in _csv_env("GOOGLE_ALLOWED_EMAILS", "")]
  GOOGLE_ALLOWED_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "").strip().lower()
  GOOGLE_REQUIRE_VERIFIED_EMAIL = os.getenv("GOOGLE_REQUIRE_VERIFIED_EMAIL", "true").lower() == "true"
  OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
  OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
  EMAIL_AI_MODEL = os.getenv("EMAIL_AI_MODEL", "gpt-4o").strip()
  WHATSAPP_AI_MODEL = os.getenv("WHATSAPP_AI_MODEL", "gpt-5-mini").strip()
  MIXPANEL_PROJECT_TOKEN = os.getenv(
      "MIXPANEL_PROJECT_TOKEN",
      os.getenv("MIXPANEL_TOKEN", os.getenv("VITE_MIXPANEL_TOKEN", "")),
  ).strip()
  MIXPANEL_API_HOST = os.getenv("MIXPANEL_API_HOST", "https://api-eu.mixpanel.com").strip().rstrip("/")
  MIXPANEL_SESSION_RECORD_PERCENT = int(os.getenv(
      "MIXPANEL_SESSION_RECORD_PERCENT",
      os.getenv("VITE_MIXPANEL_SESSION_RECORD_PERCENT", "100"),
  ))
  MIXPANEL_LLM_CAPTURE_CONTENT = os.getenv("MIXPANEL_LLM_CAPTURE_CONTENT", "false").lower() == "true"

  CORS_ORIGINS = _csv_env(
    "CORS_ORIGINS",
    _default_cors_origins(),
  )
  # Default to * so Railway's health checker always reaches /health regardless
  # of whether it uses the public domain, internal hostname, or an IP.
  # Override via ALLOWED_HOSTS env var to lock down to specific domains in prod.
  ALLOWED_HOSTS = _csv_env("ALLOWED_HOSTS", "*")
  # Uploads stored outside webroot, not served statically.
  UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).parent.parent / "data" / "uploads")))
  UPLOAD_MAX_BYTES: int = int(os.getenv("UPLOAD_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB

  # APIFY — Facebook group scraper integration
  APIFY_API_KEY: str = os.getenv("APIFY_API_KEY", "").strip()
  APIFY_ACTOR_IDS: list[str] = _csv_env("APIFY_ACTOR_IDS", "")
  # Comma-separated Facebook group URLs to scrape (e.g. https://www.facebook.com/groups/yachtjobs)
  APIFY_START_URLS: list[str] = _csv_env("APIFY_START_URLS", "")
  # Max posts to fetch per actor run. Default 20 to avoid re-fetching seen posts.
  # Set to 0 for unlimited (not recommended in production — wastes Apify credits).
  APIFY_MAX_ITEMS: int = int(os.getenv("APIFY_MAX_ITEMS", "20"))
  # Per-group post cap sent to the actor as resultsLimit (actor default is 20).
  APIFY_RESULTS_LIMIT: int = int(os.getenv("APIFY_RESULTS_LIMIT", "40"))
  # Run Apify on API startup? Default False — saves cost, first run happens after
  # the first scheduled interval instead.
  APIFY_SCRAPE_ON_STARTUP: bool = os.getenv("APIFY_SCRAPE_ON_STARTUP", "false").lower() == "true"

  # WhatsApp bot — Meta Cloud API
  META_APP_ID: str = os.getenv("META_APP_ID", "").strip()
  META_APP_SECRET: str = os.getenv("META_APP_SECRET", "").strip()
  # One Graph phone number id, or comma-separated ids if this app receives webhooks for multiple numbers.
  _WHATSAPP_PHONE_NUMBER_RAW: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
  WHATSAPP_PHONE_NUMBER_IDS: list[str] = [p.strip() for p in _WHATSAPP_PHONE_NUMBER_RAW.split(",") if p.strip()]
  WHATSAPP_PHONE_NUMBER_ID: str = WHATSAPP_PHONE_NUMBER_IDS[0] if WHATSAPP_PHONE_NUMBER_IDS else ""
  WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
  WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
  # Arbitrary string you set in the Meta webhook dashboard to verify ownership
  META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "carver-whatsapp-verify").strip()
  # Public WhatsApp business number as E.164 digits (no +), e.g. "27821234567".
  # Used to send buyers back to the chat (wa.me link) after a Yoco payment.
  WHATSAPP_PUBLIC_NUMBER: str = "".join(c for c in os.getenv("WHATSAPP_PUBLIC_NUMBER", "") if c.isdigit())
  # Base URL of the frontend — used to build magic links sent via WhatsApp
  FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").strip()
  # How long a magic login link is valid (seconds). Crew often open WhatsApp
  # hours after the bot replies, so links stay valid for 24h by default.
  WA_MAGIC_TOKEN_TTL_SECONDS: int = int(os.getenv("WA_MAGIC_TOKEN_TTL_SECONDS", "86400"))
  # WhatsApp "Recent Posts" matching window, based on when jobs entered the database.
  WA_MATCH_RECENT_DAYS: int = int(os.getenv("WA_MATCH_RECENT_DAYS", "7"))
  # Maintenance mode kill-switch. Off by default: the bot processes inbound
  # messages normally. Set WHATSAPP_MAINTENANCE_MODE=true to take the bot
  # offline — it then replies to every inbound message with a
  # "down for maintenance" notice instead of processing it.
  WHATSAPP_MAINTENANCE_MODE: bool = os.getenv("WHATSAPP_MAINTENANCE_MODE", "false").strip().lower() == "true"

  # Proactive "new jobs match your profile" WhatsApp alerts. Requires a Meta-approved
  # template (paid, business-initiated). Off until a template name is configured.
  # The template must take two body params: {{1}} = first name, {{2}} = match count.
  WHATSAPP_JOB_ALERT_TEMPLATE: str = os.getenv("WHATSAPP_JOB_ALERT_TEMPLATE", "").strip()
  WHATSAPP_JOB_ALERT_LANGUAGE: str = os.getenv("WHATSAPP_JOB_ALERT_LANGUAGE", "en").strip()
  # Minimum hours between alerts to the same user.
  JOB_ALERT_MIN_INTERVAL_HOURS: int = int(os.getenv("JOB_ALERT_MIN_INTERVAL_HOURS", "72"))
  # How often the alert loop scans for new matching jobs.
  JOB_ALERT_CHECK_INTERVAL_HOURS: int = int(os.getenv("JOB_ALERT_CHECK_INTERVAL_HOURS", "24"))

  # Match-quality feedback loop (👍/👎 pulse + "did you apply?" follow-up).
  # Seconds after match results land before the 👍/👎 pulse is sent.
  MATCH_FEEDBACK_DELAY_SECONDS: int = int(os.getenv("MATCH_FEEDBACK_DELAY_SECONDS", "600"))
  # Minimum hours after a match run completes before asking "did you apply?".
  APPLY_FOLLOWUP_MIN_AGE_HOURS: int = int(os.getenv("APPLY_FOLLOWUP_MIN_AGE_HOURS", "18"))
  # How often the apply-followup sweep runs.
  APPLY_FOLLOWUP_CHECK_INTERVAL_HOURS: int = int(os.getenv("APPLY_FOLLOWUP_CHECK_INTERVAL_HOURS", "1"))

  # Job retention — prunes the ever-growing `jobs` table (see services/job_retention.py).
  # Active jobs older than this are soft-expired (status -> "expired").
  JOB_EXPIRE_AFTER_DAYS: int = int(os.getenv("JOB_EXPIRE_AFTER_DAYS", "30"))
  # Any job older than this is deleted outright to keep the table small.
  JOB_DELETE_AFTER_DAYS: int = int(os.getenv("JOB_DELETE_AFTER_DAYS", "90"))
  # How often the retention background loop runs.
  JOB_RETENTION_INTERVAL_HOURS: int = int(os.getenv("JOB_RETENTION_INTERVAL_HOURS", "24"))
  # /status/services flags the job pipeline unhealthy when no new job has been
  # ingested for this many hours (scraper runs every 12h, so 48h = 3 missed cycles).
  JOB_FRESHNESS_ALERT_HOURS: int = int(os.getenv("JOB_FRESHNESS_ALERT_HOURS", "48"))

  # Web job board scrapers
  DOCKWALK_ENABLED: bool = os.getenv("DOCKWALK_ENABLED", "true").lower() == "true"
  WORKONAYACHT_ENABLED: bool = os.getenv("WORKONAYACHT_ENABLED", "true").lower() == "true"
  CREWFINDERS_ENABLED: bool = os.getenv("CREWFINDERS_ENABLED", "true").lower() == "true"
  VIKINGCREW_ENABLED: bool = os.getenv("VIKINGCREW_ENABLED", "true").lower() == "true"
  FASTSTREAM_ENABLED: bool = os.getenv("FASTSTREAM_ENABLED", "true").lower() == "true"
  SUPERYACHTTIMES_ENABLED: bool = os.getenv("SUPERYACHTTIMES_ENABLED", "true").lower() == "true"

  # Telnyx — inbound SMS (Ed25519 public key from Mission Control → API keys → Public key)
  TELNYX_API_KEY: str = os.getenv("TELNYX_API_KEY", "").strip()
  TELNYX_PUBLIC_KEY: str = os.getenv("TELNYX_PUBLIC_KEY", "").strip()
  TELNYX_PHONE_NUMBER: str = os.getenv("TELNYX_PHONE_NUMBER", "").strip()

  # Yoco — Checkout API (https://developer.yoco.com/docs/checkout-api/introduction)
  YOCO_PUBLIC_KEY: str = os.getenv("YOCO_PUBLIC_KEY", "").strip()
  YOCO_SECRET_KEY: str = os.getenv("YOCO_SECRET_KEY", "").strip()
  YOCO_WEBHOOK_SECRET: str = os.getenv("YOCO_WEBHOOK_SECRET", "").strip()
  # Reference unit price (ZAR) — used only as a display fallback. Real pricing
  # lives per-pack below, with a volume discount baked in.
  TOKEN_PRICE: str = os.getenv("TOKEN_PRICE", "11.00").strip()
  # Token packs (ZAR). The unit price drops as the pack grows (volume discount).
  # "Plus" is an intentional decoy — priced just below "Premium" for far fewer
  # tokens — so the best-value pack looks like the obvious choice.
  #   tokens   = credits granted on purchase
  #   price    = total charge in ZAR
  #   label    = pack name
  #   badge    = optional marketing tag shown on the card
  #   highlight= visually emphasise this card as the recommended pack
  #   wa_only  = offered only in the WhatsApp pack picker (kept off the website
  #              grid so the 4-card decoy layout stays intact)
  TOKEN_PACKAGES: list[dict] = [
      # Impulse-priced entry pack: the first payment is the hard part for
      # junior crew, so make saying yes cost less than a beer. No first-purchase
      # bonus on this one (see FIRST_PURCHASE_BONUS_MIN_TOKENS) so Starter —
      # 10 tokens for R65 with the bonus — stays the obviously better deal.
      {"tokens": 2, "price": "25.00", "label": "Kickstart", "wa_only": True},
      {"tokens": 5, "price": "65.00", "label": "Starter"},
      {"tokens": 20, "price": "220.00", "label": "Standard", "badge": "Most Popular"},
      {"tokens": 50, "price": "600.00", "label": "Plus"},
      {"tokens": 75, "price": "675.00", "label": "Premium", "badge": "Best Value", "highlight": True},
  ]

  # Bonus tokens credited on a user's very first completed purchase (any pack).
  # Bonus framing converts better than discounting and keeps pack prices intact.
  FIRST_PURCHASE_BONUS_TOKENS: int = int(os.getenv("FIRST_PURCHASE_BONUS_TOKENS", "5"))
  # Smallest pack (in tokens) that qualifies for the first-purchase bonus —
  # keeps the bonus off the impulse Kickstart pack so it upsells to Starter+.
  FIRST_PURCHASE_BONUS_MIN_TOKENS: int = int(os.getenv("FIRST_PURCHASE_BONUS_MIN_TOKENS", "5"))

  # Free tier — tokens granted to every user each month (reset every 30 days)
  FREE_MONTHLY_TOKENS: int = int(os.getenv("FREE_MONTHLY_TOKENS", "25"))
  # One-time token grant for brand-new accounts (before any subscription)
  FREE_SIGNUP_TOKENS: int = int(os.getenv("FREE_SIGNUP_TOKENS", "2"))
  # Max free tokens a user can earn per 30-day window by posting jobs (web +
  # WhatsApp combined). Caps the old unlimited "post a job, get a token" loop.
  FREE_JOB_POST_TOKENS_PER_MONTH: int = int(os.getenv("FREE_JOB_POST_TOKENS_PER_MONTH", "5"))
  # Tokens an agency/recruiter spends to unlock a crew member's contact details.
  RECRUITER_UNLOCK_COST_TOKENS: int = int(os.getenv("RECRUITER_UNLOCK_COST_TOKENS", "5"))
  # Website feedback prompt is only eligible once an account is at least this many hours old.
  FEEDBACK_MIN_ACCOUNT_AGE_HOURS: int = int(os.getenv("FEEDBACK_MIN_ACCOUNT_AGE_HOURS", "24"))

  # Static bearer token for the AI agent monitoring endpoint (/agent/stats)
  AGENT_API_TOKEN: str = os.getenv("AGENT_API_TOKEN", "").strip()

  # Scrape.do — HTML scraping proxy (alternative scraper)
  SCRAPE_DO_TOKEN: str = os.getenv("SCRAPE_DO_TOKEN", "").strip()
  # Comma-separated URLs to scrape via scrape.do
  SCRAPE_DO_URLS: list[str] = _csv_env("SCRAPE_DO_URLS", "")
  # Enable JS rendering for scrape.do requests (slower but handles SPAs)
  SCRAPE_DO_RENDER: bool = os.getenv("SCRAPE_DO_RENDER", "false").lower() == "true"


settings = Settings()


def validate_database_not_configured_for_postgres() -> None:
    """This API uses SQLite only; refuse a Railway/Heroku-style Postgres DATABASE_URL."""
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return
    low = url.lower()
    if low.startswith(("postgres://", "postgresql://")):
        raise RuntimeError(
            "DATABASE_URL is set to PostgreSQL, but this service uses SQLite only. "
            "Remove the Postgres plugin / DATABASE_URL from Railway (or unset it). "
            "Persist data with a volume on api/data/carver.db or set CARVER_SQLITE_PATH "
            "to your .db file path."
        )


def validate_production_settings() -> None:
    """Refuse to boot in production with insecure defaults."""
    if settings.APP_ENV != "production":
        return
    fatal: list[str] = []
    if settings.SECRET_KEY == "change-me-in-production":
        fatal.append("SECRET_KEY is still the default — set a strong random value")
    if settings.ADMIN_PASSWORD == "change-this-password":
        fatal.append("ADMIN_PASSWORD is still the default — set a strong password")
    if settings.AUTO_LOGIN_AS_ADMIN:
        fatal.append("AUTO_LOGIN_AS_ADMIN must be false in production")
    if settings.META_VERIFY_TOKEN == "carver-whatsapp-verify":
        fatal.append("META_VERIFY_TOKEN is still the default — set a unique webhook verify token")
    if fatal:
        raise RuntimeError(
            "FATAL: Insecure configuration detected in production:\n  - "
            + "\n  - ".join(fatal)
        )
