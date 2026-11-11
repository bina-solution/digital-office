"""An app's operations, declared once (DGO-1244): validate() refuses what the structural walk cannot, and
ops_registry() compiles .generated/registry/ops.json.

    python3 platform/manager/test_ops.py      (or: python -m pytest platform/manager/test_ops.py -q)

The native twin (packaging/dgo internal/compiler ops.go) says the same lines and writes the same file
(ops_test.go holds the same cases and the same expected JSON). On the code before DGO-1244 every case here fails:
`ops` is an unknown field, and there is no ops_registry.
"""
import atexit
import importlib.util
import json
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_ops", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_ops"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="dgo1244-"))
atexit.register(shutil.rmtree, TMP, True)          # under pytest too, which never calls main()
CAP = [{"name": "llm", "type": "protocol", "endpoint": "http://x:1"}]


def app(aid="a", **extra):
    m = {"id": aid, "layer": 3, "title": {"he": "x"}, "kind": "service", "_dir": TMP}
    m.update(extra)
    return {aid: m}


def op(**kw):
    return {"id": "models", "method": "GET", "path": "/api/tags", "access": "read"} | kw


def errors_of(cat):
    errs, _ = rc.validate(cat)       # must not raise
    return errs


def test_a_well_formed_op_is_valid():
    assert errors_of(app(capabilities=CAP, ops=[op(verb="models"), op(id="show", method="POST", path="/api/show",
                                                                       verb="show")])) == []


def test_an_op_missing_a_required_key_or_with_a_key_of_its_own_is_said():
    bad = {"id": "x", "method": "GET", "path": "/p", "colour": "red", "Note": 1}
    assert errors_of(app(capabilities=CAP, ops=[bad])) == [
        "a: ops[0] has no 'access'",
        "a: ops[0] has the key 'Note', which an op does not have",
        "a: ops[0] has the key 'colour', which an op does not have"]


def test_an_id_and_a_path_are_held_to_their_patterns():
    assert errors_of(app(capabilities=CAP, ops=[op(id="Not An Id", path="api/x")])) == [
        "a: ops[0] id 'Not An Id' is not an op's name (a-z, 0-9, -)",
        "a: ops[0] path 'api/x' does not start at the endpoint's root (/)"]


def test_an_id_twice_is_said_at_the_second():
    assert errors_of(app(capabilities=CAP, ops=[op(), op()])) == [
        "a: ops[1] 'models' is declared twice — an op's id is its name in the answer"]


def test_the_endpoint_that_serves_an_op_must_be_found():
    assert errors_of(app(ops=[op()])) == [
        "a: ops[0] names no capability, and the app has 0 with an endpoint — name the one that serves it"]
    two = CAP + [{"name": "llm2", "type": "protocol", "endpoint": "http://y:2"}]
    assert errors_of(app(capabilities=two, ops=[op()])) == [
        "a: ops[0] names no capability, and the app has 2 with an endpoint — name the one that serves it"]
    assert errors_of(app(capabilities=two, ops=[op(capability="llm2")])) == []
    assert errors_of(app(capabilities=CAP + [{"name": "quiet", "type": "protocol"}], ops=[op(capability="quiet")])) == [
        "a: ops[0] capability 'quiet' is not one of this app's capabilities with an endpoint"]


def test_a_verb_is_a_name_and_validate_reads_no_hook_file():
    assert errors_of(app(capabilities=CAP, ops=[op(verb="../models")])) == [
        "a: ops[0] verb '../models' is not a verb's name (a-z, 0-9, -)"]
    # a verb with no file in hooks/ is DGO-1246's gate to say, on a whole checkout: validate also runs on trees that
    # hold a manifest without its hooks (the store's index, the twins' test trees)
    assert errors_of(app(capabilities=CAP, ops=[op(verb="gone")])) == []


def test_the_type_walk_says_a_method_outside_the_list():
    assert errors_of(app(capabilities=CAP, ops=[op(method="FETCH")])) == [
        "a: field 'ops'[0].method must be one of GET|POST|PUT|PATCH|DELETE, got 'FETCH'"]


REGISTRY = {
    "a": [{"id": "models", "method": "GET", "path": "/api/tags", "endpoint": "http://x:1", "access": "read",
           "verb": "models", "summary": {"en": "the models", "he": "המודלים"}},
          {"id": "unload", "method": "POST", "path": "/api/generate", "endpoint": "http://x:1", "access": "write"}],
    "b": [{"id": "ping", "method": "GET", "path": "/ping", "endpoint": "http://b2:9", "access": "read",
           "ui": "the refresh button"}],
}


def registry_catalog():
    cat = {}
    cat |= app("b", capabilities=[{"name": "one", "endpoint": "http://b1:9"}, {"name": "two", "endpoint": "http://b2:9"}],
               ops=[{"ui": "the refresh button", "access": "read", "path": "/ping", "method": "GET", "id": "ping",
                     "capability": "two", "verb": None}])
    cat |= app("a", capabilities=CAP,
               ops=[op(verb="models", summary={"en": "the models", "he": "המודלים"}),
                    {"id": "unload", "method": "POST", "path": "/api/generate", "access": "write"}])
    cat |= app("c", capabilities=CAP)                       # no ops: not in the file
    cat |= app("d", capabilities=CAP, ops=[op()])           # not enabled: not in the file
    return cat


def test_the_registry_holds_every_enabled_apps_ops_in_a_fixed_shape():
    got = rc.ops_registry(registry_catalog(), ["b", "c", "a"])
    assert got == REGISTRY, got
    # the spelling: app ids sorted, an op's keys in OP_KEYS order, its summary in the manifest's own order
    text = json.dumps(got, indent=2, ensure_ascii=False)
    assert text == json.dumps(REGISTRY, indent=2, ensure_ascii=False), text
    assert list(got) == ["a", "b"] and list(got["a"][0]) == ["id", "method", "path", "endpoint", "access", "verb",
                                                              "summary"]


def main():
    fails = 0
    try:
        for name, fn in sorted((n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)):
            try:
                fn()
                print("PASS  " + name)
            except Exception as e:   # noqa: BLE001 — every failure is reported, then the next test runs
                fails += 1
                print(f"FAIL  {name}\n        {type(e).__name__}: {e}")
    finally:
        shutil.rmtree(TMP, ignore_errors=True)
    print("\nall passed" if not fails else f"\n{fails} failed")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
