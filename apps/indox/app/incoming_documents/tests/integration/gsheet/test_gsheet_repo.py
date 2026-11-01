"""Integration tests for GSheetRepo against the in-memory FakeGSheetTransport.

These exercise both the runtime path (read / batch_update / batch_create / query)
and the provisioning path (ensure_container / table / schema / permissions).
"""
from __future__ import annotations

import pytest

from incoming_documents.backends import (
    FakeGSheetTransport,
    GSheetRepo,
)
from incoming_documents.core.models import (
    ColumnDef,
    GSheetBackendConfig,
    Query,
    RepoConfig,
    RowUpdate,
)
from incoming_documents.core.types import LogicalType


HEBREW_TAB = "מסמכים נכנסים"


def _cfg(*, with_columns: bool = True, spreadsheet_id: str | None = None) -> RepoConfig:
    cols = (
        [
            ColumnDef(name="ID", type=LogicalType.STRING, nullable=False),
            ColumnDef(name="STATUS", type=LogicalType.STRING),
            ColumnDef(name="DOC_TOTAL_AMOUNT", type=LogicalType.NUMERIC),
            ColumnDef(name="ACTIVE", type=LogicalType.BOOL),
            ColumnDef(name="DOC_DATE", type=LogicalType.DATE),
            ColumnDef(name="סימון כרטסת עדכנית", type=LogicalType.STRING),
        ]
        if with_columns
        else []
    )
    return RepoConfig(
        name="prod_gsheet",
        backend="gsheet",
        primary_key="ID",
        columns=cols,
        gsheet=GSheetBackendConfig(
            spreadsheet_id=spreadsheet_id,
            spreadsheet_title="Test SS",
            sheet_name=HEBREW_TAB,
            editors=["alice@example.com", "bob@example.com"],
        ),
    )


# ---------- provisioning ----------


def test_provision_full_lifecycle_creates_spreadsheet_tab_header_and_shares():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)

    c = repo.ensure_container()
    assert c.created is True
    assert c.identifier.startswith("fake-ss-")

    tbl = repo.ensure_table()
    assert tbl.created is True

    sch = repo.ensure_schema()
    assert sch.columns_added == [
        "ID",
        "STATUS",
        "DOC_TOTAL_AMOUNT",
        "ACTIVE",
        "DOC_DATE",
        "סימון כרטסת עדכנית",
    ]
    assert sch.columns_extra_warning == []

    perms = repo.ensure_permissions()
    assert sorted(perms.granted) == ["alice@example.com", "bob@example.com"]


def test_provision_is_idempotent():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)

    repo.ensure_container()
    repo.ensure_table()
    repo.ensure_schema()

    # second pass: nothing new
    c2 = repo.ensure_container()
    assert c2.created is False

    t2 = repo.ensure_table()
    assert t2.created is False

    s2 = repo.ensure_schema()
    assert s2.columns_added == []
    assert s2.columns_extra_warning == []


def test_provision_existing_header_appends_missing_columns_only():
    t = FakeGSheetTransport()
    base = _cfg()
    repo = GSheetRepo(base, transport=t, header_ttl_sec=0)
    repo.ensure_container()
    repo.ensure_table()
    # Pre-populate with a partial header (also containing an extra column)
    t.values_update(
        repo.spreadsheet_id,
        repo._full_range("A1"),
        [["ID", "STATUS", "EXTRA_LEGACY_COL"]],
    )
    repo._invalidate_header_cache()

    sch = repo.ensure_schema()
    assert sch.columns_added == [
        "DOC_TOTAL_AMOUNT",
        "ACTIVE",
        "DOC_DATE",
        "סימון כרטסת עדכנית",
    ]
    assert sch.columns_extra_warning == ["EXTRA_LEGACY_COL"]
    final_header = repo._read_header(force=True)
    assert final_header[:3] == ["ID", "STATUS", "EXTRA_LEGACY_COL"]
    assert final_header[3:] == [
        "DOC_TOTAL_AMOUNT",
        "ACTIVE",
        "DOC_DATE",
        "סימון כרטסת עדכנית",
    ]


def test_teardown_drop_storage_deletes_spreadsheet():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    repo.ensure_container()
    sid = repo.spreadsheet_id
    assert sid in t._spreadsheets

    repo.teardown(drop_storage=True)
    assert sid not in t._spreadsheets


def test_teardown_default_keeps_storage():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    repo.ensure_container()
    sid = repo.spreadsheet_id
    repo.teardown(drop_storage=False)
    assert sid in t._spreadsseets if False else True  # noqa: E501
    assert sid in t._spreadsheets


