"""Tests for metrics counters, error-by-module tracking, and time-series snapshots."""
from app import metrics


def _reset_metrics():
    """Reset metrics state to a clean baseline for isolated tests."""
    with metrics._lock:
        for k in metrics._counters:
            metrics._counters[k] = 0
        metrics._resp_count = 0
        metrics._resp_mean_ms = 0.0
        metrics._ai_resp_count = 0
        metrics._ai_resp_mean_ms = 0.0
        metrics._errors_by_module.clear()
        metrics._history.clear()
        metrics._prev_snapshot.clear()
        metrics._prev_errors_by_module.clear()


class TestMetricsCounters:
    def setup_method(self):
        _reset_metrics()

    def test_increment_known_key(self):
        metrics.increment("requests_total")
        metrics.increment("requests_total", 5)
        snap = metrics.snapshot()
        assert snap["requests_total"] == 6

    def test_increment_unknown_key(self):
        metrics.increment("custom_counter", 3)
        snap = metrics.snapshot()
        assert snap["custom_counter"] == 3

    def test_new_counters_exist(self):
        snap = metrics.snapshot()
        assert "doc_uploads" in snap
        assert "doc_downloads" in snap
        assert "doc_deletes" in snap
        assert "scraper_triggers" in snap


class TestResponseTimeTracking:
    def setup_method(self):
        _reset_metrics()

    def test_single_response_time(self):
        metrics.record_response_time(50.0)
        snap = metrics.snapshot()
        assert snap["avg_response_ms"] == 50.0

    def test_mean_of_two(self):
        metrics.record_response_time(40.0)
        metrics.record_response_time(60.0)
        snap = metrics.snapshot()
        assert snap["avg_response_ms"] == 50.0

    def test_ai_response_time(self):
        metrics.record_ai_response_time(200.0)
        metrics.record_ai_response_time(300.0)
        snap = metrics.snapshot()
        assert snap["avg_ai_response_ms"] == 250.0


class TestErrorByModule:
    def setup_method(self):
        _reset_metrics()

    def test_record_single_module_error(self):
        metrics.record_error_by_module("auth", "4xx")
        result = metrics.errors_by_module_snapshot()
        assert result == {"auth": {"4xx": 1, "5xx": 0}}

    def test_record_mixed_errors(self):
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_error_by_module("auth", "5xx")
        metrics.record_error_by_module("jobs", "5xx")
        result = metrics.errors_by_module_snapshot()
        assert result["auth"]["4xx"] == 2
        assert result["auth"]["5xx"] == 1
        assert result["jobs"]["5xx"] == 1
        assert result["jobs"]["4xx"] == 0

    def test_empty_by_default(self):
        result = metrics.errors_by_module_snapshot()
        assert result == {}


class TestTimeSeries:
    def setup_method(self):
        _reset_metrics()

    def test_snapshot_creates_history_point(self):
        metrics.increment("requests_total", 10)
        metrics.record_snapshot()
        h = metrics.history()
        assert len(h) == 1
        assert h[0]["requests"] == 10
        assert "ts" in h[0]

    def test_snapshot_deltas(self):
        metrics.increment("requests_total", 5)
        metrics.record_snapshot()
        metrics.increment("requests_total", 3)
        metrics.record_snapshot()
        h = metrics.history()
        assert h[0]["requests"] == 5
        assert h[1]["requests"] == 3

    def test_snapshot_includes_module_errors(self):
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_error_by_module("jobs", "5xx")
        metrics.record_snapshot()
        h = metrics.history()
        assert len(h) == 1
        mod_errors = h[0]["errors_by_module"]
        assert mod_errors["auth"]["4xx"] == 1
        assert mod_errors["jobs"]["5xx"] == 1

    def test_snapshot_module_error_deltas(self):
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_snapshot()
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_error_by_module("auth", "4xx")
        metrics.record_snapshot()
        h = metrics.history()
        assert h[0]["errors_by_module"]["auth"]["4xx"] == 1
        assert h[1]["errors_by_module"]["auth"]["4xx"] == 2

    def test_snapshot_no_module_errors_when_none(self):
        metrics.increment("requests_total", 1)
        metrics.record_snapshot()
        h = metrics.history()
        assert h[0]["errors_by_module"] == {}

    def test_snapshot_includes_csrf_rejections(self):
        metrics.increment("csrf_rejections", 2)
        metrics.record_snapshot()
        h = metrics.history()
        assert h[0]["csrf_rejections"] == 2

    def test_history_bounded(self):
        for _ in range(70):
            metrics.increment("requests_total")
            metrics.record_snapshot()
        h = metrics.history()
        assert len(h) == 60


class TestRouteModuleDetection:
    """Test the _route_module helper in main.py."""

    def test_auth_module(self):
        from app.main import _route_module
        assert _route_module("/auth/login") == "auth"
        assert _route_module("/auth/session") == "auth"

    def test_jobs_module(self):
        from app.main import _route_module
        assert _route_module("/jobs") == "jobs"
        assert _route_module("/jobs/123") == "jobs"

    def test_admin_module(self):
        from app.main import _route_module
        assert _route_module("/admin/stats") == "admin"
        assert _route_module("/admin/analytics") == "admin"

    def test_unknown_path(self):
        from app.main import _route_module
        assert _route_module("/unknown/path") == "other"
        assert _route_module("/") == "other"

    def test_all_known_modules(self):
        from app.main import _route_module
        assert _route_module("/interview/next") == "interview"
        assert _route_module("/documents/cv") == "documents"
        assert _route_module("/matching/run") == "matching"
        assert _route_module("/scraper/status") == "scraper"
        assert _route_module("/health") == "health"
        assert _route_module("/users/1") == "users"
