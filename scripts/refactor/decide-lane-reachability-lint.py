#!/usr/bin/env python3
"""decide-lane-reachability-lint — every action a decide RETURNS must have a router lane, and
every router lane must be RETURNED by some decide.

    python3 scripts/refactor/decide-lane-reachability-lint.py [--self-test]

WHY. Seven times this month a change swept its source cleanly and left a reader stranded, and
every one was found days later by something going red:

    JSON blueprints retired        -> 8 consumers still opening .json
    indoxApiSupabase01 retired     -> sync-coverage.py still measuring it
    ACTION_LOG column dropped      -> gdoc's query left as "AS final_status AS action_log"
    ACTION_HISTORY moved tables    -> no suite's cleanup knew; 142 stale rows blocked re-dispatch
    owner paths gained a dot       -> the fixture sweep silently swept nothing, ever
    single-value resolvers retired -> 10 router lanes with no producer, 10 test cases asserting them
    typed restarts superseded      -> 2 decide branches unreachable by construction

The last two are what this gate makes impossible to repeat. Both are a BROKEN EDGE between two
halves of the state machine that live in different parts of the file and are edited apart:

    decide  (gdocDecide / shipmentDecide / bsDecide / docBaseDecide)   returns an action name
    router  (the switch nodes in indoxV2Actions*01)                    has a lane per action name

Remove a decide branch and its lane becomes unreachable. Rename an action in decide and the old
lane dies AND the new name has no lane, so the router falls through. Neither shows up in any test
unless a suite happens to drive that exact branch — which is how ten lanes stayed dead long enough
for a whole test file to rot around them.

WHAT IT IS NOT. It does not check that a lane's handler is correct, or that decide's precedence is
right. It checks the one property that is mechanically true or false: both directions of the name
edge. That narrowness is the point — it runs on every commit in under a second, needs no stack and
no database, and cannot be flaky.

EXEMPTIONS live in the EXEMPT table below, each with its reason. An exemption is a decision
somebody wrote down; an unlisted orphan is an accident.
"""
import os
import pathlib
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from n8n_blueprint import load, CompileError            # noqa: E402  (path set above)

REPO = pathlib.Path(__file__).resolve().parents[2]
BLUEPRINTS = REPO / "apps" / "indox" / "blueprint" / "n8n"

#: The blueprints holding BOTH a decide function and the action router it feeds.
ROUTERS = ["indoxV2ActionsGlobal01", "indoxV2ActionsInv01",
           "indoxV2ActionsBS01", "indoxV2ActionsShip01"]

#: action -> why it is allowed to exist on one side only.
EXEMPT = {
    # [2026-08-23] indoxV2Decide01 emits this from a TERNARY, not a `return`, so this linter's
    # parser cannot see it:
    #     : (__st === 'DOUBLE' ? 'no_action_double' : 'update_status_double');
    # It was previously rescued by an explicit `return 'no_action_double'` in the three lane
    # guards, which read DOUBLE_LINE_CONTEXT.merge_sig. merge_sig was retired, that read went
    # with it, and the lane looked dead the moment it did. It is not: update_status_double comes
    # off the SAME ternary and has sat on this list all along while measurably dispatching (375
    # armed dispatches counted 2026-08-23), which is the proof the blind spot is in the parser
    # and not in the graph. Exempt until the parser understands ternary returns.
    "no_action_double": "emitted by indoxV2Decide01's ternary, which this parser cannot read",
    # Routing sentinels: docBaseDecide returns these to hand a row to a typed decide. They are
    # consumed by indoxV2Decide01's dispatch loop, never by a router lane.
    "__route_bs__": "routing sentinel read by indoxV2Decide01, not a dispatchable action",
    "__route_gdoc__": "routing sentinel read by indoxV2Decide01, not a dispatchable action",
    # [2026-09-03] The feedback action is emitted per SOURCE_LIST entry as 'source_feedback_' + i
    # (a concatenation this parser reads as the literal prefix), and the router lane is the bare
    # name. Executed proof the same day: the real E2E run (tag e2e-final-1840) logged
    # `source_feedback_0` dispatches on every completed document, 3 s each, labels and folders
    # moved. One lane, one producer, one blind spot in the parser — both spellings exempt.
    "source_feedback": "fed by indoxV2Decide01's 'source_feedback_' + index, executed live 2026-09-03",
    "source_feedback_": "the static prefix of the same concatenation; the lane is source_feedback",
    "__route_shipment__": "routing sentinel read by indoxV2Decide01, not a dispatchable action",
    # resolveDocType lives inside 'Decide DOC BASE Action' and returns the row's TYPE, which
    # travels beside the action as DOC_TYPE. Types are not actions and no router dispatches one.
    "gdoc": "a DOC_TYPE returned by resolveDocType, not an action",
    "bs_doc": "a DOC_TYPE returned by resolveDocType, not an action",
    "shipment": "a DOC_TYPE returned by resolveDocType, not an action",
    "unknown": "a DOC_TYPE returned by resolveDocType, not an action",
    "empty": "a DOC_TYPE returned by resolveDocType, not an action",
    # The router's own fall-through label, reached when no lane matched. By construction it can
    # have no producer - that is what makes it the fall-through.
    "__unhandled_action__": "the router fall-through lane; having no producer is its definition",
}


