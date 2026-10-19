#!/usr/bin/env python3
"""switch-fallback-lint — gate G41: a switch node never silently discards an unmatched item.

    python3 scripts/refactor/switch-fallback-lint.py [--self-test]

WHY THIS EXISTS. n8n's `switch` node (v2/v3) in "rules" mode (a named list of `value2`/`outputKey`
cases) drops any item that matches none of them UNLESS `options.fallbackOutput` names a real output
for it to land on. Leave it unset and the drop is total silence: no error, no log line, no execution
row for that branch — the item just stops existing in the graph. `indoxV2ActionsGlobal01.json`'s
"DOC BASE Action Switch" has 13 named cases and no `fallbackOutput`; its own upstream decide
function (`Decide DOC BASE Action`, `unknownTypeAction()`) can return `extract_invoice_google_ai`,
which isn't one of the 13 — so a document needing the AI-extraction fallback is routed nowhere. It
keeps its current STATUS forever and gets re-picked every state-machine sweep until MAX_ITERATIONS,
with nothing in any log to say why. Three siblings in the same state machine have the identical
shape (see WHAT THIS CHECKS): `indoxV2ActionsBS01.json` drops its own `no_action_unhandled_state`
catch-all, and both `indoxV2ActionsGDoc01.json` / `indoxV2ActionsShip01.json` drop
`no_action_already_completed` — none of the three have ever errored either, for the same reason.

This is the SAME defect shape as G19 (`workflow-input-lint`, a sub-workflow call that silently sends
null) and G38 (a dangling errorWorkflow that silently eats a failure): something that should be
either handled or loud is instead quiet. A `switch` node with a real `fallbackOutput` wired to a
`stopAndError` node — `indoxV2Driver01.json`'s `Switch1` — is the pattern this gate wants to see
everywhere: unmatched items become a VISIBLE, retryable failure instead of an invisible, permanent one.

WHAT THIS CHECKS, two independent conditions, either one fails the gate:

  A. STRUCTURAL (scans every blueprint file, no per-file mapping needed): a `switch` node in "rules"
     mode (`parameters.rules.rules` non-empty) must set `parameters.options.fallbackOutput` to
     something other than absent/`"none"`. This is what "conditions"-mode switches like
     `indoxV2Driver01.json`'s `Switch1` already do correctly (`fallbackOutput: "extra"`, wired to a
     `stopAndError` node) — rules-mode switches in this codebase currently do not, and this is the
     structural gap that let the four case-coverage bugs below go unnoticed.

  B. COVERAGE (an explicit, hand-maintained map — `DECIDE_SWITCH_PAIRS` below — from a "decide"-style
     Code node to the "rules"-mode switch it feeds, same reasoning as G39's `UPSERT_TARGETS`: guessing
     which code node feeds which switch from naming conventions alone is exactly the kind of
     "probably right" heuristic `feedback_prefer_existing_mechanism_over_new_heuristic` warns against
     — an explicit, checkable pairing is worth the one-line-per-pipeline maintenance cost). For each
     pair, every top-level `return 'literal'` / `return "literal"` string in the decide function must
     appear as a `value2` in the switch's rules. A return value that is itself a computed expression
     (not a string literal) is invisible to static analysis and out of scope — this catches the
     literal-constant case, which is what all four known bugs are.

A currently-clean gate is not evidence nothing needs fixing: at the time this gate was written, check
A already fails for 4 switches and check B already fails for 3 of the same 4 pipelines (BS additionally
drops `no_action_unhandled_state`, GDoc/Ship additionally drop `no_action_already_completed`) — the
gate is being ADDED in a known-failing state on purpose, exactly like G1's replacement gates were
added mid-migration in `GATES.md`. Wiring the actual fix (routing `extract_invoice_google_ai` to a
real handler, adding `fallbackOutput` + a `stopAndError` sink to all four) is tracked separately; this
gate's job is to make sure it cannot go quiet again once fixed, and to stop a FIFTH pipeline from
shipping the same gap.
"""
from __future__ import annotations

import argparse
import glob
import json
import pathlib
import re
import sys
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

