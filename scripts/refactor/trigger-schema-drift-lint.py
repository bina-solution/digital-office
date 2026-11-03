#!/usr/bin/env python3
"""trigger-schema-drift-lint — gate G39: an executeWorkflowTrigger's declared schema must match the
table it upserts.

    python3 scripts/refactor/trigger-schema-drift-lint.py [--self-test]

WHY THIS EXISTS. n8n's `executeWorkflowTrigger` node has three input modes. `passthrough` forwards
whatever the caller sent, unmodified. The other two — `jsonExample` (paste a sample payload, n8n
derives field names from its keys) and the "Define below" fields list (`workflowInputs.values`) —
each compile to an explicit schema, and **n8n silently drops any field the caller sent that isn't in
that schema.** Nothing errors. The field is just gone from `$json` inside the sub-workflow, as if it
were never sent.

`indoxDocBatchUpsert01.json`'s trigger ("When Executed by Another Workflow", `jsonExample` mode) was
missing `CONNECTION`, `NEXT_RETRY_AT` and `RETRY_COUNT` — all three real columns on
`public.incoming_documents` (`apps/indox/blueprint/fixtures/schema.sql`). Measured against the live
DB (2026-08-05): `NEXT_RETRY_AT` is populated on **0 of 6,207 rows** — retry scheduling has never
once worked, silently, because every caller's `NEXT_RETRY_AT` value was discarded at the trigger
before the upsert code ever ran. (`THUMBNAIL` / `THUMBNAIL_COMPLETED` were the same defect and had
already been fixed by the time this gate was written — the fix is the same one-line addition to the
`jsonExample` for whichever field is missing.)

WHAT THIS CHECKS: a short, explicit, hand-maintained map (`UPSERT_TARGETS` below) from a blueprint
workflow file whose trigger has an explicit schema to the table it upserts into. This is deliberately
NOT a heuristic that guesses the target table from the workflow's name or its downstream nodes —
guessing which table a workflow writes to is exactly the kind of "probably right" mechanism that
produces false negatives nobody notices (see `feedback_prefer_existing_mechanism_over_new_heuristic`
in this project's operating notes: prefer an explicit, checkable declaration over an inferred one).
Today there is exactly one entry because there is exactly one workflow in this shape; add a row when
a new one exists.

For each mapped workflow, the gate diffs the trigger's declared field set against the table's real
columns (parsed from the same `schema.sql` migration file the table is actually built from) and
fails on drift in EITHER direction:
  * a table column the trigger doesn't declare  -> every caller's value for that field is silently
    discarded before it reaches the table. This is the direction that has actually bitten this
    platform (NEXT_RETRY_AT) and is the more serious failure.
  * a trigger field with no matching column       -> the field survives the trigger but nothing ever
    writes it anywhere; usually a sign the schema.sql migration and the blueprint were edited
    separately and one of them is stale.

`created_at` / `updated_at` are excluded from the "table column not in trigger" direction on
purpose: they are server-managed defaults (`timestamptz default now()`), never meant to be supplied
by a caller, and flagging them would be permanent, correct-as-is noise — exactly the kind of
false-positive that gets a gate silenced rather than fixed.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
# Blueprints are code (.workflow.ts) since 52b32aa4. n8n_blueprint is the ONE reader —
# see its docstring for why this is not a per-gate parser.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from n8n_blueprint import load as load_blueprint, CompileError   # noqa: E402


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]

#: workflow blueprint path (repo-relative) -> (schema.sql-relative path, table name).
#: See docstring for why this is an explicit list rather than an inferred one.
UPSERT_TARGETS: dict[str, tuple[str, str]] = {
    # indoxDocBatchUpsert01 was retired to legacy/indox-retired-20260821/ (b01579ac). Its entry
    # is gone rather than repointed: a target naming no file makes this gate report "not found"
    # as if it were a finding, which is how it spent weeks looking merely red instead of dead.
}

#: server-managed columns a caller is never expected to supply — see docstring.
SERVER_MANAGED = {"created_at", "updated_at"}


def trigger_schema_fields(doc: dict) -> tuple[set[str], str] | None:
    """The declared field set of `doc`'s executeWorkflowTrigger, and which mode produced it.
    Returns None if the trigger is `passthrough` (or has no explicit schema) — nothing to diff."""
    for node in doc.get("nodes", []) or []:
        if not str(node.get("type", "")).endswith("executeWorkflowTrigger"):
            continue
        p = node.get("parameters") or {}
        source = p.get("inputSource")
        if source == "jsonExample":
            try:
                example = json.loads(p.get("jsonExample") or "{}")
            except (TypeError, ValueError):
                return None
            if isinstance(example, dict):
                return set(example.keys()), "jsonExample"
        elif source is None and isinstance(p.get("workflowInputs"), dict) \
                and isinstance(p["workflowInputs"].get("values"), list):
            fields = {v.get("name") for v in p["workflowInputs"]["values"]
                      if isinstance(v, dict) and v.get("name")}
            if fields:
                return fields, "workflowInputs.values"
        # "passthrough", plain workflowInputs with no values/schema, or no trigger at all: skip.
    return None


_CREATE_COL = re.compile(
    r'create\s+table\s+if\s+not\s+exists\s+public\.(\w+)\s*\(\s*"([^"]+)"', re.IGNORECASE)
_ALTER_COL = re.compile(
    r'alter\s+table\s+public\.(\w+)\s+add\s+column\s+if\s+not\s+exists\s+"([^"]+)"', re.IGNORECASE)


def table_columns(schema_sql: str, table: str) -> set[str]:
    cols = set()
    for pat in (_CREATE_COL, _ALTER_COL):
        for m in pat.finditer(schema_sql):
            if m.group(1) == table:
                cols.add(m.group(2))
    return cols - SERVER_MANAGED


def diff(trigger_fields: set[str], columns: set[str]) -> tuple[set[str], set[str]]:
    """(columns the trigger silently drops, trigger fields with no matching column)."""
    columns = columns - SERVER_MANAGED
    return columns - trigger_fields, trigger_fields - columns - {"__force_backend", "_be"}


# ─────────────────────────────────────────────────────────────────────────────
# PART 2 — the CALLER direction, across EVERY explicit-schema trigger.
#
# WHY THIS IS HERE AND NOT A SEPARATE GATE. Part 1 above answers "does this trigger declare every
# column of the table it writes?" and needs `UPSERT_TARGETS` because only a human knows which
# workflow upserts which table. That map has exactly ONE entry, while the repo contains **31**
# workflows whose trigger carries an explicit schema — so 30 of them had no machine check of any
# kind. This part closes that without a hand-maintained map at all, because the missing fact is
# already ON DISK: every caller is an `executeWorkflow` node in this same repo, and the fields it
# passes are right there in `workflowInputs.value`.
#
# It is the SAME invariant as Part 1 — "a field that reaches an explicit-schema
# executeWorkflowTrigger undeclared is silently discarded before any node runs" — just measured
# from the caller's side instead of the table's, which is why it lives in this gate rather than
# competing with it.
#
# FOUND ON FIRST RUN (2026-08-06): `indoxV2Driver01`'s "Search Existing Shipment" node calls
# `indoxDocGet01` with `TYPE: "SHIPMENT"`. indoxDocGet01's trigger declares only
# COMPANY_ID / ID / SHORT_DOC_ID and references `TYPE` nowhere in the entire workflow, so the type
# constraint is gone before the lookup runs and a "find the existing SHIPMENT" search can match a
# document of any type.
#
# DELIBERATELY NARROW: it only flags a field some caller ACTUALLY sends. It does not guess at
# fields a trigger "ought" to have, so it cannot produce the permanent background noise that gets a
# gate silenced. Expression-valued `workflowId` (`={{...}}`) is skipped for the same reason G38
# skips it — the target is not statically knowable.
BLUEPRINT_GLOBS = ("apps/*/blueprint/n8n/*.workflow.ts",)

#: envelope/control fields that are legitimately passed but are not trigger schema fields.
CALLER_IGNORED = {"__force_backend", "_be"}


def _target_id(value):
    """The statically-known target of an executeWorkflow node's workflowId, else None."""
    if isinstance(value, str):
        return None if value.startswith("=") else (value or None)
    if isinstance(value, dict):
        v = value.get("value")
        if isinstance(v, str) and v and not v.startswith("="):
            return v
    return None