#: The four nodes that decide an action, one per router. THE NODE IS THE BOUNDARY, not the
#: function. Slicing function bodies out of a 48 KB jsCode block (from one `function X(` header
#: to the next) silently dropped branches that sat past a nested declaration — it lost
#: `no_action_paused` and `update_status_missing_type`, both of which the decide suite proves are
#: returned. A node name is unambiguous and cannot drift out from under the reader.
DECIDE_NODE = re.compile(r"^Decide .*Action$")

#: The ACTION router switch in each blueprint — 'DOC BASE Action Switch', '3a. GDOC Action
#: Switch1', '3b. BS Action Switch1'. Each file also holds switches that route something else
#: entirely: 'Route Mode' (the api mode), 'Route Feedback Op', 'Switch: Found?1'. Reading those
#: as action lanes produced 'decide', 'export_decide', 'mail_tag', 'drive_move', 'found' and
#: 'source_feedback' as orphan actions — six findings that were only ever a mode name.
ACTION_SWITCH = re.compile(r"Action Switch")


def decide_returns(body):
    """Action names one decide node can produce: plain returns, both arms of a ternary, and the
    ACTION field of a returned item.

    A regex, deliberately. The alternative is executing the blueprint's own JS, and a gate that
    has to run the thing it checks can be broken by the thing it checks.
    """
    out = set()
    for m in re.finditer(r"return\s+'([a-z_][a-z0-9_]*)'", body):
        out.add(m.group(1))
    for m in re.finditer(
            r"return\s+[^;\n]*\?\s*'([a-z_][a-z0-9_]*)'\s*:\s*'([a-z_][a-z0-9_]*)'", body):
        out.add(m.group(1))
        out.add(m.group(2))
    # Some branches return the whole item rather than a bare name -
    #     return { json: { ACTION: 'no_action_merged', DOC_TYPE: ..., ...normDoc } };
    # which is just as much a decision, and was invisible while only bare returns were read.
    for m in re.finditer(r"ACTION:\s*'([a-z_][a-z0-9_]*)'", body):
        out.add(m.group(1))
    return out


def router_lanes(wf):
    """outputKeys on every switch node — the lanes a router can dispatch to.

    BOTH switch shapes, because this estate runs both and reading only one is how a gate reports
    a confident, wrong answer. The action routers are typeVersion 2:

        parameters.rules.rules[]   {"value2": "update_name", "outputKey": "update_name"}

    while newer switches (driveApi01's Op Switch, the driver's) are typeVersion 3.2:

        parameters.rules.values[]  {"conditions": {...}, "outputKey": "..."}

    Read v3 only and this gate finds 4 lanes across four routers instead of 60, then declares
    almost every real action an orphan — which is exactly what it did on its first run.


    THE MATCHED VALUE IS `value2`, NOT `outputKey`. outputKey is only the branch's display label
    and the two are free to differ — indoxV2ActionsGDoc01 matches 'action_priority_sync' into a
    lane labelled 'priority_sync'. Comparing decide's returns against outputKey therefore invents
    a finding in each direction at once: an action with no lane AND a lane with no producer, for
    one edge that is perfectly connected.
    """
    out = set()
    for n in wf.get("nodes", []):
        if not str(n.get("type", "")).endswith(".switch"):
            continue
        if not ACTION_SWITCH.search(n.get("name", "")):
            continue
        rules = n.get("parameters", {}).get("rules") or {}
        for rule in (rules.get("values") or []) + (rules.get("rules") or []):
            vals = []
            if isinstance(rule.get("value2"), str):                       # switch v1/v2
                vals.append(rule["value2"])
            for c in ((rule.get("conditions") or {}).get("conditions") or []):   # switch v3
                if isinstance(c.get("rightValue"), str):
                    vals.append(c["rightValue"])
            if not vals and isinstance(rule.get("outputKey"), str):       # label as last resort
                vals.append(rule["outputKey"])
            for v in vals:
                if re.fullmatch(r"[a-z_][a-z0-9_]*", v):
                    out.add(v)
    return out


