import json
import os
from datetime import datetime

import pytest

from incoming_documents.core.errors import RepoAlreadyExists, RepoNotFound, ValidationError
from incoming_documents.core.models import ColumnDef, GSheetBackendConfig, RepoConfig
from incoming_documents.core.registry import RepoRegistry


def _cfg(name="r1"):
    return RepoConfig(
        name=name,
        backend="gsheet",
        primary_key="ID",
        columns=[ColumnDef(name="ID"), ColumnDef(name="STATUS")],
        gsheet=GSheetBackendConfig(spreadsheet_id="abc", sheet_name="Sheet1"),
    )


def test_create_get_list_delete(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    assert reg.list() == []
    cfg = reg.create(_cfg())
    assert isinstance(cfg.created_at, datetime)
    assert reg.get("r1").name == "r1"
    assert reg.has("r1") is True
    assert [c.name for c in reg.list()] == ["r1"]
    reg.delete("r1")
    assert reg.list() == []


def test_create_duplicate_rejected(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    reg.create(_cfg())
    with pytest.raises(RepoAlreadyExists):
        reg.create(_cfg())


def test_get_missing_raises(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    with pytest.raises(RepoNotFound):
        reg.get("nope")
    with pytest.raises(RepoNotFound):
        reg.delete("nope")


def test_atomic_write_and_hot_reload(tmp_path):
    path = tmp_path / "repos.json"
    reg_a = RepoRegistry(path)
    reg_b = RepoRegistry(path)
    reg_a.create(_cfg("r1"))
    # reg_b hasn't seen the file yet — it must hot-reload on next read.
    assert reg_b.has("r1") is True

    reg_a.create(_cfg("r2"))
    # mtime changed → reg_b sees both
    names = sorted(c.name for c in reg_b.list())
    assert names == ["r1", "r2"]


def test_invalid_json_rejected(tmp_path):
    p = tmp_path / "repos.json"
    p.write_text("{not json", encoding="utf-8")
    reg = RepoRegistry(p)
    with pytest.raises(ValidationError):
        reg.list()


def test_atomic_write_no_partial_file(tmp_path, monkeypatch):
    """Force the JSON dump to crash mid-write — the original file (if any)
    must remain intact, no partial ``repos.json`` may exist.
    """
    path = tmp_path / "repos.json"
    reg = RepoRegistry(path)
    reg.create(_cfg("good"))

    real_dump = json.dump

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(json, "dump", boom)
    with pytest.raises(RuntimeError):
        reg.create(_cfg("bad"))

    # Restore and re-read directly from disk: only "good" must be there.
    monkeypatch.setattr(json, "dump", real_dump)
    on_disk = json.loads(path.read_text(encoding="utf-8"))
    assert [r["name"] for r in on_disk] == ["good"]

    # And no leftover .tmp files
    leftovers = [n for n in os.listdir(tmp_path) if n.endswith(".tmp")]
    assert leftovers == []
