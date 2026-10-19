#!/usr/bin/env python3
"""G42 (re-pointed) -- who may WRITE public.incoming_documents.

WHY THIS REPLACES direct-db-write-lint.py RATHER THAN RESTORING IT
The retired G42 asserted "only indoxDataGateway01 may write Postgres". That premise was withdrawn
by the owner on 2026-08-07: indoxDataGateway01 was written by an agent lane, never committed to the
architecture, never executed (zero execution_entity rows all-time), and moved to
data/_attic_agent_drafts/. Restoring the gate verbatim would re-impose a rejected design and assert
"only <deleted workflow> may write" -- which is why it died the first time. GATES.md had already
sized the honest version: ~20 production workflows / ~35 nodes writing incoming_documents.

WHAT IT ENFORCES INSTEAD -- the owner's actual, current invariant (2026-08-14):
    "only the state machine should ever change the line -- no changes in driver, drainer, api,
     nothing. Only 1 upsert at each end of action execution."
So: a write to incoming_documents is legal only from a sanctioned writer. Everything else is a
direct write that bypasses the state machine, which is exactly the class of defect this session
removed (Terminalize Stalled authoring STATUS, errorHandler01 authoring MAX_ITERATIONS, the
NoAct/lock branches stamping ACTION_LOG).

IT READ NOTHING FROM ITS SECOND DAY. Written 2026-08-14 against `*.json`; the blueprints became
`.workflow.ts` on 08-16, and from then on it reported "no unsanctioned writer (0 sanctioned write
nodes)" — zero of either kind, because zero files. Read through the one reader on 2026-10-07 it
found twelve write nodes it had never been asked about: ten in the five `indoxV2Sealed*01` suites
(tests, written after it went blind — `is_test` knows them now) and two that stand:
`indoxApiSupabase01`, retired on 2026-08-12 when its id became `indoxApi01`, still ships in the
central blueprint with its `PG Delete` and `Terminalize Stalled` nodes. A run that reads no
blueprint is a failure now.

Run:  python scripts/refactor/incoming-documents-writer-lint.py [--list]
Exit: 0 clean, 1 violations found.
"""
import glob
import json
import os
import pathlib
import re
import sys

# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
TREES = [os.path.join(ROOT, "apps", "indox", "blueprint", "n8n"),
         os.path.join(ROOT, "apps", "n8n", "blueprint", "n8n")]

# Sanctioned writers. Each entry is a deliberate architectural decision, not an amnesty for
# whatever happens to exist -- adding to this list means adding a writer to the state machine.
ALLOW = {
    "indoxDocBatchUpsert01": "THE end-of-action upsert. Every action's single write goes here.",
    "indoxApi01":            "the API surface: explicit verbs (merge, delete, restart) on an id "
                             "the caller names. No inference, no sweeps.",
    "syncLedgerApi01":       "owns the sync_ledger / sync_attempt / sync_cursor family, not the "
                             "document state machine.",
    "errorHandler01":        "writes ERROR only (cleanup #9); must never author STATUS again.",
    "indoxV2ActionsGlobal01": "Record Base Doc Failure -- the FAILURE-path end-of-action write. "
                              "Cleanup #8 deliberately kept RETRY_COUNT+1, MAX_ITERATIONS at 5 and "
                              "ERROR here: it is the state machine recording its own verdict.",
    "IndoxResetFull01":      "operator's explicit full-reset verb (wipe + reseed). Not part of the "
                              "state machine, but only ever human-invoked.",
}

# Ingestion lanes: they create the row and set IN_PROGRESS at ingest, which is the one write that
# legitimately precedes the state machine.
ALLOW_PREFIX = ("SyncProc", "syncV3", "Sync")

WRITE_SQL = re.compile(
    r"\b(update|insert\s+into|delete\s+from)\b[^;]{0,400}?\bincoming_documents\b", re.I | re.S)


def is_test(name):
    # "sealed": the per-action sealed suites (indoxV2Sealed<Type>01, 2026-08-31) that
    # apps/indox/hooks/test.py runs — they seed, quiesce and clean up `sl?_`-prefixed rows in the
    # TEST instance's schema. They were written two weeks after this gate stopped reading, so
    # nothing had ever classified them.
    n = name.lower()
    return ("test" in n or "demo" in n or "fixture" in n or "sealed" in n
            or n.startswith("ztest") or n.startswith("zz"))


def scan():
    violations, allowed, read = [], [], 0
    for tree in TREES:
        for path in sorted(glob.glob(os.path.join(tree, "*.workflow.ts"))):
            wid = os.path.basename(path)[:-len(".workflow.ts")]
            try:
                wf = load_blueprint(path)
            except (OSError, ValueError, CompileError) as exc:
                print("  ! unreadable %s: %s" % (wid, exc))
                continue
            read += 1
            for node in wf.get("nodes", []):
                params = node.get("parameters") or {}
                blob = params.get("query") or ""
                if not blob and node.get("type", "").endswith(".httpRequest"):
                    blob = json.dumps(params, ensure_ascii=False)
                if not blob or "incoming_documents" not in blob:
                    continue
                # strip comments so prose about a past UPDATE is not a violation
                body = "\n".join(l for l in blob.split("\n")
                                 if not l.strip().startswith(("--", "/*", "*", "//")))
                body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
                if not WRITE_SQL.search(body):
                    continue
                rec = (wid, node.get("name", "?"))
                if wid in ALLOW or wid.startswith(ALLOW_PREFIX) or is_test(wid):
                    allowed.append(rec)
                else:
                    violations.append(rec)
    return violations, allowed, read


def main():
    violations, allowed, read = scan()
    show = "--list" in sys.argv
    if not read:
        print("G42 FAIL -- read ZERO blueprint workflows, so nothing was checked.\n"
              "  trees: " + ", ".join(os.path.relpath(t, ROOT) for t in TREES))
        return 1

    if show and allowed:
        print("SANCTIONED writers (%d nodes):" % len(allowed))
        for wid, nm in allowed:
            print("   %-26s %s" % (wid, nm))
        print()

    if not violations:
        print("G42 OK -- no unsanctioned writer of incoming_documents "
              "(%d sanctioned write nodes in %d blueprints)." % (len(allowed), read))
        return 0

    print("G42 FAIL -- %d node(s) write incoming_documents outside the state machine:"
          % len(violations))
    for wid, nm in violations:
        print("   %-26s :: %s" % (wid, nm))
    print("\nEvery write must be the single end-of-action upsert (indoxDocBatchUpsert01) or an\n"
          "explicit API verb. A direct write bypasses the state machine -- that is the defect\n"
          "class removed on 2026-08-14 (Terminalize Stalled, errorHandler01's STATUS, the\n"
          "NoAct/lock ACTION_LOG stamps). Route it through the upsert, or justify it in ALLOW.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
