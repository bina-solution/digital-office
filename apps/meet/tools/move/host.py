#!/usr/bin/env python3
"""host — the half of `bbox meet move` that runs ON a machine, as root, beside its office's meet (DGO-1861).

The computers app runs it there: `python3 <work>/host.py <verb> …` once the move has put it in its work folder, beside
meet_move.py (scripts/client-move/, DGO-1924), whose manifest, place and verify it uses; a dry run, which writes
nothing anywhere, sends it on stdin instead (`python3 - <verb> …`). Standard library only: the machine's own python3
(Debian 12/13, Ubuntu). Each verb ends with one line, `RESULT <json>`; `read` prints only the piece.

    locate <work>                     the meet on this machine: its meet-start container, the folder that holds
                                      recordings/ (the recordings volume, on the host), the room left on its disk and
                                      where <work> is, and which machine this is (/etc/machine-id and its name)
    list <root> <room>                the room's recorded meetings: each recordings/<uuid>/ whose recording is
                                      <room>_<stamp>.mp4 (and whether it is finished, by meet's own rule), and
                                      recordings/flows/<room>/ (a page made for a meeting recorded elsewhere) — every
                                      file, its size and time
    stage <root> <room> <staged>      a copy of each into <staged>/recordings/ (times kept) and its manifest — meet_move's
                                      shape, with the units moved, the room and every file's time, written once and
                                      whole. On the SOURCE this copy is the meeting's backup, and it stays
    stage and remove hold the run's lock on the machine (<work>/.lock): a step asked again while the first is still
    running there is refused, never run beside it (drive asked twice finds the folder in the trash already).
    read <path> <offset> <length>     that piece of a file, base64
    append <path> <offset>            base64 on stdin, written at <offset> (the file must be exactly that long already;
                                      the same piece sent again, its answer lost, is found there and kept)
    utime <path> <mtime>
    remove <root> <staged>            each unit of the manifest, out of <root>/recordings — only when every file there is
                                      the manifest's (size and sha256) and there is no other; each is put aside, checked
                                      again there, and only then deleted; nothing is removed unless all of it can be.
                                      Asked again after it was done, it says so. What is removed was carried and
                                      verified; <staged> is its backup
    drive <container> <room> <stems> [--trash]
                                      the room's folders in the office's Drive («/פגישות/<date> · <room>»: meet's own
                                      copies, written by its to_drive); --trash moves one to Drive's trash only when it
                                      is of a moved recording (its date, one of its files) and holds nothing but what
                                      meet writes there by itself (the recordings, the transcript and the subtitles,
                                      .meet-flow/first.json). People's corrections, approvals and uploads live there
                                      too (.meet-flow/edits.jsonl, items.json, uploads.json): they are NOT carried, so
                                      a folder that holds them stays where it is, and is named
"""
import argparse
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from urllib.parse import unquote

HERE = os.path.dirname(os.path.abspath(__file__))
# meet-start's own shapes (apps/meet/start/server.py): a session folder, a room, a recording's name
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
ROOM_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,62}$")
STAMP_RE = re.compile(r"^(?P<room>.+)_\d{4}-\d\d-\d\d-\d\d-\d\d-\d\d\.mp4$")


def result(obj, code=0):
    print("RESULT " + json.dumps(obj, ensure_ascii=False), flush=True)
    return code


def fail(msg, **more):
    return result(dict(more, ok=False, error=msg), 1)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tree(root):
    """{relative path: absolute path} of every file under root ('/' separated)."""
    out = {}
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root).replace(os.sep, "/")] = p
    return out


def recordings_of(root):
    rec = os.path.join(root, "recordings")
    if not os.path.isdir(rec):
        raise SystemExit(fail(f"{rec} is not there — is this the meet's recordings volume?"))
    return rec


def finished(folder):
    """meet's own rule for a recording that is done (server.py to_drive): Jibri wrote its metadata.json, finalize.sh is
    not between its renames (no *.part, no *.rebuilt), and each video has its sound — or is six hours old (a finalize
    that never wrote one)."""
    names = os.listdir(folder)
    if "metadata.json" not in names or any(n.endswith((".part", ".rebuilt")) for n in names):
        return False
    return all(n[:-4] + ".ogg" in names or time.time() - os.stat(os.path.join(folder, n)).st_mtime > 6 * 3600
               for n in names if n.endswith(".mp4"))


