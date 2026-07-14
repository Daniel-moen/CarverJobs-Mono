"""Engagement layer: save/dismiss on matches, dismissal-aware match runs, the
*saved* list, factor-score match drivers, the non-blocking feedback invite,
and last_active_at stamping."""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820003333"


def _patch_sends(monkeypatch, sent, buttons):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, btns):
        buttons.append((body, btns))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)
    monkeypatch.setattr(
        whatsapp, "_make_magic_link",
        lambda phone, db, redirect_to=None: "https://x/wa/tok",
    )


def _seed_job(db, title, location, role="Deckhand"):
    job = models.Job(title=title, role=role, yacht="MY Test", location=location, status="open")
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _seed_match_run(db, phone=PHONE, jobs=None, factor_scores=None):
    """A completed match run + chat session so digit/save/dismiss replies work."""
    jobs = jobs or [
        _seed_job(db, "Deckhand — 45m MY", "Antibes"),
        _seed_job(db, "Deckhand — 60m MY", "Palma"),
    ]
    ms = models.MatchSession(
        user_key=phone, status="completed",
        total_jobs_scanned=len(jobs), total_matched=len(jobs),
    )
    db.add(ms)
    db.flush()
    for i, job in enumerate(jobs):
        db.add(models.MatchSessionResult(
            session_id=ms.id, job_id=job.id, matched=True,
            compatibility=90 - i, reason="Strong deck background.",
            strengths=json.dumps(["deck experience"]), gaps=json.dumps([]),
            factor_scores=json.dumps(factor_scores or {}),
        ))
    ws = models.WhatsAppSession(phone_number=phone, mode="chat", last_match_session_id=ms.id)
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws, jobs


# ── Save / dismiss handlers ────────────────────────────────────────────────────


def test_save_records_row_and_confirms(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws, jobs = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "save 1", db))

        row = (
            db.query(models.MatchInteraction)
            .filter_by(user_key=PHONE, job_id=jobs[0].id, action="saved")
            .first()
        )
        assert row is not None
        assert "Saved" in sent[-1] and "*saved*" in sent[-1]

        # Double-tap stays idempotent — still exactly one row.
        asyncio.run(whatsapp._run_chat(ws, "save 1", db))
        assert (
            db.query(models.MatchInteraction)
            .filter_by(user_key=PHONE, action="saved")
            .count()
        ) == 1
    finally:
        db.close()


def test_dismiss_records_row_and_shows_next_match(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws, jobs = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "dismiss 1", db))

        row = (
            db.query(models.MatchInteraction)
            .filter_by(user_key=PHONE, job_id=jobs[0].id, action="dismissed")
            .first()
        )
        assert row is not None
        joined = "\n".join(sent)
        assert "Noted" in joined
        # Rolls straight into the next match's detail…
        assert jobs[1].title in joined
        # …with its own save/dismiss/draft buttons row.
        flat_ids = [bid for _body, btns in buttons for bid, _title in btns]
        assert "btn_save_2" in flat_ids and "btn_dismiss_2" in flat_ids and "btn_draft_2" in flat_ids

        # Dismissing the last match ends the run instead of drilling further.
        sent.clear()
        asyncio.run(whatsapp._run_chat(ws, "dismiss 2", db))
        assert "last match" in sent[-1]
    finally:
        db.close()


