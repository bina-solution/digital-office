#!/usr/bin/env python3
"""open-destructive-webhook-lint — gate G67: an UNAUTHENTICATED webhook may not reach a
DELETE/TRUNCATE against a client table.

    python3 scripts/refactor/open-destructive-webhook-lint.py [--self-test]

WHY THIS EXISTS. Measured 2026-08-24: POST /webhook/indox-manage takes NO authentication, and its
Action switch routes RESET into IndoxResetFull01, whose 'Clear Table' node deletes every row of
public.incoming_documents but the bootstrap sentinel. The production baseline recorded in this repo
is ~N documents in that table.

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

EXEMPTIONS are explicit and each carries a reason. The *-e2e-lane suite runners (five, then
thirteen) delete their own fixtures by design and are legitimately open. "It is a test lane" is not
something the gate can infer from the blueprint, so it has to be written down next to the exemption.

STATUS, 2026-11-10 (DGO-433).
- The indox-manage + RESET path closed on 2026-08-31 (0f8f3cfa). RESET goes through syncLedgerApi01
  ("never SQL here"), and only `hooks/reset` and the suite harness start IndoxResetFull01, through
  the CLI.
- The same cutover made every client DELETE per instance, and the pattern below knew only `public.`.
  So the gate turned green BLIND: of the 20 client DELETE nodes in 94 blueprints it saw 1, and that
  one was a JS comment.
- It sees all 20 now: Clear Table, indoxApi01's PG Delete, and 18 suite cleanups. It is red with 5
  findings, all of them open webhooks reaching PG Delete, which runs only when INLINE_ACTION = 'DELETE'.
  No caller sends that (DGO-433 measured it from the blueprints).
- Those five are KNOWN_REACH below (2026-11-10, the release, DGO-969): set aside BY THEIR EXACT TRIPLE and
  printed on every run, never hidden; DGO-1759 closes them (authentication with their callers, or indoxApi01
  refusing a DELETE from an undeclared caller). Until then this gate is green for the CI to read, and red
  the moment anything else reaches a client DELETE. It does not model router branches.
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
# is ~N client documents, and IndoxResetFull01 empties it in one statement. Engine state
# (ledger, attempts, cursors) is rebuildable by re-listing the source - that is the entire design of
# the move-back in syncLedgerApi01. Losing it costs a re-sync; losing the documents costs the client.
#
# Widen this list only with a reason written here, and expect the noise cost to be real.
CLIENT_TABLES = ("incoming_documents",)

#: (workflow id, webhook path) -> why its OWN cleanup may sit behind an open hook. [2026-11-10]
#: An exemption is keyed by workflow AND path, so another workflow that opens the same path does not
#: inherit it. It covers two things:
#: - the DELETE nodes inside the lane's own workflow, which is what each reason describes;
#: - what the lane reaches through executeWorkflow, but ONLY while the gate itself measures that the
#:   lane pins `__instance` to the literal 'test' everywhere it sets it (pins_test). Every client
#:   DELETE is per instance, so a lane pinned to the test instance can only reach indox_test's rows.
#: A lane that gives `__instance` any other value, or an expression, has its reach reported.
EXEMPT = {
    ("indoxV2DecideTest01", "decide-e2e-lane"): "suite runner; no DELETE of its own; drives the router with __instance pinned to 'test'",
    ("indoxV2GDocTest01", "gdoc-e2e-lane"): "suite runner; deletes only its own gdx_/gdt_ fixtures (G58 polices the scope)",
    ("indoxV2PipelineTest01", "pipeline-e2e-lane"): "suite runner; deletes only its own plx_/plb_ fixtures",
    ("syncFullTest01", "sync-full-e2e-lane"): "suite runner; deletes only its own sv3f_ fixtures",
    ("syncItemApiTest01", "sync-kernel-e2e-lane"): "suite runner; deletes only its own sv3k_ fixtures",
    ("syncSourcesTest01", "sync-sources-e2e-lane"): "suite runner; deletes only its own sv3s_ fixtures",
    # Eight more, found 2026-11-10 (DGO-433) the moment the gate could see an instance schema.
    # Each deletes ONLY from indox_test, the declared test instance (platform.state.default.yaml
    # bootstrap_seed, purpose: test). Each scope was read in the blueprint, and G58 polices it.
    ("indoxV2BSTest01", "bs-e2e-lane"): "suite runner; deletes from indox_test only its own case's rows (LINKED_BS/SOURCE_ID/ID from Config)",
    ("indoxV2DocBaseTest01", "doc-base-e2e-lane"): "suite runner; deletes from indox_test only its db_/dbf_/dbe_ fixtures",
    ("indoxV2SealedBS01", "sealed-bs-e2e-lane"): "suite runner; deletes from indox_test only its slb_ fixtures",
    ("indoxV2SealedInv01", "sealed-inv-e2e-lane"): "suite runner; deletes from indox_test only its sli_ fixtures",
    ("indoxV2SealedOrd01", "sealed-ord-e2e-lane"): "suite runner; deletes from indox_test only its slo_ fixtures",
    ("indoxV2SealedRcp01", "sealed-rcp-e2e-lane"): "suite runner; deletes from indox_test only its slr_ fixtures",
    ("indoxV2SealedShip01", "sealed-ship-e2e-lane"): "suite runner; deletes from indox_test only its sls_ fixtures",
    ("mailOrgTest00001", "mail-organizer-e2e-lane"): "suite runner; deletes from indox_test only its mailorg_ rows (SYNC_NAME)",
}

# A REACH this gate reports and someone has DECIDED on, each with its measurement and the item that closes it.
# EXEMPT above speaks only for a lane's OWN cleanup; this speaks for one webhook (its workflow AND its path)
# reaching one node of ANOTHER workflow whose statement is the one decided on — nothing near it: a new webhook,
# the same path in another workflow, another node, or that node's statement changed, is still a finding. An
# entry that matches nothing fails the gate (the reach was closed: delete the line), as G31's DEBT does.
# (the webhook's workflow, its path, the workflow reached, the node) → why.
#
# 2026-11-10 (the release, DGO-969): the five that DGO-433 measured and parked in run-gates.py's KNOWN_RED, which
# the CI's gates.sh does not read — so CI stayed red with nothing new to say. indoxApi01's PG Delete runs only on
# INLINE_ACTION = 'DELETE': the 29 callers of indoxApi01 send UPSERT/GET/TABLE_GET/GET_ALL/TABLE_UPSERT/DELIVER/
# MERGE, none DELETE, none computes it (measured from the blueprints, DGO-433); but indoxApiRouter01 passes its
# caller's item through, and the two e2e lanes take __instance from the request — so none is proven routable and
# none proven safe. What shields them today is outside this gate: DGO-1603's private-range ipWhitelist on all five
# (and indoxSettings01 is inactive). DGO-1759 closes them — authentication with their callers (the BFF's
# _svc_call), or indoxApi01 refusing a DELETE from an undeclared caller — and deletes these lines.
_PG_DELETE = ("PG Delete runs only on INLINE_ACTION='DELETE' — no caller sends it, but the router passes a caller's item "
              "through: not proven safe (DGO-433); the private-range ipWhitelist (DGO-1603) shields it; DGO-1759 closes it")
#: the statement the decision was made on — a node that holds anything else is not the decided reach
_PG_DELETE_STMT = 'delete from indox_" + i + ".incoming_documents'
KNOWN_REACH = {
    ("SyncApi0000000001", "indox-manage", "indoxApi01", "PG Delete"): _PG_DELETE,
    ("indoxSettings01", "query", "indoxApi01", "PG Delete"): _PG_DELETE,
    ("mailApi01", "mail-api/doc-context", "indoxApi01", "PG Delete"): _PG_DELETE,
    ("syncItemApiTest01", "sync-kernel-e2e-lane", "indoxApi01", "PG Delete"): _PG_DELETE,
    ("syncSourcesTest01", "sync-sources-e2e-lane", "indoxApi01", "PG Delete"): _PG_DELETE,
}


def decided(findings):
    """(findings still open, findings KNOWN_REACH speaks for, KNOWN_REACH keys that matched nothing) — by the
    exact (webhook workflow, path, target, node), and only while the node's statement is the decided one."""
    left, known, used = [], [], set()
    for f in findings:
        path, wid, _node, target, nname, stmt = f[:6]
        key = (wid, path, target, nname)
        if key in KNOWN_REACH and _PG_DELETE_STMT in stmt:
            known.append(f)
            used.add(key)
        else:
            left.append(f)
    return left, known, sorted(set(KNOWN_REACH) - used)

