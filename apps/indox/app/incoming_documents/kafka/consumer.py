"""Kafka consumer Protocol for the SSE tail + history endpoints.

Mirrors the producer pattern: a thin Protocol with a Fake (in-memory,
backed by the FakeKafkaProducer's published list) and a real
ConfluentKafkaConsumer that lazy-imports `confluent_kafka.Consumer`.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any, Iterator, Protocol, runtime_checkable

from ..core.errors import KafkaUnavailable
from .producer import FakeKafkaProducer, topic_for


@runtime_checkable
class KafkaConsumer(Protocol):
    def tail(
        self,
        *,
        topic: str,
        from_beginning: bool = False,
        timeout_sec: float = 0.5,
    ) -> Iterator[dict[str, Any]]:
        """Yield message payloads (already-decoded dicts) until the
        caller stops iterating. Polls with `timeout_sec` between yields.
        """
        ...

    def history(
        self, *, topic: str, key: str, max_messages: int = 100
    ) -> list[dict[str, Any]]:
        """Return up to `max_messages` historical events whose key
        equals `key`. Best-effort; ordered oldest→newest.
        """
        ...

    def close(self) -> None: ...


class FakeKafkaConsumer:
    """In-memory consumer paired with a FakeKafkaProducer."""

    def __init__(self, producer: FakeKafkaProducer) -> None:
        self._producer = producer
        self._cursors: dict[str, int] = {}

    def tail(
        self,
        *,
        topic: str,
        from_beginning: bool = False,
        timeout_sec: float = 0.5,
    ) -> Iterator[dict[str, Any]]:
        cursor = 0 if from_beginning else len(self._producer.published)
        while True:
            published = self._producer.published
            while cursor < len(published):
                t, _key, payload = published[cursor]
                cursor += 1
                if t == topic:
                    yield payload
            time.sleep(timeout_sec)

    def history(
        self, *, topic: str, key: str, max_messages: int = 100
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for t, k, payload in self._producer.published:
            if t == topic and k == key:
                out.append(payload)
        return out[-max_messages:]

    def close(self) -> None:
        return None


class NullKafkaConsumer:
    def tail(
        self,
        *,
        topic: str,
        from_beginning: bool = False,
        timeout_sec: float = 0.5,
    ) -> Iterator[dict[str, Any]]:
        if False:
            yield {}
        return

    def history(
        self, *, topic: str, key: str, max_messages: int = 100
    ) -> list[dict[str, Any]]:
        return []

    def close(self) -> None:
        return None


class ConfluentKafkaConsumer:
    """Production consumer using `confluent_kafka.Consumer`.

    Each `tail()` call creates a *new* consumer with a unique group id so
    multiple SSE clients tail the same topic independently. `history()`
    seeks to beginning, drains briefly, filters by key, then closes.
    """

    def __init__(self, *, bootstrap_servers: str | None = None) -> None:
        bs = bootstrap_servers or os.getenv("KAFKA_BOOTSTRAP_SERVERS", "")
        if not bs:
            raise KafkaUnavailable("KAFKA_BOOTSTRAP_SERVERS is not set")
        self._bs = bs

    def _new_consumer(self, *, group_suffix: str, from_beginning: bool):
        from confluent_kafka import Consumer  # lazy

        gid = f"incoming-docs-tail-{group_suffix}-{uuid.uuid4().hex[:8]}"
        return Consumer(
            {
                "bootstrap.servers": self._bs,
                "group.id": gid,
                "auto.offset.reset": "earliest" if from_beginning else "latest",
                "enable.auto.commit": False,
            }
        )

    def tail(
        self,
        *,
        topic: str,
        from_beginning: bool = False,
        timeout_sec: float = 0.5,
    ) -> Iterator[dict[str, Any]]:
        c = self._new_consumer(
            group_suffix="tail", from_beginning=from_beginning
        )
        c.subscribe([topic])
        try:
            while True:
                msg = c.poll(timeout_sec)
                if msg is None:
                    continue
                if msg.error():
                    continue
                try:
                    yield json.loads(msg.value().decode("utf-8"))
                except Exception:
                    continue
        finally:
            c.close()

    def history(
        self, *, topic: str, key: str, max_messages: int = 100
    ) -> list[dict[str, Any]]:
        c = self._new_consumer(group_suffix="history", from_beginning=True)
        c.subscribe([topic])
        out: list[dict[str, Any]] = []
        deadline = time.time() + 5.0  # cap the read to 5s
        try:
            while time.time() < deadline and len(out) < max_messages * 4:
                msg = c.poll(0.5)
                if msg is None:
                    break
                if msg.error():
                    continue
                try:
                    if msg.key() and msg.key().decode("utf-8") == key:
                        out.append(json.loads(msg.value().decode("utf-8")))
                except Exception:
                    continue
        finally:
            c.close()
        return out[-max_messages:]

    def close(self) -> None:
        return None


__all__ = [
    "KafkaConsumer",
    "FakeKafkaConsumer",
    "NullKafkaConsumer",
    "ConfluentKafkaConsumer",
    "topic_for",
]
