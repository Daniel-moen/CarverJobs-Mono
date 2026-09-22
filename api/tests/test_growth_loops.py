"""Growth-loop and durability tests for the WhatsApp bot.

Covers the changes that gave the product its first referral loop plus the
durability gaps that let a deploy charge a user twice or strand them:

* referral: both sides paid exactly once, self-referral refused
* CREW_MATCH_FREE: a match run spends nothing and never paywalls
* webhook dedup survives a process restart (fresh in-memory set)
* the promised free first match survives a restart
* the public crew-profile link is reachable from chat
* win-back copy never promises a free run the paywall would refuse
"""
import asyncio

import pytest

from app.models import CreditAccount, CrewProfile, Job, WhatsAppSeenMessage, WhatsAppSession
from app.routes import whatsapp
from app.services import credits as credits_service
from app.services import window_winback

from .conftest import _TestingSession


@pytest.fixture(autouse=True)
def _quiet_analytics(monkeypatch):
    """Keep funnel events out of the developer's real DB during tests."""
    monkeypatch.setattr(whatsapp, "record_server_event", lambda *a, **k: None)
    monkeypatch.setattr(window_winback, "record_server_event", lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _match_not_free(monkeypatch):
    """Default the flag off so each test states its own expectation."""
    monkeypatch.delenv("CREW_MATCH_FREE", raising=False)


def _session(db, phone, **kwargs):
    ws = WhatsAppSession(phone_number=phone, **kwargs)
    db.add(ws)
    db.commit()
    return ws


def _balance(db, phone):
    db.expire_all()
    return credits_service.get_credit_balance(db, phone)


# ── Referral loop ────────────────────────────────────────────────────────────

def test_referral_code_is_stable_and_scoped():
    code = whatsapp._referral_code("27820000001")
    assert code == whatsapp._referral_code("27820000001")
    assert code.startswith("REF-") and len(code) == 10
    assert code != whatsapp._referral_code("27820000002")
    assert "27820000001" not in whatsapp._referral_link("27820000001")


def test_referral_tag_on_first_contact_links_the_two_sessions():
    db = _TestingSession()
    referrer = "27820000010"
    invitee = "27820000011"
    _session(db, referrer)
    ws = _session(db, invitee)

    text = whatsapp._record_first_contact(
        invitee, ws, f"Hi Carver · {whatsapp._referral_code(referrer)}", db
    )

    assert text == "Hi Carver"
    assert ws.acquisition_source == whatsapp._referral_code(referrer)
    assert ws.referred_by == referrer
    db.close()


def test_non_ref_tag_is_attribution_only():
    db = _TestingSession()
    ws = _session(db, "27820000012")
    whatsapp._record_first_contact("27820000012", ws, "match · SCHOOL-bluewater", db)
    assert ws.acquisition_source == "SCHOOL-bluewater"
    assert ws.referred_by is None
    db.close()


def test_self_referral_is_not_recorded():
    db = _TestingSession()
    phone = "27820000013"
    ws = _session(db, phone)
    whatsapp._record_first_contact(phone, ws, f"Hi Carver · {whatsapp._referral_code(phone)}", db)
    assert ws.referred_by is None

    # …and even a hand-written row can't pay itself.
    ws.referred_by = phone
    db.commit()
    assert whatsapp._credit_referral(ws, db) is None
    db.close()


def test_referral_credits_both_sides_exactly_once():
    db = _TestingSession()
    referrer, invitee = "27820000020", "27820000021"
    _session(db, referrer)
    ws = _session(db, invitee, referred_by=referrer)

    before_ref = _balance(db, referrer)
    before_inv = _balance(db, invitee)

    assert whatsapp._credit_referral(ws, db) == referrer
    bonus = whatsapp._REFERRAL_BONUS_TOKENS
    assert _balance(db, referrer) == before_ref + bonus
    assert _balance(db, invitee) == before_inv + bonus
    assert ws.referral_credited is True

    # A retry (redeploy, repeated onboarding completion) must pay nothing more.
    assert whatsapp._credit_referral(ws, db) is None
    assert _balance(db, referrer) == before_ref + bonus
    assert _balance(db, invitee) == before_inv + bonus
    db.close()


def test_finishing_onboarding_pays_the_referral_and_shares_the_profile(monkeypatch):
    """End-to-end wiring: complete onboarding → both sides paid, link shown."""
    db = _TestingSession()
    referrer, invitee = "27820000024", "27820000025"
    _session(db, referrer)
    ws = _session(db, invitee, mode="onboarding", referred_by=referrer)

    sent: list[str] = []

    async def fake_send(to, text):
        sent.append(f"{to}|{text}")

    async def fake_cta(to, **kwargs):
        sent.append(kwargs.get("body", ""))

    async def fake_task(*a, **k):
        return None

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_make_magic_link", lambda phone, db, redirect_to=None: "https://x/wa/t")
    monkeypatch.setattr(whatsapp, "_first_match_task", fake_task)

    before_ref = _balance(db, referrer)
    partial = {"firstName": "Sam", "desiredRole": "Deckhand",
               "currentLocation": "Cape Town", "yearsExperience": "3"}

    async def _drive():
        await whatsapp._finish_onboarding(ws, db, [], partial, "done")
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)

    asyncio.run(_drive())

    bonus = whatsapp._REFERRAL_BONUS_TOKENS
    assert _balance(db, referrer) == before_ref + bonus
    assert ws.referral_credited is True
    # Welcome message names the gift and the public profile link…
    welcome = next(t for t in sent if "Welcome to the fleet" in t)
    assert f"+{bonus} match runs" in welcome
    assert "/crew/" in welcome
    # …and the referrer hears about it.
    assert any(t.startswith(f"{referrer}|") for t in sent)
    db.close()


