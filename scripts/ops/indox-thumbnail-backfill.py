#!/usr/bin/env python3
"""Backfill THUMBNAIL on rows the pipeline never rendered one for.

    python3 scripts/ops/indox-thumbnail-backfill.py --census          # counts only, no I/O
    python3 scripts/ops/indox-thumbnail-backfill.py --run 3           # do 3, measure the real rate
    python3 scripts/ops/indox-thumbnail-backfill.py --run 200 --commit

*** --run WITHOUT --commit WRITES NOTHING TO THE DATABASE. *** It downloads, renders and
uploads (so the timing is real) and then reports what it WOULD have stored.

CAVEAT, say it plainly: a dry run is NOT side-effect-free. The jpg is really rendered and
really uploaded to the local drive engine's `automations/thumbnails`; only the DB write is
skipped. So every dry-run document leaves an ORPHAN thumbnail file that no row points at.
Prefer a small `--run N --commit` over a large dry run — the work is identical and the
result is kept. Dry run is for proving the path, not for sizing.

════════════════════════════════════════════════════════════════════════════════
WHY THE GAP EXISTS — and why a backfill alone does NOT close it

apps/indox/app/incoming_documents/api/__init__.py:3914 records the cause in its own words:
indoxV2UploadApiTools01 short-circuits on an apitools `/docExists` HASH hit ("If Exists" ->
"Return") and never downloads the bytes on that path, so a document whose hash was already
uploaded produces NO thumbnail. Thumbnail rendering was folded into the upload step
(owner request, 2026-08-06); there is no separate thumbnail action to re-fire.

MEASURED 2026-08-06 at 6,405 rows — the gap is NOT historical, it is still opening:
    rows with a THUMBNAIL                                36
    rows without                                      6,369
    created in the last 24h                             255  <- of which only 27 got one (11%)
So ~89% of NEW documents still arrive without a thumbnail. Backfilling first would be the
mistake §6a of indox-column-consolidation.sql already names for HASH: "do that first —
otherwise any backfill is immediately re-diluted by the next document".

    ORDER: fix the writer (workflow change, needs `bbox n8n push`), THEN backfill.

════════════════════════════════════════════════════════════════════════════════
COST — measure it, do not assume it. Live figures 2026-08-06:

    backfillable (missing THUMBNAIL and has a LINK)             6,025
    NOT backfillable (no LINK at all — no bytes exist)            344
        183 BALANCE_SHEET per-line rows spawned from BS_EXTRACTED_LINES (they have no
            file of their own — the same class §6b exempts from the HASH backfill),
        122 legacy rows with SOURCE_TYPE null, 39 INVOICE.
    already tried and failed (THUMBNAIL_COMPLETED set, THUMBNAIL empty)  397
        fail-soft and TERMINAL by design (:3931) — re-running repeats a known failure,
        so --run skips them unless --retry-failed is passed.
    total download volume for the backfillable set              5.07 GiB (avg 913 KiB)

That traffic goes through the same apps/drive + apitools instances the live pipeline uses,
and apitools is the OCR bottleneck. Hence --run takes an explicit count and there is no
"--all": the size of the batch is a decision, not a default.

*** MEASURED, NOT ESTIMATED — 20 real documents, 2026-08-06 ~17:00Z, live stack ***

    7 of 20 rendered.  13 of 20 failed with `render_failed: ReadTimeout: timed out`
    after the full 90 s httpx timeout on apitools /pdfToJpeg.
    67.9 s per document averaged  ->  ~113 h serial for the 6,025 backfillable rows.

    The successes took 0.4-1.3 s to render. The failures took 90 s each and produced
    nothing. That bimodal split is queueing, not file size: the failures average 135 KiB
    and the successes 174 KiB, so the LARGER files are the ones that succeeded.
    /pdfToJpeg shares apitools with the OCR pipeline (4 concurrent slots), and this batch
    was simply losing the race for a slot 65% of the time.

    CONCLUSION: at current apitools capacity this backfill is NOT viable, and running it
    harder would take slots away from the OCR pipeline that is doing the work that
    actually matters. A thumbnail moves NO document toward STATUS='COMPLETED'.
    Do not schedule the full run until either apitools has spare capacity (off-peak, or
    more /pdfToJpeg concurrency) or the render is moved off apitools. Then fix the WRITER
    first, per the section above, or the backfill is re-diluted as it runs.

A thumbnail is explicitly "a nicety, never allowed to block or fail the document's real
pipeline" (:3927). It moves NO document toward STATUS='COMPLETED'. Sequence it accordingly.

════════════════════════════════════════════════════════════════════════════════
fileIdMode MUST be "url": extract_file_id (apps/drive/adapters/opsupport.py) parses a URL
only in that mode and passes every other mode through literally, which sends the whole
https:// string to Drive as a file id and 404s. Same trap indox-rehash-missing.py documents.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_CONTAINER = "supabase-db-shlomo-laptop"
DOCKER_SOCK = "unix:///run/bbox-docker.sock"
DRIVE_CONTAINER = "drive-shlomo-laptop"
DRIVE_PORT = 8975
INDOX_CONTAINER = "incoming-documents-shlomo-laptop"
INDOX_PORT = 8080
#: The blueprint's url_prefix, not the bare path. api/__init__.py:3602 reads it from
#: INCOMING_DOCS_API_PREFIX and defaults to "/incomingDocuments" — the running container
#: has exactly that value. Posting to the bare /documents/thumbnail returns 405, which
#: looks like "wrong method" and is really "no such route".
INDOX_PREFIX = "/incomingDocuments"
DEFAULT_CONNECTION = "drive_google_service_account-ea660043"

_SCOPE = ("from public.incoming_documents "
          "where coalesce(\"THUMBNAIL\",'') = '' and coalesce(\"LINK\",'') <> '' ")


def _sh(inner: str, timeout: int = 300) -> str:
    """Run a command in Linux, hopping through `wsl` when invoked from Windows.

    Status is read from the OUTER process. Never `$?` inside a `wsl bash -lc` string —
    that reports the wrapper's status and is always 0."""
    cmd = ["bash", "-lc", inner] if sys.platform.startswith("linux") else ["wsl", "bash", "-lc", inner]
    proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    if proc.returncode != 0:
        sys.exit(f"command failed rc={proc.returncode}: {proc.stderr.decode('utf-8','replace')[:400]}")
    return proc.stdout.decode("utf-8", "replace")


