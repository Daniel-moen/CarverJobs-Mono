"""
Server-side Mixpanel track calls via the HTTP API (stdlib only).

https://developer.mixpanel.com/reference/track-event
"""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request

from app.logger import get_logger

log = get_logger("carver.mixpanel")

_DEFAULT_API_HOST = "https://api.mixpanel.com"


def mixpanel_config() -> tuple[str, str]:
    token = (
        os.getenv("MIXPANEL_PROJECT_TOKEN")
        or os.getenv("MIXPANEL_TOKEN")
        or os.getenv("VITE_MIXPANEL_TOKEN")
        or ""
    ).strip()
    host = os.getenv("MIXPANEL_API_HOST", _DEFAULT_API_HOST).strip().rstrip("/")
    return token, host


def track(
    *,
    event: str,
    distinct_id: str,
    properties: dict | None = None,
    timeout: float = 2,
) -> None:
    token, api_host = mixpanel_config()
    if not token:
        return

    props: dict = {
        "token": token,
        "distinct_id": distinct_id,
        "time": int(time.time()),
    }
    if properties:
        for key, value in properties.items():
            if value is not None:
                props[key] = value

    payload = [{"event": event, "properties": props}]
    body = urllib.parse.urlencode(
        {"data": base64.b64encode(json.dumps(payload).encode()).decode()}
    ).encode()
    req = urllib.request.Request(
        f"{api_host}/track",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception as exc:
        log.debug("Mixpanel track failed | event=%s | error=%s", event, exc)
