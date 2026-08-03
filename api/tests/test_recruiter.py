from app.models import CrewProfile
from app.services.credits import add_credits
from app.settings import settings
from tests.conftest import _TestingSession


def _award(user_key: str, amount: int) -> int:
    db = _TestingSession()
    try:
        return add_credits(db, user_key, amount)
    finally:
        db.close()


def _insert_profile(slug: str, user_key: str, **kw) -> None:
    db = _TestingSession()
    try:
        db.add(CrewProfile(user_key=user_key, profile_slug=slug, **kw))
        db.commit()
    finally:
        db.close()


def _create_profile(client) -> str:
    """Create a discoverable crew profile (keyed to the admin session) and
    return its public slug as discovered via the recruiter listing."""
    resp = client.post("/profile/save", json={
        "first_name": "Alex",
        "last_name": "Crew",
        "desired_role": "Deckhand",
        "current_location": "Antibes",
        "phone": "+27123456789",
    })
    assert resp.status_code == 200
    listing = client.get("/recruiter/candidates").json()
    assert listing["candidates"], "expected the new profile to be listed"
    return listing["candidates"][0]["profile_slug"]


def test_candidates_list_hides_contact_and_reports_cost(client):
    _create_profile(client)
    resp = client.get("/recruiter/candidates")
    assert resp.status_code == 200
    body = resp.json()
    assert body["unlock_cost"] == settings.RECRUITER_UNLOCK_COST_TOKENS
    cand = body["candidates"][0]
    assert cand["unlocked"] is False
    assert cand["email"] is None and cand["phone"] is None
    assert cand["desired_role"] == "Deckhand"


def test_unlock_requires_enough_tokens(client, monkeypatch):
    # Pin the grant to zero: the signup grant and the unlock cost are tuned
    # independently, so this must not depend on one being smaller than the other.
    monkeypatch.setattr(settings, "FREE_SIGNUP_TOKENS", 0)
    slug = _create_profile(client)
    resp = client.post(f"/recruiter/candidates/{slug}/unlock")
    assert resp.status_code == 402


def test_unlock_spends_tokens_then_is_free_to_review(client):
    slug = _create_profile(client)
    _award("admin", 10)

    first = client.post(f"/recruiter/candidates/{slug}/unlock")
    assert first.status_code == 200
    data = first.json()
    assert data["already_unlocked"] is False
    assert data["cost"] == settings.RECRUITER_UNLOCK_COST_TOKENS
    assert data["phone"] == "+27123456789"
    balance_after = data["balance"]

    # Re-unlocking the same candidate is free and does not charge again.
    second = client.post(f"/recruiter/candidates/{slug}/unlock")
    assert second.status_code == 200
    sdata = second.json()
    assert sdata["already_unlocked"] is True
    assert sdata["cost"] == 0
    assert sdata["balance"] == balance_after

    # It now appears in the unlocked list with contact details.
    unlocked = client.get("/recruiter/unlocked").json()
    assert unlocked["total"] == 1
    assert unlocked["candidates"][0]["phone"] == "+27123456789"

    # And the browse list also returns the contact for an already-unlocked
    # candidate — revisiting the "Find Crew" tab must not hide what was paid for.
    listing = client.get("/recruiter/candidates").json()
    card = next(c for c in listing["candidates"] if c["profile_slug"] == slug)
    assert card["unlocked"] is True
    assert card["phone"] == "+27123456789"


def test_unknown_slug_returns_404(client):
    _award("admin", 10)
    resp = client.post("/recruiter/candidates/nope123/unlock")
    assert resp.status_code == 404


def test_non_discoverable_profile_is_hidden_and_cannot_be_unlocked(client):
    _insert_profile("hidden01", "hidden@example.com", desired_role="Chef", discoverable=False)
    _award("admin", 10)

    listing = client.get("/recruiter/candidates").json()
    slugs = [c["profile_slug"] for c in listing["candidates"]]
    assert "hidden01" not in slugs

    resp = client.post("/recruiter/candidates/hidden01/unlock")
    assert resp.status_code == 404


def test_role_filter_narrows_results(client):
    _insert_profile("deck01", "deck@example.com", desired_role="Deckhand")
    _insert_profile("chef01", "chef@example.com", desired_role="Chef")

    listing = client.get("/recruiter/candidates?role=Chef").json()
    slugs = [c["profile_slug"] for c in listing["candidates"]]
    assert "chef01" in slugs
    assert "deck01" not in slugs


def test_candidates_require_agency_or_admin(auth_client):
    # auth_client has no session → must be rejected (not a 200).
    resp = auth_client.get("/recruiter/candidates")
    assert resp.status_code in (401, 403)
