"""Transport seam for the Supabase backend.

Defines a thin `SupabaseTransport` Protocol and two implementations:

* `FakeSupabaseTransport` — in-memory; used by unit/integration tests so we
  don't need a live Supabase instance.
* `HttpxSupabaseTransport` — production. Talks PostgREST for runtime calls
  (`select`/`upsert`/`delete`) and `pg_meta` REST + an SQL-RPC for
  provisioning DDL (CREATE SCHEMA / CREATE TABLE / ALTER TABLE).

The wider repo class (`SupabaseRepo`) only knows about this Protocol so
backend logic stays test-friendly.
"""
from __future__ import annotations

import json
import os
import time
from typing import Any, Iterable, Optional, Protocol, runtime_checkable

from ..core.errors import BackendUnavailable, ProvisioningFailed, ValidationError
from ..core.month_key import month_key_regex


# ---------------------------------------------------------------------------
# TENANCY GUARD (indox-final-plan phase 6.3/6.5)
#
# `settings`, `companies` and `tag_rules` carry an `instance` discriminator.
# Every read of them must filter by it and every write must carry it, and the
# one failure mode of a discriminator-column design is a FORGOTTEN predicate:
# the query still succeeds, it just quietly returns — or overwrites — another
# client's configuration. Nothing about that is visible at the call site.
#
# So the check lives at the chokepoint every call already goes through rather
# than being restated at each of the thirteen of them. This is the same
# argument the plan makes for `Build Table Get`/`Build Table Upsert` on the
# n8n side: one gate, and it THROWS when the instance is absent, because a gate
# that defaults is a gate that hides the bug it exists to catch.
#
# `incoming_documents` is deliberately NOT in this set — documents stay
# table-per-instance, and the table name itself is the discriminator.
# ---------------------------------------------------------------------------
_TENANT_TABLES = frozenset({"settings", "companies", "tag_rules"})


class MissingInstanceError(RuntimeError):
    """Raised when a tenant-scoped table is touched without an instance."""


def _require_instance_filter(table: str, filter: dict | None, op: str) -> None:
    if table not in _TENANT_TABLES:
        return
    if not isinstance(filter, dict) or not str(filter.get("instance") or "").strip():
        raise MissingInstanceError(
            f"{op} on public.{table} without an `instance` filter — this would "
            f"read across every instance. Pass filter={{'instance': <name>}}."
        )


def _require_instance_rows(table: str, rows: list[dict] | None, op: str) -> None:
    if table not in _TENANT_TABLES:
        return
    for i, r in enumerate(rows or []):
        if not isinstance(r, dict) or not str(r.get("instance") or "").strip():
            raise MissingInstanceError(
                f"{op} on public.{table} row {i} carries no `instance` — under the "
                f"(instance, key) primary key this would land on the default "
                f"instance and overwrite another client's configuration."
            )


# ---------- protocol ----------


