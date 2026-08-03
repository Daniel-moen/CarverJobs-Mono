from app.services.credits import add_credits
from app.services.matching_engine import MatchResult
from app.settings import settings
from tests.conftest import _TestingSession


def _award_credits(user_key: str, amount: int) -> int:
    db = _TestingSession()
    try:
        return add_credits(db, user_key, amount)
    finally:
        db.close()


def _seed_profile_and_job(client) -> None:
    profile_resp = client.post("/profile/save", json={"first_name": "Alex", "desired_role": "Deckhand"})
    assert profile_resp.status_code == 200

    job_resp = client.post("/jobs", json={
        "title": "Deckhand",
        "role": "Deckhand",
        "yacht": "M/Y Horizon",
        "location": "Antibes",
    })
    assert job_resp.status_code == 201


def test_auth_session_reports_credit_balance(client):
    _award_credits("admin", 3)

    resp = client.get("/auth/session")

    assert resp.status_code == 200
    # Awarded credits sit on top of the free signup grant, whatever it is set to.
    assert resp.json()["session"]["credits_balance"] == settings.FREE_SIGNUP_TOKENS + 3


def test_profile_me_reports_credit_balance_without_profile(client):
    _award_credits("admin", 2)

    resp = client.get("/profile/me")

    assert resp.status_code == 200
    assert resp.json()["profile"] is None
    assert resp.json()["credits_balance"] == settings.FREE_SIGNUP_TOKENS + 2


def test_matching_find_requires_credit(client, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    # This is the empty-wallet path, so the signup grant must be out of the way.
    monkeypatch.setattr(settings, "FREE_SIGNUP_TOKENS", 0)
    _seed_profile_and_job(client)

    resp = client.post("/matching/find")

    assert resp.status_code == 402
    assert resp.json()["detail"] == (
        "You're out of tokens. Top up to keep matching, or submit a job to earn a free token."
    )


def test_matching_find_spends_one_credit_and_returns_remaining(client, monkeypatch):
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "test-key")
    # Exactly one credit, so "spends one, none left" is what's being measured.
    monkeypatch.setattr(settings, "FREE_SIGNUP_TOKENS", 0)
    _seed_profile_and_job(client)
    _award_credits("admin", 1)

    def _fake_match_candidate_to_jobs(**_kwargs):
        return [
            MatchResult(
                job_id=1,
                matched=True,
                compatibility=91,
                reason="Strong fit for the role.",
                strengths=["Deck experience"],
                gaps=[],
                factor_scores={"role": 95, "experience": 87},
            )
        ]

    monkeypatch.setattr("app.routes.crew_match.match_candidate_to_jobs", _fake_match_candidate_to_jobs)
    # The result-persisting worker opens its own session straight from
    # app.database, which bypasses the get_db override and would otherwise look
    # for the run in the developer's real DB and report it superseded.
    import app.database as app_database
    monkeypatch.setattr(app_database, "SessionLocal", _TestingSession)

    resp = client.post("/matching/find")

    assert resp.status_code == 200
    assert "event: complete" in resp.text
    assert '"credits_remaining":0' in resp.text

    session_resp = client.get("/auth/session")
    assert session_resp.status_code == 200
    assert session_resp.json()["session"]["credits_balance"] == 0
