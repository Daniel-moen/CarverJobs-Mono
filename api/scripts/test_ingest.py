"""
Standalone Apify ingest test.

Runs a full scrape cycle synchronously and prints a summary — no FastAPI server needed.

Usage (from the api/ directory):
    python scripts/test_ingest.py

Or with a custom item limit:
    APIFY_MAX_ITEMS=5 python scripts/test_ingest.py
"""
import sys
from pathlib import Path

# Allow imports from app/ when running as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402 — must come after sys.path fix
from app.database import SessionLocal, Base, engine  # noqa: E402
from app.services.apify_scraper import (  # noqa: E402
    ApifyScraper,
    ApifyKeyMissingError,
    ApifyActorMissingError,
    ApifyError,
)
from app.services.job_sync import sync_jobs, JobSyncError  # noqa: E402


def _check_config() -> bool:
    ok = True
    if not settings.APIFY_API_KEY:
        print("ERROR: APIFY_API_KEY is not set in api/.env")
        ok = False
    if not settings.APIFY_ACTOR_IDS:
        print("ERROR: APIFY_ACTOR_IDS is not set in api/.env")
        ok = False
    if not settings.APIFY_START_URLS:
        print("ERROR: APIFY_START_URLS is not set in api/.env")
        ok = False
    return ok


def main() -> int:
    print("=" * 60)
    print("CARVER — Apify ingest test")
    print("=" * 60)

    if not _check_config():
        return 1

    print(f"Actor IDs  : {settings.APIFY_ACTOR_IDS}")
    print(f"Start URLs : {settings.APIFY_START_URLS}")
    print(f"Max items  : {settings.APIFY_MAX_ITEMS or 'unlimited'}")
    print()

    # Ensure DB tables exist (safe to call on an already-initialised DB).
    Base.metadata.create_all(bind=engine)

    scraper = ApifyScraper(
        api_key=settings.APIFY_API_KEY,
        actor_ids=settings.APIFY_ACTOR_IDS,
        start_urls=settings.APIFY_START_URLS,
        max_items=settings.APIFY_MAX_ITEMS,
    )

    print("Starting Apify scrape…")
    try:
        items = scraper.scrape_all()
    except ApifyKeyMissingError as exc:
        print(f"ERROR (key missing): {exc}")
        return 1
    except ApifyActorMissingError as exc:
        print(f"ERROR (actor missing): {exc}")
        return 1
    except ApifyError as exc:
        print(f"ERROR (apify): {exc}")
        return 1

    print(f"Fetched {len(items)} raw items from Apify")

    if not items:
        print("Nothing to sync — check your Facebook group URLs and actor configuration.")
        return 0

    print("\nSample raw item (first result):")
    sample = items[0]
    for k, v in list(sample.items())[:15]:
        val = str(v)[:120].replace("\n", " ")
        print(f"  {k}: {val}")
    if len(sample) > 15:
        print(f"  … (+{len(sample) - 15} more fields)")

    print("\nSyncing to database…")
    db = SessionLocal()
    try:
        created, skipped, errors = sync_jobs(db, items)
    except JobSyncError as exc:
        print(f"ERROR (db sync): {exc}")
        return 1
    finally:
        db.close()

    print()
    print("=" * 60)
    print(f"Result  — created: {created}  skipped: {skipped}  errors: {errors}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