# The schema in front of the table, in every spelling the fleet uses. Since the 2026-08-31 cutover
# (0f8f3cfa) every client DELETE is per instance, and the old `(public\.)?` saw none of them:
#   IndoxResetFull01 'Clear Table'  delete from {{ (() => { …resolver… })() }}.incoming_documents …
#   indoxApi01 'PG Delete'          "delete from indox_" + i + ".incoming_documents where …"
#   the e2e lanes' cleanups         delete from indox_test.incoming_documents where …
# Measured 2026-11-10 (DGO-433) over 94 blueprints: the old pattern saw 1 node, and that one was a JS
# COMMENT in IndoxResetFull01's 'Reset Scope'. Accepted here, each one tested:
#   a bare or quoted name, with whitespace around the dot (`public.`, `indox_test . "x"`; G58 spells
#   the same table the same way);
#   an n8n expression `{{ … }}.`, which may not run past its own closing braces;
#   a JS string joined to a value: `indox_" + i + ".`;
#   a JS template slot `${…}.`.
# The table may be quoted, and `ONLY` may follow DELETE FROM / TRUNCATE. The same day's self-test found
# an older blind spot as well: `truncate\s+(table\s+)?\s+` needs two runs of whitespace in a row, so NO
# TRUNCATE had ever matched.
_SCHEMA = (r'(?:(?:\\?"[^"\\]+\\?"|\w+|\{\{(?:(?!\}\}).)*\}\}|\$\{[^}]*\}'
           r'|\w*["\'`]\s*\+\s*[^;+]{1,80}?\s*\+\s*["\'`]\w*)\s*\.\s*)?')
