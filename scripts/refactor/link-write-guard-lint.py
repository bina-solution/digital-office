#!/usr/bin/env python3
"""link-write-guard-lint — gate G85: every route of the app plane that writes THIS office's state
refuses a caller that arrived over a link.

    python3 scripts/refactor/link-write-guard-lint.py             # the enumeration, and the justifications
    python3 scripts/refactor/link-write-guard-lint.py --strict    # justifications ignored: each is a finding
    python3 scripts/refactor/link-write-guard-lint.py --self-test

WHY THIS EXISTS. AGENTS.md rule 8: before an interface is tightened, every caller is enumerated
MECHANICALLY — by a gate, not by `grep`. The caller list here is the set of ROUTES that write this
office's own state, and the interface being tightened is the link: with `serve: {"*": {}}` a linked
office reaches this office's app plane, and the door stamps every request it delivers with the
link's own header (`X-DGO-Office`, `apps/dgo-extend/link-proxy.py:76,528`). §9 of the pairing
contract (`ai/context/dgo-pairing-contract.md`, «E — the trust boundary of a paired office») says a
request that crossed a link cannot write this office's OWN state, and names the routes.

MEASURED 2026-10-09/10-11 (DGO-49). Two routes had the guard (`PUT /api/remote`,
`POST /api/apps/<id>/apply` — the second was found by the §9 tests, which asked about two routes and
nothing else). EIGHT did not, and the tests could not have noticed, because a hand-written list of
routes only ever contains the routes its author remembered. That is the whole reason this gate
exists rather than a longer list in `apps/dgo-extend/tests/test_link_security.py`.

WHAT IT CHECKS — the enumeration is mechanical and the exemption is written:

  1. ROUTES ARE READ FROM THE FILE. Every `@app.<verb>("/rule")` / `@app.route(...)` in
     `platform-base/app-management/app.py`, with its HTTP methods — parsed with `ast`, so the list is
     the file's, not this docstring's.
  2. THE CLASS IS COMPUTED, NOT TYPED. A route is a candidate when EITHER (a) its call graph inside
     the file reaches a WRITE SINK, or (b) its methods include a verb that is not GET/HEAD/OPTIONS.
     (b) exists because (a) can only see writes whose primitive is named in SINKS: a new route that
     writes this office's state through something this table does not know is still a POST, PUT or
     DELETE, and still has to answer the question below. The two rules overlap on purpose — (a)
     catches a GET that writes, (b) catches a write nobody has named yet.
  3. EVERY CANDIDATE EITHER REFUSES THE LINK OR IS JUSTIFIED IN WRITING. A refusal is an `if` IN
     THE ROUTE'S OWN BODY whose test reads the link header and whose body returns (`api_apply`'s
     shape, `api_remote_put`'s). A read that is not a refusal — `api_enable`'s
     `request.headers.get(OFFICE_HEADER) or restore.get("office")`, which merely picks a value — is
     NOT a guard, and is a finding: that is exactly the hole measured here, where `enable` with
     `restore` must stay reachable from a peer (a move places an app with `POST …/enable
     {"restore": …}`, `app.py:_move`) while a plain switch-on must not be. Everything else is a
     JUSTIFIED entry with a written reason, and a justification is anti-rotted three ways: its route
     must still exist, must still be a candidate, and `writes: False` must still be what the sink
     walk says. So an entry can only ever leave this table by the route being fixed or by the route
     no longer doing what it said — never by nobody noticing.

WHAT IT DELIBERATELY DOES NOT CHECK.

  * Whether the sink walk is complete. It is a table of the primitives that write (`SINKS`), each
    asserted to still exist in the file; a write made by something not in it is invisible to (a) and
    covered by (b) only where the route is not a GET. Said here rather than implied.
  * The OTHER planes' routes. `data-management` writes this office's data and `computers` runs
    commands on its machines; both are reachable over a link, both are separate interfaces, and an
    enumerator for one of them belongs to that one (rule 8 is per interface).
  * The RENDER. This is a static question about a route's source; what actually reaches a container
    over a link is the door's route table (`apps/dgo-extend/tests/test_link_security.py` asks the
    door the same question from the other side).
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
TARGET = "platform-base/app-management/app.py"

#: The header the link's door writes, and the module constant that names it in the file. The
#: constant is READ from the file below (its value, not its name), so a route that spells the header
#: out by hand is recognised too.
HEADER_CONST = "OFFICE_HEADER"

#: What "writes this office's own state" means, as the primitives the file actually calls. Each
#: entry is asserted to still exist in the file AND to still be reached by something — a sink that
#: nothing writes through is a stale row, and this table shrinks itself the same way the
#: justifications do.
SINKS: dict[str, str] = {
    "_set_disposition": "writes the app's disposition in platform.state.yaml (the compiler's one writer)",
    "_render": "recompiles .generated/ — routers, SSO providers, tiles, DSNs",
    "_apply": "the whole bring-up/switch-off: state, render, hooks, container create/remove",
    "_lifecycle": "the route-level bring-up/switch-off behind enable, disable, uninstall, install",
    "_compose_up": "lets compose create or RECREATE this office's containers",
    "_remove_volumes": "removes the app's named volumes — its data",
    "_blueprint_apply": "imports into / removes from this office's automation engine",
    "_run_hook": "runs the app's own hooks (DB rows, blueprints, SSO providers)",
    "_data_job": "this office's data plane: export / import / pull, which writes volumes here",
    "reconcile_once": "converges every enabled app — the whole estate, not one app",
    "_move": "exports here, brings the app up on a peer, then switches this office's copy off",
}

#: Writes made by a call that is not a function of this file (`appinstall.place(...)` — the module
#: comes from the layer-1 catalog machinery). Recognised by the attribute name, and asserted to be
#: reached by something, like every row above.
EXTERNAL_SINKS: dict[str, str] = {
    "place": "appinstall.place — writes apps/<id> and the state file for a catalog install",
}

#: WRITE-VERBS: a route whose method is one of these is a candidate whatever the sink walk says.
WRITE_VERBS = {"POST", "PUT", "PATCH", "DELETE"}

#: Both tables, for the walk and the anti-rot assertions.
ALL_SINKS: dict[str, str] = {**SINKS, **EXTERNAL_SINKS}

#: Routes that write this office's state and are NOT guarded, each with the reason. Anti-rotted:
#: an entry whose route is gone, is no longer a candidate, or whose `writes:` disagrees with the
#: sink walk, FAILS. Delete an entry the moment its route refuses the link — that is how this list
#: shrinks itself (G31/G34's rule: a declaration matching nothing is stale).
JUSTIFIED: dict[str, dict] = {
    "api_catalog_preview": {
        "writes": False,
        "reason":
            "a POST that writes no state: it fetches, verifies and validates a candidate into a "
            "private temp dir and STAGES the bytes under a token; `apps/` and platform.state.yaml "
            "are untouched. `catalog/install` is the route that completes it, and it refuses a "
            "linked caller. If this route ever reaches a sink the reason stops being true and the "
            "entry fails.",
    },
}


# ── the file, read as the file ────────────────────────────────────────────────────────────────
def parse() -> tuple[str, ast.Module]:
    path = REPO / TARGET
    if not path.is_file():
        raise SystemExit(f"G85 FAIL — {TARGET} is not here: the enumeration has nothing to read")
    src = path.read_text(encoding="utf-8")
    return src, ast.parse(src)


def header_value(tree: ast.Module) -> str:
    """The value of `OFFICE_HEADER`, read from the file — so `request.headers.get("X-DGO-Office")`
    is recognised as reading the link header, and the gate does not carry a second copy of it."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == HEADER_CONST
                                                for t in node.targets):
            if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                return node.value.value
    raise SystemExit(f"G85 FAIL — {TARGET} never binds {HEADER_CONST}: the guard has no name here")


