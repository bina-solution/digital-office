"""`SupabaseRepo` — `DocumentRepo` over a Supabase / PostgREST table.

Runtime path: PostgREST `select` + atomic `upsert` (resolution=merge-duplicates).
Provisioning path: `create schema` → `create table` → additive `add column` →
unique index on PK. Mirrors `GSheetRepo` semantics so the diff engine, the
HTTP routes and the tests treat both backends uniformly.
"""
from __future__ import annotations

from typing import Any, Optional

from ..core.errors import (
    BackendUnavailable,
    ProvisioningFailed,
    ValidationError,
)
from ..core.models import (
    ContainerReport,
    PermissionsReport,
    Query,
    RepoConfig,
    RowUpdate,
    SchemaReport,
    SupabaseBackendConfig,
    TableReport,
    UpsertMatchRule,
)
from ..core.types import LogicalType, PG_DDL, normalize_value
from .supabase_transport import FakeSupabaseTransport, SupabaseTransport


#: THE DEFAULT READING ORDER FOR A DOCUMENT TABLE: newest first.
#:
#: The question a person opens this table with is "what just came in", so an unordered read is
#: never the useful answer — and PostgREST without an ORDER BY returns rows in whatever order the
#: planner produced, which is not even stable between two identical requests.
#:
#: It lives HERE, in the query layer, rather than in the grid: every consumer — the documents
#: screen, an export, a direct `POST /documents/query` — then gets the same sane default without
#: each one remembering to ask, and a caller that DOES pass `order` still wins outright.
#:
#: `created_at` (not a business date): it is the row's own arrival instant, monotonic and always
#: present, whereas DOC_DATE is the document's printed date — frequently missing, occasionally a
#: 2094 typo, and stored as text in mixed formats, so sorting on it would put OCR errors on top.
_DEFAULT_ORDER: tuple[tuple[str, str], ...] = (("created_at", "desc"),)

#: LAWS THE OWNER ABOLISHED STAY DEAD — enforced here, not by operator discipline.
#:
#: 2026-08-17 the owner retired the unique-HASH / COMPANY_ID+COMPANY_DOC_ID dedup
#: constraints ("the dedup ACTION owns dedup") and the COMPANY_DOC_ID column ("DOC_ID
#: is the one canonical doc number"). They were dropped from the live table and the
#: fixture — but survived as DECLARATIONS in the repo registry, and on 2026-08-24
#: provisioning a NEW table (the archive) faithfully re-materialised them:
#: `ux_incoming_documents_archive_HASH` then aborted a 15,364-row archive move on the
#: first legitimate duplicate hash. Every table passes through ensure_table /
#: ensure_schema, so the refusal lives here: whatever a config file says, these are
#: never created again. Skips are logged loudly, never silent.
_RETIRED_UNIQUE_INDEXES: frozenset[tuple[str, ...]] = frozenset({
    ("HASH",), ("COMPANY_ID", "COMPANY_DOC_ID"),
})
_RETIRED_COLUMNS: frozenset[str] = frozenset({"COMPANY_DOC_ID"})


