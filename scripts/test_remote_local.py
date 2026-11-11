"""`bbox <app> api` (DGO-1245): remote.py's office `.` (this office) — where an app answers, read from its manifest.

    python3 scripts/test_remote_local.py      (or: python -m pytest scripts/test_remote_local.py -q)

A fixture checkout (apps/ and platform-base/ with a manifest each) stands in for the office's own. The request
itself is remote.py's existing call: measured live on the MacBook, `bbox console api GET /healthz` → HTTP 200
through a container on the office network. On the code before DGO-1245 every case here but the URL refusal fails:
there is no office `.`, and no resolve_local (the URL refusal is cmd_call's own, older rule, kept).
"""
import atexit
import contextlib
import importlib.util
import io
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("remote_local_test", HERE / "remote.py")
remote = importlib.util.module_from_spec(spec)
sys.modules["remote_local_test"] = remote
spec.loader.exec_module(remote)

TMP = pathlib.Path(tempfile.mkdtemp(prefix="dgo1245-"))
atexit.register(shutil.rmtree, TMP, True)


def put(rel, manifest):
    p = TMP / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(manifest) if not isinstance(manifest, str) else manifest, encoding="utf-8")


put("apps/one/app.json", {"id": "one", "cli": {"alias": "uno"},
                          "capabilities": [{"name": "llm", "endpoint": "http://one:1/"}],
                          "ops": [{"id": "tags", "method": "GET", "path": "/api/tags", "access": "read",
                                   "verb": "tags", "summary": {"en": "the tags"}}]})
put("apps/two/app.json", {"id": "two", "capabilities": [{"name": "a", "endpoint": "http://two-a:2"},
                                                         {"name": "b", "endpoint": "http://two-b:3"},
                                                         {"name": "quiet"}]})
put("apps/three/app.json", {"id": "three", "routing": [{"host": "three", "port": 8080},
                                                       {"host": "three-lan", "port": 8080},
                                                       {"host": "side", "port": 9000, "service": "three-side"}]})
put("apps/none/app.json", {"id": "none"})
put("apps/same/app.json", {"id": "same", "capabilities": [{"name": "p", "endpoint": "http://same:7"},
                                                           {"name": "q", "endpoint": "http://same:7/"},
                                                           {"name": "db", "endpoint": "postgres://same-db:5432"},
                                                           {"name": "sock", "endpoint": "unix:///var/run/docker.sock"}]})
put("apps/vault/app.json", {"id": "vault", "capabilities": [{"name": "secrets", "endpoint": "http://vault:8990"},
                                                            {"name": "instances", "endpoint": "http://vault:8990"}]})
put("apps/broken/app.json", "{not json")
put("platform-base/base/app.json", {"id": "base", "capabilities": [{"name": "x", "endpoint": "http://base:9"}]})
remote.REPO = TMP


def refused(fn, *a):
    try:
        fn(*a)
    except remote.RemoteError as e:
        return e.code, e.message
    raise AssertionError(f"{fn.__name__}{a} did not refuse")


def test_an_app_is_found_by_its_id_or_its_cli_alias_in_either_root_and_a_broken_manifest_is_passed_over():
    assert remote.local_manifest("one")["id"] == "one" and remote.local_manifest("uno")["id"] == "one"
    assert remote.local_manifest("base")["_root"] == "platform-base"
    code, msg = refused(remote.local_manifest, "nobody")
    assert code == remote.EXIT_USAGE and "'nobody'" in msg, msg


def test_its_doors_are_its_endpoints_or_else_its_routed_ports():
    assert remote.local_doors(remote.local_manifest("one")) == [("llm", "http://one:1")]
    assert remote.local_doors(remote.local_manifest("two")) == [("a", "http://two-a:2"), ("b", "http://two-b:3")]
    # no endpoint: the routed service and port, each address once, the service defaulting to the app's id
    assert remote.local_doors(remote.local_manifest("three")) == [("three", "http://three:8080"),
                                                                  ("side", "http://three-side:9000")]
    assert remote.local_doors(remote.local_manifest("none")) == []
    # one door per address (a trailing slash is the same address), and only http(s): postgres:// and unix:// are not
    assert remote.local_doors(remote.local_manifest("same")) == [("p", "http://same:7")]
    assert remote.resolve_local("same")["url"] == "http://same:7"


def test_the_vault_is_never_called_by_a_generic_call():
    for door in (None, "secrets", "instances"):    # by either name: it is one address
        code, msg = refused(remote.resolve_local, "vault", door) if door else refused(remote.resolve_local, "vault")
        assert code == remote.EXIT_USAGE and "the vault" in msg and "print a secret" in msg, (door, msg)


def test_a_call_to_this_office_is_always_made_inside_the_network():
    handed, made = [], []
    saved = (remote._delegate, remote._resolves, remote.http)
    remote._delegate = lambda argv, resolved, timeout: handed.append((argv, resolved["url"])) or 0
    remote._resolves = lambda host: True          # a short name the host resolves too (a search domain)
    remote.http = lambda *a, **k: made.append(a) or (200, {}, b"")
    try:
        rc = remote.main([".", "one", "/api/tags"])
    finally:
        remote._delegate, remote._resolves, remote.http = saved
    assert rc == 0 and made == [] and handed and handed[0][1] == "http://one:1", (rc, made, handed)
    assert handed[0][0][:3] == [".", "one", "/api/tags"], handed


def test_one_door_is_the_call_and_several_are_named_by_capability():
    r = remote.resolve_local("uno")
    assert (r["office"], r["alias"], r["url"], r["api"], r["instances"]) == (".", "one", "http://one:1", False, [])
    code, msg = refused(remote.resolve_local, "two")
    assert code == remote.EXIT_USAGE and "2 doors (a, b)" in msg and "--capability" in msg, msg
    assert remote.resolve_local("two", "b")["url"] == "http://two-b:3"
    code, msg = refused(remote.resolve_local, "two", "c")
    assert "no door 'c'" in msg and "a, b" in msg, msg
    code, msg = refused(remote.resolve_local, "none")
    assert "no capability endpoint and no routed port" in msg, msg


def test_the_app_without_a_path_lists_its_doors_and_its_ops():
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = remote.main([".", "uno"])
    text = out.getvalue()
    assert rc == 0, text
    assert "door        llm" in text and "http://one:1" in text, text
    assert "op          tags" in text and "GET /api/tags" in text and "bbox one tags" in text, text
    assert "bbox one api <METHOD> <path>" in text, text


def test_a_path_that_is_a_url_is_refused_before_anything_is_resolved():
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        rc = remote.main([".", "one", "http://elsewhere/x"])
    assert rc == remote.EXIT_USAGE and "PATH" in err.getvalue(), err.getvalue()


def main():
    fails = 0
    for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
        try:
            fn()
            print("PASS  " + name)
        except Exception as e:   # noqa: BLE001 — every failure is reported, then the next test runs
            fails += 1
            print(f"FAIL  {name}\n        {type(e).__name__}: {e}")
    print("\nall passed" if not fails else f"\n{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
