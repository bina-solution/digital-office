"""GET /timeline/spans with no instance is served for every enabled production instance, each span saying which (DGO-1815).

any-concurrency's INDOX lane cannot name an instance; the call used to read INDOX's default schema only (the first
client's books). What holds, with the span readers stubbed: each instance's reads run with ITS schema bound
(`g.indox_schema`, what `_request_schema()` answers) and the request's own is restored after each, a failing one
included; every span is tagged `meta.instance`; with several instances each span id carries its instance
(any-concurrency keys spans by id); one instance's failure blanks only that instance and is named in `errors`, all
failing reads as unreachable; a named instance is served alone with its ids as before; the registry's rows reach the
rule (the standing test tenant skipped), and a failed registry read serves the last good list rather than «none»
(which would re-key every span); an unreadable registry keeps the old unlabelled answer; and the instance-less call
is not named in the no-instance log.
"""
import logging
from types import SimpleNamespace

import pytest
from flask import Flask, g

import incoming_documents.api as api
from incoming_documents.api import create_blueprint
from incoming_documents.backends import FakeGSheetTransport, GSheetRepo
from incoming_documents.core.models import ColumnDef, GSheetBackendConfig, RepoConfig
from incoming_documents.core.registry import RepoRegistry

P = "/incomingDocuments"
TWO = [("example", "indox_example"), ("exampleu", "indox_exampleu")]
REGISTRY = [{"id": "example", "schema_name": "indox_example", "enabled": True, "purpose": ""},
            {"id": "test", "schema_name": "indox_test", "enabled": True, "purpose": "test"},
            {"id": "exampleu", "schema_name": "indox_exampleu", "enabled": True, "purpose": ""}]


class FakeSql:
    """The registry as the BFF's SQL transport answers it: the enabled list, and one instance's schema."""

    def __init__(self):
        self.rows, self.fail, self.reads = list(REGISTRY), False, 0

    def _exec_sql(self, sql):
        if "where enabled" in sql:
            self.reads += 1
            if self.fail:
                raise RuntimeError("registry down")
            if self.rows is None:                             # the transport's answer to a body it cannot parse
                return None
            return [dict(r) for r in self.rows]
        for r in self.rows or REGISTRY:                       # _instance_schema: «… where id = '<id>'»
            if f"'{r['id']}'" in sql:
                return [{"schema_name": r["schema_name"]}]
        return []


def make_client(tmp_path, monkeypatch, sql=None):
    reg = RepoRegistry(tmp_path / "repos.json")
    transport = FakeGSheetTransport()
    if sql is not None:                                       # a registered repo whose transport speaks SQL
        reg.create(RepoConfig(name="r1", backend="gsheet", primary_key="ID",
                              columns=[ColumnDef(name="ID"), ColumnDef(name="STATUS")],
                              gsheet=GSheetBackendConfig(spreadsheet_id="abc", sheet_name="Sheet1")))

    def factory(cfg):
        if sql is not None:
            return SimpleNamespace(transport=sql)
        return GSheetRepo(cfg, transport=transport, header_ttl_sec=0)

    seen, fail_on = [], set()

    def reader(kind):
        def read(_transport, *args, **kwargs):
            schema = getattr(g, "indox_schema", None)
            seen.append((kind, schema))
            if schema in fail_on:
                raise RuntimeError(f"no {kind} table in {schema}")
            return [{"id": f"{kind}:D1", "svc": kind, "svcid": "D1", "s": 1, "e": 2, "meta": {"k": "v"}}]
        return read

    monkeypatch.setattr(api, "_scope", lambda _reg: SimpleNamespace(name="main", doc_table="incoming_documents"))
    monkeypatch.setattr(api, "_sync_transport", lambda: object())
    monkeypatch.setattr(api, "_timeline_doc_spans", reader("doc"))
    monkeypatch.setattr(api, "_timeline_action_spans", reader("action"))
    monkeypatch.setattr(api, "_timeline_sync_spans", reader("sync"))
    app = Flask(__name__)
    app.register_blueprint(create_blueprint(registry=reg, repo_factory=factory, url_prefix=P))

    @app.after_request
    def schema_after(resp):                      # what the request's own schema is once the endpoint returns
        resp.headers["X-Bound-After"] = str(getattr(g, "indox_schema", None))
        return resp

    c = app.test_client()
    c.seen, c.fail_on = seen, fail_on
    return c


@pytest.fixture()
def client(tmp_path, monkeypatch):
    return make_client(tmp_path, monkeypatch)