class SupabaseRepo:
    """`DocumentRepo` implementation backed by Supabase / PostgREST."""

    def __init__(
        self,
        config: RepoConfig,
        transport: SupabaseTransport | None = None,
    ) -> None:
        if config.backend != "supabase":
            raise ValidationError(
                f"SupabaseRepo cannot serve backend='{config.backend}'"
            )
        if config.supabase is None:
            raise ValidationError("RepoConfig.supabase is required")
        self.config = config
        self.sb: SupabaseBackendConfig = config.supabase
        self.transport: SupabaseTransport = transport or FakeSupabaseTransport()

    # ---------- helpers ----------

    @property
    def schema(self) -> str:
        return self.sb.schema_

    @property
    def table(self) -> str:
        return self.sb.table

    def _column_type(self, name: str) -> LogicalType:
        for c in self.config.columns:
            if c.name == name:
                return c.type
        return LogicalType.STRING

    def _coerce_for_write(self, row: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in row.items():
            if v is None:
                out[k] = None
                continue
            t = self._column_type(k)
            n = normalize_value(v, t)
            # Decimal must be JSON-serialisable; PostgREST accepts numeric strings.
            if t is LogicalType.NUMERIC and n is not None:
                out[k] = str(n)
            elif t is LogicalType.DATE and n is not None:
                out[k] = str(n)
            elif t is LogicalType.TIMESTAMP and n is not None:
                out[k] = str(n)
            else:
                out[k] = n
        return out

    # ---------- provisioning ----------

    def ensure_container(self) -> ContainerReport:
        # "container" for Supabase = the schema. Idempotent.
        try:
            self.transport.create_schema(schema=self.schema)
        except Exception as e:
            raise ProvisioningFailed(
                f"failed to ensure schema '{self.schema}': {e}"
            ) from e
        return ContainerReport(created=False, identifier=self.schema)

    def ensure_table(self) -> TableReport:
        existing = set(self.transport.list_tables(schema=self.schema))
        if self.table in existing:
            return TableReport(created=False, identifier=f"{self.schema}.{self.table}")

        if not self.config.columns:
            raise ValidationError("ensure_table requires RepoConfig.columns")
        col_specs: list[tuple[str, str, bool]] = []
        for c in self.config.columns:
            if c.name in _RETIRED_COLUMNS:
                import logging
                logging.getLogger(__name__).warning(
                    "ensure_table: skipping RETIRED column %r (owner order "
                    "2026-08-17; see _RETIRED_COLUMNS)", c.name)
                continue
            ddl = PG_DDL[c.type]
            nullable = c.nullable and c.name != self.config.primary_key
            col_specs.append((c.name, ddl, nullable))
        self.transport.create_table(
            schema=self.schema,
            table=self.table,
            columns=col_specs,
            primary_key=self.config.primary_key,
        )
        # Ensure PK has a unique index (PG creates one automatically, but be
        # explicit for `?on_conflict=` to work even if the user later drops it).
        self.transport.create_unique_index(
            schema=self.schema,
            table=self.table,
            columns=[self.config.primary_key],
        )
        return TableReport(created=True, identifier=f"{self.schema}.{self.table}")

    def ensure_schema(self) -> SchemaReport:
        if not self.config.columns:
            raise ValidationError("ensure_schema requires RepoConfig.columns")
        live = {
            c["name"]: c for c in self.transport.list_columns(
                schema=self.schema, table=self.table
            )
        }
        added: list[str] = []
        import logging
        _log = logging.getLogger(__name__)
        for c in self.config.columns:
            if c.name in live:
                continue
            if c.name in _RETIRED_COLUMNS:
                _log.warning(
                    "ensure_schema: skipping RETIRED column %r (owner order "
                    "2026-08-17; see _RETIRED_COLUMNS)", c.name)
                continue
            self.transport.add_column(
                schema=self.schema,
                table=self.table,
                name=c.name,
                ddl_type=PG_DDL[c.type],
                nullable=c.nullable,
            )
            added.append(c.name)
        declared = {c.name for c in self.config.columns}
        extras = [name for name in live if name not in declared]
        # Apply user-declared extra unique indexes (additive only) — except the
        # retired dedup laws, which stay dead whatever a config declares.
        for idx_cols in self.sb.indexes or []:
            if tuple(idx_cols) in _RETIRED_UNIQUE_INDEXES:
                _log.warning(
                    "ensure_schema: skipping RETIRED unique index on %r (owner "
                    "order 2026-08-17; resurrected once on 2026-08-24 and broke "
                    "a 15k archive move — see _RETIRED_UNIQUE_INDEXES)", idx_cols)
                continue
            self.transport.create_unique_index(
                schema=self.schema, table=self.table, columns=list(idx_cols)
            )
        return SchemaReport(columns_added=added, columns_extra_warning=extras)

    def ensure_permissions(self) -> PermissionsReport:
        # PostgREST permissioning is handled by the service-role key, not by
        # GRANTs we'd issue here. Nothing to do — return an empty report so
        # the orchestrator can keep its uniform contract.
        return PermissionsReport(granted=[])

    def teardown(self, *, drop_storage: bool) -> None:
        if not drop_storage:
            return
        self.transport.drop_table(schema=self.schema, table=self.table)

    # ---------- runtime ----------

    def get_columns(self) -> list[str]:
        cols = self.transport.list_columns(schema=self.schema, table=self.table)
        if cols:
            return [c["name"] for c in cols]
        return [c.name for c in self.config.columns]

    def fetch_all(self, *, columns: list[str] | None = None) -> list[dict[str, Any]]:
        return self.transport.select(
            schema=self.schema, table=self.table, select=columns
        )

    def fetch_by_ids(
        self, ids: list[str], *, columns: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        # Chunk to avoid 414 Request URI Too Long on large `id=in.(...)` filters.
        str_ids = [str(i) for i in ids]
        chunk_size = 100
        out: list[dict[str, Any]] = []
        for i in range(0, len(str_ids), chunk_size):
            chunk = str_ids[i : i + chunk_size]
            out.extend(
                self.transport.select(
                    schema=self.schema,
                    table=self.table,
                    ids=chunk,
                    pk=self.config.primary_key,
                    select=columns,
                )
            )
        return out

    def fetch_by_match_rules(
        self,
        items: list[dict[str, Any]],
        rules: list[UpsertMatchRule],
        *,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch existing rows that match any incoming item by any composite rule."""
        match_groups: list[dict[str, Any]] = []
        for item in items:
            for rule in rules:
                if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                    match_groups.append({c: item[c] for c in rule.columns})
        if not match_groups:
            return []
        return self.transport.select_matching(
            schema=self.schema,
            table=self.table,
            match_groups=match_groups,
            select=columns,
        )

    def query(self, q: Query) -> list[dict[str, Any]]:
        if q.mode in ("single", "by_ids"):
            return self.fetch_by_ids(q.ids or [], columns=q.select)
        kw = dict(
            schema=self.schema,
            table=self.table,
            select=q.select,
            filter=q.filter if q.mode == "filter" else None,
            limit=q.limit,
            offset=q.offset,
            search=q.search,
            search_columns=q.search_columns,
        )
        if q.order:
            return self.transport.select(order=[(o.col, o.dir) for o in q.order], **kw)
        try:
            return self.transport.select(order=list(_DEFAULT_ORDER), **kw)
        except Exception:
            # A repo whose table predates `created_at` must still be READABLE. The default is a
            # convenience, never a reason for the documents screen to fail, so an unsortable
            # column degrades to "unordered" instead of a 400. A caller's OWN order is not
            # caught above — that one is their bug and must surface.
            return self.transport.select(order=None, **kw)

    def count(self, q: Query) -> int:
        """Total rows matching the query's filter/search (ignores paging)."""
        return self.transport.count(
            schema=self.schema,
            table=self.table,
            filter=q.filter if q.mode == "filter" else None,
            search=q.search,
            search_columns=q.search_columns,
        )

    @staticmethod
    def _uniform_keys(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """PostgREST PGRST102: all rows in a batch must have identical keys.
        Pad missing keys with None so PostgREST accepts heterogeneous rows.
        """
        if len(rows) <= 1:
            return rows
        all_keys: set[str] = set()
        for r in rows:
            all_keys.update(r.keys())
        return [{k: r.get(k) for k in all_keys} for r in rows]

    def batch_update(self, updates: list[RowUpdate]) -> list[dict[str, Any]]:
        if not updates:
            return []
        rows: list[dict[str, Any]] = []
        for u in updates:
            row = dict(u.changes)
            row[self.config.primary_key] = u.pk
            rows.append(self._coerce_for_write(row))
        rows = self._uniform_keys(rows)
        result = self.transport.upsert(
            schema=self.schema,
            table=self.table,
            on_conflict=self.config.primary_key,
            rows=rows,
        )
        out: list[dict[str, Any]] = []
        for u in updates:
            out.append(
                {
                    "pk": u.pk,
                    "changedColumns": [
                        k for k in u.changes.keys() if k != self.config.primary_key
                    ],
                }
            )
        return out

    def batch_create(self, creates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not creates:
            return []
        rows = self._uniform_keys([self._coerce_for_write(r) for r in creates])
        result = self.transport.upsert(
            schema=self.schema,
            table=self.table,
            on_conflict=self.config.primary_key,
            rows=rows,
        )
        return [{"pk": str(r.get(self.config.primary_key, ""))} for r in result]