def psql(sql: str, timeout: int = 300) -> str:
    return _sh(f"docker -H {DOCKER_SOCK} exec -i {DB_CONTAINER} "
               f"psql -U postgres -d postgres -tAc {json.dumps(sql)}", timeout)


def container_ip(name: str) -> str:
    out = _sh(f"docker -H {DOCKER_SOCK} inspect -f "
              f"'{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}} {{{{end}}}}' {name}", 120)
    ips = out.split()
    if not ips:
        sys.exit(f"{name} has no network address — is the stack up?")
    return ips[0]


def census() -> None:
    q = ("select "
         "(select count(*) from public.incoming_documents) || '|' || "
         "(select count(*) from public.incoming_documents where coalesce(\"THUMBNAIL\",'') <> '') || '|' || "
         "(select count(*) from public.incoming_documents where coalesce(\"THUMBNAIL\",'') = '') || '|' || "
         "(select count(*) " + _SCOPE + ") || '|' || "
         "(select count(*) " + _SCOPE + "and coalesce(\"THUMBNAIL_COMPLETED\",'') <> '') || '|' || "
         "(select count(*) from public.incoming_documents "
         " where coalesce(\"THUMBNAIL\",'') = '' and coalesce(\"LINK\",'') = '')")
    total, has, missing, backfillable, tried, nolink = psql(q).strip().split("|")
    print(f"total rows                      : {total}")
    print(f"  with a THUMBNAIL              : {has}")
    print(f"  without                       : {missing}")
    print(f"    backfillable (has a LINK)   : {backfillable}")
    print(f"      of which already tried    : {tried}   <- skipped unless --retry-failed")
    print(f"    NOT backfillable (no LINK)  : {nolink}")


def worklist(n: int, retry_failed: bool, link_kind: str) -> list[dict]:
    """link_kind selects which STORAGE BACKEND to work against, and it matters:
    a row's LINK is either a Google Drive URL (5,954 of the 6,025 backfillable) or a
    LOCAL drive-engine URL (http://drive.localhost/file/d/l…, 71 rows). They are served by
    different profiles — handing a local link to the Google service-account connection
    returns 503, which is a connection mismatch and NOT an unreachable host."""
    extra = "" if retry_failed else "and coalesce(\"THUMBNAIL_COMPLETED\",'') = '' "
    if link_kind == "google":
        extra += "and \"LINK\" like '%drive.google.com%' "
    elif link_kind == "local":
        extra += "and \"LINK\" not like '%drive.google.com%' "
    q = ("select \"ID\" || '|' || replace(coalesce(\"LINK\",''),'|','') || '|' || "
         "replace(coalesce(\"NAME\",''),'|','') " + _SCOPE + extra +
         f"order by created_at desc limit {int(n)};")
    rows = []
    for line in psql(q).splitlines():
        parts = line.strip().split("|")
        if len(parts) >= 3 and parts[0]:
            rows.append({"id": parts[0], "link": parts[1], "name": parts[2]})
    return rows


