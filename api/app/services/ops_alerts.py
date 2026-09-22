"""
Ops alerting over WhatsApp — the "someone tell me it broke" channel.

Nothing in the stack ever paged a human: the Facebook scraper died and the
outage was only spotted months later, by hand, from the job counts. Health
checks already knew (``/status/services`` flags a stale pipeline) but the
verdict only existed behind an admin login nobody opens daily.

This module is the one place that pushes a plain WhatsApp text to the operator
on WHATSAPP_OPS_NUMBER. Alerts are **edge-triggered by their callers** — see
``health_checker._dispatch_ops_alerts`` and the scraper-cycle counters in
``scheduler`` — because a message on every steady-state failure trains the
operator to ignore the channel, which is the same as having no channel.

Disabled by default: with WHATSAPP_OPS_NUMBER unset every call is a cheap no-op
that returns False, so tests and dev boxes never send anything.

Two entry points, one for each kind of caller:

* ``notify_ops``      — async; reuses the bot's pooled sender
  (``routes.whatsapp._send_whatsapp``) so ops messages get the same retry,
  logging and send-audit trail as crew messages.
* ``notify_ops_sync`` — blocking; for callers that are *not* on the API's event
  loop (``health_checker.run_checks`` is driven through ``asyncio.to_thread``).
  routes/whatsapp's ``AsyncClient`` is pinned to the loop that first used it, so
  driving it from a worker thread would poison its connection pool. That path
  posts with a one-shot sync client instead — the only duplicated bit of Graph
  API wiring in the codebase, and deliberately so.
"""
import os

import httpx

from app.logger import get_logger
from app.settings import settings

log = get_logger("carver.ops_alerts")

_GRAPH_URL = "https://graph.facebook.com/v23.0"

# Prefix every alert so an operator scanning their chat list can tell an ops
# page apart from the bot talking to crew.
_PREFIX = "🛠 JobCarver ops"


def ops_number() -> str:
    """The operator's WhatsApp number in digits-only Graph format ("" = disabled).

    Read via os.getenv rather than settings so this module stays independent of
    the settings module another worker is editing. Setting name:
    WHATSAPP_OPS_NUMBER (E.164, with or without the leading "+").
    """
    return "".join(c for c in os.getenv("WHATSAPP_OPS_NUMBER", "") if c.isdigit())


def is_configured() -> bool:
    """True when an ops number AND WhatsApp credentials are both present."""
    return bool(
        ops_number()
        and settings.WHATSAPP_PHONE_NUMBER_ID
        and settings.WHATSAPP_ACCESS_TOKEN
    )


def _body(text: str) -> str:
    env = settings.APP_ENV
    return f"{_PREFIX} [{env}]\n\n{text}".strip()


async def notify_ops(text: str) -> bool:
    """Send one plain WhatsApp text to the ops number. Returns True if sent.

    Never raises: an alerting channel that can take the caller down with it is
    worse than no alerting channel.
    """
    number = ops_number()
    if not number:
        log.debug("Ops alert skipped — WHATSAPP_OPS_NUMBER not set | text=%s", text[:80])
        return False
    if not is_configured():
        log.warning("Ops alert skipped — WhatsApp credentials not configured | text=%s", text[:80])
        return False

    # Local import: routes import services at module level, so a service
    # importing a route has to do it lazily to stay out of the import cycle.
    # Same pattern as job_alerts._send_freeform.
    from app.routes.whatsapp import _send_whatsapp

    try:
        await _send_whatsapp(number, _body(text))
        log.info("Ops alert sent | chars=%d", len(text))
        return True
    except Exception as exc:
        log.error("Ops alert send failed | %s", exc)
        return False


def notify_ops_sync(text: str) -> bool:
    """Blocking variant for callers off the event loop. Returns True if sent.

    Posts with a one-shot sync client — see the module docstring for why the
    pooled async sender can't be reused from a worker thread. Never raises.
    """
    number = ops_number()
    if not number:
        log.debug("Ops alert skipped — WHATSAPP_OPS_NUMBER not set | text=%s", text[:80])
        return False
    if not is_configured():
        log.warning("Ops alert skipped — WhatsApp credentials not configured | text=%s", text[:80])
        return False

    payload = {
        "messaging_product": "whatsapp",
        "to": number,
        "type": "text",
        "text": {"body": _body(text)},
    }
    try:
        resp = httpx.post(
            f"{_GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages",
            json=payload,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
            timeout=20.0,
        )
        if resp.status_code >= 400:
            log.error(
                "Ops alert send failed | status=%d | body=%s",
                resp.status_code, resp.text[:300],
            )
            return False
        log.info("Ops alert sent | chars=%d", len(text))
        return True
    except Exception as exc:
        log.error("Ops alert send error | %s", exc)
        return False