def collect(stems=None):
    """(decided, laned) — the two name sets, across every router blueprint."""
    decided, laned = set(), set()
    for stem in (stems or ROUTERS):
        wf = load(BLUEPRINTS / (stem + ".workflow.ts"))
        laned |= router_lanes(wf)
        for n in wf.get("nodes", []):
            js = (n.get("parameters", {}) or {}).get("jsCode")
            if isinstance(js, str) and DECIDE_NODE.match(n.get("name", "")):
                decided |= decide_returns(js)
    return decided, laned


def findings(decided, laned):
    out = []
    for a in sorted(laned - decided):
        if a not in EXEMPT:
            out.append(("lane-with-no-producer", a,
                        "a router lane no decide returns - a dead dispatch target"))
    for a in sorted(decided - laned):
        if a not in EXEMPT:
            out.append(("action-with-no-lane", a,
                        "a decide returns this and no lane handles it - the router falls through"))
    return out


def main():
    if "--self-test" in sys.argv:
        return self_test()
    try:
        decided, laned = collect()
    except CompileError as ex:
        print("decide-lane-reachability: CANNOT READ BLUEPRINTS")
        print("  %s" % ex)
        return 2
    fs = findings(decided, laned)
    dead = [f for f in fs if f[0] == "lane-with-no-producer"]
    homeless = [f for f in fs if f[0] == "action-with-no-lane"]
    strict = "--strict" in sys.argv

    print("decide-lane-reachability: %d decided action(s), %d router lane(s), %d exemption(s)"
          % (len(decided), len(laned), len(EXEMPT)))

    # THE DIRECTION THAT FAILS. A lane with no producer is unambiguous: a dispatch target nothing
    # can reach. Verified independently by hand against indoxV2ActionsGDoc01 before this gate
    # existed, and it reproduces that list.
    for _k, name, why in dead:
        print("  [dead-lane]  %-34s %s" % (name, why))

    # THE DIRECTION THAT ONLY ADVISES, for now. Several of these are almost certainly fine and
    # the rule that says so is not written yet:
    #   * the no_action_* family may be terminal BY NAME and need no lane at all - except some of
    #     them do have lanes, so "no_action_ means no lane" is not yet a rule, it is a guess;
    #   * link_documents_r and source_feedback_ are PREFIXES of names built at runtime
    #     (link_documents_r1, _r2 ...), which no static lane can match literally;
    #   * success / failure / pending look like helper returns inside the decide node rather than
    #     actions.
    # Reporting them as failures would make this a gate people learn to ignore, which is worse
    # than not having it. They print, they do not fail, until each class has a rule.
    if homeless:
        print("")
        print("  ADVISORY (not a failure yet - see the note in main()):")
        for _k, name, why in homeless:
            print("    [no-lane] %-34s %s" % (name, why))

    print("")
    if not dead:
        print("PASS - every router lane has a producer%s"
              % ("" if not homeless else "; %d advisory item(s) above" % len(homeless)))
        return 1 if (strict and homeless) else 0
    print("%d dead lane(s). Remove the lane, or restore the decide branch that fed it, or add "
          "the name to EXEMPT with the reason it is one-sided." % len(dead))
    return 1


