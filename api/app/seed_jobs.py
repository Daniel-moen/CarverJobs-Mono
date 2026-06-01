from app.database import Base, SessionLocal, engine
from app.logger import get_logger
from app.models import Job

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


def run_seed():
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
  run_seed()
