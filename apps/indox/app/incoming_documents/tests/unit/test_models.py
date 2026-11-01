import pytest
from pydantic import ValidationError as PydanticError

from incoming_documents.core.models import (
    ColumnDef,
    GSheetBackendConfig,
    Query,
    RepoConfig,
    SupabaseBackendConfig,
)
from incoming_documents.core.types import LogicalType


def _gsheet_cfg(**overrides):
    base = dict(
        name="prod_gsheet",
        backend="gsheet",
        primary_key="ID",
        columns=[ColumnDef(name="ID"), ColumnDef(name="STATUS")],
        gsheet=GSheetBackendConfig(spreadsheet_id="abc", sheet_name="Sheet1"),
    )
    base.update(overrides)
    return RepoConfig(**base)


def test_repo_config_happy_path():
    cfg = _gsheet_cfg()
    assert cfg.name == "prod_gsheet"
    assert cfg.kafka.partitions == 3


def test_repo_config_requires_backend_block():
    with pytest.raises(PydanticError):
        RepoConfig(name="x", backend="gsheet", primary_key="ID")


def test_repo_config_pk_must_be_in_columns():
    with pytest.raises(PydanticError):
        RepoConfig(
            name="x",
            backend="gsheet",
            primary_key="ID",
            columns=[ColumnDef(name="OTHER")],
            gsheet=GSheetBackendConfig(spreadsheet_id="a", sheet_name="s"),
        )


def test_repo_config_rejects_duplicate_columns():
    with pytest.raises(PydanticError):
        RepoConfig(
            name="x",
            backend="gsheet",
            primary_key="ID",
            columns=[ColumnDef(name="ID"), ColumnDef(name="ID")],
            gsheet=GSheetBackendConfig(spreadsheet_id="a", sheet_name="s"),
        )


def test_repo_config_supabase_with_alias_schema():
    cfg = RepoConfig(
        name="prod_supabase",
        backend="supabase",
        primary_key="ID",
        columns=[ColumnDef(name="ID", type=LogicalType.TEXT)],
        supabase=SupabaseBackendConfig(table="incoming_documents"),
    )
    dumped = cfg.model_dump(by_alias=True)
    assert dumped["supabase"]["schema"] == "public"


def test_query_modes():
    Query(mode="all")
    Query(mode="by_ids", ids=["a", "b"])
    Query(mode="filter", filter={"STATUS": "OK"})
    with pytest.raises(PydanticError):
        Query(mode="by_ids")
    with pytest.raises(PydanticError):
        Query(mode="filter")
