"""test_office_identity.py — the rule office_identity.py asks of a linked office's id (DGO-615).

    cd apps/project-pln && python -m pytest test_office_identity.py -q        # or: python test_office_identity.py

office_identity.py is Plane's own middleware (COPYed to plane/middleware/ by the Dockerfile), so it
imports Django; what is asked here is its office-id rule, which needs nothing of Django. The module is
therefore loaded from its file with the two Django names it imports stood in for, and only for the
moment of loading. OFFICE_IDENTITY_UNDER_TEST names another copy of the file, to measure it.
"""
import importlib.util
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
MODULE = os.environ.get("OFFICE_IDENTITY_UNDER_TEST") or os.path.join(HERE, "office_identity.py")
STAND_INS = ("django", "django.contrib", "django.contrib.auth")


def load():
    saved = {name: sys.modules.get(name) for name in STAND_INS}
    auth = types.ModuleType("django.contrib.auth")
    auth.get_user_model = lambda: None
    auth.login = lambda *args, **kwargs: None
    sys.modules.update({"django": types.ModuleType("django"),
                        "django.contrib": types.ModuleType("django.contrib"),
                        "django.contrib.auth": auth})
    try:
        spec = importlib.util.spec_from_file_location("office_identity_under_test", MODULE)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    finally:
        for name, before in saved.items():
            if before is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = before
    return module


def test_an_office_id_is_a_name():
    rule = load().OFFICE_RE
    assert rule.match("vps1") and rule.match("hp-laptop") and rule.match("office-75ffe977")
    assert not rule.match("../vps1") and not rule.match("") and not rule.match("Vps1")


def test_an_office_id_that_ends_in_a_line_break_is_not_one():
    # Python's `$` also matches just BEFORE a final newline, so `^…$` read "vps1" + a line break as
    # an id. Both readers in the module strip or split before they ask; the rule may not rely on it.
    rule = load().OFFICE_RE
    assert rule.match("vps1\n") is None
    assert rule.match("hp-laptop\n") is None


def test_a_hyphenated_office_finds_its_link_and_nothing_else_does():
    # hos-005: `office in name.split("-")` never matched hp-laptop or portable-ubuntu, so their identity could not
    # be verified; and splitting let a fragment ("laptop") pass for an office. The signer (dgo-extend's link-proxy)
    # uses the same rule.
    f = load().names_office
    converged = {"id": "dgo_link-macbook-hp-laptop-use", "account_hint": "macbook->hp-laptop use"}
    assert f({"id": "dgo_link-hp-laptop"}, "hp-laptop") and f({"id": "dgo_link-vps1"}, "vps1")
    assert f(converged, "hp-laptop") and f(converged, "macbook")
    assert not f(converged, "laptop") and not f({"id": "dgo_link-hp-laptop"}, "hp")
    assert not f({"id": "dgo_link-portable-ubuntu"}, "ubuntu")
    assert not f({"id": "dgo_link-vps1-x", "account_hint": "something"}, "vps1")


def test_the_signer_and_the_checker_match_offices_by_one_rule():
    # The door that signs (apps/dgo-extend/link-proxy.py) and this checker each carry `names_office`; two copies
    # that drift apart sign what is not checked. Compared by their code, docstrings aside. Skipped where the
    # door's file is not beside this app (an app's own image).
    import ast
    door = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dgo-extend", "link-proxy.py")
    if not os.path.exists(door):
        return

    def body(path):
        fn = next(n for n in ast.parse(open(path, encoding="utf-8").read()).body
                  if isinstance(n, ast.FunctionDef) and n.name == "names_office")
        fn.body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        return ast.dump(fn)
    here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "office_identity.py")
    assert body(door) == body(here), "names_office differs between link-proxy.py and office_identity.py"


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok    {name}")
            except Exception as e:                                         # noqa: BLE001
                failed += 1
                print(f"FAIL  {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
