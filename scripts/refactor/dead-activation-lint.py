#!/usr/bin/env python3
"""dead-activation-lint — gate G44: an active workflow must own a node n8n can actually activate.

    python3 scripts/refactor/dead-activation-lint.py [--self-test]

WHY THIS EXISTS. Live QA on 2026-08-05/06 found `indoxV2BSTest01` ("indox-v2 BS E2E Test") and
`indoxV2DocBaseTest01` ("indox-v2 DOC BASE E2E Test") — both test/E2E workflows whose only start
node is a `manualTrigger` — captured `active: true` in their blueprint. n8n activates on every boot
and on every workflow-list refresh, and a `manualTrigger`-only workflow always fails that with
"Workflow ... has no node to start the workflow - at least one trigger, poller or webhook node is
required" — then RETRIES FOREVER, doubling its backoff each time (`docker logs n8n-<deployment>`
showed the same handful of workflow names retrying every few seconds, forever, for as long as the
container had been up). Concretely this was one of a small family of live offenders that day
(`whatsappSendDoc01` in `apps/chat` was a third instance of the exact same bug, outside this repo's
`apps/indox/` ownership boundary — reported, not fixed here). None of this throws a red execution or
appears anywhere in the n8n UI's execution list: it is pure log noise that (a) burns CPU forever on
a workflow that will never activate no matter how many times it retries, and (b) buries every OTHER
line in `docker logs n8n-<deployment>` under it, making a real incident harder to spot by eye.

`manualTrigger` looks like a trigger (it is literally in n8n's own "trigger" node category and every
E2E suite in this repo starts one via the REST `/rest/workflows/:id/run` API — see
`apps/indox/hooks/test.py::run_suite`), which is exactly why this is easy to ship by accident: the
workflow LOOKS complete and runs perfectly when driven manually or via that REST endpoint (manual/API
runs never consult the `active` flag), so nothing about local testing reveals that `active: true` is
inert-but-harmful for it. The flag only matters for n8n's own activation cycle, which needs a node
that can independently start an execution — a webhook, a schedule, a poller, an error handler, or a
sub-workflow entry point — none of which `manualTrigger` is.

WHAT COUNTS AS A REAL ACTIVATION TRIGGER: any node whose type is exactly `n8n-nodes-base.webhook`,
or whose type ends in `Trigger` and is not `n8n-nodes-base.manualTrigger` (covers
`scheduleTrigger`, `errorTrigger`, `executeWorkflowTrigger`, `evaluationTrigger`,
`@n8n/n8n-nodes-langchain.mcpTrigger`, and any future trigger-suffixed node type without needing a
name-by-name allowlist). `respondToWebhook` does NOT count — it replies inside an existing webhook
execution, it cannot start one. A workflow with **any** such node is left alone regardless of name;
this gate does not require or forbid `active: true` on its own — it only catches the specific
combination that cannot ever work: `active: true` with none.

SCOPE: every blueprint under `apps/*/blueprint/n8n/*.workflow.ts` and `apps/n8n/blueprint/n8n/*.workflow.ts`
— the same roots G19/G38/G39 scan. A workflow that is active in the live n8n database but was never
captured into a blueprint file is invisible to this gate by construction (same limitation G38's
docstring documents for `indoxDocUploader01`) — this is a static gate over the tree, not a live-DB
check. (Measured 2026-08-06: `sG9bU0ER2yVitKXR` "zz-scratch-gateway-probe (delete me)" was active in
the live DB with no blueprint file at all, and this gate could not have seen it.)

──────────────────────────────────────────────────────────────────────────────
CHECK 2 (added 2026-08-06): an ACTIVE TEST WORKFLOW, whatever its trigger shape.

Check 1 above asks "is there a node that can activate this?". That question has a blind spot the
2026-08-06 sweep walked straight into: of the eight active test workflows on this deployment, SEVEN
carry an `n8n-nodes-base.webhook` node alongside their `manualTrigger`, so check 1 says "fine, it has
a webhook" and never looks at what the workflow IS. Only `whatsappSendDoc01` — manualTrigger-only —
was visible. A gate that catches one of eight offenders reads as green and is not.

An E2E/test workflow left `active: true` is not free even when it CAN activate: its webhook is
registered on the production instance, so a stray or replayed POST runs a suite that seeds fixtures
and writes `incoming_documents` against live data. `indoxV2TestFixtures01` ("INDOX Seed Fixtures")
was active on the production instance for exactly this reason.

So check 2 keys off the tag taxonomy G47 already enforces rather than guessing from names: a
blueprint tagged `lifecycle:test` must not be `active: true` unless it is on ACTIVE_TEST_ALLOWLIST
below WITH a reason. The allowlist is the point — it turns "someone will re-activate these next
month" into a decision that has to be written down.

Deactivating is safe for a test workflow driven by `POST /rest/workflows/:id/run` (how
`apps/indox/hooks/test.py::run_suite` starts every suite — manual/API runs never consult `active`).
It is NOT safe for one driven through its PRODUCTION webhook, which only exists while the workflow
is active; those are allowlisted here until they are converted. See the allowlist reasons.
"""
from __future__ import annotations

