#!/usr/bin/env python3
"""drive-connection-lint — gate G46: every call into apps/drive's §3 canonical ops names its
connection explicitly.

    python3 scripts/refactor/drive-connection-lint.py [--self-test]

WHY THIS GATE EXISTS

`apps/drive` used to resolve a MISSING `profile_id`/`connection_id` to whatever connection this
deployment's console happens to be bound to — an ambient, per-human, per-console choice with no
relationship to what an automated caller meant. On this host that binding is the Google SERVICE
ACCOUNT (by design: no personal storage, no Shared Drive, every write refused), and one silent
default caused three independent failures, each found by a different agent that did not know about
the others (2026-08-06):

  1. All four mail registries lacked `drive_profile_id`, so every deposit fell through to the
     service account and quarantined after 5 attempts — 100% of the `needs_review` pile.
  2. The demo-injection nodes carried no `connection_id` and would have written the owner's REAL
     client Google Drive.
  3. 16 `driveApi01` call sites across 5 E2E test workflows omitted `profile_id` — 6 of 8 suites
     dead with 503s, and the surviving `list` calls silently searched the wrong backend and found
     nothing.

`apps/drive/app.py` now REFUSES a §3 op with neither id present (`_explicit_connection_required`,
400, naming what to pass) instead of silently substituting — see that function's docstring for the
full argument (why immediate refusal, why reads refuse exactly like writes, why the UI plane is
exempt). That fixes the SERVICE. This gate is the fix for the CALL SITES: the seventeenth omission
still ships a broken caller — it now just fails loudly in production instead of quarantining
silently, which is strictly better but still worth catching before merge.

WHAT COUNTS AS A VIOLATION
  * an n8n `executeWorkflow` node whose `workflowId` names `driveApi01`, whose `params` expression
    does not mention `profile_id` or `connection_id` anywhere (as a literal key or inside the
    expression — e.g. `$json.profile_id`, `$('Ctx').item.json.connection_id`);
  * an n8n `httpRequest` node that calls one of the seven §3 canonical-op paths on the drive
    service directly (`/list /download /upload /move /update /delete /createFromText` on a host
    matching `drive` — bypassing driveApi01 entirely) whose body (`jsonBody` / `bodyParameters`)
    does not mention `profile_id` or `connection_id`;
  * a first-party Python `requests.(get|post)` call to one of those same seven paths on the drive
    service whose call does not mention `profile_id` or `connection_id` within the same statement.

SCOPE: every n8n workflow under `apps/*/blueprint/n8n/*.workflow.ts` and
`apps/n8n/blueprint/n8n/*.workflow.ts` (the live blueprint tree — same roots tenancy-lint/G28 and
source-id-lint/G37 scan), plus every first-party Python file under `apps/**`, `scripts/**` and
`platform-base/**` (excluding `apps/drive/**` itself — that is the SERVICE, not a caller).

The Python roots were `apps/*/app/**/*.py` + `scripts/**/*.py` until 2026-08-09, and that paragraph
claimed a coverage the glob did not have: `apps/*/app/**` matches `apps/indox/app/…` and nothing
else in this repo. See `PY_GLOBS` below for the incident that made the difference visible, and for
what is still open here.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
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

#: the §3 automation surface (apps/drive/adapters/__init__.py CANONICAL_OPS) — the ONLY paths this
#: gate cares about. UI-plane paths (/api/*) are deliberately out of scope: the browser SPA behind
#: SSO has no other identity to declare and is not the automation surface this incident was about.
CANONICAL_PATHS = ("/list", "/download", "/upload", "/move", "/update", "/delete",
                    "/createFromText")

_ID_MENTION = re.compile(r"\b(profile_id|connection_id)\b")

SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/issues/", "/.refactor/", "/context-collection/", "/__pycache__/",
        # added with the PY_GLOBS widening (2026-08-09): the old glob could not reach a
        # virtualenv or a vendored tree, so it never needed to exclude one.
        "/.venv/", "/venv/", "/site-packages/", "/dist-packages/", "/.tox/", "/.pytest_cache/",
        "/vendor/", "/third_party/")


# ─────────────────────────────────────────────────────────────────────────────
# n8n scanner
# ─────────────────────────────────────────────────────────────────────────────
def _rl_value(v):
    """An n8n resourceLocator field is either a bare string or {"__rl":true,"value":...}."""
    if isinstance(v, dict):
        return v.get("value")
    return v


def _workflow_inputs_text(params: dict) -> str:
    """Every string this node's workflowInputs carries, joined — covers both the current
    `defineBelow` shape (`value: {op, params}`) and a `matchingColumns` mapping, whichever the
    node was authored with."""
    wi = (params or {}).get("workflowInputs") or {}
    bits = []

    def _walk(o):
        if isinstance(o, str):
            bits.append(o)
        elif isinstance(o, dict):
            for v in o.values():
                _walk(v)
        elif isinstance(o, list):
            for v in o:
                _walk(v)

    _walk(wi.get("value"))
    return "\n".join(bits)


def _http_body_text(params: dict) -> str:
    """Every string an httpRequest node's body carries — jsonBody (raw expression) and
    bodyParameters (the multipart/form shape driveApi01's own `d:upload` node uses)."""
    bits = []
    jb = (params or {}).get("jsonBody")
    if isinstance(jb, str):
        bits.append(jb)
    for p in (((params or {}).get("bodyParameters") or {}).get("parameters") or []):
        if isinstance(p, dict):
            bits.append(str(p.get("name") or ""))
            bits.append(str(p.get("value") or ""))
    return "\n".join(bits)


#: driveApi01's OWN definition (apps/drive/blueprint/n8n/driveApi01.json) is not a CALLER — its
#: `d:list`/`d:download`/`d:move`/`d:update`/`d:delete`/`d:createFromText` nodes blindly forward
#: whatever `params` object the calling workflow supplied (`JSON.stringify($json.params||{})`).
#: The id, if any, lives in the CALLER's params — checked separately, on every OTHER file, by the
#: `driveApi01 call` branch below. Flagging driveApi01.json's own plumbing here would be a false
#: positive on the fix's own target, not a caller that forgot something.
DRIVEAPI01_DEFINITION = "apps/drive/blueprint/n8n/driveApi01.json"


def scan_workflow_file(path: pathlib.Path, is_definition: bool = False) -> list[tuple[str, str, str]]:
    """[(node_name, kind, detail)] for every violation in one workflow file."""
    try:
        doc = load_blueprint(str(path))
    except (OSError, ValueError, CompileError):
        return []
    return scan_workflow_doc(doc, is_definition=is_definition)


def scan_workflow_doc(doc: dict, is_definition: bool = False) -> list[tuple[str, str, str]]:
    """The actual rules, over a loaded workflow dict.

    [2026-08-23] Split out of scan_workflow_file so the self-test can drive the rules directly.
    It used to build its fixtures by writing json.dumps(doc) to a temp .json and handing the PATH
    back to scan_workflow_file. That worked only while blueprints were JSON; once the loader
    became n8n_blueprint (.workflow.ts), the temp file could not be parsed, every fixture loaded
    as empty, and three "must catch" cases reported "allowed" — a self-test that passes because
    it is testing nothing, which is the same failure mode as the dead globs it was fixed for.
    """
    out = []
    for node in doc.get("nodes", []) or []:
        ntype = str(node.get("type") or "")
        params = node.get("parameters") or {}
        name = str(node.get("name") or "?")

        if ntype.endswith("executeWorkflow") and not ntype.endswith("executeWorkflowTrigger"):
            target = _rl_value(params.get("workflowId"))
            if target != "driveApi01":
                continue
            text = _workflow_inputs_text(params)
            if not _ID_MENTION.search(text):
                detail = (f"op input carries no profile_id/connection_id: {text[:160]!r}" if text
                          else "no workflowInputs at all — relies on the legacy implicit "
                               "item-passthrough (typeVersion 1.1), so whatever the upstream "
                               "node emits as {op, params} goes straight through unchecked")
                out.append((name, "driveApi01 call", detail))
            continue

        if is_definition:
            continue  # driveApi01.json's own forwarding nodes — see DRIVEAPI01_DEFINITION above

        if ntype.endswith("httpRequest"):
            url = str(params.get("url") or "")
            if "drive" not in url.lower():
                continue
            if not any(url.rstrip("/").endswith(p) for p in CANONICAL_PATHS):
                continue
            text = _http_body_text(params)
            if not _ID_MENTION.search(text):
                out.append((name, f"direct HTTP call to {url}",
                            f"body carries no profile_id/connection_id: {text[:160]!r}"))
    return out


def scan_n8n() -> list[tuple[str, str, str, str]]:
    findings = []
    for pattern in ("apps/*/blueprint/n8n/*.workflow.ts",):
        for wf in sorted(REPO.glob(pattern)):
            rel = str(wf.relative_to(REPO)).replace("\\", "/")
            if any(s in f"/{rel}" for s in SKIP):
                continue
            for name, kind, detail in scan_workflow_file(wf, is_definition=(rel == DRIVEAPI01_DEFINITION)):
                findings.append((rel, name, kind, detail))
    return findings


# ─────────────────────────────────────────────────────────────────────────────
# Python scanner — a first-party script/app hitting the drive service directly.
# ─────────────────────────────────────────────────────────────────────────────
#: `requests.post(f"...{path}", ...)` / `requests.get("http://drive:8975/list", ...)` — matched
#: loosely on the trailing canonical-op path segment so both an f-string base and a literal one
#: are caught; the call is presumed to end at the matching close-paren of a single statement, which
#: this gate approximates as "the same or next 6 lines" (identical tolerance to how the call sites
#: in this codebase are actually formatted — see the self-test).
_PY_CALL = re.compile(
    r"""(?:requests|httpx)\.(get|post)\s*\(\s*[^,()]*?"""
    r"""(/list|/download|/upload|/move|/update|/delete|/createFromText)["'f]"""
)

_LOOKAHEAD_LINES = 6


def scan_python_text(rel: str, text: str) -> list[tuple[str, str, str]]:
    lines = text.splitlines()
    out = []
    for i, line in enumerate(lines):
        m = _PY_CALL.search(line)
        if not m:
            continue
        # only flag calls that plausibly name the drive service, not some unrelated API sharing an
        # op-name-shaped path segment (e.g. a totally different service's own "/move")
        if "drive" not in line.lower():
            window_has_drive = any("drive" in lines[j].lower()
                                    for j in range(max(0, i - 3), i))
            if not window_has_drive:
                continue
        window = "\n".join(lines[i:i + _LOOKAHEAD_LINES])
        if not _ID_MENTION.search(window):
            out.append((rel, f"line {i + 1}", line.strip()))
    return out


#: WAS `("apps/*/app/**/*.py", "scripts/**/*.py")` until 2026-08-09.
#:
#: `apps/*/app/**` requires a directory literally named `app`, and in this repo only `apps/indox`
#: has one — so the "every first-party Python file under apps/" this gate's own SCOPE paragraph
#: promises resolved to 47 of 209 files, one app out of fourteen. `apps/drive/app.py` is a FILE
#: named `app.py`, not a directory, and was outside it too (harmless here, since the service is
#: excluded anyway — but it shows the pattern does not mean what it reads like).
#:
#: This is not a hypothetical. The identical glob in `mail-connection-lint` (G62), copied from this
#: file, is why the mail-side guard's rollout took the client's mail UI down on 2026-08-09 with the
#: gate that watches for exactly that reporting green: `apps/mail/mailview/app.py` was never opened.
#: Measured before this change: widening the pattern adds ZERO findings to G46 today. It is
#: future-proofing — the next drive caller that lands outside `apps/*/app/**` is now seen.
#:
#: STILL OPEN ON THIS GATE, deliberately not fixed here: `_PY_CALL` can only see a canonical path
#: inside a literal `requests`/`httpx` call, so a caller that reaches drive through one proxy helper
#: (`def dv(path, ...)`) is invisible to it — hole #3 of the three G62 found. G62 now resolves
#: helpers (see `scan_python_helpers` there); porting that here is a real change to an ENFORCED,
#: currently-green, CI-wired gate and belongs in its own lane with its own measurement.
PY_GLOBS = ("apps/**/*.py", "scripts/**/*.py", "platform-base/**/*.py")


def scan_python() -> list[tuple[str, str, str]]:
    out = []
    seen: set[str] = set()
    for pattern in PY_GLOBS:
        for py in sorted(REPO.glob(pattern)):
            rel = str(py.relative_to(REPO)).replace("\\", "/")
            if rel in seen:
                continue
            seen.add(rel)
            if rel.startswith("apps/drive/"):
                continue  # the service itself, not a caller
            if rel.startswith("scripts/refactor/"):
                continue  # the gates themselves (this file's own docstring quotes a call shape and
                          # would otherwise flag itself — gates are not drive callers)
            if any(s in f"/{rel}" for s in SKIP):
                continue
            try:
                text = py.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            out += scan_python_text(rel, text)
    return out


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST_N8N = [
    ("driveApi01 call, no id anywhere", True, {
        "nodes": [{"name": "Search files", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "driveApi01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                      "op": "list",
                                      "params": "={{ ({ folderId: '', query: 'x', limit: 1 }) }}"}}}}]}),
    ("driveApi01 call, profile_id present in params expression", False, {
        "nodes": [{"name": "Upload doc", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "driveApi01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                      "op": "upload",
                                      "params": "={{ ({ folderId: $json.folder, profile_id: $json.drive_profile_id }) }}"}}}}]}),
    ("driveApi01 call, connection_id present", False, {
        "nodes": [{"name": "List files", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "driveApi01", "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow", "value": {
                                      "op": "list",
                                      "params": "={{ ({ connection_id: $json.connection_id }) }}"}}}}]}),
    ("executeWorkflow call to something OTHER than driveApi01 — must not be flagged", False, {
        "nodes": [{"name": "Call gateway", "type": "n8n-nodes-base.executeWorkflow",
                   "parameters": {"workflowId": {"__rl": True, "value": "indoxDataGateway01",
                                                  "mode": "id"},
                                  "workflowInputs": {"mappingMode": "defineBelow",
                                                      "value": {"op": "upsert"}}}}]}),
    ("executeWorkflowTrigger (the driveApi01 subworkflow's OWN trigger) — must not be flagged",
     False, {
         "nodes": [{"name": "When Called", "type": "n8n-nodes-base.executeWorkflowTrigger",
                    "parameters": {"workflowId": {"__rl": True, "value": "driveApi01",
                                                   "mode": "id"}}}]}),
    ("direct HTTP call to drive:8975/upload, no id in body", True, {
        "nodes": [{"name": "d:upload direct", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "http://drive:8975/upload", "sendBody": True,
                                  "bodyParameters": {"parameters": [
                                      {"name": "name", "value": "={{ $json.name }}"}]}}}]}),
    ("direct HTTP call to drive:8975/upload, connection_id in bodyParameters", False, {
        "nodes": [{"name": "d:upload direct", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "http://drive:8975/upload", "sendBody": True,
                                  "bodyParameters": {"parameters": [
                                      {"name": "connection_id",
                                       "value": "={{ $json.connection_id }}"}]}}}]}),
    ("HTTP call to an unrelated service's own /list — must not be flagged", False, {
        "nodes": [{"name": "Other API", "type": "n8n-nodes-base.httpRequest",
                   "parameters": {"url": "http://some-other-service:9000/list", "sendBody": True,
                                  "jsonBody": "={{ {} }}"}}]}),
    ("driveApi01's OWN d:list forwarding node, no id (it forwards the CALLER's params blindly) "
     "— must not be flagged when scanned as the definition file", False, {
         "nodes": [{"name": "d:list", "type": "n8n-nodes-base.httpRequest",
                    "parameters": {"url": "http://drive:8975/list", "sendBody": True,
                                   "jsonBody": "={{ JSON.stringify($json.params || {}) }}"}}]},
     True),  # 4th element: is_definition — scanned as apps/drive/blueprint/n8n/driveApi01.json itself
    ("executeWorkflow to driveApi01 with no workflowInputs (typeVersion 1.1 implicit "
     "passthrough) — must catch, message explains the implicit path", True, {
         "nodes": [{"name": "Claim Move", "type": "n8n-nodes-base.executeWorkflow",
                    "typeVersion": 1.1,
                    "parameters": {"workflowId": {"__rl": True, "value": "driveApi01",
                                                   "mode": "id"}, "options": {}}}]}),
]