def units_of(root, room):
    """[(unit, done)] — the room's session folders (done: finished(), above) and its flows/<room>."""
    rec = recordings_of(root)
    found = []
    for s in sorted(os.listdir(rec)):
        folder = os.path.join(rec, s)
        if s == "flows" or not SESSION_RE.fullmatch(s) or not os.path.isdir(folder):
            continue
        for name in os.listdir(folder):
            m = STAMP_RE.match(name)
            if m and unquote(m.group("room")).strip().lower() == room:
                found.append((s, finished(folder)))
                break
    if os.path.isdir(os.path.join(rec, "flows", room)):
        found.append(("flows/" + room, True))
    return found


def free_at(path):
    """(bytes free, device) of the filesystem that holds path, or of its nearest folder that exists."""
    while not os.path.exists(path):
        path = os.path.dirname(path)
    st = os.statvfs(path)
    return st.f_bavail * st.f_frsize, os.stat(path).st_dev


def locked(work):
    """This run's lock on this machine (<work>/.lock, flock): a step asked again while the first is still running there
    is refused by it, never run beside it. move.py takes the same lock around meet_move (flock -n)."""
    os.makedirs(work, exist_ok=True)
    f = open(os.path.join(work, ".lock"), "a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit(fail("another step of this run is still running on this machine — wait for it, then resume"))
    return f


def cmd_locate(a):
    names = subprocess.run(["docker", "ps", "--filter", "label=com.docker.compose.service=meet-start",
                            "--format", "{{.Names}}"], capture_output=True, text=True).stdout.split()
    if len(names) != 1:
        return fail("no meet-start runs on this machine" if not names else
                    f"{len(names)} meet-starts run on this machine ({', '.join(names)}) — which office is meant?")
    mounts = json.loads(subprocess.run(["docker", "inspect", "-f", "{{json .Mounts}}", names[0]],
                                       capture_output=True, text=True).stdout or "[]")
    root = next((m.get("Source") for m in mounts if m.get("Destination") == "/recordings"), None)
    if not root or not os.path.isdir(os.path.join(root, "recordings")):
        return fail(f"{names[0]} has no recordings volume at /recordings")
    free, dev = free_at(root)
    work_free, work_dev = free_at(a.work)
    try:
        with open("/etc/machine-id", encoding="utf-8") as f:
            machine = f.read().strip()
    except OSError:
        machine = ""
    return result({"ok": True, "container": names[0], "root": root, "free": free, "work_free": work_free,
                   "same_fs": dev == work_dev, "machine": machine + "@" + os.uname().nodename})


def cmd_list(a):
    rec = recordings_of(a.root)
    units = units_of(a.root, a.room)
    files = []
    for unit, _ in units:
        for rel, p in sorted(tree(os.path.join(rec, unit)).items()):
            st = os.stat(p)
            files.append({"rel": unit + "/" + rel, "size": st.st_size, "mtime": int(st.st_mtime)})
    return result({"ok": True, "room": a.room, "units": [u for u, _ in units], "recording": [u for u, d in units if not d],
                   "files": files, "bytes": sum(f["size"] for f in files)})


def cmd_stage(a):
    lock = locked(os.path.dirname(a.staged))           # noqa: F841 — held until this process ends
    rec = recordings_of(a.root)
    units = units_of(a.root, a.room)
    if not units:
        return fail(f"no recorded meeting of «{a.room}» here")
    if any(not d for _, d in units):
        return fail("a recording of this room is not finished yet (Jibri or finalize.sh is still writing it)")
    manifest = os.path.join(a.staged, "manifest.json")
    if os.path.exists(manifest):
        return fail(f"{a.staged} is there already, whole — a backup is never written over")
    if os.path.exists(a.staged):                       # a stage that stopped before its manifest: never a backup
        shutil.rmtree(a.staged)
    size = sum(os.path.getsize(p) for unit, _ in units for p in tree(os.path.join(rec, unit)).values())
    if free_at(a.staged)[0] < size + (256 << 20):
        return fail(f"{free_at(a.staged)[0]:,} bytes free where the backup goes; it needs {size:,} and a margin")
    for unit, _ in units:
        shutil.copytree(os.path.join(rec, unit), os.path.join(a.staged, "recordings", unit), copy_function=shutil.copy2)
    sys.path.insert(0, HERE)
    import meet_move                                   # its manifest's shape and its sha256: what place and verify read
    base = os.path.join(a.staged, "recordings")
    files = {}
    for rel, p in meet_move.files_of(base):
        st = os.stat(p)
        files[rel] = {"size": st.st_size, "sha256": meet_move.sha(p), "mtime": int(st.st_mtime)}
    man = {"format": "dgo-meet-move/1", "sessions": sorted(os.listdir(base)), "files": files, "room": a.room,
           "units": [u for u, _ in units]}
    with open(manifest + ".part", "w", encoding="utf-8") as f:   # written once, whole: a manifest is a finished backup
        json.dump(man, f, ensure_ascii=False, indent=0)
        f.flush()
        os.fsync(f.fileno())
    os.replace(manifest + ".part", manifest)
    return result({"ok": True, "units": man["units"], "files": len(files), "bytes": sum(x["size"] for x in files.values())})


def cmd_read(a):
    with open(a.path, "rb") as f:
        f.seek(a.offset)
        sys.stdout.write(base64.b64encode(f.read(a.length)).decode("ascii"))
    return 0


def cmd_append(a):
    data = base64.b64decode(sys.stdin.read())
    have = os.path.getsize(a.path) if os.path.exists(a.path) else 0
    if data and have == a.offset + len(data):            # sent again after an answer that was lost: it is there
        with open(a.path, "rb") as f:
            f.seek(a.offset)
            if f.read(len(data)) == data:
                return result({"ok": True, "size": have, "kept": True})
    if have != a.offset:
        return fail(f"{a.path} is {have} bytes, not {a.offset}: this piece is not the next one", size=have)
    os.makedirs(os.path.dirname(a.path), exist_ok=True)
    with open(a.path, "ab") as f:
        f.write(data)
    return result({"ok": True, "size": have + len(data)})


def cmd_utime(a):
    os.utime(a.path, (a.mtime, a.mtime))
    return result({"ok": True})


def aside(rec, unit):
    """Where a unit waits while it is checked one last time: recordings/.meet-move-<unit> (the same filesystem), a dot
    name meet-start never lists — not inside flows/, whose every entry it lists."""
    return os.path.join(rec, ".meet-move-" + unit.replace("/", "-"))


def mismatch(folder, unit, man):
    """What in folder is not the manifest's copy of unit: a file not in it, a file missing, other bytes."""
    here = tree(folder)
    want = {r[len(unit) + 1:]: i for r, i in man["files"].items() if r.startswith(unit + "/")}
    bad = [f"{unit}/{rel}: not in the backup (written after it?)" for rel in sorted(set(here) - set(want))]
    for rel, info in sorted(want.items()):
        p = here.get(rel)
        if not p:
            bad.append(f"{unit}/{rel}: missing")
        elif os.path.getsize(p) != info["size"] or sha(p) != info["sha256"]:
            bad.append(f"{unit}/{rel}: other bytes than the backup's")
    return bad


def cmd_remove(a):
    lock = locked(os.path.dirname(a.staged))           # noqa: F841 — held until this process ends
    rec = recordings_of(a.root)
    with open(os.path.join(a.staged, "manifest.json"), encoding="utf-8") as f:
        man = json.load(f)
    units = man.get("units") or []
    if not units:
        return fail("the backup's manifest names no meeting's folder — refusing")
    for unit in units:
        if not (SESSION_RE.fullmatch(unit) and unit != "flows") and not (
                unit.startswith("flows/") and ROOM_RE.fullmatch(unit[6:])):
            return fail(f"{unit!r} is not a meeting's folder — refusing")
        if os.path.exists(aside(rec, unit)):
            return fail(f"{aside(rec, unit)} is there from a removal that stopped — look at it before anything else")
    there = [u for u in units if os.path.exists(os.path.join(rec, u))]
    if not there:                                      # asked again after it was done: say so, change nothing
        return result({"ok": True, "removed": [], "already": True, "backup": a.staged})
    if len(there) != len(units):
        return fail("part of the meeting is gone from here already — nothing was removed",
                    bad=[f"{u}: gone" for u in units if u not in there])
    bad = [b for u in units for b in mismatch(os.path.join(rec, u), u, man)]
    if bad:
        return fail("the source is not the backup's copy — nothing was removed", bad=bad[:20])
    moved = []
    for unit in units:                                 # aside, checked again there, and only then deleted: a file
        os.rename(os.path.join(rec, unit), aside(rec, unit))   # written into a unit after the first check is not lost
        moved.append(unit)
    bad = [b for u in units for b in mismatch(aside(rec, u), u, man)]
    if bad:
        for unit in moved:
            os.rename(aside(rec, unit), os.path.join(rec, unit))
        return fail("the source changed while it was being removed — put back, nothing was removed", bad=bad[:20])
    for unit in units:
        shutil.rmtree(aside(rec, unit))
    # the run's proof that it removed the meeting (after the target verified it): a resume reads it, nothing else
    with open(os.path.join(os.path.dirname(a.staged), "removed.json"), "w", encoding="utf-8") as f:
        json.dump({"removed": units, "at": int(time.time()), "root": a.root}, f)
    return result({"ok": True, "removed": units, "files": len(man["files"]), "backup": a.staged})


# Runs inside the office's meet-start (its python and its Drive client, `server._drive`): `docker exec -i <c> python -`.
DRIVE_CODE = r'''
import json, re, sys
sys.path.insert(0, "/app")
import server
room, stems, trash = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3] == "1"
top = "/" + server.DRIVE_FOLDER
def ls(path):
    st, doc = server._drive("GET", "/api/fs?path=" + server.quote(path))
    return doc or {}
recs = {s + ext for s in stems for ext in (".mp4", ".ogg")}
own = recs | {"תמלול — %s.txt" % room, "כתוביות — %s.vtt" % room}
dates = {m.group(1) for m in (re.search(r"_(\d{4}-\d\d-\d\d)-\d\d-\d\d-\d\d$", s) for s in stems) if m}
out = []
for f in ls(top).get("folders") or []:
    name = str(f.get("name") or "")
    if " · " not in name or name.split(" · ", 1)[1].strip().lower() != room:
        continue
    path = top + "/" + name
    doc = ls(path)
    if name.split(" · ", 1)[0] not in dates or not recs & {x.get("name") for x in doc.get("files") or []}:
        out.append({"path": path, "files": [x.get("name") for x in doc.get("files") or []],
                    "other": ["(not a folder of the recordings moved)"]})
        continue                                       # another meeting of the same room: not this move's to touch
    other = [x.get("name") for x in doc.get("files") or [] if x.get("name") not in own]
    for sub in doc.get("folders") or []:
        inner = ls(path + "/" + str(sub.get("name")))
        if sub.get("name") != ".meet-flow" or inner.get("folders") or any(x.get("name") != "first.json" for x in inner.get("files") or []):
            other.append(str(sub.get("name")) + "/")
    row = {"path": path, "id": (doc.get("folder") or {}).get("id") or f.get("id"),
           "files": [x.get("name") for x in doc.get("files") or []], "other": other}
    if trash and not other:
        st, got = server._drive("POST", "/api/trash", {"ids": [row["id"]]})
        row["trashed"] = int((got or {}).get("count") or 0)
    out.append(row)
print("RESULT " + json.dumps({"ok": True, "folders": out}, ensure_ascii=False))
'''


def cmd_drive(a):
    p = subprocess.run(["docker", "exec", "-i", a.container, "python", "-", a.room, a.stems, "1" if a.trash else "0"],
                       input=DRIVE_CODE, capture_output=True, text=True)
    line = next((x for x in p.stdout.splitlines()[::-1] if x.startswith("RESULT ")), None)
    if p.returncode or not line:
        return fail(f"meet-start's Drive client did not answer: {(p.stderr or p.stdout).strip()[-400:]}")
    print(line, flush=True)
    return 0


def main():
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="host")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("locate")
    s.add_argument("work")
    s.set_defaults(fn=cmd_locate)
    for name, fn in (("list", cmd_list), ("stage", cmd_stage)):
        s = sub.add_parser(name)
        s.add_argument("root")
        s.add_argument("room", type=lambda v: v.strip().lower())
        if name == "stage":
            s.add_argument("staged")
        s.set_defaults(fn=fn)
    s = sub.add_parser("read")
    s.add_argument("path")
    s.add_argument("offset", type=int)
    s.add_argument("length", type=int)
    s.set_defaults(fn=cmd_read)
    s = sub.add_parser("append")
    s.add_argument("path")
    s.add_argument("offset", type=int)
    s.set_defaults(fn=cmd_append)
    s = sub.add_parser("utime")
    s.add_argument("path")
    s.add_argument("mtime", type=int)
    s.set_defaults(fn=cmd_utime)
    s = sub.add_parser("remove")
    s.add_argument("root")
    s.add_argument("staged")
    s.set_defaults(fn=cmd_remove)
    s = sub.add_parser("drive")
    s.add_argument("container")
    s.add_argument("room", type=lambda v: v.strip().lower())
    s.add_argument("stems", help="the recordings' names without .mp4, as a JSON list")
    s.add_argument("--trash", action="store_true")
    s.set_defaults(fn=cmd_drive)
    a = ap.parse_args()
    if getattr(a, "room", None) is not None and not ROOM_RE.fullmatch(a.room):
        return fail(f"{a.room!r} is not a room's name")
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
