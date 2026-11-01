from incoming_documents.core.diff import compute_diff
from incoming_documents.core.models import ColumnDef, GSheetBackendConfig, RepoConfig
from incoming_documents.core.types import LogicalType


def _cfg(priority_cols=None):
    return RepoConfig(
        name="r",
        backend="gsheet",
        primary_key="ID",
        columns=[
            ColumnDef(name="ID"),
            ColumnDef(name="STATUS"),
            ColumnDef(name="DOC_TOTAL_AMOUNT", type=LogicalType.NUMERIC),
            ColumnDef(name="DOC_DATE", type=LogicalType.DATE),
            ColumnDef(name="EX_INVOICE_ID"),
            ColumnDef(name="סימון כרטסת עדכנית"),
        ],
        priority_sync_columns=priority_cols or [],
        gsheet=GSheetBackendConfig(spreadsheet_id="x", sheet_name="s"),
    )


def test_empty_incoming_yields_empty_diff():
    diff = compute_diff(current_rows=[], incoming=[], config=_cfg())
    assert diff.creates == [] and diff.updates == [] and diff.noops == []


def test_new_id_routes_to_create():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[],
        incoming=[{"ID": "a", "STATUS": "PENDING"}],
        config=cfg,
    )
    assert diff.creates == [{"ID": "a", "STATUS": "PENDING"}]
    assert diff.updates == []


def test_no_change_routes_to_noop():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[{"ID": "a", "STATUS": "OK"}],
        incoming=[{"ID": "a", "STATUS": "OK"}],
        config=cfg,
    )
    assert diff.noops == ["a"]
    assert diff.updates == []


def test_changed_field_routes_to_update_with_only_changed_keys():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[{"ID": "a", "STATUS": "OK", "DOC_TOTAL_AMOUNT": "100.00"}],
        incoming=[{"ID": "a", "STATUS": "DONE", "DOC_TOTAL_AMOUNT": 100}],
        config=cfg,
    )
    assert len(diff.updates) == 1
    assert diff.updates[0].pk == "a"
    # NUMERIC normalisation makes 100 == "100.00"; only STATUS differs.
    assert diff.updates[0].changes == {"STATUS": "DONE"}


def test_nulls_are_stripped_before_compare():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[{"ID": "a", "STATUS": "OK"}],
        incoming=[{"ID": "a", "STATUS": "OK", "DOC_DATE": None}],
        config=cfg,
    )
    assert diff.noops == ["a"]


def test_priority_sync_rule_added_when_priority_col_present():
    cfg = _cfg(priority_cols=["EX_INVOICE_ID"])
    diff = compute_diff(
        current_rows=[{"ID": "a", "STATUS": "OK"}],
        incoming=[{"ID": "a", "EX_INVOICE_ID": "INV-1"}],
        config=cfg,
    )
    assert len(diff.updates) == 1
    assert diff.updates[0].changes == {"EX_INVOICE_ID": "INV-1", "priority_sync": True}


def test_priority_sync_rule_skipped_when_no_priority_col():
    cfg = _cfg(priority_cols=["EX_INVOICE_ID"])
    diff = compute_diff(
        current_rows=[{"ID": "a", "STATUS": "OK"}],
        incoming=[{"ID": "a", "STATUS": "DONE"}],
        config=cfg,
    )
    assert diff.updates[0].changes == {"STATUS": "DONE"}


def test_hebrew_column_round_trips():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[{"ID": "a", "סימון כרטסת עדכנית": "v1"}],
        incoming=[{"ID": "a", "סימון כרטסת עדכנית": "v2"}],
        config=cfg,
    )
    assert diff.updates[0].changes == {"סימון כרטסת עדכנית": "v2"}


def test_missing_pk_routes_to_create():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[],
        incoming=[{"STATUS": "NEW"}],
        config=cfg,
    )
    assert diff.creates == [{"STATUS": "NEW"}]


def test_non_dict_item_skipped():
    cfg = _cfg()
    diff = compute_diff(
        current_rows=[],
        incoming=["not a dict", 42, None, {"ID": "a"}],
        config=cfg,
    )
    assert len(diff.skipped) == 3
    assert diff.creates == [{"ID": "a"}]


def test_apply_diff_via_in_memory_repo_round_trip():
    from incoming_documents.core.repo import InMemoryRepo

    cfg = _cfg(priority_cols=["EX_INVOICE_ID"])
    repo = InMemoryRepo(
        cfg,
        rows=[
            {"ID": "a", "STATUS": "OLD", "DOC_TOTAL_AMOUNT": "100"},
            {"ID": "b", "STATUS": "OLD"},
        ],
    )
    incoming = [
        {"ID": "a", "STATUS": "NEW"},                 # update
        {"ID": "b", "STATUS": "OLD"},                 # noop
        {"ID": "c", "STATUS": "FRESH"},               # create
        {"ID": "a", "EX_INVOICE_ID": "INV"},          # update + priority_sync
    ]
    current = repo.fetch_by_ids(["a", "b", "c"])
    diff = compute_diff(current_rows=current, incoming=incoming, config=cfg)

    repo.batch_update(diff.updates)
    repo.batch_create(diff.creates)

    rows = {r["ID"]: r for r in repo.fetch_all()}
    assert rows["a"]["STATUS"] == "NEW"
    assert rows["a"]["EX_INVOICE_ID"] == "INV"
    assert rows["a"]["priority_sync"] is True
    assert rows["b"]["STATUS"] == "OLD"
    assert rows["c"]["STATUS"] == "FRESH"