def defined(tree: ast.Module) -> dict[str, ast.AST]:
    return {n.name: n for n in tree.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def called_names(fn: ast.AST) -> set[str]:
    """Every name this function calls, by the name a reader would see: `f()` -> f,
    `mod.f()` / `client.images.remove()` -> f / remove."""
    out: set[str] = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name):
                out.add(f.id)
            elif isinstance(f, ast.Attribute):
                out.add(f.attr)
    return out


def reachable(fn: ast.AST, funcs: dict[str, ast.AST]) -> set[str]:
    """Every file-local function this function can reach, transitively (including itself)."""
    seen: set[str] = set()
    todo = [n for n in called_names(fn) if n in funcs]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        todo.extend(c for c in called_names(funcs[name]) if c in funcs and c not in seen)
    return seen


def routes(tree: ast.Module) -> list[dict]:
    """Every Flask route in the file: its function, rule, methods and decorator line."""
    out = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in node.decorator_list:
            if not (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)):
                continue
            verb = d.func.attr.upper()
            if verb not in ("GET", "POST", "PUT", "PATCH", "DELETE", "ROUTE"):
                continue
            rule = d.args[0].value if d.args and isinstance(d.args[0], ast.Constant) else "?"
            methods = [verb] if verb != "ROUTE" else ["GET"]
            for kw in d.keywords:
                if kw.arg == "methods" and isinstance(kw.value, (ast.List, ast.Tuple)):
                    methods = [e.value.upper() for e in kw.value.elts if isinstance(e, ast.Constant)]
            out.append({"func": node.name, "node": node, "rule": rule, "methods": methods,
                        "line": node.lineno})
    return out


