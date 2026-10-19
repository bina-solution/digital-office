#!/usr/bin/env python3
"""open-destructive-webhook-lint — gate G67: an UNAUTHENTICATED webhook may not reach a
DELETE/TRUNCATE against a client table.

    python3 scripts/refactor/open-destructive-webhook-lint.py [--self-test]

WHY THIS EXISTS. Measured 2026-08-24: POST /webhook/indox-manage takes NO authentication, and its
Action switch routes RESET into IndoxResetFull01, whose 'Clear Table' node deletes every row of
public.incoming_documents but the bootstrap sentinel. The production baseline recorded in this repo
is ~39,000 documents in that table.

AUTHENTIK DOES NOT COVER IT, AND IS NOT MEANT TO. n8n's traefik routers carry no auth middleware
(only /rest/push has one, and that is an ORIGIN check). That is defensible on its own terms -
webhooks exist to be called by third parties, so a blanket SSO gate in front of /webhook/ would
break them. But it means each webhook node's own `authentication` field is the ONLY control there
is, and 13 of 28 INDOX webhooks set none. The asymmetry is the tell: `indox-mem-probe`, a read-only
probe returning {items, widthSeen}, REQUIRES basicAuth.

REACHABILITY IS TRANSITIVE, WHICH IS WHY REVIEW MISSES IT. Nobody wrote an open webhook next to a
DELETE. The webhook is in SyncApi0000000001; the DELETE is two workflows away in IndoxResetFull01.
Reading either file alone shows nothing wrong. This walks the executeWorkflow graph so the distance
stops hiding it - which is the whole reason it is a gate and not a one-off fix.

SCOPE. A DELETE against a fixture/test table is NOT this gate's business: G58 already proves every
cleanup query is prefix-scoped. This asks a different question - who is allowed to reach one.

WHAT A FINDING IS AND IS NOT - read this before rating one. This is a REACHABILITY
over-approximation. It proves an unauthenticated webhook can reach a WORKFLOW that contains a
client-table DELETE. It does NOT prove the caller can steer execution to that node: indoxApi01 is a
router and its PG Delete sits behind an INLINE_ACTION branch, so reaching indoxApi01 is not the same
as reaching the delete. Exactly one finding here is proven routable end to end, by reading the
switch: /webhook/indox-manage with INLINE_ACTION=RESET reaches IndoxResetFull01 'Clear Table'. Treat
the rest as "worth checking per branch", not as nine holes. A gate that overstates gets ignored as
fast as one that misses.

EXEMPTIONS are explicit and each carries a reason. The five *-e2e-lane suite runners delete their
own fixtures by design and are legitimately open; "it is a test lane" is not something the gate can
infer from the blueprint, so it has to be written down next to the exemption.
"""
import argparse
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "scripts" / "refactor"))

# THE CLIENT'S DOCUMENTS, and deliberately nothing else.
#
# The first version listed sync_ledger, sync_attempt, sync_cursor, drive_files, settings, tag_rules
# and indox_action_execution_log too, and reported 34 findings. Nearly all were syncLedgerApi01's
# own `delete from public.sync_ledger` on release/quarantine - routine per-row engine bookkeeping,
# reached transitively because almost every workflow calls the ledger API. A gate that reports 34
# findings where two matter is a gate people learn to ignore, and an ignored gate is worse than none.
#
# incoming_documents is the asset whose loss is unrecoverable: the production baseline in this repo
# is ~39,000 client documents, and IndoxResetFull01 empties it in one statement. Engine state
# (ledger, attempts, cursors) is rebuildable by re-listing the source - that is the entire design of
# the move-back in syncLedgerApi01. Losing it costs a re-sync; losing the documents costs the client.
#
# Widen this list only with a reason written here, and expect the noise cost to be real.
CLIENT_TABLES = ("incoming_documents",)

