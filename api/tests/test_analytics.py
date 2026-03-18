"""Tests for the analytics ingestion store and admin analytics endpoints."""
from app import analytics
from app.database import SessionLocal
from app.models import AnalyticsEvent


def _reset_analytics():
    """Clear analytics state and DB table between tests."""
    with analytics._lock:
        analytics._page_views.clear()
        analytics._button_clicks.clear()
        analytics._chat_events.clear()
        analytics._event_types.clear()
        analytics._total_events = 0
    db = SessionLocal()
    try:
        db.query(AnalyticsEvent).delete()
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


# ── Unit tests for analytics.py ──────────────────────────────────────────────


class TestAnalyticsStore:
    def setup_method(self):
        _reset_analytics()

    def test_record_page_view(self):
        analytics.record_events([{"type": "page_view", "page": "dashboard", "session_id": "s1"}])
        data = analytics.get_analytics()
        assert data["total_events"] == 1
        assert data["page_views"]["total"] == 1
        assert data["page_views"]["by_page"] == [{"page": "dashboard", "count": 1}]

    def test_record_button_click(self):
        analytics.record_events([
            {"type": "click", "label": "login_password", "session_id": "s1"},
            {"type": "click", "label": "login_password", "session_id": "s1"},
            {"type": "click", "label": "logout", "session_id": "s1"},
        ])
        data = analytics.get_analytics()
        assert data["total_events"] == 3
        assert data["button_clicks"]["total"] == 3
        labels = {e["label"]: e["count"] for e in data["button_clicks"]["by_label"]}
        assert labels["login_password"] == 2
        assert labels["logout"] == 1

    def test_record_chat_events(self):
        analytics.record_events([
            {"type": "chat_send", "session_id": "s1"},
            {"type": "chat_receive", "session_id": "s1"},
            {"type": "chat_send", "session_id": "s1"},
        ])
        data = analytics.get_analytics()
        assert data["chat"]["messages_sent"] == 2
        assert data["chat"]["messages_received"] == 1

    def test_event_types_counted(self):
        analytics.record_events([
            {"type": "page_view", "page": "/", "session_id": "s1"},
            {"type": "click", "label": "btn", "session_id": "s1"},
            {"type": "chat_send", "session_id": "s1"},
        ])
        data = analytics.get_analytics()
        assert data["event_types"]["page_view"] == 1
        assert data["event_types"]["click"] == 1
        assert data["event_types"]["chat_send"] == 1

    def test_batch_returns_count(self):
        count = analytics.record_events([
            {"type": "page_view", "page": "a", "session_id": "s1"},
            {"type": "page_view", "page": "b", "session_id": "s1"},
        ])
        assert count == 2

    def test_events_persisted_to_db(self):
        analytics.record_events([
            {"type": "page_view", "page": "profile", "session_id": "sess1"},
            {"type": "click", "label": "logout", "session_id": "sess1"},
        ])
        db = SessionLocal()
        rows = db.query(AnalyticsEvent).all()
        db.close()
        assert len(rows) == 2
        assert rows[0].session_id == "sess1"
        assert rows[0].event_type == "page_view"
        assert rows[0].page == "profile"
        assert rows[1].event_type == "click"
        assert rows[1].label == "logout"

    def test_top_pages_sorted_by_count(self):
        analytics.record_events([
            {"type": "page_view", "page": "a", "session_id": "s1"},
            {"type": "page_view", "page": "b", "session_id": "s1"},
            {"type": "page_view", "page": "b", "session_id": "s1"},
            {"type": "page_view", "page": "b", "session_id": "s1"},
            {"type": "page_view", "page": "a", "session_id": "s1"},
        ])
        data = analytics.get_analytics()
        pages = data["page_views"]["by_page"]
        assert pages[0]["page"] == "b"
        assert pages[0]["count"] == 3
        assert pages[1]["page"] == "a"
        assert pages[1]["count"] == 2

    def test_empty_analytics(self):
        data = analytics.get_analytics()
        assert data["total_events"] == 0
        assert data["page_views"]["total"] == 0
        assert data["button_clicks"]["total"] == 0
        assert data["chat"]["messages_sent"] == 0


