"""Pure-python diff engine.

Backend-agnostic. Given a list of *current* rows (as fetched from the
repo for the incoming PKs) and the *incoming* items, it buckets each
incoming item into one of:

  * ``creates`` — incoming item whose PK is absent from current rows
  * ``updates`` — incoming item whose PK exists, and at least one column
    value differs after `LogicalType` normalisation
  * ``noops`` — incoming item whose PK exists and all values match
  * ``skipped`` — incoming item that fails minimal validation (e.g. not
    a dict). NEVER raises.

Also applies the `priority_sync` rule: if any of
``RepoConfig.priority_sync_columns`` is set in the incoming item, an
extra ``priority_sync = True`` field is added to the changes (and the
created row).
"""
from __future__ import annotations

from typing import Any, Iterable

from .models import ColumnDef, DiffResult, RepoConfig, RowUpdate, UpsertMatchRule
from .types import LogicalType, values_equal


PRIORITY_SYNC_FIELD = "priority_sync"


def _strip_nulls(item: dict[str, Any]) -> dict[str, Any]:
    """Mirror n8n ``Clean Nulls`` — drop ``None`` (and the JS
    ``undefined``-style empty string is kept; n8n only stripped nulls).
    """
    return {k: v for k, v in item.items() if v is not None}


def _apply_priority_sync(
    item: dict[str, Any], priority_cols: Iterable[str]
) -> dict[str, Any]:
    """Mirror n8n ``Check Priority Sync`` — if any priority column is set
    in the item, force ``priority_sync = True``. Idempotent: calling
    twice with the same input gives the same output.
    """
    priority_set = set(priority_cols)
    if not priority_set:
        return item
    for k in item:
        if k in priority_set:
            return {**item, PRIORITY_SYNC_FIELD: True}
    return item


def _columns_index(config: RepoConfig) -> dict[str, ColumnDef]:
    return {c.name: c for c in config.columns}


def _column_type(idx: dict[str, ColumnDef], name: str) -> LogicalType:
    col = idx.get(name)
    return col.type if col else LogicalType.STRING


def _build_rule_indexes(
    current_rows: list[dict[str, Any]],
    rules: list[UpsertMatchRule],
) -> list[dict[tuple, dict[str, Any]]]:
    """For each rule, build a {(val1, val2, ...): row} lookup table."""
    indexes: list[dict[tuple, dict[str, Any]]] = []
    for rule in rules:
        idx: dict[tuple, dict[str, Any]] = {}
        for row in current_rows:
            if all(row.get(c) is not None and row.get(c) != "" for c in rule.columns):
                key = tuple(str(row[c]) for c in rule.columns)
                if key not in idx:  # first row wins (same as PK uniqueness expectation)
                    idx[key] = row
        indexes.append(idx)
    return indexes


def compute_diff(
    *,
    current_rows: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    config: RepoConfig,
) -> DiffResult:
    """Compute the diff. Pure: no I/O, no time, no randomness."""
    pk = config.primary_key
    by_pk: dict[str, dict[str, Any]] = {}
    for row in current_rows:
        if pk in row and row[pk] is not None:
            by_pk[str(row[pk])] = row

    # Build composite-key indexes for upsert_match_rules
    rule_indexes = _build_rule_indexes(current_rows, config.upsert_match_rules)

    col_idx = _columns_index(config)
    result = DiffResult()
    # Accumulate updates keyed by existing_pk so multiple incoming items
    # matching the same existing row are merged (last-write-wins per column).
    updates_map: dict[str, dict[str, Any]] = {}
    noops_set: set[str] = set()

    # Track pending creates by composite key so same-batch duplicates merge
    # into a single create (last-write-wins).  Indexed as:
    #   pending_creates_pk_key[pk_val] → index_in_pending_creates
    #   pending_creates_rule_key[rule_idx][composite_vals] → index_in_pending_creates
    pending_creates: list[dict[str, Any]] = []  # final deduplicated creates
    pending_pk_idx: dict[str, int] = {}          # pk_val → index in pending_creates
    pending_rule_idx: list[dict[tuple, int]] = [
        {} for _ in config.upsert_match_rules
    ]  # rule_i → {composite_vals: index in pending_creates}

    for raw in incoming:
        if not isinstance(raw, dict):
            result.skipped.append({"item": raw, "reason": "not a dict"})
            continue

        item = _strip_nulls(raw)
        item = _apply_priority_sync(item, config.priority_sync_columns)

        # --- find existing row: 1) by PK  2) by composite match rules ---
        existing_row: dict[str, Any] | None = None
        existing_pk: str | None = None

        if pk in item and item[pk] is not None:
            pk_val = str(item[pk])
            existing_row = by_pk.get(pk_val)
            if existing_row is not None:
                existing_pk = pk_val

        if existing_row is None and rule_indexes:
            for rule, idx in zip(config.upsert_match_rules, rule_indexes):
                if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                    key = tuple(str(item[c]) for c in rule.columns)
                    existing_row = idx.get(key)
                    if existing_row is not None:
                        existing_pk = str(existing_row.get(pk, "")) or None
                        break

        if existing_row is None:
            # No existing DB row found. Check for same-batch duplicate.
            batch_match_idx: int | None = None

            # 1) same PK already queued as a create?
            if pk in item and item[pk] is not None:
                batch_match_idx = pending_pk_idx.get(str(item[pk]))

            # 2) composite rule matches a pending create?
            if batch_match_idx is None:
                for ri, rule in enumerate(config.upsert_match_rules):
                    if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                        key = tuple(str(item[c]) for c in rule.columns)
                        batch_match_idx = pending_rule_idx[ri].get(key)
                        if batch_match_idx is not None:
                            break

            if batch_match_idx is not None:
                # Merge into existing pending create (last-write-wins per field)
                pending_creates[batch_match_idx].update(
                    {k: v for k, v in item.items() if k != pk}
                )
            else:
                # Truly new — queue as create and index it
                new_idx = len(pending_creates)
                pending_creates.append(dict(item))
                if pk in item and item[pk] is not None:
                    pending_pk_idx[str(item[pk])] = new_idx
                for ri, rule in enumerate(config.upsert_match_rules):
                    if all(item.get(c) is not None and item.get(c) != "" for c in rule.columns):
                        key = tuple(str(item[c]) for c in rule.columns)
                        pending_rule_idx[ri].setdefault(key, new_idx)
            continue

        if existing_pk is None:
            # Matched by composite rule but existing row has no PK — treat as create
            result.creates.append(item)
            continue

        # Compare each incoming field against the current row
        changes: dict[str, Any] = {}
        for k, v in item.items():
            if k == pk:
                continue
            if not values_equal(existing_row.get(k), v, _column_type(col_idx, k)):
                changes[k] = v

        if changes:
            # Merge into updates_map (last-write-wins per column)
            if existing_pk in updates_map:
                updates_map[existing_pk].update(changes)
            else:
                updates_map[existing_pk] = changes
            noops_set.discard(existing_pk)
        else:
            if existing_pk not in updates_map:
                noops_set.add(existing_pk)

    for pk_val, changes in updates_map.items():
        result.updates.append(RowUpdate(pk=pk_val, changes=changes))
    result.noops = list(noops_set)
    result.creates = pending_creates

    return result