#: workflow blueprint path (repo-relative) -> [(decide code-node name, switch node name,
#: [relevant JS function names, or None to scan the whole code node]), ...].
#: See docstring, check B, for why the pairing is explicit rather than inferred.
#:
#: The function-name scope matters: `indoxV2ActionsGlobal01.json`'s code node also defines
#: `resolveDocType()`, whose returns ('gdoc', 'bs_doc', 'shipment', 'unknown', ...) become
#: `DOC_TYPE` and are consumed by a DIFFERENT switch (`indoxV2Driver01.json`'s `Switch1`), not this
#: one — scanning the whole code node would wrongly flag them as dropped ACTION values. The other
#: three pipelines' code nodes have no such unrelated helper, so `None` (whole node) is precise there.
DECIDE_SWITCH_PAIRS: dict[str, list[tuple[str, str, list[str] | None]]] = {
    "apps/indox/blueprint/n8n/indoxV2ActionsGlobal01.workflow.ts":
        [("Decide DOC BASE Action", "DOC BASE Action Switch",
          ["docBaseDecide", "unknownTypeAction", "docBaseRouterDecide"])],
    "apps/indox/blueprint/n8n/indoxV2ActionsBS01.workflow.ts":
        [("Decide BS Action", "3b. BS Action Switch1", None)],
    "apps/indox/blueprint/n8n/indoxV2ActionsInv01.workflow.ts":
        [("Decide GDoc Action", "3a. GDOC Action Switch1", None)],
    "apps/indox/blueprint/n8n/indoxV2ActionsShip01.workflow.ts":
        [("Decide Shipment Action", "3a. GDOC Action Switch1", None)],
}

#: Verdicts a typed lane's decide may return that its OWN switch never receives, because the
#: CENTRAL ROUTER owns their dispatch. The pair model above assumes decide's returns feed the
#: paired switch — true in execute mode — but in decide mode the verdicts go back to
#: indoxV2ActionRouter01, whose Switch1 carries an explicit DOC-BASE action list and dispatches
#: those to indoxV2ActionsGlobal01 instead of the typed lane. Verified against the router
#: blueprint: 'restart_base' sits in that literal DOC-BASE array, so a shipment decide answering
#: restart_base for a TYPE-less doc is Global01's to run and the typed switch is out of the path.
#: Every entry here must name a value present in the router's DOC-BASE list — an entry that
#: stops being true there turns back into a real gap, which is why this is a lint-owned ledger
#: and not a silencing flag at the call site.
ROUTER_MEDIATED: dict[str, set[str]] = {
    "apps/indox/blueprint/n8n/indoxV2ActionsShip01.workflow.ts": {"restart_base"},
}

_RETURN_LITERAL = re.compile(r"""return\s*['"]([a-zA-Z0-9_]+)['"]\s*;""")
_FUNC_START = re.compile(r"function\s+{name}\s*\([^)]*\)\s*\{{")


def _function_body(js_code: str, name: str) -> str:
    """The brace-matched body of `function name(...) { ... }` in `js_code`, or "" if not found."""
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


# ─────────────────────────────────────────────────────────────────────────────
# Check A — structural: every rules-mode switch must declare a real fallbackOutput.
# ─────────────────────────────────────────────────────────────────────────────
def rules_mode_cases(node: dict) -> list[str] | None:
    """The list of `value2` case values if `node` is a rules-mode switch, else None."""
    if not str(node.get("type", "")).endswith(".switch"):
        return None
    rules = ((node.get("parameters") or {}).get("rules") or {}).get("rules")
    if not rules:
        return None
    return [r.get("value2") for r in rules if isinstance(r, dict)]


def missing_fallback(node: dict) -> bool:
    """True if `node` is a rules-mode switch with no real fallbackOutput configured."""
    if rules_mode_cases(node) is None:
        return False
    fb = (node.get("parameters") or {}).get("options", {}).get("fallbackOutput")
    return fb is None or fb == "none"


# ─────────────────────────────────────────────────────────────────────────────
# Check B — coverage: every literal a decide function can return is a real switch case.
# ─────────────────────────────────────────────────────────────────────────────
_ACTION_EXPR = re.compile(r"""ACTION\s*:\s*([^,\n]+)""")
_QUOTED = re.compile(r"""['"]([a-zA-Z0-9_]+)['"]""")
_ROUTE_MARKER = re.compile(r"^__.*__$")
# [2026-08-23] Two more classes of decide return that CANNOT reach an action switch, both
# verified in the blueprints rather than assumed:
#
#   no_action*  -- indoxV2Driver01's `IfAction` gates dispatch on
#                    ACTION notStartsWith 'no_action'  (leftValue={{ $json.ACTION }}),
#                  so the driver never calls an action workflow for one. The driver even
#                  REWRITES actions it wants dropped into this namespace on purpose:
#                    "rewrite to a no_action so the filter drops it from dispatch"
#                  (indoxV2Driver01 :: no_action_double_action_blocked, _inflight_skip).
#                  These are terminal signals consumed by the driver, not dispatched work.
#
#   source_feedback_<n> -- the action switch's own value1 folds the whole family back to one
#                  case before matching:
#                    {{ String($json.ACTION||"").startsWith("source_feedback_")
#                         ? "source_feedback" : ... }}
#                  so `source_feedback` is the only case that can ever be needed. Same trick
#                  as BS's link_documents_r<n> -> link_documents.
#
# Flagging either produced 11 false gaps on DOC BASE Action Switch and hid the real ones.
_DISPATCH_FILTERED = re.compile(r"^(no_action|source_feedback_)")


