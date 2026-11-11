"""A malformed manifest is refused BY NAME — never a traceback (DGO-612).

    python3 platform/manager/test_validate_refusals.py      (or: python -m pytest platform/manager/test_validate_refusals.py -q)

validate() is the compiler's first word on an app, and three manifest mistakes made it die instead:
  * a capability with no `name` — `c["name"]`, a KeyError;
  * `"compose": 5` — the path join, a TypeError;
  * an id YAML does not read as text (`on`, `yes`, … `null`) — it validated, and then `plan` sorted the state's
    key True (or None) among the ids and died there; the state can never name such an app.
Each is now one line that names the app and what is wrong; the type check's own line still says a wrong type.
The native twin (packaging/dgo internal/compiler validate.go) says the same lines (readverbs_test.go).
On the code before DGO-612 the first two raise and the third passes.
"""
import importlib.util
import pathlib
import shutil
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent


def _load():
    spec = importlib.util.spec_from_file_location("reconcile_validate_refusals", HERE / "reconcile.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["reconcile_validate_refusals"] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load()
TMP = pathlib.Path(tempfile.mkdtemp(prefix="dgo612-"))
(TMP / "c.yml").write_text("services:\n  x: {image: x}\n")


def app(aid, **extra):
    m = {"id": aid, "layer": 3, "title": {"he": "x"}, "kind": "service", "_dir": TMP}
    m.update(extra)
    return {aid: m}


def errors_of(cat):
    errs, provided = rc.validate(cat)       # must not raise
    return errs, provided


def test_a_capability_with_no_name_is_said():
    errs, provided = errors_of(app("nameless", capabilities=[{"type": "protocol"}]))
    assert "nameless: capabilities[0] has no name — nothing can `use` it" in errs, errs
    assert provided == {}


def test_a_capability_name_that_is_not_text_is_the_type_checks_to_say():
    errs, provided = errors_of(app("listname", capabilities=[{"name": ["x"], "type": "protocol"}]))
    assert any("listname: field 'capabilities'[0].name must be string" in e for e in errs), errs
    assert provided == {}


def test_a_compose_that_is_not_a_path_is_the_type_checks_to_say():
    errs, _ = errors_of(app("num", compose=5))
    assert any(e.startswith("num: field 'compose' must be string|null, got int") for e in errs), errs
    assert not any("not found" in e for e in errs), errs


def test_an_id_yaml_does_not_read_as_text_is_refused():
    for aid in ("yes", "no", "on", "off", "true", "false", "null"):
        errs, _ = errors_of(app(aid, compose="c.yml"))
        assert any(e.startswith(f"{aid}: id '{aid}' is a word YAML does not read as text") for e in errs), (aid, errs)


PAGES = ("meetings", "tasks", "mail", "drive", "ai", "notes", "services", "documents", "recording", "browser",
         "concurrency", "base")


def test_a_page_outside_the_owners_twelve_is_refused():
    # DGO-1042: the app names its page of the product; a page the owner did not name is refused by name, the
    # schema's own list in the line (a typo, a page invented on the spot, the case of the owner's word changed)
    for bad in ("gallery", "Meetings", ""):
        errs, _ = errors_of(app("paged", compose="c.yml", page=bad))
        assert errs == [f"paged: field 'page' must be one of {'|'.join(PAGES)}, got {bad!r}"], (bad, errs)
    errs, _ = errors_of(app("paged", compose="c.yml", page=["ai"]))
    assert errs == ["paged: field 'page' must be string, got list"], errs
    # an explicit null is not «no page»: the schema does not declare null, and a top-level field's own type check
    # says so first and goes no further (one line, unlike a nested enum's two)
    errs, _ = errors_of(app("paged", compose="c.yml", page=None))
    assert errs == ["paged: field 'page' must be string, got NoneType"], errs


def test_each_of_the_owners_twelve_pages_is_valid_and_so_is_none():
    # the schema's list IS the owner's twelve, in his order; no page at all is valid (measure.py lists it apart)
    assert tuple(rc.json.loads(rc.SCHEMA.read_text(encoding="utf-8"))["properties"]["page"]["enum"]) == PAGES
    for page in PAGES:
        errs, _ = errors_of(app("paged", compose="c.yml", page=page))
        assert errs == [], (page, errs)
    errs, _ = errors_of(app("unpaged", compose="c.yml"))
    assert errs == [], errs


def test_what_was_valid_stays_valid():
    errs, provided = errors_of(app("fine", compose="c.yml", capabilities=[{"name": "thing", "type": "protocol"}]))
    assert errs == [], errs
    assert provided == {"thing": ["fine"]}


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