def test_no_instance_serves_every_enabled_one_with_its_schema_bound_and_restored(client, monkeypatch):
    monkeypatch.setattr(api, "timeline_targets", lambda named, bound, rows: TWO)
    r = client.get(P + "/timeline/spans?hours=1")
    assert r.status_code == 200, r.json
    body = r.json
    assert body["reachable"] is True and "errors" not in body
    assert {s["meta"]["instance"] for s in body["spans"]} == {"example", "exampleu"}
    assert all(s["meta"]["k"] == "v" for s in body["spans"]), "a span's own meta is kept"
    assert [sch for _, sch in client.seen] == ["indox_example"] * 3 + ["indox_exampleu"] * 3
    assert r.headers["X-Bound-After"] == "None", "the request's own bound schema is restored"


def test_several_instances_prefix_each_span_id_one_does_not(client, monkeypatch):
    monkeypatch.setattr(api, "timeline_targets", lambda named, bound, rows: TWO)
    ids = {s["id"] for s in client.get(P + "/timeline/spans?hours=1&rows=doc").json["spans"]}
    assert ids == {"example:doc:D1", "exampleu:doc:D1"}, "two instances' doc:D1 must not overwrite each other"
    monkeypatch.setattr(api, "timeline_targets", lambda named, bound, rows: TWO[:1])
    ids = {s["id"] for s in client.get(P + "/timeline/spans?hours=1&rows=doc").json["spans"]}
    assert ids == {"doc:D1"}, "one instance: ids as before, so a lane's spans keep their identity"


def test_one_instance_failing_blanks_only_that_one(client, monkeypatch):
    monkeypatch.setattr(api, "timeline_targets", lambda named, bound, rows: TWO)
    client.fail_on.add("indox_exampleu")
    r = client.get(P + "/timeline/spans?hours=1&rows=doc")
    body = r.json
    assert body["reachable"] is True
    assert {s["meta"]["instance"] for s in body["spans"]} == {"example"}
    assert len(body["errors"]) == 1 and body["errors"][0].startswith("exampleu: ")
    assert r.headers["X-Bound-After"] == "None", "restored after a failing instance too"
    client.fail_on.add("indox_example")
    body = client.get(P + "/timeline/spans?hours=1&rows=doc").json
    assert body["reachable"] is False and body["spans"] == []


def test_a_named_instance_is_served_alone_its_ids_as_before(tmp_path, monkeypatch):
    sql = FakeSql()
    c = make_client(tmp_path, monkeypatch, sql)
    r = c.get(P + "/timeline/spans?hours=1&rows=doc&instance=exampleu")
    assert r.status_code == 200, r.json
    assert [s["id"] for s in r.json["spans"]] == ["doc:D1"]
    assert r.json["spans"][0]["meta"]["instance"] == "exampleu"
    assert [sch for _, sch in c.seen] == ["indox_exampleu"]
    assert sql.reads == 0, "a named call does not read the enabled list"


def test_the_registry_rows_reach_the_rule_and_a_failed_read_serves_the_last_good_list(tmp_path, monkeypatch):
    sql = FakeSql()
    c = make_client(tmp_path, monkeypatch, sql)
    clock = [1000.0]
    monkeypatch.setattr(api.time, "time", lambda: clock[0])
    ids = lambda: sorted(s["id"] for s in c.get(P + "/timeline/spans?hours=1&rows=doc").json["spans"])
    assert ids() == ["example:doc:D1", "exampleu:doc:D1"], "the standing test tenant is not served"
    sql.fail, clock[0] = True, clock[0] + 61                  # the cache expired, and the registry is down
    assert ids() == ["example:doc:D1", "exampleu:doc:D1"], "the last good list, never a re-keyed «none»"
    reads = sql.reads
    clock[0] += 5
    ids()
    assert sql.reads == reads, "while it is down it is asked at most every 10 s"
    sql.fail = False
    clock[0] += 6                                             # the failure was not cached as an answer: it reads
    ids()
    assert sql.reads == reads + 1
    sql.rows, clock[0] = None, clock[0] + 61                  # a body the transport could not parse: not «none»
    assert ids() == ["example:doc:D1", "exampleu:doc:D1"]


def test_an_unread_registry_keeps_the_old_unlabelled_answer(client):
    # the fake registry has no SQL transport: _enabled_instance_rows() answers [] → the default schema, unlabelled
    r = client.get(P + "/timeline/spans?hours=1")
    assert r.status_code == 200, r.json
    assert r.json["spans"] and all("instance" not in s["meta"] for s in r.json["spans"])
    assert {s["id"] for s in r.json["spans"]} == {"doc:D1", "action:D1", "sync:D1"}


def test_the_instance_less_timeline_is_not_named_as_a_default(client, caplog):
    caplog.set_level(logging.WARNING, logger="incoming_documents.api")
    client.get(P + "/timeline/spans?hours=1", headers={"User-Agent": "any-concurrency"})
    assert not [m for m in (rec.getMessage() for rec in caplog.records) if m.startswith("indox-no-instance:")]