def _action_values(scope: str) -> set[str]:
    """Action names in VALUE position of an `ACTION:` property — the shape the OUTER
    decide (`docBaseRouterDecide`) uses: it returns ITEMS (`return { json: { ACTION: ...`)
    rather than bare strings, so `_RETURN_LITERAL` alone sees nothing there and would
    report a confident PASS having matched zero literals.

    Ternaries yield both arms and never the comparison operand:
    `ACTION: doc.STATUS === 'GARBAGE' ? 'a' : 'b'` -> {a, b}, not 'GARBAGE'.
    Kept behaviourally identical to driver-dispatch-drift-lint.py's copy (same reasoning
    that file already gives for duplicating `_function_body`: a hyphenated filename is
    not importable without machinery neither gate needs)."""
    out: set[str] = set()
    for expr in _ACTION_EXPR.findall(scope or ""):
        expr = expr.strip()
        if "?" in expr:
            out.update(_QUOTED.findall(expr.split("?", 1)[1]))
        elif expr[:1] in ("'", '"'):
            m = _QUOTED.match(expr)
            if m:
                out.add(m.group(1))
    return out


def code_return_literals(js_code: str) -> set[str]:
    found = set(_RETURN_LITERAL.findall(js_code or "")) | _action_values(js_code)
    # `__route_gdoc__` & co. are DOC_TYPE routing sentinels consumed by the DRIVER's
    # DOC_TYPE lanes, never cases on this action switch.
    return {x for x in found
            if x and not _ROUTE_MARKER.match(x) and not _DISPATCH_FILTERED.match(x)}


def coverage_gap(decide_js: str, switch_cases: list[str], functions: list[str] | None = None) -> set[str]:
    if functions:
        js_scope = "\n".join(_function_body(decide_js, fn) for fn in functions)
    else:
        js_scope = decide_js
    return code_return_literals(js_scope) - set(switch_cases)


def find_node(doc: dict, name: str) -> dict | None:
    for n in doc.get("nodes", []) or []:
        if n.get("name") == name:
            return n
    return None


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST_A = [
    ("rules-mode switch, no fallbackOutput at all — must catch", True,
     {"type": "n8n-nodes-base.switch",
      "parameters": {"rules": {"rules": [{"value2": "x", "outputKey": "x"}]}}}),
    ("rules-mode switch, fallbackOutput explicitly 'none' — must catch", True,
     {"type": "n8n-nodes-base.switch",
      "parameters": {"rules": {"rules": [{"value2": "x", "outputKey": "x"}]},
                      "options": {"fallbackOutput": "none"}}}),
    ("rules-mode switch, fallbackOutput set to a real output — must allow", False,
     {"type": "n8n-nodes-base.switch",
      "parameters": {"rules": {"rules": [{"value2": "x", "outputKey": "x"}]},
                      "options": {"fallbackOutput": "extra"}}}),
    ("conditions-mode switch (no rules.rules) — out of scope for check A, must allow", False,
     {"type": "n8n-nodes-base.switch",
      "parameters": {"rules": {"values": [{"conditions": {}}]}, "options": {"fallbackOutput": "extra"}}}),
    ("non-switch node — must allow", False,
     {"type": "n8n-nodes-base.code", "parameters": {"jsCode": "return 'x';"}}),
]

SELF_TEST_B = [
    ("literal return with no matching case — must catch",
     "function decide(doc){ if (doc.x) return 'handled_case'; return 'orphan_case'; }",
     ["handled_case"], None, {"orphan_case"}),
    ("every literal return has a matching case — must be clean",
     "function decide(doc){ if (doc.x) return 'a'; return 'b'; }",
     ["a", "b"], None, set()),
    ("computed (non-literal) return is invisible to static analysis, not a false catch",
     "function decide(doc){ return someVar; }",
     ["a"], None, set()),
    ("scoped to named function(s) — an unrelated helper's return must NOT false-positive",
     "function resolveType(x){ return 'gdoc'; } function decide(doc){ return 'real_case'; }",
     ["real_case"], ["decide"], set()),
    ("scoped to named function(s) — the unrelated helper's return alone (no scope) WOULD have flagged",
     "function resolveType(x){ return 'gdoc'; } function decide(doc){ return 'real_case'; }",
     ["real_case"], None, {"gdoc"}),
]