class TestUserFlows:
    def setup_method(self):
        _reset_analytics()

    def test_flows_returns_sessions(self):
        analytics.record_events([
            {"type": "page_view", "page": "auto-apply", "session_id": "aaa"},
            {"type": "page_view", "page": "profile", "session_id": "aaa"},
            {"type": "page_view", "page": "jobs", "session_id": "bbb"},
        ])
        flows = analytics.get_user_flows(limit=10)
        assert len(flows) == 2
        session_ids = {f["session_id"] for f in flows}
        assert "aaa" in session_ids or any(f["session_id"].startswith("aaa") for f in flows)

    def test_flows_contain_page_journey(self):
        analytics.record_events([
            {"type": "page_view", "page": "auto-apply", "session_id": "flow1"},
            {"type": "click", "label": "open_interview", "session_id": "flow1"},
            {"type": "page_view", "page": "profile", "session_id": "flow1"},
            {"type": "page_view", "page": "job-board", "session_id": "flow1"},
        ])
        flows = analytics.get_user_flows(limit=10)
        assert len(flows) == 1
        flow = flows[0]
        assert flow["pages"] == ["auto-apply", "profile", "job-board"]
        assert flow["event_count"] == 4

    def test_page_transitions(self):
        analytics.record_events([
            {"type": "page_view", "page": "auto-apply", "session_id": "t1"},
            {"type": "page_view", "page": "profile", "session_id": "t1"},
            {"type": "page_view", "page": "auto-apply", "session_id": "t2"},
            {"type": "page_view", "page": "profile", "session_id": "t2"},
            {"type": "page_view", "page": "jobs", "session_id": "t2"},
        ])
        transitions = analytics.get_page_transitions()
        trans_map = {(t["from"], t["to"]): t["count"] for t in transitions}
        assert trans_map[("auto-apply", "profile")] == 2
        assert trans_map[("profile", "jobs")] == 1

    def test_transitions_skip_same_page(self):
        analytics.record_events([
            {"type": "page_view", "page": "auto-apply", "session_id": "x1"},
            {"type": "page_view", "page": "auto-apply", "session_id": "x1"},
            {"type": "page_view", "page": "profile", "session_id": "x1"},
        ])
        transitions = analytics.get_page_transitions()
        trans_map = {(t["from"], t["to"]): t["count"] for t in transitions}
        assert ("auto-apply", "auto-apply") not in trans_map
        assert trans_map[("auto-apply", "profile")] == 1

    def test_empty_flows(self):
        flows = analytics.get_user_flows(limit=10)
        assert flows == []

    def test_empty_transitions(self):
        transitions = analytics.get_page_transitions()
        assert transitions == []


# ── Integration tests via API endpoints ──────────────────────────────────────


class TestAnalyticsEndpoints:
    def setup_method(self):
        _reset_analytics()

    def test_post_analytics_batch(self, client):
        resp = client.post("/admin/analytics", json={
            "events": [
                {"type": "page_view", "page": "auto-apply", "session_id": "s1"},
                {"type": "click", "label": "logout", "session_id": "s1"},
            ]
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["ingested"] == 2

    def test_get_analytics_returns_data(self, client):
        client.post("/admin/analytics", json={
            "events": [
                {"type": "page_view", "page": "profile", "session_id": "s1"},
                {"type": "click", "label": "open_interview", "session_id": "s1"},
            ]
        })
        resp = client.get("/admin/analytics")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["total_events"] == 2
        assert body["page_views"]["total"] == 1
        assert body["button_clicks"]["total"] == 1

    def test_get_flows_endpoint(self, client):
        client.post("/admin/analytics", json={
            "events": [
                {"type": "page_view", "page": "auto-apply", "session_id": "f1"},
                {"type": "page_view", "page": "profile", "session_id": "f1"},
                {"type": "page_view", "page": "jobs", "session_id": "f2"},
            ]
        })
        resp = client.get("/admin/analytics/flows")
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert len(body["flows"]) == 2
        assert "transitions" in body

    def test_post_analytics_empty_batch(self, client):
        resp = client.post("/admin/analytics", json={"events": []})
        assert resp.status_code == 200
        assert resp.json()["ingested"] == 0

    def test_post_analytics_is_public(self, auth_client):
        # POST /admin/analytics is intentionally unauthenticated so that
        # pre-login pages (landing, login form) can send analytics events.
        resp = auth_client.post("/admin/analytics", json={
            "events": [{"type": "page_view", "page": "x", "session_id": "s"}]
        })
        assert resp.status_code == 200

    def test_get_analytics_requires_auth(self, auth_client):
        resp = auth_client.get("/admin/analytics")
        assert resp.status_code == 401

    def test_get_flows_requires_auth(self, auth_client):
        resp = auth_client.get("/admin/analytics/flows")
        assert resp.status_code == 401

    def test_stats_includes_errors_by_module(self, client):
        resp = client.get("/admin/stats")
        assert resp.status_code == 200
        body = resp.json()
        assert "errors_by_module" in body
        assert isinstance(body["errors_by_module"], dict)
