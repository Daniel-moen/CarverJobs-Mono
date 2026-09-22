"""Tests for WhatsApp ops alerting (services/ops_alerts) and its two callers.

The property under test everywhere here is *edge-triggering*: an alert channel
that repeats itself on every cycle of a steady-state failure gets muted by its
operator, which is indistinguishable from having no alerting at all.
"""
import asyncio

import pytest

from app import health_checker, scheduler
from app.services import ops_alerts


@pytest.fixture()
def sent(monkeypatch):
    """Capture ops messages and pretend the channel is configured."""
    messages: list[str] = []

    monkeypatch.setattr(ops_alerts, "is_configured", lambda: True)
    monkeypatch.setattr(ops_alerts, "notify_ops_sync", lambda text: messages.append(text) or True)

    async def _async_notify(text: str) -> bool:
        messages.append(text)
        return True

    monkeypatch.setattr(ops_alerts, "notify_ops", _async_notify)
    return messages


@pytest.fixture(autouse=True)
def _reset_alert_state():
    health_checker._alert_state.clear()
    scheduler.reset_alert_state()
    yield
    health_checker._alert_state.clear()
    scheduler.reset_alert_state()


def _results(**services) -> dict:
    return {
        name: {"connected": ok, "detail": detail, "checked_at": "2026-09-22T00:00:00+00:00"}
        for name, (ok, detail) in services.items()
    }


# ── Health-check flips ────────────────────────────────────────────────────────

def test_healthy_baseline_sends_nothing(sent):
    health_checker._dispatch_ops_alerts(_results(database=(True, "Database reachable")))
    assert sent == []


def test_ok_to_failed_sends_one_alert(sent):
    health_checker._dispatch_ops_alerts(_results(database=(True, "Database reachable")))
    health_checker._dispatch_ops_alerts(_results(database=(False, "Service unavailable")))

    assert len(sent) == 1
    assert "database" in sent[0]
    assert "FAILED" in sent[0]


def test_steady_state_failure_does_not_spam(sent):
    health_checker._dispatch_ops_alerts(_results(job_pipeline=(True, "3 new jobs")))
    for _ in range(10):
        health_checker._dispatch_ops_alerts(_results(job_pipeline=(False, "No new jobs in 96h")))

    assert len(sent) == 1, "a failure that persists must alert exactly once"


def test_recovery_sends_one_alert(sent):
    health_checker._dispatch_ops_alerts(_results(job_pipeline=(True, "3 new jobs")))
    health_checker._dispatch_ops_alerts(_results(job_pipeline=(False, "No new jobs in 96h")))
    sent.clear()

    health_checker._dispatch_ops_alerts(_results(job_pipeline=(True, "5 new jobs")))
    health_checker._dispatch_ops_alerts(_results(job_pipeline=(True, "6 new jobs")))

    assert len(sent) == 1
    assert "RECOVERED" in sent[0]


def test_critical_service_already_down_at_boot_alerts_once(sent):
    """A restart while the pipeline is dead must not reset the outage to silence."""
    for _ in range(3):
        health_checker._dispatch_ops_alerts(_results(job_pipeline=(False, "No jobs ever ingested")))

    assert len(sent) == 1
    assert "DOWN at startup" in sent[0]


def test_unconfigured_google_login_never_alerts(sent):
    """connected=False for "not configured" is a steady state on every dev box."""
    for _ in range(3):
        health_checker._dispatch_ops_alerts(_results(google_login=(False, "Not configured")))

    assert sent == []


def test_multiple_flips_are_batched_into_one_message(sent):
    health_checker._dispatch_ops_alerts(
        _results(database=(True, "ok"), openai_ai=(True, "ok"))
    )
    health_checker._dispatch_ops_alerts(
        _results(database=(False, "Service unavailable"), openai_ai=(False, "Request timed out"))
    )

    assert len(sent) == 1
    assert "database" in sent[0] and "openai_ai" in sent[0]


def test_nothing_is_sent_when_ops_number_is_unset(monkeypatch):
    """The default (no WHATSAPP_OPS_NUMBER) must be a silent no-op, not an error."""
    calls: list[str] = []
    monkeypatch.setattr(ops_alerts, "is_configured", lambda: False)
    monkeypatch.setattr(ops_alerts, "notify_ops_sync", lambda text: calls.append(text) or True)

    health_checker._dispatch_ops_alerts(_results(database=(True, "ok")))
    health_checker._dispatch_ops_alerts(_results(database=(False, "down")))

    assert calls == []
    # State is still tracked, so switching the channel on later doesn't replay history.
    assert health_checker._alert_state["database"] is False


def test_dispatch_failure_never_breaks_the_health_loop(monkeypatch):
    def _boom(_results):
        raise RuntimeError("alert channel exploded")

    monkeypatch.setattr(health_checker, "_dispatch_ops_alerts", _boom)
    monkeypatch.setattr(health_checker, "_check_openai", lambda: {
        "connected": True, "detail": "Reachable", "checked_at": "t"})

    results = health_checker.run_checks()
    assert results["api"]["connected"] is True


# ── Scraper-cycle alerts ──────────────────────────────────────────────────────

def _cycle(created: int, failures=None):
    asyncio.run(scheduler._alert_on_cycle_outcome(created, 10, failures or []))


def test_scrape_failure_alerts(sent):
    _cycle(0, ["Apify scrape failed (CRV-6005): boom"])
    assert len(sent) == 1
    assert "CRV-6005" in sent[0]


def test_zero_new_jobs_alerts_only_on_the_third_run(sent):
    _cycle(0)
    assert sent == []
    _cycle(0)
    assert sent == []
    _cycle(0)
    assert len(sent) == 1
    assert "3 consecutive scrape cycles" in sent[0]


def test_zero_new_jobs_does_not_re_alert_while_still_dead(sent):
    for _ in range(8):
        _cycle(0)
    assert len(sent) == 1, "one page per outage, not one per cycle"


def test_streak_resets_after_a_productive_cycle(sent):
    _cycle(0)
    _cycle(0)
    _cycle(4)            # supply came back — streak resets
    _cycle(0)
    _cycle(0)
    assert sent == []
    _cycle(0)
    assert len(sent) == 1


def test_productive_cycle_alerts_nothing(sent):
    _cycle(7)
    assert sent == []


def test_cycle_alert_survives_a_broken_channel(monkeypatch):
    async def _boom(_text):
        raise RuntimeError("no network")

    monkeypatch.setattr(ops_alerts, "notify_ops", _boom)
    _cycle(0, ["something broke"])   # must not raise


# ── Module-level guards ───────────────────────────────────────────────────────

def test_ops_number_strips_formatting(monkeypatch):
    monkeypatch.setenv("WHATSAPP_OPS_NUMBER", "+27 82 123 4567")
    assert ops_alerts.ops_number() == "27821234567"


def test_ops_number_defaults_to_disabled(monkeypatch):
    monkeypatch.delenv("WHATSAPP_OPS_NUMBER", raising=False)
    assert ops_alerts.ops_number() == ""
    assert ops_alerts.is_configured() is False
    assert ops_alerts.notify_ops_sync("hello") is False
    assert asyncio.run(ops_alerts.notify_ops("hello")) is False
