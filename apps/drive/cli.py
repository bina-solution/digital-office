"""cli — «קבצים» from the shell: every drive of the office, by path (DGO-1390).

A drive is one of the office's connections: a profile of the office's own storage, a Google account, a
Google service account. `-p <drive>` names one — its profile id, its address, its name or its connection
id (`profile list` shows them); without it the office's default drive is used (the one agents and
automations work on), and a command that writes says so on stderr.

    profile list [--json]               every drive: what it is, and which is the default (*)
    profile show <drive>                one drive, and whether it answers right now (a real check)
    profile default <drive>             make it the default of agents, automations and this CLI

    files list [path] [--json]          the files of a folder (default /), one a line
    folders list [path] [--json]        the folders of a folder
    ls [path]                           both, folders first
    tree [path] [--depth N]             the folders under a folder
    file <path>                         one file or folder, as JSON (alias: stat)
    get <path>                          the file's bytes to stdout (alias: download)
    put <path> [--replace]              stdin into the file at <path>: folders are made on the way, an
                                        existing name is kept and this one is «name (2)» unless --replace
                                        (alias: upload)
    mkdir <path>                        get-or-create a folder path
    mv <path> <folder path>             move a file or a folder into another folder
    rename <path> <new name>
    rm <path>                           to the drive's trash (alias: trash) — never a permanent delete
    restore <name>                      back out of the trash
    find <text> [--json]                files and folders whose name holds the text, with their paths
    link <path>                         the file's link (the office's own: anyone who has it can download;
                                        Google's: whoever has access)
    storage                             what the drive holds, and its ceiling

    …any of the above:  -p <drive>  (or --profile, --drive)

Runs INSIDE the office network (the hooks run it in the drive's own container, or — on an office that
does not run the drive — in the credential plane's container against the linked office's door) and talks
to the drive's own API (DRIVE_API, default the container's loopback): no address, no sign-in and no key on
a command line. Bytes go through stdin/stdout, so `get` and `put` stream any size.
"""
import json
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

API = (os.environ.get("DRIVE_API") or "http://127.0.0.1:8975").rstrip("/")
KIND = {"drive_local": "אחסון הלשכה", "drive_google_oauth": "Google Drive",
        "drive_google_service_account": "Google Drive · חשבון שירות"}
DRIVE = {"cid": None}           # the connection every call names, once -p resolved it


def note(msg):
    print(msg, file=sys.stderr)


def call(method, path, params=None, body=None, headers=None, stream=False, scoped=True):
    params = dict(params or {})
    if scoped and DRIVE["cid"]:
        params["connection_id"] = DRIVE["cid"]
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    if isinstance(body, (dict, list)):
        body, headers = json.dumps(body).encode(), {**(headers or {}), "Content-Type": "application/json"}
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error")
        except ValueError:
            msg = None
        sys.exit(f"drive: {msg or e.reason} (HTTP {e.code})")
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        sys.exit(f"drive: the drive does not answer at {API} ({getattr(e, 'reason', e)})")
    return r if stream else json.loads(r.read() or b"{}")


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


# ── the drives ──────────────────────────────────────────────────────────────────
def drives():
    d = call("GET", "/connections", scoped=False)
    return d.get("connections") or [], d.get("active")


def name_of(c):
    if c.get("protocol") == "drive_local":
        return c.get("label") or c.get("profile_id") or c.get("id")
    return c.get("account_hint") or c.get("label") or c.get("id")


