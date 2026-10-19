#!/usr/bin/env python3
"""n8n node coverage — which nodes of the sync + state-machine estate actually executed.

For every target workflow: total ACTIVE nodes (from the live workflow blob, disabled excluded)
vs the union of nodes that ran across an execution-id window (execution_data.runData keys,
via the harness's own deflatten). Reports per-workflow coverage and the exact unexecuted
nodes, so a gap is a named node — either a missing test lane or a dead node to remove.

Usage:
  python3 scripts/n8n-node-coverage.py --since-id 3735000 [--min 85] [--wf name ...]

Runs on the WSL side (needs docker exec into n8n-postgres). Exit 1 when any workflow in
scope is under --min percent.
"""
import argparse
import json
import os
import subprocess
import sys

PG = ["docker", "exec", "n8n-postgres-shlomo-laptop", "psql", "-U", "hacohen", "-d", "n8n",
      "-t", "-A"]

# The estate under the 85% bar: sync + state machine. Extractor/utility workflows are listed
# too but reported separately (informational) — their bar is owned by the extraction gates.
CORE = [
    # sync engine — the SYNC ITEM architecture (2026-09-02): one clock pass, discovery per source,
    # a run stage that takes rows, three delivery lanes, one ledger API. Unit/Deliver/mailDiscovery
    # are gone.
    "syncV3Main0001", "syncLedgerApi01", "syncDiscoverDrive01", "syncDiscoverGmail01", "syncRun01",
    "syncDeliverDrive01", "syncDeliverGmail01", "syncDeliverLink01",
    # state machine
    "indox01", "indoxV2Driver01", "indoxV2Decide01", "indoxV2ActionsGlobal01",
    "indoxV2ActionsInv01", "indoxV2ActionsShip01", "indoxV2ActionsBS01",
    "indoxV2ActionsOrd01", "indoxV2ActionsRcp01", "indoxV2BaseDrain01",
    "indoxV2ActionRouter01", "indoxApi01",
    # extraction + selection (the state machine's working arms)
    "BaseDocEx01", "SelectBase01", "SelectType01",
    "InvoiceDocEx01", "ShipmentDocEx01", "BsDocEx01",
    "indoxV2SearchWarehouse01", "indoxV2SearchFile01",
    "JQExV3Base000001", "JQExV3Invoice001", "JQExV3Ship000001",
    "JQExV3BS00000001",
    # shared plumbing
    "processLock01",
    # mail engine
    "mailLabelEngine01", "gmailApiImap01", "mailApi01",
    # drive engine
    "driveApi01",
]
#: ops / reset / dev tooling — reported, never gated (not the runtime solution).
#: Moved 2026-09-01, each per this file's own doctrine ("their bar is owned by the extraction
#: gates" — the header's words, finally honored):
#:   indoxV2Extract{BalanceSheet,InvoiceGemini}01 + indoxV2UploadApiTools01 — the deep-extraction
#:     engines. In a green battery the AI-cache short-circuits their cold paths by DESIGN; their
#:     real bar is the extraction corpus gates (527/527), not test-battery node touch.
#:   errorHandler01 — fires only on errors; counting its unfired branches AGAINST a green battery
#:     inverts the goal (a red battery would "cover" it better).
#:   indoxSettings01 — the UI config plane (company/setting/query webhooks the console drives);
#:     its consumers are the console flows, not the document pipeline.
#: SyncApi0000000001 moved here 2026-08-31: it is the RESET dispatcher (IndoxResetFull01's
#: chain), ops estate like the resets themselves — not a runtime sync path.
#: JQExV3Order00001 moved here 2026-08-31: ORDER is a PARKED class by the five-classes owner
#: ruling (decide+mark_completed only, no extraction) — the engine exists for the day the type
#: is activated in settings and is deliberately unreachable until then.
INFO = ["indoxV2ExtractBalanceSheet01", "indoxV2ExtractInvoiceGemini01",
        "indoxV2UploadApiTools01", "errorHandler01", "indoxSettings01",
        "IndoxResetFull01", "indoxV2TestFixtures01",
        "indoxHealth00001", "glitchtipReporter01", "priorityLocalApi01",
        "SyncApi0000000001", "JQExV3Order00001",
        "JQExV3RunBase001", "JQExV3RunInv0001", "JQExV3RunShip001", "JQExV3RunBS00001",
        "whatsappApi01", "mail01"]


def sql(q):
    return subprocess.run(PG + ["-c", q], capture_output=True).stdout.decode(
        "utf-8", errors="replace").strip()