def test_unknown_referral_code_is_kept_as_plain_source():
    db = _TestingSession()
    ws = _session(db, "27820000022")
    whatsapp._record_first_contact("27820000022", ws, "hi · REF-ZZZZZZ", db)
    assert ws.acquisition_source == "REF-ZZZZZZ"
    assert ws.referred_by is None
    db.close()


def test_match_summary_carries_the_invite_line():
    line = whatsapp._referral_invite_line("27820000023")
    assert "you both get 2 extra match runs" in line
    assert whatsapp._referral_code("27820000023") in line
    assert "wa.me" in line


# ── CREW_MATCH_FREE ──────────────────────────────────────────────────────────

class _FakeResult:
    def __init__(self, job_id):
        self.job_id = job_id
        self.matched = True
        self.compatibility = 82.0
        self.tier = "strong"
        self.reason = "fits"
        self.strengths = ["deck time"]
        self.gaps = []
        self.factor_scores = {"role": 90}


def _run_whatsapp_match(monkeypatch, db, phone, *, matched=True):
    """Drive _handle_match_command with a stubbed engine; return sent texts."""
    from app.services import matching_engine

    sent: list[str] = []

    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, buttons):
        sent.append(body)

    async def fake_cta(to, **kwargs):
        sent.append(kwargs.get("body", ""))

    async def fake_pulse(*a, **k):
        return None

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_cta_url", fake_cta)
    monkeypatch.setattr(whatsapp, "_send_match_quality_pulse", fake_pulse)
    monkeypatch.setattr(whatsapp.settings, "OPENAI_API_KEY", "test-key")

    job_ids = [j.id for j in db.query(Job).all()]
    monkeypatch.setattr(
        matching_engine,
        "match_candidate_to_jobs",
        lambda **kw: [_FakeResult(job_ids[0])] if matched else [],
    )

    asyncio.run(whatsapp._handle_match_command(phone, db))
    return sent


def _seed_matchable(db, phone):
    db.add(CrewProfile(user_key=phone, profile_slug=f"s{phone[-6:]}", desired_role="Deckhand"))
    db.add(Job(title="Deckhand", role="Deckhand", yacht="M/Y Test", location="Antibes", status="open"))
    db.commit()