def declared_schemas(docs: dict[str, dict]) -> dict[str, tuple[set[str], str, str]]:
    """workflow id -> (declared field set, mode, file) for every EXPLICIT-schema trigger."""
    out: dict[str, tuple[set[str], str, str]] = {}
    for rel, doc in docs.items():
        wid = doc.get("id")
        if not isinstance(wid, str) or not wid:
            continue
        res = trigger_schema_fields(doc)
        if res is not None:
            out[wid] = (res[0], res[1], rel)
    return out


def call_site_fields(docs: dict[str, dict]) -> dict[str, dict[str, set[str]]]:
    """target workflow id -> {caller file -> field names that caller passes}."""
    out: dict[str, dict[str, set[str]]] = {}
    for rel, doc in docs.items():
        for node in doc.get("nodes", []) or []:
            t = str(node.get("type", ""))
            if "executeWorkflow" not in t or t.endswith("executeWorkflowTrigger"):
                continue
            p = node.get("parameters") or {}
            target = _target_id(p.get("workflowId"))
            if not target:
                continue
            wi = p.get("workflowInputs")
            if not isinstance(wi, dict):
                continue
            fields: set[str] = set()
            v = wi.get("value")
            if isinstance(v, dict):
                fields |= {k for k in v.keys() if isinstance(k, str)}
            if fields:
                out.setdefault(target, {}).setdefault(rel, set()).update(fields)
    return out


