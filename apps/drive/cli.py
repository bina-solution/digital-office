"""cli — «קבצים» by path, for agents and for the person at the server's shell.

Runs INSIDE the drive container (the hooks call `dcx exec -T drive python /app/cli.py …`) and talks
to this service's own API on 127.0.0.1, so it needs no address, no sign-in and no key on a command
line. Bytes go through stdin / stdout, so `get` and `put` stream any size.

    ls    [/path]            what is in a folder (folders first)
    stat  /path              one file or folder, as JSON
    get   /path              the file's bytes to stdout
    put   /path [--replace]  stdin into the file at /path (folders made on demand; an existing name is
                             kept and the new file is called «name (2)» unless --replace)
    mkdir /path              get-or-create a folder path
    find  text               files and folders whose name holds the text, with their paths
"""
import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

API = "http://127.0.0.1:8975"


def call(method, path, params=None, body=None, headers=None, stream=False):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    req = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        r = urllib.request.urlopen(req, timeout=3600)
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read() or b"{}").get("error")
        except ValueError:
            msg = None
        sys.exit(f"drive: {msg or e.reason} (HTTP {e.code})")
    return r if stream else json.loads(r.read() or b"{}")


def human(n):
    n = float(n or 0)
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    verb, rest = argv[0], argv[1:]
    if verb == "ls":
        d = call("GET", "/api/fs", {"path": rest[0] if rest else "/"})
        if d.get("kind") == "file":
            f = d["file"]
            print(f"{f['name']}\t{human(f['size'])}\t{f['created']}")
            return 0
        for f in d.get("folders", []):
            print(f"{f['name']}/\t{f.get('count', 0)} files" + (f"\t[{f['system']}]" if f.get("system") else ""))
        for f in d.get("files", []):
            print(f"{f['name']}\t{human(f['size'])}\t{f['created']}")
        return 0
    if verb == "stat":
        print(json.dumps(call("GET", "/api/fs", {"path": rest[0]}), ensure_ascii=False, indent=1))
        return 0
    if verb == "get":
        r = call("GET", "/api/fs/content", {"path": rest[0], "dl": "1"}, stream=True)
        shutil.copyfileobj(r, sys.stdout.buffer, 1 << 20)
        return 0
    if verb == "put":
        if not rest:
            sys.exit("drive: put needs a /path")
        with tempfile.TemporaryFile() as tmp:              # the length must be known before storage takes it
            shutil.copyfileobj(sys.stdin.buffer, tmp, 1 << 20)
            size = tmp.tell()
            tmp.seek(0)
            d = call("PUT", "/api/fs/content", {"path": rest[0], "mode": "replace" if "--replace" in rest else "new"},
                     body=tmp, headers={"Content-Length": str(size), "Content-Type": "application/octet-stream"})
        print(f"{d['path']}\t{human(d['file']['size'])}")
        return 0
    if verb == "mkdir":
        d = call("POST", "/api/fs/mkdir", body=json.dumps({"path": rest[0]}).encode(), headers={"Content-Type": "application/json"})
        print(d["path"])
        return 0
    if verb == "find":
        d = call("GET", "/api/search", {"q": " ".join(rest)})
        for f in d.get("folders", []):
            print(call("GET", f"/api/folder/{urllib.parse.quote(f['id'])}/path")["path"] + "/")
        for f in d.get("files", [])[:100]:
            print(call("GET", f"/api/file/{urllib.parse.quote(f['id'])}")["file"].get("path", f["name"]))
        return 0
    sys.exit(f"drive: unknown verb {verb!r} — ls, stat, get, put, mkdir, find")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
