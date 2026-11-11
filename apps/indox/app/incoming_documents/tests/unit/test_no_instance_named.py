"""A BFF call with no `?instance=` is NAMED in the log, and still answered (DGO-1792, stage one of two).

Without an instance every read and write lands on schema `public`, whose compat views are the first
client's books. Stage one names each such caller once per route and caller per ten minutes, so the
list is complete before stage two refuses the call with 400. What holds:
  1. a data route without an instance is named, with its method, route and caller — and answered as before;
  2. the same caller on the same route is named once per window, not on every poll;
  3. meta routes (health, openapi, the instance list, the registry's GET) are never named;
  4. a request that names its instance is never named.
"""
import logging

import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core.registry import RepoRegistry

P = "/incomingDocuments"
LOGGER = "incoming_documents.api"


@pytest.fixture()
def client(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = FakeGSheetTransport()
    cache: dict = {}

    def factory(cfg):
        if cfg.name not in cache:
            cache[cfg.name] = GSheetRepo(cfg, transport=transport, header_ttl_sec=0)
        return cache[cfg.name]

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(registry=reg, repo_factory=factory, url_prefix=P))
    return app.test_client()


def named(caplog):
    return [r.getMessage() for r in caplog.records if r.getMessage().startswith("indox-no-instance:")]


def test_a_data_route_without_instance_is_named_and_still_answered(client, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    # no spreadsheet_id: the fake creates one (201), as test_blueprint_skeleton does — a named id it does not
    # know is a 503 from provisioning, which would hide whether the call was answered
    body = {"name": "r1", "backend": "gsheet", "primary_key": "ID",
            "columns": [{"name": "ID"}, {"name": "STATUS"}], "gsheet": {"sheet_name": "Sheet1"}}
    r = client.post(P + "/repos", json=body, headers={"User-Agent": "chat-intake/1"})
    assert r.status_code == 201, r.json          # answered as before: stage one refuses nothing
    said = named(caplog)
    assert len(said) == 1, said
    assert "POST /repos" in said[0] and "chat-intake/1" in said[0] and "schema public" in said[0]


def test_the_same_caller_is_named_once_per_window(client, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    for _ in range(5):
        client.get(P + "/dashboard/stats", headers={"User-Agent": "timeline-lane"})
    assert len(named(caplog)) == 1
    client.get(P + "/dashboard/stats", headers={"User-Agent": "another-caller"})
    assert len(named(caplog)) == 2


@pytest.mark.parametrize("path", ["/health", "/openapi.json", "/repos", "/auth/me"])
def test_meta_routes_are_not_named(client, caplog, path):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    client.get(P + path)
    assert named(caplog) == []


def test_a_call_that_names_its_instance_is_not_named(client, caplog):
    caplog.set_level(logging.WARNING, logger=LOGGER)
    # no SQL transport in this fixture: the binder refuses the unknown instance, and names nothing
    client.get(P + "/dashboard/stats?instance=levi")
    assert named(caplog) == []
