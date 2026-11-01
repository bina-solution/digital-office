"""Logical column type system.

The `LogicalType` is the source of truth in `RepoConfig.columns[*].type`.
It is mapped to backend-specific representations for storage (DDL / sheet
header) and used by the diff engine for value normalisation so that
``"42" == 42`` for an ``int`` column and dates compare ISO-string-equal.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any


class LogicalType(str, Enum):
    STRING = "string"     # default
    TEXT = "text"
    INT = "int"
    NUMERIC = "numeric"
    BOOL = "bool"
    DATE = "date"
    TIMESTAMP = "timestamp"
    JSON = "json"


# Postgres / Supabase DDL fragment per logical type.
PG_DDL: dict[LogicalType, str] = {
    LogicalType.STRING: "text",
    LogicalType.TEXT: "text",
    LogicalType.INT: "bigint",
    LogicalType.NUMERIC: "numeric",
    LogicalType.BOOL: "boolean",
    LogicalType.DATE: "date",
    LogicalType.TIMESTAMP: "timestamptz",
    LogicalType.JSON: "jsonb",
}

# Inverse lookup for `?adopt=true` introspection of an existing Supabase table.
PG_TO_LOGICAL: dict[str, LogicalType] = {
    "text": LogicalType.TEXT,
    "varchar": LogicalType.TEXT,
    "character varying": LogicalType.TEXT,
    "char": LogicalType.TEXT,
    "uuid": LogicalType.STRING,
    "bigint": LogicalType.INT,
    "integer": LogicalType.INT,
    "smallint": LogicalType.INT,
    "int4": LogicalType.INT,
    "int8": LogicalType.INT,
    "numeric": LogicalType.NUMERIC,
    "decimal": LogicalType.NUMERIC,
    "real": LogicalType.NUMERIC,
    "double precision": LogicalType.NUMERIC,
    "float4": LogicalType.NUMERIC,
    "float8": LogicalType.NUMERIC,
    "boolean": LogicalType.BOOL,
    "bool": LogicalType.BOOL,
    "date": LogicalType.DATE,
    "timestamp": LogicalType.TIMESTAMP,
    "timestamptz": LogicalType.TIMESTAMP,
    "timestamp with time zone": LogicalType.TIMESTAMP,
    "timestamp without time zone": LogicalType.TIMESTAMP,
    "json": LogicalType.JSON,
    "jsonb": LogicalType.JSON,
}


_TRUE_TOKENS = {"true", "TRUE", "True", "1", "yes", "YES", "y", "Y", "t", "T"}
_FALSE_TOKENS = {"false", "FALSE", "False", "0", "no", "NO", "n", "N", "f", "F", ""}


def normalize_value(value: Any, type_: LogicalType) -> Any:
    """Return the canonical Python value for comparison.

    The function NEVER raises on unparseable input — it returns the value
    unchanged so the diff engine can still compare it as a string and the
    caller receives a clear "value differs" rather than an opaque crash.

    ``None`` always normalises to ``None``.
    """
    if value is None:
        return None

    if type_ in (LogicalType.STRING, LogicalType.TEXT):
        return str(value)

    if type_ is LogicalType.INT:
        if isinstance(value, bool):
            # bool is a subclass of int; treat True/False as 1/0
            return int(value)
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            try:
                return int(Decimal(str(value).strip()))
            except (InvalidOperation, ValueError):
                return value

    if type_ is LogicalType.NUMERIC:
        if isinstance(value, (int, float, Decimal)):
            return Decimal(str(value))
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return value

    if type_ is LogicalType.BOOL:
        if isinstance(value, bool):
            return value
        s = str(value).strip()
        if s in _TRUE_TOKENS:
            return True
        if s in _FALSE_TOKENS:
            return False
        return value

    if type_ is LogicalType.DATE:
        if isinstance(value, date) and not isinstance(value, datetime):
            return value.isoformat()
        s = str(value).strip()
        if not s:
            return None
        # accept ISO date or ISO datetime; canonicalise to YYYY-MM-DD
        try:
            return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
        except ValueError:
            return s

    if type_ is LogicalType.TIMESTAMP:
        if isinstance(value, datetime):
            return value.isoformat()
        s = str(value).strip()
        if not s:
            return None
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            return s

    if type_ is LogicalType.JSON:
        # Equality of dict/list is structural — return as-is.
        return value

    return value


def values_equal(a: Any, b: Any, type_: LogicalType) -> bool:
    """Diff-engine equality predicate."""
    return normalize_value(a, type_) == normalize_value(b, type_)
