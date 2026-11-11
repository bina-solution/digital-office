"""`serve.computers.machines` survives the store (DGO-553).

`_set_home_serve` is the one writer of what this office gives a linked office, and it REBUILDS every
entry from the keys it knows (`port`, `agent_api_port`, `identity`, `host`) — so a key it does not name
is dropped. That is not a theoretical hazard: the first time the sharing screen wrote
`serve: {"computers": {"port": 8977, "machines": "*"}}` the stored record came back as
`{"port": 8977}` (measured 2026-11-01), and the computers app, which reads that key to decide which
machines a peer may see, silently fell back to "everything" — the opposite of what the screen said.

What is asserted here, against a temp state dir:

  * a declared `"*"` is stored;
  * a declared list is stored, normalised;
  * naming the port again does NOT drop the machines (the same rule `identity`/`host` get);
  * a malformed id is not a narrowing — what was declared before is kept;
  * an entry with no `machines` at all keeps meaning "every machine".

Run: python3 apps/dgo-extend/tests/test_serve_machines.py   (or pytest — plain functions)
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))               # apps/dgo-extend, so `import converge` is the app's


def _fresh(home: dict) -> pathlib.Path:
    d = pathlib.Path(tempfile.mkdtemp(prefix="dgo-home-"))
    (d / "home.json").write_text(json.dumps(home), encoding="utf-8")
    os.environ["DGO_STATE_DIR"] = str(d)
    return d


def _load():
    """Import `converge` AFTER the env is set: the module reads its paths at call time, not import."""
    import importlib
    import converge
    importlib.reload(converge)
    return converge


BASE = {"id": "hp-laptop", "label": "HP", "slot": 1,
        "serve": {"*": {}, "bina-ds": {"port": 3080, "agent_api_port": 3081},
                  "only": {"vps1": ["plane"]}}}


def _serve_after(serve: dict) -> dict:
    d = _fresh(BASE)
    cv = _load()
    # one entry the way the screen sends it: the port it already had, plus the machines
    cv.set_home_serve(serve)
    return json.loads((d / "home.json").read_text(encoding="utf-8"))["serve"]


def test_a_star_is_stored() -> None:
    s = _serve_after({**BASE["serve"], "computers": {"port": 8977, "machines": "*"}})
    assert s["computers"]["machines"] == "*"
    assert s["computers"]["port"] == 8977


def test_a_list_is_stored_normalised() -> None:
    s = _serve_after({**BASE["serve"],
                      "computers": {"port": 8977, "machines": [" Computer_SSH-A ", "computer_local-local"]}})
    assert s["computers"]["machines"] == ["computer_ssh-a", "computer_local-local"], (
        "ids are stored the way the vault writes them: lower-case, no padding")


def test_naming_the_port_again_does_not_drop_the_machines() -> None:
    d = _fresh({**BASE, "serve": {**BASE["serve"],
                                  "computers": {"port": 8977, "machines": ["computer_ssh-a"]}}})
    cv = _load()
    cv.set_home_serve({**BASE["serve"], "computers": {"port": 8977}})     # the screen re-saved the port only
    s = json.loads((d / "home.json").read_text(encoding="utf-8"))["serve"]
    assert s["computers"]["machines"] == ["computer_ssh-a"], (
        "a re-declared port is not a statement about machines")


def test_a_malformed_id_is_not_a_narrowing() -> None:
    d = _fresh({**BASE, "serve": {**BASE["serve"],
                                  "computers": {"port": 8977, "machines": "*"}}})
    cv = _load()
    cv.set_home_serve({**BASE["serve"], "computers": {"port": 8977, "machines": ["bad id with spaces"]}})
    s = json.loads((d / "home.json").read_text(encoding="utf-8"))["serve"]
    assert s["computers"]["machines"] == "*", "a typo must not turn into 'share nothing'"


def test_no_machines_key_keeps_its_old_meaning() -> None:
    s = _serve_after({**BASE["serve"], "computers": {"port": 8977}})
    assert "machines" not in s["computers"], "absent = every machine, as before this key existed"


def test_the_rest_of_the_declaration_is_untouched() -> None:
    s = _serve_after({**BASE["serve"], "computers": {"port": 8977, "machines": "*"}})
    assert s["only"] == {"vps1": ["plane"]}, "a narrowed office stays narrowed"
    assert s["bina-ds"] == {"port": 3080, "agent_api_port": 3081}


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS {name}")
            except Exception as e:                 # noqa: BLE001 — a runner reports, never hides
                fails += 1
                print(f"FAIL {name}: {e}")
    print(f"test_serve_machines — {fails} failing")
    sys.exit(1 if fails else 0)
