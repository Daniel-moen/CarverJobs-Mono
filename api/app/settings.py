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
  SESSION_SECURE_COOKIE = os.getenv("SESSION_SECURE_COOKIE", "false").lower() == "true"

  ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
  ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-this-password")
  GOOGLE_OAUTH_CLIENT_ID = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
  GOOGLE_ALLOWED_EMAILS = [email.lower() for email in _csv_env("GOOGLE_ALLOWED_EMAILS", "")]
  GOOGLE_ALLOWED_DOMAIN = os.getenv("GOOGLE_ALLOWED_DOMAIN", "").strip().lower()
  GOOGLE_REQUIRE_VERIFIED_EMAIL = os.getenv("GOOGLE_REQUIRE_VERIFIED_EMAIL", "true").lower() == "true"
  OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
  OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()

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
  WHATSAPP_PHONE_NUMBER_ID: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
  WHATSAPP_BUSINESS_ACCOUNT_ID: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "").strip()
  WHATSAPP_ACCESS_TOKEN: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
  # Arbitrary string you set in the Meta webhook dashboard to verify ownership
  META_VERIFY_TOKEN: str = os.getenv("META_VERIFY_TOKEN", "carver-whatsapp-verify").strip()
  # Base URL of the frontend — used to build magic links sent via WhatsApp
  FRONTEND_BASE_URL: str = os.getenv("FRONTEND_BASE_URL", "http://localhost:5173").strip()
  # How long a magic login link is valid (seconds)
  WA_MAGIC_TOKEN_TTL_SECONDS: int = int(os.getenv("WA_MAGIC_TOKEN_TTL_SECONDS", "1800"))

  # Web job board scrapers
  DOCKWALK_ENABLED: bool = os.getenv("DOCKWALK_ENABLED", "true").lower() == "true"
  WORKONAYACHT_ENABLED: bool = os.getenv("WORKONAYACHT_ENABLED", "true").lower() == "true"
  CREWFINDERS_ENABLED: bool = os.getenv("CREWFINDERS_ENABLED", "true").lower() == "true"
  VIKINGCREW_ENABLED: bool = os.getenv("VIKINGCREW_ENABLED", "true").lower() == "true"
  FASTSTREAM_ENABLED: bool = os.getenv("FASTSTREAM_ENABLED", "true").lower() == "true"
  SUPERYACHTTIMES_ENABLED: bool = os.getenv("SUPERYACHTTIMES_ENABLED", "true").lower() == "true"

  # Scrape.do — HTML scraping proxy (alternative scraper)
  SCRAPE_DO_TOKEN: str = os.getenv("SCRAPE_DO_TOKEN", "").strip()
  # Comma-separated URLs to scrape via scrape.do
  SCRAPE_DO_URLS: list[str] = _csv_env("SCRAPE_DO_URLS", "")
  # Enable JS rendering for scrape.do requests (slower but handles SPAs)
  SCRAPE_DO_RENDER: bool = os.getenv("SCRAPE_DO_RENDER", "false").lower() == "true"


settings = Settings()


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
    if fatal:
        raise RuntimeError(
            "FATAL: Insecure configuration detected in production:\n  - "
            + "\n  - ".join(fatal)
        )
