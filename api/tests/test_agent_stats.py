"""Tests for agent monitoring endpoints."""

import sqlite3

import pytest

from app.main import app
from app.routes import agent_stats
from app.settings import settings


_TOKEN = "test-agent-token-do-not-use-in-prod"


@pytest.fixture(autouse=True)
def _set_agent_token(monkeypatch):
    monkeypatch.setattr(settings, "AGENT_API_TOKEN", _TOKEN)


@pytest.fixture(autouse=True)
def _force_db_ready(client):
    app.state.db_ready = True
    yield


@pytest.fixture()
def agent_db(tmp_path, monkeypatch):
    db_path = tmp_path / "agent.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE notes (id INTEGER PRIMARY KEY, body TEXT)")
        conn.execute("INSERT INTO notes (body) VALUES ('hello')")
    monkeypatch.setattr(agent_stats, "DB_PATH", db_path)
    return db_path


def _auth():
    return {"Authorization": f"Bearer {_TOKEN}"}


def test_agent_sql_allows_read_only_select(client, agent_db):
    resp = client.post(
        "/agent/sql",
        json={"query": "SELECT id, body FROM notes", "limit": 10},
        headers=_auth(),
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["columns"] == ["id", "body"]
    assert body["rows"] == [[1, "hello"]]


def test_agent_sql_rejects_mutating_query(client, agent_db):
    resp = client.post(
        "/agent/sql",
        json={"query": "DELETE FROM notes WHERE id = 1"},
        headers=_auth(),
    )

    assert resp.status_code == 403

    with sqlite3.connect(agent_db) as conn:
        remaining = conn.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    assert remaining == 1