def test_match_spends_a_token_when_flag_is_off(monkeypatch):
    db = _TestingSession()
    phone = "27820000030"
    _seed_matchable(db, phone)
    start = _balance(db, phone)

    sent = _run_whatsapp_match(monkeypatch, db, phone)

    assert _balance(db, phone) == start - 1
    assert any("1 token used" in t for t in sent)
    # The growth loop rides the summary of every completed run.
    assert any(whatsapp._referral_code(phone) in t for t in sent)
    db.close()


def test_match_is_free_and_never_paywalls_when_flag_is_on(monkeypatch):
    monkeypatch.setenv("CREW_MATCH_FREE", "true")
    db = _TestingSession()
    phone = "27820000031"
    _seed_matchable(db, phone)
    # Deliberately broke: the old path would have shown the paywall teaser.
    db.add(CreditAccount(user_key=phone, balance=0))
    db.commit()

    sent = _run_whatsapp_match(monkeypatch, db, phone)

    assert _balance(db, phone) == 0
    assert any("This run is free" in t for t in sent)
    assert not any("buy tokens" in t.lower() for t in sent)
    assert not any("need *1 token*" in t.lower() for t in sent)
    # The run still happened and still shows the results.
    assert any("top 3" in t for t in sent)
    db.close()


def test_free_flag_reads_env_at_call_time(monkeypatch):
    monkeypatch.delenv("CREW_MATCH_FREE", raising=False)
    assert credits_service.crew_match_free() is False
    monkeypatch.setenv("CREW_MATCH_FREE", "TRUE")
    assert credits_service.crew_match_free() is True
    monkeypatch.setenv("CREW_MATCH_FREE", "false")
    assert credits_service.crew_match_free() is False


def test_zero_match_run_refunds_only_when_it_charged(monkeypatch):
    db = _TestingSession()
    phone = "27820000032"
    _seed_matchable(db, phone)
    start = _balance(db, phone)
    _run_whatsapp_match(monkeypatch, db, phone, matched=False)
    assert _balance(db, phone) == start  # spent then refunded

    monkeypatch.setenv("CREW_MATCH_FREE", "1")
    phone2 = "27820000033"
    _seed_matchable(db, phone2)
    start2 = _balance(db, phone2)
    _run_whatsapp_match(monkeypatch, db, phone2, matched=False)
    assert _balance(db, phone2) == start2  # never charged, so never gifted
    db.close()


# ── Durable webhook dedup ────────────────────────────────────────────────────

def test_dedup_survives_a_fresh_in_memory_set(monkeypatch):
    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)
    whatsapp._SEEN_MSG_IDS.clear()
    whatsapp._SEEN_MSG_IDS_ORDER.clear()

    assert whatsapp._inbound_skip_reason("wamid.dedup1", None) is None

    # Simulate a deploy: the process memory is gone, the table is not.
    whatsapp._SEEN_MSG_IDS.clear()
    whatsapp._SEEN_MSG_IDS_ORDER.clear()

    assert whatsapp._inbound_skip_reason("wamid.dedup1", None) == "duplicate"
    assert whatsapp._inbound_skip_reason("wamid.dedup2", None) is None

    db = _TestingSession()
    assert db.query(WhatsAppSeenMessage).count() == 2
    db.close()


def test_dedup_failure_never_swallows_a_message(monkeypatch):
    def _boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(whatsapp, "SessionLocal", _boom)
    whatsapp._SEEN_MSG_IDS.clear()
    whatsapp._SEEN_MSG_IDS_ORDER.clear()
    assert whatsapp._inbound_skip_reason("wamid.dedup3", None) is None


# ── Pending first match ──────────────────────────────────────────────────────

