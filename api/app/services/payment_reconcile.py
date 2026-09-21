"""
Payment reconcile sweep — the safety net under the Yoco webhook.

Crediting hangs entirely off `POST /subscription/webhook`. Anything that stops
one delivery landing — a deploy mid-flight, a signature clock skew, a Yoco
retry budget running out — charges the buyer and gives them nothing, silently.
Nobody finds out until the user complains, and most never do.

So every ~30 minutes this sweep takes the other side of the conversation: for
each checkout we still believe is unpaid and that is young enough to matter
(≤48h), it asks Yoco directly

    GET https://payments.yoco.com/api/checkouts/{checkout_id}

and, when Yoco says the checkout completed, credits it through exactly the same
function the webhook uses (`subscription.credit_successful_payment`). That
function no-ops on an already-completed row, so a webhook arriving mid-sweep
cannot double-credit.

"superseded" rows are swept too: those are checkouts the buyer abandoned in
favour of a newer one and then went back and paid (see
`services/payments.create_checkout`).

Everything is best-effort — any failure is logged and never crashes the loop.
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from app.logger import get_logger
from app.models import Subscription
from app.settings import settings

log = get_logger("carver.payment_reconcile")

YOCO_CHECKOUT_URL = "https://payments.yoco.com/api/checkouts"

# Yoco's wording for "the buyer paid". Anything else means not yet / never.
_PAID_STATUSES = {"completed", "succeeded", "successful", "paid"}
# Safety cap per sweep — a backlog drains over a few cycles rather than
# hammering Yoco in one burst.
_MAX_CHECKS_PER_RUN = 50

_http = httpx.AsyncClient(timeout=20.0)


def _configured() -> bool:
    return bool(settings.PAYMENT_RECONCILE_ENABLED and settings.YOCO_SECRET_KEY)


def _as_aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _fetch_checkout(checkout_id: str) -> dict | None:
    """Ask Yoco about one checkout. None on any failure (retried next sweep)."""
    try:
        resp = await _http.get(
            f"{YOCO_CHECKOUT_URL}/{checkout_id}",
            headers={"Authorization": f"Bearer {settings.YOCO_SECRET_KEY}"},
        )
    except httpx.HTTPError as exc:
        log.warning("Yoco checkout lookup failed | checkout_id=%s | %s", checkout_id, exc)
        return None
    if resp.status_code != 200:
        log.warning(
            "Yoco checkout lookup rejected | checkout_id=%s | status=%d | body=%s",
            checkout_id, resp.status_code, resp.text[:300],
        )
        return None
    try:
        return resp.json()
    except ValueError as exc:
        log.warning("Yoco checkout lookup invalid JSON | checkout_id=%s | %s", checkout_id, exc)
        return None


def _tokens_from_checkout(data: dict, sub: Subscription) -> int | None:
    """Token count Yoco is holding for this checkout, if it still has it."""
    meta = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    try:
        tokens = int(meta.get("tokens") or 0)
    except (TypeError, ValueError):
        tokens = 0
    # Falling through to None lets the shared crediting path reverse-lookup the
    # pack from the amount on the row.
    return tokens if tokens > 0 else None


async def run_payment_reconcile_once(db: Session | None = None) -> dict[str, int]:
    """One reconcile sweep. Returns counts for logging/tests."""
    from app.database import SessionLocal
    from app.routes.subscription import CREDITABLE_STATUSES, credit_successful_payment

    stats = {"checked": 0, "asked": 0, "credited": 0, "still_unpaid": 0, "errors": 0}
    if not _configured():
        log.debug("Payment reconcile skipped — not enabled or YOCO_SECRET_KEY missing")
        return stats

    now = datetime.now(timezone.utc)
    oldest = now - timedelta(hours=settings.PAYMENT_RECONCILE_MAX_AGE_HOURS)

    own_db = db is None
    if own_db:
        db = SessionLocal()
    try:
        candidates = (
            db.query(Subscription)
            .filter(
                Subscription.status.in_(CREDITABLE_STATUSES),
                Subscription.checkout_id.isnot(None),
            )
            .all()
        )
        for sub in candidates:
            stats["checked"] += 1
            # SQLite hands back naive datetimes — age-filter in Python.
            created = _as_aware(sub.created_at)
            if created is None or created < oldest:
                continue
            if stats["asked"] >= _MAX_CHECKS_PER_RUN:
                log.warning("Payment reconcile: per-run cap (%d) reached", _MAX_CHECKS_PER_RUN)
                break

            stats["asked"] += 1
            data = await _fetch_checkout(str(sub.checkout_id))
            if data is None:
                stats["errors"] += 1
                continue

            yoco_status = str(data.get("status") or "").strip().lower()
            if yoco_status not in _PAID_STATUSES:
                stats["still_unpaid"] += 1
                continue

            try:
                result = await credit_successful_payment(
                    db, sub,
                    tokens_hint=_tokens_from_checkout(data, sub),
                    payment_id=data.get("paymentId") or data.get("id"),
                    source="reconcile_sweep",
                )
            except Exception as exc:
                db.rollback()
                stats["errors"] += 1
                log.error(
                    "PAYMENT_RECONCILE credit failed | ref=%s | user=%s | %s",
                    sub.m_payment_id, sub.user_key, exc,
                )
                continue

            if result.get("credited"):
                stats["credited"] += 1
                log.error(
                    "PAYMENT_RECONCILE sweep credited | ref=%s | user=%s | checkout_id=%s | "
                    "tokens=%s | bonus=%s — Yoco says paid but no webhook ever credited it",
                    sub.m_payment_id, sub.user_key, sub.checkout_id,
                    result.get("tokens"), result.get("bonus"),
                )
    finally:
        if own_db:
            db.close()

    if stats["asked"]:
        log.info(
            "Payment reconcile sweep done | checked=%d | asked=%d | credited=%d | "
            "still_unpaid=%d | errors=%d",
            stats["checked"], stats["asked"], stats["credited"],
            stats["still_unpaid"], stats["errors"],
        )
    return stats


async def payment_reconcile_loop() -> None:
    """Background asyncio task started at API startup. No-ops until configured."""
    interval_seconds = max(60, settings.PAYMENT_RECONCILE_INTERVAL_MINUTES * 60)
    # Let DB init settle before the first sweep.
    await asyncio.sleep(180)
    while True:
        try:
            await run_payment_reconcile_once()
        except Exception as exc:
            log.error("Payment reconcile sweep failed | error=%s", exc)
        await asyncio.sleep(interval_seconds)
