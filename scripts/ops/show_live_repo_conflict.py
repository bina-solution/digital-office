#!/usr/bin/env python3
"""Show exactly what LIVE and REPO each changed in a conflicted workflow.

WHY
---
`bbox n8n status` says a workflow "changed LIVE since last sync", and verify_live_parity says the
bodies differ — but neither says WHAT differs, and without that a two-writer conflict cannot be
resolved except by picking a side and losing the other's work.

Four INDOX test workflows are in exactly that state (2026-08-23): committed repo fixes from
2026-08-21 on one side, human n8n-UI edits on the other, drifting in BOTH directions —
`indoxV2DecideTest01` is 8,135 characters longer in the repo, `syncV3SourcesTest01` is longer live.
Pushing discards the human's work; pulling by name discards the commits.

This prints a unified diff per differing node so whoever made the live edit can see their change
next to the repo's and decide, instead of being asked to trust one side.

usage: show_live_repo_conflict.py <workflowId> [workflowId...]
"""
import difflib
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "verify_live_parity", os.path.join(_HERE, "verify_live_parity.py"))
vlp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vlp)

CONTEXT = 2
MAX_LINES = 60


def main(argv):
    ids = argv[1:]
    if not ids:
        print("usage: show_live_repo_conflict.py <workflowId> [workflowId...]")
        return 2
    for wf in ids:
        path = os.path.join(vlp.N8N_DIR, wf + ".workflow.ts")
        if not os.path.exists(path):
            print("  %s: no .workflow.ts in the blueprint" % wf)
            continue
        live = vlp.live_bodies(wf) or {}
        repo = vlp.repo_bodies(path)
        differing = [(n, repo[n], live[n]) for n in repo
                     if n in live and repo[n].strip() != live[n].strip()]
        print("\n===== %s : %d differing node(s) =====" % (wf, len(differing)))
        for name, r, l in differing:
            print("  --- node: %s   (repo %d chars, live %d chars) ---" % (name, len(r), len(l)))
            d = list(difflib.unified_diff(
                l.split("\n"), r.split("\n"),
                fromfile="LIVE (a person edited this in the n8n UI)",
                tofile="REPO (committed)", lineterm="", n=CONTEXT))
            if not d:
                print("      (whitespace-only difference)")
            for line in d[:MAX_LINES]:
                print("    %s" % line[:160])
            if len(d) > MAX_LINES:
                print("    ... %d more diff lines" % (len(d) - MAX_LINES))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
