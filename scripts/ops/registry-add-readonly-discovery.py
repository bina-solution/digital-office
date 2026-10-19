#!/usr/bin/env python3
"""
settings.sync_registry writer for the READ-ONLY DESTINATION-FOLDER BACKFILL.

WHY THIS EXISTS
---------------
The `synced` and `failed` folders of the two real source families were filled by the LEGACY
automation, not by this engine. The engine only ever WRITES to them (projection moves), never
reads them, so 4,634 + 918 + 2,296 + 891 client documents have never been ingested. The owner's
instruction is that they must show up in sync state NATURALLY, via the syncs -- and that no client
file may be moved or relabelled to make that happen.

The mechanism already exists and has precedent: `drive-whatsapp-bot` (added 2026-08-09, backup
sync_registry.20260809T092525Z.json) is a registry entry whose five pair slots ALL point at one
folder (so a projection could not move a file even if it fired) and which sets `projection: "off"`
(so it never fires at all). syncV3Main0001 `Build Units` computes, for a thin pipe,
    proj_on = (s.projection === 'on')
and syncV3Deliver0001 `Post Record Route` requires `proj_on === true` on BOTH of its acting
branches, falling through to `Result OK` otherwise. With projection 'off' there is no reachable
move and no reachable label op. That is the read-only guarantee, and it is structural.

SIZING `page_size`
------------------
Drive discovery has NO cursor: every pass re-lists the folder from the start and takes the first
`page_size` files. If page_size < the folder's in-window size, the pipe can only ever see that
first page -- once those are ledgered, `missing` is 0 forever and the rest of the folder is never
discovered. So for a read-only backfill source page_size MUST exceed the folder's in-window count.
It costs nothing to over-size it: op_list stops at min(limit, matching), so the walk cost is set by
the folder, not the limit.

Measured 2026-08-09 through the engine's own path (drive /list, createdAfter = the live
OldDocumentMonthsBack = 6 months), scripts/ops/tmp-dest-folder-census.sh:

    1YpapJ3v..  'sroukot hitzliach'   4,634 files   57.5 s    -> page_size 8000
    1xthreeBl.. 'yetzu chat acharei'  2,296 files   26.7 s    -> page_size 6000
    1m25RdFE..  'sroukot nichshal'      918 files   11.9 s    -> page_size 4000
    1PYaVJ4d..  'yetzu chat nichshal'   891 files   13.7 s    -> page_size 4000

CEILING, measured the same day: the same call UNBOUNDED against 1YpapJ3v (17,067 files) returns
HTTP 500 after 120.9 s -- the gunicorn worker (--timeout 120) is SIGKILLed mid-walk at ~12.4 ms per
file. That puts the practical ceiling at ~9,600 files per /list call. Every folder above is inside
it WITH the 6-month window applied, and the window is what keeps it there: the unbounded scanned
folder is not listable at all today. If `sroukot hitzliach` grows past ~9,600 files IN WINDOW, this
pipe starts 500ing and needs a drive-side cursor (see the report).

status_override TO_EXTRACT + v3_mode thin + processor_wf null: delivery builds the
incoming_documents row from LISTING METADATA ONLY (syncV3Deliver0001 `Drive Row` -- no download,
no OCR) and hands it to the extraction driver's queue. Same as drive-whatsapp-bot.

DISCIPLINE: backup+sha256 taken before running this; the script re-asserts that every pre-existing
entry is byte-identical afterwards, except the two fields it deliberately edits.
"""
import hashlib
import json
import subprocess
import sys

DOCKER = ["docker", "-H", "unix:///run/bbox-docker.sock"]
DB = DOCKER + ["exec", "-i", "supabase-db-shlomo-laptop",
               "psql", "-U", "postgres", "-d", "postgres"]
CONN = "drive_google_service_account-ea660043"

# ---- the corrected `failed` folder for drive-gdoc-scanned --------------------------------------
# The registry points at 11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb 'acharei shemot, sroukot Boris nichshal'
# (101 files in window). The real failed folder of this family is
# 1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2 'sroukot- nichshal (Boris)' (918 files in window). Established
# by the tri-state sibling resolution in scripts/ops/registry-fix-drive-gdoc-warehouse.sql:26.
SCANNED_FAILED_WRONG = "11rj5zDw2lhYnc8zMUxmYADKIJaPaunhb"
SCANNED_FAILED_RIGHT = "1m25RdFEkfv_5KjSqFGM8gpjupXWZuUW2"

F_SCANNED_SYNCED = "1YpapJ3vJDYo_idP3aZiFJR_1WoEaCNhu"
F_SCANNED_FAILED = SCANNED_FAILED_RIGHT
F_CHAT_SYNCED = "1xthreeBl1VD-5uN9PFu9Zi-0IABQDwst"
F_CHAT_FAILED = "1PYaVJ4dKdOl1iGJlVKFT0pzJ_Rs2mYNL"