def caller_findings(docs: dict[str, dict]) -> list[tuple[str, str, str, list[str]]]:
    """(target id, target file, caller file, sorted undeclared fields) for every drop."""
    declared = declared_schemas(docs)
    sites = call_site_fields(docs)
    found = []
    for wid, (fields, _mode, wf_rel) in sorted(declared.items()):
        for caller_rel, sent in sorted((sites.get(wid) or {}).items()):
            dropped = sorted(f for f in sent if f not in fields and f not in CALLER_IGNORED)
            if dropped:
                found.append((wid, wf_rel, caller_rel, dropped))
    return found


# ─────────────────────────────────────────────────────────────────────────────
SELF_TEST = [
    ("missing column (the real NEXT_RETRY_AT bug), jsonExample mode",
     {"nodes": [{"type": "n8n-nodes-base.executeWorkflowTrigger",
       "parameters": {"inputSource": "jsonExample",
                       "jsonExample": json.dumps({"ID": None, "NAME": None})}}]},
     {"ID", "NAME", "RETRY_COUNT"}, True),
    ("schema matches columns exactly, jsonExample mode", {"nodes": [
        {"type": "n8n-nodes-base.executeWorkflowTrigger",
         "parameters": {"inputSource": "jsonExample",
                         "jsonExample": json.dumps({"ID": None, "NAME": None})}}]},
     {"ID", "NAME"}, False),
    ("missing column, workflowInputs.values mode", {"nodes": [
        {"type": "n8n-nodes-base.executeWorkflowTrigger",
         "parameters": {"workflowInputs": {"values": [{"name": "ID"}, {"name": "NAME"}]}}}]},
     {"ID", "NAME", "CONNECTION"}, True),
    ("extra trigger field with no matching column", {"nodes": [
        {"type": "n8n-nodes-base.executeWorkflowTrigger",
         "parameters": {"inputSource": "jsonExample",
                         "jsonExample": json.dumps({"ID": None, "GHOST_FIELD": None})}}]},
     {"ID"}, True),
    ("passthrough mode — nothing to diff, must not even attempt it", {"nodes": [
        {"type": "n8n-nodes-base.executeWorkflowTrigger",
         "parameters": {"inputSource": "passthrough"}}]},
     {"ID", "ANYTHING"}, False),
    ("server-managed created_at/updated_at excluded from the column-missing direction", {"nodes": [
        {"type": "n8n-nodes-base.executeWorkflowTrigger",
         "parameters": {"inputSource": "jsonExample",
                         "jsonExample": json.dumps({"ID": None})}}]},
     {"ID", "created_at", "updated_at"}, False),
]


