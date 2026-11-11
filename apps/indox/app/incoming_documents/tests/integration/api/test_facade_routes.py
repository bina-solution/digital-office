"""Tests for the Step 12 facade + Step 13 SSE endpoints."""
from __future__ import annotations

import json

import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core import RepoRegistry
from incoming_documents.kafka.admin import FakeKafkaAdmin
from incoming_documents.kafka.consumer import FakeKafkaConsumer
from incoming_documents.kafka.producer import FakeKafkaProducer


_REPO = {
    "name": "facade_repo",
    "backend": "gsheet",
    "primary_key": "ID",
    "columns": [
        {"name": "ID", "type": "string", "nullable": False},
        {"name": "STATUS", "type": "string"},
    ],
    "gsheet": {"sheet_name": "Sheet1"},
}


@pytest.fixture
def app(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = FakeGSheetTransport()
    cache: dict[str, GSheetRepo] = {}
    producer = FakeKafkaProducer()
    consumer = FakeKafkaConsumer(producer)

    def factory(cfg):
        if cfg.name not in cache:
            cache[cfg.name] = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
        return cache[cfg.name]

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            registry=reg,
            repo_factory=factory,
            kafka_admin=FakeKafkaAdmin(),
            kafka_producer=producer,
            kafka_consumer=consumer,
            url_prefix="/incomingDocuments",
        )
    )
    app.config.update(TESTING=True, _producer=producer, _consumer=consumer)
    return app


def _create_repo(client):
    r = client.post("/incomingDocuments/repos", json=_REPO)
    assert r.status_code == 201, r.get_json()


def test_openapi_spec_lists_all_routes(app):
    client = app.test_client()
    r = client.get("/incomingDocuments/openapi.json")
    assert r.status_code == 200
    spec = r.get_json()
    assert spec["openapi"].startswith("3.")
    paths = set(spec["paths"].keys())
    for required in [
        "/health",
        "/auth/me",
        "/repos",
        "/repos/{repo}",
        "/repos/{repo}/stats",
        "/repos/{repo}/documents",
        "/repos/{repo}/documents/query",
        "/repos/{repo}/documents/{id}",
        "/repos/{repo}/documents/{id}/history",
    ]:
        assert required in paths, f"missing path {required}"
    # the kafka tail went in the final release (9df84f270, «dead routes gone»); the spec must not promise it
    assert "/repos/{repo}/kafka/tail" not in paths


def test_auth_me_unauthenticated(app):
    r = app.test_client().get("/incomingDocuments/auth/me")
    assert r.status_code == 200
    body = r.get_json()
    assert body["authenticated"] is False
    assert body["username"] is None
    assert body["groups"] == []
    assert body["is_admin"] is False


def test_auth_me_parses_authentik_headers(app):
    r = app.test_client().get(
        "/incomingDocuments/auth/me",
        headers={
            "X-authentik-username": "alice",
            "X-authentik-email": "alice@example.com",
            "X-authentik-groups": "users|incoming-docs-admin|other",
        },
    )
    body = r.get_json()
    assert body["authenticated"] is True
    assert body["username"] == "alice"
    assert body["email"] == "alice@example.com"
    assert body["groups"] == ["users", "incoming-docs-admin", "other"]
    assert body["is_admin"] is True


def test_repo_stats_returns_row_count_and_columns(app):
    client = app.test_client()
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/facade_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}, {"ID": "b", "STATUS": "Y"}],
    )
    r = client.get("/incomingDocuments/repos/facade_repo/stats")
    assert r.status_code == 200
    body = r.get_json()
    assert body["row_count"] == 2
    assert body["backend"] == "gsheet"
    assert body["kafka_enabled"] is True
    assert {c["name"] for c in body["columns"]} == {"ID", "STATUS"}


def test_get_single_document(app):
    client = app.test_client()
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/facade_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],
    )
    r = client.get("/incomingDocuments/repos/facade_repo/documents/a")
    assert r.status_code == 200
    body = r.get_json()
    assert body["row"]["ID"] == "a"
    assert body["row"]["STATUS"] == "X"


def test_get_single_document_404(app):
    client = app.test_client()
    _create_repo(client)
    r = client.get("/incomingDocuments/repos/facade_repo/documents/nope")
    assert r.status_code == 404


def test_patch_document_updates_existing_row(app):
    client = app.test_client()
    producer: FakeKafkaProducer = app.config["_producer"]
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/facade_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],
    )
    producer.published.clear()

    r = client.patch(
        "/incomingDocuments/repos/facade_repo/documents/a",
        json={"STATUS": "DONE"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["updated"]) == 1
    assert body["events_published"] == 1
    last_event = producer.published[-1][2]
    assert last_event["event_type"] == "ROW_CHANGED"
    # n8n GSheet-trigger parity: ROW_CHANGED must carry the FULL post-write
    # row (not just the changed columns), so downstream Kafka-trigger
    # consumers can reference any column directly.
    assert last_event["row"]["ID"] == "a"
    assert last_event["row"]["STATUS"] == "DONE"
    # The pre-existing column from the initial create must still be present
    # even though the PATCH only sent STATUS.
    assert "ID" in last_event["row"] and "STATUS" in last_event["row"]

    # confirm it stuck
    g = client.get("/incomingDocuments/repos/facade_repo/documents/a").get_json()
    assert g["row"]["STATUS"] == "DONE"


def test_patch_document_creates_when_missing(app):
    client = app.test_client()
    _create_repo(client)
    r = client.patch(
        "/incomingDocuments/repos/facade_repo/documents/new1",
        json={"STATUS": "FRESH"},
    )
    assert r.status_code == 200
    body = r.get_json()
    assert len(body["created"]) == 1
    g = client.get("/incomingDocuments/repos/facade_repo/documents/new1")
    assert g.get_json()["row"]["STATUS"] == "FRESH"


def test_document_history_returns_events_keyed_by_id(app):
    client = app.test_client()
    _create_repo(client)
    client.put(
        "/incomingDocuments/repos/facade_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],
    )
    client.patch(
        "/incomingDocuments/repos/facade_repo/documents/a",
        json={"STATUS": "Y"},
    )
    r = client.get("/incomingDocuments/repos/facade_repo/documents/a/history")
    assert r.status_code == 200
    events = r.get_json()["events"]
    assert len(events) == 2
    assert {e["event_type"] for e in events} == {"ROW_CREATED", "ROW_CHANGED"}


def test_document_history_empty_when_kafka_disabled(app):
    client = app.test_client()
    body = dict(_REPO)
    body["name"] = "no_kafka"
    body["kafka"] = {"enabled": False, "partitions": 1, "retention_hours": 1}
    client.post("/incomingDocuments/repos", json=body)
    r = client.get("/incomingDocuments/repos/no_kafka/documents/anything/history")
    assert r.status_code == 200
    assert r.get_json()["events"] == []


def test_the_kafka_tail_is_gone(app):
    """The SSE kafka tail was removed in the final release (9df84f270, «dead routes gone»; nothing in the repo
    calls it). Its two tests — a ready frame, and 400 with kafka off — kept failing on every tree; what holds now is
    that the route does not answer."""
    client = app.test_client()
    _create_repo(client)
    r = client.get("/incomingDocuments/repos/facade_repo/kafka/tail?from_beginning=true")
    assert r.status_code == 404
