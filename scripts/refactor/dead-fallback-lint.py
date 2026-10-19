#!/usr/bin/env python3
"""dead-fallback-lint — gate G59: a switch branch no item can ever reach is dead code.

    python3 scripts/refactor/dead-fallback-lint.py [--self-test]

WHY THIS GATE EXISTS

On 2026-08-07 roughly three hours went into diagnosing why `syncV3SourcesTest01`'s `gmail-bs`
lane never applied its projection label. Three separate hypotheses about label *semantics* were
raised, one was deployed, and all of them were wrong — because the node everyone was reading,
`syncV3Deliver0001/Label Req`, HAS NEVER EXECUTED:

    Post Record Route  output 0 "thin-proj" : proj_on && mode=='thin' && src_kind=='drive'
                                                -> Proj Kind
    Proj Kind          output 0 "drive"     : src_kind=='drive'      -> Move Req
                       fallback  "gmail"                             -> Label Req

`Proj Kind`'s only inbound is `Post Record Route[0]`, whose rule already requires
`src_kind=='drive'`. So every item arriving at `Proj Kind` satisfies its rule 0, output 0 is
always taken, and the `gmail` fallback — with `Label Req` behind it — is unreachable. The code
reads as the gmail projection path. It is dead.

That is the third instance in one day of a plausible-looking mechanism that never runs
(`select_invoice_values` orphaned since the v2.1 rewrite; the `no_action_*` returns reachable
only via a direct call; this). Deleting the branch fixes one instance; this finds the next.

THE RULE

For a switch `S` with a fallback output, and a rule `R` on `S`:

    if EVERY inbound edge into S comes from a switch output whose own conditions
    already contain every condition of R, then R always matches, and every other
    output of S — including the fallback — is unreachable.

WHY IT IS CONSERVATIVE ON PURPOSE

Conditions are compared as EXACT (leftValue, operation, rightValue) triples. No attempt is made
to decide that `={{ $json.src_kind }}` and `={{ $('Item In').first().json.src_kind }}` are the
same field: they may well be, but proving it needs the execution model, and a gate that guesses
produces false positives on live workflows — which is how a gate gets switched off. Exact
matching means this reports only what it can prove, and stays silent where it cannot. It will
miss dead branches; it will not invent them.

Nodes with a single inbound edge from a non-switch are ignored entirely — an unconditional
predecessor constrains nothing.

WHAT THIS GATE DOES NOT COVER — read before trusting a green.
  * ONE mechanism only: an always-satisfied rule upstream. A branch dead for any other reason
    (an expression that is constant at runtime, a credential that always fails, a filter that
    never passes) is invisible here.
  * It reads committed blueprint JSON. It cannot see what is active in n8n.
  * `if` nodes are not analysed, only `switch` — an `if` has two live outputs by construction
    and its dead-branch cases need value analysis this deliberately does not do.
  * An unreachable branch is reported as DEAD CODE, not as a bug. Sometimes the right fix is to
    delete the branch; sometimes it is to fix the upstream rule that over-constrains it. This
    gate does not know which, and says so rather than prescribing.
"""
from __future__ import annotations

import argparse
import json
import pathlib
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


def _is_switch(node: dict) -> bool:
    return "switch" in str(node.get("type", "")).lower()


def _rules(node: dict) -> list[dict]:
    return ((node.get("parameters") or {}).get("rules") or {}).get("values", []) or []


def _has_fallback(node: dict) -> bool:
    opts = (node.get("parameters") or {}).get("options") or {}
    fb = opts.get("fallbackOutput")
    return fb is not None and fb != "none"


def _conds(rule: dict) -> set[tuple]:
    """A rule's conditions as exact comparable triples. An `or` combinator yields the empty
    set: 'any one of these' does not let us conclude a downstream rule always holds."""
    c = rule.get("conditions") or {}
    if str(c.get("combinator", "and")).lower() != "and":
        return set()
    out = set()
    for cond in c.get("conditions") or []:
        op = (cond.get("operator") or {}).get("operation")
        out.add((str(cond.get("leftValue")), str(op), json.dumps(cond.get("rightValue"),
                                                                sort_keys=True)))
    return out