def self_test() -> int:
    bad = 0
    for label, doc, columns, should_flag in SELF_TEST:
        fields_mode = trigger_schema_fields(doc)
        if fields_mode is None:
            got = False
        else:
            missing, extra = diff(fields_mode[0], columns)
            got = bool(missing or extra)
        ok = got == should_flag
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'flagged' if got else 'clean  ':<8} "
              f"({'must flag' if should_flag else 'must be clean'}): {label}")

    # sanity: the parser itself, against a miniature real-shaped schema.sql fragment.
    frag = (
        'create table if not exists public.incoming_documents ("ID" TEXT primary key);\n'
        'alter table public.incoming_documents add column if not exists "NAME" TEXT;\n'
        'alter table public.incoming_documents add column if not exists "RETRY_COUNT" integer default 0;\n'
        'alter table public.incoming_documents add column if not exists "created_at" timestamptz default now();\n'
        'alter table public.other_table add column if not exists "UNRELATED" TEXT;\n'
    )
    got_cols = table_columns(frag, "incoming_documents")
    want_cols = {"ID", "NAME", "RETRY_COUNT"}  # created_at excluded, other_table's column excluded
    ok = got_cols == want_cols
    bad += 0 if ok else 1
    print(f"  [{'ok ' if ok else 'FAIL'}] schema.sql column parser: got {sorted(got_cols)}"
          + ("" if ok else f" != expected {sorted(want_cols)}"))

    # ── Part 2 self-tests: prove the CALLER direction can both fire and stay quiet. A gate only
    #    ever observed passing has not been tested (GATES.md, "Adding a gate", step 3).
    trig = {"type": "n8n-nodes-base.executeWorkflowTrigger",
            "parameters": {"inputSource": "jsonExample",
                            "jsonExample": json.dumps({"ID": None, "COMPANY_ID": None})}}

    def _caller(target, value):
        return {"type": "n8n-nodes-base.executeWorkflow",
                "parameters": {"workflowId": {"value": target},
                                "workflowInputs": {"value": value}}}

    CALLER_TESTS = [
        ("caller sends an undeclared field (the real indoxDocGet01/TYPE bug)",
         {"target.json": {"id": "tgt", "nodes": [trig]},
          "caller.json": {"id": "c", "nodes": [_caller("tgt", {"ID": "=x", "TYPE": "SHIPMENT"})]}},
         True),
        ("caller sends only declared fields",
         {"target.json": {"id": "tgt", "nodes": [trig]},
          "caller.json": {"id": "c", "nodes": [_caller("tgt", {"ID": "=x", "COMPANY_ID": "=y"})]}},
         False),
        ("target trigger is passthrough — nothing is dropped, must not flag",
         {"target.json": {"id": "tgt", "nodes": [{"type": "n8n-nodes-base.executeWorkflowTrigger",
                                                   "parameters": {"inputSource": "passthrough"}}]},
          "caller.json": {"id": "c", "nodes": [_caller("tgt", {"ANYTHING": "=1"})]}},
         False),
        ("expression-valued workflowId is not statically knowable — must not flag",
         {"target.json": {"id": "tgt", "nodes": [trig]},
          "caller.json": {"id": "c", "nodes": [{"type": "n8n-nodes-base.executeWorkflow",
              "parameters": {"workflowId": {"value": "={{ $json.wf }}"},
                              "workflowInputs": {"value": {"TYPE": "x"}}}}]}},
         False),
        ("envelope control fields are ignored, not reported as drops",
         {"target.json": {"id": "tgt", "nodes": [trig]},
          "caller.json": {"id": "c", "nodes": [_caller("tgt", {"ID": "=x", "_be": "supabase"})]}},
         False),
    ]
    for label, docs, should_flag in CALLER_TESTS:
        got = bool(caller_findings(docs))
        ok = got == should_flag
        bad += 0 if ok else 1
        print(f"  [{'ok ' if ok else 'FAIL'}] "
              f"{'flagged' if got else 'clean  ':<8} "
              f"({'must flag' if should_flag else 'must be clean'}): {label}")

    total = len(SELF_TEST) + 1 + len(CALLER_TESTS)
    print(f"\nG39 self-test: {total - bad}/{total} passed")
    return 1 if bad else 0