EXEMPT = {
    "gdoc-e2e-lane": "suite runner; deletes only its own gdx_/gdt_ fixtures (G58 polices the scope)",
    "pipeline-e2e-lane": "suite runner; deletes only its own plx_/plb_ fixtures",
    "sync-full-e2e-lane": "suite runner; deletes only its own sv3f_ fixtures",
    "sync-kernel-e2e-lane": "suite runner; deletes only its own sv3k_ fixtures",
    "sync-sources-e2e-lane": "suite runner; deletes only its own sv3s_ fixtures",
}

DESTRUCTIVE = re.compile(
    r"\b(delete\s+from|truncate\s+(table\s+)?)\s+(public\.)?(" + "|".join(CLIENT_TABLES) + r")\b",
    re.I)


def blueprints():
    """Every blueprint this deployment can execute, keyed by workflow id."""
    out = {}
    dirs = sorted(REPO.glob("apps/*/blueprint/n8n"))
    dirs.append(REPO / "apps" / "n8n" / "blueprint" / "n8n")
    for d in dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.workflow.ts")):
            # NOT f.stem. `.workflow.ts` has TWO extensions, so stem yields "X.workflow" while every
            # executeWorkflow target is the bare "X" - the call graph then resolves NOTHING and the
            # gate silently degrades to same-workflow findings only, i.e. it stops asking the one
            # question it exists for. This is the identical bug fixture-sweep.py records for
            # owner_stem ("rsplit('.',1)[0], written when owners were .json"), reproduced here and
            # caught only because the real estate's finding came back with a ".workflow" suffix in
            # the id. Verified by the transitive self-test case, which passes on synthetic ids and
            # therefore could NOT have caught this - it took the live run.
            out[f.name[:-len(".workflow.ts")]] = f
    return out


def load_all(paths):
    from n8n_blueprint import load
    wfs = {}
    for wid, f in paths.items():
        try:
            wfs[wid] = load(str(f))
        except Exception as e:
            # A blueprint this gate cannot READ is not a pass - it is an unanswered question.
            wfs[wid] = {"_unreadable": str(e), "nodes": []}
    return wfs


def analyse(wfs):
    """(call graph, destructive nodes per workflow, unauthenticated webhooks)."""
    calls, destructive, open_hooks = {}, {}, []
    for wid, wf in wfs.items():
        for n in wf.get("nodes") or []:
            t = n.get("type", "")
            p = n.get("parameters") or {}
            if t.endswith("executeWorkflow"):
                # REAL targets only. A text mention is not a call - conflating the two is how
                # "3 production callers" survived for SyncApi0000000001 when there was one.
                tgt = p.get("workflowId")
                tgt = tgt.get("value") if isinstance(tgt, dict) else tgt
                if tgt:
                    calls.setdefault(wid, set()).add(str(tgt))
            if t.endswith("webhook") and (p.get("authentication") or "NONE") == "NONE":
                open_hooks.append((wid, p.get("path") or "?", n.get("name", "?")))
            blob = " ".join(str(v) for v in p.values() if isinstance(v, str))
            m = DESTRUCTIVE.search(blob)
            if m:
                destructive.setdefault(wid, []).append((n.get("name", "?"), m.group(0)))
    return calls, destructive, open_hooks


def reach(start, calls, seen=None):
    """Transitive executeWorkflow closure. Cycle-safe: a workflow already seen is not re-walked."""
    seen = seen if seen is not None else set()
    for nxt in calls.get(start, ()):
        if nxt not in seen:
            seen.add(nxt)
            reach(nxt, calls, seen)
    return seen


