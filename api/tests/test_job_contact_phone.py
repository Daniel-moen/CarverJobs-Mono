"""Tests for contact_phone extraction (services/job_sync).

Crew apply by WhatsApp as often as by email, so a post whose only contact
detail is a phone number was being stored as unactionable. The rule under test:
normalise to E.164 when the country code is *knowable*, keep the poster's text
when it isn't, and never turn a vessel length or a salary into a phone number.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Job
from app.services import job_sync
from app.services.job_sync import (
    _build_job_fields,
    _extract_phone,
    _normalise_phone,
    sync_jobs,
)

_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
_Session = sessionmaker(autocommit=False, autoflush=False, bind=_engine)


@pytest.fixture()
def db():
    Base.metadata.create_all(bind=_engine)
    session = _Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=_engine)


# ── Normalisation ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("+27821234567", "+27821234567"),                 # South Africa, already E.164
    ("+27 82 123 4567", "+27821234567"),              # spaces stripped
    ("+33 6 12 34 56 78", "+33612345678"),            # France
    ("+44 (0)7911 123456", "+4407911123456"),         # UK, kept verbatim in digits
    ("+1 (415) 555-0123", "+14155550123"),            # US
    ("0027821234567", "+27821234567"),                # 00 IDD prefix → +
    ("0033 6 12 34 56 78", "+33612345678"),
])
def test_international_numbers_become_e164(raw, expected):
    assert _normalise_phone(raw) == expected


def test_local_number_is_kept_verbatim():
    """Guessing a country code for a bare local number gets a stranger called."""
    assert _normalise_phone("082 123 4567") == "082 123 4567"


def test_whitespace_is_collapsed_in_local_numbers():
    assert _normalise_phone("  082   123\t4567 ") == "082 123 4567"


@pytest.mark.parametrize("raw", [None, "", "   ", "45", "2026", "3000-4000", "n/a"])
def test_non_phone_values_are_dropped(raw):
    assert _normalise_phone(raw) is None


def test_over_long_digit_runs_are_dropped():
    """E.164 tops out at 15 digits — anything longer is an id, not a number."""
    assert _normalise_phone("+1234567890123456789") is None


# ── Extraction from post text ─────────────────────────────────────────────────

def test_extracts_international_number_from_a_post():
    text = "Chief Stew needed in Antibes. WhatsApp Marie on +33 6 12 34 56 78 to apply."
    assert _extract_phone(text) == "+33612345678"


def test_extracts_south_african_number():
    text = "Deckhand wanted, Cape Town based. Call +27 82 123 4567."
    assert _extract_phone(text) == "+27821234567"


def test_ignores_vessel_specs_and_salaries():
    text = "50m motor yacht, built 2019, salary 3000-4000 EUR per month, 10 crew."
    assert _extract_phone(text) is None


def test_ignores_bare_local_numbers_in_free_text():
    """Without a country the regex can't tell a phone from any other digit run."""
    text = "Deckhand wanted. Call 082 123 4567."
    assert _extract_phone(text) is None


def test_empty_text_is_safe():
    assert _extract_phone("") is None


# ── Field mapping ─────────────────────────────────────────────────────────────

def test_ai_phone_wins_over_the_regex():
    fields = _build_job_fields(
        {"contact_phone": "082 123 4567 (South Africa)"},
        {"text": "Or reach the office on +44 20 7946 0000"},
        "apify",
    )
    assert fields["contact_phone"] == "082 123 4567 (South Africa)"


def test_ai_phone_is_normalised_to_e164():
    fields = _build_job_fields({"contact_phone": "+27 82 123 4567"}, {}, "apify")
    assert fields["contact_phone"] == "+27821234567"


def test_regex_fallback_when_the_ai_found_nothing():
    fields = _build_job_fields(
        {"contact_phone": None},
        {"text": "Stew needed. WhatsApp +33 6 12 34 56 78."},
        "apify",
    )
    assert fields["contact_phone"] == "+33612345678"


def test_raw_item_hint_is_used_before_the_regex():
    fields = _build_job_fields(
        {},
        {"contact_phone": "+14155550123", "text": "Call +33 6 12 34 56 78"},
        "workonayacht",
    )
    assert fields["contact_phone"] == "+14155550123"


def test_no_phone_anywhere_is_none():
    fields = _build_job_fields({}, {"text": "Deckhand needed in Palma."}, "apify")
    assert fields["contact_phone"] is None


def test_phone_does_not_disturb_the_email(monkeypatch):
    fields = _build_job_fields(
        {},
        {"text": "Apply to crew@yacht.com or WhatsApp +27 82 123 4567"},
        "apify",
    )
    assert fields["contact_email"] == "crew@yacht.com"
    assert fields["contact_phone"] == "+27821234567"


# ── End to end through sync_jobs ──────────────────────────────────────────────

def test_contact_phone_is_persisted(db, monkeypatch):
    def _stub(post_text, post_url, api_key, model, trusted_source=False):
        return {
            "title": "Chief Stewardess",
            "role": "Chief Stewardess",
            "location": "Antibes",
            "contact_phone": "+33 6 12 34 56 78",
        }

    monkeypatch.setattr(job_sync, "review_post", _stub)

    created, _skipped, errors = sync_jobs(
        db,
        [{"url": "https://facebook.com/posts/1", "text": "Chief Stew needed in Antibes."}],
        openai_api_key="k", openai_model="m", source="apify",
    )

    assert (created, errors) == (1, 0)
    job = db.query(Job).one()
    assert job.contact_phone == "+33612345678"
