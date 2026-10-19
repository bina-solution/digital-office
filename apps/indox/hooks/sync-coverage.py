#!/usr/bin/env python3
"""sync node-coverage gate (ai/context/archive/indox-pre-2026-09/sync-v3-plan.md §5d).

100% NODE coverage, enforced mechanically: for each sync workflow, every node in the
repo blueprint must appear in the executed runData of at least one execution in the window.
A node nobody executes = a branch nobody tests -> exit 1. Adding a node without a test
lane trips this gate in CI.

Universe: the 9 sync WFs (the Sync Item API, Main, the two discoveries, Run, the three
deliveries, the manage door) fully + the 4 DELIVER nodes injected into the supabase backend
+ the 3 test suites themselves (dead-lane detection), minus trigger/respond/sticky nodes
(mode-dependent: manual vs webhook runs can't both happen in one battery).

Usage: python3 apps/indox/hooks/sync-coverage.py [--profile sync-v3|state-machine]
                                                [--since-minutes N] (default 240)
"""
import json, os, re, subprocess, sys

# Blueprints are code (.workflow.ts) since 52b32aa4. scripts/refactor/n8n_blueprint is the ONE
# reader; this gate used to json.load() the .json files that commit deleted, so it did not
# report 0% coverage - it raised FileNotFoundError and never ran at all.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))))), "scripts", "refactor"))
from n8n_blueprint import load as load_blueprint   # noqa: E402

if hasattr(sys.stdout, "reconfigure"):  # windows consoles default to cp125x
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
WF_DIR = os.path.join(ROOT, "apps", "indox", "blueprint", "n8n")

#: PROFILES - one gate, two workflow sets. sync-v3 has had node coverage since the plan (5d);
#: the STATE MACHINE has never had any, so "the suites are green" and "every branch of the
#: driver/decide/actions ran" were unrelated statements - the same defect class the sync side
#: was built to prevent: a node nobody executes is a branch nobody tests.
#:
#: Adding a profile is adding a dict entry. Deliberately NOT a second copy of this file; six
#: private parsers is how the .json era drifted out from under its readers.
PROFILES = {
    "sync-v3": {
        "core":   ["syncLedgerApi01", "syncV3Main0001", "syncDiscoverDrive01", "syncDiscoverGmail01",
                   "syncRun01", "syncDeliverDrive01", "syncDeliverGmail01", "syncDeliverLink01",
                   "SyncApi0000000001"],
        "suites": ["syncItemApiTest01", "syncSourcesTest01", "syncFullTest01"],
        "backend": "indoxApi01",
        "backend_nodes": {"Build Deliver", "PG Deliver Insert",
                          "Deliver Fetch Req", "PG Deliver Fetch"},
    },
    "state-machine": {
        # The dispatch spine: driver -> decide -> router -> the per-type action lanes, plus the
        # drain that feeds it. A node here that never runs is a state transition nobody tested.
        "core":   ["indoxV2Driver01", "indoxV2Decide01", "indoxV2ActionRouter01",
                   "indoxV2ActionsGlobal01", "indoxV2ActionsBS01", "indoxV2ActionsInv01",
                   "indoxV2ActionsShip01", "indoxV2BaseDrain01"],
        "suites": ["indoxV2DocBaseTest01", "indoxV2BSTest01",
                   "indoxV2GDocTest01", "indoxV2PipelineTest01"],
        # No injected-node carve-out: the state machine owns its whole surface.
        "backend": None,
        "backend_nodes": set(),
    },
}

PROFILE = "sync-v3"
CORE = PROFILES[PROFILE]["core"]
SUITES = PROFILES[PROFILE]["suites"]
#: Was indoxApiSupabase01, now
#:   name: 'indox api (RETIRED 2026-08-12 - id renamed to indoxApi01)'  active: false
#: All four BACKEND_NODES live in indoxApi01 (verified 2026-08-21); scoring coverage against
#: the retired copy would measure nodes no execution can ever touch.
BACKEND = PROFILES[PROFILE]["backend"]  # sv3: only the injected DELIVER nodes are in scope
BACKEND_NODES = PROFILES[PROFILE]["backend_nodes"]

EXCLUDE_TYPES = {"n8n-nodes-base.stickyNote", "n8n-nodes-base.manualTrigger",
                 "n8n-nodes-base.scheduleTrigger", "n8n-nodes-base.webhook",
                 "n8n-nodes-base.respondToWebhook"}


