#!/usr/bin/env python3
"""driver-dispatch-drift-lint — gate G51: a decide function's action name must be in the
driver's own dispatch allowlist, or the driver silently discards it at `Stop and Error`.

    python3 scripts/refactor/driver-dispatch-drift-lint.py [--self-test]

WHY THIS EXISTS. `indoxV2Driver01.json`'s `Switch1` dispatches the DOC-BASE lane by ACTION NAME —
its first branch is a hardcoded array literal (`[...].includes($json.ACTION)`) that `indoxV2Decide01`
never sees and never validates against. `indoxV2ActionsGlobal01.json`'s `docBaseDecide`/
`unknownTypeAction` compute an ACTION independently, in a completely different file, with no
mechanism forcing the two lists to agree. On 2026-08-06 this bit for real: `extract_base_doc` was
added to `docBaseDecide` (the new base-extractor migration action) but never added to `Switch1`'s
array. `indoxV2Decide01` correctly computed `ACTION='extract_base_doc'` on every eligible row (6,008
of them); `indoxV2Driver01` could not dispatch a name it did not recognize and fell through to
`fallbackOutput` -> `Stop and Error "UnHandeled Document"`. This ran for real, confirmed in
`execution_entity`: 3 errors in 30 minutes, silently outnumbered by unrelated successes in every
health-check summary anyone actually looked at. Root cause was found only by a live-execution-count
anomaly (a brand-new extractor workflow sitting at zero calls) forcing a by-hand trace — exactly the
kind of thing a static gate should catch at commit time instead.

This is the SAME defect shape as G39 (a trigger silently dropping an undeclared field) and G41 (a
switch silently dropping an unmatched case) — a decide function and the thing that consumes its
output are two independent lists that must never be allowed to drift, and nothing enforced that
until now. It is the third silent two-list-drift found in one session (trigger schemas, the gate
registry, now this).

SCOPE: only the DOC-BASE lane. `indoxV2ActionsGDoc01`/`Ship01`/`BS01`'s decide functions
(`invoiceDecide`/`shipmentDecide`/`bsDecide`) are dispatched by `indoxV2Driver01.json`'s `Switch1`
branches 2-5, which match `$json.DOC_TYPE` (`gdoc`/`bs_doc`/`shipment`/`empty_row`), never the ACTION
string — those lanes are structurally immune to this exact defect (any ACTION reaches the target
lane's OWN switch, in the OWN file, already covered by G41). Only the base lane's action-name array
is a second, cross-file copy of "which actions exist" — so only it can drift from the decide
functions the way `extract_base_doc` did.

WHAT THIS CHECKS: every string literal `docBaseDecide`/`unknownTypeAction` (in
`indoxV2ActionsGlobal01.json`) can `return` must appear in `indoxV2Driver01.json`'s `Switch1` base-lane
array (`rules.values[0]`'s `conditions[0].leftValue` array-literal expression). Reuses G41's own
literal-extraction regex/function-body-scoping approach (`switch-fallback-lint.py`) rather than
re-inventing it — same reasoning, same known blind spot: only literal `return 'x'`/`return "x"`
strings are visible to static analysis; a computed return is out of scope.

WHAT THIS DELIBERATELY DOES NOT CHECK: the reverse direction (an allowlist entry with no producing
literal) is intentionally not flagged — `figure_document_type`/`extract_invoice_google_ai` are exactly
this shape today (retired-by-guard, not deleted, see `ai/context/archive/indox-pre-2026-09/EXTRACTION-REFACTOR-PLAN.md`), and an
allowlist may legitimately carry a name for a decide branch reachable only via a computed expression
this gate cannot see. Flagging that direction would either be permanent noise or force deleting
intentionally-dormant code just to silence a gate — the same false-positive shape G39 already ruled
out for `created_at`/`updated_at`.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

# Blueprints are code (.workflow.ts) since 52b32aa4 — read through scripts/refactor/n8n_blueprint,
# the ONE reader. The base-lane allowlist lives in the ACTION ROUTER's Switch1 (the driver only
# groups and POSTs to it) — the .json-era constants named the driver and silently made this gate
# report "mapped file missing" on every run since the as-code flip.
DRIVER_FILE = "apps/indox/blueprint/n8n/indoxV2ActionRouter01.workflow.ts"
DRIVER_SWITCH_NODE = "Switch1"
DECIDE_FILE = "apps/indox/blueprint/n8n/indoxV2ActionsGlobal01.workflow.ts"
DECIDE_NODE = "Decide DOC BASE Action"
# docBaseRouterDecide added 2026-08-06: it is the OUTER decide (guards, dedup, the
# Gmail-label action, the GARBAGE terminal gate) and it dispatches ACTIONs just as
# surely as the two inner ones — but it was outside this scan, so three lanes shipped
# unlinted action literals into it in one day and A5's update_status_garbage /
# no_action_garbage reached the driver unregistered (every garbage document would have
# hit Switch1's fallback "Stop and Error" instead of terminalising).
DECIDE_FUNCTIONS = ["docBaseDecide", "unknownTypeAction", "docBaseRouterDecide"]

_RETURN_LITERAL = re.compile(r"""return\s*['"]([a-zA-Z0-9_]+)['"]\s*;""")
# The outer decide returns ITEMS, not strings: `return { json: { ACTION: 'x', ... } };`
# and the ternary form `ACTION: cond ? 'a' : 'b'`. Scanning docBaseRouterDecide without
# this pattern would report a confident PASS having matched nothing — the false-clean
# failure mode this gate family exists to prevent.
_ACTION_EXPR = re.compile(r"""ACTION\s*:\s*([^,\n]+)""")
_QUOTED = re.compile(r"""['"]([a-zA-Z0-9_]+)['"]""")
# `__route_gdoc__` & co. are DOC_TYPE routing sentinels consumed by Switch1's own
# DOC_TYPE rules, never by the base-lane ACTION allowlist — excluded by shape, not by
# name list, so a new one needs no gate edit.
_ROUTE_MARKER = re.compile(r"^__.*__$")
_FUNC_START = re.compile(r"function\s+{name}\s*\([^)]*\)\s*\{{")
_STRING_LITERAL = re.compile(r'''"([a-zA-Z0-9_]+)"''')