def download(drive_url: str, link: str, conn: str, timeout: int) -> bytes:
    body = json.dumps({"fileId": link, "fileIdMode": "url", "connection_id": conn}).encode()
    req = urllib.request.Request(f"{drive_url}/download", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _multipart(name: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----indoxthumb" + uuid.uuid4().hex
    pre = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
           f"filename=\"{name}\"\r\nContent-Type: {mime}\r\n\r\n").encode()
    post = f"\r\n--{boundary}--\r\n".encode()
    return pre + data + post, f"multipart/form-data; boundary={boundary}"


def render(indox_url: str, name: str, data: bytes, timeout: int) -> dict:
    mime = mimetypes.guess_type(name)[0] or "application/pdf"
    body, ctype = _multipart(name or "document.pdf", data, mime)
    req = urllib.request.Request(f"{indox_url}/documents/thumbnail", data=body,
                                 headers={"Content-Type": ctype})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


#: Failure reasons that are a property of the DOCUMENT and will never succeed on a retry.
#: Anything not listed here (timeouts, transport errors, 5xx from apitools/drive) is treated
#: as TRANSIENT and must not be stamped terminal.
_PERMANENT_PREFIXES = ("unsupported_mime", "empty_file", "empty_render", "file required")


def is_permanent(err: str | None) -> bool:
    e = (err or "").strip()
    return any(e.startswith(p) for p in _PERMANENT_PREFIXES)


def store(doc_id: str, thumb: str | None, err: str | None) -> None:
    """Guarded on THUMBNAIL still being empty, so a concurrent genuine write is never
    clobbered and a re-run is a no-op.

    THUMBNAIL_COMPLETED is TERMINAL (api/__init__.py:3931 — one failed attempt ends the
    retries), so it is stamped ONLY on success or on a PERMANENT failure. A timeout is a
    statement about apitools' capacity at that moment, not about the document: stamping it
    would permanently exclude a perfectly renderable file from this tool AND from the live
    pipeline. The first run of this script did exactly that to 13 rows; they were restored by
    scripts/ops/migrations/2026-08-06_thumbnail_timeout_flag_revert.sql, and this guard is
    why it cannot happen again."""
    esc = lambda s: s.replace("'", "''")
    if not thumb and not is_permanent(err):
        return                                   # transient — leave the row untouched
    val = f"'{esc(thumb)}'" if thumb else "null"
    psql(f"update public.incoming_documents set \"THUMBNAIL\" = {val}, "
         f"\"THUMBNAIL_COMPLETED\" = 'true' where \"ID\" = '{esc(doc_id)}' "
         f"and coalesce(\"THUMBNAIL\",'') = '';")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--census", action="store_true")
    ap.add_argument("--run", type=int, default=0, help="process N documents")
    ap.add_argument("--commit", action="store_true", help="actually write THUMBNAIL to the DB")
    ap.add_argument("--retry-failed", action="store_true",
                    help="also re-attempt rows already marked THUMBNAIL_COMPLETED")
    ap.add_argument("--links", choices=("google", "local", "any"), default="google",
                    help="which storage backend to work against (default google — see worklist())")
    ap.add_argument("--connection-id", default=DEFAULT_CONNECTION)
    ap.add_argument("--timeout", type=int, default=180)
    a = ap.parse_args()
    if not (a.census or a.run):
        ap.error("pass --census or --run N")

    if a.census:
        census()
    if not a.run:
        return 0

    drive_url = f"http://{container_ip(DRIVE_CONTAINER)}:{DRIVE_PORT}"
    indox_url = f"http://{container_ip(INDOX_CONTAINER)}:{INDOX_PORT}{INDOX_PREFIX}"
    rows = worklist(a.run, a.retry_failed, a.links)
    print(f"\nworklist: {len(rows)} row(s) | drive={drive_url} indox={indox_url} | "
          f"{'COMMIT' if a.commit else 'DRY RUN — no DB write'}")

    ok = failed = 0
    t_all = time.time()
    for i, r in enumerate(rows, 1):
        t0 = time.time()
        try:
            data = download(drive_url, r["link"], a.connection_id, a.timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            print(f"  [{i}/{len(rows)}] DOWNLOAD FAIL {r['id']}: {e}")
            failed += 1
            continue
        t_dl = time.time() - t0
        t1 = time.time()
        try:
            res = render(indox_url, r["name"], data, a.timeout)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            print(f"  [{i}/{len(rows)}] RENDER FAIL {r['id']}: {e}")
            failed += 1
            continue
        t_rn = time.time() - t1
        thumb, err = res.get("thumbnail"), res.get("error")
        if thumb:
            ok += 1
        else:
            failed += 1
        if a.commit:
            store(r["id"], thumb, err)
        if thumb:
            verdict = "OK  "
        elif is_permanent(err):
            verdict = "FAIL-PERMANENT"
        else:
            verdict = "FAIL-TRANSIENT(row left eligible)"
        print(f"  [{i}/{len(rows)}] {verdict} {r['id']}  "
              f"{len(data)/1024:.0f}KiB  dl={t_dl:.1f}s render+upload={t_rn:.1f}s"
              + (f"  error={err}" if err else ""))

    el = time.time() - t_all
    print(f"\n{ok} rendered, {failed} failed, {el:.1f}s total "
          f"({el/max(len(rows),1):.1f}s per document)")
    if rows:
        print(f"extrapolated for the full backfillable set: "
              f"{el/len(rows)*6025/3600:.1f} h serial at this rate")
    if not a.commit:
        print("NOTHING WAS WRITTEN TO THE DATABASE (no --commit).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