# ---------- runtime ----------


def _seed(repo: GSheetRepo) -> None:
    repo.ensure_container()
    repo.ensure_table()
    repo.ensure_schema()
    repo.batch_create(
        [
            {"ID": "abc-1", "STATUS": "PENDING", "DOC_TOTAL_AMOUNT": "10",
             "ACTIVE": "TRUE", "DOC_DATE": "2025-01-01"},
            {"ID": "abc-2", "STATUS": "DONE", "DOC_TOTAL_AMOUNT": "42.5",
             "ACTIVE": "FALSE", "DOC_DATE": "2025-02-15",
             "סימון כרטסת עדכנית": "כן"},
            {"ID": "abc-3", "STATUS": "PENDING", "DOC_TOTAL_AMOUNT": "100"},
        ]
    )


def test_fetch_all_and_fetch_by_ids():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)

    rows = repo.fetch_all()
    assert {r["ID"] for r in rows} == {"abc-1", "abc-2", "abc-3"}

    by = repo.fetch_by_ids(["abc-2"])
    assert len(by) == 1
    assert by[0]["STATUS"] == "DONE"
    assert by[0]["סימון כרטסת עדכנית"] == "כן"


def test_batch_update_only_writes_changed_cells():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)

    res = repo.batch_update(
        [
            RowUpdate(pk="abc-1", changes={"STATUS": "DONE"}),
            RowUpdate(pk="abc-3", changes={"DOC_TOTAL_AMOUNT": "200"}),
            RowUpdate(pk="missing", changes={"STATUS": "X"}),
        ]
    )
    pks = {r["pk"] for r in res}
    assert pks == {"abc-1", "abc-3"}
    after = {r["ID"]: r for r in repo.fetch_all()}
    assert after["abc-1"]["STATUS"] == "DONE"
    assert after["abc-3"]["DOC_TOTAL_AMOUNT"] == "200"


def test_batch_create_appends_in_header_order_with_hebrew_column():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)

    out = repo.batch_create(
        [{"ID": "abc-9", "STATUS": "NEW", "סימון כרטסת עדכנית": "לא"}]
    )
    assert out[0]["pk"] == "abc-9"
    rows = repo.fetch_by_ids(["abc-9"])
    assert rows[0]["סימון כרטסת עדכנית"] == "לא"


def test_query_filter_with_eq_in_and_contains():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)

    out = repo.query(Query(mode="filter", filter={"STATUS": "PENDING"}))
    assert {r["ID"] for r in out} == {"abc-1", "abc-3"}

    out = repo.query(
        Query(mode="filter", filter={"ID": {"op": "in", "value": ["abc-2", "abc-3"]}})
    )
    assert {r["ID"] for r in out} == {"abc-2", "abc-3"}

    out = repo.query(
        Query(mode="filter", filter={"DOC_TOTAL_AMOUNT": {"op": "gt", "value": "50"}})
    )
    assert {r["ID"] for r in out} == {"abc-3"}


def test_query_pagination_via_offset_and_limit():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)
    p1 = repo.query(Query(mode="all", limit=2, offset=0))
    p2 = repo.query(Query(mode="all", limit=2, offset=2))
    assert len(p1) == 2
    assert len(p2) == 1
    assert {r["ID"] for r in p1 + p2} == {"abc-1", "abc-2", "abc-3"}


def test_get_columns_returns_live_header():
    t = FakeGSheetTransport()
    repo = GSheetRepo(_cfg(), transport=t, header_ttl_sec=0)
    _seed(repo)
    cols = repo.get_columns()
    assert cols[0] == "ID"
    assert "סימון כרטסת עדכנית" in cols


# ---------- error paths ----------


def test_repo_rejects_wrong_backend():
    with pytest.raises(Exception):
        GSheetRepo(
            RepoConfig(
                name="x",
                backend="supabase",
                primary_key="ID",
                columns=[ColumnDef(name="ID")],
                supabase={"table": "t"},
            ),
            transport=FakeGSheetTransport(),
        )


def test_spreadsheet_id_required_before_runtime():
    repo = GSheetRepo(_cfg(spreadsheet_id=None), transport=FakeGSheetTransport())
    with pytest.raises(Exception):
        repo.fetch_all()


def test_ensure_schema_requires_columns():
    cfg = _cfg(with_columns=False)
    repo = GSheetRepo(cfg, transport=FakeGSheetTransport())
    repo.ensure_container()
    repo.ensure_table()
    with pytest.raises(Exception):
        repo.ensure_schema()