# ── reading the header, and refusing on it ────────────────────────────────────────────────────
def header_reads(node: ast.AST, value: str) -> list[int]:
    """Lines where this subtree reads the link header: the constant's name, or a `headers.get()`
    whose argument is the header spelled out. A docstring is a Constant too — which is why only an
    argument of a lookup counts, never a bare string."""
    hits = []
    for n in ast.walk(node):
        if isinstance(n, ast.Name) and n.id == HEADER_CONST:
            hits.append(n.lineno)
        elif isinstance(n, ast.Attribute) and n.attr == HEADER_CONST:
            hits.append(n.lineno)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.args:
            arg = n.args[0]
            if isinstance(arg, ast.Constant) and arg.value == value:
                hits.append(n.lineno)
    return hits


def negates_header(test: ast.AST, value: str) -> bool:
    """`if not request.headers.get(H)` is a test for the ABSENCE of a link — the opposite of a
    guard, and the shape a reader would mistake for one."""
    for n in ast.walk(test):
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not) and header_reads(n.operand, value):
            return True
    return False


def refuses_link(fn: ast.AST, value: str) -> int | None:
    """The line of the `if` that refuses a linked caller, or None. A refusal is an `if` whose test
    reads the header (not negated) and whose body returns — `api_apply` / `api_remote_put`."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.If):
            continue
        if not header_reads(n.test, value) or negates_header(n.test, value):
            continue
        if any(isinstance(s, ast.Return) for s in ast.walk(n)):
            return n.lineno
    return None


# ── self-test: prove each rule, so a green run means something ────────────────────────────────
def self_test() -> int:
    guard = ('@app.post("/api/apps/<aid>/disable")\ndef api_disable(aid):\n'
             '    if request.headers.get(OFFICE_HEADER):\n'
             '        return jsonify(error="no"), 403\n'
             '    return _lifecycle(aid, False)\n')
    literal = ('@app.post("/api/x")\ndef api_x():\n'
               '    if request.headers.get("X-DGO-Office"):\n'
               '        return jsonify(error="no"), 403\n'
               '    return _lifecycle("a", True)\n')
    mere_read = ('@app.post("/api/apps/<aid>/enable")\ndef api_enable(aid):\n'
                 '    restore = (request.get_json() or {}).get("restore")\n'
                 '    if restore is not None:\n'
                 '        office = str(request.headers.get(OFFICE_HEADER) or "x").strip()\n'
                 '    return _lifecycle(aid, True, restore)\n')
    absent = ('@app.post("/api/y")\ndef api_y():\n'
              '    if not request.headers.get(OFFICE_HEADER) and _writable():\n'
              '        return _render()\n'
              '    return _render()\n')
    post_silent = '@app.post("/api/z")\ndef api_z():\n    return jsonify(ok=True)\n'
    get_silent = '@app.get("/api/z")\ndef api_z():\n    return jsonify(ok=True)\n'
    get_write = ('@app.get("/api/w/wipe")\ndef api_wipe():\n'
                 '    _remove_volumes(["v"])\n    return jsonify(ok=True)\n')
    docstring = ('@app.post("/api/d")\ndef api_d():\n'
                 '    """Refuses a caller from X-DGO-Office — see the link."""\n'
                 '    return _render()\n')
    # (what it proves, source, guarded?, in the class?)
    cases = [
        ("a refusal in the route's own body", guard, True, True),
        ("the header spelled out instead of the constant", literal, True, True),
        ("a read that is NOT a refusal — enable's own shape", mere_read, False, True),
        ("a test for the ABSENCE of a link", absent, False, True),
        ("a GET that writes nothing: not in the class at all", get_silent, False, False),
        ("a POST that writes nothing: in the class by its verb", post_silent, False, True),
        ("a GET that writes — found by the walk, not the verb", get_write, False, True),
        ("the header named in a docstring only", docstring, False, True),
    ]
    bad = []
    value = header_value(ast.parse('OFFICE_HEADER = "X-DGO-Office"\n'))
    for what, src, want_guard, want_candidate in cases:
        tree = ast.parse(src)
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
        funcs = defined(tree)
        r = next(iter(routes(tree)))
        wrote = bool((reachable(fn, funcs) | called_names(fn)) & set(ALL_SINKS))
        candidate = wrote or bool(set(r["methods"]) & WRITE_VERBS)
        guarded = refuses_link(fn, value) is not None
        if guarded != want_guard or candidate != want_candidate:
            bad.append(f"{what}: guarded={guarded} wanted={want_guard}, "
                       f"candidate={candidate} wanted={want_candidate}")
    for b in bad:
        print(f"  self-test FAIL — {b}")
    print(f"link_write_guard self-test: {len(cases)} shape(s), {len(cases) - len(bad)} as intended")
    return 1 if bad else 0


# ── the check ─────────────────────────────────────────────────────────────────────────────────
def check(strict: bool) -> int:
    src, tree = parse()
    value = header_value(tree)
    funcs = defined(tree)
    all_routes = routes(tree)

    # the sink table is anti-rotted before it is used: a row for something that is gone, or that
    # nothing in the file writes through, would silently shrink the class.
    problems = []
    for name, why in SINKS.items():
        if name not in funcs:
            problems.append(f"SINKS names `{name}` ({why}) and {TARGET} no longer defines it")
    reach = {r["func"]: reachable(r["node"], funcs) for r in all_routes}
    reached_sinks = {s for r in all_routes for s in (reach[r["func"]] | called_names(r["node"]))
                     if s in ALL_SINKS}
    for name, why in ALL_SINKS.items():
        if name not in reached_sinks:
            problems.append(f"{'SINKS' if name in SINKS else 'EXTERNAL_SINKS'} names `{name}` "
                            f"({why}) and no route reaches it any more — the row is stale, and the "
                            f"class it describes is smaller than this table says")

    candidates, guarded = [], {}
    for r in all_routes:
        sinks = sorted((reach[r["func"]] | called_names(r["node"])) & set(ALL_SINKS))
        writes = bool(sinks)
        by_verb = bool(set(r["methods"]) & WRITE_VERBS)
        if not (writes or by_verb):
            continue
        line = refuses_link(r["node"], value)
        candidates.append((r, sinks, writes, line))
        guarded[r["func"]] = line is not None

    print(f"G85 — {TARGET}, {len(src.splitlines())} lines, {len(all_routes)} route(s); "
          f"the link header is `{value}` ({HEADER_CONST})")
    print(f"      {len(candidates)} route(s) in the class (a write sink, or a write verb) of which "
          f"{sum(1 for _, _, _, ln in candidates if ln)} refuse the link")
    for r, sinks, writes, line in candidates:
        how = f"GUARDED at :{line}" if line else ("JUSTIFIED" if r["func"] in JUSTIFIED else "OPEN")
        what = ", ".join(sinks) if sinks else f"no sink reached — by method ({','.join(r['methods'])})"
        print(f"      {how:<16} {','.join(r['methods']):<12} {r['rule']:<34} "
              f"{r['func']}() :{r['line']}  writes: {what}")

    for name, entry in JUSTIFIED.items():
        if name not in {r["func"] for r in all_routes}:
            problems.append(f"JUSTIFIED names `{name}` and {TARGET} has no such route — delete the "
                            f"entry (a justification matching nothing is stale)")
            continue
        if name not in guarded:
            problems.append(f"JUSTIFIED names `{name}`, which is not in the class any more — the "
                            f"entry is stale")
            continue
        if guarded[name]:
            problems.append(f"JUSTIFIED names `{name}`, which now REFUSES the link — delete the "
                            f"entry, it is how this table shrinks itself")
            continue
        r = next(x for x in all_routes if x["func"] == name)
        sinks = sorted((reach[name] | called_names(r["node"])) & set(ALL_SINKS))
        if entry.get("writes") is False and sinks:
            problems.append(f"JUSTIFIED says `{name}` writes nothing, and it now reaches "
                            f"{', '.join(sinks)} — the reason is no longer true")
        print(f"      justification    {name}() — writes={entry.get('writes')}: {entry['reason']}")
        if strict:
            problems.append(f"JUSTIFIED `{name}`: --strict counts every justification as a finding "
                            f"({entry['reason']})")

    for r, _sinks, _writes, line in candidates:
        if line is None and r["func"] not in JUSTIFIED:
            problems.append(f"{r['func']}() ({','.join(r['methods'])} {r['rule']}, :{r['line']}) "
                            f"writes this office's state and neither refuses a caller that came "
                            f"over a link nor is justified in JUSTIFIED")

    if problems:
        print(f"\nG85 FAIL — {len(problems)} finding(s):")
        for p in problems:
            print(f"  · {p}")
        return 1
    print(f"\nG85 PASS — every route that writes this office's state refuses a linked caller, or is "
          f"justified in writing ({len(JUSTIFIED)} justification(s))")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="justifications are findings too — the end state this list migrates to")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    return self_test() if a.self_test else check(a.strict)


if __name__ == "__main__":
    raise SystemExit(main())
