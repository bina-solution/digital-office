#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fix_wiring.py — corrects a real bug found on the first single-document proof run.

IndoxInjectDemo01 is one STRICT LINEAR chain: Build X -> Send X -> Read Y -> Build Y -> ...
n8n does NOT execute nodes downstream of a node that emits ZERO items on a `main` connection —
it isn't a harmless pass-through, it's a hard stop for everything wired serially after it. The
original patch appended e2e-mail/e2e-drive-gdoc/e2e-drive-bs AFTER "Send gmail-link", at the tail
of the pre-existing chain (Build gmail-doc -> Send gmail-doc -> Read gmail-bs -> ... -> Send
gmail-link). loadtest.yml defines none of those five original sync keys, so "Build gmail-doc"
emits 0 items on its very first stage — confirmed live: execution 112437 finished "success" having
run only 13/36+ nodes, stopping dead right after "Build gmail-doc", never reaching "Send gmail-doc"
let alone the new nodes.

Fix: make the new chain a PARALLEL branch off "Seed Companies" (which always has output whenever
the blueprint has >=1 company, true for every blueprint including loadtest), not a continuation of
the pre-existing chain. "Seed Companies" now fans out to BOTH "Read gmail-doc" (unchanged, existing
demos untouched) AND "Read e2e-mail" (new). The tail rewire onto "Send gmail-link" is removed.

Usage: python3 fix_wiring.py [--check]
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WF = os.path.join(ROOT, "apps", "indox", "blueprint", "n8n", "IndoxInjectDemo01.json")


def main():
    check_only = "--check" in sys.argv
    with open(WF, encoding="utf-8") as f:
        d = json.load(f)
    conns = d["connections"]

    already_parallel = any(t.get("node") == "Read e2e-mail"
                           for branch in conns.get("Seed Companies", {}).get("main", [])
                           for t in branch)
    if already_parallel:
        print("[fix_wiring] already applied — no-op")
        return 0
    if check_only:
        print("[fix_wiring] NOT applied yet")
        return 1

    if "Read e2e-mail" not in {n["name"] for n in d["nodes"]}:
        sys.exit("Read e2e-mail node not found — run patch_inject_workflow.py first")

    # 1) Seed Companies must fan out to BOTH Read gmail-doc (unchanged) and Read e2e-mail (new)
    sc = conns.get("Seed Companies", {}).get("main", [[]])
    branch0 = sc[0] if sc else []
    if not any(t.get("node") == "Read e2e-mail" for t in branch0):
        branch0.append({"node": "Read e2e-mail", "type": "main", "index": 0})
    conns["Seed Companies"] = {"main": [branch0]}

    # 2) undo the old tail-rewire: "Send gmail-link" goes back to being the natural end of its
    #    own chain (no outgoing connection — matches the original, pre-patch file exactly)
    if "Send gmail-link" in conns:
        del conns["Send gmail-link"]

    with open(WF, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print("[fix_wiring] Seed Companies now fans out to Read gmail-doc + Read e2e-mail (parallel)")
    print("[fix_wiring] next: bbox n8n push (check no other push running), then re-test")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
