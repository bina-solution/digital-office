"""Tests for ``poller.sync_repo_once`` — verifies it emits full-row
events on ROW_CHANGED to match n8n Google Sheets Trigger semantics.

The downstream Kafka consumers (the new Kafka-trigger replacement for the
n8n Google Sheets Trigger in ``Incoming Documents 0.1.6``) reference any
column directly (e.g. ``$json.LINK``, ``$json.STATUS``), so the poller must
emit the **complete** post-change row, not just the diff.
"""
from __future__ import annotations

from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core.models import (
    ColumnDef,
    GSheetBackendConfig,
    KafkaConfig,
    RepoConfig,
    RowUpdate,
)
from incoming_documents.core.types import LogicalType
from incoming_documents.kafka.producer import FakeKafkaProducer
from incoming_documents.poller import sync_repo_once


def _cfg() -> RepoConfig:
    return RepoConfig(
        name="poll_repo",
        backend="gsheet",
        primary_key="ID",
        columns=[
            ColumnDef(name="ID", type=LogicalType.STRING, nullable=False),
            ColumnDef(name="NAME", type=LogicalType.STRING),
            ColumnDef(name="STATUS", type=LogicalType.STRING),
        ],
        gsheet=GSheetBackendConfig(
            spreadsheet_title="Test SS",
            sheet_name="Sheet1",
            editors=[],
        ),
        kafka=KafkaConfig(enabled=True),
        active=True,
    )


def test_poller_emits_full_row_on_change(tmp_path):
    cfg = _cfg()
    transport = FakeGSheetTransport()
    repo = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
    repo.ensure_container()
    repo.ensure_table()
    repo.ensure_schema()
    repo.batch_create([
        {"ID": "a", "NAME": "Alice", "STATUS": "INIT"},
    ])

    snapshot_dir = tmp_path / "snap"
    snapshot_dir.mkdir()
    producer = FakeKafkaProducer()

    # First sync: emits ROW_CREATED for the existing row.
    res = sync_repo_once(cfg, repo, snapshot_dir, producer)
    assert res["created"] == 1
    assert res["changed"] == 0
    producer.published.clear()

    # Mutate one column on the existing row via the repo's batch_update path
    # (mirrors how a human / external editor would change a single cell).
    repo.batch_update([RowUpdate(pk="a", changes={"STATUS": "DONE"})])

    res = sync_repo_once(cfg, repo, snapshot_dir, producer)
    assert res["changed"] == 1
    assert len(producer.published) == 1
    payload = producer.published[0][2]
    assert payload["event_type"] == "ROW_CHANGED"
    # Full row must be present, not just the changed column.
    row = payload["row"]
    assert row["ID"] == "a"
    assert row["NAME"] == "Alice"
    assert row["STATUS"] == "DONE"
