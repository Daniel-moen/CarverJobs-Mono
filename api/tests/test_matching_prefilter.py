import json
from datetime import datetime, timedelta, timezone

from app.services.matching_engine import (
    CandidateProfile,
    JobSummary,
    MATCH_THRESHOLD,
    PREFILTER_TOP_N,
    _availability_score,
    _build_prompt,
    _deterministic_composite,
    _deterministic_factors,
    _experience_score,
    _salary_score,
    match_candidate_to_jobs,
    prefilter_jobs,
    tier_for,
)


def _job(job_id, role="Deckhand", *, days_old=0, **kwargs):
    kwargs.setdefault("title", role)
    kwargs.setdefault("created_at", datetime.now(timezone.utc) - timedelta(days=days_old))
    return JobSummary(job_id=job_id, role=role, **kwargs)


def _echo_llm(compatibility=60):
    """Fake _call_openai that scores every job in the prompt."""
    calls = []

    def _fake(api_key, model, prompt, *, job_count):
        calls.append(prompt)
        payload = json.loads(prompt[prompt.find("{"):])
        return json.dumps({"matched_jobs": [
            {
                "job_id": j["job_id"], "matched": True,
                "compatibility": compatibility, "reason": "Fit.",
                "strengths": [], "gaps": [], "factor_scores": {"role": 80},
            }
            for j in payload["jobs"]
        ]})

    return _fake, calls


# ── Prefilter ────────────────────────────────────────────────────────────────

def test_prefilter_keeps_top_n_role_related_jobs():
    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = (
        [_job(i, "Deckhand", days_old=i) for i in range(1, 31)]
        + [_job(i, "Chef", days_old=1) for i in range(100, 160)]
    )
    selected, excluded = prefilter_jobs(candidate, jobs, top_n=30)

    assert excluded == []
    assert len(selected) == 30
    # Role relatedness dominates: every deckhand job beats the chef junk.
    assert {j.job_id for j in selected} == set(range(1, 31))


def test_prefilter_always_includes_priority_and_urgent_jobs():
    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = [_job(i, "Deckhand", days_old=i % 20) for i in range(1, 60)]
    jobs.append(_job(900, "Chef", days_old=25, status="priority"))
    jobs.append(_job(901, "Chef", days_old=25, urgent_hire=True))

    selected, _ = prefilter_jobs(candidate, jobs, top_n=20)
    selected_ids = {j.job_id for j in selected}

    assert 900 in selected_ids
    assert 901 in selected_ids
    # Top N by score, plus the two always-included urgent jobs.
    assert len(selected) == 22


def test_prefilter_falls_back_to_recent_when_role_unknown():
    candidate = CandidateProfile(user_key="u1", desired_role="Zookeeper")
    jobs = [_job(i, "Deckhand", days_old=i) for i in range(1, 61)]

    selected, _ = prefilter_jobs(candidate, jobs, top_n=40)

    assert len(selected) == 40
    # Most recent 40 regardless of role relatedness.
    assert {j.job_id for j in selected} == set(range(1, 41))


