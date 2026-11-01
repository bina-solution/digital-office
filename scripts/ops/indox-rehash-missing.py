#!/usr/bin/env python3
"""Backfill the HASH of the GOOGLE_DRIVE_FILE rows that were written without one.

    python3 scripts/ops/indox-rehash-missing.py --worklist        # census, no I/O at all
    python3 scripts/ops/indox-rehash-missing.py --verify 5        # download 5 files, PROVE the rule
    python3 scripts/ops/indox-rehash-missing.py --emit            # write the reviewable .sql

*** THIS SCRIPT NEVER WRITES TO THE DATABASE. *** It emits an .sql file for a human to
review and run. Mass writes to the live table need the owner's approval (see
scripts/ops/indox-column-consolidation.sql §6).

════════════════════════════════════════════════════════════════════════════════
WHY THESE ROWS HAVE NO HASH  (established 2026-08-06 — was "unexplained" before)

They were written by the n8n `Search File` workflow's GoogleDrive node, `resource:
fileFolder`, `searchMethod: query`, `options: {}` — see the pre-refactor export
.claude/worktrees/fervent-mestorf-20f464/production/n8n/workflows/cnvttABSBdZTe9Xv.json.
With `options.fields` unset, that node's own `prepareQueryString(undefined)` returns the
literal string 'id, name' (v2/helpers/utils.js, read out of the running n8n image), so it
asked Drive for `files(id, name)` — no md5Checksum, no size. `Build: ... LINK FOUND` then
evaluated `HASH = {{ $json.md5Checksum }}` against an object that never carried the key;
n8n's Set node coerced `undefined` to '' and stored an empty string.

The rows themselves are the proof: all 183 have NAME and SOURCE_ID (from `name`/`id`) and
BOTH `SIZE` and `HASH` empty — exactly, and only, the two fields that projection omitted.
uq_incdoc_hash is PARTIAL (excludes null/''/'unknown'), so '' means zero dedup protection.

HISTORICAL, NOT A LIVE LEAK — but not because it was fixed:
  * 0 new GOOGLE_DRIVE_FILE rows since the 2026-08-05 00:58:51 restore; ACTION_LOG contains
    'LINK FOUND' on 0 rows table-wide.
  * The projection half IS repaired: apps/drive `op_list` asks for `files(*)`, verified live
    to return md5Checksum for binary files.
  * The path is dead for a WORSE reason: apps/drive `/list` accepts no `query`, so
    indoxV2SearchFile01's `name contains …` is silently dropped and its own guard rejects the
    arbitrary file that comes back. See op_list's docstring in apps/drive/adapters/google.py.

════════════════════════════════════════════════════════════════════════════════
WHY NO DOWNLOAD IS NEEDED (this replaces the previous download-every-file approach)

API_TOOLS_ID on these rows already IS the md5 of the file's bytes: apitools computes
`file_hash = hashlib.md5(file_content).hexdigest()` in apps/apitools/src/api/ocr_api.py and
returns it as the document key. All 183 rows carry a 32-hex API_TOOLS_ID.

Verified by download, not assumed — `--verify` fetches N files through apps/drive and
compares. On 2026-08-06, 2/2 GOOGLE_DRIVE_FILE rows hashed byte-identical to their
API_TOOLS_ID.

CAVEAT, and it is why this shortcut is scoped to GOOGLE_DRIVE_FILE only: md5Checksum and
file_hash are NOT interchangeable in general. They agree only when the bytes apitools
received are the bytes Drive stores. On GOOGLE_DRIVE_FOLDER rows 725 of 3,092 DISAGREE, and
spot-checks show HASH matches the current Drive bytes while API_TOOLS_ID does not — those
documents were converted between OCR and archiving. Never generalise this rule.

WHY THE EARLIER "EVERY DRIVE FETCH 404s ON THIS HOST" REPORT WAS WRONG
That run sent `fileIdMode: "link"`. `extract_file_id` (adapters/opsupport.py) parses a URL
ONLY for mode == "url"; every other mode is literal, so the whole
`https://drive.google.com/...` string went to Drive as a file id and came back 404 (surfaced
as 503) — including the control rows, which is what made it look environmental. Measured
2026-08-06 on the same host, same file: mode "link" -> 503, mode "id" -> 503, mode "url" ->
669,521 bytes. Drive is reachable. This script uses "url".

════════════════════════════════════════════════════════════════════════════════
WHAT THE EMITTED SQL DOES — three phases, because a blind UPDATE would fail

Census on 2026-08-06 (the script re-derives it every run; trust the run, not this text):
    183  rows in scope
    110  whose API_TOOLS_ID is ALREADY another row's HASH  -> genuine duplicates
      3  that duplicate ANOTHER of the 183
     70  unique and safe to fill
  of the 110: 52 already STATUS='DOUBLE', 58 still sitting as COMPLETED — i.e. 58 duplicate
  documents the missing hash let through undetected. That is the finding, not a side effect.

  Phase 1  fill HASH on the 70 safe rows. Guarded on HASH still being empty, so re-running is
           safe and a concurrent genuine write is never clobbered.
  Phase 2  REPORT ONLY (a SELECT) for the 113 colliders. uq_incdoc_hash permits exactly one
           holder per hash, so their HASH must stay empty — the canonical row keeps it.
  Phase 3  OPTIONAL and separate: move the 58 non-DOUBLE colliders to NEEDS_REVIEW and record
           the twin. NOT 'DOUBLE': indoxDataGateway01's LEGAL_TRANSITIONS table allows
           COMPLETED -> NEEDS_REVIEW and not COMPLETED -> DOUBLE, and this backfill has no
           licence to invent a transition the gateway would refuse. Left commented out.

SCOPE — GOOGLE_DRIVE_FILE only. Deliberately NOT the other missing-hash rows:
  * 183 BALANCE_SHEET, BS-spawned per-line rows with no file at all — a content md5 is
    meaningless for them (§6b of the consolidation SQL).
  * 166 legacy rows with SOURCE_TYPE null — quarantine.
  * 41 INVOICE rows — a different lane.
────────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import sys
import urllib.error
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO = pathlib.Path(__file__).resolve().parents[2]
DB_CONTAINER = "supabase-db-shlomo-laptop"
DOCKER_SOCK = "unix:///run/bbox-docker.sock"

# Deliberately ONE LINE each with no tabs. `psql -tAc` receives these through a shell, and any
# real newline or tab arrives as a literal backslash-n / backslash-t, which psql then reads as a
# META-COMMAND ("invalid command \nselect") rather than as SQL. Keep them single-line.
_SCOPE = ("from public.incoming_documents "
          "where (\"HASH\" is null or \"HASH\" = '' or lower(\"HASH\") = 'unknown') "
          "and \"SOURCE_TYPE\" = 'GOOGLE_DRIVE_FILE' ")

# Every in-scope row with the verdict the emitted SQL will act on.
# collides = its API_TOOLS_ID is already some OTHER row's HASH -> cannot be written (unique index)
# rn>1     = a second in-scope row sharing an API_TOOLS_ID with an earlier one -> same problem
CENSUS_SQL = (
    "with g as (select \"ID\", \"API_TOOLS_ID\" a, coalesce(\"STATUS\",'') s, coalesce(\"LINK\",'') l "
    + _SCOPE
    + "), c as (select g.*, exists (select 1 from public.incoming_documents d "
      "where d.\"HASH\" = g.a and d.\"ID\" <> g.\"ID\") as collides, "
      "row_number() over (partition by g.a order by g.\"ID\") as rn, "
      "(select min(d.\"ID\") from public.incoming_documents d "
      "where d.\"HASH\" = g.a and d.\"ID\" <> g.\"ID\") as twin from g) "
      "select \"ID\" || '|' || coalesce(a,'') || '|' || s || '|' || l || '|' "
      "|| case when collides then 'COLLIDE' when rn > 1 then 'INTRADUP' else 'FILL' end "
      "|| '|' || coalesce(twin,'') from c order by \"ID\";"
)


def psql(sql: str) -> str:
    """Read-only query via the project's docker socket. Status is read from the OUTER process,
    never from `$?` inside a `wsl bash -lc` string (that reports the wrapper's status).

    Runs docker directly when we are already inside Linux, and hops through `wsl` when invoked
    from Windows. The --verify half needs the drive container's bridge IP, which only resolves
    INSIDE WSL — so in practice run the whole thing from WSL. From Windows the census works and
    every download fails `getaddrinfo`, which is a routing fact, not a bug in the script."""
    inner = (f"docker -H {DOCKER_SOCK} exec -i {DB_CONTAINER} "
             f"psql -U postgres -d postgres -tAc {json.dumps(sql)}")
    cmd = ["bash", "-lc", inner] if sys.platform.startswith("linux") \
        else ["wsl", "bash", "-lc", inner]
    proc = subprocess.run(cmd, capture_output=True, timeout=300)
    if proc.returncode != 0:
        sys.exit(f"psql failed rc={proc.returncode}: "
                 f"{proc.stderr.decode('utf-8', 'replace')[:400]}")
    return proc.stdout.decode("utf-8", "replace")


def census() -> list[dict]:
    rows = []
    for line in psql(CENSUS_SQL).splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 6:
            continue
        rows.append({"id": parts[0], "atid": parts[1], "status": parts[2],
                     "link": parts[3], "verdict": parts[4], "twin": parts[5]})
    return rows


DRIVE_CONTAINER = "drive-shlomo-laptop"
DRIVE_PORT = 8975


def discover_drive_url() -> str:
    """The drive app's reachable base URL, resolved at runtime.

    Why not a hostname: `drive.localhost` is a TRAEFIK route and does not resolve in WSL's
    resolver at all; hitting 127.0.0.1 with a `Host:` header does reach traefik but lands in the
    authentik forward-auth chain (302), which is correct for the SSO'd UI plane and wrong for a
    canonical op. `http://drive:8975` is docker-internal DNS and only resolves INSIDE the network.
    What IS reachable from the WSL host is the container's bridge IP — verified 200 on /healthz —
    so resolve that each run rather than pinning an address that changes on every recreate."""
    inner = (f"docker -H {DOCKER_SOCK} inspect -f "
             f"'{{{{range .NetworkSettings.Networks}}}}{{{{.IPAddress}}}} {{{{end}}}}' "
             f"{DRIVE_CONTAINER}")
    cmd = ["bash", "-lc", inner] if sys.platform.startswith("linux") \
        else ["wsl", "bash", "-lc", inner]
    proc = subprocess.run(cmd, capture_output=True, timeout=120)
    if proc.returncode != 0:
        sys.exit(f"could not resolve {DRIVE_CONTAINER}: "
                 f"{proc.stderr.decode('utf-8', 'replace')[:300]}")
    ips = proc.stdout.decode("utf-8", "replace").split()
    if not ips:
        sys.exit(f"{DRIVE_CONTAINER} has no network address — is the stack up?")
    return f"http://{ips[0]}:{DRIVE_PORT}"


def fetch_md5(base_url: str, connection_id: str, link: str, timeout: int) -> tuple[str, int]:
    """`fileIdMode` MUST be "url" — extract_file_id parses a URL only in that mode and passes
    every other mode through literally, which sends the whole https:// string to Drive as a file
    id and 404s. That single wrong value is what an earlier run mistook for an unreachable host."""
    body = json.dumps({"fileId": link, "fileIdMode": "url",
                       "connection_id": connection_id}).encode()
    req = urllib.request.Request(f"{base_url.rstrip('/')}/download", data=body,
                                 headers={"Content-Type": "application/json"})
    h, n = hashlib.md5(), 0
    with urllib.request.urlopen(req, timeout=timeout) as r:
        while chunk := r.read(65536):
            h.update(chunk)
            n += len(chunk)
    return h.hexdigest(), n


def do_verify(rows: list[dict], n: int, drive_url: str, conn: str, timeout: int) -> int:
    """Download N files and check the claim "API_TOOLS_ID is the md5 of this file's bytes".
    Any mismatch invalidates the whole shortcut — say so loudly and fail."""
    sample = [r for r in rows if r["link"] and r["atid"]][:n]
    print(f"verify: downloading {len(sample)} file(s) via {drive_url}")
    bad = 0
    for i, r in enumerate(sample, 1):
        try:
            md5, nbytes = fetch_md5(drive_url, conn, r["link"], timeout)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:200].replace("\n", " ")
            print(f"  [{i}/{len(sample)}] FETCH FAIL {r['id']}: HTTP {e.code} — {detail}")
            bad += 1
            continue
        except (urllib.error.URLError, OSError, TimeoutError) as e:
            print(f"  [{i}/{len(sample)}] FETCH FAIL {r['id']}: {e}")
            bad += 1
            continue
        ok = md5 == r["atid"]
        print(f"  [{i}/{len(sample)}] {'MATCH  ' if ok else 'MISMATCH'} {r['id']}  "
              f"md5={md5}  API_TOOLS_ID={r['atid']}  {nbytes}B")
        if not ok:
            bad += 1
    if bad:
        print(f"\n{bad} of {len(sample)} did NOT confirm the rule — DO NOT RUN THE BACKFILL.")
    else:
        print(f"\nall {len(sample)} confirm: API_TOOLS_ID == md5(file bytes).")
    return 1 if bad else 0


def emit(rows: list[dict], dest: pathlib.Path) -> None:
    fill = [r for r in rows if r["verdict"] == "FILL"]
    collide = [r for r in rows if r["verdict"] in ("COLLIDE", "INTRADUP")]
    promote = [r for r in collide if r["status"] not in ("DOUBLE", "NEEDS_REVIEW")]

    out = [
        "-- GENERATED by scripts/ops/indox-rehash-missing.py — REVIEW BEFORE RUNNING.",
        "-- Read the module docstring first; it explains why HASH := API_TOOLS_ID is sound for",
        "-- THESE rows and unsound in general.",
        f"-- in scope: {len(rows)} | phase 1 fills: {len(fill)} | "
        f"collide (left empty): {len(collide)} | phase 3 candidates: {len(promote)}",
        "",
        "BEGIN;",
        "",
        "-- ── PHASE 1 — fill the rows whose hash is unique ───────────────────────────────────",
        "-- Guarded on HASH still being empty: re-running is a no-op and a concurrent genuine",
        "-- write is never clobbered. Expect exactly the count above; anything else means the",
        "-- table moved under you — ROLLBACK and re-generate.",
    ]
    for r in fill:
        out.append(
            f"update public.incoming_documents set \"HASH\" = '{r['atid']}' "
            f"where \"ID\" = '{r['id']}' "
            f"and (\"HASH\" is null or \"HASH\" = '' or lower(\"HASH\") = 'unknown');")

    out += [
        "",
        "-- ── PHASE 2 — REPORT ONLY. The duplicates the missing hash let through. ────────────",
        "-- These rows' content hash is ALREADY held by another row, and uq_incdoc_hash permits",
        "-- exactly one holder, so their HASH stays empty by design — the canonical row keeps it.",
        "-- This SELECT is the deliverable: it names each duplicate and its twin.",
        "select d.\"ID\", d.\"STATUS\", d.\"NAME\", d.\"API_TOOLS_ID\", t.\"ID\" as twin_id,",
        "       t.\"STATUS\" as twin_status, t.\"SOURCE_TYPE\" as twin_source",
        "  from public.incoming_documents d",
        "  join public.incoming_documents t on t.\"HASH\" = d.\"API_TOOLS_ID\" and t.\"ID\" <> d.\"ID\"",
        " where d.\"SOURCE_TYPE\" = 'GOOGLE_DRIVE_FILE'",
        "   and (d.\"HASH\" is null or d.\"HASH\" = '' or lower(d.\"HASH\") = 'unknown')",
        " order by d.\"STATUS\", d.\"ID\";",
        "",
        "COMMIT;",
        "",
        "-- ── PHASE 3 — OPTIONAL, SEPARATE APPROVAL, DELIBERATELY COMMENTED OUT ─────────────",
        f"-- {len(promote)} of the duplicates above are not yet flagged — they sit as COMPLETED,",
        "-- counted as real documents. Moving them to NEEDS_REVIEW (not DOUBLE: indoxDataGateway01's",
        "-- LEGAL_TRANSITIONS allows COMPLETED -> NEEDS_REVIEW and forbids COMPLETED -> DOUBLE)",
        "-- puts them in front of a human without inventing a transition the gateway would refuse.",
        "-- This CHANGES THE MEANING of live rows. Run it only on an explicit, separate decision.",
        "-- BEGIN;",
    ]
    for r in promote:
        twin = r["twin"] or "?"
        out.append(
            f"-- update public.incoming_documents set \"STATUS\" = 'NEEDS_REVIEW', "
            f"\"ERROR\" = 'duplicate of {twin} (content md5 {r['atid']}); "
            f"flagged by indox-rehash-missing backfill' "
            f"where \"ID\" = '{r['id']}' and \"STATUS\" = '{r['status']}';")
    out.append("-- COMMIT;")

    dest.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--worklist", action="store_true", help="census only, no I/O")
    ap.add_argument("--verify", type=int, default=0,
                    help="download N files and prove API_TOOLS_ID == md5(bytes)")
    ap.add_argument("--emit", action="store_true", help="write the reviewable .sql")
    ap.add_argument("--drive-url", default="",
                    help="override the drive base URL; default auto-resolves the container's "
                         "bridge IP (see discover_drive_url)")
    ap.add_argument("--connection-id", default="drive_google_service_account-ea660043",
                    help="REQUIRED by apps/drive on every canonical op — it never falls back to "
                         "the console's ambient binding (2026-08-06 incident)")
    ap.add_argument("--out", default="scripts/ops/indox-rehash-missing.generated.sql")
    ap.add_argument("--timeout", type=int, default=120)
    a = ap.parse_args()
    if not (a.worklist or a.verify or a.emit):
        ap.error("pass --worklist, --verify N, or --emit")

    rows = census()
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("FILL", "COLLIDE", "INTRADUP")}
    no_atid = sum(1 for r in rows if not r["atid"])
    print(f"in scope: {len(rows)} GOOGLE_DRIVE_FILE row(s) with no HASH")
    print(f"  fillable (unique hash) : {counts['FILL']}")
    print(f"  collides with a live HASH: {counts['COLLIDE']}   <- genuine duplicates")
    print(f"  duplicates another in-scope row: {counts['INTRADUP']}")
    print(f"  missing API_TOOLS_ID (unrecoverable here): {no_atid}")
    if a.worklist:
        for r in rows[:20]:
            print(f"  {r['verdict']:<8} {r['id']}  {r['status']:<10} {r['atid']}")
        if len(rows) > 20:
            print(f"  ... and {len(rows) - 20} more")

    rc = 0
    if a.verify:
        drive_url = a.drive_url or discover_drive_url()
        rc = do_verify(rows, a.verify, drive_url, a.connection_id, a.timeout)

    if a.emit:
        dest = REPO / a.out
        emit(rows, dest)
        print(f"\nwrote {dest}")
        print("NOTHING WAS WRITTEN TO THE DATABASE.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
