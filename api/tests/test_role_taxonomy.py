from app.services.job_alerts import _matching_jobs, _role_tokens
from app.services.role_taxonomy import (
    normalize_role,
    normalize_roles,
    role_tokens,
    roles_related,
)


# ── normalize_role ───────────────────────────────────────────────────────────

def test_normalize_role_synonyms():
    assert normalize_role("Deckhand") == "deckhand"
    assert normalize_role("Junior Deckhand — 45m MY") == "deckhand"
    assert normalize_role("Bosun") == "bosun"
    assert normalize_role("Stew") == "stewardess"
    assert normalize_role("2nd Stewardess") == "stewardess"
    assert normalize_role("Steward") == "stewardess"
    assert normalize_role("eng") == "engineer"
    assert normalize_role("Sole Engineer 38m") == "engineer"
    assert normalize_role("ETO") == "eto"
    assert normalize_role("Masseuse") == "spa"


def test_normalize_role_longest_synonym_wins():
    # Compound titles must resolve to the most specific role, not a substring.
    assert normalize_role("Chief Stewardess") == "chief_stew"
    assert normalize_role("Sous Chef") == "sous_chef"
    assert normalize_role("Head Chef") == "chef"
    assert normalize_role("2nd Engineer") == "second_engineer"
    assert normalize_role("Chief Engineer") == "chief_engineer"
    assert normalize_role("AV/IT Officer") != "officer"
    assert normalize_role("Chief Officer") == "officer"


def test_normalize_role_no_short_substring_overmatch():
    # "eng" must only match as a whole token, never inside other words.
    assert normalize_role("England-based recruiter") is None
    assert normalize_role("Stewart Island charter") is None
    assert normalize_role("") is None
    assert normalize_role(None) is None
    assert normalize_role("Underwater basket weaver") is None


def test_normalize_roles_multi_role_string():
    assert normalize_roles("Deckhand, Engineer / ETO") == ["deckhand", "engineer", "eto"]
    assert normalize_roles("Deck/Stew") == ["deckhand", "stewardess"]
    assert normalize_roles("") == []


# ── roles_related ────────────────────────────────────────────────────────────

def test_roles_related_same_role():
    assert roles_related("Deckhand", "Junior Deckhand") == 1.0
    assert roles_related("Stew", "2nd Stewardess") == 1.0


def test_roles_related_adjacent_same_department():
    assert roles_related("Deckhand", "Bosun") == 0.7
    assert roles_related("Stewardess", "Chief Stew") == 0.7
    assert roles_related("2nd Engineer", "Chief Engineer") == 0.7
    assert roles_related("Sous Chef", "Head Chef") == 0.7


def test_roles_related_same_department_senior_junior():
    assert roles_related("Deckhand", "Captain") == 0.4
    assert roles_related("Stewardess", "Purser") == 0.4


def test_roles_related_cross_department_is_zero():
    assert roles_related("Deckhand", "Stewardess") == 0.0
    assert roles_related("Chef", "Captain") == 0.0
    assert roles_related("Nurse", "Engineer") == 0.0


def test_roles_related_unknown_roles():
    assert roles_related("Astronaut", "Deckhand") == 0.0
    assert roles_related("", "Deckhand") == 0.0
    assert roles_related(None, None) == 0.0


def test_roles_related_multi_role_takes_best():
    assert roles_related("Deckhand, Engineer", "Chief Engineer") == 0.4
    assert roles_related("Deck/Stew", "Chief Stewardess") == 0.7


# ── role_tokens ──────────────────────────────────────────────────────────────

def test_role_tokens_returns_synonyms():
    tokens = role_tokens("stewardess")
    assert "stew" in tokens
    assert "steward" in tokens
    assert role_tokens("Chief Stewardess") == role_tokens("chief_stew")
    assert role_tokens("unknown role") == set()


# ── job_alerts integration ───────────────────────────────────────────────────

class _J:
    def __init__(self, role, title):
        self.role = role
        self.title = title


def test_job_alert_role_tokens_canonicalise():
    assert _role_tokens("Deckhand, Engineer / ETO") == ["deckhand", "engineer", "eto"]
    # Abbreviations resolve via the taxonomy.
    assert _role_tokens("Stew") == ["stewardess"]
    assert _role_tokens("eng") == ["engineer"]
    # Unknown parts fall back to plain tokens, but 3-char fragments are dropped.
    assert _role_tokens("Underwater welder") == ["underwater welder"]
    assert _role_tokens("xyz") == []


def test_job_alert_matching_uses_taxonomy():
    jobs = [
        _J("Deckhand", "Junior Deckhand — 45m MY"),
        _J("Chief Stewardess", "Chief Stew needed"),
        _J("", "Sole Engineer 38m"),
        _J("Captain", "Captain 60m+"),
    ]
    # Same role.
    assert _matching_jobs(jobs, "Deckhand") == [jobs[0]]
    # "Stew" reaches the adjacent Chief Stew job, nothing cross-department.
    assert _matching_jobs(jobs, "Stew") == [jobs[1]]
    assert _matching_jobs(jobs, "Engineer") == [jobs[2]]
    # Senior/junior in the same department (0.4) is below the alert bar.
    assert _matching_jobs(jobs, "Captain") == [jobs[3]]
    assert _matching_jobs(jobs, "") == []


def test_job_alert_matching_no_three_char_overmatch():
    jobs = [_J("Stewardess", "Stewardess for England-flagged yacht")]
    # Old substring logic matched "eng" inside "England"; taxonomy must not.
    assert _matching_jobs(jobs, "eng") == []


def test_job_alert_matching_unknown_role_falls_back_to_token():
    jobs = [
        _J("Dive Instructor", "Dive Instructor / Deckhand"),
        _J("Stewardess", "2nd Stew"),
    ]
    assert _matching_jobs(jobs, "Dive Instructor") == [jobs[0]]
