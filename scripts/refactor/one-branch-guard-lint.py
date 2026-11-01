#!/usr/bin/env python3
r"""one-branch-guard-lint — gate G60: a type guard that can only ever take one branch.

    python3 scripts/refactor/one-branch-guard-lint.py [--self-test]

WHY THIS GATE EXISTS

`indoxV2GDocTest01/Batch Config` narrows its config to one lane:

    j.docs = j.docs.filter(d => d.type === t);
    const keep = new Set(j.docs.map(d => d.id));
    if (Array.isArray(j.ids))       j.ids = j.ids.filter(id => keep.has(id));      // NEVER RUNS
    if (Array.isArray(j.knownPins)) j.knownPins = j.knownPins.filter(...);         // runs

`j.ids` is a comma-joined STRING — `"gdx_inv1,gdx_inv2,…"` — assigned as a string literal eleven
lines above. `Array.isArray` on it is always false, so `ids` was never narrowed while `docs` and
`knownPins` were: a `batch:shp` lane carried all 15 ids against 5 docs. Nothing errored, nothing
logged, and the suite stayed green over a value that had silently not been filtered.

This is the family recorded in GATES.md as "checks whose evidence is an ABSENCE": the guard's
failure mode is that its body does not run, and a body that does not run is indistinguishable
from a body that ran and found nothing to do. The general property is worth more than the
instance:

    A GUARD THAT CAN ONLY EVER TAKE ONE BRANCH IS A BUG, REGARDLESS OF WHICH BRANCH IT TAKES.

THE RULE

Within a single Code node, if a key `K` is assigned a STRING literal in an object literal, and
nothing in that node ever assigns `K` anything else, then `Array.isArray(<expr>.K)` is provably
always false. The symmetric case — `K` assigned only an ARRAY literal, guarded by
`typeof <expr>.K === 'string'` — is reported the same way.

WHY IT IS CONSERVATIVE ON PURPOSE

  * Only keys whose assignment is VISIBLE IN THE SAME NODE are considered. A value arriving from
    an input item, a sub-workflow or a previous node is unknowable here and is skipped.
  * A key assigned anything non-literal ANYWHERE in the node is skipped entirely — one
    `j.ids = something()` is enough to make the guard legitimately useful.
  * n8n Code nodes are analysed as text, not parsed as JS. The patterns are deliberately narrow
    so that what is matched is unambiguous; anything clever is left alone.

The point is the same as G59's: it will miss one-branch guards; it will not invent them. A gate
that guesses gets switched off, and a switched-off gate is a green nobody reads.

WHAT THIS GATE DOES NOT COVER — read before trusting a green.
  * Code nodes in blueprints only. The same defect in the Python services is invisible here.
  * Type guards only (`Array.isArray`, `typeof === 'string'`). A guard that is constant for a
    non-type reason — a flag that is never set, a threshold nothing exceeds — is not detected.
  * It cannot see a value's shape across nodes, which is where most real drift lives.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
# [2026-08-23] Blueprints are code (.workflow.ts) since 52b32aa4. This gate globbed *.json,
# matched zero files on disk, and reported PASS while checking nothing. n8n_blueprint is the
# ONE reader — see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOB = "apps/*/blueprint/n8n/*.workflow.ts"

#: `"ids": "a,b,c"` / `ids: 'a,b'` — an object-literal key whose value is a string literal.
_STR_KEY = re.compile(r"""["']?(?P<k>[A-Za-z_][A-Za-z0-9_]*)["']?\s*:\s*(?P<q>["'])(?:\\.|(?!\2).)*\2""")
#: the same shape with an ARRAY literal value
_ARR_KEY = re.compile(r"""["']?(?P<k>[A-Za-z_][A-Za-z0-9_]*)["']?\s*:\s*\[""")
#: any OTHER assignment to that key — object-literal or member — that is not a bare literal.
#:
#: SELF-DERIVED REASSIGNMENT IS NOT EVIDENCE, and getting this wrong made the gate miss the very
#: case it was written for. The real defect is
#:
#:     if (Array.isArray(j.ids)) j.ids = j.ids.filter(...)
#:
#: whose BODY assigns `j.ids`. A naive "was this key ever reassigned?" test sees that and
#: concludes the type is unknowable — but the body only runs when the guard is true, and the
#: guard is never true, so the assignment never happens. Assignments whose right-hand side
#: mentions the same key (`X.K = … X.K …`) are therefore ignored: they cannot change the type
#: the guard sees, because they are downstream of it.
#:
#: The lookahead spans whitespace — `(?!\s*[...])`, not `\s*(?![...])`. With the latter the `\s*`
#: can match zero characters, so the lookahead inspects the SPACE after the colon rather than the
#: value, and `"ids": "a,b"` reads as a non-literal assignment. That bug made this gate silently
#: skip the exact node it was written for: a pattern that matched something it shouldn't, with no
#: symptom but a clean report. The gate for the absence-family, caught by its own self-test.
_OTHER_ASSIGN = r"""(?:["']?%s["']?\s*:\s*(?!\s*[\"'\[])|\.%s\s*=(?!=)(?P<rhs>[^;\n]*))"""

_ISARRAY = re.compile(r"Array\.isArray\s*\(\s*(?P<expr>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*\)")
_TYPEOF_STR = re.compile(
    r"typeof\s+(?P<expr>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)*)\s*===?\s*(['\"])string\2")


def _tail(expr: str) -> str:
    return expr.rsplit(".", 1)[-1]


_ELSE_BEFORE = re.compile(r"\belse\s+if\s*\($")


def _is_else_arm(src: str, guard_start: int) -> bool:
    """True if the guard at `guard_start` is the `else if` arm of a chain.

    [2026-08-23] This gate exists because of ONE node — indoxV2GDocTest01 :: 'Batch Config' —
    where `if (Array.isArray(j.ids))` was the only guard on a key holding a comma-joined string,
    so it never ran and `ids` was never narrowed. That bug has since been FIXED, in exactly the
    way this gate's own message recommends ("Handle the type the value actually has, and keep the
    other branch so the guard stays total"):

        if (typeof j.ids === 'string') j.ids = j.ids.split(',').filter(...).join(',');
        else if (Array.isArray(j.ids)) j.ids = j.ids.filter(...);

    and the gate went on flagging it, because it matched the `Array.isArray` text without looking
    at what precedes it. A gate that reports the repair of the bug it was written for is worse
    than one that reports nothing: the only way to make it quiet is to delete the total guard and
    reintroduce the defect.

    An `else if` arm is by definition not a single-branch guard — another arm handles the value's
    actual type. A bare `if` on a provably-false condition still flags.
    """
    head = src[max(0, guard_start - 40):guard_start]
    return bool(_ELSE_BEFORE.search(head.rstrip()))


def scan_code(rel: str, node: str, src: str) -> list[dict]:
    out = []
    str_keys = {m.group("k") for m in _STR_KEY.finditer(src)}
    arr_keys = {m.group("k") for m in _ARR_KEY.finditer(src)}
    # a key that is both is ambiguous -> skip
    both = str_keys & arr_keys
    str_keys -= both
    arr_keys -= both

    def reassigned(k: str) -> bool:
        for m in re.finditer(_OTHER_ASSIGN % (re.escape(k), re.escape(k)), src):
            rhs = m.groupdict().get("rhs")
            if rhs is not None and ("." + k) in rhs:
                continue          # self-derived: downstream of the guard, cannot change its type
            return True
        return False

    for m in _ISARRAY.finditer(src):
        k = _tail(m.group("expr"))
        if k in str_keys and not reassigned(k) and not _is_else_arm(src, m.start()):
            out.append({"file": rel, "node": node, "guard": m.group(0),
                        "key": k, "why": "assigned a STRING literal in this node",
                        "always": "false"})
    for m in _TYPEOF_STR.finditer(src):
        k = _tail(m.group("expr"))
        if k in arr_keys and not reassigned(k) and not _is_else_arm(src, m.start()):
            out.append({"file": rel, "node": node, "guard": m.group(0),
                        "key": k, "why": "assigned an ARRAY literal in this node",
                        "always": "false"})
    return out


def scan() -> list[dict]:
    out = []
    for p in sorted(REPO.glob(BLUEPRINT_GLOB)):
        try:
            data = load_blueprint(str(p))
        except (OSError, ValueError, CompileError):
            continue
        if not isinstance(data, dict):
            continue
        rel = str(p.relative_to(REPO)).replace("\\", "/")
        for n in data.get("nodes") or []:
            if not isinstance(n, dict):
                continue
            src = (n.get("parameters") or {}).get("jsCode")
            if isinstance(src, str) and src:
                out += scan_code(rel, n.get("name", "?"), src)
    return out


# ── self-test ────────────────────────────────────────────────────────────────────────────
#: THE REAL CASE, reduced. `ids` is a comma-joined string; the guard is always false.
_REAL = ('const __ret=[{json:{"ids": "gdx_inv1,gdx_inv2", "knownPins": ["gdx_shp3"], '
         '"docs": [{"id":"gdx_inv1"}]}}];\n'
         'const j=__ret[0].json; const keep=new Set();\n'
         'if (Array.isArray(j.ids)) j.ids=j.ids.filter(id=>keep.has(id));\n'
         'if (Array.isArray(j.knownPins)) j.knownPins=j.knownPins.filter(id=>keep.has(id));\n')

SELF_TEST = [
    ("THE REAL CASE: Array.isArray on a key assigned a string literal", _REAL, 1),
    ("the REPAIRED form of the real case -- else-if arm keeps the guard total, must be CLEAN",
     'const j={"ids":"a,b"};\n'
     "if (typeof j.ids === 'string') j.ids=j.ids.split(',').join(',');\n"
     'else if (Array.isArray(j.ids)) j.ids=j.ids.filter(x=>x);\n', 0),
    ("a BARE if on the same provably-false condition still flags",
     'const j={"ids":"a,b"};\nif (Array.isArray(j.ids)) j.ids=j.ids.filter(x=>x);\n', 1),
    ("the sibling guard on an ARRAY-valued key is correct and must not fire",
     'const j={"pins": ["a"]}; if (Array.isArray(j.pins)) j.pins=j.pins.filter(x=>x);', 0),
    ("a key reassigned from a call is unknowable -> skip",
     'const j={"ids": "a,b"}; j.ids = compute(); '
     'if (Array.isArray(j.ids)) j.ids=j.ids.filter(x=>x);', 0),
    ("a key assigned BOTH a string and an array somewhere is ambiguous -> skip",
     'const a={"ids": "a,b"}; const b={"ids": ["a"]}; '
     'if (Array.isArray(a.ids)) a.ids=a.ids.filter(x=>x);', 0),
    ("a value from an input item is not visible here -> skip",
     'const j=$input.first().json; if (Array.isArray(j.ids)) j.ids=j.ids.filter(x=>x);', 0),
    ("the symmetric case: typeof === 'string' on an array-literal key",
     'const j={"pins": ["a","b"]}; if (typeof j.pins === "string") j.pins=j.pins.split(",");', 1),
    ("a guard with no matching literal anywhere is left alone",
     'if (Array.isArray(whatever.thing)) doIt();', 0),
]


def self_test() -> int:
    bad = 0
    for label, src, want in SELF_TEST:
        got = len(scan_code("t.json", "N", src))
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] expected %d, got %d: %s" % ("ok " if ok else "FAIL", want, got, label))
    print("\nG60 self-test: %d/%d passed" % (len(SELF_TEST) - bad, len(SELF_TEST)))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    found = scan()
    n = len(list(REPO.glob(BLUEPRINT_GLOB)))
    # [2026-08-23 G66/C] AN EMPTY SCAN IS A RED, NEVER A PASS. This repo has already lived the
    # other way: twelve gates globbed apps/*/blueprint/n8n/*.json after blueprints became
    # .workflow.ts in 52b32aa4, matched nothing, looped over nothing, and printed their success
    # line for weeks. Green and blind are indistinguishable from OUTSIDE, so nothing surfaced it.
    # The glob is right today; this guard is what makes it stay honest if the layout moves again.
    if not n:
        print("G60 FAIL - scanned 0 blueprint(s) via %s. That is not a clean run, it is no run:"
              " a measurement over zero inputs is not a low score, it is no score." % BLUEPRINT_GLOB)
        return 1
    if not found:
        print("G60 PASS — no type guard across %d blueprint(s) is provably single-branch." % n)
        print("  Scope of this green is in the module docstring — visible literals only.")
        return 0
    print("G60 FAIL — %d single-branch guard(s):" % len(found))
    for f in found:
        print("\n  %s  node=%r" % (f["file"], f["node"]))
        print("      %s  is always %s" % (f["guard"], f["always"]))
        print("      `%s` is %s, so the body never runs and nothing errors." % (f["key"], f["why"]))
    print("\n  Handle the type the value actually has, and keep the other branch so the guard")
    print("  stays total rather than accidentally-false.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