def test_match_detail_offers_save_dismiss_draft_buttons(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws, jobs = _seed_match_run(db)
        asyncio.run(whatsapp._run_chat(ws, "1", db))
    finally:
        db.close()

    assert jobs[0].title in sent[-1]
    _body, btns = buttons[-1]
    assert [bid for bid, _t in btns] == ["btn_save_1", "btn_dismiss_1", "btn_draft_1"]
    # Buttons route through the interactive command map to the new handlers.
    assert whatsapp._INTERACTIVE_CMD_MAP["btn_save_1"] == "save 1"
    assert whatsapp._INTERACTIVE_CMD_MAP["btn_dismiss_1"] == "dismiss 1"
    assert whatsapp._INTERACTIVE_CMD_MAP["btn_draft_1"] == "draft 1"
    assert whatsapp._INTERACTIVE_CMD_MAP["cmd_saved"] == "saved"


# ── Dismissals shape future runs ───────────────────────────────────────────────


def test_dismissed_jobs_excluded_from_match_job_query(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    monkeypatch.setattr(settings, "OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(whatsapp, "spend_credits", lambda db, key, amount=1: 4)

    captured = {}

    def fake_match(**kwargs):
        captured["job_ids"] = [j.job_id for j in kwargs["jobs"]]
        return []

    monkeypatch.setattr("app.services.matching_engine.match_candidate_to_jobs", fake_match)

    db = _TestingSession()
    try:
        db.add(models.CrewProfile(user_key=PHONE, profile_slug="slugeng1", desired_role="Deckhand"))
        dismissed = _seed_job(db, "Deckhand — dismissed", "Palma")
        kept = _seed_job(db, "Deckhand — kept", "Antibes")
        db.add(models.MatchInteraction(user_key=PHONE, job_id=dismissed.id, action="dismissed"))
        db.commit()

        asyncio.run(whatsapp._handle_match_command(PHONE, db))
    finally:
        db.close()

    assert captured["job_ids"] == [kept.id]


def test_paywall_teaser_excludes_dismissed_jobs(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)
    monkeypatch.setattr(whatsapp, "get_credit_balance", lambda db, key: 0)

    db = _TestingSession()
    try:
        profile = models.CrewProfile(user_key=PHONE, profile_slug="slugeng2", desired_role="Deckhand")
        db.add(profile)
        dismissed = _seed_job(db, "Deckhand — dismissed", "Palma")
        kept = _seed_job(db, "Deckhand — kept", "Antibes")
        db.add(models.MatchInteraction(user_key=PHONE, job_id=dismissed.id, action="dismissed"))
        db.commit()

        asyncio.run(whatsapp._send_paywall_teaser(PHONE, db, profile, [dismissed, kept]))
    finally:
        db.close()

    body = sent[-1]
    assert "1 open position" in body
    assert "Antibes" in body and "Palma" not in body


# ── Saved list ────────────────────────────────────────────────────────────────


def test_saved_command_lists_jobs_and_digit_drills_down(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws = models.WhatsAppSession(phone_number=PHONE, mode="chat")
        db.add(ws)
        first = _seed_job(db, "Deckhand — 45m MY", "Antibes")
        second = _seed_job(db, "Bosun — 70m MY", "Palma", role="Bosun")
        db.add(models.MatchInteraction(user_key=PHONE, job_id=first.id, action="saved"))
        db.add(models.MatchInteraction(user_key=PHONE, job_id=second.id, action="saved"))
        db.commit()

        asyncio.run(whatsapp._run_chat(ws, "saved", db))
        body = sent[-1]
        assert "My Jobs" in body
        # Newest saved first: "N. *title* — location", with the reply-N hint.
        assert f"1. *{second.title}* — {second.location}" in body
        assert f"2. *{first.title}* — {first.location}" in body
        assert "Reply *1*–*2*" in body

        # Bare digit now drills into the saved list, rendered from the Job row.
        asyncio.run(whatsapp._run_chat(ws, "2", db))
        assert first.title in sent[-1]
        assert first.location in sent[-1]
    finally:
        db.close()


def test_saved_command_with_nothing_saved(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws = models.WhatsAppSession(phone_number=PHONE, mode="chat")
        db.add(ws)
        db.commit()
        asyncio.run(whatsapp._run_chat(ws, "saved", db))
    finally:
        db.close()

    assert "Nothing saved yet" in sent[-1]


def test_fresh_match_run_points_digits_back_at_results(monkeypatch):
    """A new run must clear the saved-list digit context."""
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws, jobs = _seed_match_run(db)
        db.add(models.MatchInteraction(user_key=PHONE, job_id=jobs[0].id, action="saved"))
        db.commit()

        asyncio.run(whatsapp._run_chat(ws, "saved", db))
        assert whatsapp._saved_list_context(ws) == [jobs[0].id]

        whatsapp._clear_saved_list_context(ws)
        db.commit()
        assert whatsapp._saved_list_context(ws) == []

        # Digits target the last match run again.
        asyncio.run(whatsapp._run_chat(ws, "2", db))
        assert jobs[1].title in sent[-1]
    finally:
        db.close()


# ── Match drivers (factor scores) ─────────────────────────────────────────────


def test_match_detail_shows_top_three_factor_drivers(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws, jobs = _seed_match_run(db, factor_scores={
            "role": 92, "experience": 80, "location": 65,
            "pay": 10, "det_role": 99,
        })
        asyncio.run(whatsapp._run_chat(ws, "1", db))
    finally:
        db.close()

    detail = sent[-1]
    assert "📊 *Match drivers:* Role 92 · Experience 80 · Location 65" in detail
    assert "det_" not in detail and "Pay" not in detail


def test_match_drivers_line_handles_missing_scores():
    assert whatsapp._match_drivers_line(None) == ""
    assert whatsapp._match_drivers_line("") == ""
    assert whatsapp._match_drivers_line("not json") == ""
    assert whatsapp._match_drivers_line(json.dumps({"det_role": 99})) == ""


# ── Feedback gate + last_active_at ────────────────────────────────────────────


def _patch_inbound(monkeypatch, calls):
    """Wire _process_whatsapp_message to the test DB with observable sends."""
    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)

    async def fake_send(to, text):
        calls.append(("send", text))

    async def fake_buttons(to, body, btns):
        calls.append(("buttons", body))

    async def fake_invite(phone, db):
        calls.append(("feedback_invite", phone))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_send_feedback_request", fake_invite)


def test_feedback_gate_no_longer_drops_the_command(monkeypatch):
    calls = []
    _patch_inbound(monkeypatch, calls)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (True, None))

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "balance"))

    labels = [c[0] for c in calls]
    # The command ran and answered…
    assert "send" in labels
    balance_reply = next(text for label, text in calls if label == "send")
    assert "balance" in balance_reply.lower()
    # …and the invite came AFTER the command's response, not instead of it.
    assert "feedback_invite" in labels
    assert labels.index("feedback_invite") > labels.index("send")

    db = _TestingSession()
    try:
        ws = db.query(models.WhatsAppSession).filter_by(phone_number=PHONE).first()
        assert ws.feedback_prompted_at is not None
    finally:
        db.close()


def test_feedback_invite_respects_cooldown_stamp(monkeypatch):
    calls = []
    _patch_inbound(monkeypatch, calls)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (True, None))

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(
            phone_number=PHONE, mode="chat",
            feedback_prompted_at=datetime.now(timezone.utc) - timedelta(days=2),
        ))
        db.commit()
    finally:
        db.close()

    # Prompted 2 days ago — inside the cooldown window, no re-invite.
    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "balance"))
    assert "feedback_invite" not in [c[0] for c in calls]

    # Age the stamp past the cooldown — the invite fires again.
    db = _TestingSession()
    try:
        ws = db.query(models.WhatsAppSession).filter_by(phone_number=PHONE).first()
        ws.feedback_prompted_at = (
            datetime.now(timezone.utc)
            - timedelta(days=whatsapp._FEEDBACK_PROMPT_COOLDOWN_DAYS + 1)
        )
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "balance"))
    assert "feedback_invite" in [c[0] for c in calls]


def test_no_feedback_invite_when_already_submitted(monkeypatch):
    calls = []
    _patch_inbound(monkeypatch, calls)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (True, None))
    monkeypatch.setattr(whatsapp, "_feedback_already_submitted", lambda db, key: True)

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "balance"))
    labels = [c[0] for c in calls]
    assert "send" in labels and "feedback_invite" not in labels


def test_last_active_at_stamped_on_every_inbound(monkeypatch):
    calls = []
    _patch_inbound(monkeypatch, calls)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (False, None))

    db = _TestingSession()
    try:
        db.add(models.WhatsAppSession(phone_number=PHONE, mode="chat"))
        db.commit()
    finally:
        db.close()

    before = datetime.now(timezone.utc)
    asyncio.run(whatsapp._process_whatsapp_message(PHONE, "balance"))

    db = _TestingSession()
    try:
        ws = db.query(models.WhatsAppSession).filter_by(phone_number=PHONE).first()
        stamped = ws.last_active_at
        assert stamped is not None
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=timezone.utc)
        assert stamped >= before - timedelta(seconds=5)
    finally:
        db.close()
