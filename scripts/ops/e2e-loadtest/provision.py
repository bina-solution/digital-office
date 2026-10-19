#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""provision.py — one-time setup for the E2E load-test harness. Idempotent.

1. Creates local (drive_local) folders for the second source path: e2e-loadtest/{gdoc,bs} x
   {to_sync,synced,failed,in_progress} — via apps/drive's own local engine, ALWAYS with an
   explicit connection_id override (drive_local-19213e58, the "admin" local profile) so this
   NEVER touches the bound connection, which on this deployment today is the real Google
   service account (drive_google_service_account-ea660043 — confirmed live via GET /readyz).
2. Adds three new public.settings.sync_registry entries (source/config only, not documents —
   this deployment already carries hand-written registry rows like "mail-private" that were
   never created via the validated /sync/registry API, so this script writes the same way):
     e2e-mail          (source: gmail, connection_id: mail_imap_local-<admin>, mirrors "mail-private")
     e2e-drive-gdoc    (source: drive, connection: drive_local-<admin>, mirrors "drive-gdoc")
     e2e-drive-bs      (source: drive, connection: drive_local-<admin>, mirrors "drive-bs", type_hint BALANCE_SHEET)
   Snapshots sync_registry to <outdir>/sync_registry.before.json BEFORE writing, and
   sync_registry.after.json after — the non-negotiable snapshot/diff.
3. Writes <outdir>/provision.json — the resolved connection ids + folder ids gen_corpus.py needs.

Run inside WSL with DOCKER_HOST=unix:///run/bbox-docker.sock exported.
Usage: python3 provision.py --outdir <dir> [--deployment-name shlomo-laptop]
"""
import argparse
import json
import os
import subprocess
import sys

MARKER_PREFIX = "e2elt"


def sh(cmd, timeout=30):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)


def dexec_py(dn_container, code, timeout=30):
    r = sh(["docker", "exec", dn_container, "python3", "-c", code], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"docker exec {dn_container} failed: {r.stderr[:500]}")
    return r.stdout.strip()


def psql(dn, sql, timeout=30):
    r = sh(["docker", "exec", f"supabase-db-{dn}", "psql", "-U", "postgres", "-d", "postgres", "-tAc", sql], timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"psql failed: {r.stderr[:500]}")
    return r.stdout.strip()


def drive_call(dn, method, path, body=None, connection_id=None):
    """One-shot HTTP call to the drive service, executed via python3 urllib INSIDE the drive
    container (no curl there) so it hits http://localhost:8975 directly."""
    b = dict(body or {})
    if connection_id:
        b["connection_id"] = connection_id
    payload = json.dumps(b)
    code = f'''
import urllib.request, json
req = urllib.request.Request("http://localhost:8975{path}", data={payload!r}.encode(),
    headers={{"Content-Type":"application/json"}}, method={method!r})
try:
    r = urllib.request.urlopen(req, timeout=15)
    print(r.read().decode())
except urllib.error.HTTPError as e:
    print(json.dumps({{"_http_error": e.code, "body": e.read().decode()}}))
'''
    out = dexec_py(f"drive-{dn}", code)
    return json.loads(out.splitlines()[-1])


def ensure_folder(dn, name, parent, connection_id, cache):
    key = (parent, name)
    if key in cache:
        return cache[key]
    r = drive_call(dn, "POST", "/api/folders", {"name": name, "parent": parent or ""}, connection_id)
    fid = (r.get("folder") or {}).get("id") if isinstance(r.get("folder"), dict) else r.get("id")
    if not fid:
        # might already exist — list and find by name/parent
        listing = drive_call(dn, "GET", "/api/folders", {}, connection_id)
        for f in listing.get("folders", []):
            if f.get("name") == name and (f.get("parent") or "") == (parent or ""):
                fid = f.get("id")
                break
    if not fid:
        raise RuntimeError(f"could not create/find folder {name!r} under {parent!r}: {r}")
    cache[key] = fid
    return fid


def read_registry(dn):
    raw = psql(dn, "select value from public.settings where key='sync_registry'")
    try:
        return json.loads(raw) if raw else []
    except Exception:
        return []


