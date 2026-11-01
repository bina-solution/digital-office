"""End-to-end blueprint tests against a Flask test client.

Uses a shared FakeGSheetTransport so a single in-memory backend serves
every repo created during the tests.
"""
from __future__ import annotations

import os

import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core import RepoConfig, RepoRegistry


_PROD_REPO = {
    "name": "prod_gsheet",
    "backend": "gsheet",
    "primary_key": "ID",
    "columns": [
        {"name": "ID", "type": "string", "nullable": False},
        {"name": "STATUS", "type": "string"},
        {"name": "DOC_TOTAL_AMOUNT", "type": "numeric"},
        {"name": "ACTIVE", "type": "bool"},
        {"name": "DOC_DATE", "type": "date"},
    ],
    "priority_sync_columns": ["EX_INVOICE_ID"],
    "gsheet": {
        "sheet_name": "מסמכים נכנסים",
        "editors": ["alice@example.com"],
    },
}


@pytest.fixture
def transport():
    return FakeGSheetTransport()


@pytest.fixture
def app(tmp_path, transport):
    reg = RepoRegistry(tmp_path / "repos.json")

    # Per-config repo cache so successive route calls hit the same in-memory
    # GSheetRepo (and therefore the same provisioned spreadsheet).
    cache: dict[str, GSheetRepo] = {}

    def factory(cfg: RepoConfig) -> GSheetRepo:
        if cfg.name not in cache:
            repo = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
            repo.ensure_container()
            repo.ensure_table()
            repo.ensure_schema()
            cache[cfg.name] = repo
        return cache[cfg.name]

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(registry=reg, repo_factory=factory, url_prefix="/incomingDocuments")
    )
    app.config.update(TESTING=True)
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def _create_repo(client) -> dict:
    r = client.post("/incomingDocuments/repos", json=_PROD_REPO)
    assert r.status_code == 201, r.get_json()
    return r.get_json()["repo"]


# ---------- /health + /repos CRUD ----------


def test_health_ok(client):
    r = client.get("/incomingDocuments/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_repo_lifecycle(client):
    assert client.get("/incomingDocuments/repos").get_json() == {
        "success": True,
        "repos": [],
    }
    _create_repo(client)
    listed = client.get("/incomingDocuments/repos").get_json()
    assert len(listed["repos"]) == 1
    g = client.get("/incomingDocuments/repos/prod_gsheet").get_json()
    assert g["repo"]["backend"] == "gsheet"
    d = client.delete("/incomingDocuments/repos/prod_gsheet")
    assert d.status_code == 200


def test_get_unknown_repo_returns_404(client):
    r = client.get("/incomingDocuments/repos/missing")
    assert r.status_code == 404
    body = r.get_json()
    assert body["error"] == "repo_not_found"
    assert body["success"] is False


def test_create_repo_validation_error(client):
    r = client.post("/incomingDocuments/repos", json={"name": "bad"})
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_error"


def test_create_repo_duplicate_returns_409(client):
    _create_repo(client)
    r = client.post("/incomingDocuments/repos", json=_PROD_REPO)
    assert r.status_code == 409
    assert r.get_json()["error"] == "repo_already_exists"


# ---------- /documents PUT ----------


def test_batch_upsert_creates_then_updates(client):
    _create_repo(client)
    r = client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[
            {"ID": "abc-1", "STATUS": "PENDING"},
            {"ID": "abc-2", "STATUS": "DONE", "DOC_TOTAL_AMOUNT": "10"},
        ],
    )
    assert r.status_code == 200
    body = r.get_json()
    assert body["stats"] == {
        "incoming": 2, "updated": 0, "created": 2, "noop": 0, "events_published": 2
    }

    r2 = client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[
            {"ID": "abc-1", "STATUS": "DONE"},
            {"ID": "abc-2", "STATUS": "DONE", "DOC_TOTAL_AMOUNT": "10"},
            {"ID": "abc-3", "STATUS": "NEW"},
        ],
    )
    body2 = r2.get_json()
    assert body2["stats"] == {
        "incoming": 3, "updated": 1, "created": 1, "noop": 1, "events_published": 2
    }
    assert body2["updated"][0]["pk"] == "abc-1"


def test_batch_upsert_rejects_non_array_body(client):
    _create_repo(client)
    r = client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json={"ID": "abc"},
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_error"


def test_batch_upsert_enforces_max_batch_size(client, monkeypatch):
    monkeypatch.setenv("INCOMING_DOCS_MAX_BATCH_SIZE", "3")
    _create_repo(client)
    r = client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[{"ID": f"a-{i}"} for i in range(5)],
    )
    assert r.status_code == 413
    assert r.get_json()["error"] == "batch_too_large"


def test_batch_upsert_priority_sync_rule_applied(client, transport):
    _create_repo(client)
    r = client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[{"ID": "abc-9", "STATUS": "NEW", "EX_INVOICE_ID": "X"}],
    )
    assert r.status_code == 200
    # priority_sync should be present on the created row even though
    # it isn't a declared column (n8n parity).
    q = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "by_ids", "ids": ["abc-9"]},
    )
    body = q.get_json()
    assert body["count"] == 1


# ---------- /documents/query ----------


def test_query_modes(client):
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[
            {"ID": "a", "STATUS": "X"},
            {"ID": "b", "STATUS": "Y"},
            {"ID": "c", "STATUS": "X"},
        ],
    )

    r = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "all"},
    )
    body = r.get_json()
    assert body["count"] == 3 and body["truncated"] is False

    r = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "filter", "filter": {"STATUS": "X"}},
    )
    body = r.get_json()
    assert {row["ID"] for row in body["rows"]} == {"a", "c"}

    r = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "by_ids", "ids": ["b"]},
    )
    body = r.get_json()
    assert body["count"] == 1 and body["rows"][0]["ID"] == "b"


def test_query_pagination(client):
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/prod_gsheet/documents",
        json=[{"ID": f"id-{i:03d}"} for i in range(5)],
    )
    r1 = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "all", "limit": 2, "offset": 0},
    )
    b1 = r1.get_json()
    assert b1["count"] == 2 and b1["truncated"] is True and b1["next_offset"] == 2
    r2 = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "all", "limit": 2, "offset": b1["next_offset"]},
    )
    b2 = r2.get_json()
    assert b2["count"] == 2 and b2["truncated"] is True and b2["next_offset"] == 4
    r3 = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "all", "limit": 2, "offset": b2["next_offset"]},
    )
    b3 = r3.get_json()
    assert b3["count"] == 1 and b3["truncated"] is False


def test_query_validation_error(client):
    _create_repo(client)
    r = client.post(
        "/incomingDocuments/repos/prod_gsheet/documents/query",
        json={"mode": "by_ids"},  # missing ids
    )
    assert r.status_code == 400
    assert r.get_json()["error"] == "validation_error"
