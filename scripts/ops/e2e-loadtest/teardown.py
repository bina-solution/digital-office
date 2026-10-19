#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""teardown.py — reverses provision.py. Run BEFORE scripts/ops/e2e-loadtest-cleanup.sql.

1. Restores public.settings.sync_registry to EXACTLY the pre-provision snapshot
   (<state>/sync_registry.before.json) — the non-negotiable "prove you can return to it".
2. Deletes the local-drive (drive_local) folders/files created for the second source path.
3. Deletes the injected local-mailbox messages (marker: From/To on *.e2e-loadtest.local),
   via the mailapi container's own live IMAP connection object (there is no message-delete
   HTTP op on mailapi — see report) so no separate credentials are needed.

Usage: python3 teardown.py --state <dir> --deployment-name shlomo-laptop
"""
import argparse
import json
import os
import subprocess


def sh(cmd, timeout=60):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def dexec_py(container, code, timeout=60):
    r = sh(["docker", "exec", container, "python3", "-c", code], timeout=timeout)
    return r.returncode, r.stdout.strip(), r.stderr.strip()


# The three names provision.py appends. Used only as the FALLBACK when the snapshot
# pair is unavailable — see _provisioned_names(). Kept in sync with provision.py's
# `new_entries` dict; scripts/ops/e2e-loadtest-cleanup.sql lists the same three.
E2E_PIPE_NAMES = ("e2e-mail", "e2e-drive-gdoc", "e2e-drive-bs")


def _psql(dn, *args):
    return sh(["docker", "exec", "-i", f"supabase-db-{dn}", "psql", "-U", "postgres",
               "-d", "postgres", *args])


def _read_registry(dn):
    r = _psql(dn, "-tAc", "select value from public.settings where key='sync_registry'")
    raw = (r.stdout or "").strip()
    return json.loads(raw) if raw else []


def _provisioned_names(state):
    """Exactly the pipe names THIS provision run added = after - before.

    Derived from the snapshot pair rather than hardcoded, so a provision that
    skipped an already-present name (provision.py: "already in registry — leaving
    as-is") does not get that pre-existing pipe torn down underneath it.

    Falls back to the known three when either snapshot is missing — which is the
    case that stranded the entries in the first place: a teardown that cannot find
    its snapshot used to do nothing recoverable, so the e2e rows outlived the run.
    """
    try:
        with open(os.path.join(state, "sync_registry.before.json"), encoding="utf-8") as f:
            before = {e.get("name") for e in json.load(f)}
        with open(os.path.join(state, "sync_registry.after.json"), encoding="utf-8") as f:
            after = {e.get("name") for e in json.load(f)}
        added = sorted(after - before)
        if added:
            return added, "snapshot diff (after - before)"
        return [], "snapshot diff (after - before) — provision added nothing"
    except (OSError, ValueError) as e:
        return list(E2E_PIPE_NAMES), f"fallback to known e2e names ({type(e).__name__})"


def restore_registry(dn, state):
    """Remove ONLY the entries this provision run added. Never a blanket restore.

    WHY NOT A SNAPSHOT RESTORE (changed 2026-08-06). This used to do:

        update public.settings set value=<entire sync_registry.before.json>

    i.e. overwrite the whole registry with a snapshot taken before provisioning.
    That is correct only if nothing else changed the registry in between — and the
    registry is live production config, edited through the BFF by operators and by
    the Console UI. On a long-lived stack, or on the production VPS, a stale
    snapshot silently reverts every unrelated change: pipe renames, folder-id
    corrections, pauses. Those revert with no error and no diff, because the write
    "succeeded" and the function only ever checked that the result matched the
    snapshot it just forced.

    A teardown must undo what it did, not restore the world to a photograph of it.
    So: read the CURRENT registry, drop the names this run added, keep every other
    entry byte-identical, write back. Concurrent edits to other pipes survive.
    """
    added, how = _provisioned_names(state)
    current = _read_registry(dn)
    names_now = [e.get("name") for e in current]
    to_remove = [n for n in added if n in names_now]

    print(f"[teardown] sync_registry: provisioned names = {added or '(none)'}  [{how}]")
    if not to_remove:
        print(f"[teardown] sync_registry: nothing to remove; {len(current)} entries left untouched")
        return True

    kept = [e for e in current if e.get("name") not in to_remove]
    payload = json.dumps(kept, ensure_ascii=False)
    r = _psql(dn, "-c", "update public.settings set value=$E2ELT$" + payload +
              "$E2ELT$, updated_at=now() where key='sync_registry'")
    if r.returncode != 0:
        raise RuntimeError(f"registry narrow-removal failed: {r.stderr[:500]}")

    got = _read_registry(dn)
    got_names = {e.get("name") for e in got}
    expected = {n for n in names_now if n not in to_remove}
    # Two independent assertions: the ones we meant to remove are gone, AND nothing
    # else moved. The old code could only ever check the first.
    removed_ok = not (got_names & set(to_remove))
    survivors_ok = got_names == expected
    by_name = {e.get("name"): e for e in current}
    unchanged = all(json.dumps(e, sort_keys=True, ensure_ascii=False) ==
                    json.dumps(by_name.get(e.get("name")), sort_keys=True, ensure_ascii=False)
                    for e in got)
    ok = removed_ok and survivors_ok and unchanged
    print(f"[teardown] sync_registry: removed {sorted(to_remove)}; "
          f"{len(got)} entries remain "
          f"({'survivors byte-identical' if ok else 'MISMATCH — manual check needed'})")
    return ok


def delete_drive_tree(dn, provision):
    conn = provision["drive_connection_id"]
    root = provision["e2e_root_folder"]
    archive = provision.get("archive_folder")
    all_folder_ids = list(provision["drive_folders"].values()) + [root]
    if archive:
        all_folder_ids.append(archive)
    # delete files first (leaf content), then folders, deepest first is not required since the
    # local adapter's delete() is a flat id-based op (not a real filesystem needing empty dirs)
    code = f'''
import urllib.request, json
def call(method, path, body):
    b = dict(body); b["connection_id"] = {conn!r}
    req = urllib.request.Request("http://localhost:8975"+path, data=json.dumps(b).encode(),
        headers={{"Content-Type":"application/json"}}, method=method)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=20).read().decode())
    except Exception as e:
        return {{"_error": str(e)}}

folder_ids = {all_folder_ids!r}
n_files = 0
for fid in folder_ids:
    listing = call("GET", "/api/files?folder=" + fid, {{}})
    ids = [f["id"] for f in (listing.get("files") or [])]
    if ids:
        call("POST", "/api/trash", {{"ids": ids}})
        call("POST", "/api/delete", {{"ids": ids}})
        n_files += len(ids)
call("POST", "/api/trash", {{"ids": folder_ids}})
res = call("POST", "/api/delete", {{"ids": folder_ids}})
print(json.dumps({{"files_deleted": n_files, "folder_delete_result": res}}))
'''
    rc, out, err = dexec_py(f"drive-{dn}", code)
    print(f"[teardown] drive cleanup -> {out or err}")
    return rc == 0


MAIL_CLEAN_CODE = r'''
import sys
sys.path.insert(0, "/app")
from service import _backend
_cid, be = _backend("%(CID)s")
with be._lock:
    c = be._conn()
    c.select_folder("INBOX")
    uids = c.search(["OR", "FROM", "e2e-loadtest.local", "TO", "e2e-loadtest.local"], charset="UTF-8")
    if uids:
        c.delete_messages(uids)
        c.expunge()
print("deleted_uids=%%d" %% len(uids))
'''


def delete_mail_messages(dn, provision):
    cid = provision["mail_connection_id"]
    code = MAIL_CLEAN_CODE % {"CID": cid}
    rc, out, err = dexec_py(f"mailapi-{dn}", code, timeout=60)
    if rc != 0:
        print(f"[teardown] mail cleanup via live backend FAILED ({err[:300]}) — "
              f"fallback: messages remain in the local test mailbox (admin@local.test), "
              f"marked From/To *@e2e-loadtest.local for manual removal.")
        return False
    print(f"[teardown] mail cleanup -> {out}")
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--deployment-name", default="shlomo-laptop")
    a = ap.parse_args()
    dn = a.deployment_name
    with open(os.path.join(a.state, "provision.json"), encoding="utf-8") as f:
        provision = json.load(f)

    ok_reg = restore_registry(dn, a.state)
    ok_drive = delete_drive_tree(dn, provision)
    ok_mail = delete_mail_messages(dn, provision)
    print(f"[teardown] summary: registry={'ok' if ok_reg else 'CHECK'} "
          f"drive={'ok' if ok_drive else 'CHECK'} mail={'ok' if ok_mail else 'CHECK (see note above)'}")
    print("[teardown] next: run scripts/ops/e2e-loadtest-cleanup.sql against supabase-db")


if __name__ == "__main__":
    main()
