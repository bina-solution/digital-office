"""Provisioning orchestrator for `POST /incomingDocuments/repos`.

Sequence per IMPLEMENTATION-PLAN §8 step 8:

    1. ensure_container  ──┐
    2. ensure_table         │ rolled back via teardown(drop_storage=True)
    3. ensure_schema        │ when *we* created the storage in this call
    4. ensure_permissions  ─┘
    5. ensure_topic        ──> rolled back via delete_topic(...) iff *we*
                                  created it in this call
    6. registry.upsert_unsafe (state of record)
    7. publish REPO_CREATED  (best-effort; logged on failure, never blocks)

Rollback ONLY undoes resources that were *newly created in this call*. We
must never destroy a pre-existing spreadsheet, table, or topic.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

from .errors import ProvisioningFailed, RepoAlreadyExists
from .models import (
    ContainerReport,
    PermissionsReport,
    ProvisionReport,
    RepoConfig,
    SchemaReport,
    TableReport,
)
from .registry import RepoRegistry
from .repo import DocumentRepo
from ..kafka.admin import KafkaAdmin, NullKafkaAdmin


_log = logging.getLogger(__name__)


RepoFactory = Callable[[RepoConfig], DocumentRepo]


@dataclass
class _RollbackState:
    storage_created: bool = False
    topic_created: bool = False


def _topic_name(cfg: RepoConfig) -> str:
    return f"incoming-documents.{cfg.name}"


def provision_repo(
    config: RepoConfig,
    *,
    registry: RepoRegistry,
    repo_factory: RepoFactory,
    kafka_admin: KafkaAdmin | None = None,
) -> dict[str, Any]:
    """Provision storage + topic + register `config`. Idempotent.

    Returns a dict with the persisted `RepoConfig` and the per-step
    `ProvisionReport`. Raises `ProvisioningFailed` on irrecoverable
    errors after attempting rollback of resources we created.
    """
    admin: KafkaAdmin = kafka_admin or NullKafkaAdmin()
    if registry.has(config.name):
        raise RepoAlreadyExists(f"repo '{config.name}' already exists")

    repo = repo_factory(config)
    state = _RollbackState()
    container: ContainerReport | None = None
    table: TableReport | None = None
    schema: SchemaReport | None = None
    perms: PermissionsReport | None = None
    topic_created = False

    try:
        container = repo.ensure_container()
        if container.created:
            state.storage_created = True
        table = repo.ensure_table()
        if table.created:
            state.storage_created = True
        schema = repo.ensure_schema()
        perms = repo.ensure_permissions()

        if config.kafka.enabled:
            topic_created = admin.ensure_topic(
                name=_topic_name(config),
                partitions=config.kafka.partitions,
                retention_hours=config.kafka.retention_hours,
            )
            state.topic_created = topic_created

        # Persist the (possibly mutated) config — gsheet provisioning fills
        # in `gsheet.spreadsheet_id` / `gsheet.gid`.
        persisted = registry.upsert_unsafe(config)

    except Exception as e:
        _log.warning("provision_repo failed for %s: %s — rolling back", config.name, e)
        _rollback(repo, admin, config, state)
        if isinstance(e, ProvisioningFailed):
            raise
        raise ProvisioningFailed(
            f"provisioning failed for '{config.name}': {e}"
        ) from e

    report = ProvisionReport(
        container=container,
        table=table,
        schema=schema,  # type: ignore[call-arg]  # aliased field
        permissions=perms,
        kafka_topic_created=topic_created,
    )
    return {
        "repo": persisted.model_dump(mode="json", by_alias=True),
        "provisioned": report.model_dump(mode="json", by_alias=True),
    }


def _rollback(
    repo: DocumentRepo,
    admin: KafkaAdmin,
    config: RepoConfig,
    state: _RollbackState,
) -> None:
    if state.topic_created:
        try:
            admin.delete_topic(name=_topic_name(config))
        except Exception:  # pragma: no cover - best-effort
            _log.exception("rollback: delete_topic failed for %s", config.name)
    if state.storage_created:
        try:
            repo.teardown(drop_storage=True)
        except Exception:  # pragma: no cover - best-effort
            _log.exception("rollback: teardown failed for %s", config.name)