def write_registry(dn, entries):
    payload = json.dumps(entries, ensure_ascii=False)
    # write via a temp SQL file to avoid shell-quoting hell with Hebrew + quotes
    sql = ("update public.settings set value=$E2ELT$" + payload + "$E2ELT$, updated_at=now() "
           "where key='sync_registry'")
    r = sh(["docker", "exec", "-i", f"supabase-db-{dn}", "psql", "-U", "postgres", "-d", "postgres", "-c", sql], timeout=30)
    if r.returncode != 0 or (r.stderr or "").strip():
        raise RuntimeError(f"registry write failed: {r.stderr[:500]}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--deployment-name", default="shlomo-laptop")
    ap.add_argument("--force", action="store_true", help="re-provision even if e2e-* entries already exist")
    a = ap.parse_args()
    dn = a.deployment_name
    os.makedirs(a.outdir, exist_ok=True)

    # ---- 1. drive local profile / connection ----
    conns = dexec_py(f"drive-{dn}",
        "import urllib.request,json; print(urllib.request.urlopen('http://localhost:8975/connections',timeout=10).read().decode())")
    conns = json.loads(conns)
    admin_local = next((c["id"] for c in conns["connections"]
                        if c.get("engine") == "drive_local" and c.get("profile_id") == "admin"), None)
    if not admin_local:
        sys.exit("could not resolve drive_local admin connection_id from /connections")
    print(f"[provision] drive_local admin connection_id = {admin_local}")
    bound = conns.get("bound")
    print(f"[provision] drive's currently BOUND connection = {bound} "
          f"({'SAFE (local)' if 'drive_local' in str(bound) else 'REAL GOOGLE — harness will still always override with connection_id'})")

    mail_profiles = dexec_py(f"mailapi-{dn}",
        "import urllib.request,json; print(urllib.request.urlopen('http://localhost:8970/engine/profiles',timeout=10).read().decode())")
    mail_profiles = json.loads(mail_profiles)
    admin_mail = next((p["connection_id"] for p in mail_profiles["profiles"] if p["id"] == "admin"), None)
    if not admin_mail:
        sys.exit("could not resolve mail_imap_local admin connection_id from /engine/profiles")
    print(f"[provision] mail_imap_local admin connection_id = {admin_mail}")

    # ---- 2. local drive folders ----
    cache = {}
    root = ensure_folder(dn, "e2e-loadtest", "", admin_local, cache)
    folders = {}
    for bucket in ("gdoc", "bs"):
        bucket_root = ensure_folder(dn, bucket, root, admin_local, cache)
        for sub in ("to_sync", "synced", "failed", "in_progress"):
            folders[f"{bucket}_{sub}"] = ensure_folder(dn, sub, bucket_root, admin_local, cache)
    archive_root = ensure_folder(dn, "mail-archive", root, admin_local, cache)
    print("[provision] local drive folders:", json.dumps(folders, ensure_ascii=False))

    # ---- 3. sync_registry snapshot + append ----
    before = read_registry(dn)
    with open(os.path.join(a.outdir, "sync_registry.before.json"), "w", encoding="utf-8") as f:
        json.dump(before, f, ensure_ascii=False, indent=1)
    print(f"[provision] snapshotted sync_registry BEFORE ({len(before)} entries) -> sync_registry.before.json")

    names_present = {e.get("name") for e in before}
    new_entries = {
        "e2e-mail": {
            "name": "e2e-mail", "engine": "v3", "source": "gmail",
            "connection_id": admin_mail,
            "v3_query": "has:attachment newer_than:9m", "search_extra": "has:attachment newer_than:9m",
            "dest_folder": archive_root, "source_type": "MAIL_ATTACHMENT", "message_link_base": "",
            "batch": {"take": 25, "page_size": 50, "schedule_min": 15},
            "type_hint": None, "skip_inline_attachments": True,
            "att_exts": ["pdf", "doc", "docx", "txt", "rtf", "odt", "pages", "md", "csv", "xls", "xlsx", "jpg", "jpeg", "png"],
            "att_max_bytes": 10485760, "enabled": True, "fallback_type": None, "drive_profile_id": "admin",
        },
        "e2e-drive-gdoc": {
            "name": "e2e-drive-gdoc", "source": "drive", "engine": "v3",
            "connection": admin_local, "processor_wf": "SyncProcGDoc0001", "projection": "on",
            "enabled": True, "type_hint": None, "fallback_type": None,
            "batch": {"take": 50, "chunk": 25, "timeout_min": 14, "schedule_min": 15},
            "pairs": [{"to_sync": folders["gdoc_to_sync"], "synced": folders["gdoc_synced"],
                       "failed": folders["gdoc_failed"], "in_progress": folders["gdoc_in_progress"],
                       "from": folders["gdoc_to_sync"], "to": folders["gdoc_synced"],
                       "failed_to": folders["gdoc_failed"]}],
        },
        "e2e-drive-bs": {
            "name": "e2e-drive-bs", "source": "drive", "engine": "v3",
            "connection": admin_local, "processor_wf": "SyncProcBS000001", "projection": "on",
            "enabled": True, "type_hint": "BALANCE_SHEET", "fallback_type": "BALANCE_SHEET",
            "batch": {"take": 50, "chunk": 25, "timeout_min": 14, "schedule_min": 15},
            "pairs": [{"to_sync": folders["bs_to_sync"], "synced": folders["bs_synced"],
                       "failed": folders["bs_failed"], "in_progress": folders["bs_in_progress"],
                       "from": folders["bs_to_sync"], "to": folders["bs_synced"],
                       "failed_to": folders["bs_failed"]}],
        },
    }
    after = [e for e in before]
    for name, entry in new_entries.items():
        if name in names_present:
            if not a.force:
                print(f"[provision] '{name}' already in registry — leaving as-is (use --force to replace)")
                continue
            after = [e for e in after if e.get("name") != name]
        after.append(entry)
    write_registry(dn, after)
    after_check = read_registry(dn)
    with open(os.path.join(a.outdir, "sync_registry.after.json"), "w", encoding="utf-8") as f:
        json.dump(after_check, f, ensure_ascii=False, indent=1)
    print(f"[provision] wrote sync_registry AFTER ({len(after_check)} entries) -> sync_registry.after.json")

    out = {
        "drive_connection_id": admin_local,
        "mail_connection_id": admin_mail,
        "drive_folders": {"gdoc_to_sync": folders["gdoc_to_sync"], "bs_to_sync": folders["bs_to_sync"],
                           **folders},
        "archive_folder": archive_root,
        "e2e_root_folder": root,
    }
    with open(os.path.join(a.outdir, "provision.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("[provision] done ->", os.path.join(a.outdir, "provision.json"))


if __name__ == "__main__":
    main()
