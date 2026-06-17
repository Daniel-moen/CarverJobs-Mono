"""Tests for /jobs CRUD endpoints."""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import crud, models
from app.database import Base

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


# ── crud.list_jobs: status filter + cap ─────────────────────────────────────


def _crud_session():
    """Isolated in-memory DB session for unit-testing crud.list_jobs directly."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)()


def _add_job(db, title, status="open"):
    db.add(models.Job(title=title, role="Deckhand", yacht="MY Test", location="Nice", status=status))


def test_list_jobs_excludes_expired_by_default():
    db = _crud_session()
    _add_job(db, "Active")
    _add_job(db, "Stale", status="expired")  # set by Worker 2's retention scan
    db.commit()

    jobs = crud.list_jobs(db)

    assert {j.title for j in jobs} == {"Active"}


def test_list_jobs_include_inactive_returns_expired():
    db = _crud_session()
    _add_job(db, "Active")
    _add_job(db, "Stale", status="expired")
    db.commit()

    jobs = crud.list_jobs(db, include_inactive=True)

    assert {j.title for j in jobs} == {"Active", "Stale"}


def test_list_jobs_excludes_all_inactive_statuses():
    db = _crud_session()
    _add_job(db, "Active")
    for i, bad in enumerate(crud.INACTIVE_JOB_STATUSES):
        _add_job(db, f"Inactive{i}", status=bad)
    db.commit()

    jobs = crud.list_jobs(db)

    assert {j.title for j in jobs} == {"Active"}


def test_list_jobs_caps_results():
    db = _crud_session()
    for i in range(5):
        _add_job(db, f"Job{i}")
    db.commit()

    jobs = crud.list_jobs(db, limit=2)

    assert len(jobs) == 2


def test_list_jobs_route_excludes_inactive_for_admin_by_default(client):
    create = client.post("/jobs", json=_JOB_PAYLOAD)
    job_id = create.json()["id"]
    # "closed" is a client-settable inactive status (PATCH validates against the schema).
    client.patch(f"/jobs/{job_id}", json={"status": "closed"})

    resp = client.get("/jobs")

    assert resp.status_code == 200
    assert resp.json() == []


def test_list_jobs_route_include_inactive_for_admin(client):
    create = client.post("/jobs", json=_JOB_PAYLOAD)
    job_id = create.json()["id"]
    client.patch(f"/jobs/{job_id}", json={"status": "closed"})

    resp = client.get("/jobs", params={"include_inactive": "true"})

    assert resp.status_code == 200
    assert len(resp.json()) == 1
