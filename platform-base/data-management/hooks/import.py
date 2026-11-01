#!/usr/bin/env python3
#: bbox data import <DIR> [--app ID] [--force] — restore an archive onto this machine
"""Restore through the data-management service and follow it.

    A CLIENT of the API, like every other verb here. The archive format, the refusals and the
    fact-comparison at the end all live server-side in scripts/deployment-archive.py, because export
    and import must agree byte-for-byte and a second implementation of either is how they stop
    agreeing.

WHAT THIS REFUSES, AND WHY THAT IS THE FEATURE

    The archiver will not restore into the deployment an archive came FROM without --force. The
    compose project name is the CLONE DIRECTORY BASENAME, not DEPLOYMENT_NAME, so two checkouts of
    this repo in identically-named directories are the same project to docker — and a restore would
    overwrite the volumes of the very deployment being backed up. It also refuses when the archive's
    N8N_ENCRYPTION_KEY fingerprint does not match this host's, because that particular restore
    reports success and yields credential rows that cannot be decrypted.
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _client import call                                   # noqa: E402


def main():
    ap = argparse.ArgumentParser(prog="bbox data import")
    ap.add_argument("dir", help="archive directory (as the service sees it, e.g. /archives/<name>)")
    ap.add_argument("--app", metavar="ID", help="restore ONLY this app's artifacts from the archive")
    ap.add_argument("--force", action="store_true",
                    help="restore even into the deployment this archive came from, or with a "
                         "mismatched encryption key. Both refusals exist for a reason — read them "
                         "before overriding.")
    ap.add_argument("--no-follow", action="store_true", help="return the job id and exit")
    a = ap.parse_args()

    q = f"?path={quote(a.dir)}"
    if a.app:
        q += f"&app={quote(a.app)}"
    if a.force:
        q += "&force=true"
    started = call("POST", "/api/import" + q)
    job = started["job"]
    print(f"[bbox data import] job {job}  path={started['path']}"
          + (f"  app={started['app']}" if started.get("app") else ""))
    if a.no_follow:
        return 0

    # Absolute cursor, not len(log): the server keeps a bounded tail, so a length-based cursor goes
    # silent partway through a long restore.
    seen = 0
    while True:
        st = call("GET", f"/api/jobs/{job}?tail=400")
        log, first = (st.get("log") or []), st.get("first_seq", 0)
        if first > seen and seen:
            print(f"[bbox data import] … {first - seen} line(s) scrolled past between polls")
        for line in log[max(0, seen - first):]:
            print(line)
        seen = max(seen, first + len(log))
        if st.get("state") in ("done", "failed"):
            rc = st.get("returncode")
            print(f"[bbox data import] {st['state']}  rc={rc}")
            return 0 if st["state"] == "done" else 1
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
