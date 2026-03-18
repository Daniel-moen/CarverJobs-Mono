"""
Standalone scraper debug tool — runs any scraper independently and prints results.

Usage (from api/ directory):
    python scripts/test_scrapers.py apify
    python scripts/test_scrapers.py dockwalk
    python scripts/test_scrapers.py workonayacht
    python scripts/test_scrapers.py faststream
    python scripts/test_scrapers.py crewfinders
    python scripts/test_scrapers.py vikingcrew
    python scripts/test_scrapers.py reed
    python scripts/test_scrapers.py all       # run all enabled scrapers

Flags:
    --no-sync     fetch raw items only, skip DB sync (no AI calls, no DB writes)
    --limit N     override max_items for Apify (default: from .env)

Examples:
    python scripts/test_scrapers.py apify --no-sync
    python scripts/test_scrapers.py apify --limit 10
    python scripts/test_scrapers.py all --no-sync
"""
import argparse
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.settings import settings  # noqa: E402
from app.database import SessionLocal, Base, engine  # noqa: E402


def _hdr(title: str) -> None:
    print()
    print("=" * 60)
    print(f"  {title}")
    print("=" * 60)


def _show_items(items: list[dict], label: str) -> None:
    print(f"\n{label}: {len(items)} raw items fetched")
    if not items:
        return
    print("\nSample (first item):")
    sample = items[0]
    for k, v in list(sample.items())[:15]:
        val = textwrap.shorten(str(v).replace("\n", " "), 120)
        print(f"  {k:30s} {val}")
    if len(sample) > 15:
        print(f"  … (+{len(sample) - 15} more fields)")


def _sync(items: list[dict], source: str) -> None:
    if not items:
        print("Nothing to sync.")
        return
    from app.services.job_sync import sync_jobs, JobSyncError
    print(f"\nSyncing {len(items)} items to DB (OpenAI model: {settings.OPENAI_MODEL})…")
    db = SessionLocal()
    try:
        created, skipped, errors = sync_jobs(
            db, items,
            openai_api_key=settings.OPENAI_API_KEY,
            openai_model=settings.OPENAI_MODEL,
            source=source,
        )
        print(f"  created={created}  skipped={skipped}  errors={errors}")
    except JobSyncError as exc:
        print(f"  DB sync error: {exc}")
    finally:
        db.close()


# ── Per-scraper runners ───────────────────────────────────────────────────────

def run_apify(no_sync: bool, limit: int | None) -> None:
    _hdr("APIFY — Facebook Groups")
    from app.services.apify_scraper import ApifyScraper, ApifyError

    if not settings.APIFY_API_KEY:
        print("ERROR: APIFY_API_KEY not set"); return
    if not settings.APIFY_ACTOR_IDS:
        print("ERROR: APIFY_ACTOR_IDS not set"); return
    if not settings.APIFY_START_URLS:
        print("ERROR: APIFY_START_URLS not set"); return

    max_items = limit if limit is not None else settings.APIFY_MAX_ITEMS
    print(f"Actor  : {settings.APIFY_ACTOR_IDS}")
    print(f"Groups : {len(settings.APIFY_START_URLS)} URLs")
    print(f"Limit  : {max_items or 'unlimited'}")
    print("NOTE   : NOT sending onlyPostsNewerThan to actor (unreliable param)")

    try:
        scraper = ApifyScraper(
            api_key=settings.APIFY_API_KEY,
            actor_ids=settings.APIFY_ACTOR_IDS,
            start_urls=settings.APIFY_START_URLS,
            max_items=max_items,
            # intentionally no `since` — see scheduler.py comment
        )
        items = scraper.scrape_all()
    except ApifyError as exc:
        print(f"Apify error: {exc}"); return

    _show_items(items, "Apify")
    if not no_sync:
        _sync(items, "apify")


def run_dockwalk(no_sync: bool) -> None:
    _hdr("Dockwalk")
    from app.services.dockwalk_scraper import DockwalkScraper
    try:
        items = DockwalkScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "Dockwalk")
    if not no_sync:
        _sync(items, "dockwalk")


def run_workonayacht(no_sync: bool) -> None:
    _hdr("WorkOnAYacht / Yotspot")
    from app.services.workonayacht_scraper import WorkOnAYachtScraper
    try:
        items = WorkOnAYachtScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "WorkOnAYacht")
    if not no_sync:
        _sync(items, "workonayacht")


def run_faststream(no_sync: bool) -> None:
    _hdr("Faststream")
    from app.services.faststream_scraper import FaststreamScraper
    try:
        items = FaststreamScraper().scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "Faststream")
    if not no_sync:
        _sync(items, "faststream")


def run_crewfinders(no_sync: bool) -> None:
    _hdr("CrewFinders")
    from app.services.crewfinders_scraper import CrewFindersScraper
    try:
        items = CrewFindersScraper().scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "CrewFinders")
    if not no_sync:
        _sync(items, "crewfinders")


def run_vikingcrew(no_sync: bool) -> None:
    _hdr("Viking Crew")
    from app.services.vikingcrew_scraper import VikingCrewScraper
    try:
        items = VikingCrewScraper(scrape_do_token=settings.SCRAPE_DO_TOKEN).scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "Viking Crew")
    if not no_sync:
        _sync(items, "vikingcrew")


def run_reed(no_sync: bool) -> None:
    _hdr("Reed (SuperYachtTimes)")
    from app.services.superyachttimes_scraper import SuperYachtTimesScraper
    try:
        items = SuperYachtTimesScraper().scrape()
    except Exception as exc:
        print(f"Error: {exc}"); return
    _show_items(items, "Reed")
    if not no_sync:
        _sync(items, "reed")


# ── CLI ───────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Run a scraper independently for debugging")
    parser.add_argument(
        "scraper",
        choices=["apify", "dockwalk", "workonayacht", "faststream", "crewfinders", "vikingcrew", "reed", "all"],
        help="Which scraper to run",
    )
    parser.add_argument("--no-sync", action="store_true", help="Skip DB sync (no AI calls, no writes)")
    parser.add_argument("--limit", type=int, default=None, help="Override APIFY_MAX_ITEMS")
    args = parser.parse_args()

    Base.metadata.create_all(bind=engine)

    targets = (
        ["apify", "dockwalk", "workonayacht", "faststream", "crewfinders", "vikingcrew", "reed"]
        if args.scraper == "all"
        else [args.scraper]
    )

    for t in targets:
        if t == "apify":
            run_apify(args.no_sync, args.limit)
        elif t == "dockwalk":
            run_dockwalk(args.no_sync)
        elif t == "workonayacht":
            run_workonayacht(args.no_sync)
        elif t == "faststream":
            run_faststream(args.no_sync)
        elif t == "crewfinders":
            run_crewfinders(args.no_sync)
        elif t == "vikingcrew":
            run_vikingcrew(args.no_sync)
        elif t == "reed":
            run_reed(args.no_sync)

    return 0


if __name__ == "__main__":
    sys.exit(main())
