"""Pydantic models for `RepoConfig`, document records, query, diff, and
event-envelope shapes. These are the canonical wire formats used by the
HTTP API and by the on-disk repo registry JSON file.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional, Union
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .types import LogicalType


class EnumValue(BaseModel):
    """One value of a display enum: what it READS as, and what it MEANS.

    `kind` is the semantic colour class (ok/warn/bad/muted). It travels with the value so a
    status is the same colour on the dashboard, in a grid cell and on the detail page without
    three components each keeping their own opinion."""

    model_config = ConfigDict(extra="forbid")

    label: str
    kind: Optional[str] = None


class ColumnDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1)
    type: LogicalType = LogicalType.STRING
    nullable: bool = True
    unique: bool = False
    default: Optional[Any] = None

    # ── display metadata ──────────────────────────────────────────────────────
    # A COLUMN CARRIES HOW IT IS SHOWN, not just how it is stored. Before this the grid
    # rendered raw SQL identifiers as Hebrew-UI headers (STATUS, SOURCE_TYPE, DOC_TOTAL_AMOUNT)
    # and each screen kept its own private label map, so a column added to the pipeline reached
    # the operator as an English shout and every screen had to be edited to fix it.
    #
    # Serving it HERE means the UI can never be behind the schema: `GET /repos/<r>` already
    # returns these columns, so a label added to the catalog is live on the next page load with
    # no frontend change. An unlabelled column still renders — as its raw name — because a new
    # column must be visible and usable the day it appears, never blank.
    label: Optional[str] = None
    #: name of a value domain in `RepoConfig.enums` (e.g. "STATUS") — the cell, the header
    #: filter's option list and the detail page all read their words from that one domain.
    enum: Optional[str] = None
    #: default grid visibility. None = let the client curate (the historical behaviour).
    visible: Optional[bool] = None
    #: included in the free-text search's ILIKE set.
    searchable: Optional[bool] = None
    #: 'end' for amounts/numbers (ERP convention), 'start' otherwise.
    align: Optional[str] = None
    #: declared, but not for humans: a column the table still carries and nothing should show.
    #: Kept in the schema on purpose — a column that exists and is undeclared is the failure
    #: this field exists to end; hiding it by omission would recreate exactly that.
    deprecated: Optional[bool] = None
    #: free text for a tooltip — why this column exists, in the operator's language.
    description: Optional[str] = None


class GSheetBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spreadsheet_id: Optional[str] = None
    spreadsheet_title: Optional[str] = None
    sheet_name: str
    gid: Optional[int] = None
    editors: list[str] = Field(default_factory=list)


class SupabaseBackendConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_: str = Field("public", alias="schema")
    table: str
    service_key_env: str = "SUPABASE_SERVICE_KEY"
    rls: bool = False
    indexes: list[list[str]] = Field(default_factory=list)
    studio_url: Optional[str] = Field(
        None,
        description="Base URL of Supabase Studio (e.g. https://supabase-studio.example.com)",
    )


class UpsertMatchRule(BaseModel):
    """One composite-key pattern for upsert deduplication.

    When an incoming item has all listed columns present (non-null), any
    existing row with the same values is treated as a match — even if the
    primary key is absent from the incoming item or differs.  Rules are
    tried in order after the primary-key lookup; the first match wins.

    Example (mirrors the n8n "Build Lookup Query" pattern)::

        upsert_match_rules:
          - columns: [COMPANY_ID, SHORT_DOC_ID]
          - columns: [COMPANY_ID, DOC_ID]
          - columns: [HASH]
    """

    model_config = ConfigDict(extra="forbid")

    columns: list[str] = Field(..., min_length=1)


class KafkaConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    partitions: int = 3
    retention_hours: int = 168


class RepoConfig(BaseModel):
    """Full repo configuration. Stored verbatim in the JSON registry."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, pattern=r"^[a-zA-Z0-9_\-]+$")
    backend: Literal["gsheet", "supabase"]
    primary_key: str = Field("ID", min_length=1)
    columns: list[ColumnDef] = Field(default_factory=list)
    #: VALUE DOMAINS, by name: `{"STATUS": {"COMPLETED": {"label": "הושלם", "kind": "ok"}, …}}`.
    #: A column points at one via `ColumnDef.enum`. Held once per repo rather than inlined on
    #: every column that uses it, because STATUS is read by the grid cell, that column's header
    #: filter, the drill-down chip and the detail page — four readers, one set of words.
    enums: dict[str, dict[str, EnumValue]] = Field(default_factory=dict)
    priority_sync_columns: list[str] = Field(default_factory=list)
    gsheet: Optional[GSheetBackendConfig] = None
    supabase: Optional[SupabaseBackendConfig] = None
    kafka: KafkaConfig = Field(default_factory=KafkaConfig)
    upsert_match_rules: list[UpsertMatchRule] = Field(
        default_factory=list,
        description=(
            "Composite-key match rules tried (in order) when incoming item "
            "PK is absent or not found. Mirrors the n8n 'Build Lookup Query' pattern."
        ),
    )
    active: bool = Field(False, description="Enable background polling for this repo")
    poll_interval_seconds: int = Field(
        30, ge=10, description="How often (seconds) to poll the source when active"
    )
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @model_validator(mode="after")
    def _backend_block_present(self) -> "RepoConfig":
        if self.backend == "gsheet" and self.gsheet is None:
            raise ValueError("gsheet backend requires `gsheet` config block")
        if self.backend == "supabase" and self.supabase is None:
            raise ValueError("supabase backend requires `supabase` config block")
        return self

    @model_validator(mode="after")
    def _pk_in_columns(self) -> "RepoConfig":
        if self.columns:
            names = {c.name for c in self.columns}
            if self.primary_key not in names:
                raise ValueError(f"primary_key '{self.primary_key}' is not in columns")
        return self

    @field_validator("columns")
    @classmethod
    def _unique_column_names(cls, v: list[ColumnDef]) -> list[ColumnDef]:
        seen: set[str] = set()
        for c in v:
            if c.name in seen:
                raise ValueError(f"duplicate column name '{c.name}'")
            seen.add(c.name)
        return v