def test_prefilter_excludes_gender_mismatch_before_llm(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("LLM must not be called for hard-excluded jobs")

    monkeypatch.setattr("app.services.matching_engine._call_openai", _boom)

    candidate = CandidateProfile(user_key="u1", first_name="Alex", sex="male", desired_role="Stewardess")
    jobs = [_job(1, "Stewardess", description="Female candidates only.")]

    results = match_candidate_to_jobs(
        api_key="test-key", model="test-model", candidate=candidate, jobs=jobs,
    )

    assert len(results) == 1
    assert results[0].matched is False
    assert results[0].compatibility <= 5
    assert "specifies female candidates" in results[0].reason.lower()


def test_prefilter_small_boards_pass_through_untouched():
    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = [_job(i, "Chef") for i in range(1, 6)]
    selected, excluded = prefilter_jobs(candidate, jobs)
    assert selected == jobs
    assert excluded == []


def test_match_flow_only_sends_prefiltered_jobs_to_llm(monkeypatch):
    fake, calls = _echo_llm()
    monkeypatch.setattr("app.services.matching_engine._call_openai", fake)

    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = [_job(i, "Deckhand" if i <= 50 else "Chef", days_old=i % 10) for i in range(1, 101)]

    results = match_candidate_to_jobs(
        api_key="test-key", model="test-model", candidate=candidate, jobs=jobs,
        batch_size=200,
    )

    sent_ids = [
        j["job_id"]
        for prompt in calls
        for j in json.loads(prompt[prompt.find("{"):])["jobs"]
    ]
    assert len(sent_ids) == PREFILTER_TOP_N
    assert all(i <= 50 for i in sent_ids)  # cross-department junk cut
    assert len(results) == PREFILTER_TOP_N


# ── Deterministic sub-scores ─────────────────────────────────────────────────

def test_salary_score_edge_cases():
    c = CandidateProfile(user_key="u", salary_min="3000")
    assert _salary_score(c, _job(1, salary_max=4000.0)) == 100.0
    assert _salary_score(c, _job(1, salary_max=1500.0)) == 50.0
    # Missing data on either side skips the factor entirely.
    assert _salary_score(c, _job(1)) is None
    assert _salary_score(CandidateProfile(user_key="u"), _job(1, salary_max=4000.0)) is None
    # salary_min used when salary_max absent.
    assert _salary_score(c, _job(1, salary_min=3000.0)) == 100.0


def test_experience_score_edge_cases():
    c = CandidateProfile(user_key="u", years_experience="5")
    assert _experience_score(c, _job(1, experience_required_years=3)) == 100.0
    assert _experience_score(CandidateProfile(user_key="u", years_experience="2"),
                             _job(1, experience_required_years=4)) == 50.0
    assert _experience_score(c, _job(1, experience_required_years=0)) == 100.0
    assert _experience_score(c, _job(1)) is None
    assert _experience_score(CandidateProfile(user_key="u"), _job(1, experience_required_years=3)) is None


def test_availability_score_edge_cases():
    c = CandidateProfile(user_key="u", available_from="2026-07-01")
    assert _availability_score(c, _job(1, start_date="2026-08-01")) == 100.0
    # 31 days late: 100 - 2/day.
    assert _availability_score(c, _job(1, start_date="2026-05-31")) == 38.0
    assert _availability_score(c, _job(1, start_date="ASAP")) is not None
    assert _availability_score(c, _job(1)) is None
    assert _availability_score(c, _job(1, start_date="whenever suits")) is None
    assert _availability_score(CandidateProfile(user_key="u"), _job(1, start_date="2026-08-01")) is None


def test_deterministic_composite_renormalises_missing_factors():
    c = CandidateProfile(user_key="u", salary_min="3000", location="Antibes")
    job = _job(1, salary_max=4000.0, location="Palma")
    factors = _deterministic_factors(c, job)
    assert set(factors) == {"salary", "location"}
    # (0.3*100 + 0.2*40) / 0.5 = 76
    assert _deterministic_composite(factors) == 76.0
    assert _deterministic_composite({}) is None


# ── Blend, boost, tiers ──────────────────────────────────────────────────────

def _full_data_candidate():
    return CandidateProfile(
        user_key="u1", desired_role="Deckhand", location="Antibes",
        salary_min="3000", years_experience="5", available_from="2026-07-01",
    )


def _full_data_job(job_id=1, **kwargs):
    return _job(
        job_id, "Deckhand", location="Antibes", salary_max=4000.0,
        experience_required_years=3, start_date="2026-08-01", **kwargs,
    )


def test_blend_math_llm_with_deterministic_composite(monkeypatch):
    fake, _ = _echo_llm(compatibility=80)
    monkeypatch.setattr("app.services.matching_engine._call_openai", fake)

    results = match_candidate_to_jobs(
        api_key="k", model="m", candidate=_full_data_candidate(), jobs=[_full_data_job()],
    )

    # All deterministic factors are perfect (composite 100):
    # round(0.65 * 80 + 0.35 * 100) = 87.
    assert results[0].compatibility == 87.0
    assert results[0].matched is True
    assert results[0].tier == "strong"
    assert results[0].factor_scores["det_salary"] == 100.0


def test_blend_skipped_when_no_deterministic_data(monkeypatch):
    fake, _ = _echo_llm(compatibility=88)
    monkeypatch.setattr("app.services.matching_engine._call_openai", fake)

    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    results = match_candidate_to_jobs(
        api_key="k", model="m", candidate=candidate,
        jobs=[JobSummary(job_id=1, title="Deckhand", role="Deckhand")],
    )

    assert results[0].compatibility == 88.0
    assert results[0].tier == "strong"


def test_priority_boost_applied_in_code_not_prompt(monkeypatch):
    fake, calls = _echo_llm(compatibility=60)
    monkeypatch.setattr("app.services.matching_engine._call_openai", fake)

    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = [
        JobSummary(job_id=1, title="Deckhand", role="Deckhand"),
        JobSummary(job_id=2, title="Deckhand", role="Deckhand", status="priority"),
        JobSummary(job_id=3, title="Deckhand", role="Deckhand", urgent_hire=True),
    ]
    results = {r.job_id: r for r in match_candidate_to_jobs(
        api_key="k", model="m", candidate=candidate, jobs=jobs,
    )}

    assert results[1].compatibility == 60.0
    assert results[2].compatibility == 70.0
    assert results[3].compatibility == 70.0
    # The prompt no longer asks the LLM to apply the boost.
    assert "+10" not in calls[0]


def test_priority_boost_clamped_at_100(monkeypatch):
    fake, _ = _echo_llm(compatibility=97)
    monkeypatch.setattr("app.services.matching_engine._call_openai", fake)

    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    results = match_candidate_to_jobs(
        api_key="k", model="m", candidate=candidate,
        jobs=[JobSummary(job_id=1, title="Deckhand", role="Deckhand", status="priority")],
    )
    assert results[0].compatibility == 100.0


def test_tier_assignment():
    assert tier_for(90) == "strong"
    assert tier_for(75) == "strong"
    assert tier_for(74) == "good"
    assert tier_for(50) == "good"
    assert tier_for(49) == "stretch"
    assert tier_for(MATCH_THRESHOLD) == "stretch"
    assert tier_for(29) == ""


def test_prompt_includes_new_job_fields():
    candidate = CandidateProfile(user_key="u1", desired_role="Officer")
    job = JobSummary(
        job_id=1, title="2nd Officer", role="Officer",
        minimum_license="OOW 3000GT", rank_level="Officer",
        requirements="R" * 400, responsibilities="P" * 400, urgent_hire=True,
    )
    prompt = _build_prompt(candidate, [job])
    payload = json.loads(prompt[prompt.find("{"):])
    entry = payload["jobs"][0]
    assert entry["minimum_license"] == "OOW 3000GT"
    assert entry["rank_level"] == "Officer"
    assert entry["urgent_hire"] is True
    assert len(entry["requirements"]) == 300
    assert len(entry["responsibilities"]) == 300


# ── Missing-id retry / fallback ──────────────────────────────────────────────

def test_missing_job_ids_are_retried_once(monkeypatch):
    calls = []

    def _fake(api_key, model, prompt, *, job_count):
        calls.append(prompt)
        payload = json.loads(prompt[prompt.find("{"):])
        ids = [j["job_id"] for j in payload["jobs"]]
        # First call: drop job 2. Retry call: answer whatever was asked.
        if len(calls) == 1:
            ids = [i for i in ids if i != 2]
        return json.dumps({"matched_jobs": [
            {"job_id": i, "matched": True, "compatibility": 55, "reason": "Fit.",
             "strengths": [], "gaps": [], "factor_scores": {}}
            for i in ids
        ]})

    monkeypatch.setattr("app.services.matching_engine._call_openai", _fake)

    candidate = CandidateProfile(user_key="u1", desired_role="Deckhand")
    jobs = [
        JobSummary(job_id=1, title="Deckhand", role="Deckhand"),
        JobSummary(job_id=2, title="Deckhand", role="Deckhand"),
    ]
    results = {r.job_id: r for r in match_candidate_to_jobs(
        api_key="k", model="m", candidate=candidate, jobs=jobs,
    )}

    assert len(calls) == 2  # one batch call + one retry for the missing id
    retry_ids = [j["job_id"] for j in json.loads(calls[1][calls[1].find("{"):])["jobs"]]
    assert retry_ids == [2]
    assert results[2].compatibility == 55.0
    assert "profile fit" not in results[2].reason


def test_still_missing_after_retry_scores_deterministically(monkeypatch):
    calls = []

    def _fake(api_key, model, prompt, *, job_count):
        calls.append(prompt)
        payload = json.loads(prompt[prompt.find("{"):])
        ids = [j["job_id"] for j in payload["jobs"] if j["job_id"] != 2]
        return json.dumps({"matched_jobs": [
            {"job_id": i, "matched": True, "compatibility": 55, "reason": "Fit.",
             "strengths": [], "gaps": [], "factor_scores": {}}
            for i in ids
        ]})

    monkeypatch.setattr("app.services.matching_engine._call_openai", _fake)

    jobs = [_full_data_job(1), _full_data_job(2)]
    results = {r.job_id: r for r in match_candidate_to_jobs(
        api_key="k", model="m", candidate=_full_data_candidate(), jobs=jobs,
    )}

    assert len(calls) == 2
    # No silent drop: job 2 is scored from the deterministic composite alone
    # (all factors perfect -> 100) with an explanatory reason.
    assert 2 in results
    assert "scored on profile fit" in results[2].reason.lower()
    assert results[2].compatibility == 100.0
    assert results[2].matched is True
    assert results[2].tier == "strong"
