"""
In-memory metrics counters + rolling time-series history.

Counters reset on server restart — intentional, they show "live since last
deploy" activity.  The time-series is populated by a background task that
calls record_snapshot() every 60 seconds (up to 60 points = 1 hour).
"""
import threading
from collections import Counter, deque
from datetime import datetime, timezone

_lock = threading.Lock()

server_started_at: datetime = datetime.now(timezone.utc)

_counters: dict[str, int] = {
    "requests_total": 0,
    "errors_4xx": 0,
    "errors_5xx": 0,
    "rate_limit_hits": 0,
    "csrf_rejections": 0,
    "feature_blocked": 0,
    "logins_success": 0,
    "logins_failed": 0,
    "onboard_started": 0,
    "onboard_completed": 0,
    "interview_turns": 0,
    "matching_queued": 0,
    "matching_completed": 0,
    "doc_uploads": 0,
    "doc_downloads": 0,
    "doc_deletes": 0,
    "scraper_triggers": 0,
    "whatsapp_messages": 0,
    "whatsapp_apply_drafts": 0,
    "whatsapp_magic_logins": 0,
    "crew_matches": 0,
}

# Response time tracking (Welford online mean) — excludes AI/interview paths.
_resp_count: int = 0
_resp_mean_ms: float = 0.0

# AI call latency — tracks only the external HTTP call duration.
_ai_resp_count: int = 0
_ai_resp_mean_ms: float = 0.0

# Per-module error tracking (route prefix -> {4xx: n, 5xx: n})
_errors_by_module: Counter = Counter()

# Rolling 60-point history (one point per minute = last 60 minutes).
_HISTORY_MAX = 60
_history: deque = deque(maxlen=_HISTORY_MAX)
_prev_snapshot: dict[str, int] = {}
_prev_errors_by_module: dict[str, int] = {}


def increment(key: str, amount: int = 1) -> None:
    with _lock:
        if key in _counters:
            _counters[key] += amount
        else:
            _counters[key] = amount


def record_response_time(ms: float) -> None:
    """Update rolling mean for non-AI endpoint response times (Welford)."""
    global _resp_count, _resp_mean_ms
    with _lock:
        _resp_count += 1
        _resp_mean_ms += (ms - _resp_mean_ms) / _resp_count


def record_ai_response_time(ms: float) -> None:
    """Update rolling mean for AI API call latency (Welford)."""
    global _ai_resp_count, _ai_resp_mean_ms
    with _lock:
        _ai_resp_count += 1
        _ai_resp_mean_ms += (ms - _ai_resp_mean_ms) / _ai_resp_count


def record_error_by_module(module: str, status_class: str) -> None:
    """Track an error against a route module. status_class is '4xx' or '5xx'."""
    key = f"{module}:{status_class}"
    with _lock:
        _errors_by_module[key] += 1


def errors_by_module_snapshot() -> dict:
    """Return {module: {4xx: n, 5xx: n}} breakdown."""
    with _lock:
        result: dict[str, dict[str, int]] = {}
        for key, count in _errors_by_module.items():
            module, status_class = key.rsplit(":", 1)
            if module not in result:
                result[module] = {"4xx": 0, "5xx": 0}
            result[module][status_class] = count
        return result


def snapshot() -> dict:
    with _lock:
        data = dict(_counters)
        data["avg_response_ms"] = round(_resp_mean_ms, 1)
        data["avg_ai_response_ms"] = round(_ai_resp_mean_ms, 1)
        return data


def record_snapshot() -> None:
    """Append a time-series point with per-minute deltas."""
    with _lock:
        current = dict(_counters)
        prev = dict(_prev_snapshot) if _prev_snapshot else {k: 0 for k in _counters}

        def _delta(key: str) -> int:
            return max(0, current.get(key, 0) - prev.get(key, 0))

        current_mod = dict(_errors_by_module)
        mod_deltas: dict[str, int] = {}
        for key, count in current_mod.items():
            mod_deltas[key] = max(0, count - _prev_errors_by_module.get(key, 0))

        module_errors: dict[str, dict[str, int]] = {}
        for key, delta in mod_deltas.items():
            if delta == 0:
                continue
            module, status_class = key.rsplit(":", 1)
            if module not in module_errors:
                module_errors[module] = {"4xx": 0, "5xx": 0}
            module_errors[module][status_class] = delta

        _history.append({
            "ts": datetime.now(timezone.utc).isoformat(),
            "requests": _delta("requests_total"),
            "errors_4xx": _delta("errors_4xx"),
            "errors_5xx": _delta("errors_5xx"),
            "rate_limit_hits": _delta("rate_limit_hits"),
            "csrf_rejections": _delta("csrf_rejections"),
            "logins_success": _delta("logins_success"),
            "logins_failed": _delta("logins_failed"),
            "onboard_started": _delta("onboard_started"),
            "onboard_completed": _delta("onboard_completed"),
            "avg_response_ms": round(_resp_mean_ms, 1),
            "avg_ai_response_ms": round(_ai_resp_mean_ms, 1),
            "errors_by_module": module_errors,
        })
        _prev_snapshot.clear()
        _prev_snapshot.update(current)
        _prev_errors_by_module.clear()
        _prev_errors_by_module.update(current_mod)


def history() -> list:
    with _lock:
        return list(_history)