def env(k, d=""):
    try:
        for ln in open(os.path.join(ROOT, ".env"), encoding="utf-8", errors="replace"):
            if ln.startswith(k + "="):
                return ln.strip().split("=", 1)[1]
    except OSError:
        pass
    return d


def psql(sql):
    dn = env("DEPLOYMENT_NAME", "bina-deployment")
    cmd = ["docker", "exec", "n8n-postgres-" + dn, "sh", "-c",
           'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tA -F "\t" -c ' + json.dumps(sql)]
    out = subprocess.run(cmd, capture_output=True, timeout=120).stdout
    return (out or b"").decode("utf-8", errors="replace")


def _blueprint(wid):
    """Load one blueprint by id from whichever tree owns it (apps/ or platform-base/)."""
    for cand in (os.path.join(WF_DIR, wid + ".workflow.ts"),
                 os.path.join(ROOT, "apps", "n8n", "workflows", wid + ".workflow.ts")):
        if os.path.exists(cand):
            return load_blueprint(cand)
    sys.exit("sync-coverage: no blueprint for %r in apps/indox/blueprint/n8n or "
             "apps/n8n/blueprint/n8n" % wid)


def universe():
    uni = {}  # wfid -> set(node names)
    for wid in CORE + SUITES:
        w = _blueprint(wid)
        uni[wid] = {n["name"] for n in w["nodes"]
                    if n.get("type") not in EXCLUDE_TYPES and not n.get("disabled")}
    if not BACKEND:
        return uni
    w = _blueprint(BACKEND)
    uni[BACKEND] = {n["name"] for n in w["nodes"] if n["name"] in BACKEND_NODES}
    return uni


def executed_nodes(since_minutes):
    # a profile with no injected-node backend contributes no id (state-machine)
    ids = "','".join(CORE + SUITES + ([BACKEND] if BACKEND else []))
    rows = psql(
        "select e.\"workflowId\", d.data from execution_entity e "
        "join execution_data d on d.\"executionId\"=e.id "
        "where e.\"workflowId\" in ('" + ids + "') "
        "and e.\"startedAt\" > now() - interval '" + str(int(since_minutes)) + " minutes'")
    hit = {}
    for ln in rows.splitlines():
        if "\t" not in ln:
            continue
        wid, data = ln.split("\t", 1)
        try:
            arr = json.loads(data)
            root = arr[0]
            rd = arr[int(root["resultData"])] if isinstance(root.get("resultData"), str) else root.get("resultData", {})
            run = arr[int(rd["runData"])] if isinstance(rd.get("runData"), str) else rd.get("runData", {})
            for name in run.keys():
                hit.setdefault(wid, set()).add(name)
        except (ValueError, KeyError, IndexError, TypeError):
            continue
    return hit


def main():
    since = 240
    global PROFILE, CORE, SUITES, BACKEND, BACKEND_NODES
    if "--profile" in sys.argv:
        PROFILE = sys.argv[sys.argv.index("--profile") + 1]
        if PROFILE not in PROFILES:
            sys.exit("unknown --profile %r; choose one of %s" % (PROFILE, sorted(PROFILES)))
        cfg = PROFILES[PROFILE]
        CORE, SUITES = cfg["core"], cfg["suites"]
        BACKEND, BACKEND_NODES = cfg["backend"], cfg["backend_nodes"]
    if "--since-minutes" in sys.argv:
        since = int(sys.argv[sys.argv.index("--since-minutes") + 1])
    uni = universe()
    hit = executed_nodes(since)
    total = covered = 0
    misses = []
    for wid, want in sorted(uni.items()):
        got = hit.get(wid, set())
        miss = sorted(want - got)
        total += len(want)
        covered += len(want) - len(miss)
        tag = "OK " if not miss else "MISS"
        print(("[%s-coverage]" % PROFILE) + " %s %-22s %d/%d" % (tag, wid, len(want) - len(miss), len(want)))
        for m in miss:
            misses.append(wid + " :: " + m)
            print("    - never executed: " + m)
    pct = 100.0 * covered / total if total else 0.0
    print(("[%s-coverage]" % PROFILE) + " TOTAL %d/%d nodes (%.1f%%) in last %dm" % (covered, total, pct, since))
    if misses:
        print(("[%s-coverage]" % PROFILE) + " FAIL — %d uncovered node(s)" % len(misses))
        sys.exit(1)
    print(("[%s-coverage]" % PROFILE) + " PASS — 100% node coverage")


if __name__ == "__main__":
    main()
