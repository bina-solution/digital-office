"""Kafka admin Protocol used by the provisioning orchestrator."""
from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable

from ..core.errors import KafkaUnavailable


@runtime_checkable
class KafkaAdmin(Protocol):
    def ensure_topic(
        self, *, name: str, partitions: int, retention_hours: int
    ) -> bool:
        """Return True if the topic was newly created, False if pre-existing."""
        ...

    def delete_topic(self, *, name: str) -> None: ...

    def list_topics(self) -> list[str]: ...


class FakeKafkaAdmin:
    """In-memory Kafka admin for tests."""

    def __init__(self) -> None:
        self.topics: dict[str, dict[str, int]] = {}

    def ensure_topic(
        self, *, name: str, partitions: int, retention_hours: int
    ) -> bool:
        if name in self.topics:
            return False
        self.topics[name] = {
            "partitions": partitions,
            "retention_hours": retention_hours,
        }
        return True

    def delete_topic(self, *, name: str) -> None:
        self.topics.pop(name, None)

    def list_topics(self) -> list[str]:
        return list(self.topics.keys())


class NullKafkaAdmin:
    """No-op admin used when `RepoConfig.kafka.enabled = False`."""

    def ensure_topic(
        self, *, name: str, partitions: int, retention_hours: int
    ) -> bool:
        return False

    def delete_topic(self, *, name: str) -> None:
        return None

    def list_topics(self) -> list[str]:
        return []


class ConfluentKafkaAdmin:
    """Production admin built on `confluent_kafka.admin.AdminClient`.

    Lazy: imports the Kafka client only on construction. Compatible with
    Redpanda since Redpanda exposes the Kafka admin protocol.
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str | None = None,
        replication_factor: int | None = None,
        timeout_sec: float = 10.0,
    ) -> None:
        from confluent_kafka.admin import AdminClient  # lazy

        bs = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
        if not bs:
            raise KafkaUnavailable("KAFKA_BOOTSTRAP_SERVERS is not set")
        self._client = AdminClient({"bootstrap.servers": bs})
        self._rf = (
            replication_factor
            if replication_factor is not None
            else int(os.getenv("KAFKA_REPLICATION_FACTOR", "1"))
        )
        self._timeout = timeout_sec

    def ensure_topic(
        self, *, name: str, partitions: int, retention_hours: int
    ) -> bool:
        from confluent_kafka.admin import NewTopic  # lazy

        existing = set(self.list_topics())
        if name in existing:
            return False
        cfg = {
            "retention.ms": str(retention_hours * 60 * 60 * 1000),
            "cleanup.policy": "delete",
        }
        topic = NewTopic(
            topic=name,
            num_partitions=partitions,
            replication_factor=self._rf,
            config=cfg,
        )
        futures = self._client.create_topics([topic], request_timeout=self._timeout)
        try:
            futures[name].result(timeout=self._timeout)
        except Exception as e:
            # If topic appeared concurrently, treat as pre-existing.
            if "already exists" in str(e).lower():
                return False
            raise KafkaUnavailable(f"create_topics failed: {e}") from e
        return True

    def delete_topic(self, *, name: str) -> None:
        futures = self._client.delete_topics([name], request_timeout=self._timeout)
        try:
            futures[name].result(timeout=self._timeout)
        except Exception as e:
            if "unknown topic" in str(e).lower():
                return
            raise KafkaUnavailable(f"delete_topics failed: {e}") from e

    def list_topics(self) -> list[str]:
        meta = self._client.list_topics(timeout=self._timeout)
        return [t for t in meta.topics.keys() if not t.startswith("__")]