def _inbound(conns: dict, name: str) -> list[tuple[str, int]]:
    out = []
    for src, c in conns.items():
        for bi, branch in enumerate(c.get("main") or []):
            for t in (branch or []):
                if isinstance(t, dict) and t.get("node") == name:
                    out.append((src, bi))
    return out


def scan_workflow(rel: str, data: dict) -> list[dict]:
    nodes = {n.get("name"): n for n in (data.get("nodes") or []) if isinstance(n, dict)}
    conns = data.get("connections") or {}
    findings = []

    for name, node in nodes.items():
        if not _is_switch(node) or not _has_fallback(node):
            continue
        rules = _rules(node)
        if not rules:
            continue
        ins = _inbound(conns, name)
        if not ins:
            continue

        # Every inbound must come from a switch output we can read conditions for.
        upstream: list[set] = []
        for src, bi in ins:
            snode = nodes.get(src)
            if snode is None or not _is_switch(snode):
                upstream = []
                break
            srules = _rules(snode)
            if bi >= len(srules):      # the fallback output of the parent: unconstrained
                upstream = []
                break
            sc = _conds(srules[bi])
            if not sc:
                upstream = []
                break
            upstream.append(sc)
        if not upstream:
            continue

        for ri, rule in enumerate(rules):
            rc = _conds(rule)
            if not rc:
                continue
            if all(rc <= u for u in upstream):
                dead = []
                for oi, branch in enumerate((conns.get(name) or {}).get("main") or []):
                    if oi == ri:
                        continue
                    dead += [t.get("node") for t in (branch or []) if isinstance(t, dict)]
                if not dead:
                    continue
                findings.append({
                    "file": rel, "node": name,
                    "rule": rule.get("outputKey") or ("rule %d" % ri),
                    "upstream": ["%s[%d]" % (s, b) for s, b in ins],
                    "dead": dead,
                    "conds": sorted(rc),
                })
    return findings


def scan() -> list[dict]:
    out = []
    for p in sorted(REPO.glob(BLUEPRINT_GLOB)):
        try:
            data = load_blueprint(str(p))
        except (OSError, ValueError, CompileError):
            continue
        if isinstance(data, dict):
            out += scan_workflow(str(p.relative_to(REPO)).replace("\\", "/"), data)
    return out


# ── self-test ────────────────────────────────────────────────────────────────────────────
#: THE REAL CASE, reduced to its shape: an upstream switch whose taken output already requires
#: `src_kind=='drive'`, feeding a switch that branches on the very same condition.
_DRIVE = {"leftValue": "={{ $('Item In').first().json.src_kind }}",
          "operator": {"operation": "equals"}, "rightValue": "drive"}
_THIN = {"leftValue": "={{ $('Item In').first().json.mode }}",
         "operator": {"operation": "equals"}, "rightValue": "thin"}


def _sw(name, rules, fallback="extra"):
    return {"name": name, "type": "n8n-nodes-base.switch",
            "parameters": {"rules": {"values": rules},
                           "options": {"fallbackOutput": fallback}}}


def _rule(key, conds, comb="and"):
    return {"outputKey": key, "conditions": {"combinator": comb, "conditions": conds}}