# ─────────────────────────────────────────────────────────────────────────────
# PART 3 — the LIVE direction: does the RUNNING n8n instance declare what the repo says?
#
# WHY THIS EXISTS, AND WHY PARTS 1-2 CANNOT COVER IT. Parts 1 and 2 read the repo. That is the right
# scope for a CI gate — it must work in a fresh clone with no stack. But it means a GREEN GATE PROVES
# NOTHING ABOUT PRODUCTION, and on 2026-08-06 that gap was live and costly:
#
#   committed indoxDocBatchUpsert01 trigger : 96 fields, includes `priority_sync`
#   LIVE n8n indoxDocBatchUpsert01 trigger  : 95 fields, `priority_sync` ABSENT
#   public.incoming_documents               : priority_sync non-null on 3 of 6,341 rows
#
# The repo had already been fixed; the fix had never been pushed. Parts 1-2 pass, `schema.sql` has
# the column, and the running system silently discards it on every single write. Only a check
# against `workflow_entity` can see that — this is the "verify as the real principal" rule: the
# thing that runs is the thing to measure.
#
# Opt-in (`--live`) because it needs docker + a running stack, so it can never be the default for
# CI. Intended for the ops loop / post-push verification, which is exactly when it matters.
def live_trigger_schemas() -> dict[str, set[str]] | None:
    """workflow id -> declared trigger field set, read from the RUNNING n8n's workflow_entity.
    Returns None (with a printed reason) when the stack isn't reachable — never raises, because a
    missing stack must not be reported as 'no drift'."""
    import subprocess
    env = {"DOCKER_HOST": "unix:///run/bbox-docker.sock", "PATH": os.environ.get("PATH", "")}
    try:
        ps = subprocess.run(["docker", "ps", "--format", "{{.Names}}"],
                            capture_output=True, text=True, timeout=30, env=env)
        pg = next((n for n in ps.stdout.split() if n.startswith("n8n-postgres-")), None)
        if not pg:
            print("  live check SKIPPED: no n8n-postgres-* container running.")
            return None
        out = subprocess.run(
            ["docker", "exec", pg, "psql", "-U", "hacohen", "-d", "n8n", "-tAc",
             'select id || E\'\\t\' || nodes::text from workflow_entity'],
            capture_output=True, text=True, timeout=120, env=env)
        if out.returncode != 0:
            print(f"  live check SKIPPED: psql failed: {out.stderr.strip()[:200]}")
            return None
    except (OSError, subprocess.SubprocessError) as e:
        print(f"  live check SKIPPED: {e}")
        return None

    live: dict[str, set[str]] = {}
    for line in out.stdout.splitlines():
        if "\t" not in line:
            continue
        wid, blob = line.split("\t", 1)
        try:
            nodes = json.loads(blob)
        except ValueError:
            continue
        res = trigger_schema_fields({"nodes": nodes})
        if res is not None:
            live[wid] = res[0]
    return live


