"""
Demo job seeder — a local development convenience, never a production tool.

Nothing in the application calls run_seed(); it only runs when this file is
executed directly (`python -m app.seed_jobs`). It used to open with
`Base.metadata.drop_all()`, i.e. one stray invocation next to prod credentials
would drop every table in the database — users, payments, WhatsApp sessions,
the lot. That path is now gated behind BOTH an explicit ALLOW_DB_DROP=1 and a
non-production APP_ENV, and refuses loudly otherwise.
"""
import os

from app.database import Base, SessionLocal, engine
from app.logger import get_logger
from app.models import Job
from app.settings import settings

log = get_logger("carver.seed_jobs")

ROLES = [
  "Deckhand",
  "Bosun",
  "Stewardess",
  "Chief Stewardess",
  "Second Engineer",
  "Chief Engineer",
  "Chef",
  "Sous Chef",
  "First Officer",
  "Captain",
]

LOCATIONS = ["Antibes", "Monaco", "Palma", "Fort Lauderdale", "Athens", "Barcelona", "Split", "Nice"]
YACHT_TYPES = ["Motor Yacht", "Sailing Yacht", "Expedition Yacht"]
FLAGS = ["Cayman Islands", "Marshall Islands", "Malta", "Jamaica"]
SEASONS = ["Mediterranean", "Caribbean", "Dual Season"]


def make_job(i: int) -> Job:
  role = ROLES[i % len(ROLES)]
  location = LOCATIONS[i % len(LOCATIONS)]
  yacht_type = YACHT_TYPES[i % len(YACHT_TYPES)]
  season = SEASONS[i % len(SEASONS)]
  flag = FLAGS[i % len(FLAGS)]
  salary_min = 2800 + (i * 75)
  salary_max = salary_min + 900

  return Job(
    title=f"{role} - Immediate Placement #{i + 1}",
    role=role,
    yacht=f"M/Y CARVER Horizon {i + 101}",
    yacht_type=yacht_type,
    yacht_length_m=45 + (i % 35),
    vessel_flag=flag,
    vessel_itinerary=f"{location} base with seasonal passages across {season} charter zones.",
    department="Interior" if "Stew" in role else "Deck/Engineering",
    rank_level="Senior" if role in {"Captain", "Chief Engineer", "Chief Stewardess"} else "Mid-Level",
    location=location,
    start_date=f"2026-{(i % 12) + 1:02d}-{((i * 2) % 27) + 1:02d}",
    contract_type="Permanent" if i % 3 == 0 else "Seasonal",
    leave_structure="3:1" if i % 2 == 0 else "2:2",
    rotation="3:1" if i % 2 == 0 else "2:2",
    season=season,
    salary_currency="EUR",
    salary_min=float(salary_min),
    salary_max=float(salary_max),
    tips_bonus="Charter tips + performance bonus",
    visa_support=i % 2 == 0,
    accommodation="Private/shared cabin depending on rank",
    travel_reimbursement=True,
    experience_required_years=1 + (i % 8),
    minimum_license="STCW, ENG1",
    certifications_required="STCW, ENG1, PDSD, Food Safety, Yachtmaster (role dependent)",
    languages_required="English (required), French/Spanish preferred",
    description=(
      "CARVER partner vessel seeks a polished professional with strong service standards, safety culture, "
      "and adaptability in fast-paced charter operations. Candidate should be confident in guest interaction, "
      "teamwork, and multi-department collaboration."
    ),
    responsibilities=(
      "Maintain vessel standards, execute watchkeeping duties, support guest operations, perform safety drills, "
      "complete checklists, and coordinate with department heads on daily briefs, maintenance windows, and turnaround prep."
    ),
    requirements=(
      "Minimum 1 full season in yachting preferred, verifiable references, clean medicals, "
      "strong communication, and ability to operate under ISM and owner confidentiality protocols."
    ),
    benefits=(
      "Competitive salary, paid leave rotation, medical coverage contribution, training support, "
      "uniform allowance, travel support, and long-term progression opportunities."
    ),
    contact_email=f"recruitment+job{i + 1}@carvercrew.com",
    application_url=f"https://careers.carvercrew.com/jobs/{i + 1}",
    recruiter_name=f"Recruiter {i % 9 + 1}",
    recruiter_agency="CARVER Crew Placement",
    urgent_hire=i % 7 == 0,
    status="priority" if i % 7 == 0 else "open",
    auto_apply_enabled=i % 2 == 0,
  )


def drop_allowed() -> bool:
  """Two independent conditions, both required, before any table is dropped.

  ALLOW_DB_DROP=1 is the deliberate opt-in; the APP_ENV check is the backstop
  for the case the opt-in ends up in a production environment file by accident.
  """
  return (
    os.getenv("ALLOW_DB_DROP", "").strip() == "1"
    and settings.APP_ENV != "production"
  )


def run_seed(*, drop: bool = False):
  """Insert 50 demo jobs. Additive by default — pass drop=True (and set
  ALLOW_DB_DROP=1 outside production) to wipe the schema first."""
  if drop:
    if not drop_allowed():
      raise RuntimeError(
        "Refusing to drop the database: set ALLOW_DB_DROP=1 and run with "
        f"APP_ENV != production (APP_ENV={settings.APP_ENV!r})"
      )
    log.warning("dropping_all_tables_before_seed", app_env=settings.APP_ENV)
    Base.metadata.drop_all(bind=engine)

  Base.metadata.create_all(bind=engine)

  db = SessionLocal()
  try:
    jobs = [make_job(i) for i in range(50)]
    db.add_all(jobs)
    db.commit()
    log.info("seeded_jobs", count=len(jobs))
  finally:
    db.close()


if __name__ == "__main__":
  import argparse

  parser = argparse.ArgumentParser(description="Seed 50 demo jobs (development only)")
  parser.add_argument(
    "--drop",
    action="store_true",
    help="Drop every table first. Requires ALLOW_DB_DROP=1 and APP_ENV != production.",
  )
  run_seed(drop=parser.parse_args().drop)
