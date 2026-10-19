#!/usr/bin/env python3
"""node-credential-lint — gate G52: a node that cannot work without credentials must declare them.

    python3 scripts/refactor/node-credential-lint.py [--self-test]

WHY THIS EXISTS, and it is a confession. On 2026-08-06 this repo grew two new Redis nodes
(`RENEW CHECK EXISTS` / `RENEW PROCESS KEY` in `processLock01`, task #72) that shipped with **no
`credentials` block**, while all eleven of their siblings in the same workflow carried the same one.
They errored on every single invocation until the block was copied across by hand. The fix they were
part of — making the reconcile mutex's renewal actually renew — was therefore inert on arrival: the
node ran, the workflow continued (`onError: continueRegularOutput` on the caller), and nothing said
the renewal had never happened. A fix for a silent no-op, delivered as a silent no-op.

It is the same TWO-LIST DRIFT that G39 catches for `executeWorkflowTrigger` schemas, that `GATES.md`
catches for gate numbers, and that G46 catches for drive connection ids: one list says what the node
does and a second says what it needs, nothing joins them, and the second is the one a human forgets.
n8n's editor hides this — it fills the credential in from the dropdown, so a node built in the UI is
never wrong and a node written as JSON always can be. Every blueprint in this repo is written as
JSON.

WHAT THIS CHECKS. Every node whose TYPE cannot function without a credential (`REQUIRED_TYPES`
below — postgres, redis, gmail, googleDrive, ... : there is no such thing as an anonymous Postgres
node) must carry a non-empty `credentials` object.

WHAT IT DELIBERATELY DOES NOT CHECK, measured rather than assumed. The obvious wider rule — "a node
must match its same-type siblings in the same workflow" — was implemented and measured first: **14
findings, every one of them `httpRequest` or `webhook`**, and every one legitimate. An
`httpRequest` may call a public endpoint next to one that calls an authenticated API
(`indoxGmailLinkDownloader01` has 1 credentialed of 6, all correct), and a `webhook`'s credential is
optional header-auth (`indoxSettings01`, `indoxV2Driver01`). A gate firing on those trains people to
ignore it. The narrow rule catches the actual bug — Redis, Postgres — and nothing else, because for
those types "no credential" is not a configuration, it is a defect.

CLOSED, and worth recording because it vindicates the narrowing. Four workflows were reported as
having same-type siblings naming DIFFERENT credential ids, pending a human verdict. All four came
back BENIGN:

  * `IndoxResetFull01` — checked 2026-08-06 against the live `credentials_entity` table. Its two
    Postgres credentials are two different DATABASES, which is the whole point of the workflow:
    `Kill Main Executions` uses `tJ195ajNq1kQveRG` ("N8N DB") to cancel rows in n8n's own
    `execution_entity`, and `Clear Table` uses `yY8FYvp6Kz86pt2t` ("INDOX Supabase Postgres") to
    delete from `public.incoming_documents`. A gate asserting they should agree would have demanded
    a real defect.
  * `indoxV2ActionsGDoc01` / `indoxV2ActionsShip01` / `indoxV2Driver01` — a sibling lane's endpoint
    gate could not reproduce the divergence: grouped by host+path rather than by node type, the
    `httpBasicAuth` pairs agree. A host-level false positive.

Four for four. The broader "match your siblings" rule would have shipped red on four legitimate
configurations on its first run, on top of the 14 `httpRequest`/`webhook` sites already measured —
which is the precise failure mode this gate was narrowed to avoid.
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
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

#: Node types with no anonymous mode — the credential is not optional configuration, it is how the
#: node reaches the thing it exists to reach. `httpRequest` and `webhook` are deliberately ABSENT:
#: see the docstring for the measurement that kept them out.
REQUIRED_TYPES = frozenset({
    "n8n-nodes-base.postgres",
    "n8n-nodes-base.redis",
    "n8n-nodes-base.mySql",
    "n8n-nodes-base.mongoDb",
    "n8n-nodes-base.gmail",
    "n8n-nodes-base.gmailTool",
    "n8n-nodes-base.googleDrive",
    "n8n-nodes-base.googleDriveTool",
    "n8n-nodes-base.googleSheets",
    "n8n-nodes-base.googleSheetsTool",
    "n8n-nodes-base.awsS3",
    "n8n-nodes-base.ssh",
    "n8n-nodes-base.ftp",
    "n8n-nodes-base.imap",
    "n8n-nodes-base.slack",
    "n8n-nodes-base.telegram",
})


def missing_credentials(node: dict) -> bool:
    """True if `node` is a credential-requiring type carrying no usable credentials block."""
    if node.get("type") not in REQUIRED_TYPES:
        return False
    creds = node.get("credentials")
    if not isinstance(creds, dict) or not creds:
        return True
    # a present-but-hollow block is the same defect wearing a shirt
    return not any(isinstance(v, dict) and (v.get("id") or v.get("name")) for v in creds.values())


SELF_TEST = [
    ("the #72 bug verbatim — a redis node with no credentials key at all: must catch", True,
     {"name": "RENEW PROCESS KEY", "type": "n8n-nodes-base.redis",
      "parameters": {"operation": "incr"}}),
    ("the same node once the credential block was copied across: must allow", False,
     {"name": "RENEW PROCESS KEY", "type": "n8n-nodes-base.redis",
      "parameters": {"operation": "incr"},
      "credentials": {"redis": {"id": "BoJE1odVZ6MBcpax", "name": "Redis Local Account"}}}),
    ("an empty credentials object is not a credential: must catch", True,
     {"name": "PG", "type": "n8n-nodes-base.postgres", "credentials": {}}),
    ("a credentials block with neither id nor name is hollow: must catch", True,
     {"name": "PG", "type": "n8n-nodes-base.postgres", "credentials": {"postgres": {}}}),
    ("name-only (an env-managed credential resolved at import): must allow", False,
     {"name": "PG", "type": "n8n-nodes-base.postgres",
      "credentials": {"postgres": {"name": "INDOX Supabase Postgres"}}}),
    ("httpRequest is deliberately out of scope — 14 legitimate sites: must allow", False,
     {"name": "Document OCR", "type": "n8n-nodes-base.httpRequest", "parameters": {}}),
    ("webhook auth is optional by design: must allow", False,
     {"name": "Query Webhook", "type": "n8n-nodes-base.webhook", "parameters": {}}),
    ("a code node needs nothing: must allow", False,
     {"name": "Normalize", "type": "n8n-nodes-base.code", "parameters": {"jsCode": "return []"}}),
]


def self_test() -> int:
    bad = 0
    for label, should, node in SELF_TEST:
        got = missing_credentials(node)
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} "
              f"({'must catch' if should else 'must allow'}): {label}")
    print(f"\nG52 self-test: {len(SELF_TEST) - bad}/{len(SELF_TEST)} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings: list[tuple[str, str, str]] = []
    checked = read = 0
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                doc = load_blueprint(str(path))
            except (OSError, ValueError, CompileError) as e:
                print(f"  ! {path.relative_to(REPO)}: {e}")
                continue
            read += 1
            rel = str(path.relative_to(REPO)).replace("\\", "/")
            for node in doc.get("nodes") or []:
                if node.get("type") not in REQUIRED_TYPES:
                    continue
                checked += 1
                if missing_credentials(node):
                    findings.append((rel, str(node.get("name") or "?"),
                                     str(node.get("type") or "?").split(".")[-1]))

    # A gate that read nothing has checked nothing. Where the blueprints cannot be compiled (no
    # node, no toolchain) every load above fails, and this used to end in PASS over zero of them.
    if not read:
        print("G52 FAIL — read ZERO blueprint workflows, so nothing was checked.\n"
              "  globs: " + ", ".join(BLUEPRINT_GLOBS))
        return 1

    if not findings:
        print(f"G52 PASS — all {checked} credential-requiring node(s) in {read} blueprint(s) "
              f"declare a credential.")
        return 0

    print("G52 FAIL")
    print(f"\n  {len(findings)} node(s) that cannot work without a credential and do not declare one:")
    for rel, name, typ in findings:
        print(f"    {rel}  ::  {name!r}  ({typ})")
    print(
        "\n  Copy the `credentials` block from a sibling of the same type in the same workflow.\n"
        "  A node like this does not fail loudly on deploy: it errors on every invocation while the\n"
        "  caller carries on (`onError: continueRegularOutput` is the norm here), so whatever the\n"
        "  node was added to accomplish is simply never accomplished, silently — which is how a fix\n"
        "  for a silent no-op shipped AS a silent no-op (processLock01, task #72)."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
