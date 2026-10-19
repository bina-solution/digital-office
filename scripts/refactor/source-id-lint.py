#!/usr/bin/env python3
"""source-id-lint — gate G37: SOURCE_ID must be a per-document id, never a folder id or a sender.

    python3 scripts/refactor/source-id-lint.py [--self-test]

`public.incoming_documents.SOURCE_ID` is documented (apps/indox/app/incoming_documents/api/
__init__.py, `_DOC_JOIN_COLS`) as "the drive file id / gmail message id the pipeline stamped when it
ingested the item — that is the join key." It is read back by `_docs_by_source()` keyed on
`(CONNECTION, SOURCE_ID)`, so a wrong value there does not error — it just joins to the wrong row, or
to no row, silently.

NOT HYPOTHETICAL. Five live writers shipped the wrong thing:
  * `SyncProcGDoc0001.json` / `SyncProcBS000001.json` (drive) stamped the *folder* being synced
    (`docs_source_folder_id` / `to_sync`) instead of the file's own id — every document in the same
    watched folder collapsed onto one SOURCE_ID.
  * `indoxGmailDocDownloader01.json` / `indoxGmailBSDownloader01.json` / `indoxGmailLinkDownloader01
    .json` (gmail) stamped the *sender's email address* (`.from.value[0].address` / `balanceSource` /
    `.from`) instead of the message id — every document from the same sender collapsed onto one
    SOURCE_ID.
  These four workflow names are exactly the ones `_default_processor()` in incoming_documents/api/
  __init__.py wires up as the PRODUCTION `processor_wf` for a Console-authored sync-v3 pipe — this
  was not a dead code path. Measured against the live DB (2026-08-05): 6,250 rows, only 579 distinct
  SOURCE_ID values; named (non-bulk-import) pipe rows for `drive-gdoc` and `gmail-doc` showed the
  exact same folder id / sender email repeated across different documents.

WHAT COUNTS AS BAD: an expression assigned to SOURCE_ID that references a folder-id variable
(`docs_source_folder_id`, `to_sync`, `folderId`/`folder_id`), or an email/sender field (`.from`,
`.from.value`, `.address`, `balanceSource`, `sender`). The per-document id is always reached through
something like `.json.id`, `.json.ID`, or `platform_id` — none of those match.

SCOPE: every n8n workflow under `apps/*/blueprint/n8n/*.workflow.ts` and `apps/n8n/blueprint/n8n/*.workflow.ts`
(the live blueprint tree — same roots tenancy-lint (G28) scans), plus every first-party Python file,
for a SOURCE_ID assignment written the same way a future Python writer would write one. A schema-only
mention of the column name (e.g. the `matchingColumns`/`schema` entries every executeWorkflow node
carries, or a `dynamic_data` column-type declaration) is not an assignment and is not flagged — only
a `name`/`value` pair or a raw `"SOURCE_ID": "<expr>"` key counts.
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

#: word-bounded so `fromDate`, `senderId` (a company field, say) etc. do not false-positive — see
#: the docstring's WHAT COUNTS AS BAD for what each of these traces back to.
BAD_PATTERNS = re.compile(
    r"\bto_sync\b"
    r"|\bdocs_source_folder_id\b"
    r"|\bfolder_?[Ii]d\b"
    r"|\bbalanceSource\b"
    r"|\bsender\b"
    r"|\.from\b"
    r"|\.address\b",
    re.IGNORECASE,
)

#: an id/platform_id/ID tail is what a per-document identity actually looks like — used only for the
#: self-test's own sanity, not as a gate condition (absence of BAD is sufficient to pass).
_GOOD_EXAMPLE = re.compile(r"\.(id|ID)\b|platform_id\b")


def _normalize(expr: str) -> str:
    e = expr.strip()
    if e.startswith("="):
        e = e[1:]
    e = e.strip()
    if e.startswith("{{") and e.endswith("}}"):
        e = e[2:-2]
    return e.strip()


#: Python spells the same property access `x["from"]` instead of `x.from` (a reserved word besides).
#: Fold bracket-subscript access to dot form before matching so ONE pattern set covers both n8n's
#: JS-flavoured expressions and Python's dict/subscript ones.
_PY_SUBSCRIPT = re.compile(r'''\[\s*["'](\w+)["']\s*\]''')


def _pyify(expr: str) -> str:
    return _PY_SUBSCRIPT.sub(r".\1", expr)


# ─────────────────────────────────────────────────────────────────────────────
# n8n scanner
# ─────────────────────────────────────────────────────────────────────────────
def _source_id_exprs(obj):
    """Yield every expression string a node's `parameters` assigns to SOURCE_ID.

    Two shapes appear in this codebase:
      * a raw key:  "SOURCE_ID": "={{ ... }}"                         (executeWorkflow inputs)
      * an assignment entry: {"name": "SOURCE_ID", "value": "={{ ... }}", ...}   (Set-node style)
    A `{"id": "SOURCE_ID", "displayName": "SOURCE_ID", ...}` schema entry (no `value` key) or a
    `{"name": "SOURCE_ID", "type": "TEXT", ...}` dynamic_data column declaration (no `value` key)
    describes the COLUMN, not a value, and is deliberately not yielded.
    """
    if isinstance(obj, dict):
        v = obj.get("SOURCE_ID")
        if isinstance(v, str):
            yield v
        if obj.get("name") == "SOURCE_ID" and isinstance(obj.get("value"), str):
            yield obj["value"]
        for v in obj.values():
            yield from _source_id_exprs(v)
    elif isinstance(obj, list):
        for item in obj:
            yield from _source_id_exprs(item)


def scan_workflow_obj(doc: dict, label: str) -> list[tuple[str, str, str]]:
    out = []
    for node in doc.get("nodes", []) or []:
        name = str(node.get("name") or "?")
        for expr in _source_id_exprs(node.get("parameters", {}) or {}):
            norm = _normalize(expr)
            if not norm:
                continue
            if BAD_PATTERNS.search(norm):
                out.append((label, name, expr))
    return out


def scan_workflow_file(path: pathlib.Path) -> list[tuple[str, str, str]]:
    try:
        doc = load_blueprint(str(path))
    except (OSError, ValueError, CompileError):
        return []
    return scan_workflow_obj(doc, path.name)


# ─────────────────────────────────────────────────────────────────────────────
# Python scanner — no writer does this today; the check is here so the NEXT one can't either.
# ─────────────────────────────────────────────────────────────────────────────
#: `"SOURCE_ID": <expr>` in a dict literal, and `row["SOURCE_ID"] = <expr>` / `entry["SOURCE_ID"] =
#: <expr>` assignment. Stops at the next comma/brace/newline — good enough for a single-line
#: expression, which is how every real writer (n8n or otherwise) has written this value so far.
PY_SOURCE_ID = re.compile(r'''["']SOURCE_ID["']\s*:\s*([^,\n}]+)''')
PY_SOURCE_ID_SUBSCRIPT = re.compile(r'''\[\s*["']SOURCE_ID["']\s*\]\s*=\s*([^\n]+)''')

SKIP = ("/node_modules/", "/_archive/", "/attic/", "/legacy/", "/.git/", "/ci-artifacts/",
        "/issues/", "/.refactor/", "/context-collection/",
        # added with the PY_GLOBS widening (2026-08-09): the old glob could not reach a virtualenv
        # or a cache dir, so it never needed to exclude one.
        "/__pycache__/", "/.venv/", "/venv/", "/site-packages/", "/.tox/", "/.pytest_cache/")


def scan_python_text(rel: str, text: str) -> list[tuple[str, str, str]]:
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        for pat in (PY_SOURCE_ID, PY_SOURCE_ID_SUBSCRIPT):
            m = pat.search(line)
            if not m:
                continue
            expr = m.group(1).strip()
            if BAD_PATTERNS.search(_pyify(expr)):
                out.append((rel, f"line {i}", expr))
    return out


#: WAS `apps/*/app/**/*.py` until 2026-08-09. That pattern needs a directory literally named `app`
#: and only `apps/indox` has one, so it resolved to 47 of the 209 first-party app `.py` files — one
#: app out of fourteen — while reading like "every app". Widened after the same glob, in
#: `mail-connection-lint` (G62), let `apps/mail/mailview/app.py` break production with the gate that
#: watched for it reporting green: it had never opened the file. Measured before the change: widening
#: this one adds ZERO findings today, so it is future-proofing, not a deferred fix.
PY_GLOBS = ("apps/**/*.py", "platform-base/**/*.py")


def scan_python_files() -> list[tuple[str, str, str]]:
    out = []
    seen: set[str] = set()
    for py in sorted(p for g in PY_GLOBS for p in REPO.glob(g)):
        rel = str(py.relative_to(REPO)).replace("\\", "/")
        if rel in seen:
            continue
        seen.add(rel)
        if any(s in f"/{rel}" for s in SKIP):
            continue
        try:
            text = py.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        out += scan_python_text(rel, text)
    return out


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    # n8n — must catch
    ("drive folder id (docs_source_folder_id)", True, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"value": {
            "SOURCE_TYPE": "GOOGLE_DRIVE_FOLDER",
            "SOURCE_ID": "={{ $('Start').first().json.docs_source_folder_id }}"}}}}]}),
    ("drive folder id (to_sync)", True, {
        "nodes": [{"name": "Register", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Ctx').first().json.to_sync }}"}}}}]}),
    ("gmail sender address (.from.value[].address)", True, {
        "nodes": [{"name": "Upsert Incoming Document", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Loop over documents').first().json.from.value[0].address }}"
        }}}}]}),
    ("gmail sender (balanceSource)", True, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Balance Doc Properties').item.json.balanceSource }}"}}}}]}),
    ("gmail sender (bare .from)", True, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Code in JavaScript').item.json.from }}"}}}}]}),
    ("Set-node assignment shape, folder id", True, {
        "nodes": [{"name": "Map Fields", "parameters": {"assignments": {"assignments": [
            {"id": "x", "name": "SOURCE_ID", "value": "={{ $json.folderId }}", "type": "string"}
        ]}}}]}),
    # n8n — must allow
    ("per-document drive file id (Loop Over Items.id)", False, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Loop Over Items').first().json.id }}"}}}}]}),
    ("per-document gmail message id (Get a message.id)", False, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"value": {
            "SOURCE_ID": "={{ $('Get a message').item.json.id }}"}}}}]}),
    ("v3 thin-mode platform_id", False, {
        "nodes": [{"name": "Drive Row", "parameters": {"jsCode":
            "const row={SOURCE_TYPE:'GOOGLE_DRIVE_FOLDER', SOURCE_ID:j.platform_id};"}}]}),
    ("Set-node assignment shape, $json.ID", False, {
        "nodes": [{"name": "Map Fields", "parameters": {"assignments": {"assignments": [
            {"id": "bw9", "name": "SOURCE_ID", "value": "={{ $json.ID }}", "type": "string"}
        ]}}}]}),
    ("schema-only mention, no value — must not be flagged", False, {
        "nodes": [{"name": "Call Upsert", "parameters": {"workflowInputs": {"schema": [
            {"id": "SOURCE_ID", "displayName": "SOURCE_ID", "required": False, "display": True}
        ]}}}]}),
    ("dynamic_data column declaration, no value — must not be flagged", False, {
        "nodes": [{"name": "UPSERT Adapter", "parameters": {"fields": [
            {"name": "SOURCE_ID", "type": "TEXT", "isPrimaryKey": False}
        ]}}]}),
]

PY_SELF_TEST = [
    ("dict literal, folder id", "apps/_x/app/_p.py",
     'row = {"SOURCE_TYPE": "GOOGLE_DRIVE_FOLDER", "SOURCE_ID": ctx["docs_source_folder_id"]}\n',
     True),
    ("subscript assignment, sender field", "apps/_x/app/_p.py",
     'entry["SOURCE_ID"] = msg["from"]["value"][0]["address"]\n', True),
    ("dict literal, per-document id — must allow", "apps/_x/app/_p.py",
     'row = {"SOURCE_TYPE": "GMAIL", "SOURCE_ID": msg["id"]}\n', False),
    ("subscript assignment, platform_id — must allow", "apps/_x/app/_p.py",
     'entry["SOURCE_ID"] = platform_id\n', False),
]


def self_test() -> int:
    bad = 0
    print("n8n scanner:")
    for label, should, doc in SELF_TEST:
        got = bool(scan_workflow_obj(doc, "_self_test_.json"))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    print("python scanner:")
    for label, rel, text, should in PY_SELF_TEST:
        got = bool(scan_python_text(rel, text))
        ok = got == should
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'caught' if got else 'allowed':<8} ({'must catch' if should else 'must allow'}): {label}")
    total = len(SELF_TEST) + len(PY_SELF_TEST)
    print(f"\nG37 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings: list[tuple[str, str, str]] = []
    for pattern in ("apps/*/blueprint/n8n/*.workflow.ts",):
        for wf in sorted(REPO.glob(pattern)):
            findings.extend(scan_workflow_file(wf))
    findings.extend(scan_python_files())

    if not findings:
        print("G37 PASS — every SOURCE_ID assignment resolves to a per-document id "
              "(no folder-id variable, no email/sender field).")
        return 0

    print(f"G37 FAIL — {len(findings)} SOURCE_ID assignment(s) look like a folder id or a "
          f"sender/email, not a per-document id:\n")
    for where, node, expr in findings:
        print(f"  {where}  ::  {node}")
        print(f"      SOURCE_ID = {expr}")
    print(
        "\n  SOURCE_ID must be the drive file id / gmail message id the pipeline ingested the item\n"
        "  under (apps/indox/app/incoming_documents/api/__init__.py, _DOC_JOIN_COLS) — reach it via\n"
        "  the file/message object's own `.id` (or `platform_id` in the sync-v3 delivery contract),\n"
        "  never via the folder/context being synced or the message's `from`/sender."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