#: A SQL STRING LITERAL. The single quote is doubled, which is the escape postgres defines;
#: `_q` (nested in the match-group builder) escapes for PostgREST query params — a different job.
#: dict/list values are JSON — str() on those produces Python repr (single quotes, True/None),
#: which postgres rejects as jsonb input, so every tenant-schema write of a stats payload failed
#: and was swallowed as a warning. The PostgREST path JSON-encodes whole rows; this path must
#: encode the value the same way or the two write paths disagree exactly on non-public schemas.
def _q_lit(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        value = json.dumps(value, ensure_ascii=False, default=str)
    return "'" + str(value).replace("'", "''") + "'"


@runtime_checkable
class SupabaseTransport(Protocol):
    """Wire-level operations the `SupabaseRepo` needs."""

    # ----- runtime (PostgREST) -----
    def select(
        self,
        *,
        schema: str,
        table: str,
        select: list[str] | None = None,
        ids: list[str] | None = None,
        pk: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order: list[tuple[str, str]] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def count(
        self,
        *,
        schema: str,
        table: str,
        filter: dict[str, Any] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> int:
        """Total rows matching filter/search (ignores limit/offset)."""
        ...

    def upsert(
        self, *, schema: str, table: str, on_conflict: str, rows: list[dict[str, Any]]
    ) -> list[dict[str, Any]]: ...

    def select_matching(
        self,
        *,
        schema: str,
        table: str,
        match_groups: list[dict[str, Any]],
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows where ANY match_group dict fully matches (AND within group, OR across groups)."""
        ...

    # ----- provisioning (pg_meta + SQL) -----
    def list_tables(self, *, schema: str) -> list[str]: ...

    def list_columns(self, *, schema: str, table: str) -> list[dict[str, Any]]:
        """Returns a list of `{"name": str, "data_type": str, "is_nullable": bool}`."""
        ...

    def create_schema(self, *, schema: str) -> None: ...

    def create_table(
        self,
        *,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key: str,
    ) -> None:
        """`columns` is a list of `(name, ddl_type, nullable)`."""
        ...

    def add_column(
        self, *, schema: str, table: str, name: str, ddl_type: str, nullable: bool
    ) -> None: ...

    def create_unique_index(
        self, *, schema: str, table: str, columns: list[str], name: str | None = None
    ) -> None: ...

    def drop_table(self, *, schema: str, table: str) -> None: ...


# ---------- in-memory fake ----------


class FakeSupabaseTransport:
    """In-memory backend for tests.

    State lives in `self.tables[(schema, table)]` as a list of row dicts
    plus `self.schemas[(schema, table)]` capturing the column DDL types.
    """

    def __init__(self) -> None:
        self.schemas_set: set[str] = {"public"}
        self.tables: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.columns: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.primary_keys: dict[tuple[str, str], str] = {}
        self.unique_indexes: dict[tuple[str, str], list[list[str]]] = {}

    # ----- runtime -----

    @staticmethod
    def _match_search(
        row: dict[str, Any], search: str, search_columns: list[str] | None
    ) -> bool:
        needle = search.strip().lower()
        if not needle:
            return True
        cols = search_columns or list(row.keys())
        for c in cols:
            v = row.get(c)
            if v is not None and needle in str(v).lower():
                return True
        return False

    def _filtered_rows(
        self,
        schema: str,
        table: str,
        *,
        ids: list[str] | None,
        pk: str | None,
        filter: dict[str, Any] | None,
        search: str | None,
        search_columns: list[str] | None,
    ) -> list[dict[str, Any]]:
        out = list(self._rows(schema, table))
        if ids is not None:
            if pk is None:
                raise ProvisioningFailed("select(ids=...) requires pk")
            wanted = {str(i) for i in ids}
            out = [r for r in out if str(r.get(pk)) in wanted]
        if filter:
            out = [r for r in out if self._match_filter(r, filter)]
        if search:
            out = [r for r in out if self._match_search(r, search, search_columns)]
        return out

    def select(
        self,
        *,
        schema: str,
        table: str,
        select: list[str] | None = None,
        ids: list[str] | None = None,
        pk: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order: list[tuple[str, str]] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        out = self._filtered_rows(
            schema, table, ids=ids, pk=pk, filter=filter,
            search=search, search_columns=search_columns,
        )
        if order:
            # Apply in reverse so the first key is the most significant.
            for col, direction in reversed(order):
                out = sorted(
                    out,
                    key=lambda r, c=col: (
                        r.get(c) is None,
                        str(r.get(c)) if r.get(c) is not None else "",
                    ),
                    reverse=(direction == "desc"),
                )
        if offset:
            out = out[offset:]
        if limit is not None:
            out = out[:limit]
        if select:
            out = [{k: r.get(k) for k in select} for r in out]
        return [dict(r) for r in out]

    def count(
        self,
        *,
        schema: str,
        table: str,
        filter: dict[str, Any] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> int:
        return len(
            self._filtered_rows(
                schema, table, ids=None, pk=None, filter=filter,
                search=search, search_columns=search_columns,
            )
        )

    def select_matching(
        self,
        *,
        schema: str,
        table: str,
        match_groups: list[dict[str, Any]],
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        rows = self._rows(schema, table)
        out: list[dict[str, Any]] = []
        seen_idxes: set[int] = set()
        for i, row in enumerate(rows):
            if i in seen_idxes:
                continue
            for group in match_groups:
                if all(str(row.get(k)) == str(v) for k, v in group.items()):
                    seen_idxes.add(i)
                    out.append(
                        {k: row.get(k) for k in select} if select else dict(row)
                    )
                    break
        return out

    def upsert(
        self,
        *,
        schema: str,
        table: str,
        on_conflict: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        bucket = self._rows(schema, table)
        results: list[dict[str, Any]] = []
        for incoming in rows:
            key = incoming.get(on_conflict)
            existing = next(
                (r for r in bucket if r.get(on_conflict) == key), None
            )
            if existing is None:
                bucket.append(dict(incoming))
                results.append(dict(incoming))
            else:
                existing.update(incoming)
                results.append(dict(existing))
        return results

    # ----- provisioning -----

    def list_tables(self, *, schema: str) -> list[str]:
        return [t for (s, t) in self.tables if s == schema]

    def list_columns(self, *, schema: str, table: str) -> list[dict[str, Any]]:
        return [dict(c) for c in self.columns.get((schema, table), [])]

    def create_schema(self, *, schema: str) -> None:
        self.schemas_set.add(schema)

    def create_table(
        self,
        *,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key: str,
    ) -> None:
        key = (schema, table)
        if key in self.tables:
            return
        self.tables[key] = []
        self.columns[key] = [
            {"name": n, "data_type": t, "is_nullable": nul}
            for (n, t, nul) in columns
        ]
        self.primary_keys[key] = primary_key

    def add_column(
        self,
        *,
        schema: str,
        table: str,
        name: str,
        ddl_type: str,
        nullable: bool,
    ) -> None:
        key = (schema, table)
        if key not in self.columns:
            raise ProvisioningFailed(f"table {schema}.{table} not found")
        if any(c["name"] == name for c in self.columns[key]):
            return
        self.columns[key].append(
            {"name": name, "data_type": ddl_type, "is_nullable": nullable}
        )

    def create_unique_index(
        self,
        *,
        schema: str,
        table: str,
        columns: list[str],
        name: str | None = None,
    ) -> None:
        key = (schema, table)
        idx = self.unique_indexes.setdefault(key, [])
        if columns not in idx:
            idx.append(list(columns))

    def drop_table(self, *, schema: str, table: str) -> None:
        key = (schema, table)
        self.tables.pop(key, None)
        self.columns.pop(key, None)
        self.primary_keys.pop(key, None)
        self.unique_indexes.pop(key, None)

    # ----- helpers -----

    def _rows(self, schema: str, table: str) -> list[dict[str, Any]]:
        key = (schema, table)
        if key not in self.tables:
            raise BackendUnavailable(f"table {schema}.{table} does not exist")
        return self.tables[key]

    @staticmethod
    def _match_filter(row: dict[str, Any], filt: dict[str, Any]) -> bool:
        for col, clause in filt.items():
            if isinstance(clause, dict) and "op" in clause:
                op = clause.get("op", "eq")
                v = clause.get("value")
            else:
                op, v = "eq", clause
            cur = row.get(col)
            if op == "eq" and cur != v:
                return False
            if op == "neq" and cur == v:
                return False
            if op == "in" and cur not in (v or []):
                return False
            if op == "is_null" and cur is not None:
                return False
            if op == "not_null" and cur is None:
                return False
            if op == "contains" and (cur is None or str(v) not in str(cur)):
                return False
        return True


# ---------- production: httpx ----------


class HttpxSupabaseTransport:
    """Real PostgREST + pg_meta transport.

    Reads `SUPABASE_BASE_URL` (e.g. `https://xyz.supabase.co`) and a service
    role key from the env var named in `RepoConfig.supabase.service_key_env`
    (default `SUPABASE_SERVICE_KEY`).

    Provisioning DDL is executed via a single SQL RPC named
    `INCOMING_DOCS_SQL_RPC` (default `run_sql`). The RPC must accept a
    single text param `query` and run it with the service role.
    """

    def __init__(
        self,
        *,
        base_url: str | None = None,
        service_key: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._base_url = (base_url or os.getenv("SUPABASE_BASE_URL", "")).rstrip("/")
        if not self._base_url:
            raise BackendUnavailable("SUPABASE_BASE_URL is not set")
        self._key = service_key or os.getenv("SUPABASE_SERVICE_KEY", "")
        if not self._key:
            raise BackendUnavailable("SUPABASE_SERVICE_KEY is not set")
        self._timeout = timeout
        self._sql_rpc = os.getenv("INCOMING_DOCS_SQL_RPC", "run_sql")

    def _client(self):
        import httpx  # lazy

        return httpx.Client(
            base_url=self._base_url,
            timeout=self._timeout,
            headers={
                "apikey": self._key,
                "Authorization": f"Bearer {self._key}",
            },
        )

    # ----- runtime -----

    @staticmethod
    def _sanitize_search(term: str) -> str:
        """Strip characters that would break a PostgREST `or=(...)` filter.

        The horizontal-filter grammar uses `,()."\\` as delimiters; a raw user
        term containing them corrupts the query. We drop those and keep the rest
        (spaces collapse to a single wildcard segment via `ilike.*term*`).
        """
        cleaned = "".join(ch for ch in term if ch not in ',()."\\')
        return cleaned.strip()

    def _search_or_param(
        self, search: str, search_columns: list[str] | None
    ) -> str | None:
        term = self._sanitize_search(search)
        if not term or not search_columns:
            return None
        pattern = f"*{term}*"
        parts = ",".join(f"{col}.ilike.{pattern}" for col in search_columns)
        return f"({parts})"

    def _runtime_params(
        self,
        *,
        select: list[str] | None,
        ids: list[str] | None,
        pk: str | None,
        filter: dict[str, Any] | None,
        search: str | None,
        search_columns: list[str] | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {}
        if select:
            params["select"] = ",".join(select)
        if ids is not None:
            if not pk:
                raise ProvisioningFailed("select(ids=...) requires pk")
            quoted = ",".join(f'"{str(i)}"' for i in ids)
            params[pk] = f"in.({quoted})"
        if filter:
            for col, clause in filter.items():
                if isinstance(clause, dict) and "op" in clause:
                    params[col] = self._encode_op(clause.get("op", "eq"), clause.get("value"))
                else:
                    params[col] = self._encode_op("eq", clause)
        if search:
            or_part = self._search_or_param(search, search_columns)
            if or_part is not None:
                params["or"] = or_part
        return params

    # ── READING A SCHEMA POSTGREST CANNOT SEE ────────────────────────────────────────────────
    #
    # PostgREST serves only the schemas in PGRST_DB_SCHEMAS (public, storage, graphql_public).
    # A tenant schema is not among them and cannot be, in any way that scales: db-schemas takes
    # no wildcards, so exposing `indox_<client>` would mean editing compose and bouncing a shared
    # service for every client onboarded — an infra operation for something that must be a
    # runtime one. Asking for one anyway returns 406 Not Acceptable.
    #
    # So a read against a tenant schema goes through `public.run_sql`, which PostgREST does serve
    # and whose body is not schema-limited.
    #
    # THE SAFETY RULE THIS CODE LIVES BY. run_sql is SECURITY DEFINER as postgres, and EXECUTE was
    # revoked from anon/authenticated on 2026-08-28 precisely because it is a superuser primitive.
    # A value that escaped its quoting here would be that same hole reopened from the inside. So:
    #
    #   * IDENTIFIERS ARE NEVER TAKEN FROM THE CALLER. Every column name is checked against the
    #     table's ACTUAL columns, read from information_schema; anything unknown is REFUSED rather
    #     than escaped. That is what makes Hebrew and spaced names ("מזהה 1", "VALIDATION STATUS")
    #     safe without a permissive regex that would have to allow them anyway.
    #   * OPERATORS COME FROM A FIXED MAP, never from the request.
    #   * VALUES are quoted literals and only ever appear in comparison position.
    #
    # The PostgREST path below is untouched and still serves `public`, so nothing that reads a
    # compat view moves until its caller asks for a tenant schema.
    _POSTGREST_SCHEMAS = {
        s.strip()
        for s in os.getenv(
            "INCOMING_DOCS_POSTGREST_SCHEMAS", "public,storage,graphql_public"
        ).split(",")
        if s.strip()
    }

    def _serves_via_rest(self, schema: str) -> bool:
        return (schema or "public") in self._POSTGREST_SCHEMAS

    # MODULE-LEVEL, not per-instance: transports are constructed fresh per call all over the BFF
    # (_config_transport, _sync_transport, bare HttpxSupabaseTransport()), so a cache hung on
    # `self` was empty on essentially every request — every tenant-schema operation paid an extra
    # information_schema round trip, roughly doubling the RPC count of instance-scoped requests.
    # 60s TTL: column sets change on schema migration, not per request; apply-schema restarts
    # nothing, so a bounded staleness window (same as the API layer's _columns_cache) beats a
    # cache that never hits.
    _COLSET_CACHE: dict[str, tuple[float, set[str]]] = {}
    _COLSET_TTL = 60.0

    def _columns_of(self, *, schema: str, table: str) -> set[str]:
        """The table's real columns — the allowlist every identifier is checked against."""
        key = schema + "." + table
        now = time.monotonic()
        hit = HttpxSupabaseTransport._COLSET_CACHE.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        rows = self._exec_sql(
            "select column_name from information_schema.columns "
            "where table_schema = " + _q_lit(schema) + " and table_name = " + _q_lit(table)
        ) or []
        cols = {str(r.get("column_name")) for r in rows if r.get("column_name")}
        HttpxSupabaseTransport._COLSET_CACHE[key] = (now + HttpxSupabaseTransport._COLSET_TTL, cols)
        return cols

    def _ident(self, name: str, known: set[str], what: str) -> str:
        if name not in known:
            raise ProvisioningFailed("refusing to build SQL for an unknown " + what + ": " + repr(name))
        return '"' + str(name).replace('"', '""') + '"'

    def _where_sql(self, *, known, filter=None, ids=None, pk=None, search=None, search_columns=None) -> str:
        clauses: list[str] = []
        if ids is not None and pk:
            if not ids:
                return " where false"
            col = self._ident(pk, known, "primary key")
            clauses.append(col + " in (" + ", ".join(_q_lit(str(i)) for i in ids) + ")")
        for raw_col, clause in (filter or {}).items():
            col = self._ident(str(raw_col), known, "filter column")
            op, val = "eq", clause
            if isinstance(clause, dict):
                op, val = str(clause.get("op", "eq")), clause.get("value")
            if op == "eq":
                clauses.append(col + " is null" if val is None
                               else col + "::text = " + _q_lit(val))
            elif op == "neq":
                clauses.append(col + "::text is distinct from " + _q_lit(val))
            elif op == "in":
                vals = list(val or [])
                clauses.append(
                    col + "::text in (" + ", ".join(_q_lit(v) for v in vals) + ")" if vals else "false"
                )
            elif op == "is_null":
                clauses.append(col + " is null")
            elif op == "not_null":
                clauses.append(col + " is not null")
            elif op in ("contains", "like"):
                clauses.append(col + "::text ilike " + _q_lit("%" + str(val) + "%"))
            elif op == "startswith":
                clauses.append(col + "::text ilike " + _q_lit(str(val) + "%"))
            # RANGE OPERATORS. Every window on the dashboard and the action log is a date range,
            # so leaving these out did not degrade — it raised "unsupported filter operator: gte"
            # and blanked the screen the moment a tenant read took this path. The set below is the
            # one the codebase actually uses (measured across the BFF and the webapp), and it is
            # still a FIXED map: an operator that is not named here is refused, never interpolated.
            elif op in ("gte", "gt", "lte", "lt"):
                sym = {"gte": ">=", "gt": ">", "lte": "<=", "lt": "<"}[op]
                clauses.append(col + " " + sym + " " + _q_lit(val))
            elif op in ("empty", "is_empty"):
                clauses.append("(" + col + " is null or " + col + "::text = '')")
            elif op in ("notempty", "not_empty", "notEmpty"):
                clauses.append("(" + col + " is not null and " + col + "::text <> '')")
            elif op == "equals":
                clauses.append(col + "::text = " + _q_lit(val))
            else:
                raise ProvisioningFailed("unsupported filter operator: " + repr(op))
        term = (search or "").strip()
        if term and search_columns:
            like = _q_lit("%" + term.replace(" ", "%") + "%")
            ors = [
                self._ident(c, known, "search column") + "::text ilike " + like
                for c in search_columns if c in known
            ]
            if ors:
                clauses.append("(" + " or ".join(ors) + ")")
        return (" where " + " and ".join(clauses)) if clauses else ""

    def _select_sql(self, *, schema, table, select=None, ids=None, pk=None, filter=None,
                    limit=None, offset=None, order=None, search=None, search_columns=None):
        known = self._columns_of(schema=schema, table=table)
        cols = "*"
        if select and list(select) != ["*"]:
            cols = ", ".join(self._ident(c, known, "select column") for c in select)
        sql = 'select ' + cols + ' from "' + schema + '"."' + table + '"'
        sql += self._where_sql(known=known, filter=filter, ids=ids, pk=pk,
                               search=search, search_columns=search_columns)
        if order:
            parts = [
                self._ident(c, known, "order column") + (" desc" if str(d).lower() == "desc" else " asc")
                for c, d in order
            ]
            sql += " order by " + ", ".join(parts)
        if limit is not None:
            sql += " limit " + str(int(limit))
        if offset is not None:
            sql += " offset " + str(int(offset))
        return self._exec_sql(sql) or []

    def _count_sql(self, *, schema, table, filter=None, search=None, search_columns=None) -> int:
        known = self._columns_of(schema=schema, table=table)
        sql = 'select count(*) as n from "' + schema + '"."' + table + '"'
        sql += self._where_sql(known=known, filter=filter, ids=None, pk=None,
                               search=search, search_columns=search_columns)
        rows = self._exec_sql(sql) or []
        return int(rows[0].get("n", 0)) if rows else 0

    def select(
        self,
        *,
        schema: str,
        table: str,
        select: list[str] | None = None,
        ids: list[str] | None = None,
        pk: str | None = None,
        filter: dict[str, Any] | None = None,
        limit: int | None = None,
        offset: int | None = None,
        order: list[tuple[str, str]] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        # SCHEMA ISOLATION SUPERSEDES THE ROW-LEVEL GUARD, and must be checked first.
        # `_require_instance_filter` exists because a read of `public.settings` without an
        # `instance` filter spans every tenant. Inside `indox_<id>` that premise is false —
        # the schema IS the discriminator, and imposing the filter is worse than omitting
        # it: a tenant's rows carry their own instance label, so filtering by the global
        # one returns the leaked rows and hides the real ones (measured: 8 of 68 on
        # indox_levi.settings, and the 8 were the wrong ones).
        if not self._serves_via_rest(schema):
            return self._select_sql(
                schema=schema, table=table, select=select, ids=ids, pk=pk,
                filter=filter, limit=limit, offset=offset, order=order,
                search=search, search_columns=search_columns,
            )
        # …and for a `public` read the guard stands exactly as before: there the premise IS true.
        _require_instance_filter(table, filter, "select")
        params = self._runtime_params(
            select=select, ids=ids, pk=pk, filter=filter,
            search=search, search_columns=search_columns,
        )
        if order:
            params["order"] = ",".join(
                f"{col}.{'desc' if str(direction).lower() == 'desc' else 'asc'}"
                for col, direction in order
            )
        if limit is not None:
            params["limit"] = str(limit)
        if offset is not None:
            params["offset"] = str(offset)
        with self._client() as c:
            r = c.get(
                f"/rest/v1/{table}",
                params=params,
                headers={"Accept-Profile": schema},
            )
            r.raise_for_status()
            return r.json()

    def count(
        self,
        *,
        schema: str,
        table: str,
        filter: dict[str, Any] | None = None,
        search: str | None = None,
        search_columns: list[str] | None = None,
    ) -> int:
        """Exact row count via PostgREST `Prefer: count=exact` + Content-Range.

        Requests a zero-row window (`limit=1`, `head`-style) and parses the
        total off the ``Content-Range: 0-0/1234`` response header.
        """
        # SCHEMA ISOLATION SUPERSEDES THE ROW-LEVEL GUARD, and must be checked first.
        # `_require_instance_filter` exists because a read of `public.settings` without an
        # `instance` filter spans every tenant. Inside `indox_<id>` that premise is false —
        # the schema IS the discriminator, and imposing the filter is worse than omitting
        # it: a tenant's rows carry their own instance label, so filtering by the global
        # one returns the leaked rows and hides the real ones (measured: 8 of 68 on
        # indox_levi.settings, and the 8 were the wrong ones).
        if not self._serves_via_rest(schema):
            return self._count_sql(
                schema=schema, table=table, filter=filter,
                search=search, search_columns=search_columns,
            )
        # …and for a `public` count the guard stands exactly as before.
        _require_instance_filter(table, filter, "count")
        params = self._runtime_params(
            select=["*"], ids=None, pk=None, filter=filter,
            search=search, search_columns=search_columns,
        )
        params["limit"] = "1"
        with self._client() as c:
            r = c.get(
                f"/rest/v1/{table}",
                params=params,
                headers={
                    "Accept-Profile": schema,
                    "Prefer": "count=exact",
                    "Range-Unit": "items",
                },
            )
            r.raise_for_status()
            content_range = r.headers.get("Content-Range", "")
            # Format is "start-end/total" or "*/total".
            total_part = content_range.split("/")[-1] if content_range else ""
            try:
                return int(total_part)
            except (ValueError, TypeError):
                return len(r.json())

    def select_matching(
        self,
        *,
        schema: str,
        table: str,
        match_groups: list[dict[str, Any]],
        select: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch rows matching any group via PostgREST ?or= query, chunked."""
        if not match_groups:
            return []

        def _q(v: Any) -> str:
            """PostgREST value quoting: wrap in double-quotes."""
            return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"') + '"'

        def _group_to_or_part(group: dict[str, Any]) -> str:
            if len(group) == 1:
                k, v = next(iter(group.items()))
                return f"{k}.eq.{_q(v)}"
            parts = ",".join(f"{k}.eq.{_q(v)}" for k, v in group.items())
            return f"and({parts})"

        or_parts = [_group_to_or_part(g) for g in match_groups]
        CHUNK = 50
        results: list[dict[str, Any]] = []
        seen: set[str] = set()  # deduplicate by row identity (str repr)

        params_base: dict[str, Any] = {}
        if select:
            params_base["select"] = ",".join(select)

        with self._client() as c:
            for i in range(0, len(or_parts), CHUNK):
                chunk = or_parts[i : i + CHUNK]
                params = {**params_base, "or": f"({','.join(chunk)})"}
                r = c.get(
                    f"/rest/v1/{table}",
                    params=params,
                    headers={"Accept-Profile": schema},
                )
                r.raise_for_status()
                for row in r.json():
                    key = str(sorted(row.items()))
                    if key not in seen:
                        seen.add(key)
                        results.append(row)
        return results

    # ── WRITING TO A SCHEMA POSTGREST CANNOT SEE ─────────────────────────────────────────────
    #
    # The read fallback above covered select/count only, and that asymmetry was the last thing
    # blocking the tenancy cutover. Measured on the live stack:
    #
    #   Content-Profile: public         -> 201
    #   Content-Profile: indox_hacohen  -> 406 PGRST106 "Only the following schemas are exposed"
    #
    # So every upsert/update/insert/delete against a tenant schema failed outright, while reads
    # succeeded — which meant the webapp could not send `?instance=` on writes without turning
    # every settings save into a 406. These four close that gap.
    #
    # SAME DISCIPLINE AS THE READ PATH, and for the same reason: run_sql is SECURITY DEFINER as
    # postgres. Column names are checked against information_schema and REFUSED if unknown rather
    # than escaped; values are quoted literals and only ever appear as values; the schema name is
    # gated separately because it is the one identifier with nothing to check it against.
    #
    # Writes get one thing reads do not: RETURNING, so the caller still gets the representation
    # PostgREST's `Prefer: return=representation` gave it and nothing downstream changes shape.
    _SAFE_SCHEMA_RE = __import__("re").compile(r"^[a-z][a-z0-9_]*$")

    def _qualified(self, schema: str, table: str) -> str:
        if not self._SAFE_SCHEMA_RE.match(schema or ""):
            raise ProvisioningFailed(f"refusing to build SQL for schema {schema!r}")
        known = self._columns_of(schema=schema, table=table)
        if not known:
            raise ProvisioningFailed(f"refusing to write to unknown table {schema}.{table}")
        return f'"{schema}"."{table}"'

    def _eq_where(self, *, known: set[str], match: dict) -> str:
        """An equality filter, the same shape PostgREST's `?col=eq.v` params carry."""
        if not match:
            raise ValidationError("a write filter must not be empty")
        parts = []
        for col, val in match.items():
            ident = self._ident(str(col), known, "filter column")
            parts.append(f"{ident} is null" if val is None else f"{ident}::text = {_q_lit(val)}")
        return " where " + " and ".join(parts)

    def _readback(self, *, schema: str, table: str, rows: list[dict], keys: list[str]) -> list[dict]:
        """Re-read the rows a write just touched.

        `public.run_sql` does not return rows for DML — measured: a bare `RETURNING *` and a
        CTE-wrapped one both come back empty, because the function only treats a statement as
        row-returning when it can wrap it in a subquery. PostgREST's callers rely on
        `Prefer: return=representation` handing the row back (the console's "add row" reads it),
        so the fallback restores that contract with a follow-up SELECT rather than quietly
        returning [] and making a successful write look like a failed one."""
        if not rows or not keys:
            return []
        known = self._columns_of(schema=schema, table=table)
        idents = [self._ident(k, known, "key column") for k in keys]
        tuples = []
        for r in rows:
            if any(r.get(k) is None for k in keys):
                continue
            tuples.append("(" + ", ".join(_q_lit(r[k]) for k in keys) + ")")
        if not tuples:
            return []
        rel = self._qualified(schema, table)
        cast = "(" + ", ".join(f"{i}::text" for i in idents) + ")"
        return self._exec_sql(
            f"select * from {rel} where {cast} in ({', '.join(tuples)})"
        ) or []

    def _upsert_sql(self, *, schema: str, table: str, on_conflict: str,
                    rows: list[dict]) -> list[dict]:
        rel = self._qualified(schema, table)
        known = self._columns_of(schema=schema, table=table)
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(str(k))
        idents = [self._ident(c, known, "insert column") for c in cols]
        conflict = [self._ident(c.strip(), known, "conflict column")
                    for c in str(on_conflict).split(",") if c.strip()]
        values = ", ".join(
            "(" + ", ".join(_q_lit(r.get(c)) for c in cols) + ")" for r in rows
        )
        # DO UPDATE over every non-conflict column — the same merge-duplicates semantics
        # `Prefer: resolution=merge-duplicates` gives, so a caller cannot tell the paths apart.
        sets = [f"{i} = excluded.{i}" for i, c in zip(idents, cols) if i not in conflict]
        action = (f" do update set {', '.join(sets)}" if sets else " do nothing")
        sql = (f"insert into {rel} ({', '.join(idents)}) values {values}"
               f" on conflict ({', '.join(conflict)}){action}")
        self._exec_sql(sql)
        keys = [c.strip() for c in str(on_conflict).split(",") if c.strip()]
        return self._readback(schema=schema, table=table, rows=rows, keys=keys)

    def _insert_sql(self, *, schema: str, table: str, rows: list[dict]) -> list[dict]:
        rel = self._qualified(schema, table)
        known = self._columns_of(schema=schema, table=table)
        cols: list[str] = []
        for r in rows:
            for k in r:
                if k not in cols:
                    cols.append(str(k))
        idents = [self._ident(c, known, "insert column") for c in cols]
        values = ", ".join(
            "(" + ", ".join(_q_lit(r.get(c)) for c in cols) + ")" for r in rows
        )
        self._exec_sql(f"insert into {rel} ({', '.join(idents)}) values {values}")
        # No conflict key to read back by, so match on the columns the caller supplied — the
        # honest best a generated PK allows, and enough for the console's add-row flow.
        return self._readback(schema=schema, table=table, rows=rows, keys=cols)

    def _update_sql(self, *, schema: str, table: str, match: dict,
                    values: dict) -> list[dict]:
        rel = self._qualified(schema, table)
        known = self._columns_of(schema=schema, table=table)
        sets = ", ".join(
            f"{self._ident(str(k), known, 'update column')} = {_q_lit(v)}"
            for k, v in values.items()
        )
        where = self._eq_where(known=known, match=match)
        self._exec_sql(f"update {rel} set {sets}{where}")
        return self._exec_sql(f"select * from {rel}{where}") or []

    def _delete_sql(self, *, schema: str, table: str, match: dict) -> None:
        rel = self._qualified(schema, table)
        known = self._columns_of(schema=schema, table=table)
        # Uses the READ path's clause builder, not the equality-only one, because a delete is not
        # always an equality: the action-log purge filters `STARTED_AT >= <iso>` or "everything
        # non-null". Same fixed operator map, same refusal of unknown identifiers.
        where = self._where_sql(known=known, filter=match, ids=None, pk=None,
                                search=None, search_columns=None)
        # NO UNFILTERED DELETE, EVER. An empty match would render an empty WHERE and take the
        # whole table; PostgREST refuses the same thing by design, and so does this.
        if not where.strip():
            raise ValidationError("delete requires a match filter")
        self._exec_sql(f"delete from {rel}{where}")

    def upsert(
        self,
        *,
        schema: str,
        table: str,
        on_conflict: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not rows:
            return []
        if not self._serves_via_rest(schema):
            return self._upsert_sql(schema=schema, table=table,
                                    on_conflict=on_conflict, rows=rows)
        _require_instance_rows(table, rows, "upsert")
        conflict_target = _postgrest_identifier(on_conflict)
        with self._client() as c:
            r = c.post(
                f"/rest/v1/{table}",
                params={"on_conflict": conflict_target},
                headers={
                    "Content-Profile": schema,
                    "Prefer": "resolution=merge-duplicates,return=representation",
                    "Content-Type": "application/json",
                },
                json=rows,
            )
            if r.status_code >= 400:
                # 400/409 from PostgREST are client data errors (constraint
                # violations, not-null violations, type mismatches, etc.) —
                # not backend outages. 401/403/404/5xx remain BackendUnavailable.
                if r.status_code in (400, 409):
                    try:
                        body = r.json()
                        raise ValidationError(
                            body.get("message", r.text),
                            constraint=body.get("details", ""),
                            hint=body.get("hint"),
                            pg_code=body.get("code"),
                        )
                    except ValidationError:
                        raise
                    except Exception:
                        raise ValidationError(r.text)
                raise BackendUnavailable(
                    f"supabase upsert failed [{r.status_code}]: {r.text}"
                )
            return r.json()

    def update(
        self,
        *,
        schema: str,
        table: str,
        match: dict[str, Any],
        values: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Pure UPDATE via PostgREST PATCH — never inserts (so it is safe on
        tables with a GENERATED-ALWAYS identity PK, unlike merge-upsert which
        must name the PK in the INSERT clause). ``match`` is an equality filter
        (e.g. ``{"id": 5}``); ``values`` are the columns to set."""
        if not values:
            return []
        if not self._serves_via_rest(schema):
            return self._update_sql(schema=schema, table=table, match=match, values=values)
        _require_instance_filter(table, match, "update")
        params = {k: f"eq.{v}" for k, v in match.items()}
        with self._client() as c:
            r = c.patch(
                f"/rest/v1/{table}",
                params=params,
                headers={
                    "Content-Profile": schema,
                    "Prefer": "return=representation",
                    "Content-Type": "application/json",
                },
                json=values,
            )
            if r.status_code >= 400:
                if r.status_code in (400, 409):
                    try:
                        body = r.json()
                        raise ValidationError(
                            body.get("message", r.text),
                            constraint=body.get("details", ""),
                            hint=body.get("hint"),
                            pg_code=body.get("code"),
                        )
                    except ValidationError:
                        raise
                    except Exception:
                        raise ValidationError(r.text)
                raise BackendUnavailable(
                    f"supabase update failed [{r.status_code}]: {r.text}"
                )
            return r.json()

    def insert(
        self,
        *,
        schema: str,
        table: str,
        rows: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Plain INSERT (PostgREST POST, no on_conflict) — for adding new rows to
        a table with a GENERATED-ALWAYS identity PK (omit the PK; it's assigned)."""
        if not rows:
            return []
        if not self._serves_via_rest(schema):
            return self._insert_sql(schema=schema, table=table, rows=rows)
        _require_instance_rows(table, rows, "insert")
        with self._client() as c:
            r = c.post(
                f"/rest/v1/{table}",
                headers={
                    "Content-Profile": schema,
                    "Prefer": "return=representation",
                    "Content-Type": "application/json",
                },
                json=rows,
            )
            if r.status_code >= 400:
                if r.status_code in (400, 409):
                    try:
                        body = r.json()
                        raise ValidationError(
                            body.get("message", r.text),
                            constraint=body.get("details", ""),
                            hint=body.get("hint"),
                            pg_code=body.get("code"),
                        )
                    except ValidationError:
                        raise
                    except Exception:
                        raise ValidationError(r.text)
                raise BackendUnavailable(
                    f"supabase insert failed [{r.status_code}]: {r.text}"
                )
            return r.json()

    def delete(self, *, schema: str, table: str, match: dict[str, Any]) -> None:
        """Delete rows matching an equality filter (e.g. {"id": 5})."""
        if not match:
            raise ValidationError("delete requires a match filter")
        if not self._serves_via_rest(schema):
            return self._delete_sql(schema=schema, table=table, match=match)
        _require_instance_filter(table, match, "delete")
        params = {k: f"eq.{v}" for k, v in match.items()}
        with self._client() as c:
            r = c.delete(
                f"/rest/v1/{table}",
                params=params,
                headers={"Content-Profile": schema},
            )
            if r.status_code >= 400:
                raise BackendUnavailable(
                    f"supabase delete failed [{r.status_code}]: {r.text}"
                )

    # ----- provisioning -----

    def _exec_sql(self, sql: str) -> Any:
        with self._client() as c:
            r = c.post(
                f"/rest/v1/rpc/{self._sql_rpc}",
                json={"query": sql},
                headers={"Content-Type": "application/json"},
            )
            if r.status_code >= 400:
                raise ProvisioningFailed(
                    f"sql failed [{r.status_code}]: {r.text} | sql={sql}"
                )
            try:
                return r.json()
            except Exception:
                return None

    def list_tables(self, *, schema: str) -> list[str]:
        rows = self._exec_sql(
            "select table_name from information_schema.tables "
            f"where table_schema = '{_q(schema)}' and table_type = 'BASE TABLE'"
        ) or []
        return [r["table_name"] for r in rows]

    def list_columns(self, *, schema: str, table: str) -> list[dict[str, Any]]:
        rows = self._exec_sql(
            "select column_name as name, data_type, is_nullable "
            "from information_schema.columns "
            f"where table_schema = '{_q(schema)}' and table_name = '{_q(table)}'"
        ) or []
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(
                {
                    "name": r["name"],
                    "data_type": r["data_type"],
                    "is_nullable": str(r.get("is_nullable", "YES")).upper() == "YES",
                }
            )
        return out

    def create_schema(self, *, schema: str) -> None:
        self._exec_sql(f'create schema if not exists "{_id(schema)}"')

    def create_table(
        self,
        *,
        schema: str,
        table: str,
        columns: list[tuple[str, str, bool]],
        primary_key: str,
    ) -> None:
        col_sql_parts = []
        for n, t, nullable in columns:
            null = "" if nullable else " not null"
            col_sql_parts.append(f'"{_id(n)}" {t}{null}')
        col_sql_parts.append(f'primary key ("{_id(primary_key)}")')
        cols = ", ".join(col_sql_parts)
        self._exec_sql(
            f'create table if not exists "{_id(schema)}"."{_id(table)}" ({cols})'
        )

    def add_column(
        self,
        *,
        schema: str,
        table: str,
        name: str,
        ddl_type: str,
        nullable: bool,
    ) -> None:
        null = "" if nullable else " not null"
        self._exec_sql(
            f'alter table "{_id(schema)}"."{_id(table)}" '
            f'add column if not exists "{_id(name)}" {ddl_type}{null}'
        )

    def create_unique_index(
        self,
        *,
        schema: str,
        table: str,
        columns: list[str],
        name: str | None = None,
    ) -> None:
        idx_name = name or f"ux_{table}_{'_'.join(columns)}"
        cols = ", ".join(f'"{_id(c)}"' for c in columns)
        self._exec_sql(
            f'create unique index if not exists "{_id(idx_name)}" '
            f'on "{_id(schema)}"."{_id(table)}" ({cols})'
        )

    def drop_table(self, *, schema: str, table: str) -> None:
        self._exec_sql(f'drop table if exists "{_id(schema)}"."{_id(table)}"')

    # ----- helpers -----

    @staticmethod
    def _encode_op(op: str, value: Any) -> str:
        if op == "is_null":
            return "is.null"
        if op == "not_null":
            return "not.is.null"
        if op == "in":
            quoted = ",".join(f'"{x}"' for x in (value or []))
            return f"in.({quoted})"
        if op == "contains":
            return f"like.*{value}*"
        if op == "startswith":
            return f"like.{value}*"
        if op == "endswith":
            return f"like.*{value}"
        if op == "month":
            # PostgREST `match` is Postgres `~`. `month_key_regex` is built to be
            # comma-free and quote-free so it survives the query string as a plain
            # operand, and it matches EXACTLY the raw values `month_key_of` buckets
            # into this key — the month index and the month filter are then the same
            # rule, which is the whole point of the operator.
            return f"match.{month_key_regex(str(value))}"
        return f"{op}.{value}"


def _id(name: str) -> str:
    """Escape a SQL identifier — the only metacharacter is a literal `"`."""
    return name.replace('"', '""')


def _postgrest_identifier(name: str) -> str:
    """Format an `on_conflict` target for PostgREST query parameters — one column, or several
    comma-joined for a composite unique constraint (e.g. `settings`' primary key `(instance, key)`).

    `on_conflict=ID` is interpreted as the lowercase SQL identifier `id`. For quoted/mixed-case
    table columns (the incoming-documents schemas use names like `ID` and `COMPANY_ID`), PostgREST
    needs the quoted form.

    BUG THIS FIXES: a composite target like `instance,key` is not a valid Python identifier, so it
    used to fall straight into the quoting branch and come back as `"instance,key"` — ONE quoted
    string containing a comma, which PostgREST reads as a single column literally named
    `instance,key`. `column "instance,key" does not exist`, on every write to a composite-keyed
    table (`settings`, since phase 6's tenancy-by-discriminator work) — the whole reason INDOX's
    "database unavailable" sync-source save error existed. Each part must be quoted (or not)
    *individually*, then rejoined with the comma PostgREST itself expects between conflict columns.
    """
    return ",".join(
        part if part.isidentifier() and part == part.lower() else f'"{_id(part)}"'
        for part in name.split(",")
    )


def _q(literal: str) -> str:
    """Escape a SQL string literal — replace single quotes."""
    return literal.replace("'", "''")