import glob
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
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)
DEAD_TRIGGER = "n8n-nodes-base.manualTrigger"
WEBHOOK_TYPE = "n8n-nodes-base.webhook"
TEST_TAG = "lifecycle:test"

# An `active: true` workflow tagged `lifecycle:test` is a finding UNLESS it is here.
# Every entry needs a reason someone can act on. Removing an entry is how this gate starts
# enforcing that workflow — so shrinking this dict is the goal, not growing it.
ACTIVE_TEST_ALLOWLIST: dict[str, str] = {
    # --- legitimately active forever -----------------------------------------------------
    "ciHelloWebhook01":
        "IS the probe: scripts/ci-verify.sh asserts that an ACTIVE workflow's webhook actually "
        "registers and answers. Deactivating it deletes the thing under test.",

    # --- MIS-TAGGED: production endpoints wearing a test tag ------------------------------
    # These three are not tests at all — they are the live MCP servers documented in
    # ai/context/n8n-cli.md (paths gmail-enhanced / gdrive-agent / gsheet-agent). The fix is to
    # RETAG them (role:api), not to deactivate them. Listed here so the mis-tag is visible
    # rather than silently excluded; delete these entries once the tags are corrected.
    "gmailMcpAgent01":  "MIS-TAGGED lifecycle:test — production MCP server (n8n-cli.md). Retag role:api.",
    "gDriveMcpAgent01": "MIS-TAGGED lifecycle:test — production MCP server (n8n-cli.md). Retag role:api.",
    "gSheetMcpAgent01": "MIS-TAGGED lifecycle:test — production MCP server (n8n-cli.md). Retag role:api.",

    # --- genuinely tests, but driven through their PRODUCTION webhook --------------------
    # Verified 2026-08-06: apps/indox/hooks/test.py:431 posts to /webhook/<lane-path> per lane,
    # and _run_one_lane() in apps/indox/app/incoming_documents/api/__init__.py (the product's own
    # test-run API) does the same. A production webhook exists ONLY while the workflow is active,
    # so deactivating these 404s both call sites and breaks the E2E harness (Lane E depends on it).
    # Remove each entry as its lane driver is converted to POST /rest/workflows/:id/run.
    "indoxV2GDocTest01":
        "webhook 'gdoc-e2e-lane' driven by test.py:431 + _run_one_lane(). Convert to /rest/run first.",
    "indoxV2PipelineTest01":
        "webhook 'pipeline-e2e-lane' driven by test.py:431 + _run_one_lane(). Convert to /rest/run first.",
    "mailOrgTest00001":
        "webhook 'mail-organizer-e2e-lane' driven by test.py:431 + _run_one_lane(). Convert to /rest/run first.",

    # --- a SUB-WORKFLOW, not a suite: it is called, never started -------------------------
    # [2026-08-23] indoxV2TestFixtures01 is not driven by POST /rest/workflows/:id/run and has no
    # webhook. It is an executeWorkflow TARGET — every suite's 'Seed Test Fixtures' node calls it,
    # and so does IndoxResetFull01. n8n resolves an executeWorkflow target through its
    # published/active version, so deactivating it does not make a test safer; it removes the
    # seeding step from eight callers.
    #
    # Measured, not assumed. Of the five processor_wf targets in this estate, four declare
    # active:true and the fifth (SyncProcBS000001) declared false — and that fifth has ZERO
    # executions in the entire history of this deployment while its lane, sync_sources proc-bs,
    # fails with "W1 TIMED OUT waiting for ledger delivered>=1". Being inactive is not a neutral
    # flag on a callee; it is why nothing ever called it. That one is now active with the other
    # four, and this entry records why the same is true here.
    "indoxV2TestFixtures01":
        "SUB-WORKFLOW, not a suite: an executeWorkflow target called by every suite's 'Seed Test "
        "Fixtures' node and by IndoxResetFull01 — never started by POST /rest/run and it has no "
        "webhook. Deactivating removes seeding from eight callers. Evidence: SyncProcBS000001 was "
        "the one processor declared inactive and has never executed once.",
    "syncFullTest01":
        "webhook 'sync-full-e2e-lane' driven by test.py + _run_one_lane(). Convert to /rest/run first.",
    "syncItemApiTest01":
        "webhook 'sync-kernel-e2e-lane' driven by test.py + _run_one_lane(). Convert to /rest/run first.",
    "syncSourcesTest01":
        "webhook 'sync-sources-e2e-lane' driven by test.py + _run_one_lane(). Convert to /rest/run first.",
}