def load_deflatten():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "t", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "..", "apps", "indox", "hooks", "test.py"))
    m = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(m)
    except SystemExit:
        pass
    return m.deflatten


def wf_nodes(wf):
    raw = sql("SELECT nodes::text FROM workflow_entity WHERE id='%s';" % wf)
    if not raw:
        return None
    nodes = json.loads(raw)
    out = []
    for n in nodes:
        # sticky notes are canvas prose; disabled nodes are deliberately parked.
        # manualTrigger never appears in runData for REST/webhook-driven batteries --
        # it is the canvas play button, structural, not a coverage target.
        if n.get("type") in ("n8n-nodes-base.stickyNote", "n8n-nodes-base.manualTrigger"):
            continue
        out.append((n.get("name"), bool(n.get("disabled"))))
    return out


def ran_nodes(wf, since_id, deflatten, until_id=None):
    # ONE psql round-trip per workflow, not one per execution: the per-exec form spawned
    # wsl+docker+psql thousands of times and ran for tens of minutes on a battery window
    # (measured 2026-08-31: 20+ min, unfinished). Rows are newline-joined JSON documents;
    # execution_data.data never contains raw newlines (JSON string escapes them), so
    # splitting on '\n' recovers each row.
    upper = (" AND ed.\"executionId\"<=%d" % until_id) if until_id else ""
    raw = sql("SELECT ed.data FROM execution_data ed JOIN execution_entity ee "
              "ON ee.id=ed.\"executionId\" WHERE ee.\"workflowId\"='%s' AND "
              "ed.\"executionId\">=%d%s ORDER BY ed.\"executionId\" DESC LIMIT 2000;"
              % (wf, since_id, upper))
    ran = set()
    n = 0
    for line in raw.split("\n"):
        line = line.strip()
        if not line:
            continue
        n += 1
        try:
            d = deflatten(json.loads(line))
            ran |= set(((d.get("resultData") or {}).get("runData") or {}).keys())
        except Exception:
            continue
    return ran, n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-id", type=int, required=True)
    ap.add_argument("--until-id", type=int, default=None,
                    help="upper execution-id fence (default: open)")
    ap.add_argument("--min", type=float, default=80.0)
    ap.add_argument("--wf", nargs="*", default=None)
    ap.add_argument("--out", default=None, help="also write the report to this file")
    a = ap.parse_args()
    deflatten = load_deflatten()

    lines = []
    rows = []
    fail = False
    tot_active = tot_hit = 0
    for scope, wfs in (("CORE", a.wf or CORE), ("INFO", [] if a.wf else INFO)):
        for wf in wfs:
            nodes = wf_nodes(wf)
            if nodes is None:
                lines.append("%-34s MISSING from n8n" % wf)
                continue
            active = [n for n, dis in nodes if not dis]
            disabled = [n for n, dis in nodes if dis]
            ran, nexec = ran_nodes(wf, a.since_id, deflatten, a.until_id)
            hit = [n for n in active if n in ran]
            miss = [n for n in active if n not in ran]
            pct = (100.0 * len(hit) / len(active)) if active else 100.0
            if scope == "CORE":
                tot_active += len(active)
                tot_hit += len(hit)
                if pct < a.min:
                    fail = True
            rows.append((scope, wf, pct, len(hit), len(active), nexec, len(disabled), miss))
    # table first, gaps after — the table is the answer, the gaps are the work list
    for scope, wf, pct, h, t, nexec, dis, _ in rows:
        bar = ("OK " if pct >= a.min else "LOW") if scope == "CORE" else "  -"
        lines.append("%s %-34s %5.1f%%  %3d/%-3d nodes  (%d execs%s)" % (
            bar, wf, pct, h, t, nexec, (", %d disabled" % dis) if dis else ""))
    if tot_active:
        lines.append("─" * 72)
        lines.append("CORE TOTAL %30s %5.1f%%  %d/%d nodes  (bar %.0f%%)" % (
            "", 100.0 * tot_hit / tot_active, tot_hit, tot_active, a.min))
    lines.append("")
    for scope, wf, pct, h, t, _, _, miss in rows:
        if miss and (scope == "CORE" or pct < a.min):
            lines.append("── %s — %d unexecuted node(s):" % (wf, len(miss)))
            for n in miss:
                lines.append("      %s" % n)
    report = "\n".join(lines)
    print(report)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(report + "\n")
    sys.exit(1 if fail else 0)


if __name__ == "__main__":
    main()