def readonly_entry(name, folder, page_size):
    """Shape copied field-for-field from the live `drive-whatsapp-bot` entry, which is the
    established precedent for a read-only discovery source on this deployment. The only
    additions are the sized page_size and take/chunk matching the drive-gdoc-* family."""
    return {
        "name": name,
        "batch": {"take": 50, "chunk": 25, "page_size": page_size,
                  "timeout_min": 14, "schedule_min": 15},
        # ALL FIVE SLOTS ARE THE SAME FOLDER. Belt and braces behind `projection: off`: even if a
        # projection somehow fired, its destination is the folder the file is already in, so the
        # move is a no-op. No client file can be relocated by this entry.
        "pairs": [{"to": folder, "from": folder, "failed": folder,
                   "synced": folder, "to_sync": folder}],
        "engine": "v3",
        "source": "drive",
        "enabled": True,
        "v3_mode": "thin",
        "type_hint": None,
        "connection": CONN,
        "projection": "off",
        "processor_wf": None,
        "fallback_type": None,
        "status_override": "TO_EXTRACT",
    }


NEW_ENTRIES = {
    "drive-gdoc-scanned-synced": (F_SCANNED_SYNCED, 8000),
    "drive-gdoc-scanned-failed": (F_SCANNED_FAILED, 4000),
    "drive-gdoc-chat-export-synced": (F_CHAT_SYNCED, 6000),
    "drive-gdoc-chat-export-failed": (F_CHAT_FAILED, 4000),
}


def read_registry():
    out = subprocess.run(DB + ["-t", "-A", "-c",
                               "select value from public.settings where key='sync_registry'"],
                         capture_output=True, text=True, check=True).stdout.strip()
    return out, json.loads(out)


def canon(e):
    return json.dumps(e, sort_keys=True, ensure_ascii=False)


def write_registry(entries):
    payload = json.dumps(entries, ensure_ascii=False)
    assert "$sr$" not in payload
    sql = ("update public.settings set value = $sr$" + payload +
           "$sr$ where key='sync_registry';")
    r = subprocess.run(DB + ["-v", "ON_ERROR_STOP=1", "-c", sql],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(r.stdout, r.stderr, file=sys.stderr)
        raise SystemExit("registry write FAILED - nothing changed")
    print("write:", r.stdout.strip())


def main():
    steps = sys.argv[1:]
    if not steps:
        raise SystemExit("usage: registry-add-readonly-discovery.py <fix-failed-id|entry-name> ...")

    raw_before, before = read_registry()
    print("BEFORE sha256:", hashlib.sha256(raw_before.encode()).hexdigest())
    print("BEFORE entries:", [e["name"] for e in before])

    baseline = {e["name"]: canon(e) for e in before}
    after = json.loads(raw_before)
    expected_edits = {}

    for step in steps:
        if step == "fix-failed-id":
            hit = [e for e in after if e["name"] == "drive-gdoc-scanned"]
            if len(hit) != 1:
                raise SystemExit("drive-gdoc-scanned not found exactly once")
            p = hit[0]["pairs"][0]
            # EXACT-MATCH WRITE: refuse unless the value on disk is the one we believe is wrong.
            for k in ("failed", "failed_to"):
                if p.get(k) != SCANNED_FAILED_WRONG:
                    raise SystemExit(
                        "refusing: drive-gdoc-scanned.pairs[0].%s is %r, expected %r"
                        % (k, p.get(k), SCANNED_FAILED_WRONG))
                p[k] = SCANNED_FAILED_RIGHT
            expected_edits["drive-gdoc-scanned"] = ("failed", "failed_to")
            print("staged: drive-gdoc-scanned failed/failed_to %s -> %s"
                  % (SCANNED_FAILED_WRONG, SCANNED_FAILED_RIGHT))
        elif step in NEW_ENTRIES:
            if any(e["name"] == step for e in after):
                raise SystemExit("refusing: %s already present" % step)
            folder, ps = NEW_ENTRIES[step]
            after.append(readonly_entry(step, folder, ps))
            print("staged: + %s -> %s (page_size=%d, projection=off)" % (step, folder, ps))
        else:
            raise SystemExit("unknown step %r" % step)

    write_registry(after)

    raw_after, verify = read_registry()
    print("AFTER  sha256:", hashlib.sha256(raw_after.encode()).hexdigest())
    print("AFTER  entries:", [e["name"] for e in verify])

    # ---- ASSERT: every pre-existing entry byte-identical, except the fields we meant to edit ----
    seen = set()
    for e in verify:
        n = e["name"]
        seen.add(n)
        if n not in baseline:
            continue
        if n in expected_edits:
            probe = json.loads(baseline[n])
            for k in expected_edits[n]:
                probe["pairs"][0][k] = SCANNED_FAILED_RIGHT
            if canon(e) != canon(probe):
                raise SystemExit("MISMATCH on edited entry %s - registry differs beyond the "
                                 "intended fields" % n)
            print("verified (edited, only the named fields moved):", n)
        else:
            if canon(e) != baseline[n]:
                raise SystemExit("MISMATCH: pre-existing entry %s changed" % n)
    missing = set(baseline) - seen
    if missing:
        raise SystemExit("MISSING pre-existing entries: %s" % missing)
    print("verified byte-identical: %d pre-existing entries"
          % (len(baseline) - len(expected_edits)))
    print("OK")


if __name__ == "__main__":
    main()
