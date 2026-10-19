import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core.registry import RepoRegistry


@pytest.fixture()
def client(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = FakeGSheetTransport()
    cache: dict[str, GSheetRepo] = {}

    def factory(cfg):
        if cfg.name not in cache:
            cache[cfg.name] = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
        return cache[cfg.name]

    app = Flask(__name__)
    app.register_blueprint(
        create_blueprint(
            registry=reg, repo_factory=factory, url_prefix="/incomingDocuments"
        )
    )
    return app.test_client()


def test_health(client):
    r = client.get("/incomingDocuments/health")
    assert r.status_code == 200
    assert r.json["status"] == "ok"


def test_repos_lifecycle(client):
    # initially empty
    assert client.get("/incomingDocuments/repos").json["repos"] == []

    body = {
        "name": "r1",
        "backend": "gsheet",
        "primary_key": "ID",
        "columns": [{"name": "ID"}, {"name": "STATUS"}],
        "gsheet": {"sheet_name": "Sheet1"},
    }
    r = client.post("/incomingDocuments/repos", json=body)
    assert r.status_code == 201, r.json
    assert r.json["repo"]["name"] == "r1"

    # duplicate -> 409
    r = client.post("/incomingDocuments/repos", json=body)
    assert r.status_code == 409
    assert r.json["error"] == "repo_already_exists"

    # get
    r = client.get("/incomingDocuments/repos/r1")
    assert r.status_code == 200
    assert r.json["repo"]["primary_key"] == "ID"

    # not found
    r = client.get("/incomingDocuments/repos/missing")
    assert r.status_code == 404
    assert r.json["error"] == "repo_not_found"

    # validation error
    r = client.post("/incomingDocuments/repos", json={"name": "x"})
    assert r.status_code == 400
    assert r.json["error"] == "validation_error"

    # delete
    assert client.delete("/incomingDocuments/repos/r1").status_code == 200
    assert client.get("/incomingDocuments/repos").json["repos"] == []