SELF_TEST_PY = [
    ("requests.post to drive /upload, no id", "scripts/_x/caller.py",
     'requests.post(f"{DRIVE_URL}/upload", files=files, data={"name": name}, timeout=30)\n',
     True),
    ("requests.post to drive /list, profile_id in payload", "scripts/_x/caller.py",
     'requests.post(f"{DRIVE_URL}/list", json={"folderId": fid, "profile_id": pid}, timeout=30)\n',
     False),
    ("requests.get to drive /download, connection_id passed", "scripts/_x/caller.py",
     'requests.get(f"{DRIVE_URL}/download", json={"fileId": fid, "connection_id": cid})\n',
     False),
    ("requests.post to an unrelated host's own /upload — must not be flagged",
     "scripts/_x/caller.py",
     'requests.post(f"{OTHER_URL}/upload", json={"name": name}, timeout=30)\n',
     False),
]


def self_test() -> int:
    bad = 0
    print("n8n scanner:")
    for entry in SELF_TEST_N8N:
        label, should, doc = entry[0], entry[1], entry[2]
        is_definition = entry[3] if len(entry) > 3 else False
        got = bool(scan_workflow_file_from_obj(doc, is_definition=is_definition))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("python scanner:")
    for label, rel, text, should in SELF_TEST_PY:
        got = bool(scan_python_text(rel, text))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    total = len(SELF_TEST_N8N) + len(SELF_TEST_PY)
    print(f"\nG46 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def scan_workflow_file_from_obj(doc: dict, is_definition: bool = False) -> list[tuple[str, str, str]]:
    """Same logic as scan_workflow_file, over an in-memory doc (for the self-test)."""
    return scan_workflow_doc(doc, is_definition=is_definition)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    n8n_findings = scan_n8n()
    py_findings = scan_python()

    if not n8n_findings and not py_findings:
        print("G46 PASS — every driveApi01 call site and every direct call into apps/drive's "
              "canonical ops names an explicit profile_id/connection_id.")
        return 0

    if n8n_findings:
        print(f"n8n call sites with no explicit connection ({len(n8n_findings)}):\n")
        for path, node, kind, detail in n8n_findings:
            print(f"  {path}  ::  {node}")
            print(f"      {kind}")
            print(f"      {detail}")
        print()
    if py_findings:
        print(f"Python call sites with no explicit connection ({len(py_findings)}):\n")
        for path, where, line in py_findings:
            print(f"  {path}  {where}")
            print(f"      {line}")
        print()

    total = len(n8n_findings) + len(py_findings)
    print(f"G46 FAIL — {total} call site(s) into apps/drive's §3 canonical ops (list/download/"
          f"upload/move/update/delete/createFromText) carry no explicit profile_id/connection_id.")
    print(
        "\n  apps/drive now REFUSES these calls at runtime (400, naming what to pass) instead of\n"
        "  silently running against whatever connection the console happens to be bound to — see\n"
        "  apps/drive/app.py `_explicit_connection_required`. Add `profile_id` (an engine profile\n"
        "  id) or `connection_id` (any vault instance id) to this call's params/body."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