def run(wfs):
    calls, destructive, open_hooks = analyse(wfs)
    findings = []
    for wid, path, node in open_hooks:
        if path in EXEMPT:
            continue
        for target in [wid] + sorted(reach(wid, calls)):
            for nname, stmt in destructive.get(target, []):
                hop = "in the same workflow" if target == wid else "via " + target
                findings.append((path, wid, node, target, nname, stmt.strip(), hop))
    return findings, len(open_hooks)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()

    paths = blueprints()
    if not paths:
        # An empty scan is a red, never a pass - twelve gates once reported green over zero files.
        print("[open-destructive-webhook-lint] FAIL - scanned ZERO blueprints. "
              "An empty scan is a red, never a pass.")
        return 1

    wfs = load_all(paths)
    unreadable = [w for w, x in wfs.items() if x.get("_unreadable")]
    findings, n_open = run(wfs)
    print("[open-destructive-webhook-lint] %d blueprint(s), %d unauthenticated webhook(s)"
          % (len(wfs), n_open))
    for u in unreadable:
        print("  ! cannot read %s: %s" % (u, wfs[u]["_unreadable"][:120]))

    if findings:
        print("")
        print("[open-destructive-webhook-lint] FAIL - %d open webhook path(s) reach a client-table "
              "DELETE/TRUNCATE:" % len(findings))
        for path, wid, node, target, nname, stmt, hop in findings:
            print("  /webhook/%s  (%s / %s, authentication: NONE)" % (path, wid, node))
            print("      reaches %s / %s %s" % (target, nname, hop))
            print("      %s" % stmt)
        print("")
        print("  REACHABILITY, NOT EXPLOITABILITY: this proves the webhook can reach a WORKFLOW")
        print("  containing the DELETE, not that a caller can steer execution to that node. Verify")
        print("  the branch before rating one. Proven routable today: indox-manage + RESET.")
        print("  Set `authentication` on the webhook, or add an EXEMPT entry SAYING WHY it may be open.")
        print("  MIND THE PAIRED CHANGE: closing the gate breaks any caller that does not send the")
        print("  credential. The BFF's _svc_call sends none today, so indox-manage needs both halves.")
        return 1

    if unreadable:
        return 1
    print("[open-destructive-webhook-lint] PASS - no unauthenticated webhook reaches a client-table "
          "DELETE/TRUNCATE")
    return 0


def self_test():
    """The real defect is the first fixture: an open hook TWO hops from a client DELETE."""
    def wf(nodes):
        return {"nodes": nodes}

    def hook(path, auth):
        return {"type": "n8n-nodes-base.webhook", "name": "W",
                "parameters": {"path": path, "authentication": auth}}

    def call(target):
        return {"type": "n8n-nodes-base.executeWorkflow", "name": "C",
                "parameters": {"workflowId": {"value": target}}}

    DEL = {"type": "n8n-nodes-base.postgres", "name": "Clear",
           "parameters": {"query": "delete from public.incoming_documents where a=1"}}
    OTHER = {"type": "n8n-nodes-base.postgres", "name": "ClearFix",
             "parameters": {"query": "delete from public.some_other_table where a=1"}}

    cases = []
    f, _ = run({"A": wf([hook("p", "NONE"), call("B")]), "B": wf([call("C")]), "C": wf([DEL])})
    cases.append(("an open webhook TWO hops from a client DELETE is caught", len(f), 1))
    f, _ = run({"A": wf([hook("p", "basicAuth"), call("B")]), "B": wf([DEL])})
    cases.append(("an AUTHENTICATED webhook is not a finding", len(f), 0))
    f, _ = run({"A": wf([hook("p", "NONE"), call("B")]), "B": wf([OTHER])})
    cases.append(("a DELETE on a non-client table is not this gate's business", len(f), 0))
    f, _ = run({"A": wf([hook("p", "NONE")])})
    cases.append(("an open webhook reaching nothing destructive is fine", len(f), 0))
    f, _ = run({"A": wf([hook("gdoc-e2e-lane", "NONE"), call("B")]), "B": wf([DEL])})
    cases.append(("an EXEMPT suite runner is allowed", len(f), 0))
    # a cycle must not hang the walk
    f, _ = run({"A": wf([hook("p", "NONE"), call("B")]), "B": wf([call("A"), DEL])})
    cases.append(("a call CYCLE terminates and still reports", len(f), 1))

    bad = 0
    for name, got, want in cases:
        ok = got == want
        bad += 0 if ok else 1
        print("  [%s] %s  (got %s, want %s)" % ("ok " if ok else "FAIL", name, got, want))
    print("")
    print("open-destructive-webhook-lint self-test: %d/%d passed" % (len(cases) - bad, len(cases)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
