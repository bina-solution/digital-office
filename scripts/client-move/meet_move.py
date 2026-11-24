#!/usr/bin/env python3
"""meet_move — a client's recorded meetings into its own office's meet, byte for byte (DGO-1924).

A meeting's recording, its page and everything the recorder wrote live in ONE folder of the meet's recordings volume,
`recordings/<session uuid>/` (the mp4, the ogg, capture/holes/silence json, Jibri's metadata.json, and flow/ — the
meeting's page). The folder keeps its uuid on the target, so the MEET item's `meet-recording` key (`<uuid>/<file>`) and
the page's own paths stay true there. Runs in a helper container (`--network none`) with the volumes mounted:

    manifest <staged>                        writes <staged>/manifest.json: every file's size and sha256 (on the SOURCE)
    place <staged> <rec> [--rewrite O=N …] [--redact RX]
                                             each <staged>/recordings/<uuid>/ into <rec>/recordings/<uuid>/: a file
                                             already there with the same bytes is kept, a DIFFERENT one refuses the run
                                             (a meeting is never overwritten); owned like <rec>/recordings (meet-jibri's
                                             user); flow/data.js and flow/flow.json get the source office's addresses
                                             rewritten (pairs applied in the order given: an item's own link before
                                             the host's prefix) and, with --redact, another client's name replaced by
                                             «[לקוח אחר]» (the page's text, as plane_move does to the meeting's item;
                                             the recording itself is the meeting)
    verify <staged> <rec> [--rewrite O=N …] [--redact RX]
                                             every manifest file on the target, its sha256 (the two flow/ files: after
                                             the rewrite)

ORDER ON THE TARGET (apps/meet's workflow): the MEET items are imported FIRST (plane_move, their `meet-recording` key
kept) and the recordings placed after — a recording the target's meet finds with no item is transcribed again.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys

REWRITTEN = ("flow/data.js",           # the page's data: the Plane links of its tasks and the console's address
             "flow/flow.json")         # the meeting's record (title, who, tags, docs): the same links and words
OTHER = "[לקוח אחר]"


def say(msg):
    print("[meet-move] " + msg, file=sys.stderr, flush=True)


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def files_of(root):
    for d, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(d, f)
            yield os.path.relpath(p, root).replace(os.sep, "/"), p


def cmd_manifest(a):
    base = os.path.join(a.staged, "recordings")
    out = {"format": "dgo-meet-move/1", "sessions": sorted(os.listdir(base)), "files": {}}
    for rel, p in files_of(base):
        out["files"][rel] = {"size": os.path.getsize(p), "sha256": sha(p)}
    with open(os.path.join(a.staged, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=0)
    say(f"{len(out['sessions'])} session(s), {len(out['files'])} file(s), "
        f"{sum(x['size'] for x in out['files'].values())} bytes")
    return 0


def load(staged):
    with open(os.path.join(staged, "manifest.json"), encoding="utf-8") as f:
        m = json.load(f)
    if m.get("format") != "dgo-meet-move/1":
        raise SystemExit("[meet-move] not a dgo-meet-move/1 manifest")
    return m


def changes(a):
    """(the --rewrite pairs, the --redact pattern or None): what a REWRITTEN file gets on its way to the target."""
    return [x.split("=", 1) for x in a.rewrite or []], (re.compile(a.redact) if a.redact else None)


def expected(rel, src, ch):
    pairs, rx = ch
    with open(src, "rb") as f:
        b = f.read()
    if (pairs or rx) and rel.split("/", 1)[-1] in REWRITTEN:
        t = b.decode("utf-8")
        for o, n in pairs:
            t = t.replace(o, n)
        if rx:
            t = rx.sub(OTHER, t)
        b = t.encode("utf-8")
    return b


def cmd_place(a):
    m = load(a.staged)
    ch = changes(a)
    src_base, dst_base = os.path.join(a.staged, "recordings"), os.path.join(a.rec, "recordings")
    if not os.path.isdir(dst_base):
        raise SystemExit(f"[meet-move] {dst_base} is not there — is this the meet's recordings volume?")
    st = os.stat(dst_base)
    made = kept = 0
    # first every check, then every write: a run that would overwrite anything writes nothing
    plan = []
    for rel, info in sorted(m["files"].items()):
        src = os.path.join(src_base, rel)
        if os.path.getsize(src) != info["size"] or sha(src) != info["sha256"]:   # the staged copy is never rewritten
            raise SystemExit(f"[meet-move] {rel}: the staged copy is not the source's (manifest) — refusing")
        # only the two small flow files are read whole (to rewrite them): a recording is hashed as it streams
        data = expected(rel, src, ch) if rel.split("/", 1)[-1] in REWRITTEN and any(ch) else None
        want = hashlib.sha256(data).hexdigest() if data is not None else info["sha256"]
        dst = os.path.join(dst_base, rel)
        if os.path.exists(dst):
            if sha(dst) == want:
                kept += 1; continue
            raise SystemExit(f"[meet-move] {dst} is there with other bytes — a meeting is never overwritten; refusing "
                             f"(nothing was written)")
        plan.append((rel, dst, data, src))
    # Jibri's metadata.json last: it is what tells the target's meet that a recording is finished (DGO-1861)
    plan.sort(key=lambda p: p[0].endswith("/metadata.json"))
    for rel in m["files"]:
        stale = os.path.join(dst_base, rel) + ".part"     # a run that died mid-write left it: never a file of the move
        if os.path.exists(stale) and not a.dry_run:
            os.remove(stale)
    for rel, dst, data, src in plan:
        if a.dry_run:
            made += 1; continue
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        tmp = dst + ".part"
        if data is None:
            shutil.copyfile(src, tmp)
            # its time too: the target's meet lists recordings by it, and a «פגישות» row without a page for 14 days
            # from it (DGO-1861) — a copy stamped «now» was the newest recording there, whatever day it was made
            t = os.stat(src)
            os.utime(tmp, ns=(t.st_atime_ns, t.st_mtime_ns))
        else:
            with open(tmp, "wb") as f:
                f.write(data)
        os.replace(tmp, dst)
        made += 1
    if not a.dry_run:          # owned like the meet's own recordings — only what this move put there, and its folders
        paths = set()
        for rel in m["files"]:
            parts = rel.split("/")
            paths.update(os.path.join(dst_base, *parts[:i]) for i in range(1, len(parts) + 1))
        for n in sorted(paths):
            try:
                os.chown(n, st.st_uid, st.st_gid)
            except OSError as e:
                say(f"{n} stays root's: {e}")
    print("RESULT " + json.dumps({"sessions": m["sessions"], "created": made, "kept": kept,
                                  "files": len(m["files"]), "dry_run": a.dry_run}))
    return 0


def cmd_verify(a):
    m = load(a.staged)
    ch = changes(a)
    bad = []
    for rel, info in sorted(m["files"].items()):
        dst = os.path.join(a.rec, "recordings", rel)
        if not os.path.isfile(dst):
            bad.append(f"{rel}: missing"); continue
        if rel.split("/", 1)[-1] in REWRITTEN and any(ch):
            ok = sha(dst) == hashlib.sha256(expected(rel, os.path.join(a.staged, "recordings", rel), ch)).hexdigest()
        else:
            ok = os.path.getsize(dst) == info["size"] and sha(dst) == info["sha256"]
        if not ok:
            bad.append(f"{rel}: other bytes")
    print("VERIFY " + json.dumps({"files": len(m["files"]), "bad": bad[:40]}))
    return 1 if bad else 0


def main():
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="meet_move")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("manifest")
    s.add_argument("staged")
    s.set_defaults(fn=cmd_manifest)
    for name, fn in (("place", cmd_place), ("verify", cmd_verify)):
        s = sub.add_parser(name)
        s.add_argument("staged")
        s.add_argument("rec")
        s.add_argument("--rewrite", action="append", metavar="OLD=NEW")
        s.add_argument("--redact", metavar="RX", help="another client's name in the page's data → «[לקוח אחר]»")
        if name == "place":
            s.add_argument("--dry-run", action="store_true")
        s.set_defaults(fn=fn)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
