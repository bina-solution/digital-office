"""Cross-backend route smoke test: identical client behaviour against
both GSheet and Supabase backends."""
from __future__ import annotations

import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import (
    FakeGSheetTransport,
    FakeSupabaseTransport,
    GSheetRepo,
    SupabaseRepo,
)
from incoming_documents.core import RepoConfig, RepoRegistry


GSHEET_REPO = {
    "name": "gs",
    "backend": "gsheet",
    "primary_key": "ID",
    "columns": [
        {"name": "ID", "type": "string", "nullable": False},
        {"name": "STATUS", "type": "string"},
    ],
    "gsheet": {"sheet_name": "Sheet1"},
}

SUPABASE_REPO = {
    "name": "sb",
    "backend": "supabase",
    "primary_key": "ID",
    "columns": [
        {"name": "ID", "type": "string", "nullable": False},
        {"name": "STATUS", "type": "string"},
    ],
    "supabase": {"schema": "public", "table": "items"},
}


@pytest.fixture
def app(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    gtransport = FakeGSheetTransport()
    stransport = FakeSupabaseTransport()
    cache: dict[str, object] = {}

    def factory(cfg: RepoConfig):
        if cfg.name in cache:
            return cache[cfg.name]
        if cfg.backend == "gsheet":
            r = GSheetRepo(cfg, transport=gtransport, header_ttl_sec=0)
        else:
            r = SupabaseRepo(cfg, transport=stransport)
        r.ensure_container()
        r.ensure_table()
        r.ensure_schema()
        cache[cfg.name] = r
        return r

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            registry=reg, repo_factory=factory, url_prefix="/incomingDocuments"
        )
    )
    app.config.update(TESTING=True)
    return app


@pytest.mark.parametrize("body", [GSHEET_REPO, SUPABASE_REPO])
def test_documents_roundtrip_per_backend(app, body):
    client = app.test_client()
    r = client.post("/incomingDocuments/repos", json=body)
    assert r.status_code == 201, r.get_json()

    name = body["name"]
    r = client.put(
        f"/incomingDocuments/repos/{name}/documents",
        json=[{"ID": "a", "STATUS": "X"}, {"ID": "b", "STATUS": "Y"}],
    )
    body_resp = r.get_json()
    assert r.status_code == 200, body_resp
    assert body_resp["stats"]["created"] == 2

    r = client.put(
        f"/incomingDocuments/repos/{name}/documents",
        json=[{"ID": "a", "STATUS": "X"}, {"ID": "b", "STATUS": "Z"}],
    )
    body_resp = r.get_json()
    assert body_resp["stats"]["updated"] == 1
    assert body_resp["stats"]["noop"] == 1

    r = client.post(
        f"/incomingDocuments/repos/{name}/documents/query",
        json={"mode": "by_ids", "ids": ["b"]},
    )
    body_resp = r.get_json()
    assert body_resp["count"] == 1
    assert body_resp["rows"][0]["STATUS"] == "Z"
