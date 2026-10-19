"""Tests for the Kafka producer Protocol + Fake + topic naming +
end-to-end publishing through `/documents` PUT."""
from __future__ import annotations

import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core import RepoConfig, RepoRegistry
from incoming_documents.core.models import EventEnvelope
from incoming_documents.kafka.admin import FakeKafkaAdmin
from incoming_documents.kafka.producer import FakeKafkaProducer, topic_for


def test_topic_for_uses_default_prefix(monkeypatch):
    monkeypatch.delenv("INCOMING_DOCS_TOPIC_PREFIX", raising=False)
    assert topic_for("prod_gsheet") == "incoming-documents.prod_gsheet"


def test_topic_for_honours_env_prefix(monkeypatch):
    monkeypatch.setenv("INCOMING_DOCS_TOPIC_PREFIX", "prod-events")
    assert topic_for("r1") == "prod-events.r1"


def test_fake_producer_captures_envelopes_and_uses_id_as_key():
    p = FakeKafkaProducer()
    p.publish(EventEnvelope(repo="r1", event_type="ROW_CREATED", row={"ID": "abc"}))
    p.publish_many(
        [
            EventEnvelope(repo="r1", event_type="ROW_CHANGED", row={"ID": "x", "S": 1}),
            EventEnvelope(repo="r2", event_type="REPO_CREATED", row={}),
        ]
    )
    assert len(p.published) == 3
    assert p.published[0][0] == "incoming-documents.r1"
    assert p.published[0][1] == "abc"  # row.ID used as key
    assert p.published[2][1] != ""  # falls back to event_id when no ID


def test_fake_producer_flush_returns_zero_remaining():
    p = FakeKafkaProducer()
    assert p.flush() == 0
    assert p.flush_count == 1


@pytest.fixture
def app(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = FakeGSheetTransport()
    cache: dict[str, GSheetRepo] = {}
    producer = FakeKafkaProducer()
    admin = FakeKafkaAdmin()

    def factory(cfg):
        if cfg.name not in cache:
            cache[cfg.name] = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
        return cache[cfg.name]

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            registry=reg,
            repo_factory=factory,
            kafka_admin=admin,
            kafka_producer=producer,
            url_prefix="/incomingDocuments",
        )
    )
    app.config.update(TESTING=True, _producer=producer, _admin=admin)
    return app


_REPO = {
    "name": "kafka_repo",
    "backend": "gsheet",
    "primary_key": "ID",
    "columns": [
        {"name": "ID", "type": "string", "nullable": False},
        {"name": "STATUS", "type": "string"},
    ],
    "gsheet": {"sheet_name": "Sheet1"},
}


def test_batch_upsert_publishes_events_and_flushes(app):
    client = app.test_client()
    producer: FakeKafkaProducer = app.config["_producer"]

    r = client.post("/incomingDocuments/repos", json=_REPO)
    assert r.status_code == 201

    r = client.put(
        "/incomingDocuments/repos/kafka_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}, {"ID": "b", "STATUS": "Y"}],
    )
    body = r.get_json()
    assert r.status_code == 200, body
    assert body["stats"]["events_published"] == 2
    assert producer.flush_count == 1
    assert {topic for (topic, _, _) in producer.published} == {
        "incoming-documents.kafka_repo"
    }
    keys = {key for (_, key, _) in producer.published}
    assert keys == {"a", "b"}
    types = {payload["event_type"] for (_, _, payload) in producer.published}
    assert types == {"ROW_CREATED"}


def test_batch_upsert_emits_row_changed_for_updates(app):
    client = app.test_client()
    producer: FakeKafkaProducer = app.config["_producer"]
    client.post("/incomingDocuments/repos", json=_REPO)
    client.put(
        "/incomingDocuments/repos/kafka_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],
    )
    producer.published.clear()
    producer.flush_count = 0

    client.put(
        "/incomingDocuments/repos/kafka_repo/documents",
        json=[{"ID": "a", "STATUS": "Y"}],
    )
    assert len(producer.published) == 1
    assert producer.published[0][2]["event_type"] == "ROW_CHANGED"
    # n8n GSheet-trigger parity: ROW_CHANGED must carry the FULL row.
    row = producer.published[0][2]["row"]
    assert row["ID"] == "a"
    assert row["STATUS"] == "Y"
    assert producer.flush_count == 1


def test_batch_upsert_skips_publish_when_kafka_disabled(app):
    client = app.test_client()
    producer: FakeKafkaProducer = app.config["_producer"]
    body = dict(_REPO)
    body["name"] = "noprod"
    body["kafka"] = {"enabled": False, "partitions": 1, "retention_hours": 1}
    client.post("/incomingDocuments/repos", json=body)
    r = client.put(
        "/incomingDocuments/repos/noprod/documents",
        json=[{"ID": "a"}],
    )
    assert r.get_json()["stats"]["events_published"] == 0
    assert producer.published == []
    assert producer.flush_count == 0


def test_batch_upsert_no_events_when_only_noops(app):
    client = app.test_client()
    producer: FakeKafkaProducer = app.config["_producer"]
    client.post("/incomingDocuments/repos", json=_REPO)
    client.put(
        "/incomingDocuments/repos/kafka_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],
    )
    producer.published.clear()
    producer.flush_count = 0

    client.put(
        "/incomingDocuments/repos/kafka_repo/documents",
        json=[{"ID": "a", "STATUS": "X"}],  # exact same -> noop
    )
    assert producer.published == []
    assert producer.flush_count == 0
