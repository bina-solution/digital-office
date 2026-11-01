"""Integration tests for SupabaseRepo against the in-memory FakeSupabaseTransport.

Mirrors the GSheetRepo coverage so we know both backends honour the same
DocumentRepo contract.
"""
from __future__ import annotations

import pytest

from incoming_documents.backends import (
    FakeSupabaseTransport,
    SupabaseRepo,
)
from incoming_documents.core.errors import (
    BackendUnavailable,
    ProvisioningFailed,
    ValidationError,
)
from incoming_documents.core.models import (
    ColumnDef,
    Query,
    RepoConfig,
    RowUpdate,
    SupabaseBackendConfig,
)
from incoming_documents.core.types import LogicalType


def _cfg(*, with_columns: bool = True, schema: str = "public") -> RepoConfig:
    cols = (
        [
            ColumnDef(name="ID", type=LogicalType.STRING, nullable=False),
            ColumnDef(name="STATUS", type=LogicalType.STRING),
            ColumnDef(name="DOC_TOTAL_AMOUNT", type=LogicalType.NUMERIC),
            ColumnDef(name="ACTIVE", type=LogicalType.BOOL),
            ColumnDef(name="DOC_DATE", type=LogicalType.DATE),
        ]
        if with_columns
        else []
    )
    return RepoConfig(
        name="prod_supabase",
        backend="supabase",
        primary_key="ID",
        columns=cols,
        supabase=SupabaseBackendConfig(
            schema=schema,  # type: ignore[arg-type]
            table="incoming_documents",
            indexes=[["STATUS"]],
        ),
    )


# ---------- provisioning ----------


def test_provision_creates_schema_table_and_index():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(schema="ingest"), transport=t)

    assert repo.ensure_container().identifier == "ingest"
    assert "ingest" in t.schemas_set

    tbl = repo.ensure_table()
    assert tbl.created is True
    assert ("ingest", "incoming_documents") in t.tables

    sch = repo.ensure_schema()
    assert sch.columns_added == []
    assert sch.columns_extra_warning == []
    # custom unique index from supabase.indexes was applied
    assert ["STATUS"] in t.unique_indexes[("ingest", "incoming_documents")]
    # PK unique index always applied during ensure_table
    assert ["ID"] in t.unique_indexes[("ingest", "incoming_documents")]


def test_provision_is_idempotent():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    repo.ensure_container()
    repo.ensure_table()
    repo.ensure_schema()
    # Run again
    assert repo.ensure_container().identifier == "public"
    assert repo.ensure_table().created is False
    sch = repo.ensure_schema()
    assert sch.columns_added == []


def test_ensure_schema_appends_missing_columns_and_warns_extras():
    t = FakeSupabaseTransport()
    # Pre-create a table with a partial schema + an extra legacy column
    t.create_table(
        schema="public",
        table="incoming_documents",
        columns=[
            ("ID", "text", False),
            ("STATUS", "text", True),
            ("LEGACY_COL", "text", True),
        ],
        primary_key="ID",
    )
    repo = SupabaseRepo(_cfg(), transport=t)
    repo.ensure_container()
    # ensure_table should be a no-op since table exists
    assert repo.ensure_table().created is False
    sch = repo.ensure_schema()
    assert sch.columns_added == ["DOC_TOTAL_AMOUNT", "ACTIVE", "DOC_DATE"]
    assert sch.columns_extra_warning == ["LEGACY_COL"]


def test_teardown_drops_table_when_drop_storage_true():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    repo.ensure_container()
    repo.ensure_table()
    assert ("public", "incoming_documents") in t.tables
    repo.teardown(drop_storage=True)
    assert ("public", "incoming_documents") not in t.tables


def test_teardown_default_keeps_table():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    repo.ensure_container()
    repo.ensure_table()
    repo.teardown(drop_storage=False)
    assert ("public", "incoming_documents") in t.tables


# ---------- runtime ----------


def _seed(repo: SupabaseRepo) -> None:
    repo.ensure_container()
    repo.ensure_table()
    repo.ensure_schema()
    repo.batch_create(
        [
            {"ID": "abc-1", "STATUS": "PENDING", "DOC_TOTAL_AMOUNT": "10"},
            {"ID": "abc-2", "STATUS": "DONE", "DOC_TOTAL_AMOUNT": "42.5"},
            {"ID": "abc-3", "STATUS": "PENDING", "DOC_TOTAL_AMOUNT": "100"},
        ]
    )


def test_fetch_all_and_fetch_by_ids():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    _seed(repo)
    rows = repo.fetch_all()
    assert {r["ID"] for r in rows} == {"abc-1", "abc-2", "abc-3"}
    by = repo.fetch_by_ids(["abc-2"])
    assert by[0]["STATUS"] == "DONE"


def test_batch_update_does_pk_keyed_upsert():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    _seed(repo)
    res = repo.batch_update(
        [
            RowUpdate(pk="abc-1", changes={"STATUS": "DONE"}),
            RowUpdate(pk="abc-3", changes={"DOC_TOTAL_AMOUNT": "200"}),
        ]
    )
    assert {r["pk"] for r in res} == {"abc-1", "abc-3"}
    after = {r["ID"]: r for r in repo.fetch_all()}
    assert after["abc-1"]["STATUS"] == "DONE"
    assert after["abc-3"]["DOC_TOTAL_AMOUNT"] == "200"


def test_query_filter_and_pagination():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    _seed(repo)
    out = repo.query(Query(mode="filter", filter={"STATUS": "PENDING"}))
    assert {r["ID"] for r in out} == {"abc-1", "abc-3"}
    p1 = repo.query(Query(mode="all", limit=2, offset=0))
    p2 = repo.query(Query(mode="all", limit=2, offset=2))
    assert len(p1) == 2 and len(p2) == 1


def test_get_columns_returns_live_columns():
    t = FakeSupabaseTransport()
    repo = SupabaseRepo(_cfg(), transport=t)
    _seed(repo)
    cols = repo.get_columns()
    assert cols[0] == "ID"
    assert "STATUS" in cols


# ---------- error paths ----------


def test_repo_rejects_wrong_backend():
    with pytest.raises(ValidationError):
        SupabaseRepo(
            RepoConfig(
                name="x",
                backend="gsheet",
                primary_key="ID",
                columns=[ColumnDef(name="ID")],
                gsheet={"sheet_name": "s"},
            ),
            transport=FakeSupabaseTransport(),
        )


def test_runtime_before_provisioning_fails():
    repo = SupabaseRepo(_cfg(), transport=FakeSupabaseTransport())
    with pytest.raises(BackendUnavailable):
        repo.fetch_all()