# ---------- query ----------

QueryOp = Literal[
    "eq", "neq", "in", "nin",
    "gt", "gte", "lt", "lte",
    "contains", "startswith", "endswith",
    "is_null", "not_null",
    # `month`: value is a `YYYY-MM` key; matches every raw date STRING that the
    # month index buckets into that month (`core.month_key`). It exists because a
    # date column here is TEXT holding two live shapes — ISO `YYYY-MM-DD…` and the
    # `D/M/YY(YY)` the OCR/AI extractors write — so a `startswith 'YYYY-MM'` prefix,
    # which is what month navigation used to send, can only ever match the ISO
    # minority. Each backend renders the ONE rule into its own dialect; neither
    # invents a second one.
    "month",
]


class FilterClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: QueryOp = "eq"
    value: Any = None


# A filter value in the API may be either a scalar (sugar for {op:eq, value:...})
# or a full FilterClause dict.
FilterValue = Union[Any, FilterClause]


class OrderClause(BaseModel):
    """One column + direction for server-side sorting."""

    model_config = ConfigDict(extra="forbid")

    col: str
    dir: Literal["asc", "desc"] = "asc"


class Query(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["single", "by_ids", "filter", "all"] = "all"
    ids: Optional[list[str]] = None
    filter: Optional[dict[str, FilterValue]] = None
    select: Optional[list[str]] = None
    limit: int = 1000
    offset: int = 0
    # ── grid extensions (all optional / backward-compatible) ──────────────────
    # `order`  : server-side multi-column sort (applied by supabase backend).
    # `search` : free-text ILIKE match across `search_columns` (OR'd together).
    # `with_count` : when true the query endpoint also returns the total row
    #                count matching the filter/search (for "page N of M").
    order: Optional[list[OrderClause]] = None
    search: Optional[str] = None
    search_columns: Optional[list[str]] = None
    with_count: bool = False

    @model_validator(mode="after")
    def _mode_inputs(self) -> "Query":
        if self.mode in ("single", "by_ids") and not self.ids:
            raise ValueError(f"mode={self.mode} requires `ids`")
        if self.mode == "filter" and not self.filter:
            raise ValueError("mode=filter requires `filter`")
        return self


# ---------- diff ----------

class RowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pk: str
    changes: dict[str, Any]


class DiffResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    updates: list[RowUpdate] = Field(default_factory=list)
    creates: list[dict[str, Any]] = Field(default_factory=list)
    noops: list[str] = Field(default_factory=list)         # PKs unchanged
    skipped: list[dict[str, Any]] = Field(default_factory=list)  # malformed items


# ---------- event ----------

EventType = Literal["ROW_CHANGED", "ROW_CREATED", "REPO_CREATED", "MANUAL"]


class EventEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID = Field(default_factory=uuid4)
    repo: str
    event_type: EventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    row: dict[str, Any] = Field(default_factory=dict)


# ---------- provisioning reports ----------

class ContainerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created: bool
    identifier: str  # spreadsheet_id or schema name


class TableReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    created: bool
    identifier: str  # gid (as str) or fully-qualified table


class SchemaReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns_added: list[str] = Field(default_factory=list)
    columns_extra_warning: list[str] = Field(default_factory=list)


class PermissionsReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    granted: list[str] = Field(default_factory=list)


class ProvisionReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    container: ContainerReport
    table: TableReport
    schema_: SchemaReport = Field(alias="schema")
    permissions: PermissionsReport
    kafka_topic_created: bool = False
