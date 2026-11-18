#!/usr/bin/env python3
"""drive_move — a folder of one office's «קבצים» into another office's, whole and idempotent (DGO-1924).

Runs INSIDE an office's drive container (copied there; README.md has the commands), talking to
that office's own «קבצים» at http://127.0.0.1:8975 — the same API every agent uses (apps/drive/AGENT.md).

    export <path> [--connection ID]            > bundle.tar   the folder, recursively, and a manifest (sha256 per file)
    import <dest> [--connection ID] [--dry-run] < bundle.tar   each file PUT under <dest>; one already there with the same
                                                               size is kept (`mode=exclusive`: a file is never doubled
                                                               as «name (2)», never replaced)
    verify <dest> [--connection ID]            < bundle.tar   every manifest file under <dest>, its size and sha256

A Google Doc has no bytes of its own: `content` gives an export of it, and that export is what is carried.
"""
import argparse
import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8975"


def say(msg):
    print("[drive-move] " + msg, file=sys.stderr, flush=True)


def call(method, route, conn, data=None, ctype=None, raw=False, **q):
    if conn:
        q["connection_id"] = conn
    url = API + route + ("?" + urllib.parse.urlencode(q) if q else "")
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": ctype} if ctype else {})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                b = r.read()
                return r.status, (b if raw else (json.loads(b) if b else {}))
        except urllib.error.HTTPError as e:
            if e.code in (502, 503, 504) and attempt < 3:
                time.sleep(5 * (attempt + 1)); continue
            return e.code, e.read()[:300]
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 3:
                time.sleep(5 * (attempt + 1)); continue
            return -1, str(e)
    return -1, "gave up"


def listing(path, conn):
    code, d = call("GET", "/api/fs", conn, path=path)
    if code == 404:
        return None
    if code != 200:
        raise SystemExit(f"[drive-move] cannot list {path}: HTTP {code} {d!r}")
    return d


def walk(path, conn, rel=""):
    d = listing(path, conn)
    if d is None:
        raise SystemExit(f"[drive-move] no folder {path}")
    for f in d.get("files") or []:
        size = f.get("size")
        yield rel + f["name"], path.rstrip("/") + "/" + f["name"], int(size) if size is not None else -1
    for f in d.get("folders") or []:
        yield from walk(path.rstrip("/") + "/" + f["name"], conn, rel + f["name"] + "/")


def cmd_export(a):
    out = tarfile.open(fileobj=sys.stdout.buffer, mode="w|")
    manifest = []
    for rel, full, _ in walk(a.path, a.connection):
        code, blob = call("GET", "/api/fs/content", a.connection, raw=True, path=full)
        if code != 200:
            raise SystemExit(f"[drive-move] {full}: HTTP {code}")
        ti = tarfile.TarInfo("files/" + rel)
        ti.size, ti.mtime = len(blob), int(time.time())
        out.addfile(ti, io.BytesIO(blob))
        manifest.append({"path": rel, "size": len(blob), "sha256": hashlib.sha256(blob).hexdigest()})
    m = json.dumps({"format": "dgo-drive-move/1", "from": a.path, "files": manifest}, ensure_ascii=False).encode()
    ti = tarfile.TarInfo("manifest.json")
    ti.size, ti.mtime = len(m), int(time.time())
    out.addfile(ti, io.BytesIO(m))
    out.close()
    say(f"{a.path}: {len(manifest)} file(s), {sum(x['size'] for x in manifest)} bytes")
    return 0


def read_bundle():
    t = tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()), mode="r:")
    blobs, manifest = {}, None
    for m in t.getmembers():
        if m.name == "manifest.json":
            manifest = json.load(t.extractfile(m))
        elif m.isfile() and m.name.startswith("files/"):
            blobs[m.name[len("files/"):]] = t.extractfile(m).read()
    if not manifest or manifest.get("format") != "dgo-drive-move/1":
        raise SystemExit("[drive-move] not a dgo-drive-move/1 bundle")
    for f in manifest["files"]:
        b = blobs.get(f["path"])
        if b is None or hashlib.sha256(b).hexdigest() != f["sha256"]:
            raise SystemExit(f"[drive-move] {f['path']}: the bundle's bytes are not the manifest's — refusing")
    return manifest, blobs


def here(dest, conn):
    """{relative path: size} of what is under <dest> now ({} when it is not there yet)."""
    if listing(dest, conn) is None:
        return {}
    return {rel: size for rel, _, size in walk(dest, conn)}


def cmd_import(a):
    manifest, blobs = read_bundle()
    have = here(a.dest, a.connection)
    made = kept = 0
    clash = [f"{f['path']} ({have[f['path']]} ≠ {f['size']} bytes)" for f in manifest["files"]
             if f["path"] in have and have[f["path"]] != f["size"]]
    if clash:      # every check before the first write: a refused run has put nothing
        raise SystemExit(f"[drive-move] under {a.dest}, another file of the same name is there: {clash[:10]} — a "
                         f"person's file is never replaced; refusing (nothing was written)")
    for f in manifest["files"]:
        if have.get(f["path"]) == f["size"]:
            kept += 1; continue
        if a.dry_run:
            say(f"would put {f['path']}"); made += 1; continue
        code, out = call("PUT", "/api/fs/content", a.connection, data=blobs[f["path"]],
                         ctype="application/octet-stream", path=a.dest.rstrip("/") + "/" + f["path"], mode="exclusive")
        if code not in (200, 201):
            raise SystemExit(f"[drive-move] {f['path']}: HTTP {code} {out!r}")
        made += 1
    print("RESULT " + json.dumps({"dest": a.dest, "created": made, "kept": kept, "files": len(manifest["files"]),
                                  "dry_run": a.dry_run}, ensure_ascii=False))
    return 0


def cmd_verify(a):
    manifest, _ = read_bundle()
    have = here(a.dest, a.connection)
    bad = [f["path"] for f in manifest["files"] if have.get(f["path"]) != f["size"]]
    for f in manifest["files"]:                   # and the bytes themselves, read back
        if f["path"] in bad:
            continue
        code, blob = call("GET", "/api/fs/content", a.connection, raw=True, path=a.dest.rstrip("/") + "/" + f["path"])
        if code != 200 or hashlib.sha256(blob).hexdigest() != f["sha256"]:
            bad.append(f["path"])
    print("VERIFY " + json.dumps({"dest": a.dest, "files": len(manifest["files"]), "missing_or_different": bad[:40]},
                                 ensure_ascii=False))
    return 1 if bad else 0


def main():
    for stream in (sys.stdout, sys.stderr):    # Hebrew on every line: UTF-8 whatever the console's code page (G10)
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(prog="drive_move")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn, arg in (("export", cmd_export, "path"), ("import", cmd_import, "dest"), ("verify", cmd_verify, "dest")):
        s = sub.add_parser(name)
        s.add_argument(arg)
        s.add_argument("--connection", help="the drive (connection id); default: the office's default drive")
        if name == "import":
            s.add_argument("--dry-run", action="store_true")
        s.set_defaults(fn=fn)
    a = ap.parse_args()
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
