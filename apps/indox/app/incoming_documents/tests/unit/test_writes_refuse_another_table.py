"""A write names the table the screen shows, and the BFF refuses any table but the repo's own (DGO-1815).

The document browser shows any table of the instance (`?table=`); its writes used to name none, so an edit made on
a row of table B was applied to the documents table's row that merely shares its id. The write paths are the
documents repo's (its key, its columns, its router, its events), so now every write route — the batch upsert (PUT),
the single PATCH, the bulk edit, the dispatch, the drain and the archive move — answers 400 for another table and
writes nothing, there or in the repo's own table, while the repo's own table, named or not, writes as before.

The fake instance HOLDS the other table (`companies`) and lists it as information_schema would, so the old code's
write there — a CREATE through the documents repo's config — is what the refusal is measured against.
"""
import pytest
from flask import Flask

from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeSupabaseTransport, SupabaseRepo
from incoming_documents.core import RepoConfig, RepoRegistry

P = "/incomingDocuments"
REPO = {"name": "sb", "backend": "supabase", "primary_key": "ID",
        "columns": [{"name": "ID", "type": "string", "nullable": False}, {"name": "STATUS", "type": "string"}],
        "supabase": {"schema": "public", "table": "items"}}


class InstanceTransport(FakeSupabaseTransport):
    """The fake, answering the one SQL question repo_for asks: which base tables the schema holds."""

    def _exec_sql(self, sql):
        if "information_schema.tables" in sql:
            return [{"table_name": t} for (s, t) in self.tables if s == "public"]
        return []


@pytest.fixture()
def client(tmp_path):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = InstanceTransport()
    transport.create_table(schema="public", table="companies", primary_key="ID",
                           columns=[("ID", "text", False), ("STATUS", "text", True)])
    cache: dict[tuple, object] = {}

    def factory(cfg: RepoConfig):
        key = (cfg.name, cfg.supabase.schema_ if cfg.supabase else None, cfg.supabase.table if cfg.supabase else None)
        if key not in cache:
            r = SupabaseRepo(cfg, transport=transport)
            r.ensure_container()
            r.ensure_table()
            r.ensure_schema()
            cache[key] = r
        return cache[key]

    app = Flask(__name__)
    app.register_blueprint(create_blueprint(registry=reg, repo_factory=factory, url_prefix=P))
    app.config.update(TESTING=True)
    c = app.test_client()
    assert c.post(P + "/repos", json=REPO).status_code == 201
    r = c.put(P + "/repos/sb/documents", json=[{"ID": "a", "STATUS": "X"}, {"ID": "b", "STATUS": "Y"}])
    assert r.status_code == 200, r.get_json()
    c.transport = transport
    return c


def status_of(c, doc_id):
    r = c.get(P + f"/repos/sb/documents/{doc_id}")
    assert r.status_code == 200, r.get_json()
    return r.get_json()["row"]["STATUS"]


def refused(r):
    body = r.get_json() or {}
    return r.status_code == 400 and body.get("error") == "validation_error" and "'companies'" in body.get("message", "")


WRITES = [
    ("put", "/repos/sb/documents", [{"ID": "a", "STATUS": "Q"}]),
    ("patch", "/repos/sb/documents/a", {"STATUS": "Q"}),
    ("post", "/repos/sb/documents/bulk", {"ids": ["a", "b"], "patch": {"STATUS": "QUEUED"}}),
    ("post", "/repos/sb/documents/dispatch", {"ids": ["a"], "action": "extract_base_doc"}),
    ("post", "/repos/sb/documents/archive", {"ids": ["a"]}),
    ("post", "/pipeline/drain", {"mode": "ids", "repo": "sb", "ids": ["a"]}),
]


@pytest.mark.parametrize("method,path,body", WRITES, ids=[w[1] for w in WRITES])
def test_a_write_to_another_table_is_refused_and_writes_nothing(client, method, path, body):
    r = getattr(client, method)(P + path + "?table=companies", json=body)
    assert refused(r), (r.status_code, r.get_json())
    assert (status_of(client, "a"), status_of(client, "b")) == ("X", "Y")
    assert client.transport.tables[("public", "companies")] == [], "nothing written in the other table either"


def test_the_other_table_is_still_read(client):
    # reading another table of the instance is what the switcher is for; only writing it is refused
    r = client.post(P + "/repos/sb/documents/query?table=companies", json={})
    assert r.status_code == 200, r.get_json()


def test_the_repos_own_table_named_or_not_writes_as_before(client):
    assert client.patch(P + "/repos/sb/documents/a?table=items", json={"STATUS": "Q"}).status_code == 200
    assert status_of(client, "a") == "Q"
    assert client.patch(P + "/repos/sb/documents/b", json={"STATUS": "R"}).status_code == 200
    assert status_of(client, "b") == "R"
    r = client.put(P + "/repos/sb/documents?table=items", json=[{"ID": "a", "STATUS": "S"}])
    assert r.status_code == 200, r.get_json()
    assert status_of(client, "a") == "S"
