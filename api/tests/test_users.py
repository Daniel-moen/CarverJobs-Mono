"""Tests for /users CRUD endpoints."""

_USER_PAYLOAD = {
    "email": "alice@example.com",
    "full_name": "Alice Smith",
    "password": "strongpassword123",
}


def test_list_users_empty(client):
    resp = client.get("/users")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_user(client):
    resp = client.post("/users", json=_USER_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == _USER_PAYLOAD["email"]
    assert body["full_name"] == _USER_PAYLOAD["full_name"]
    assert "id" in body
    # Password must never appear in the response.
    assert "password" not in body
    assert "password_hash" not in body


def test_create_user_duplicate_email(client):
    client.post("/users", json=_USER_PAYLOAD)
    resp = client.post("/users", json=_USER_PAYLOAD)
    assert resp.status_code == 409


def test_list_users_after_create(client):
    client.post("/users", json=_USER_PAYLOAD)
    resp = client.get("/users")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_user(client):
    create = client.post("/users", json=_USER_PAYLOAD)
    user_id = create.json()["id"]
    resp = client.get(f"/users/{user_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id


def test_get_user_not_found(client):
    resp = client.get("/users/9999")
    assert resp.status_code == 404


def test_update_user(client):
    create = client.post("/users", json=_USER_PAYLOAD)
    user_id = create.json()["id"]
    resp = client.patch(f"/users/{user_id}", json={"full_name": "Alice Jones"})
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Alice Jones"


def test_update_user_password(client):
    """Updating the password must succeed and not expose the hash."""
    create = client.post("/users", json=_USER_PAYLOAD)
    user_id = create.json()["id"]
    resp = client.patch(f"/users/{user_id}", json={"password": "newpassword456"})
    assert resp.status_code == 200
    assert "password" not in resp.json()


def test_update_user_not_found(client):
    resp = client.patch("/users/9999", json={"full_name": "X"})
    assert resp.status_code == 404


def test_delete_user(client):
    create = client.post("/users", json=_USER_PAYLOAD)
    user_id = create.json()["id"]
    resp = client.delete(f"/users/{user_id}")
    assert resp.status_code == 204
    assert client.get(f"/users/{user_id}").status_code == 404


def test_delete_user_not_found(client):
    resp = client.delete("/users/9999")
    assert resp.status_code == 404


def test_users_require_auth(auth_client):
    resp = auth_client.get("/users")
    assert resp.status_code == 401
