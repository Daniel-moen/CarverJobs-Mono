"""Freshness defaults, JobSummary parity, and honest result framing.

Three findings from the 22 Sep review are pinned here:
  * the auto first run said "Found 35 matches!" topped by irrelevant jobs;
  * WhatsApp built a thinner JobSummary than the web path, so recency scoring
    was dead on the channel where most users actually are;
  * a run that returned nothing still charged a token.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.services.matching_engine import MatchResult, MatchRunResults
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820008888"


def _patch_sends(monkeypatch, sent, buttons, events=None):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, btns):
        buttons.append((body, btns))

    async def fake_cta(to, **kwargs):
        sent.append(kwargs.get("body", ""))

    async def fake_pulse(phone, session_id):
        return None

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_send_match_quality_pulse", fake_pulse)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(
        whatsapp, "_make_magic_link",
        lambda phone, db, redirect_to=None: "https://x/wa/tok",
    )
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(whatsapp, "spend_credits", lambda db, key, amount=1: 4)
    if events is None:
        monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)
    else:
        monkeypatch.setattr(
            whatsapp, "record_server_event",
            lambda user_key, name, value=None: events.append((user_key, name, value)),
        )


def _seed_job(db, title, location="Antibes", role="Deckhand", age_days=1, **extra):
    job = models.Job(
        title=title, role=role, yacht="MY Test", location=location, status="open",
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        **extra,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _capture_engine(monkeypatch, results):
    """Stub the engine and record exactly what whatsapp.py handed it."""
    captured = {}

    def fake_match(**kwargs):
        captured["jobs"] = kwargs["jobs"]
        captured["candidate"] = kwargs["candidate"]
        return results

    monkeypatch.setattr("app.services.matching_engine.match_candidate_to_jobs", fake_match)
    return captured


def _profile(db):
    db.add(models.CrewProfile(user_key=PHONE, profile_slug="slugfresh", desired_role="Deckhand"))
    db.commit()


# ── Freshness defaults ────────────────────────────────────────────────────────


def test_recent_scope_widens_to_all_open_jobs_when_the_week_is_thin(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    captured = _capture_engine(monkeypatch, MatchRunResults())

    db = _TestingSession()
    try:
        _profile(db)
        _seed_job(db, "Deckhand — fresh", age_days=1)
        for i in range(4):
            _seed_job(db, f"Deckhand — older {i}", age_days=20 + i)

        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_RECENT))
    finally:
        db.close()

    scanning = sent[0]
    assert "Only 1 this week, so I widened to the last month." in scanning
    assert "all open jobs" in scanning
    # All five jobs actually reached the engine, not just the fresh one.
    assert len(captured["jobs"]) == 5


def test_recent_scope_stays_narrow_when_the_week_is_healthy(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    captured = _capture_engine(monkeypatch, MatchRunResults())

    db = _TestingSession()
    try:
        _profile(db)
        for i in range(3):
            _seed_job(db, f"Deckhand — fresh {i}", age_days=1)
        _seed_job(db, "Deckhand — ancient", age_days=25)

        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_RECENT))
    finally:
        db.close()

    assert "widened" not in sent[0]
    assert len(captured["jobs"]) == 3


def test_automatic_first_run_uses_the_recent_scope(monkeypatch):
    """Onboarding completion kicks the free run at the fresh window, not the
    whole database."""
    scopes = []

    async def fake_bg(phone, graph_id="", scope=whatsapp._MATCH_SCOPE_ALL):
        scopes.append(scope)

    async def fake_send(to, text):
        return None

    async def fake_cta(to, **kwargs):
        return None

    async def fake_enrich(phone, db=None):
        return None

    monkeypatch.setattr(whatsapp, "_run_match_command_background", fake_bg)
    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_send_post_match_enrichment", fake_enrich)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x")
    monkeypatch.setattr(whatsapp, "get_credit_balance", lambda db, key: 1)

    db = _TestingSession()
    try:
        ws = models.WhatsAppSession(
            phone_number=PHONE, mode="onboarding",
            history=json.dumps([{"role": "user", "content": "x"}]),
            partial_profile=json.dumps({
                "desiredRole": "Deckhand", "firstName": "Sam",
                "currentLocation": "Palma", "yearsExperience": "3",
            }),
        )
        db.add(ws)
        db.commit()

        async def _drive():
            await whatsapp._finish_onboarding(ws, db, [], json.loads(ws.partial_profile), "done")
            await asyncio.sleep(0)
            pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in pending:
                await asyncio.wait_for(task, timeout=10)

        asyncio.run(_drive())
    finally:
        db.close()

    assert scopes == [whatsapp._MATCH_SCOPE_RECENT]


# ── JobSummary parity with the web path ───────────────────────────────────────


def test_whatsapp_job_summary_matches_the_web_path(monkeypatch):
    """created_at / requirements / urgent_hire were missing, which silently
    killed recency scoring on WhatsApp."""
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    captured = _capture_engine(monkeypatch, MatchRunResults())

    db = _TestingSession()
    try:
        _profile(db)
        job = _seed_job(
            db, "Deckhand — 45m MY", age_days=2,
            requirements="STCW, ENG1", responsibilities="Deck watch",
            urgent_hire=True, minimum_license="Yachtmaster", rank_level="junior",
        )
        job_id = job.id

        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_ALL))

        from app.routes.crew_match import _job_to_summary
        expected = _job_to_summary(db.query(models.Job).filter(models.Job.id == job_id).first())
    finally:
        db.close()

    summary = captured["jobs"][0]
    assert summary == expected
    assert summary.created_at is not None
    assert summary.requirements == "STCW, ENG1"
    assert summary.urgent_hire is True


# ── Honest result framing ─────────────────────────────────────────────────────


def _results_with_tiers(job_ids):
    return MatchRunResults([
        MatchResult(job_id=job_ids[0], matched=True, compatibility=88.0, tier="strong", reason="Strong deck fit."),
        MatchResult(job_id=job_ids[1], matched=True, compatibility=61.0, tier="good", reason="Decent fit."),
        MatchResult(job_id=job_ids[2], matched=False, compatibility=35.0, tier="stretch", reason="Thin."),
    ])


def test_summary_leads_with_tier_counts_and_never_hypes(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        _profile(db)
        ids = [_seed_job(db, f"Deckhand {i}", location=f"Port {i}").id for i in range(3)]
        _capture_engine(monkeypatch, _results_with_tiers(ids))
        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_ALL))
    finally:
        db.close()

    summary = sent[1]
    assert summary.startswith("🎯 *1 strong · 1 good fits*")
    assert "Found" not in summary
    assert "!" not in summary
    # Per-result tier word in the top-3 list.
    assert "strong" in summary and "good" in summary


def test_summary_degrades_to_a_plain_count_without_tier_metadata(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        _profile(db)
        ids = [_seed_job(db, f"Deckhand {i}").id for i in range(2)]
        plain = [
            MatchResult(job_id=ids[0], matched=True, compatibility=80.0),
            MatchResult(job_id=ids[1], matched=True, compatibility=70.0),
        ]
        _capture_engine(monkeypatch, plain)  # a bare list: no tier_counts
        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_ALL))
    finally:
        db.close()

    summary = sent[1]
    assert summary.startswith("🎯 *2 jobs ranked* — top 3:")
    assert "Found" not in summary
    assert "!" not in summary


def test_summary_header_helper_handles_missing_attributes():
    assert whatsapp._match_summary_header([], 0).startswith("🎯 *0 jobs ranked*")
    assert whatsapp._match_summary_header(object(), 5).startswith("🎯 *5 jobs ranked*")
    graded = MatchRunResults([MatchResult(job_id=1, matched=True, compatibility=90.0, tier="strong")])
    assert whatsapp._match_summary_header(graded, 1).startswith("🎯 *1 strong fit*")


def test_tier_label_derives_the_word_from_the_score():
    assert whatsapp._tier_label("strong") == "strong"
    assert whatsapp._tier_label("", 88.0) == "strong"
    assert whatsapp._tier_label("", 60.0) == "good"
    assert whatsapp._tier_label("", 35.0) == "a stretch"
    assert whatsapp._tier_label("", 10.0) == ""


# ── Zero results are refunded ─────────────────────────────────────────────────


def test_zero_result_run_refunds_the_token_and_says_so(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)
    _capture_engine(monkeypatch, MatchRunResults())

    refunds = []

    def fake_add_credits(db, key, amount=1):
        refunds.append((key, amount))
        return 5

    monkeypatch.setattr(whatsapp, "add_credits", fake_add_credits)

    db = _TestingSession()
    try:
        _profile(db)
        _seed_job(db, "Chef — 50m MY", role="Chef")
        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_ALL))
    finally:
        db.close()

    assert refunds == [(PHONE, 1)]
    refund_msg = sent[1]
    assert "put your token back" in refund_msg
    assert "*5*" in refund_msg
    assert "!" not in refund_msg
    assert (PHONE, "match_zero_refund", "1") in events


def test_engine_error_still_refunds(monkeypatch):
    """The pre-existing refund path must survive the rewrite."""
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    def boom(**kwargs):
        raise RuntimeError("engine down")

    monkeypatch.setattr("app.services.matching_engine.match_candidate_to_jobs", boom)

    refunds = []
    monkeypatch.setattr(
        whatsapp, "add_credits",
        lambda db, key, amount=1: refunds.append((key, amount)) or 5,
    )

    db = _TestingSession()
    try:
        _profile(db)
        _seed_job(db, "Deckhand — 45m MY")
        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_ALL))
    finally:
        db.close()

    assert refunds == [(PHONE, 1)]
    assert any("refunded" in b[0] for b in buttons)


def test_empty_board_never_charges(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    spends = []
    monkeypatch.setattr(
        whatsapp, "spend_credits",
        lambda db, key, amount=1: spends.append(key) or 4,
    )

    db = _TestingSession()
    try:
        _profile(db)
        asyncio.run(whatsapp._handle_match_command(PHONE, db, match_scope=whatsapp._MATCH_SCOPE_RECENT))
    finally:
        db.close()

    assert spends == []
    assert "I'll ping you the moment fresh ones land" in sent[0]


# ── Tier word on the in-chat detail card ──────────────────────────────────────


def test_detail_card_shows_the_tier_word(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        job = _seed_job(db, "Deckhand — 45m MY")
        ms = models.MatchSession(
            user_key=PHONE, status="completed", total_jobs_scanned=1, total_matched=1,
            completed_at=datetime.now(timezone.utc),
        )
        db.add(ms)
        db.flush()
        db.add(models.MatchSessionResult(
            session_id=ms.id, job_id=job.id, matched=True, compatibility=88.0,
            reason="Strong deck background.", strengths=json.dumps([]),
            gaps=json.dumps([]), factor_scores=json.dumps({}),
        ))
        ws = models.WhatsAppSession(phone_number=PHONE, mode="chat", last_match_session_id=ms.id)
        db.add(ws)
        db.commit()

        asyncio.run(whatsapp._send_match_detail(PHONE, db, ws, 1))
    finally:
        db.close()

    assert "*Match: 88% · strong fit*" in sent[0]