def test_pending_first_match_resumes_after_a_restart(monkeypatch):
    db = _TestingSession()
    phone = "27820000040"
    ws = _session(db, phone, mode="chat", pending_first_match=True)

    started: list[str] = []

    async def fake_task(p, graph_id="", delay_seconds=3.0):
        started.append(p)

    monkeypatch.setattr(whatsapp, "_first_match_task", fake_task)
    whatsapp._ACTIVE_MATCH_RUNS.discard(phone)

    async def _go():
        resumed = await whatsapp._resume_pending_first_match(ws, db)
        await asyncio.sleep(0)  # let the created task run
        return resumed

    assert asyncio.run(_go()) is True
    assert started == [phone]
    whatsapp._finish_match_run(phone)
    db.close()


def test_no_pending_flag_means_no_resume(monkeypatch):
    db = _TestingSession()
    phone = "27820000041"
    ws = _session(db, phone, mode="chat")

    monkeypatch.setattr(whatsapp, "_first_match_task", lambda *a, **k: None)
    assert asyncio.run(whatsapp._resume_pending_first_match(ws, db)) is False
    db.close()


def test_first_match_task_clears_the_flag(monkeypatch):
    db = _TestingSession()
    phone = "27820000042"
    _session(db, phone, mode="chat", pending_first_match=True)
    db.close()

    monkeypatch.setattr(whatsapp, "SessionLocal", _TestingSession)

    async def fake_run(p, graph_id="", scope=whatsapp._MATCH_SCOPE_RECENT):
        return None

    async def fake_enrich(p, db=None):
        return None

    monkeypatch.setattr(whatsapp, "_run_match_command_background", fake_run)
    monkeypatch.setattr(whatsapp, "_send_post_match_enrichment", fake_enrich)

    asyncio.run(whatsapp._first_match_task(phone, delay_seconds=0))

    db = _TestingSession()
    ws = db.query(WhatsAppSession).filter(WhatsAppSession.phone_number == phone).first()
    assert ws.pending_first_match is False
    db.close()


# ── Public profile link ──────────────────────────────────────────────────────

def test_profile_link_command_returns_the_public_url(monkeypatch):
    db = _TestingSession()
    phone = "27820000050"
    ws = _session(db, phone, mode="chat")
    db.add(CrewProfile(user_key=phone, profile_slug="abc123", first_name="Matt"))
    db.commit()

    sent: list[str] = []

    async def fake_send(to, text):
        sent.append(text)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)

    assert asyncio.run(whatsapp._run_chat(ws, "profile link", db)) is None
    assert any("/crew/abc123" in t for t in sent)
    db.close()


def test_profile_card_includes_the_public_url():
    db = _TestingSession()
    phone = "27820000051"
    db.add(CrewProfile(user_key=phone, profile_slug="xyz789", first_name="Matt", desired_role="Deckhand"))
    db.commit()

    text = asyncio.run(whatsapp._handle_profile_command(phone, db))
    assert "/crew/xyz789" in text
    db.close()


def test_refer_command_sends_the_invite_link(monkeypatch):
    db = _TestingSession()
    phone = "27820000052"
    ws = _session(db, phone, mode="chat")

    sent: list[str] = []

    async def fake_send(to, text):
        sent.append(text)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    assert asyncio.run(whatsapp._run_chat(ws, "invite", db)) is None
    assert any(whatsapp._referral_code(phone) in t for t in sent)
    db.close()


# ── Job-submit share prompt ──────────────────────────────────────────────────

def test_job_posted_confirmation_asks_for_a_reshare(monkeypatch):
    sent: list[str] = []

    async def fake_send(to, text):
        sent.append(text)

    async def fake_buttons(to, body, buttons):
        sent.append(body)

    monkeypatch.setattr(whatsapp, "_send_whatsapp", fake_send)
    monkeypatch.setattr(whatsapp, "_send_whatsapp_buttons", fake_buttons)

    job = Job(title="Stewardess", role="Stewardess", location="Palma", status="open")
    for award in ({"granted": True, "balance": 3}, {"granted": False, "balance": 3}):
        sent.clear()
        asyncio.run(whatsapp._send_job_posted_confirmation("27820000060", job, award))
        assert any("/jobs/board" in t for t in sent)
        assert any("reply JOBS" in t for t in sent)


