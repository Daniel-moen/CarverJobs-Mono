"""
Abandoned-checkout recovery — the "you left money on the table" loop.

`payments.create_checkout` writes a `pending` Subscription row and drops a Yoco
payment link in the WhatsApp chat, but nothing ever followed up when the buyer
didn't pay. This sweep closes that gap: every ~15 minutes it finds pending
WhatsApp checkouts that are 45 minutes to 24 hours old and sends ONE free-text
nudge with the original payment link (or a *buy tokens* prompt when the link
is unknown).

Why the 24h ceiling: WhatsApp only allows free-form business messages inside
the 24-hour service window after the user's last inbound message. A checkout
always starts from an inbound chat message, so anything younger than 24h is
safely reachable free-text; older pendings are skipped rather than paying for
a template.

Everything is best-effort — any failure is logged and never crashes the loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app import flags
from app.analytics import record_server_event
from app.logger import get_logger
from app.models import Subscription, WhatsAppSession
from app.services import payments
from app.settings import settings

log = get_logger("carver.checkout_recovery")

CHECK_INTERVAL_SECONDS = 15 * 60
# A pending checkout is considered abandoned once it's this old…
REMIND_AFTER_MINUTES = 45
# …and unreachable free-text once past the WhatsApp 24h service window.
MAX_AGE_HOURS = 24
# Safety cap per sweep while Meta messaging limits are still low.
_MAX_REMINDERS_PER_RUN = 25


def _configured() -> bool:
    return bool(settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_ACCESS_TOKEN)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _is_whatsapp_checkout(db: Session, sub: Subscription) -> bool:
    """WhatsApp when the row says so; legacy rows (no channel) fall back to
    "does this user_key have a WhatsApp session" — phone-keyed buyers only."""
    if sub.channel:
        return sub.channel == "whatsapp"
    return (
        db.query(WhatsAppSession.phone_number)
        .filter(WhatsAppSession.phone_number == sub.user_key)
        .first()
    ) is not None


def _reminder_body(sub: Subscription) -> str:
    pkg = payments.package_for_amount(payments.amount_str_to_cents(sub.amount))
    if pkg is not None:
        price = f"{float(pkg['price']):g}"
        pack_bit = f"*{pkg['label']}* pack ({int(pkg['tokens'])} tokens, R{price})"
    else:
        pack_bit = f"token pack (R{float(sub.amount):g})"
    resume = f"👉 {sub.checkout_url}" if sub.checkout_url else "👉 Type *buy tokens* to grab it."
    return (
        f"💳 Your {pack_bit} is still waiting — tokens land the second you pay.\n\n"
        f"{resume}"
    )


async def run_checkout_recovery_once(db: Session | None = None) -> dict[str, int]:
    """One recovery sweep. Returns counts for logging/tests."""
    from app.database import SessionLocal

    stats = {"checked": 0, "abandoned": 0, "sent": 0, "skipped": 0}
    if not _configured():
        log.debug("Checkout recovery skipped — WhatsApp credentials not configured")
        return stats
    if not flags.is_enabled("whatsapp"):
        log.info("Checkout recovery skipped — whatsapp feature flag disabled")
        return stats

    # Lazy import — whatsapp routes import payments which sits next to us.
    from app.routes import whatsapp as whatsapp_routes

    now = datetime.now(timezone.utc)
    newest_eligible = now - timedelta(minutes=REMIND_AFTER_MINUTES)
    oldest_eligible = now - timedelta(hours=MAX_AGE_HOURS)

    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        pendings = (
            db.query(Subscription)
            .filter(Subscription.status == "pending", Subscription.reminder_sent_at.is_(None))
            .all()
        )
        for sub in pendings:
            stats["checked"] += 1
            # SQLite hands back naive datetimes — window-filter in Python.
            created = _as_aware(sub.created_at)
            if created is None or created > newest_eligible or created < oldest_eligible:
                stats["skipped"] += 1
                continue
            if not _is_whatsapp_checkout(db, sub):
                stats["skipped"] += 1
                continue
            if stats["sent"] >= _MAX_REMINDERS_PER_RUN:
                log.warning("Checkout recovery: per-run cap (%d) reached", _MAX_REMINDERS_PER_RUN)
                break

            phone = sub.user_key
            try:
                stats["abandoned"] += 1
                record_server_event(phone, "checkout_abandoned", "whatsapp")
                await whatsapp_routes._send_whatsapp_buttons(
                    phone,
                    _reminder_body(sub),
                    [("cmd_subscribe", "Buy Tokens"), ("btn_menu", "Menu")],
                )
                # One reminder max — mark it sent even if Meta soft-failed the
                # send (the helper swallows HTTP errors); never nag twice.
                sub.reminder_sent_at = now
                db.commit()
                stats["sent"] += 1
                record_server_event(phone, "checkout_reminder_sent", "whatsapp")
            except Exception as exc:
                db.rollback()
                log.error(
                    "Checkout reminder failed | phone=%s | %s",
                    (phone or "")[:6] + "****", exc,
                )
    finally:
        if own_db:
            db.close()

    log.info(
        "Checkout recovery sweep done | checked=%d | abandoned=%d | sent=%d | skipped=%d",
        stats["checked"], stats["abandoned"], stats["sent"], stats["skipped"],
    )
    return stats


async def checkout_recovery_loop() -> None:
    """Background asyncio task started at API startup. No-ops until configured."""
    # Let DB init settle before the first sweep.
    await asyncio.sleep(120)
    while True:
        try:
            await run_checkout_recovery_once()
        except Exception as exc:
            log.error("Checkout recovery sweep failed | error=%s", exc)
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