SELF_TEST_B += [
    ("outer-decide object return -- must be SEEN (function name alone would false-clean)",
     "function docBaseRouterDecide(d){ return { json: { ACTION: 'obj_action' } }; }",
     ["known"], ["docBaseRouterDecide"], {"obj_action"}),
    ("outer-decide ternary -- both arms seen, comparison operand NOT treated as an action",
     "function docBaseRouterDecide(d){ return { json: { ACTION: d.S === 'GARBAGE' ? 'act_a' : 'act_b' } }; }",
     ["act_a"], ["docBaseRouterDecide"], {"act_b"}),
    ("__route_*__ sentinels are not switch cases -- must not be flagged",
     "function docBaseRouterDecide(d){ return { json: { ACTION: '__route_gdoc__' } }; }",
     [], ["docBaseRouterDecide"], set()),
    ("no_action* never reaches a switch -- driver IfAction drops it before dispatch",
     "function docBaseRouterDecide(d){ return { json: { ACTION: 'no_action_paused' } }; }",
     [], ["docBaseRouterDecide"], set()),
    ("source_feedback_<n> is folded to 'source_feedback' by the switch's own value1",
     "function docBaseRouterDecide(d){ return { json: { ACTION: 'source_feedback_' + i } }; }",
     [], ["docBaseRouterDecide"], set()),
    ("the exclusion is a PREFIX rule, not a substring one -- a real action still flags",
     "function docBaseRouterDecide(d){ return { json: { ACTION: 'mark_no_action_done' } }; }",
     [], ["docBaseRouterDecide"], {"mark_no_action_done"}),
]


def self_test() -> int:
    bad = 0
    print("check A (structural fallbackOutput):")
    for label, should, node in SELF_TEST_A:
        got = missing_fallback(node)
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("check B (decide/switch coverage):")
    for label, js, cases, functions, want_gap in SELF_TEST_B:
        got_gap = coverage_gap(js, cases, functions)
        ok = got_gap == want_gap
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] gap={sorted(got_gap)} (want {sorted(want_gap)}): {label}")
    total = len(SELF_TEST_A) + len(SELF_TEST_B)
    print(f"\nG41 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings_a: list[tuple[str, str]] = []
    checked_a = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(path)
            except (OSError, ValueError):
                continue
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for node in doc.get("nodes", []) or []:
                if rules_mode_cases(node) is None:
                    continue
                checked_a += 1
                if missing_fallback(node):
                    findings_a.append((rel, str(node.get("name") or "?")))

    findings_b: list[tuple[str, str, str, set]] = []
    checked_b = 0
    for wf_rel, pairs in DECIDE_SWITCH_PAIRS.items():
        wf_path = REPO / wf_rel
        if not wf_path.exists():
            findings_b.append((wf_rel, "?", "?", {"blueprint file not found"}))
            continue
        try:
            doc = load_blueprint(wf_path)
        except (OSError, ValueError) as e:
            findings_b.append((wf_rel, "?", "?", {f"could not parse: {e}"}))
            continue
        for decide_name, switch_name, functions in pairs:
            checked_b += 1
            decide_node = find_node(doc, decide_name)
            switch_node = find_node(doc, switch_name)
            if decide_node is None or switch_node is None:
                findings_b.append((wf_rel, decide_name, switch_name,
                                    {"node(s) not found — DECIDE_SWITCH_PAIRS entry may be stale"}))
                continue
            cases = rules_mode_cases(switch_node) or []
            gap = coverage_gap((decide_node.get("parameters") or {}).get("jsCode", ""), cases, functions)
            gap -= ROUTER_MEDIATED.get(wf_rel, set())
            if gap:
                findings_b.append((wf_rel, decide_name, switch_name, gap))

    if not findings_a and not findings_b:
        print(f"G41 PASS — {checked_a} rules-mode switch(es) all declare a fallbackOutput, and "
              f"{checked_b} decide/switch pair(s) have full case coverage.")
        return 0

    print(f"G41 FAIL")
    if findings_a:
        print(f"\n  check A — {len(findings_a)} rules-mode switch(es) with no fallbackOutput "
              f"(unmatched items are silently dropped):")
        for rel, name in findings_a:
            print(f"    {rel}  ::  {name!r}")
    if findings_b:
        print(f"\n  check B — {len(findings_b)} decide/switch pair(s) with a case-coverage gap:")
        for rel, decide_name, switch_name, gap in findings_b:
            print(f"    {rel}  ::  {decide_name!r} -> {switch_name!r}")
            print(f"        unreachable/dropped value(s): {sorted(gap)}")
    print(
        "\n  Give the switch a fallbackOutput wired to a stopAndError node (indoxV2Driver01.json's\n"
        "  Switch1 -> 'Stop and Error' is the pattern), and add a case + handler for every value\n"
        "  the decide function can actually return. A document that falls through here keeps its\n"
        "  current STATUS forever and is silently re-picked every sweep until MAX_ITERATIONS — no\n"
        "  error, no retry signal, no log line."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