# ── Pack picker: bonus-aware labels ──────────────────────────────────────────

def test_pack_labels_and_anchor_account_for_the_first_purchase_bonus(monkeypatch):
    db = _TestingSession()
    phone = "27820000070"
    sent: dict = {}

    async def fake_list(to, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(whatsapp, "_send_whatsapp_list", fake_list)
    monkeypatch.setattr(whatsapp.payments, "yoco_configured", lambda: True)
    monkeypatch.setattr(whatsapp, "_is_first_purchase", lambda db, phone: True)

    asyncio.run(whatsapp._send_token_pack_picker(phone, db))

    descriptions = [r["description"] for r in sent["rows"]]
    assert any("with bonus" in d for d in descriptions)

    bonus = whatsapp.settings.FIRST_PURCHASE_BONUS_TOKENS
    best = min(
        whatsapp.settings.TOKEN_PACKAGES,
        key=lambda p: whatsapp._pack_rate(p, True),
    )
    assert f"{int(best['tokens'])}-token pack" in sent["body"]
    # The bonus makes a qualifying pack genuinely cheaper per run.
    qualifying = next(
        p for p in whatsapp.settings.TOKEN_PACKAGES
        if int(p["tokens"]) >= whatsapp.settings.FIRST_PURCHASE_BONUS_MIN_TOKENS
    )
    if bonus > 0:
        assert whatsapp._pack_rate(qualifying, True) < whatsapp._pack_rate(qualifying, False)
    db.close()


def test_pack_labels_unchanged_for_a_repeat_buyer(monkeypatch):
    db = _TestingSession()
    sent: dict = {}

    async def fake_list(to, **kwargs):
        sent.update(kwargs)

    monkeypatch.setattr(whatsapp, "_send_whatsapp_list", fake_list)
    monkeypatch.setattr(whatsapp.payments, "yoco_configured", lambda: True)
    monkeypatch.setattr(whatsapp, "_is_first_purchase", lambda db, phone: False)

    asyncio.run(whatsapp._send_token_pack_picker("27820000071", db))

    assert not any("with bonus" in r["description"] for r in sent["rows"])
    db.close()


# ── Win-back copy honesty ────────────────────────────────────────────────────

def test_winback_never_promises_a_free_run_on_zero_tokens():
    ws = WhatsAppSession(phone_number="27820000080", mode="chat")
    body, buttons = window_winback._no_match_nudge(ws, 0)
    assert "free run" not in body
    assert "*JOBS*" in body
    assert buttons[0][0] == "cmd_jobs"
    # Buying is mentioned, but only after the free option.
    assert body.index("JOBS") < body.index("buy tokens")


def test_winback_counts_the_runs_the_user_actually_has():
    ws = WhatsAppSession(phone_number="27820000081", mode="chat")
    body, buttons = window_winback._no_match_nudge(ws, 3)
    assert "3 free runs" in body
    assert buttons[0][0] == "btn_find_matches"

    body_one, _ = window_winback._no_match_nudge(ws, 1)
    assert "1 free run" in body_one


def test_winback_says_matching_is_free_under_the_flag(monkeypatch):
    monkeypatch.setenv("CREW_MATCH_FREE", "true")
    ws = WhatsAppSession(phone_number="27820000082", mode="chat")
    body, buttons = window_winback._no_match_nudge(ws, 0)
    assert "free right now" in body
    assert buttons[0][0] == "btn_find_matches"


def test_early_onboarding_nudge_drops_the_free_promise_on_zero_tokens():
    ws = WhatsAppSession(phone_number="27820000083", mode="onboarding", partial_profile="{}")
    body, _ = window_winback._early_onboarding_nudge(ws, 0)
    assert "free" not in body
    body_funded, _ = window_winback._early_onboarding_nudge(ws, 5)
    assert "first AI job match is free" in body_funded
