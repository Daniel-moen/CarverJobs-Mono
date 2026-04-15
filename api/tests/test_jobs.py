"""Tests for /jobs CRUD endpoints."""

_JOB_PAYLOAD = {
    "title": "Chief Stewardess",
    "role": "Stewardess",
    "yacht": "MY Serenity",
    "location": "Monaco",
}


def test_list_jobs_empty(client):
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_job(client):
    resp = client.post("/jobs", json=_JOB_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["title"] == _JOB_PAYLOAD["title"]
    assert "id" in body
    assert "created_at" in body


def test_list_jobs_after_create(client):
    client.post("/jobs", json=_JOB_PAYLOAD)
    resp = client.get("/jobs")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_list_jobs_dedupes_duplicates(client):
    client.post("/jobs", json=_JOB_PAYLOAD)
    client.post("/jobs", json=_JOB_PAYLOAD)

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert len(resp.json()) == 1


def test_get_job(client):
    create = client.post("/jobs", json=_JOB_PAYLOAD)
    job_id = create.json()["id"]
    resp = client.get(f"/jobs/{job_id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == job_id


def test_get_job_not_found(client):
    resp = client.get("/jobs/9999")
    assert resp.status_code == 404


def test_update_job(client):
    create = client.post("/jobs", json=_JOB_PAYLOAD)
    job_id = create.json()["id"]
    resp = client.patch(f"/jobs/{job_id}", json={"title": "Second Stewardess"})
    assert resp.status_code == 200
    assert resp.json()["title"] == "Second Stewardess"


def test_update_job_not_found(client):
    resp = client.patch("/jobs/9999", json={"title": "X"})
    assert resp.status_code == 404


def test_delete_job(client):
    create = client.post("/jobs", json=_JOB_PAYLOAD)
    job_id = create.json()["id"]
    resp = client.delete(f"/jobs/{job_id}")
    assert resp.status_code == 204
    # Confirm it is gone.
    assert client.get(f"/jobs/{job_id}").status_code == 404


def test_delete_job_not_found(client):
    resp = client.delete("/jobs/9999")
    assert resp.status_code == 404


def test_jobs_require_auth(auth_client):
    resp = auth_client.get("/jobs")
    assert resp.status_code == 401
