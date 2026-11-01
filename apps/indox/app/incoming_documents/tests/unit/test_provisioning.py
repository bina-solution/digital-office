"""Tests for `core.provisioning.provision_repo` orchestrator.

Verifies the happy path, rollback semantics (only resources newly
created in this call are torn down), and Kafka topic management.
"""
from __future__ import annotations

import pytest

from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core.errors import (
    ProvisioningFailed,
    RepoAlreadyExists,
)
from incoming_documents.core.models import (
    ColumnDef,
    GSheetBackendConfig,
    KafkaConfig,
    RepoConfig,
)
from incoming_documents.core.provisioning import provision_repo
from incoming_documents.core.registry import RepoRegistry
from incoming_documents.core.types import LogicalType
from incoming_documents.kafka.admin import FakeKafkaAdmin


def _cfg(name: str = "r1", *, kafka_enabled: bool = True) -> RepoConfig:
    return RepoConfig(
        name=name,
        backend="gsheet",
        primary_key="ID",
        columns=[
            ColumnDef(name="ID", type=LogicalType.STRING, nullable=False),
            ColumnDef(name="STATUS", type=LogicalType.STRING),
        ],
        gsheet=GSheetBackendConfig(sheet_name="Sheet1"),
        kafka=KafkaConfig(enabled=kafka_enabled, partitions=3, retention_hours=24),
    )


@pytest.fixture
def registry(tmp_path):
    return RepoRegistry(tmp_path / "repos.json")


@pytest.fixture
def transport():
    return FakeGSheetTransport()


@pytest.fixture
def admin():
    return FakeKafkaAdmin()


def _factory(transport: FakeGSheetTransport):
    cache: dict[str, GSheetRepo] = {}

    def make(cfg):
        if cfg.name not in cache:
            cache[cfg.name] = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
        return cache[cfg.name]

    return make, cache


def test_happy_path_creates_storage_topic_and_persists(registry, transport, admin):
    factory, _ = _factory(transport)
    cfg = _cfg()
    out = provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)

    assert out["repo"]["name"] == "r1"
    assert out["provisioned"]["container"]["created"] is True
    # FakeGSheetTransport seeds new spreadsheets with a default "Sheet1" tab,
    # so ensure_table is a no-op when the configured sheet_name matches.
    assert out["provisioned"]["table"]["created"] is False
    assert out["provisioned"]["schema"]["columns_added"] == ["ID", "STATUS"]
    assert out["provisioned"]["kafka_topic_created"] is True
    assert "incoming-documents.r1" in admin.topics

    # Persisted with auto-assigned spreadsheet_id
    persisted = registry.get("r1")
    assert persisted.gsheet is not None
    assert persisted.gsheet.spreadsheet_id is not None
    assert persisted.gsheet.spreadsheet_id in transport._spreadsheets


def test_duplicate_repo_raises_already_exists(registry, transport, admin):
    factory, _ = _factory(transport)
    cfg = _cfg()
    provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)
    with pytest.raises(RepoAlreadyExists):
        provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)


def test_rollback_only_drops_storage_we_created(registry, transport, admin):
    """Pre-existing storage must NOT be torn down on failed provisioning."""
    # Pre-create the spreadsheet by hand
    meta = transport.spreadsheet_create("preexisting")
    sid = meta["spreadsheetId"]

    cfg = _cfg()
    cfg.gsheet.spreadsheet_id = sid  # adopt the pre-existing one
    cfg.gsheet.sheet_name = "new_tab_we_are_creating"

    # Force ensure_table to fail on its addSheet batch update.
    original = transport.spreadsheet_batch_update

    def boom(*a, **kw):
        raise RuntimeError("simulated failure mid-provisioning")

    transport.spreadsheet_batch_update = boom  # type: ignore[assignment]

    factory, _ = _factory(transport)
    with pytest.raises(ProvisioningFailed):
        provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)

    # Restore
    transport.spreadsheet_batch_update = original  # type: ignore[assignment]
    # Pre-existing spreadsheet must still be there
    assert sid in transport._spreadsheets
    # No registry entry
    assert not registry.has("r1")
    # No kafka topic created
    assert "incoming-documents.r1" not in admin.topics


def test_rollback_drops_storage_and_topic_when_we_created_them(
    registry, transport, admin
):
    """If we created storage AND topic and a later step fails, both get rolled back."""
    cfg = _cfg()

    # Make registry.upsert_unsafe blow up to trigger rollback after both
    # storage and topic creation.
    def explode(_cfg):
        raise RuntimeError("disk full")

    registry.upsert_unsafe = explode  # type: ignore[assignment]

    factory, _ = _factory(transport)
    with pytest.raises(ProvisioningFailed):
        provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)

    # Storage we created is gone
    assert transport._spreadsheets == {}
    # Topic we created is gone
    assert admin.topics == {}


def test_kafka_disabled_skips_topic_creation(registry, transport, admin):
    factory, _ = _factory(transport)
    cfg = _cfg(kafka_enabled=False)
    out = provision_repo(cfg, registry=registry, repo_factory=factory, kafka_admin=admin)
    assert out["provisioned"]["kafka_topic_created"] is False
    assert admin.topics == {}
