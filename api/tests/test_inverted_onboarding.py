"""Inverted onboarding: value before profile.

The 22 Sep transcript review found 15 of 20 stalled users sent exactly one
message and never replied, and that a completed user needed ~5 messages and
~90s before seeing a single job title. These tests pin the fix: a fixed,
pricing-free first message; real jobs on message two; a list that actually
lists; and an honest, refunded zero-result run.
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

from app import models
from app.routes import whatsapp
from app.settings import settings
from tests.conftest import _TestingSession


PHONE = "27820007777"


def _patch_sends(monkeypatch, sent, buttons, events=None):
    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, btns):
        buttons.append((body, btns))

    async def fake_cta(to, **kwargs):
        sent.append(kwargs.get("body", ""))

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(
        whatsapp, "_make_magic_link",
        lambda phone, db, redirect_to=None: "https://x/wa/tok",
    )
    if events is None:
        monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)
    else:
        monkeypatch.setattr(
            whatsapp, "record_server_event",
            lambda user_key, name, value=None: events.append((user_key, name, value)),
        )


def _seed_job(db, title, location, role="Deckhand", age_days=1):
    job = models.Job(
        title=title, role=role, yacht="MY Test", location=location, status="open",
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _session(db, phone=PHONE, history=None, partial=None):
    ws = models.WhatsAppSession(
        phone_number=phone,
        mode="onboarding",
        history=json.dumps(history if history is not None else []),
        partial_profile=json.dumps(partial or {}),
    )
    db.add(ws)
    db.commit()
    db.refresh(ws)
    return ws


# ── 1. The first message is fixed, cheap and free of pricing ──────────────────


def test_first_message_is_deterministic_and_never_mentions_pricing(monkeypatch):
    """No LLM, no tokens, no prices — and the same string every single time."""
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    async def boom(*a, **k):  # the first message must not cost an LLM call
        raise AssertionError("_call_openai must not run for the first message")

    monkeypatch.setattr(whatsapp, "_call_openai", boom)

    db = _TestingSession()
    try:
        ws = _session(db)
        reply = asyncio.run(whatsapp._run_onboarding(ws, "match", db))
    finally:
        db.close()

    assert reply == whatsapp._FIRST_MESSAGE
    low = reply.lower()
    for banned in ("token", "buy", "price", "pricing", "top up", "free run", "r25", "€", "pay"):
        assert banned not in low, banned
    # Asks for one thing: the role.
    assert "role" in low
    assert "deckhand" in low


def test_first_message_is_stable_across_users(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        a = asyncio.run(whatsapp._run_onboarding(_session(db, phone="27820007701"), "hi", db))
        b = asyncio.run(whatsapp._run_onboarding(_session(db, phone="27820007702"), "hello there", db))
    finally:
        db.close()

    assert a == b == whatsapp._FIRST_MESSAGE


# ── 2. The role answer buys real jobs, immediately ────────────────────────────


def test_role_answer_shows_live_job_count_and_three_titles(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed_job(db, "Deckhand — 45m MY", "Antibes", age_days=1)
        _seed_job(db, "Deckhand — 60m MY", "Palma", age_days=2)
        _seed_job(db, "Deckhand — 38m SY", "Nice", age_days=3)
        _seed_job(db, "Chef — 50m MY", "Monaco", role="Chef", age_days=1)
        # Outside WA_MATCH_RECENT_DAYS — must not be counted as "this week".
        _seed_job(db, "Deckhand — stale", "Genoa", age_days=90)

        ws = _session(db, history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": whatsapp._FIRST_MESSAGE},
        ])
        reply = asyncio.run(whatsapp._run_onboarding(ws, "Deckhand", db))
    finally:
        db.close()

    # The preview was sent directly (with buttons), so no string is returned.
    assert reply is None
    assert len(sent) == 1
    preview = sent[0]
    assert "3" in preview                      # the honest recent count
    assert "Deckhand" in preview
    assert "Antibes" in preview and "Palma" in preview and "Nice" in preview
    assert "Genoa" not in preview              # stale job excluded
    assert "!" not in preview                  # no hype

    # Two buttons, both wired into the command map.
    assert len(buttons) == 1
    ids = [bid for bid, _t in buttons[0][1]]
    assert ids == ["btn_onb_rank", "btn_onb_list"]
    for bid in ids:
        assert bid in whatsapp._INTERACTIVE_CMD_MAP

    assert (PHONE, "onboard_role_jobs_shown", "3") in events
    # The role is captured as a profile field, with its funnel event.
    assert (PHONE, "onboard_field_filled", "desiredRole") in events


def test_role_answer_with_empty_week_falls_back_to_the_month(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        _seed_job(db, "Stewardess — 45m MY", "Antibes", role="Stewardess", age_days=20)

        ws = _session(db, history=[{"role": "user", "content": "hi"},
                                   {"role": "assistant", "content": whatsapp._FIRST_MESSAGE}])
        asyncio.run(whatsapp._run_onboarding(ws, "Stewardess", db))
    finally:
        db.close()

    assert len(sent) == 1
    assert "last month" in sent[0].lower()
    assert "Antibes" in sent[0]
    assert (PHONE, "onboard_role_jobs_shown", "1") in events


def test_role_answer_with_no_jobs_is_honest_and_keeps_onboarding(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        ws = _session(db, history=[{"role": "user", "content": "hi"},
                                   {"role": "assistant", "content": whatsapp._FIRST_MESSAGE}])
        reply = asyncio.run(whatsapp._run_onboarding(ws, "Bosun", db))
    finally:
        db.close()

    assert reply is not None
    assert "I'll ping you the moment one lands" in reply
    # …and the next profile question rides along, so onboarding continues.
    assert whatsapp._ONBOARD_QUESTIONS["firstName"] in reply
    assert buttons == []
    assert (PHONE, "onboard_role_jobs_shown", "0") in events


def test_role_extraction_rejects_a_sentence_and_re_asks(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws = _session(db, history=[{"role": "user", "content": "hi"},
                                   {"role": "assistant", "content": whatsapp._FIRST_MESSAGE}])
        reply = asyncio.run(whatsapp._run_onboarding(ws, "🤷", db))
    finally:
        db.close()

    assert whatsapp._ONBOARD_QUESTIONS["desiredRole"] in reply


def test_extract_role_strips_common_lead_ins():
    assert whatsapp._extract_role("deckhand") == "Deckhand"
    assert whatsapp._extract_role("I'm a Chief Stew") == "Chief Stew"
    assert whatsapp._extract_role("a chef") == "Chef"
    assert whatsapp._extract_role("") == ""
    assert whatsapp._extract_role("well it depends, I have done a bit of everything really") == ""


# ── 3. "Just show me the list" actually shows a list ──────────────────────────


def test_just_show_the_list_sends_a_real_list_then_re_offers_questions(monkeypatch):
    sent, buttons, events = [], [], []
    _patch_sends(monkeypatch, sent, buttons, events)

    db = _TestingSession()
    try:
        for i in range(4):
            _seed_job(db, f"Deckhand — vessel {i}", f"Port {i}", age_days=i + 1)

        ws = _session(
            db,
            history=[{"role": "user", "content": "Deckhand"},
                     {"role": "assistant", "content": "preview"}],
            partial={"desiredRole": "Deckhand"},
        )
        reply = asyncio.run(whatsapp._run_onboarding(
            ws, whatsapp._INTERACTIVE_CMD_MAP["btn_onb_list"], db,
        ))
    finally:
        db.close()

    assert len(sent) == 1
    listing = sent[0]
    for i in range(4):
        assert f"vessel {i}" in listing
        assert f"Port {i}" in listing
    assert "1." in listing and "4." in listing
    assert "ago" in listing or "today" in listing or "yesterday" in listing

    # The profile questions are re-offered rather than abandoned.
    assert reply is not None
    assert whatsapp._ONBOARD_QUESTIONS["firstName"] in reply
    assert (PHONE, "onboard_list_tapped", "Deckhand") in events


def test_list_is_capped_at_ten_with_an_honest_remainder(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        for i in range(13):
            _seed_job(db, f"Deckhand — v{i}", "Antibes", age_days=1)
        asyncio.run(whatsapp._send_role_job_list(PHONE, db, "Deckhand"))
    finally:
        db.close()

    listing = sent[0]
    assert "13 live Deckhand jobs" in listing
    assert "10." in listing and "11." not in listing
    assert "and 3 more" in listing


def test_rank_them_for_me_goes_straight_to_the_next_question(monkeypatch):
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    db = _TestingSession()
    try:
        ws = _session(
            db,
            history=[{"role": "user", "content": "Deckhand"},
                     {"role": "assistant", "content": "preview"}],
            partial={"desiredRole": "Deckhand"},
        )
        reply = asyncio.run(whatsapp._run_onboarding(
            ws, whatsapp._INTERACTIVE_CMD_MAP["btn_onb_rank"], db,
        ))
    finally:
        db.close()

    assert sent == []  # no list, straight on with onboarding
    assert whatsapp._ONBOARD_QUESTIONS["firstName"] in reply


# ── 4. Deterministic question sequence ────────────────────────────────────────


def test_question_order_is_role_then_the_three_required_fields():
    assert whatsapp._ONBOARD_QUESTION_ORDER[0] == "desiredRole"
    assert sorted(whatsapp._ONBOARD_QUESTION_ORDER) == sorted(whatsapp.REQUIRED_ONBOARD_FIELDS)
    assert whatsapp._missing_onboard_fields({}) == whatsapp._ONBOARD_QUESTION_ORDER
    assert whatsapp._missing_onboard_fields({"desiredRole": "Chef"}) == [
        "firstName", "currentLocation", "yearsExperience",
    ]


def test_field_sequence_is_code_not_the_llms_choice(monkeypatch):
    """Even when the LLM returns its own chatty message, the question asked is
    the deterministic next one."""
    sent, buttons = [], []
    _patch_sends(monkeypatch, sent, buttons)

    async def chatty(system, history, user_message, *, model=None):
        return {
            "message": "Ahoy! Tell me all about your certifications! 🏅",
            "done": False,
            "updates": {"firstName": "Sam"},
        }

    monkeypatch.setattr(whatsapp, "_call_openai", chatty)

    db = _TestingSession()
    try:
        ws = _session(
            db,
            history=[{"role": "user", "content": "Deckhand"},
                     {"role": "assistant", "content": "preview"}],
            partial={"desiredRole": "Deckhand"},
        )
        reply = asyncio.run(whatsapp._run_onboarding(ws, "Sam", db))
    finally:
        db.close()

    assert whatsapp._ONBOARD_QUESTIONS["currentLocation"] in reply
    assert "certifications" not in reply.lower()


# ── 5. Commands still work from onboarding mode ───────────────────────────────


def test_allowed_commands_cover_jobs_match_hey_help_stop():
    allowed = whatsapp._ONBOARDING_ALLOWED_CMDS | whatsapp._GLOBAL_CMDS
    for cmd in ("jobs", "match", "hey", "help"):
        assert cmd in allowed, cmd
    # STOP is handled ahead of routing entirely, in any mode.
    assert "stop" in whatsapp._OPT_OUT_KEYWORDS


def test_first_message_is_not_swallowed_by_the_website_match_prefill():
    """The wa.me CTAs prefill "match · <tag>", so a brand-new user's first
    message is literally "match" — it must reach onboarding, not the router."""
    assert "match" in whatsapp._ONBOARDING_ALLOWED_CMDS
    assert "match" not in whatsapp._GLOBAL_CMDS  # gated on a non-empty history


def _patch_inbound(monkeypatch, sent):
    async def fake_send(to, text):
        sent.append(text)

    async def _noop():
        return None

    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_typing_indicator", lambda *a, **k: _noop())
    monkeypatch.setattr(whatsapp, "_record_whatsapp_message", lambda *a, **k: None)
    monkeypatch.setattr(whatsapp, "feedback_is_eligible", lambda *a, **k: (False, None))
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)


def test_website_match_prefill_still_gets_the_greeting_end_to_end(monkeypatch):
    sent = []
    _patch_inbound(monkeypatch, sent)

    phone = "27820007710"
    asyncio.run(whatsapp._process_whatsapp_message(phone, "match · m-hero"))

    assert sent == [whatsapp._FIRST_MESSAGE]


def test_jobs_command_works_mid_onboarding_without_losing_the_profile(monkeypatch):
    sent = []
    _patch_inbound(monkeypatch, sent)
    ctas = []

    async def fake_cta(to, **kwargs):
        ctas.append(kwargs)

    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/tok")

    phone = "27820007711"
    db = _TestingSession()
    try:
        _session(db, phone=phone,
                 history=[{"role": "user", "content": "hi"},
                          {"role": "assistant", "content": whatsapp._FIRST_MESSAGE}],
                 partial={"desiredRole": "Deckhand"})
    finally:
        db.close()

    asyncio.run(whatsapp._process_whatsapp_message(phone, "jobs"))

    assert len(ctas) == 1
    assert "Browse jobs" == ctas[0]["button_text"]

    db = _TestingSession()
    try:
        row = db.query(models.WhatsAppSession).filter_by(phone_number=phone).first()
        # Still mid-onboarding, role intact — the next message resumes it.
        assert row.mode == "onboarding"
        assert json.loads(row.partial_profile)["desiredRole"] == "Deckhand"
    finally:
        db.close()
