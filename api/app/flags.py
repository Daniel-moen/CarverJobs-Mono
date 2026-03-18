"""
In-memory feature flags for emergency kill-switches.

Flags reset to True (all on) on server restart. Toggle via PATCH /admin/flags.
"""
import threading

_lock = threading.Lock()

# Keys must stay stable — frontend and routes reference them by name.
_flags: dict[str, bool] = {
    "interview":         True,   # AI interview (/interview/next)
    "onboarding":        True,   # AI onboarding (/interview/onboard)
    "matching":          True,   # Job matching engine (/matching/*)
    "user_registration": True,   # Creating new user accounts (POST /users)
    "scraper":           True,   # Apify Facebook scraper — costs money per run
    "scraper_web":       True,   # Web scrapers (Dockwalk, Yotspot) — free, runs every cycle
    "whatsapp":          True,   # WhatsApp bot (/whatsapp/webhook)
}

# Human-readable label for the dashboard toggle UI.
LABELS: dict[str, str] = {
    "interview":         "AI Interview",
    "onboarding":        "AI Onboarding",
    "matching":          "Job Matching Engine",
    "user_registration": "User Registration",
    "scraper":           "Apify Scraper (paid — Facebook groups)",
    "scraper_web":       "Web Scrapers (free — Dockwalk + Yotspot)",
    "whatsapp":          "WhatsApp Bot",
}


def get_all() -> dict[str, bool]:
    with _lock:
        return dict(_flags)


def is_enabled(key: str) -> bool:
    with _lock:
        return _flags.get(key, True)


def set_flag(key: str, value: bool) -> bool:
    """Returns False if key does not exist."""
    with _lock:
        if key not in _flags:
            return False
        _flags[key] = value
        return True
