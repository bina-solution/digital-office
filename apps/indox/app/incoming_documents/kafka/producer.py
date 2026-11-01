"""Kafka producer for incoming-documents events.

Two implementations behind a thin Protocol so unit tests don't need a
live broker:

* `FakeKafkaProducer` — captures published envelopes in memory.
* `ConfluentKafkaProducer` — production. Uses `confluent_kafka.Producer`
  with `acks=all`, idempotence, and a synchronous `flush()` before any
  HTTP 200 returns to the caller (so we never lose a published event
  on crash).
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional, Protocol, runtime_checkable

from ..core.errors import KafkaUnavailable
from ..core.models import EventEnvelope


_log = logging.getLogger(__name__)


def topic_for(repo_name: str, *, prefix: str | None = None) -> str:
    """Canonical topic name for a repo."""
    base = prefix or os.getenv(
        "INCOMING_DOCS_TOPIC_PREFIX", "incoming-documents"
    )
    return f"{base}.{repo_name}"


@runtime_checkable
class KafkaProducer(Protocol):
    def publish(self, envelope: EventEnvelope) -> None: ...
    def publish_many(self, envelopes: list[EventEnvelope]) -> None: ...
    def flush(self, timeout_sec: float = 10.0) -> int:
        """Returns the number of messages still in queue (0 == fully flushed)."""
        ...

    def close(self) -> None: ...


class FakeKafkaProducer:
    """In-memory producer for tests."""

    def __init__(self, *, prefix: str | None = None) -> None:
        self._prefix = prefix
        self.published: list[tuple[str, str, dict[str, Any]]] = []
        self.flush_count: int = 0

    def publish(self, envelope: EventEnvelope) -> None:
        topic = topic_for(envelope.repo, prefix=self._prefix)
        key = self._key_for(envelope)
        payload = envelope.model_dump(mode="json")
        self.published.append((topic, key, payload))

    def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        for env in envelopes:
            self.publish(env)

    def flush(self, timeout_sec: float = 10.0) -> int:
        self.flush_count += 1
        return 0

    def close(self) -> None:
        return None

    @staticmethod
    def _key_for(envelope: EventEnvelope) -> str:
        # Use the row's ID column when present (n8n-parity primary key
        # name); fall back to the event id.
        for k in ("ID", "id", "Id"):
            if k in envelope.row and envelope.row[k] is not None:
                return str(envelope.row[k])
        return str(envelope.event_id)


class NullKafkaProducer:
    """No-op producer used when Kafka is disabled in config or env."""

    def publish(self, envelope: EventEnvelope) -> None:
        return None

    def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        return None

    def flush(self, timeout_sec: float = 10.0) -> int:
        return 0

    def close(self) -> None:
        return None


class ConfluentKafkaProducer:
    """Production producer wrapping `confluent_kafka.Producer`.

    Configured for at-least-once delivery with idempotence on. Each
    `publish_many` call is followed by a synchronous `flush()` so the
    HTTP request handler can rely on "if the call returned 200, the
    events are durable on the broker".
    """

    def __init__(
        self,
        *,
        bootstrap_servers: str | None = None,
        client_id: str | None = None,
        prefix: str | None = None,
        extra_conf: dict[str, Any] | None = None,
    ) -> None:
        from confluent_kafka import Producer  # lazy

        bs = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
        if not bs:
            raise KafkaUnavailable("KAFKA_BOOTSTRAP_SERVERS is not set")
        conf: dict[str, Any] = {
            "bootstrap.servers": bs,
            "client.id": client_id or os.getenv(
                "KAFKA_CLIENT_ID", "incoming-documents-api"
            ),
            "enable.idempotence": True,
            "acks": "all",
            "compression.type": "gzip",
            "linger.ms": 5,
            "retries": 5,
        }
        if extra_conf:
            conf.update(extra_conf)
        self._producer = Producer(conf)
        self._prefix = prefix
        self._delivery_errors: list[str] = []

    def publish(self, envelope: EventEnvelope) -> None:
        topic = topic_for(envelope.repo, prefix=self._prefix)
        key = FakeKafkaProducer._key_for(envelope)
        payload = json.dumps(envelope.model_dump(mode="json"), ensure_ascii=False)
        try:
            self._producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=payload.encode("utf-8"),
                on_delivery=self._on_delivery,
            )
        except BufferError:
            # Local queue full — drain then retry once.
            self._producer.poll(1.0)
            self._producer.produce(
                topic=topic,
                key=key.encode("utf-8"),
                value=payload.encode("utf-8"),
                on_delivery=self._on_delivery,
            )

    def publish_many(self, envelopes: list[EventEnvelope]) -> None:
        for env in envelopes:
            self.publish(env)

    def flush(self, timeout_sec: float = 10.0) -> int:
        remaining = self._producer.flush(timeout_sec)
        if remaining > 0:
            raise KafkaUnavailable(
                f"flush timed out: {remaining} messages still in queue"
            )
        if self._delivery_errors:
            errs = self._delivery_errors[:]
            self._delivery_errors.clear()
            raise KafkaUnavailable(
                f"delivery failed for {len(errs)} message(s): {errs[0]}"
            )
        return 0

    def close(self) -> None:
        try:
            self._producer.flush(5.0)
        except Exception:  # pragma: no cover - best-effort
            pass

    def _on_delivery(self, err: Any, msg: Any) -> None:  # pragma: no cover
        if err is not None:
            self._delivery_errors.append(str(err))
            _log.warning("kafka delivery failed: %s", err)
