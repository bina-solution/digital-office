"""`GSheetRepo` — `DocumentRepo` over a Google Sheet via `GSheetTransport`.

Runtime path: header read + cached → row index → batch update + append.
Provisioning path: ensure spreadsheet → ensure tab → ensure header row →
ensure share permissions. Mirrors n8n's existing `Batch Upsert`
behaviour byte-for-byte against the same sheet.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Iterable, Optional

from ..core.errors import BackendUnavailable, ValidationError
from ..core.month_key import month_key_of
from ..core.models import (
    ColumnDef,
    ContainerReport,
    GSheetBackendConfig,
    PermissionsReport,
    Query,
    RepoConfig,
    RowUpdate,
    SchemaReport,
    TableReport,
    UpsertMatchRule,
)
from ..core.types import LogicalType, normalize_value
from .gsheet_transport import FakeGSheetTransport, GSheetTransport


def _col_letter(index_zero: int) -> str:
    """0-indexed column number → A1 letters (0→A, 25→Z, 26→AA)."""
    if index_zero < 0:
        raise ValueError("column index must be non-negative")
    n = index_zero
    letters = ""
    while True:
        n, rem = divmod(n, 26)
        letters = chr(65 + rem) + letters
        if n == 0:
            break
        n -= 1
    return letters


def _quote_sheet(name: str) -> str:
    """Quote a sheet name for an A1 range — safe for Hebrew, spaces, etc."""
    return "'" + name.replace("'", "''") + "'"


def _serialize_for_sheet(value: Any, type_: LogicalType) -> Any:
    """Coerce a python value into the cell representation we write."""
    if value is None:
        return ""
    if type_ is LogicalType.JSON:
        import json
        return json.dumps(value, ensure_ascii=False)
    if type_ is LogicalType.BOOL:
        return "TRUE" if bool(value) else "FALSE"
    norm = normalize_value(value, type_)
    if norm is None:
        return ""
    # Cells are stored as strings in the API on the wire; canonicalise.
    return str(norm)


class GSheetRepo:
    """`DocumentRepo` implementation backed by Google Sheets."""

    def __init__(
        self,
        config: RepoConfig,
        transport: GSheetTransport | None = None,
        *,
        header_ttl_sec: int | None = None,
    ) -> None:
        if config.backend != "gsheet":
            raise ValidationError(
                f"GSheetRepo cannot serve backend='{config.backend}'"
            )
        if config.gsheet is None:
            raise ValidationError("RepoConfig.gsheet is required")
        self.config = config
        self.gs: GSheetBackendConfig = config.gsheet
        self.transport: GSheetTransport = transport or FakeGSheetTransport()
        self._header_cache: Optional[list[str]] = None
        self._header_cache_at: float = 0.0
        self._header_ttl: int = (
            header_ttl_sec
            if header_ttl_sec is not None
            else int(os.getenv("INCOMING_DOCS_HEADER_TTL_SEC", "60"))
        )

    # ---------- helpers ----------

    @property
    def spreadsheet_id(self) -> str:
        if not self.gs.spreadsheet_id:
            raise BackendUnavailable(
                "spreadsheet has not been provisioned yet "
                "(gsheet.spreadsheet_id is null)"
            )
        return self.gs.spreadsheet_id

    @property
    def sheet_name(self) -> str:
        return self.gs.sheet_name

    def _full_range(self, a1: str | None = None) -> str:
        base = _quote_sheet(self.sheet_name)
        return f"{base}!{a1}" if a1 else base

    def _column_def(self, name: str) -> ColumnDef | None:
        for c in self.config.columns:
            if c.name == name:
                return c
        return None

    def _column_type(self, name: str) -> LogicalType:
        c = self._column_def(name)
        return c.type if c else LogicalType.STRING

    def _invalidate_header_cache(self) -> None:
        self._header_cache = None
        self._header_cache_at = 0.0

    def _read_header(self, force: bool = False) -> list[str]:
        if (
            not force
            and self._header_cache is not None
            and (time.monotonic() - self._header_cache_at) < self._header_ttl
        ):
            return list(self._header_cache)
        result = self.transport.values_get(self.spreadsheet_id, self._full_range("1:1"))
        rows = result.get("values") or []
        header = [str(c) for c in (rows[0] if rows else [])]
        self._header_cache = header
        self._header_cache_at = time.monotonic()
        return list(header)

    def _read_all_rows(self) -> tuple[list[str], list[list[Any]]]:
        result = self.transport.values_get(self.spreadsheet_id, self._full_range())
        rows = result.get("values") or []
        if not rows:
            return [], []
        header = [str(c) for c in rows[0]]
        body = [list(r) for r in rows[1:]]
        # cache header from this read
        self._header_cache = list(header)
        self._header_cache_at = time.monotonic()
        return header, body

    @staticmethod
    def _row_to_dict(header: list[str], row: list[Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for i, name in enumerate(header):
            if i < len(row):
                v = row[i]
                if v == "":
                    continue
                out[name] = v
        return out

    # ---------- provisioning ----------

    def ensure_container(self) -> ContainerReport:
        if self.gs.spreadsheet_id:
            try:
                meta = self.transport.spreadsheet_get(self.gs.spreadsheet_id)
                return ContainerReport(
                    created=False, identifier=meta["spreadsheetId"]
                )
            except Exception as e:  # pragma: no cover - defensive
                raise BackendUnavailable(
                    f"spreadsheet '{self.gs.spreadsheet_id}' is unreachable: {e}"
                ) from e
        title = self.gs.spreadsheet_title or f"Incoming Documents — {self.config.name}"
        meta = self.transport.spreadsheet_create(title)
        new_id = meta["spreadsheetId"]
        self.gs.spreadsheet_id = new_id
        return ContainerReport(created=True, identifier=new_id)

    def ensure_table(self) -> TableReport:
        meta = self.transport.spreadsheet_get(self.spreadsheet_id)
        existing = {
            s["properties"]["title"]: s["properties"]["sheetId"]
            for s in meta.get("sheets", [])
        }
        if self.sheet_name in existing:
            self.gs.gid = int(existing[self.sheet_name])
            return TableReport(created=False, identifier=str(self.gs.gid))

        reply = self.transport.spreadsheet_batch_update(
            self.spreadsheet_id,
            [{"addSheet": {"properties": {"title": self.sheet_name}}}],
        )
        new_id = (
            reply["replies"][0]["addSheet"]["properties"]["sheetId"]
            if reply.get("replies")
            else None
        )
        if new_id is not None:
            self.gs.gid = int(new_id)
        return TableReport(created=True, identifier=str(self.gs.gid))

    def ensure_schema(self) -> SchemaReport:
        """Reconcile the sheet header row against `config.columns`.

        * Empty header → write the full declared header.
        * Existing header → append missing columns at the right; report
          extras as a warning; **never** reorder or delete.
        """
        if not self.config.columns:
            raise ValidationError("ensure_schema requires RepoConfig.columns")
        declared = [c.name for c in self.config.columns]
        current = self._read_header(force=True)

        if not current:
            self.transport.values_update(
                self.spreadsheet_id,
                self._full_range("A1"),
                [list(declared)],
            )
            self._invalidate_header_cache()
            return SchemaReport(columns_added=list(declared))

        added: list[str] = [c for c in declared if c not in current]
        extras: list[str] = [c for c in current if c not in declared]
        if added:
            new_header = list(current) + added
            self.transport.values_update(
                self.spreadsheet_id,
                self._full_range("A1"),
                [new_header],
            )
            self._invalidate_header_cache()
        return SchemaReport(columns_added=added, columns_extra_warning=extras)

    def ensure_permissions(self) -> PermissionsReport:
        granted: list[str] = []
        for editor in self.gs.editors or []:
            try:
                self.transport.drive_share(
                    self.spreadsheet_id, editor, role="writer"
                )
                granted.append(editor)
            except Exception:  # pragma: no cover - best-effort
                continue
        return PermissionsReport(granted=granted)

    def teardown(self, *, drop_storage: bool) -> None:
        if not drop_storage or not self.gs.spreadsheet_id:
            return
        try:
            self.transport.drive_delete(self.gs.spreadsheet_id)
        finally:
            self.gs.spreadsheet_id = None
            self.gs.gid = None

    # ---------- runtime ----------

    def get_columns(self) -> list[str]:
        header = self._read_header()
        if header:
            return header
        return [c.name for c in self.config.columns]

    def fetch_all(
        self, *, columns: list[str] | None = None
    ) -> list[dict[str, Any]]:
        header, body = self._read_all_rows()
        rows = [self._row_to_dict(header, r) for r in body]
        return [self._project(r, columns) for r in rows]

    def fetch_by_ids(
        self, ids: list[str], *, columns: list[str] | None = None
    ) -> list[dict[str, Any]]:
        if not ids:
            return []
        wanted = {str(i) for i in ids}
        out: list[dict[str, Any]] = []
        for row in self.fetch_all(columns=None):
            pk_v = row.get(self.config.primary_key)
            if pk_v is None:
                continue
            if str(pk_v) in wanted:
                out.append(self._project(row, columns))
        return out

    def fetch_by_match_rules(
        self,
        items: list[dict[str, Any]],
        rules: list[UpsertMatchRule],
        *,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch existing rows matching any incoming item by any composite rule (full scan)."""
        if not rules or not items:
            return []
        # Build set of (rule_idx, *vals) match keys from incoming items
        match_sets: list[set[tuple]] = [set() for _ in rules]
        for item in items:
            for i, rule in enumerate(rules):
                if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                    match_sets[i].add(tuple(str(item[c]) for c in rule.columns))
        if not any(match_sets):
            return []
        out: list[dict[str, Any]] = []
        pk = self.config.primary_key
        seen_pks: set[str] = set()
        for row in self.fetch_all(columns=None):
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
        rows = self.fetch_all(columns=None)
        if q.mode == "filter" and q.filter:
            rows = [r for r in rows if self._row_matches(r, q.filter)]
        if q.select:
            rows = [self._project(r, q.select) for r in rows]
        return rows[q.offset : q.offset + q.limit]

    def batch_update(
        self, updates: list[RowUpdate]
    ) -> list[dict[str, Any]]:
        if not updates:
            return []
        # Build (header, row-index-by-pk) once
        header, body = self._read_all_rows()
        if not header:
            raise BackendUnavailable("sheet has no header row")
        col_index = {name: i for i, name in enumerate(header)}
        pk_col = col_index.get(self.config.primary_key)
        if pk_col is None:
            raise BackendUnavailable(
                f"primary_key '{self.config.primary_key}' not in sheet header"
            )
        row_for_pk: dict[str, int] = {}
        for r_idx, row in enumerate(body):
            if pk_col < len(row):
                pk_v = row[pk_col]
                if pk_v not in (None, ""):
                    row_for_pk[str(pk_v)] = r_idx + 2  # +1 for header, +1 for 1-index

        data: list[dict[str, Any]] = []
        results: list[dict[str, Any]] = []
        for u in updates:
            row_no = row_for_pk.get(u.pk)
            if row_no is None:
                continue
            for col, val in u.changes.items():
                ci = col_index.get(col)
                if ci is None:
                    # unknown column → skip silently to mirror n8n tolerance
                    continue
                cell = f"{_col_letter(ci)}{row_no}"
                data.append(
                    {
                        "range": self._full_range(cell),
                        "values": [
                            [_serialize_for_sheet(val, self._column_type(col))]
                        ],
                    }
                )
            results.append(
                {
                    "pk": u.pk,
                    "row": row_no,
                    "changedColumns": list(u.changes.keys()),
                }
            )
        if data:
            self.transport.values_batch_update(self.spreadsheet_id, data)
        return results

    def batch_create(
        self, creates: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not creates:
            return []
        header = self._read_header()
        if not header:
            raise BackendUnavailable("sheet has no header row")
        rows: list[list[Any]] = []
        for item in creates:
            line: list[Any] = []
            for name in header:
                line.append(_serialize_for_sheet(item.get(name), self._column_type(name)))
            rows.append(line)
        result = self.transport.values_append(
            self.spreadsheet_id, self._full_range(), rows
        )
        # Best-effort row number from updatedRange
        first_row = None
        upd = result.get("updates") or {}
        m = re.search(r"!([A-Z]+)(\d+):", upd.get("updatedRange", ""))
        if m:
            first_row = int(m.group(2))
        out: list[dict[str, Any]] = []
        for i, item in enumerate(creates):
            entry = {"pk": str(item.get(self.config.primary_key, ""))}
            if first_row is not None:
                entry["row"] = first_row + i
            out.append(entry)
        return out

    # ---------- helpers ----------

    @staticmethod
    def _project(
        row: dict[str, Any], columns: list[str] | None
    ) -> dict[str, Any]:
        if columns is None:
            return dict(row)
        return {k: row.get(k) for k in columns}

    def _row_matches(
        self, row: dict[str, Any], filt: dict[str, Any]
    ) -> bool:
        for col, clause in filt.items():
            type_ = self._column_type(col)
            row_val = row.get(col)
            if isinstance(clause, dict) and "op" in clause:
                op = clause.get("op", "eq")
                v = clause.get("value")
            else:
                op, v = "eq", clause
            if not _eval_op(op, row_val, v, type_):
                return False
        return True


def _eval_op(op: str, row_val: Any, v: Any, type_: LogicalType) -> bool:
    nrow = normalize_value(row_val, type_)
    if op in ("is_null", "not_null"):
        is_null = nrow is None or nrow == ""
        return is_null if op == "is_null" else not is_null
    if op == "in":
        if not isinstance(v, (list, tuple)):
            return False
        return nrow in {normalize_value(x, type_) for x in v}
    if op == "nin":
        if not isinstance(v, (list, tuple)):
            return False
        return nrow not in {normalize_value(x, type_) for x in v}
    nv = normalize_value(v, type_)
    if op == "eq":
        return nrow == nv
    if op == "neq":
        return nrow != nv
    try:
        if op == "gt":
            return nrow > nv  # type: ignore[operator]
        if op == "gte":
            return nrow >= nv  # type: ignore[operator]
        if op == "lt":
            return nrow < nv  # type: ignore[operator]
        if op == "lte":
            return nrow <= nv  # type: ignore[operator]
    except TypeError:
        return False
    s = "" if nrow is None else str(nrow)
    sv = "" if nv is None else str(nv)
    if op == "contains":
        return sv in s
    if op == "startswith":
        return s.startswith(sv)
    if op == "endswith":
        return s.endswith(sv)
    if op == "month":
        # Same rule the month INDEX buckets by (`core.month_key`) — a gsheet repo
        # filters in memory, so it can call it directly instead of rendering the
        # regex the supabase backend needs.
        return month_key_of(s) == sv
    return False
