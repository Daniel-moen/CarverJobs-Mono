import json

from app.routes.scraper import _run_import_pipeline, _save_job_from_ai_fields
from app.services.matching_engine import (
    CandidateProfile,
    JobSummary,
    _call_openai,
    match_candidate_to_jobs,
)
from tests.conftest import _TestingSession


def test_run_import_pipeline_dedupes_same_position_by_fingerprint(monkeypatch):
    monkeypatch.setattr("app.routes.scraper.SessionLocal", _TestingSession)

    calls = {"count": 0}

    def _fake_review_post(post_text, post_url, api_key, model, trusted_source=False):
        calls["count"] += 1
        if calls["count"] == 1:
            return {
                "title": "Seasonal Stewardess",
                "role": "Stewardess",
                "location": "Antibes",
                "start_date": "ASAP",
                "description": "Female only role for summer season.",
            }
        return {
            "title": "Stewardess - Immediate Start",
            "role": "Stewardess",
            "location": "Antibes",
            "start_date": "ASAP",
            "description": "Reposted by a different recruiter.",
        }

    monkeypatch.setattr("app.services.ai_job_reviewer.review_post", _fake_review_post)

    first = _run_import_pipeline(
        text="First wording of the listing",
        url="https://jobs.example.com/1",
        source="manual",
    )
    second = _run_import_pipeline(
        text="Second wording of the same listing",
        url="https://jobs.example.com/2",
        source="manual",
    )

    assert first is not None
    assert not isinstance(first, dict)
    assert isinstance(second, dict)
    assert second["duplicate"] is True


def test_save_job_from_ai_fields_dedupes_by_fingerprint(monkeypatch):
    monkeypatch.setattr("app.routes.scraper.SessionLocal", _TestingSession)

    ai_fields = {
        "title": "Deckhand",
        "role": "Deckhand",
        "location": "Palma",
        "start_date": "June 2026",
        "description": "Great deckhand role.",
    }

    first = _save_job_from_ai_fields(ai_fields=ai_fields, url="", source="manual_screenshot")
    second = _save_job_from_ai_fields(ai_fields=ai_fields, url="", source="manual_screenshot")

    assert first is not None
    assert not isinstance(first, dict)
    assert isinstance(second, dict)
    assert second["duplicate"] is True


def test_matching_engine_filters_gender_mismatch_even_if_llm_marks_match(monkeypatch):
    def _fake_call_openai(api_key, model, prompt):
        return json.dumps({
            "matched_jobs": [{
                "job_id": 1,
                "matched": True,
                "compatibility": 92,
                "reason": "Strong fit.",
                "strengths": ["Great role fit"],
                "gaps": [],
                "factor_scores": {"role": 90},
            }]
        })

    monkeypatch.setattr("app.services.matching_engine._call_openai", _fake_call_openai)

    candidate = CandidateProfile(user_key="u1", first_name="Alex", sex="male")
    jobs = [JobSummary(
        job_id=1,
        title="Stewardess",
        role="Stewardess",
        description="Female candidates only.",
    )]

    results = match_candidate_to_jobs(
        api_key="test-key",
        model="test-model",
        candidate=candidate,
        jobs=jobs,
        batch_size=10,
    )

    assert len(results) == 1
    assert results[0].matched is False
    assert results[0].compatibility <= 5
    assert "specifies female candidates" in results[0].reason.lower()


def test_matching_engine_allows_gender_match(monkeypatch):
    def _fake_call_openai(api_key, model, prompt):
        return json.dumps({
            "matched_jobs": [{
                "job_id": 1,
                "matched": True,
                "compatibility": 88,
                "reason": "Strong fit.",
                "strengths": ["Good profile fit"],
                "gaps": [],
                "factor_scores": {"role": 88},
            }]
        })

    monkeypatch.setattr("app.services.matching_engine._call_openai", _fake_call_openai)

    candidate = CandidateProfile(user_key="u2", first_name="Mia", sex="female")
    jobs = [JobSummary(
        job_id=1,
        title="Stewardess",
        role="Stewardess",
        description="Female candidates only.",
    )]

    results = match_candidate_to_jobs(
        api_key="test-key",
        model="test-model",
        candidate=candidate,
        jobs=jobs,
        batch_size=10,
    )

    assert len(results) == 1
    assert results[0].matched is True
    assert results[0].compatibility == 88


def test_matching_engine_openai_call_uses_shared_ai_client(monkeypatch):
    captured = {}

    def _fake_call_openai(**kwargs):
        captured.update(kwargs)
        return '{"matched_jobs": []}'

    monkeypatch.setattr("app.services.matching_engine.call_openai", _fake_call_openai)

    assert _call_openai("test-key", "test-model", "test prompt") == '{"matched_jobs": []}'
    assert captured["api_key"] == "test-key"
    assert captured["model"] == "test-model"
    assert captured["messages"] == [{"role": "user", "content": "test prompt"}]
    assert captured["response_format"] == {"type": "json_object"}
