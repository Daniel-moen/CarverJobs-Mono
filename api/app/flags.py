"""
Feature flags for emergency kill-switches — persisted across restarts.

A kill-switch that forgets is not a kill-switch: the flags used to live only in
memory, so turning the (paid) Apify scraper off survived exactly until the next
deploy, then silently turned itself back on. State is therefore written to a
small JSON file next to the SQLite database — the same volume the DB lives on,
so it survives a container restart on Railway the same way the data does.

The file is only ever a cache of overrides: unknown keys in it are ignored and
missing keys fall back to the defaults below, so adding or renaming a flag in
code never has to be coordinated with the file on disk.

Toggle via PATCH /admin/flags.
"""
import json
import os
import tempfile
import threading
from pathlib import Path

from app.logger import get_logger

log = get_logger("carver.flags")

_lock = threading.Lock()

# Keys must stay stable — frontend and routes reference them by name.
_DEFAULTS: dict[str, bool] = {
    "interview":         True,   # AI interview (/interview/next)
    "onboarding":        True,   # AI onboarding (/interview/onboard)
    "matching":          True,   # Job matching engine (/matching/*)
    "user_registration": True,   # Creating new user accounts (POST /users)
    "scraper":           True,   # Apify Facebook scraper — costs money per run
    "scraper_web":       True,   # Web scrapers (WorkOnAYacht/Yotspot) — free, runs every cycle
    "whatsapp":          True,   # WhatsApp bot (/webhooks/whatsapp)
}

_flags: dict[str, bool] = dict(_DEFAULTS)

# Human-readable label for the dashboard toggle UI.
LABELS: dict[str, str] = {
    "interview":         "AI Interview",
    "onboarding":        "AI Onboarding",
    "matching":          "Job Matching Engine",
    "user_registration": "User Registration",
    "scraper":           "Apify Scraper (paid — Facebook groups)",
    "scraper_web":       "Web Scrapers (free — WorkOnAYacht/Yotspot)",
    "whatsapp":          "WhatsApp Bot",
}


def flags_path() -> Path:
    """Where the override file lives.

    Defaults to `flags.json` beside the SQLite database, so it lands on the
    mounted data volume wherever the DB does. Setting name (optional override):
    CARVER_FLAGS_PATH.
    """
    override = os.getenv("CARVER_FLAGS_PATH", "").strip()
    if override:
        return Path(override)
    from app.database import DB_PATH  # local import — keeps this module import-cheap
    return DB_PATH.parent / "flags.json"


def _load() -> None:
    """Apply persisted overrides over the defaults. Never raises.

    A missing, empty or corrupt file simply means "no overrides": failing open
    (everything on) is the safe direction, because the alternative is an app
    that boots with its features silently disabled.
    """
    try:
        path = flags_path()
        if not path.exists():
            return
        stored = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(stored, dict):
            log.warning("Flag file is not a JSON object — ignoring | path=%s", path)
            return
        applied = {
            key: bool(value)
            for key, value in stored.items()
            if key in _DEFAULTS and isinstance(value, bool)
        }
        _flags.update(applied)
        off = [k for k, v in applied.items() if not v]
        log.info(
            "Feature flags restored | path=%s | overrides=%d | off=%s",
            path, len(applied), ",".join(off) or "none",
        )
    except Exception as exc:
        log.error("Could not read persisted feature flags — using defaults | %s", exc)


def _save() -> None:
    """Write the current flags atomically. Never raises — a failed write only
    costs persistence, and must not fail the admin request that toggled a
    kill-switch (turning the switch off is the urgent part)."""
    try:
        path = flags_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Write-then-rename so a crash mid-write can't leave a truncated file
        # that would be read back as "no overrides" on the next boot.
        fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".flags-", suffix=".json")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(_flags, fh, indent=2, sort_keys=True)
            os.replace(tmp_name, path)
        except Exception:
            os.unlink(tmp_name)
            raise
    except Exception as exc:
        log.error("Could not persist feature flags | %s", exc)


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
        _save()
        return True


def reload_from_disk() -> dict[str, bool]:
    """Re-read the override file over the defaults. Test seam."""
    with _lock:
        _flags.clear()
        _flags.update(_DEFAULTS)
        _load()
        return dict(_flags)


_load()
