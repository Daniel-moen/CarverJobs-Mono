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
  POSTHOG_API_KEY = os.getenv("POSTHOG_API_KEY", os.getenv("POSTHOG_PROJECT_API_KEY", os.getenv("VITE_POSTHOG_KEY", ""))).strip()
  POSTHOG_HOST = os.getenv("POSTHOG_HOST", os.getenv("VITE_POSTHOG_HOST", "https://us.i.posthog.com")).strip().rstrip("/")
  POSTHOG_LLM_CAPTURE_CONTENT = os.getenv("POSTHOG_LLM_CAPTURE_CONTENT", "false").lower() == "true"

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
  # Base URL of the frontend — used to build magic links sent via WhatsApp
  FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").strip()
  # How long a magic login link is valid (seconds)
  WA_MAGIC_TOKEN_TTL_SECONDS: int = int(os.getenv("WA_MAGIC_TOKEN_TTL_SECONDS", "1800"))
  # WhatsApp "Recent Posts" matching window, based on when jobs entered the database.
  WA_MATCH_RECENT_DAYS: int = int(os.getenv("WA_MATCH_RECENT_DAYS", "7"))

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
  TOKEN_PRICE: str = os.getenv("TOKEN_PRICE", "10.00").strip()
  TOKEN_PACKAGES: list[int] = [10, 20]

  # Free tier — tokens granted to every user each month (reset every 30 days)
  FREE_MONTHLY_TOKENS: int = int(os.getenv("FREE_MONTHLY_TOKENS", "25"))
  # One-time token grant for brand-new accounts (before any subscription)
  FREE_SIGNUP_TOKENS: int = int(os.getenv("FREE_SIGNUP_TOKENS", "2"))

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