# -- self-test ---------------------------------------------------------------------------------
def self_test():
    bad = []

    def chk(label, cond):
        print("  [%s] %s" % ("ok " if cond else "FAIL", label))
        if not cond:
            bad.append(label)

    chk("a plain return is picked up", decide_returns("return 'find_link';") == {"find_link"})
    chk("both arms of a ternary return are picked up",
        decide_returns("return x ? 'no_action_double' : 'update_status_double';")
        == {"no_action_double", "update_status_double"})
    chk("an upper-case status is not mistaken for an action",
        decide_returns("return 'COMPLETED';") == set())
    # A branch may return the whole item instead of a bare name; that is still a decision.
    chk("an ACTION field on a returned item counts",
        decide_returns("return { json: { ACTION: 'no_action_merged', DOC_TYPE: t } };")
        == {"no_action_merged"})
    # THE NODE IS THE BOUNDARY. Slicing function bodies out of a 48 KB block dropped branches
    # past a nested declaration - it lost no_action_paused and update_status_missing_type,
    # both of which the decide suite proves are returned.
    chk("the decide node name is what selects a block",
        all(DECIDE_NODE.match(n) for n in ("Decide DOC BASE Action", "Decide GDoc Action",
                                           "Decide BS Action", "Decide Shipment Action")))
    chk("a non-decide node name is not selected",
        not any(DECIDE_NODE.match(n) for n in ("Adjudicate Merge", "Dedupe Docs (execute)",
                                               "Build: Restart (clear completed flags)")))
    chk("switch v3 outputKeys (rules.values) are read as lanes",
        router_lanes({"nodes": [{"name": "X Action Switch", "type": "n8n-nodes-base.switch", "parameters": {"rules": {
            "values": [{"outputKey": "find_link"}, {"outputKey": "mark_completed"}]}}}]})
        == {"find_link", "mark_completed"})
    # The action routers are typeVersion 2 and use rules.rules[]. Reading only the v3 shape found
    # 4 lanes across all four routers instead of 60 and called nearly every action an orphan.
    chk("switch v2 outputKeys (rules.rules) are read as lanes",
        router_lanes({"nodes": [{"name": "X Action Switch", "type": "n8n-nodes-base.switch", "parameters": {"rules": {
            "rules": [{"value2": "update_name", "outputKey": "update_name"}]}}}]})
        == {"update_name"})
    chk("a node carrying both shapes yields both",
        router_lanes({"nodes": [{"name": "X Action Switch", "type": "n8n-nodes-base.switch", "parameters": {"rules": {
            "values": [{"outputKey": "a"}], "rules": [{"outputKey": "b"}]}}}]}) == {"a", "b"})
    # Each router also holds switches that route something else entirely; reading those as
    # action lanes produced six findings that were only ever a mode name.
    chk("only an Action Switch contributes lanes",
        all(ACTION_SWITCH.search(n) for n in ("DOC BASE Action Switch", "3a. GDOC Action Switch1", "3b. BS Action Switch1"))
        and not any(ACTION_SWITCH.search(n) for n in ("Route Mode", "Route Feedback Op",
                                                      "Switch: Found?1", "Switch2")))
    chk("a switch that is not an Action Switch contributes no lane",
        router_lanes({"nodes": [{"name": "Route Mode", "type": "n8n-nodes-base.switch",
                                 "parameters": {"rules": {"rules": [{"value2": "decide"}]}}}]})
        == set())
    chk("a non-switch node contributes no lane",
        router_lanes({"nodes": [{"type": "n8n-nodes-base.code", "parameters": {}}]}) == set())

    # The gate must FAIL on the two shapes it exists to catch, or it is decoration.
    chk("a lane with no producer IS a finding",
        any(f[1] == "orphan_lane" for f in findings({"a"}, {"a", "orphan_lane"})))
    chk("an action with no lane IS a finding",
        any(f[1] == "homeless" for f in findings({"a", "homeless"}, {"a"})))
    chk("a balanced pair is silent", findings({"a"}, {"a"}) == [])
    chk("an exempt name is silent in both directions",
        findings({"__route_bs__"}, set()) == [] and findings(set(), {"__route_bs__"}) == [])

    print("")
    print("decide-lane-reachability self-test: %s" % ("FAILED" if bad else "all passed"))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
