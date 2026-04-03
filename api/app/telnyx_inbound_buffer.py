"""Ring buffer of recent inbound Telnyx SMS (process-local; single-instance deploys)."""
from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from threading import Lock

_lock = Lock()
_recent: deque[dict] = deque(maxlen=50)


def record(*, from_number: str, to_numbers: list[str], text: str, msg_id: str) -> None:
    with _lock:
        _recent.appendleft(
            {
                "received_at": datetime.now(timezone.utc).isoformat(),
                "from": from_number,
                "to": to_numbers,
                "text": text,
                "id": msg_id,
            }
        )


def recent() -> list[dict]:
    with _lock:
        return list(_recent)
