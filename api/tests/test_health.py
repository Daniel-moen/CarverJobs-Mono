"""Tests for GET /health and GET /status/services."""


def test_root_liveness(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["service"] == "api"


def test_health_liveness(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["service"] == "api"


def test_status_services_requires_auth(auth_client):
    """Without a valid session the endpoint must return 401."""
    resp = auth_client.get("/status/services")
    assert resp.status_code == 401


def test_status_services_with_auth(client):
    resp = client.get("/status/services")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert "services" in body
    assert "api" in body["services"]
    # Every service entry must have the required keys including history.
    for _name, info in body["services"].items():
        assert "connected" in info
        assert "checked_at" in info
        assert "history" in info
        assert isinstance(info["history"], list)
        # Each history entry must have connected + checked_at.
        for entry in info["history"]:
            assert "connected" in entry
            assert "checked_at" in entry


def test_status_services_api_always_connected(client):
    resp = client.get("/status/services")
    assert resp.status_code == 200
    services = resp.json()["services"]
    assert services["api"]["connected"] is True


def test_cors_preflight_allows_requested_headers(client):
    origin = "https://jobcarver.co"
    resp = client.options(
        "/auth/login",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "Content-Type,X-Requested-With,X-Custom-Header",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == origin
    allow_headers = (resp.headers.get("access-control-allow-headers") or "").lower()
    assert "x-custom-header" in allow_headers