DESTRUCTIVE = re.compile(
    r"\b(delete\s+from(?:\s+only)?|truncate(?:\s+table)?(?:\s+only)?)\s+" + _SCHEMA
    + r'\\?"?(' + "|".join(CLIENT_TABLES) + r')\\?"?\b',
    re.I | re.S)

# A comment that mentions a DELETE is not a DELETE: '//' and '/* */' (JS), and '--' (SQL) when it
# starts a line or follows whitespace, so a URL's 'https://' and a JS 'i--' are left alone.
_COMMENTS = re.compile(r"/\*.*?\*/|(?:^|(?<=\s))(?://|--)[^\n]*", re.S | re.M)


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
            blob = _COMMENTS.sub(" ", " ".join(str(v) for v in p.values() if isinstance(v, str)))
            m = DESTRUCTIVE.search(blob)
            if m:
                destructive.setdefault(wid, []).append((n.get("name", "?"), m.group(0)))
    return calls, destructive, open_hooks


# A reached DELETE that a pinned lane may be excused for: its schema is the test instance by name,
# or it is built per request (an n8n expression, a JS template slot, or a string joined to a value,
# which is how every per-instance client DELETE names `indox_` + __instance). A DELETE on a STATIC
# client schema (`indox_main.`, `public.`) is reported whoever reaches it: a pin cannot redirect it.
_TEST_OR_PER_INSTANCE = re.compile(r"""\bindox_test\b|\{\{|\$\{|["'`]\s*\+""", re.I)
_INST_ANY = re.compile(r"""__instance['"]?\s*(?::|=(?!=))\s*\S""")
_INST_LIT = re.compile(r"""__instance['"]?\s*(?::|=(?!=))\s*(['"])([^'"]*)\1""")
# Message text, not an assignment: `'… __instance=' + JSON.stringify(x)` (indoxV2BSTest01's own error).
_INST_MSG = re.compile(r"""__instance=(['"])\s*\+""")