def live_findings(docs: dict[str, dict]) -> list[tuple[str, list[str], list[str]]] | None:
    """(workflow id, in-repo-not-live, in-live-not-repo) per drifted workflow, or None if skipped."""
    live = live_trigger_schemas()
    if live is None:
        return None
    repo = declared_schemas(docs)
    out = []
    for wid, (fields, _mode, _rel) in sorted(repo.items()):
        if wid not in live:
            continue                     # not deployed, or live is passthrough — different concern
        only_repo = sorted(fields - live[wid])
        only_live = sorted(live[wid] - fields)
        if only_repo or only_live:
            out.append((wid, only_repo, only_live))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true")
    ap.add_argument("--live", action="store_true",
                     help="ALSO diff every explicit-schema trigger against the RUNNING n8n "
                          "instance (needs docker + a live stack; see PART 3)")
    a = ap.parse_args()
    if a.self_test:
        return self_test()

    findings = []
    for wf_rel, (schema_rel, table) in UPSERT_TARGETS.items():
        wf_path, schema_path = REPO / wf_rel, REPO / schema_rel
        if not wf_path.exists():
            findings.append((wf_rel, None, None, f"blueprint file not found: {wf_rel}"))
            continue
        if not schema_path.exists():
            findings.append((wf_rel, None, None, f"schema file not found: {schema_rel}"))
            continue
        try:
            doc = load_blueprint(wf_path)
        except (OSError, ValueError) as e:
            findings.append((wf_rel, None, None, f"could not parse {wf_rel}: {e}"))
            continue
        result = trigger_schema_fields(doc)
        if result is None:
            findings.append((wf_rel, None, None,
                              "no explicit-schema executeWorkflowTrigger found (passthrough, or "
                              "trigger shape changed) — UPSERT_TARGETS entry may be stale"))
            continue
        fields, mode = result
        columns = table_columns(schema_path.read_text(encoding="utf-8"), table)
        if not columns:
            findings.append((wf_rel, None, None,
                              f"no columns found for public.{table} in {schema_rel} — "
                              f"UPSERT_TARGETS entry may be stale"))
            continue
        missing, extra = diff(fields, columns)
        if missing or extra:
            findings.append((wf_rel, sorted(missing), sorted(extra),
                              f"trigger mode={mode}, table=public.{table}"))

    # ── Part 2: the caller direction, across every explicit-schema trigger in the repo ──
    docs: dict[str, dict] = {}
    for pattern in BLUEPRINT_GLOBS:
        for path in sorted(REPO.glob(pattern)):
            try:
                d = load_blueprint(path)
            except (OSError, ValueError):
                continue
            if isinstance(d, dict):
                docs[str(path.relative_to(REPO)).replace("\\", "/")] = d
    n_explicit = len(declared_schemas(docs))
    drops = caller_findings(docs)

    # ── Part 3: optional live-instance drift ──
    live_drift = None
    if a.live:
        print("Live trigger-schema drift (running n8n vs this checkout):")
        live_drift = live_findings(docs)
        if live_drift is None:
            print("  NOT VERIFIED — the live instance was not reachable. This is not a pass.\n")
        elif not live_drift:
            print(f"  OK — every deployed explicit-schema trigger matches the blueprint.\n")
        else:
            print(f"  DRIFT — {len(live_drift)} deployed trigger(s) differ from this checkout:")
            for wid, only_repo, only_live in live_drift:
                print(f"    {wid}")
                if only_repo:
                    print(f"      in blueprint but NOT LIVE (discarded in production right now): "
                          f"{only_repo}")
                if only_live:
                    print(f"      live but not in the blueprint (a push would REMOVE it): {only_live}")
            print("    Fix: push the blueprint (`bbox n8n push`). Until then production silently\n"
                  "    discards every value sent for the fields listed as 'NOT LIVE'.\n")

    if not findings and not drops:
        print(f"G39 PASS — {len(UPSERT_TARGETS)} executeWorkflowTrigger schema(s) match the table "
              f"they upsert into, and no caller passes an undeclared field to any of the "
              f"{n_explicit} explicit-schema trigger(s).")
        return 0

    if drops:
        print(f"G39 FAIL — {len(drops)} call site(s) pass a field the target trigger does not "
              f"declare (silently dropped before any node runs):\n")
        for wid, wf_rel, caller_rel, dropped in drops:
            print(f"  {caller_rel}")
            print(f"      calls {wid} ({wf_rel})")
            print(f"      field(s) discarded at the trigger: {dropped}")
        print(
            "\n  n8n filters the caller's payload down to the trigger's declared field names BEFORE\n"
            "  the sub-workflow's first node runs. There is no error and no warning — the field is\n"
            "  simply absent from $json. Either add the field to the target trigger's schema, or\n"
            "  stop sending it if the caller is what's wrong.\n"
        )
        if findings:
            print()

    if not findings:
        return 1

    print(f"G39 FAIL — {len(findings)} trigger/table schema mismatch(es):\n")
    for wf_rel, missing, extra, note in findings:
        print(f"  {wf_rel}")
        print(f"      {note}")
        if missing:
            print(f"      table column(s) the trigger silently drops: {missing}")
        if extra:
            print(f"      trigger field(s) with no matching column:   {extra}")
    print(
        "\n  A table column missing from the trigger's schema means every caller's value for that\n"
        "  field is discarded before the sub-workflow ever sees it — no error, just gone (this is\n"
        "  exactly how NEXT_RETRY_AT ended up populated on 0 of 6,207 rows). Add the missing field(s)\n"
        "  to the trigger's jsonExample / fields list, or to the schema.sql migration if the trigger\n"
        "  is right and the table definition is what's stale."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
