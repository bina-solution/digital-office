"""`DocumentRepo` Protocol and a tiny in-memory implementation used by
unit tests so the diff engine can be wired end-to-end without any I/O.
"""
from __future__ import annotations

from typing import Any, Protocol

from .models import (
    ContainerReport,
    PermissionsReport,
    Query,
    RepoConfig,
    RowUpdate,
    SchemaReport,
    TableReport,
    UpsertMatchRule,
)


class DocumentRepo(Protocol):
    config: RepoConfig

    # ---- provisioning ----
    def ensure_container(self) -> ContainerReport: ...
    def ensure_table(self) -> TableReport: ...
    def ensure_schema(self) -> SchemaReport: ...
    def ensure_permissions(self) -> PermissionsReport: ...
    def teardown(self, *, drop_storage: bool) -> None: ...

    # ---- runtime ----
    def get_columns(self) -> list[str]: ...
    def fetch_all(self, *, columns: list[str] | None = None) -> list[dict[str, Any]]: ...
    def fetch_by_ids(
        self, ids: list[str], *, columns: list[str] | None = None
    ) -> list[dict[str, Any]]: ...
    def fetch_by_match_rules(
        self,
        items: list[dict[str, Any]],
        rules: list[UpsertMatchRule],
        *,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...
    def query(self, q: Query) -> list[dict[str, Any]]: ...
    def batch_update(self, updates: list[RowUpdate]) -> list[dict[str, Any]]: ...
    def batch_create(self, creates: list[dict[str, Any]]) -> list[dict[str, Any]]: ...


class InMemoryRepo:
    """Minimal Protocol-conforming repo used in unit tests."""

    def __init__(self, config: RepoConfig, rows: list[dict[str, Any]] | None = None):
        self.config = config
        self._rows: dict[str, dict[str, Any]] = {}
        for r in rows or []:
            pk = r.get(config.primary_key)
            if pk is not None:
                self._rows[str(pk)] = dict(r)

    # provisioning is a no-op for the in-memory backend
    def ensure_container(self) -> ContainerReport:
        return ContainerReport(created=False, identifier="memory")

    def ensure_table(self) -> TableReport:
        return TableReport(created=False, identifier="memory")

    def ensure_schema(self) -> SchemaReport:
        return SchemaReport()

    def ensure_permissions(self) -> PermissionsReport:
        return PermissionsReport()

    def teardown(self, *, drop_storage: bool) -> None:
        if drop_storage:
            self._rows.clear()

    def get_columns(self) -> list[str]:
        return [c.name for c in self.config.columns]

    def fetch_all(self, *, columns: list[str] | None = None) -> list[dict[str, Any]]:
        return [self._project(r, columns) for r in self._rows.values()]

    def fetch_by_ids(
        self, ids: list[str], *, columns: list[str] | None = None
    ) -> list[dict[str, Any]]:
        return [
            self._project(self._rows[i], columns) for i in ids if i in self._rows
        ]

    def fetch_by_match_rules(
        self,
        items: list[dict[str, Any]],
        rules: list[UpsertMatchRule],
        *,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if not rules or not items:
            return []
        match_sets: list[set[tuple]] = [set() for _ in rules]
        for item in items:
            for i, rule in enumerate(rules):
                if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                    match_sets[i].add(tuple(str(item[c]) for c in rule.columns))
        if not any(match_sets):
            return []
        pk = self.config.primary_key
        seen_pks: set[str] = set()
        out: list[dict[str, Any]] = []
        for row in self._rows.values():
            for i, rule in enumerate(rules):
                if not match_sets[i]:
                    continue
                row_vals = tuple(str(row.get(c, "")) for c in rule.columns)
                if row_vals in match_sets[i]:
                    pk_v = str(row.get(pk, ""))
                    if pk_v not in seen_pks:
                        seen_pks.add(pk_v)
                        out.append(self._project(row, columns))
                    break
        return out

    def query(self, q: Query) -> list[dict[str, Any]]:
        if q.mode in ("single", "by_ids"):
            return self.fetch_by_ids(q.ids or [], columns=q.select)
        return self.fetch_all(columns=q.select)[q.offset : q.offset + q.limit]

    def batch_update(self, updates: list[RowUpdate]) -> list[dict[str, Any]]:
        out = []
        for u in updates:
            row = self._rows.get(u.pk)
            if row is None:
                continue
            row.update(u.changes)
            out.append({"pk": u.pk, "changedColumns": list(u.changes.keys())})
        return out

    def batch_create(self, creates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for r in creates:
            pk = r.get(self.config.primary_key)
            if pk is None:
                continue
            self._rows[str(pk)] = dict(r)
            out.append({"pk": str(pk)})
        return out

    @staticmethod
    def _project(row: dict[str, Any], columns: list[str] | None) -> dict[str, Any]:
        if columns is None:
            return dict(row)
        return {k: row.get(k) for k in columns}