SELF_TEST = [
    ("THE REAL CASE: upstream already requires drive, so the gmail fallback is dead",
     {"nodes": [_sw("Post Record Route", [_rule("thin-proj", [_THIN, _DRIVE])]),
                _sw("Proj Kind", [_rule("drive", [_DRIVE])]),
                {"name": "Move Req", "type": "n8n-nodes-base.code"},
                {"name": "Label Req", "type": "n8n-nodes-base.code"}],
      "connections": {"Post Record Route": {"main": [[{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "Move Req"}],
                                             [{"node": "Label Req"}]]}}},
     1),
    # The same graph with a SECOND inbound that does NOT constrain src_kind: the fallback is
    # now reachable and must NOT be reported. This is the case that stops the gate over-firing
    # on any diamond-shaped graph.
    ("a second, unconstrained inbound makes the fallback reachable again",
     {"nodes": [_sw("Post Record Route", [_rule("thin-proj", [_THIN, _DRIVE])]),
                _sw("Other", [_rule("any", [_THIN])]),
                _sw("Proj Kind", [_rule("drive", [_DRIVE])]),
                {"name": "Move Req", "type": "n8n-nodes-base.code"},
                {"name": "Label Req", "type": "n8n-nodes-base.code"}],
      "connections": {"Post Record Route": {"main": [[{"node": "Proj Kind"}]]},
                      "Other": {"main": [[{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "Move Req"}],
                                             [{"node": "Label Req"}]]}}},
     0),
    ("an upstream `or` combinator proves nothing and must not fire",
     {"nodes": [_sw("Up", [_rule("x", [_THIN, _DRIVE], comb="or")]),
                _sw("Proj Kind", [_rule("drive", [_DRIVE])]),
                {"name": "A", "type": "n8n-nodes-base.code"},
                {"name": "B", "type": "n8n-nodes-base.code"}],
      "connections": {"Up": {"main": [[{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "A"}], [{"node": "B"}]]}}},
     0),
    ("arriving on the parent's FALLBACK output constrains nothing",
     {"nodes": [_sw("Up", [_rule("x", [_DRIVE])]),
                _sw("Proj Kind", [_rule("drive", [_DRIVE])]),
                {"name": "A", "type": "n8n-nodes-base.code"},
                {"name": "B", "type": "n8n-nodes-base.code"}],
      # index 1 is Up's fallback, not rule 0
      "connections": {"Up": {"main": [[], [{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "A"}], [{"node": "B"}]]}}},
     0),
    ("a non-switch predecessor constrains nothing",
     {"nodes": [{"name": "Code", "type": "n8n-nodes-base.code"},
                _sw("Proj Kind", [_rule("drive", [_DRIVE])]),
                {"name": "A", "type": "n8n-nodes-base.code"},
                {"name": "B", "type": "n8n-nodes-base.code"}],
      "connections": {"Code": {"main": [[{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "A"}], [{"node": "B"}]]}}},
     0),
    ("a switch with no fallback is out of scope",
     {"nodes": [_sw("Up", [_rule("x", [_DRIVE])]),
                _sw("Proj Kind", [_rule("drive", [_DRIVE])], fallback=None),
                {"name": "A", "type": "n8n-nodes-base.code"}],
      "connections": {"Up": {"main": [[{"node": "Proj Kind"}]]},
                      "Proj Kind": {"main": [[{"node": "A"}]]}}},
     0),
]


def self_test() -> int:
    bad = 0
    for label, wf, want in SELF_TEST:
        got = len(scan_workflow("t.json", wf))
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] expected %d, got %d: %s" % ("ok " if ok else "FAIL", want, got, label))
    print("\nG59 self-test: %d/%d passed" % (len(SELF_TEST) - bad, len(SELF_TEST)))
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    found = scan()
    n_files = len(list(REPO.glob(BLUEPRINT_GLOB)))
    # [2026-08-23 G66/C] AN EMPTY SCAN IS A RED, NEVER A PASS. This repo has already lived the
    # other way: twelve gates globbed apps/*/blueprint/n8n/*.json after blueprints became
    # .workflow.ts in 52b32aa4, matched nothing, looped over nothing, and printed their success
    # line for weeks. Green and blind are indistinguishable from OUTSIDE, so nothing surfaced it.
    # The glob is right today; this guard is what makes it stay honest if the layout moves again.
    if not n_files:
        print("G59 FAIL - scanned 0 blueprint(s) via %s. That is not a clean run, it is no run:"
              " a measurement over zero inputs is not a low score, it is no score." % BLUEPRINT_GLOB)
        return 1
    if not found:
        print("G59 PASS — no switch branch across %d blueprint(s) is provably unreachable "
              "via an always-satisfied upstream rule." % n_files)
        print("  Scope of this green is in the module docstring — ONE mechanism only.")
        return 0

    print("G59 FAIL — %d unreachable switch branch(es):" % len(found))
    for f in found:
        print("\n  %s  node=%r" % (f["file"], f["node"]))
        print("      rule %r always matches: every inbound (%s) already requires it"
              % (f["rule"], ", ".join(f["upstream"])))
        for c in f["conds"]:
            print("        %s %s %s" % c)
        print("      DEAD (nothing can reach these): %s" % ", ".join(f["dead"]))
    print("\n  Either delete the dead branch, or fix the upstream rule that over-constrains it.")
    print("  This gate cannot tell which is right — see its docstring.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