def pick(word):
    """The one drive a `-p` word names: its connection id, profile id, address or name — exactly, then
    as the start of one; two drives that answer the same word are named, never guessed between."""
    conns, _ = drives()
    w = str(word or "").strip().lower()
    keys = lambda c: [str(c.get(k) or "").lower() for k in ("id", "profile_id", "account_hint")] + [name_of(c).lower()]  # noqa: E731
    hits = [c for c in conns if w in keys(c)] or [c for c in conns if any(k.startswith(w) for k in keys(c) if k)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        sys.exit(f"drive: no drive is called {word!r} — `profile list` shows them")
    sys.exit(f"drive: {word!r} names {len(hits)} drives — " + ", ".join(f"{name_of(c)} ({c['id']})" for c in hits))


def say_default(verb):
    """A write with no -p goes to the office's default drive: said, never silent."""
    if DRIVE["cid"]:
        return
    conns, active = drives()
    c = next((x for x in conns if x.get("id") == active), None)
    if c:
        note(f"drive: {verb} on {name_of(c)} ({KIND.get(c.get('protocol'), c.get('protocol'))}) — the office's default; -p names another")


def profile(args, as_json):
    sub = args[0] if args else "list"
    if sub in ("list", "ls"):
        conns, active = drives()
        if as_json:
            print(json.dumps({"active": active, "drives": [{"id": c.get("id"), "name": name_of(c), "kind": c.get("protocol"),
                                                            "profile_id": c.get("profile_id"), "account": c.get("account_hint"),
                                                            "default": c.get("id") == active, "status": c.get("status")}
                                                           for c in conns]}, ensure_ascii=False, indent=1))
            return 0
        for c in conns:
            mark = "*" if c.get("id") == active else " "
            who = c.get("profile_id") if c.get("protocol") == "drive_local" else c.get("account_hint")
            print(f"{mark} {name_of(c)}\t{KIND.get(c.get('protocol'), c.get('protocol'))}\t{who or ''}\t{c.get('id')}"
                  + (f"\t[{c.get('status')}]" if c.get("status") not in (None, "ok") else ""))
        if not conns:
            note("drive: no drive is connected")
        return 0
    if sub in ("show", "check", "probe"):
        c = pick(args[1] if len(args) > 1 else "")
        p = call("GET", f"/connections/{urllib.parse.quote(c['id'])}/probe", scoped=False)
        print(json.dumps({"id": c["id"], "name": name_of(c), "kind": c.get("protocol"), "ok": p.get("ok"),
                          "reason": p.get("reason"), "account": p.get("account_hint") or c.get("account_hint")},
                         ensure_ascii=False, indent=1))
        return 0 if p.get("ok") else 1
    if sub in ("default", "select", "use"):
        c = pick(args[1] if len(args) > 1 else "")
        call("POST", "/connections/select", body={"id": c["id"]}, scoped=False)
        print(f"the default drive is now {name_of(c)} ({c['id']})")
        return 0
    sys.exit("drive: profile list | show <drive> | default <drive>")


# ── paths ───────────────────────────────────────────────────────────────────────
def at(path):
    """{kind, file|folder, …} at a path — the drive's own answer (api/fs)."""
    return call("GET", "/api/fs", {"path": path or "/"})


def item_of(path):
    """(id, 'file'|'folder') of what is at a path; the top is not an item."""
    d = at(path)
    if d.get("kind") == "file":
        return d["file"]["id"], "file"
    fid = (d.get("folder") or {}).get("id")
    if not fid:
        sys.exit(f"drive: {path!r} is the top of the drive — name what is in it")
    return fid, "folder"


def ls(path, what="both", as_json=False):
    d = at(path)
    if d.get("kind") == "file":
        f = d["file"]
        print(json.dumps(f, ensure_ascii=False, indent=1) if as_json else f"{f['name']}\t{human(f.get('size'))}\t{f.get('created', '')}")
        return 0
    folders = d.get("folders", []) if what in ("both", "folders") else []
    files = d.get("files", []) if what in ("both", "files") else []
    if as_json:
        print(json.dumps({"path": d.get("path"), "folders": folders, "files": files}, ensure_ascii=False, indent=1))
        return 0
    for f in sorted(folders, key=lambda x: x.get("name") or ""):
        line = f"{f['name']}/" + (f"\t{f['count']} files" if f.get("count") is not None else "")
        print(line + (f"\t[{f['system']}]" if f.get("system") else ""))
    for f in files:
        print(f"{f['name']}\t{human(f.get('size'))}\t{f.get('created', '')}")
    return 0


def tree(path, depth):
    rows = call("GET", "/api/folders").get("folders", [])
    kids = {}
    for f in rows:
        kids.setdefault(f.get("parent") or "", []).append(f)
    top = "" if (path or "/").strip("/") == "" else item_of(path)[0]

    def walk(fid, indent):
        if indent >= depth:
            return
        for f in sorted(kids.get(fid, []), key=lambda x: x.get("name") or ""):
            if not fid and f.get("shared"):
                continue
            print("  " * indent + f["name"] + "/")
            walk(f["id"], indent + 1)
    print((path or "/").rstrip("/") or "/")
    walk(top, 1)
    return 0


def main(argv):
    args, as_json, word = [], False, None
    it = iter(argv)
    for a in it:
        if a in ("-p", "--profile", "--drive"):
            word = next(it, None)
        elif a.startswith("--profile=") or a.startswith("--drive="):
            word = a.split("=", 1)[1]
        elif a == "--json":
            as_json = True
        else:
            args.append(a)
    if not args or args[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if word:
        DRIVE["cid"] = pick(word)["id"]
    verb, rest = args[0], args[1:]
    if verb in ("profile", "profiles", "drives"):
        return profile(rest, as_json)
    if verb in ("files", "folders") and rest[:1] == ["list"]:
        return ls(rest[1] if len(rest) > 1 else "/", verb, as_json)
    if verb == "ls":
        return ls(rest[0] if rest else "/", "both", as_json)
    if verb == "tree":
        depth = int(rest[rest.index("--depth") + 1]) if "--depth" in rest else 3
        return tree(next((r for r in rest if not r.startswith("--") and not r.isdigit()), "/"), depth + 1)
    if verb in ("file", "stat"):
        print(json.dumps(at(rest[0] if rest else "/"), ensure_ascii=False, indent=1))
        return 0
    if verb in ("get", "download"):
        if not rest:
            sys.exit("drive: get needs a /path")
        r = call("GET", "/api/fs/content", {"path": rest[0], "dl": "1"}, stream=True)
        shutil.copyfileobj(r, sys.stdout.buffer, 1 << 20)
        return 0
    if verb in ("put", "upload"):
        if not rest:
            sys.exit("drive: put needs a /path")
        say_default("put")
        with tempfile.TemporaryFile() as tmp:              # the length must be known before storage takes it
            shutil.copyfileobj(sys.stdin.buffer, tmp, 1 << 20)
            size = tmp.tell()
            tmp.seek(0)
            d = call("PUT", "/api/fs/content", {"path": rest[0], "mode": "replace" if "--replace" in rest else "new"},
                     body=tmp, headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"})
        print(f"{d['path']}\t{human(d['file'].get('size'))}")
        return 0
    if verb == "mkdir":
        say_default("mkdir")
        print(call("POST", "/api/fs/mkdir", body={"path": rest[0]})["path"])
        return 0
    if verb in ("mv", "move"):
        if len(rest) < 2:
            sys.exit("drive: mv <path> <folder path>")
        src, _ = item_of(rest[0])
        dest = at(rest[1])
        if dest.get("kind") != "folder":
            sys.exit(f"drive: {rest[1]!r} is not a folder")
        say_default("mv")
        call("POST", "/api/move", body={"ids": [src], "to": (dest.get("folder") or {}).get("id") or ""})
        print(f"{rest[0]} → {dest.get('path') or rest[1]}")
        return 0
    if verb == "rename":
        if len(rest) < 2:
            sys.exit("drive: rename <path> <new name>")
        fid, _ = item_of(rest[0])
        say_default("rename")
        call("POST", "/api/rename", body={"id": fid, "name": rest[1]})
        print(f"{rest[0]} → {rest[1]}")
        return 0
    if verb in ("rm", "trash"):
        if not rest:
            sys.exit("drive: rm <path>")
        fid, kind = item_of(rest[0])
        say_default("rm")
        call("POST", "/api/trash", body={"ids": [fid]})
        print(f"{rest[0]} — in the trash ({kind}); `restore` brings it back")
        return 0
    if verb == "restore":
        if not rest:
            sys.exit("drive: restore <name>")
        d = call("GET", "/api/files", {"trash": "1"})
        hits = [f for f in (d.get("files") or []) + (d.get("folders") or []) if f.get("name") == rest[0]]
        if len(hits) != 1:
            sys.exit(f"drive: {len(hits)} items in the trash are called {rest[0]!r}" if hits else f"drive: nothing in the trash is called {rest[0]!r}")
        call("POST", "/api/trash", body={"ids": [hits[0]["id"]], "restore": True})
        print(f"{rest[0]} — restored")
        return 0
    if verb == "find":
        d = call("GET", "/api/search", {"q": " ".join(rest)})
        out = []
        for f in d.get("folders", []):
            out.append(call("GET", f"/api/folder/{urllib.parse.quote(f['id'])}/path")["path"] + "/")
        for f in d.get("files", [])[:100]:
            out.append(call("GET", f"/api/file/{urllib.parse.quote(f['id'])}")["file"].get("path", f["name"]))
        print(json.dumps(out, ensure_ascii=False, indent=1) if as_json else "\n".join(out))
        return 0
    if verb == "link":
        d = at(rest[0] if rest else "")
        if d.get("kind") != "file":
            sys.exit("drive: link names a file")
        print(d["file"].get("link") or "")
        return 0
    if verb == "storage":
        s = call("GET", "/api/storage")
        if as_json:
            print(json.dumps(s, ensure_ascii=False, indent=1))
        else:
            print(f"{human(s.get('used'))}" + (f" of {human(s['limit'])} ({s.get('percent')}%)" if s.get("limit") else "")
                  + (f" · {s['files']} files" if isinstance(s.get("files"), int) else "")
                  + (f" · {human(s['trash_used'])} in the trash" if s.get("trash_used") else ""))
        return 0
    sys.exit(f"drive: unknown verb {verb!r} — `bbox drive help` lists them")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
