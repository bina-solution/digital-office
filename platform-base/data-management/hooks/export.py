#!/usr/bin/env python3
#: bbox data export [--app ID] [--mode full|config] [--quiesce] [--resume DIR] — snapshot everything a zip would miss
"""Start an export through the data-management service and follow it.

    A CLIENT of the API. The archive format, the inventory and the consistency rules all live
    server-side; this starts a job and prints its log. Deliberately no local fallback: an export
    that could run two ways would eventually produce two different archives.
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
    ap = argparse.ArgumentParser(prog="bbox data export")
    ap.add_argument("--mode", choices=("full", "config"), default="full",
                    help="full = incl. execution history and OCR caches; config = without them")
    ap.add_argument("--quiesce", action="store_true",
                    help="stop the writers for a cross-store consistent snapshot. Right for a "
                         "MIGRATION, wrong for a routine backup of a live system.")
    ap.add_argument("--no-follow", action="store_true", help="return the job id and exit")
    ap.add_argument("--app", metavar="ID",
                    help="export ONLY this app's declared stores — an archive that can be imported "
                         "into a different deployment on its own")
    ap.add_argument("--resume", metavar="DIR",
                    help="continue a previous run (a directory name under the archive root)")
    a = ap.parse_args()

    q = f"?mode={a.mode}&quiesce={'true' if a.quiesce else 'false'}"
    if a.app:
        q += f"&app={quote(a.app)}"
    if a.resume:
        q += f"&resume={quote(a.resume)}"
    started = call("POST", "/api/export" + q)
    job = started["job"]
    print(f"[bbox data export] job {job}  mode={started['mode']}  "
          f"quiesce={started['quiesce']}"
          + (f"  app={started['app']}" if started.get("app") else "")
          + f"  out={started['out']}")
    if a.no_follow:
        print(f"[bbox data export] follow with: bbox data jobs {job}")
        return 0

    # ABSOLUTE cursor, not len(log). The server keeps only the last 400 lines, so len() plateaus and
    # a length-based cursor goes permanently silent partway through a long export.
    seen = 0
    while True:
        st = call("GET", f"/api/jobs/{job}?tail=400")
        log, first = (st.get("log") or []), st.get("first_seq", 0)
        if first > seen and seen:
            print(f"[bbox data export] … {first - seen} line(s) scrolled past between polls")
        for line in log[max(0, seen - first):]:
            print(line)
        seen = max(seen, first + len(log))
        if st.get("state") in ("done", "failed"):
            rc = st.get("returncode")
            print(f"[bbox data export] {st['state']}  rc={rc}")
            return 0 if st["state"] == "done" else 1
        time.sleep(3)


if __name__ == "__main__":
    sys.exit(main())
