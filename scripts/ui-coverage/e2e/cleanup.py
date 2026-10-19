#!/usr/bin/env python3
"""
cleanup.py — remove everything the E2E suites in this directory create.

Every object these suites make is named via common.qa_name()/QA_TAG, i.e. it always contains the
literal substring "QA_E2E_" somewhere in its name/subject/label. This script finds and deletes
exactly those rows/files — nothing else. It is deliberately conservative: every DELETE is scoped
with a `LIKE '%QA_E2E_%'` (or equivalent) predicate, never a bare TRUNCATE, and it prints what it
removed so a run is auditable after the fact.

Covers:
  - drive_files / drive_folders  (test_drive.py)
  - public.companies              (test_indox.py)
  - public.settings.sync_registry entries (test_indox.py — pipe cards)
  - public.incoming_documents     (test_indox.py / test_indox_regressions.py uploads)
  - local mailbox messages tagged QA_E2E_ in admin@local.test / user2@local.test (test_mail.py) —
    deleted via mailapi (IMAP STORE \\Deleted + EXPUNGE), never by touching mailserver files
    directly.

Does NOT touch: my-docs, connections, machine, notifications, any-concurrency, console, or
anything without the QA_E2E_ tag. Never touches the real client mailbox
(mail_imap_app_password-51185288 / person9@example.com) — mail cleanup only ever calls mailapi with
the LOCAL engine's own connection_ids.

Run:
    python3 scripts/ui-coverage/e2e/cleanup.py            # delete everything tagged
    python3 scripts/ui-coverage/e2e/cleanup.py --dry-run  # just report what would be deleted
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import psql, psql_rows, mailapi_call  # noqa: E402

# These suites print Hebrew document text. On a host whose stdout is not already UTF-8 that
# raises UnicodeEncodeError on the first Hebrew character, and the traceback reads as a
# test failure rather than an encoding one. Same guard the gates use. (G10)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")


DRY = "--dry-run" in sys.argv


def run_sql(label: str, select_sql: str, delete_sql: str):
    rows = psql_rows(select_sql)
    n = len(rows)
    print(f"[cleanup] {label}: {n} row(s) tagged QA_E2E_")
    if n and not DRY:
        psql(delete_sql)
        print(f"[cleanup] {label}: deleted")
    elif n and DRY:
        for r in rows[:10]:
            print("   ", r)


def clean_drive():
    run_sql(
        "drive_files",
        "SELECT id, name FROM drive_files WHERE name LIKE '%QA_E2E_%';",
        "DELETE FROM drive_files WHERE name LIKE '%QA_E2E_%';",
    )
    run_sql(
        "drive_folders",
        "SELECT id, name FROM drive_folders WHERE name LIKE '%QA_E2E_%';",
        "DELETE FROM drive_folders WHERE name LIKE '%QA_E2E_%';",
    )


def clean_companies():
    # ANCHORED to the start of the name, not `%QA_E2E_%` anywhere in it. qa_name() always builds
    # `QA_E2E_<run>__<label>`, so every company this suite creates starts with the tag — while a
    # REAL company whose name merely CONTAINS it is, by definition, one a test corrupted rather
    # than created. That is not hypothetical: on 2026-08-11 test_indox.py's grid edit appended its
    # tag to live company id=1, turning 'SV3S Sender Co' into
    # 'SV3S Sender CoQA_E2E_..._company'. The unanchored predicate below would have deleted that
    # customer row outright, and a cleanup pass that destroys real data because a test misfired is
    # far worse than one that leaves a stray QA row behind. Anchoring makes the destructive case
    # impossible; a corrupted row now survives cleanup and stays visible to be repaired.
    run_sql(
        "companies",
        "SELECT id, \"שם חברה\" FROM public.companies WHERE \"שם חברה\" LIKE 'QA_E2E_%';",
        "DELETE FROM public.companies WHERE \"שם חברה\" LIKE 'QA_E2E_%';",
    )


def clean_incoming_documents():
    run_sql(
        "incoming_documents",
        "SELECT \"ID\", \"NAME\" FROM public.incoming_documents WHERE \"NAME\" LIKE '%QA_E2E_%';",
        "DELETE FROM public.incoming_documents WHERE \"NAME\" LIKE '%QA_E2E_%';",
    )


def clean_sync_registry():
    import json
    out = psql("SELECT value FROM public.settings WHERE key='sync_registry';").strip()
    if not out:
        print("[cleanup] sync_registry: empty/missing, nothing to do")
        return
    try:
        arr = json.loads(out)
    except Exception as e:
        print(f"[cleanup] sync_registry: could not parse ({e}), leaving untouched")
        return
    tagged = [e for e in arr if isinstance(e, dict) and "QA_E2E_" in str(e.get("name", ""))]
    print(f"[cleanup] sync_registry: {len(tagged)} entr(y/ies) tagged QA_E2E_ "
          f"of {len(arr)} total")
    if tagged and not DRY:
        kept = [e for e in arr if e not in tagged]
        esc = json.dumps(kept).replace("'", "''")
        psql(f"UPDATE public.settings SET value = '{esc}' WHERE key='sync_registry';")
        print("[cleanup] sync_registry: tagged entries removed, everything else left untouched")
    elif tagged:
        for e in tagged:
            print("   ", e.get("name"))


def clean_mail():
    status, data = mailapi_call("/engine/profiles")
    if status != 200 or not data:
        print(f"[cleanup] mail: could not reach mailapi ({status}) — skipping")
        return
    for p in data.get("profiles", []):
        cid = p.get("connection_id")
        if not cid:
            continue
        st, sd = mailapi_call("/search", "POST", {
            "connection_id": cid, "folder": "INBOX", "query": "QA_E2E_", "limit": 100,
        })
        msgs = (sd or {}).get("messages", []) if st == 200 else []
        print(f"[cleanup] mail[{p.get('id')}]: {len(msgs)} message(s) tagged QA_E2E_")
        if msgs and not DRY:
            for m in msgs:
                mailapi_call("/labels/add", "POST", {
                    "connection_id": cid, "id": m.get("uid") or m.get("id"), "label": "\\Deleted",
                })
            print(f"[cleanup] mail[{p.get('id')}]: marked deleted (expunge happens on the "
                  f"backend's normal IMAP cycle)")


def main():
    print(f"[cleanup] mode: {'DRY RUN — nothing will be deleted' if DRY else 'DELETING tagged QA_E2E_ data'}")
    clean_drive()
    clean_companies()
    clean_sync_registry()
    clean_incoming_documents()
    clean_mail()
    print("[cleanup] done")


if __name__ == "__main__":
    main()
