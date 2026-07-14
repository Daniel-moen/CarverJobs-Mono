"""Curated yacht-crew role taxonomy — synonyms, departments, seniority.

Deterministic role normalisation shared by the matching prefilter (skip
cross-department jobs before any LLM spend) and the job-alert loop (precision
over naive substring matching). Deliberately curated, not exhaustive: unknown
roles normalise to None and callers fall back to their own heuristics.
"""

from __future__ import annotations

import re

# canonical role -> (department, seniority within department, synonyms)
# Seniority is an ordinal within the department: relatedness treats a gap of
# <=1 as "adjacent" (deckhand <-> bosun) and >1 as "same-department
# senior/junior" (deckhand <-> captain).
_ROLES: dict[str, tuple[str, int, tuple[str, ...]]] = {
    # ── Deck ────────────────────────────────────────────────────────────────
    "deckhand": ("deck", 1, (
        "deckhand", "deck hand", "junior deckhand", "lead deckhand",
        "senior deckhand", "deck crew", "deck",
    )),
    "bosun": ("deck", 2, ("bosun", "boatswain")),
    "officer": ("deck", 3, (
        "officer", "deck officer", "mate", "first mate", "chief mate",
        "chief officer", "2nd officer", "second officer", "3rd officer",
        "third officer", "oow", "officer of the watch",
    )),
    "captain": ("deck", 4, ("captain", "master", "skipper", "relief captain")),
    # ── Engine ──────────────────────────────────────────────────────────────
    "engineer": ("engine", 1, (
        "engineer", "eng", "sole engineer", "yacht engineer", "4th engineer",
        "fourth engineer", "junior engineer", "motorman", "oiler",
    )),
    "third_engineer": ("engine", 1, ("third engineer", "3rd engineer")),
    "second_engineer": ("engine", 2, ("second engineer", "2nd engineer")),
    "chief_engineer": ("engine", 3, (
        "chief engineer", "first engineer", "1st engineer", "head engineer",
    )),
    "eto": ("engine", 2, (
        "eto", "electro-technical officer", "electro technical officer",
        "electrician", "electrical engineer",
    )),
    "avit": ("engine", 2, (
        "avit", "av/it", "av-it", "av it officer", "it officer", "av officer",
        "it engineer", "av engineer", "audio visual",
    )),
    # ── Interior ────────────────────────────────────────────────────────────
    "stewardess": ("interior", 1, (
        "stewardess", "steward", "stew", "junior stewardess", "junior stew",
        "2nd stewardess", "second stewardess", "2nd stew", "3rd stewardess",
        "third stewardess", "3rd stew", "sole stewardess", "service stewardess",
        "housekeeping stewardess", "laundry stewardess",
    )),
    "spa": ("interior", 1, (
        "masseuse", "masseur", "massage therapist", "spa therapist",
        "spa manager", "beautician", "hairdresser", "hair stylist",
        "yoga instructor", "personal trainer", "fitness instructor",
    )),
    "chief_stew": ("interior", 2, (
        "chief stewardess", "chief stew", "chief steward", "head stewardess",
        "head of interior", "interior manager",
    )),
    "purser": ("interior", 3, ("purser",)),
    # ── Galley ──────────────────────────────────────────────────────────────
    "cook": ("galley", 1, ("cook", "crew cook")),
    "sous_chef": ("galley", 2, (
        "sous chef", "sous-chef", "2nd chef", "second chef", "crew chef",
    )),
    "chef": ("galley", 3, (
        "chef", "head chef", "private chef", "yacht chef", "chef de cuisine",
        "executive chef", "solo chef", "sole chef",
    )),
    # ── Medical ─────────────────────────────────────────────────────────────
    "nurse": ("medical", 1, (
        "nurse", "medic", "paramedic", "ship nurse", "medical officer",
    )),
}

# Longest synonym first so "chief stewardess" wins over "stewardess",
# "sous chef" over "chef", "it officer" over "officer", etc.
_SYNONYM_INDEX: list[tuple[str, re.Pattern[str]]] = sorted(
    (
        (canonical, re.compile(r"(?<![a-z0-9])" + re.escape(syn) + r"(?![a-z0-9])"))
        for canonical, (_, _, synonyms) in _ROLES.items()
        for syn in synonyms
    ),
    key=lambda item: len(item[1].pattern),
    reverse=True,
)

_SPLIT_RE = re.compile(r"[,/&;+]|\band\b|\bor\b")

RELATED_SAME = 1.0
RELATED_ADJACENT = 0.7
RELATED_SAME_DEPARTMENT = 0.4


def normalize_role(text: str | None) -> str | None:
    """Map free-text like "Jnr Stew" or "2nd Engineer" to a canonical role.

    The longest matching synonym wins so compound titles resolve to the most
    specific role ("Chief Stewardess" -> chief_stew, not stewardess).
    Returns None when nothing in the curated map matches.
    """
    if not text:
        return None
    t = str(text).strip().lower()
    if not t:
        return None
    for canonical, pattern in _SYNONYM_INDEX:
        if pattern.search(t):
            return canonical
    return None


def normalize_roles(text: str | None) -> list[str]:
    """Normalise a possibly multi-role string ("Deckhand, Engineer / ETO").

    Splits on common separators and normalises each part; falls back to the
    whole string when no part matches. Deduplicates, preserving order.
    """
    if not text:
        return []
    roles: list[str] = []
    for part in _SPLIT_RE.split(str(text).lower()):
        role = normalize_role(part)
        if role and role not in roles:
            roles.append(role)
    if not roles:
        whole = normalize_role(text)
        if whole:
            roles.append(whole)
    return roles


def role_department(role: str | None) -> str | None:
    """Department for a canonical (or free-text) role, or None if unknown."""
    canonical = role if role in _ROLES else normalize_role(role)
    if canonical is None:
        return None
    return _ROLES[canonical][0]


def role_tokens(role: str | None) -> set[str]:
    """All known synonyms (lowercase) for a canonical or free-text role."""
    canonical = role if role in _ROLES else normalize_role(role)
    if canonical is None:
        return set()
    _, _, synonyms = _ROLES[canonical]
    return set(synonyms) | {canonical.replace("_", " ")}


def _related(role_a: str, role_b: str) -> float:
    if role_a == role_b:
        return RELATED_SAME
    dept_a, seniority_a, _ = _ROLES[role_a]
    dept_b, seniority_b, _ = _ROLES[role_b]
    if dept_a != dept_b:
        return 0.0
    if abs(seniority_a - seniority_b) <= 1:
        return RELATED_ADJACENT
    return RELATED_SAME_DEPARTMENT


def roles_related(a: str | None, b: str | None) -> float:
    """Relatedness in [0, 1] between two (possibly multi-role) role strings.

    1.0 = same canonical role, 0.7 = same-department adjacent seniority
    (deckhand <-> bosun), 0.4 = same department but a bigger seniority gap
    (deckhand <-> captain), 0.0 = cross-department or unknown.
    """
    roles_a = normalize_roles(a)
    roles_b = normalize_roles(b)
    best = 0.0
    for role_a in roles_a:
        for role_b in roles_b:
            best = max(best, _related(role_a, role_b))
            if best >= RELATED_SAME:
                return best
    return best