def pins_test(wf):
    """True when every value this workflow gives `__instance` is the literal 'test', and it gives at
    least one. An expression, a variable or any other literal makes it False."""
    vals = []

    def walk(x):
        if isinstance(x, dict):
            if x.get("name") == "__instance" and "value" in x:   # a Set node assignment
                vals.append(x["value"])
            for k, v in x.items():
                if k == "__instance":                             # an input mapping
                    vals.append(v)
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, str):                                  # code: `__instance: 'test'`
            s = _COMMENTS.sub(" ", x)
            for m in _INST_ANY.finditer(s):
                if _INST_MSG.match(s, m.start()):
                    continue
                lit = _INST_LIT.match(s, m.start())
                vals.append(lit.group(2) if lit else None)

    for n in wf.get("nodes") or []:
        walk(n.get("parameters") or {})
    return bool(vals) and all(v == "test" for v in vals)


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
        exempt = (wid, path) in EXEMPT
        pinned = exempt and pins_test(wfs.get(wid) or {})
        for target in [wid] + sorted(reach(wid, calls)):
            if exempt and target == wid:
                continue   # the lane's own cleanup, which its reason speaks for
            for nname, stmt in destructive.get(target, []):
                if pinned and _TEST_OR_PER_INSTANCE.search(stmt):
                    continue   # a lane pinned to 'test' reaches only test rows through this one
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
    n_del = sum(len(v) for v in analyse(wfs)[1].values())
    print("[open-destructive-webhook-lint] %d blueprint(s), %d unauthenticated webhook(s), "
          "%d client-table DELETE/TRUNCATE node(s)" % (len(wfs), n_open, n_del))
    for u in unreadable:
        print("  ! cannot read %s: %s" % (u, wfs[u]["_unreadable"][:120]))
    findings, known, stale = decided(findings)
    for path, wid, node, target, nname, _stmt, hop in known:
        print("  decided: /webhook/%s (%s) reaches %s / %s %s — %s"
              % (path, wid, target, nname, hop, KNOWN_REACH[(wid, path, target, nname)]))
    if stale and not unreadable:
        print("[open-destructive-webhook-lint] FAIL - %d KNOWN_REACH entr%s match no reach any more — the reach "
              "was closed (or moved): delete the line, never let it excuse a later one:"
              % (len(stale), "y" if len(stale) == 1 else "ies"))
        for wid, path, target, nname in stale:
            print("  (%s, /webhook/%s) → %s / %s" % (wid, path, target, nname))
        return 1

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
        print("  the branch before rating one. The one ever proven routable, indox-manage + RESET into")
        print("  IndoxResetFull01, closed on 2026-08-31 (0f8f3cfa). For indoxApi01's PG Delete, which")
        print("  runs on INLINE_ACTION='DELETE', see this gate's KNOWN_REACH and DGO-1759.")
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
    f, _ = run({"indoxV2GDocTest01": wf([hook("gdoc-e2e-lane", "NONE"), DEL])})
    cases.append(("an EXEMPT suite runner's OWN cleanup is allowed", len(f), 0))
    f, _ = run({"indoxV2GDocTest01": wf([hook("gdoc-e2e-lane", "NONE"), call("B")]), "B": wf([DEL])})
    cases.append(("an EXEMPT lane with NO __instance pin reaching another workflow's DELETE is reported",
                  len(f), 1))

    def code(js):
        return {"type": "n8n-nodes-base.code", "name": "Seed", "parameters": {"jsCode": js}}

    lane = ("indoxV2GDocTest01", "gdoc-e2e-lane")
    PER_INST = {"type": "n8n-nodes-base.code", "name": "PG Delete",
                "parameters": {"jsCode": 'return "delete from indox_" + i + ".incoming_documents where 1=1";'}}
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"), code("return [{json:{__instance:'test'}}];"), call("B")]),
                "B": wf([PER_INST])})
    cases.append(("a lane pinned to 'test' may reach a PER-INSTANCE DELETE (it deletes test rows)", len(f), 0))
    # KNOWN_REACH speaks for exactly its key (DGO-1759): a decided webhook is set aside; a NEW webhook, the same
    # PATH in another workflow (the second reader's case), another node, or the node's statement changed is still a
    # finding; an entry that matches nothing is reported as stale
    PGD = {"type": "n8n-nodes-base.code", "name": "PG Delete",
           "parameters": {"jsCode": 'return "delete from indox_" + i + ".incoming_documents where id = $1";'}}
    f, _ = run({"SyncApi0000000001": wf([hook("indox-manage", "NONE"), call("indoxApi01")]), "indoxApi01": wf([PGD])})
    left, known, stale = decided(f)
    cases.append(("a KNOWN_REACH entry is set aside, said, not hidden", (len(left), len(known)), (0, 1)))
    cases.append(("…and the four entries it did not meet are named stale", len(stale), len(KNOWN_REACH) - 1))
    f, _ = run({"X": wf([hook("brand-new-hook", "NONE"), call("indoxApi01")]), "indoxApi01": wf([PGD])})
    cases.append(("a NEW webhook reaching the same PG Delete is still a finding", len(decided(f)[0]), 1))
    f, _ = run({"newApp01": wf([hook("query", "NONE"), call("indoxApi01")]), "indoxApi01": wf([PGD])})
    cases.append(("a decided PATH in another workflow is still a finding", len(decided(f)[0]), 1))
    f, _ = run({"SyncApi0000000001": wf([hook("indox-manage", "NONE"), call("Other")]), "Other": wf([PGD])})
    cases.append(("a decided webhook reaching ANOTHER workflow's DELETE is still a finding", len(decided(f)[0]), 1))
    TRUNC = {"type": "n8n-nodes-base.postgres", "name": "PG Delete",
             "parameters": {"query": "truncate public.incoming_documents"}}
    f, _ = run({"SyncApi0000000001": wf([hook("indox-manage", "NONE"), call("indoxApi01")]), "indoxApi01": wf([TRUNC])})
    cases.append(("the decided node holding ANOTHER statement is still a finding", len(decided(f)[0]), 1))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"), code("return [{json:{__instance:'test'}}];"), call("B")]),
                "B": wf([DEL])})
    cases.append(("a lane pinned to 'test' reaching a STATIC public. DELETE is still reported", len(f), 1))
    MAIN = {"type": "n8n-nodes-base.postgres", "name": "M",
            "parameters": {"query": "delete from indox_main.incoming_documents where 1=1"}}
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"), code("return [{json:{__instance:'test'}}];"), call("B")]),
                "B": wf([MAIN])})
    cases.append(("a lane pinned to 'test' reaching a STATIC indox_main. DELETE is still reported", len(f), 1))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"),
                             code("return [{json:{__instance:'test'}}, {json:{__instance:'main'}}];"),
                             call("B")]), "B": wf([PER_INST])})
    cases.append(("a lane that ALSO sends __instance 'main' has its reach reported", len(f), 1))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"), code("return [{json:{__instance: $json.inst}}];"),
                             call("B")]), "B": wf([PER_INST])})
    cases.append(("a lane whose __instance is an expression has its reach reported", len(f), 1))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"),
                             {"type": "n8n-nodes-base.set", "name": "S", "parameters": {"assignments": {
                                 "assignments": [{"name": "__instance", "value": "test"}]}}},
                             call("B")]), "B": wf([PER_INST])})
    cases.append(("a Set-node pin to 'test' counts as a pin", len(f), 0))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"),
                             code("if (!ok) throw new Error('bad __instance=' + JSON.stringify(u));\n"
                                  "return [{json:{__instance:'test'}}];"), call("B")]), "B": wf([PER_INST])})
    cases.append(("an error MESSAGE naming '__instance=' is not a value (BSTest01's shape)", len(f), 0))
    f, _ = run({lane[0]: wf([hook(lane[1], "NONE"),
                             code("return [{json:{__instance:('__instance' in req)?req.__instance:'test'}}];"),
                             call("B")]), "B": wf([PER_INST])})
    cases.append(("a lane that takes __instance from the REQUEST is not pinned (syncItemApiTest01's shape)",
                  len(f), 1))
    f, _ = run({"Other": wf([hook("gdoc-e2e-lane", "NONE"), DEL])})
    cases.append(("another workflow opening an exempt lane's PATH does not inherit it", len(f), 1))
    # a cycle must not hang the walk
    f, _ = run({"A": wf([hook("p", "NONE"), call("B")]), "B": wf([call("A"), DEL])})
    cases.append(("a call CYCLE terminates and still reports", len(f), 1))
    # IndoxResetFull01's shape since 2026-08-31: the schema is an n8n expression per instance.
    TPL = {"type": "n8n-nodes-base.postgres", "name": "Clear Table",
           "parameters": {"query": '=delete from {{ (() => { const i = String($json.__instance || "");'
                                   ' if (!i) { throw new Error("x"); } return "indox_" + i; })() }}'
                                   '.incoming_documents where "ID" <> \'0\''}}
    f, _ = run({"A": wf([hook("p", "NONE"), call("B")]), "B": wf([TPL])})
    cases.append(("a DELETE whose schema is an n8n expression is SEEN", len(f), 1))
    NAMED = {"type": "n8n-nodes-base.postgres", "name": "N",
             "parameters": {"query": 'truncate table "indox_main".incoming_documents'}}
    f, _ = run({"A": wf([hook("p", "NONE"), NAMED])})
    cases.append(("a TRUNCATE on a quoted instance schema is SEEN", len(f), 1))
    TRUNC = {"type": "n8n-nodes-base.postgres", "name": "T",
             "parameters": {"query": "TRUNCATE TABLE public.incoming_documents"}}
    f, _ = run({"A": wf([hook("p", "NONE"), TRUNC])})
    cases.append(("TRUNCATE TABLE with ONE space after TABLE is SEEN (it never matched before)", len(f), 1))
    BARE = {"type": "n8n-nodes-base.postgres", "name": "T2",
            "parameters": {"query": "truncate incoming_documents"}}
    f, _ = run({"A": wf([hook("p", "NONE"), BARE])})
    cases.append(("a bare TRUNCATE with no TABLE and no schema is SEEN", len(f), 1))
    TPL_OTHER = {"type": "n8n-nodes-base.postgres", "name": "O",
                 "parameters": {"query": "=delete from {{ $json.s }}.sync_ledger where a=1"}}
    f, _ = run({"A": wf([hook("p", "NONE"), TPL_OTHER])})
    cases.append(("a templated schema on a non-client table is still not this gate's business", len(f), 0))
    # The second reader's counter-examples (2026-11-10): the template must not run past its `}}`.
    for q in ("=delete from {{ $json.s }}.sync_ledger l using {{ $json.s }}.incoming_documents d where 1=1",
              "=delete from {{s}}.sync_ledger where a=1; select * from {{s}}.incoming_documents"):
        f, _ = run({"A": wf([hook("p", "NONE"), {"type": "n8n-nodes-base.postgres", "name": "O2",
                                                  "parameters": {"query": q}}])})
        cases.append(("a DELETE on another table, with the client table named later, is not caught: "
                      + q[:40], len(f), 0))

    def pg(q):
        return {"type": "n8n-nodes-base.code", "name": "Q", "parameters": {"jsCode": q}}

    seen = [
        ("indoxApi01 'PG Delete': a schema joined in JS",
         'return "delete from indox_" + i + ".incoming_documents where \\"ID\\" = $1";'),
        ("a JS template slot schema", "const q = `delete from ${schema}.incoming_documents where id=$1`;"),
        ("a quoted table name", 'delete from indox_test."incoming_documents" where 1=1'),
        ("whitespace around the dot", "delete from indox_test . incoming_documents where 1=1"),
        ("DELETE FROM ONLY", "DELETE FROM ONLY public.incoming_documents"),
    ]
    for label, q in seen:
        f, _ = run({"A": wf([hook("p", "NONE"), pg(q)])})
        cases.append((label + " is SEEN", len(f), 1))
    unseen = [
        ("a JS line comment that mentions a delete", "// delete from incoming_documents\nreturn 1;"),
        ("a JS block comment that mentions a delete", "/* truncate incoming_documents */ return 1;"),
        ("an SQL comment that mentions a delete", "select 1 -- delete from incoming_documents"),
    ]
    for label, q in unseen:
        f, _ = run({"A": wf([hook("p", "NONE"), pg(q)])})
        cases.append((label + " is NOT a delete", len(f), 0))

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