def _function_body(js_code: str, name: str) -> str:
    """The brace-matched body of `function name(...) { ... }` in `js_code`, or "" if not found.
    Identical approach to switch-fallback-lint.py's `_function_body` -- kept in lockstep by
    inspection rather than imported (same reasoning that gate gives for its own duplication:
    a hyphenated filename isn't importable as a module without machinery neither script needs)."""
    m = re.search(_FUNC_START.pattern.format(name=re.escape(name)), js_code)
    if not m:
        return ""
    depth, i = 0, m.end() - 1
    start = i
    while i < len(js_code):
        c = js_code[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return js_code[start:i + 1]
        i += 1
    return js_code[start:]


def find_node(doc: dict, name: str) -> dict | None:
    for n in doc.get("nodes", []) or []:
        if n.get("name") == name:
            return n
    return None


def decide_literals(js_code: str, functions: list[str]) -> set[str]:
    scope = "\n".join(_function_body(js_code, fn) for fn in functions)
    found = set(_RETURN_LITERAL.findall(scope))
    found |= _action_values(scope)
    return {x for x in found if x and not _ROUTE_MARKER.match(x)}


def _action_values(scope: str) -> set[str]:
    """Action names in VALUE position of an `ACTION:` property.

    Only value position counts. `ACTION: doc.STATUS === 'GARBAGE' ? 'a' : 'b'` yields
    {a, b} — never 'GARBAGE', which is a comparison operand and not an action anyone
    dispatches. A non-literal value (`resolveDocType(...)`) yields nothing, which is
    correct: there is no literal for the allowlist to be missing."""
    out: set[str] = set()
    for expr in _ACTION_EXPR.findall(scope):
        expr = expr.strip()
        if "?" in expr:                      # ternary: the arms follow the '?'
            out.update(_QUOTED.findall(expr.split("?", 1)[1]))
        elif expr[:1] in ("'", '"'):         # plain literal value
            m = _QUOTED.match(expr)
            if m:
                out.add(m.group(1))
    return out


def driver_allowlist(driver_doc: dict, switch_node_name: str) -> set[str] | None:
    """The base-lane action-name array literal inside Switch1's first `conditions`
    branch, or None if the node/branch shape isn't what's expected (stale mapping)."""
    node = find_node(driver_doc, switch_node_name)
    if node is None:
        return None
    values = ((node.get("parameters") or {}).get("rules") or {}).get("values")
    if not values:
        return None
    try:
        left_value = values[0]["conditions"]["conditions"][0]["leftValue"]
    except (KeyError, IndexError, TypeError):
        return None
    # the array literal sits inside `={{ [ "a", "b", ... ] }}` -- pull the bracketed
    # portion specifically so a name appearing elsewhere in the expression (there is
    # none today, but the extraction should not assume it) can't produce a false clean.
    m = re.search(r"\[(.*)\]", left_value, re.S)
    if not m:
        return None
    return set(_STRING_LITERAL.findall(m.group(1)))


def driver_prefixes(driver_doc: dict, switch_node_name: str) -> set[str]:
    """Prefixes the base-lane rule also accepts through `startsWith` conditions (the router's
    `source_feedback_<idx>` family is one rule, not N array entries). A decide literal that IS
    such a prefix (`'source_feedback_' + idx`) is covered by that rule."""
    node = find_node(driver_doc, switch_node_name)
    if node is None:
        return set()
    try:
        conds = node["parameters"]["rules"]["values"][0]["conditions"]["conditions"]
    except (KeyError, IndexError, TypeError):
        return set()
    out: set[str] = set()
    for c in conds or []:
        op = ((c or {}).get("operator") or {}).get("operation")
        rv = (c or {}).get("rightValue")
        if op == "startsWith" and isinstance(rv, str) and rv:
            out.add(rv)
    return out


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST_CASES = [
    ("every literal has a matching allowlist entry -- must be clean",
     "function docBaseDecide(doc){ if (doc.x) return 'known_action'; return null; }",
     {"known_action", "other_entry"}, set()),
    ("a literal with no allowlist entry -- must catch (this is exactly the "
     "extract_base_doc incident)",
     "function docBaseDecide(doc){ if (doc.x) return 'new_action'; return null; }",
     {"known_action"}, {"new_action"}),
    ("an allowlist entry with no producing literal -- must NOT be flagged (retired-by-guard "
     "actions like figure_document_type are exactly this shape, by design)",
     "function docBaseDecide(doc){ return 'known_action'; }",
     {"known_action", "figure_document_type"}, set()),
    ("outer-decide object return -- must be SEEN (adding the function name without the "
     "ACTION: pattern would have reported a false clean here)",
     "function docBaseDecide(doc){ return { json: { ACTION: 'obj_action', DOC_TYPE: 'x' } }; }",
     {"known_action"}, {"obj_action"}),
    ("outer-decide TERNARY object return -- both arms must be seen (this is exactly the "
     "A5 GARBAGE shape: STATUS==='GARBAGE' ? no_action_garbage : update_status_garbage)",
     "function docBaseDecide(doc){ return { json: { ACTION: doc.S === 'G' ? 'act_a' : 'act_b' } }; }",
     {"act_a"}, {"act_b"}),
    ("__route_*__ DOC_TYPE sentinels are NOT allowlist actions -- must not be flagged",
     "function docBaseDecide(doc){ return { json: { ACTION: '__route_gdoc__' } }; }",
     set(), set()),
]


def self_test() -> int:
    bad = 0
    print("check (decide literal -> driver allowlist coverage):")
    for label, js, allowlist, want_gap in SELF_TEST_CASES:
        got_gap = decide_literals(js, ["docBaseDecide"]) - allowlist
        ok = got_gap == want_gap
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] gap={sorted(got_gap)} (want {sorted(want_gap)}): {label}")
    total = len(SELF_TEST_CASES)
    print(f"\nG51 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    decide_path = REPO / DECIDE_FILE
    driver_path = REPO / DRIVER_FILE
    if not decide_path.exists() or not driver_path.exists():
        print(f"G51 FAIL — mapped file missing: {DECIDE_FILE} or {DRIVER_FILE} not found "
              "(DECIDE_FILE/DRIVER_FILE may be stale)")
        return 1

    try:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
        from n8n_blueprint import load as load_blueprint
        decide_doc = load_blueprint(decide_path)
        driver_doc = load_blueprint(driver_path)
    except Exception as e:  # noqa: BLE001 — a gate must name what it could not read
        print(f"G51 FAIL — could not parse: {e}")
        return 1

    decide_node = find_node(decide_doc, DECIDE_NODE)
    if decide_node is None:
        print(f"G51 FAIL — node {DECIDE_NODE!r} not found in {DECIDE_FILE} "
              "(DECIDE_NODE may be stale)")
        return 1

    allowlist = driver_allowlist(driver_doc, DRIVER_SWITCH_NODE)
    if allowlist is None:
        print(f"G51 FAIL — could not extract the base-lane action array from "
              f"{DRIVER_FILE}::{DRIVER_SWITCH_NODE} (shape changed — mapping may be stale)")
        return 1

    literals = decide_literals((decide_node.get("parameters") or {}).get("jsCode", ""),
                                DECIDE_FUNCTIONS)
    prefixes = driver_prefixes(driver_doc, DRIVER_SWITCH_NODE)
    gap = {x for x in literals - allowlist if not any(x.startswith(p) for p in prefixes)}

    if not gap:
        print(f"G51 PASS — every action literal {sorted(DECIDE_FUNCTIONS)} in {DECIDE_FILE} can "
              f"return is in {DRIVER_FILE}::{DRIVER_SWITCH_NODE}'s base-lane allowlist "
              f"({len(literals)} literal(s) checked).")
        return 0

    print(f"G51 FAIL — {len(gap)} action literal(s) {DECIDE_FUNCTIONS} in {DECIDE_FILE} can "
          f"return but {DRIVER_FILE}::{DRIVER_SWITCH_NODE} does not recognize:")
    for name in sorted(gap):
        print(f"    {name!r}")
    print(
        "\n  A document reaching this action will compute it correctly in indoxV2Decide01, then\n"
        "  fail to dispatch in indoxV2Driver01 and fall to Stop and Error - UnHandeled Document.\n"
        "  Add the literal to Switch1's base-lane action array (rules.values[0].conditions[0]\n"
        "  .leftValue) in indoxV2ActionRouter01.workflow.ts. This is what happened to 'extract_base_doc' on\n"
        "  2026-08-06 -- 3 real errors in 30 minutes before anyone traced it by hand."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