def can_activate(doc: dict) -> bool:
    """True if `doc` owns at least one node n8n's activation cycle can actually use."""
    for node in doc.get("nodes", []) or []:
        t = str(node.get("type") or "")
        if t == WEBHOOK_TYPE:
            return True
        if t.endswith("Trigger") and t != DEAD_TRIGGER:
            return True
    return False


def check(doc: dict) -> bool:
    """CHECK 1 — True if `doc` is a FAILING case: active with nothing that can activate it."""
    return bool(doc.get("active")) and not can_activate(doc)


def tags_of(doc: dict) -> set[str]:
    """Tag names, tolerating both shapes n8n emits (`"t"` and `{"name": "t"}`)."""
    out = set()
    for t in doc.get("tags") or []:
        name = t.get("name") if isinstance(t, dict) else t
        if name:
            out.add(str(name))
    return out


def check_active_test(doc: dict) -> bool:
    """CHECK 2 — True if `doc` is an active `lifecycle:test` workflow that is not allowlisted.

    Deliberately independent of trigger shape: the point is that seven of eight offenders
    carried a webhook node and so sailed past check 1."""
    if not bool(doc.get("active")) or TEST_TAG not in tags_of(doc):
        return False
    return str(doc.get("id") or "") not in ACTIVE_TEST_ALLOWLIST


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    ("active, manualTrigger only — must catch", True,
     {"active": True, "nodes": [{"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("active, no nodes at all — must catch", True,
     {"active": True, "nodes": []}),
    ("active, webhook present — must allow", False,
     {"active": True, "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"},
                                 {"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("active, scheduleTrigger present — must allow", False,
     {"active": True, "nodes": [{"name": "S", "type": "n8n-nodes-base.scheduleTrigger"}]}),
    ("active, executeWorkflowTrigger present — must allow (sub-workflow entry point)", False,
     {"active": True, "nodes": [{"name": "E", "type": "n8n-nodes-base.executeWorkflowTrigger"}]}),
    ("active, only respondToWebhook — must catch (that node cannot start an execution)", True,
     {"active": True, "nodes": [{"name": "R", "type": "n8n-nodes-base.respondToWebhook"},
                                 {"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("inactive, manualTrigger only — must allow (flag itself is honest)", False,
     {"active": False, "nodes": [{"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
]

# CHECK 2 — the blind spot that motivated it: a webhook makes check 1 say "fine".
SELF_TEST_ACTIVE_TEST = [
    ("active test WITH a webhook — must catch (this is the blind spot: check 1 allows it)", True,
     {"id": "someTest01", "active": True, "tags": ["indox-app", "lifecycle:test"],
      "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"},
                {"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("active test, manualTrigger only — must catch", True,
     {"id": "someTest02", "active": True, "tags": ["lifecycle:test"],
      "nodes": [{"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("active test, executeWorkflowTrigger (a sub-workflow fixture) — must catch", True,
     {"id": "someTest03", "active": True, "tags": ["lifecycle:test"],
      "nodes": [{"name": "E", "type": "n8n-nodes-base.executeWorkflowTrigger"}]}),
    ("tag as {'name': ...} dict — must catch (n8n emits both shapes)", True,
     {"id": "someTest04", "active": True, "tags": [{"name": "lifecycle:test"}],
      "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"}]}),
    ("INACTIVE test — must allow (the flag is honest)", False,
     {"id": "someTest05", "active": False, "tags": ["lifecycle:test"],
      "nodes": [{"name": "M", "type": "n8n-nodes-base.manualTrigger"}]}),
    ("active, NOT tagged lifecycle:test — must allow (not this check's business)", False,
     {"id": "realProd01", "active": True, "tags": ["indox-app", "role:api"],
      "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"}]}),
    ("active test ON the allowlist — must allow (decision is written down)", False,
     {"id": "ciHelloWebhook01", "active": True, "tags": ["lifecycle:test"],
      "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"}]}),
    ("no tags at all — must allow", False,
     {"id": "untagged01", "active": True,
      "nodes": [{"name": "W", "type": "n8n-nodes-base.webhook"}]}),
]


def self_test() -> int:
    bad = 0
    print("CHECK 1 — active with no node that can activate it:")
    for label, should, doc in SELF_TEST:
        got = check(doc)
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("\nCHECK 2 — active lifecycle:test workflow, any trigger shape:")
    for label, should, doc in SELF_TEST_ACTIVE_TEST:
        got = check_active_test(doc)
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    total = len(SELF_TEST) + len(SELF_TEST_ACTIVE_TEST)
    print(f"\nG44 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    if "--self-test" in sys.argv[1:]:
        return self_test()

    dead: list[tuple[str, str, str]] = []          # check 1: path, id, name
    active_tests: list[tuple[str, str, str]] = []   # check 2: path, id, name
    checked = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(str(path))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {path.relative_to(REPO)}: {e}")
                continue
            checked += 1
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            row = (rel, str(doc.get("id") or "?"), str(doc.get("name") or "?"))
            if check(doc):
                dead.append(row)
            if check_active_test(doc):
                active_tests.append(row)

    # A gate that read nothing has checked nothing. Where the blueprints cannot be compiled (no
    # node, no toolchain) every load above fails, and this used to end in PASS over zero of them.
    if not checked:
        print("G44 FAIL — read ZERO blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    if not dead and not active_tests:
        print(f"G44 PASS — across {checked} blueprint(s): every active workflow owns a node n8n's\n"
              f"activation cycle can use, and no `{TEST_TAG}` workflow is active outside the\n"
              f"{len(ACTIVE_TEST_ALLOWLIST)}-entry allowlist.")
        return 0

    if dead:
        print(f"G44 FAIL (check 1) — {len(dead)} workflow(s) are active:true with no webhook/schedule/\n"
              f"poller/trigger node — n8n will retry activating them forever, spamming the log and\n"
              f"burning CPU on a workflow that can never activate no matter how many retries:\n")
        for path, wid, name in dead:
            print(f"  {path}")
            print(f"      id={wid!r}  name={name!r}")
        print(
            "\n  Set \"active\": false — a manual/API-triggered workflow (this repo's E2E suites all\n"
            "  start via POST /rest/workflows/:id/run, see apps/indox/hooks/test.py::run_suite) runs\n"
            "  exactly the same whether active or not; only n8n's own activation cycle reads the flag."
        )

    if active_tests:
        if dead:
            print()
        print(f"G44 FAIL (check 2) — {len(active_tests)} workflow(s) tagged `{TEST_TAG}` are\n"
              f"active:true and not on ACTIVE_TEST_ALLOWLIST. An active test workflow has its webhook\n"
              f"registered on the PRODUCTION instance, so a stray or replayed POST runs a suite that\n"
              f"seeds fixtures and writes real tables:\n")
        for path, wid, name in active_tests:
            print(f"  {path}")
            print(f"      id={wid!r}  name={name!r}")
        print(
            "\n  Either set \"active\": false (safe when the suite is started by\n"
            "  POST /rest/workflows/:id/run — manual/API runs ignore the flag), or add it to\n"
            "  ACTIVE_TEST_ALLOWLIST in this file WITH a reason. Do NOT deactivate a suite whose\n"
            "  lanes are driven through its production webhook (see the allowlist) — that URL only\n"
            "  exists while the workflow is active, and deactivating 404s the caller.\n"
            "\n  Verifying live: `PATCH /rest/workflows/:id {\"active\": false}` returns HTTP 200 and\n"
            "  changes NOTHING on this n8n. Read workflow_entity.active back from Postgres."
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
