"""test_engines — «קבצים» after the split (DGO-1500, ENGINES.md): the generic app, its engines, one protocol.

    python3 apps/drive/test_engines.py        (flask + requests: the drive's image has them)

What is held: the engines are found BY NAME in the compiled registry (a tile row or a door row, and an
address override), never from a list here; every vault row of every engine is one list, each said by its
own engine, and the rows of an engine that does not answer stay, saying so; the routes callers use keep
their answers — a folder, a file's bytes with Range, a stored upload, the §3 ops and their refusal of a
call that names no drive, a search, /readyz, /manifest, /providers, /engines; an engine's errors keep their
status and their shape (a missing file 404, an account that cannot sign in 503, a key of another profile
403); a profile key travels to the engine; what an engine keeps for itself (/engine/*, /file/d/*) is handed
to it verbatim, with the bound drive named for the screen and never taken from the caller; the copies of
the protocol's engine side are equal in every engine. The engine here is the real engine_rpc.py over an
in-memory drive; the vault is a stand-in. No network.
"""
import hashlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
APPS = os.path.dirname(HERE)
sys.path.insert(0, HERE)
TMP = tempfile.mkdtemp(prefix="drive-engines-")
os.environ["DRIVE_REGISTRY_DIR"] = os.path.join(TMP, "registry")
os.environ["ACTIVE_PATH"] = os.path.join(TMP, "active.json")
os.environ["EXTENSIONS_PATH"] = os.path.join(TMP, "extensions.json")
os.environ["DRIVE_UPLOAD_DIR"] = os.path.join(TMP, "uploads")
os.environ["DRIVE_ENGINE_ROUTES"] = os.path.join(TMP, "engine-routes.json")
os.makedirs(os.environ["DRIVE_REGISTRY_DIR"])
os.makedirs(os.environ["DRIVE_UPLOAD_DIR"])

import requests  # noqa: E402
from flask import Flask, Response, jsonify, request  # noqa: E402

FAILS = []


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── the stand-ins: a vault, and an engine over the REAL engine_rpc.py ────────────────────────────────────
rpc = _load("engine_rpc_under_test", os.path.join(APPS, "drive-local", "engine_rpc.py"))

VAULT = [{"id": "drive_local-admin", "protocol": "drive_local", "label": "admin", "account_hint": "admin"},
         {"id": "drive_local-user2", "protocol": "drive_local", "label": "user2", "account_hint": "user2"},
         {"id": "drive_other-x", "protocol": "drive_other", "label": "x", "account_hint": "x@example.com"}]
vault = Flask("vault")


@vault.get("/api/instances")
def v_list():
    import fnmatch
    pat = request.args.get("protocol") or "*"
    return jsonify({"instances": [i for i in VAULT if fnmatch.fnmatch(i["protocol"], pat)]})


@vault.post("/api/instances")
def v_add():
    b = request.get_json()
    row = {"id": f"{b['protocol']}-{len(VAULT)}", "protocol": b["protocol"], "label": b["label"],
           "account_hint": b.get("account_hint")}
    VAULT.append(row)
    return jsonify(row), 201


FILES = {"lf1": {"id": "lf1", "name": "חוזה.pdf", "folder": "", "size": 11, "mime": "application/pdf"}}
BYTES = {"lf1": b"%PDF-hello!"}
SEEN = {"keys": [], "acting": []}
KEYS = {"key-admin": "admin", "key-user2": "user2"}


class FakeDrive:
    """One profile's drive, in memory, with the in-process adapters' method names and shapes."""
    protocol = "drive_local"

    def __init__(self, cid):
        self.cid, self.profile_id = cid, cid.split("-", 1)[1]

    def probe(self):
        return None

    def folders(self):
        return [{"id": "ld1", "name": "מסמכים", "parent": None, "count": 1}]

    def files(self, folder="", trashed=False, view="", created_after=None, limit=1000, offset=0):
        return [f for f in FILES.values() if f["folder"] == folder]

    def _file(self, fid):
        return FILES.get(fid)

    def search(self, term, limit=200):
        return [f for f in FILES.values() if term in f["name"]]

    def views(self):
        return ["recent", "starred"]

    def star(self, ids, on=True):
        return {"ok": True, "count": len(ids)}

    def trash(self, ids):
        # marked, not removed: a file's id is made from how many there are (store_file)
        for fid in ids:
            if fid in FILES:
                FILES[fid]["trashed"] = True
        return {"ok": True, "count": len(ids)}

    def resolve_path(self, path):
        if path in ("/", ""):
            return ["folder", {"id": "", "path": "/", "name": ""}]
        hit = next((f for f in FILES.values() if "/" + f["name"] == path and not f.get("trashed")), None)
        return ["file", hit] if hit else None

    def ensure_path(self, path, system=None):
        return ""

    def path_of(self, folder):
        return "/"

    def free_name(self, folder, name):
        return name

    def content(self, fid, range_header=None, want="inline"):
        if fid not in BYTES:
            raise rpc.EngineError("הקובץ אינו קיים בדרייב של הפרופיל הזה", 404)
        data = BYTES[fid]
        if range_header:
            a, b = range_header.split("=")[1].split("-")
            part = data[int(a):int(b) + 1]
            return 206, {"Content-Type": "application/pdf", "Content-Range": f"bytes {a}-{b}/{len(data)}",
                         "Content-Length": str(len(part)), "Content-Security-Policy": "sandbox"}, iter([part])
        return 200, {"Content-Type": "application/pdf", "Content-Length": str(len(data)),
                     "Content-Security-Policy": "sandbox"}, iter([data])

    def store_file(self, src, size, md5, name, mime, folder="", oid=None):
        data = src.read()
        assert len(data) == size and hashlib.md5(data).hexdigest() == md5
        fid = "lf%d" % (len(FILES) + 1)
        FILES[fid] = {"id": fid, "name": name, "folder": folder, "size": size, "mime": mime or "", "by": self.cid}
        BYTES[fid] = data
        return FILES[fid]

    def op_list(self, folder_id="", limit=100, *a):
        return [{"id": f["id"], "name": f["name"]} for f in FILES.values()][:int(limit)]

    def op_store(self, src, size, md5, name, mime, folder=""):
        item = self.store_file(src, size, md5, name, mime, folder)
        return {"id": item["id"], "name": item["name"], "md5Checksum": md5, "kind": "drive#file"}

    def op_upload(self, folder_id, name, mime, data):
        raise AssertionError("a streamed upload must not be read whole")


class AuthBroken(Exception):
    pass


class FakeEngine:
    def ops(self):
        return {"for": "drive", "id": "local", "kind": "engine", "service": "drive-local",
                "routes": ["/engine/", "/file/d/"], "protocols": {"drive_local": {"private": True}},
                "engines": [{"id": "drive_local", "name": "אחסון הלשכה"}],
                "providers": [{"id": "local", "name": "אחסון הלשכה", "auth_methods": []}],
                "oauth": {"demo": {"grant": "demo-grant", "provider": "Demo", "connected": "Demo connected."}}}

    def adapter(self, cid):
        if cid == "drive_local-broken":
            raise AuthBroken("ההרשאה פגה — יש לחבר מחדש")
        if not any(i["id"] == cid for i in VAULT):
            raise rpc.EngineError(f"unknown connection {cid!r}", 404)
        return FakeDrive(cid)

    def as_error(self, e):
        return rpc.EngineError(str(e), 503, "auth") if isinstance(e, AuthBroken) else None

    def check_key(self, cid, key):
        SEEN["keys"].append(key)
        if key not in KEYS:
            raise rpc.EngineError("מפתח הפרופיל אינו תקף", 401, "profile")
        if KEYS[key] != cid.split("-", 1)[1]:
            raise rpc.EngineError("המפתח שייך לפרופיל אחר", 403, "profile")

    def accounts(self, instances):
        # the fields drive-local gives (engine.py Engine.accounts)
        return [dict(i, engine=i["protocol"], is_private=True, app="drive", profile_id=i["account_hint"],
                     label={"admin": "מנהל"}.get(i["account_hint"], i["label"]), profile_status="active",
                     is_admin=i["account_hint"] == "admin", primary=True,
                     default=i["account_hint"] == "admin") for i in instances]

    def connect(self, b):
        return {"error": "no"}, 400

    def disconnect(self, cid):
        return {"error": "a profile is removed in «ניהול פרופילים»"}, 400


engine = Flask("drive-local")
engine.register_blueprint(rpc.blueprint(FakeEngine()))


@engine.get("/engine/whoami")
def e_whoami():
    # as drive-local does: a key, else the drive «קבצים» says it is bound to — nothing else the request carries
    SEEN["acting"].append(dict(request.headers))
    key = request.headers.get("X-Drive-Profile-Key")
    if key and key not in KEYS:
        return jsonify({"error": "מפתח הפרופיל אינו תקף"}), 401
    if key:
        pid = KEYS[key]
    else:
        b = requests.get("http://drive:8975/connections/active").json()
        pid = (b.get("id") or "-").split("-", 1)[1] if b.get("is_private") else None
    return jsonify({"ok": True, "profile": {"id": pid, "is_admin": pid == "admin"}, "is_admin": pid == "admin"})


@engine.get("/file/d/<oid>/view")
def e_link(oid):
    SEEN["link"] = dict(request.headers)
    return Response(BYTES.get(oid, b""), mimetype="application/pdf", headers={"X-Served-By": "drive-local"})


# a LINKED office's door that claims too much: the office's private storage, prefixes, a consent door
evil = Flask("drive-a")


@evil.get("/ops")
def evil_ops():
    return jsonify({"ok": True, "interface": "drive-engine.v1", "for": "drive", "id": "a", "kind": "engine",
                    "routes": ["/api/files", "/l", "/upload"], "protocols": {"drive_local": {"private": False}},
                    "oauth": {"google": {"grant": "theirs"}}, "providers": [], "engines": []})


# ── requests, routed to the stand-ins by host ────────────────────────────────────────────────────────────
HOSTS = {"connections:8990": vault.test_client(), "drive-local:8988": engine.test_client(),
         "drive-a.evil:9999": evil.test_client()}
DOWN = set()


class _Raw:
    def __init__(self, data):
        self.data = data

    def stream(self, n=65536, decode_content=True):
        for i in range(0, len(self.data), n):
            yield self.data[i:i + n]


class Resp:
    def __init__(self, r):
        self.status_code, self.headers, self.content = r.status_code, r.headers, r.get_data()
        self.ok = self.status_code < 400
        self.text = self.content.decode("utf-8", "replace")
        self.raw = _Raw(self.content)

    def json(self):
        return json.loads(self.content)

    def iter_content(self, n=65536):
        for i in range(0, len(self.content), n):
            yield self.content[i:i + n]

    def close(self):
        pass

    def raise_for_status(self):
        if not self.ok:
            raise requests.HTTPError(str(self.status_code))


def route(method, url, params=None, json=None, data=None, headers=None, **_kw):
    u = urllib.parse.urlsplit(url)
    if u.netloc in DOWN or u.netloc not in HOSTS:
        raise requests.ConnectionError(f"no route to {u.netloc}")
    q = urllib.parse.urlencode(params or {}, doseq=True)
    path = u.path + ("?" + (u.query + "&" if u.query else "") + q if q or u.query else "")
    body = data.read() if hasattr(data, "read") else data
    return Resp(HOSTS[u.netloc].open(path, method=method, json=json, data=body, headers=headers or {}))


requests.get = lambda url, **kw: route("GET", url, **kw)
requests.post = lambda url, **kw: route("POST", url, **kw)
requests.put = lambda url, **kw: route("PUT", url, **kw)
requests.delete = lambda url, **kw: route("DELETE", url, **kw)
requests.request = lambda method, url, **kw: route(method, url, **kw)

# the compiled registry: the engine is a door with no tile (link: true), so it is a `services` row
with open(os.path.join(os.environ["DRIVE_REGISTRY_DIR"], "office.apps.json"), "w", encoding="utf-8") as f:
    json.dump({"apps": [{"app": "drive", "alias": "drive", "port": 8975, "service": "drive"}],
               "services": [{"app": "drive-local", "alias": "drive-local", "port": 8988, "service": "drive-local"}]}, f)
with open(os.path.join(os.environ["DRIVE_REGISTRY_DIR"], "remote.evil.drive-a.json"), "w", encoding="utf-8") as f:
    json.dump({"app": "drive-a", "module": {"host": "drive-a.evil"}, "link_port": 9999, "remote": {"office": "evil"}}, f)

import app  # noqa: E402
import engines  # noqa: E402

c = app.app.test_client()
HOSTS["drive:8975"] = c


def main() -> int:
    # ── finding the engines ──
    check(engines.found()["local"]["url"] == "http://drive-local:8988" and engines.found()["a"]["office"] == "evil",
          "an engine is found by its name in the compiled registry (a door row), and a linked office's by its door")
    check(engines.engine_of("drive_local") == "local" and engines.engine_of("drive_other") is None,
          "an account's engine is found from its protocol, by the engines' own word")
    check(engines.private_protocols() == ["drive_local"] and engines.private_engine() == "local",
          "the office's own storage is the engine of THIS office that says it is private")
    check(all(e == "local" for _p, e in engines.routes()) and engines.oauth("google") is None,
          "a linked office's engine is given no prefix of this app and no consent door, whatever it claims")

    # ── every account of every engine, one list ──
    d = c.get("/connections").get_json()
    rows = {r["id"]: r for r in d["connections"]}
    check(d["active"] == "drive_local-admin" and d["bound"] is None,
          "nothing bound: the office acts as the first admin profile, as its engine marks it")
    check(rows["drive_local-admin"]["label"] == "מנהל" and rows["drive_local-admin"]["is_private"],
          "a profile's row is said by its own engine (its name, private)")
    check(rows["drive_other-x"]["status"] == "needs_action" and "אינו פועל" in rows["drive_other-x"]["reason"],
          "an account whose engine does not run stays in the list, saying so — never dropped")
    check([r["id"] for r in d["connections"]] == [i["id"] for i in VAULT], "…in the vault's own order")
    check((d.get("acting_profile") or {}).get("id") == "admin", "who is acting is the office storage's word")

    # ── the routes callers use ──
    r = c.get("/api/folders")
    check(r.status_code == 200 and r.get_json()["folders"][0]["name"] == "מסמכים"
          and r.get_json()["connection"]["views"] == ["recent", "starred"], "a drive's folders, and what it can show")
    r = c.get("/api/files?folder=")
    check(r.status_code == 200 and r.get_json()["files"][0]["id"] == "lf1", "a folder's files")
    r = c.get("/api/fs?path=/חוזה.pdf")
    check(r.status_code == 200 and r.get_json()["kind"] == "file", "a file named by its path (agents, apps)")
    r = c.get("/api/file/lf1/content", headers={"Range": "bytes=0-3"})
    check(r.status_code == 206 and r.get_data() == b"%PDF" and r.headers.get("Content-Range") == "bytes 0-3/11"
          and r.headers.get("Content-Security-Policy") == "sandbox", "a file's bytes, with Range, and the engine's serving headers")
    r = c.get("/api/file/nope/content")
    check(r.status_code == 404 and "אינו קיים" in r.get_json()["error"], "a missing file is a 404 that says so, never a 503")
    r = c.get("/api/search?q=חוזה")
    check(r.status_code == 200 and len(r.get_json()["files"]) == 1, "a search")
    check(c.post("/api/star", json={"ids": ["lf1"]}).status_code == 200, "an optional op the engine has")
    check(c.get("/api/storage").status_code == 501, "an optional op the engine lacks is refused before it is tried")
    r = c.put("/api/fs/content?path=/מסמכים/סיכום.md", data=b"# hello", headers={"Content-Type": "text/markdown"})
    stored = r.get_json() or {}
    check(r.status_code == 201 and BYTES.get(stored.get("file", {}).get("id")) == b"# hello",
          "a stored file reaches its engine whole, its size and md5 checked there")
    r1 = c.put("/api/fs/content?path=/pack-0001&mode=exclusive", data=b"one")
    r2 = c.put("/api/fs/content?path=/pack-0001&mode=exclusive", data=b"two")
    check(r1.status_code == 201 and r2.status_code == 409 and BYTES.get(r1.get_json()["file"]["id"]) == b"one",
          "mode=exclusive: a create that fails when the name is taken, and the first file stays as it was (DGO-1505)")

    # ── DGO-2042: the body is the file — nothing parses it, and the drive is named in the address only ──
    # (a body labelled as a form or as JSON was parsed away by `_use()`: stored EMPTY with a 201, after
    # mode=replace had trashed the good copy — issues/a-drive-upload-sent-as-a-form-is-stored-empty-…yaml)
    def kept_bytes(resp):
        return BYTES.get(((resp.get_json() or {}).get("file") or {}).get("id"))

    def kept_file(resp):
        return (resp.get_json() or {}).get("file") or {}

    r = c.put("/api/fs/content?path=/form-2042.md", data=b"# sent as a form",
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    check(r.status_code == 201 and kept_bytes(r) == b"# sent as a form" and kept_file(r).get("mime") == "",
          "a body labelled as a form (curl -d, urllib's default) is stored whole, its type left to its name")
    big = b"%PDF-" + b"x" * 600_000
    r = c.put("/api/fs/content?path=/big-form-2042.pdf", data=big,
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    check(r.status_code == 201 and kept_bytes(r) == big,
          "…a big one too (600 KB: Flask parses no form over 500 KB, so a parse of it answered 413)")
    doc = json.dumps({"connection_id": "drive_local-user2", "profile_key": "key-user2", "state": "kept"}).encode()
    r = c.put("/api/fs/content?path=/state-2042.json", data=doc, headers={"Content-Type": "application/json"})
    check(r.status_code == 201 and kept_bytes(r) == doc and kept_file(r).get("by") == "drive_local-admin",
          "a JSON file is stored whole, in the drive the call is on — its own connection_id and profile_key choose nothing")
    c.put("/api/fs/content?path=/keep-2042.md", data=b"keep me", headers={"Content-Type": "text/markdown"})
    r = c.put("/api/fs/content?path=/keep-2042.md&mode=replace", data=b"", headers={"Content-Type": "text/markdown"})
    check(r.status_code == 400 and "empty=1" in (r.get_json() or {}).get("error", "")
          and c.get("/api/fs/content?path=/keep-2042.md").get_data() == b"keep me",
          "mode=replace with an empty body is refused, says how to ask for one, and the file stays as it was")
    r = c.put("/api/fs/content?path=/keep-2042.md&mode=replace", data=b"replaced",
              headers={"Content-Type": "application/x-www-form-urlencoded"})
    check(r.status_code == 201 and c.get("/api/fs/content?path=/keep-2042.md").get_data() == b"replaced",
          "…and a replace whose body is labelled as a form replaces it with the bytes that were sent")
    r = c.put("/api/fs/content?path=/keep-2042.md&mode=replace",
              data={"file": (io.BytesIO(b"an envelope"), "x.md")}, content_type="multipart/form-data")
    check(r.status_code == 415 and c.get("/api/fs/content?path=/keep-2042.md").get_data() == b"replaced",
          "a multipart PUT is refused (415: PUT stores the file itself), and the file it would have replaced stays")
    check(c.put("/api/fs/content?path=/empty-2042.txt", data=b"").status_code == 400,
          "an empty body is refused when the caller did not ask for an empty file")
    r = c.put("/api/fs/content?path=/empty-2042.txt&empty=1", data=b"")
    check(r.status_code == 201 and kept_bytes(r) == b"", "…and stored when it asks (empty=1)")
    limit, app.uploads.MAX_SIZE = app.uploads.MAX_SIZE, 4
    try:
        r = c.put("/api/fs/content?path=/keep-2042.md&mode=replace", data=b"too long", headers={"Content-Type": "text/plain"})
    finally:
        app.uploads.MAX_SIZE = limit
    check(r.status_code == 413 and c.get("/api/fs/content?path=/keep-2042.md").get_data() == b"replaced",
          "a body over the limit is refused before anything is trashed")
    r = c.post("/api/upload", data={"files": (io.BytesIO(b"abc"), "a.txt"), "folder": ""},
               content_type="multipart/form-data")
    check(r.status_code == 200 and r.get_json()["uploaded"][0]["name"] == "a.txt", "a small upload")

    # ── the §3 ops ──
    r = c.post("/list", json={})
    check(r.status_code == 400 and "explicit" in r.get_json()["error"] and "drive_local-admin" in r.get_json()["error"],
          "a §3 op that names no drive is refused, naming the drives it could have named")
    r = c.post("/list", json={"connection_id": "drive_local-admin", "limit": 2})
    check(r.status_code == 200 and len(r.get_json()["files"]) == 2, "a §3 op on a named drive")
    r = c.post("/upload", data={"file": (io.BytesIO(b"x" * 10), "big.bin"), "connection_id": "drive_local-admin"},
               content_type="multipart/form-data")
    check(r.status_code == 200 and r.get_json().get("kind") == "drive#file", "the §3 upload streams to the engine and answers its resource")

    # ── errors keep their status and shape ──
    VAULT.append({"id": "drive_local-broken", "protocol": "drive_local", "label": "b", "account_hint": "broken"})
    r = c.get("/api/folders?connection_id=drive_local-broken")
    check(r.status_code == 503 and "ההרשאה פגה" in r.get_json()["error"] and "connection_id" in r.get_json(),
          "an account that cannot sign in is a 503 in the account error's shape")
    VAULT.pop()
    r = c.get("/api/folders?connection_id=drive_local-user2", headers={"X-Drive-Profile-Key": "key-admin"})
    check(r.status_code == 403 and SEEN["keys"][-1] == "key-admin", "a key travels to the engine, which refuses another profile's drive")
    r = c.get("/api/folders?connection_id=drive_local-user2", headers={"X-Drive-Profile-Key": "key-user2"})
    check(r.status_code == 200, "…and lets the profile's own key work on its own drive")
    check(c.get("/api/folders?connection_id=nope").status_code == 404, "an unknown drive is a 404, never another drive")

    # ── /readyz, /manifest, the catalogues ──
    r = c.get("/readyz")
    check(r.status_code == 200 and r.get_json()["connection_id"] == "drive_local-admin", "/readyz probes the drive actually used")
    m = c.get("/manifest").get_json()
    check(m["protocols"] == ["drive_local"] and m["connection"]["id"] == "drive_local-admin"
          and "list" in m["connection"]["ops"] and m["capabilities"]["ops_require_explicit_connection"],
          "/manifest says what this drive can do, from its engine")
    check(c.get("/providers").get_json()["providers"][0]["id"] == "local", "/providers is the engines' own rows")
    check(c.get("/engines").get_json()["engines"][0]["id"] == "drive_local", "/engines too")

    # ── what an engine keeps for itself ──
    r = c.get("/file/d/lf1/view", headers={"Cookie": "authentik_session=secret", "Range": "bytes=0-"})
    check(r.status_code == 200 and r.get_data() == b"%PDF-hello!" and r.headers.get("X-Served-By") == "drive-local"
          and r.headers.get("Content-Length") == "11",
          "a share link is handed to its engine and served on this address with its length, as before")
    check("Cookie" not in SEEN["link"] and SEEN["link"].get("Range") == "bytes=0-",
          "…carrying the range, never the person's session")
    r = c.get("/engine/whoami", headers={"X-Drive-Acting-Connection": "drive_local-user2"})
    check(r.status_code == 200 and r.get_json()["profile"]["id"] == "admin"
          and not any(k.lower() == "x-drive-acting-connection" for k in SEEN["acting"][-1]),
          "the profile plane is handed over; who acts is the bound drive, asked of «קבצים» — never what a caller sends")
    check(c.get("/connections/active").get_json()["id"] == "drive_local-admin", "/connections/active names the bound drive")
    for bad in ("/file/d/%2e%2e/%2e%2e/engine/whoami", "/file/d/../engine/profiles"):
        r = c.get(bad)
        check(r.status_code in (400, 404) and "profile" not in (r.get_data(as_text=True)),
              f"a path that climbs out of the share links ({bad}) is refused, never handed over")

    # ── the consent door an engine names ──
    r = c.get("/oauth/nobody/start?check=1&ret=http%3A%2F%2Fx%2Freturn")
    check(r.status_code == 404, "a consent door no engine names is not opened")

    # ── an engine that stops answering ──
    DOWN.add("drive-local:8988")
    engines.invalidate()
    d = c.get("/connections").get_json()
    check(d["connections"] and all(r.get("status") == "needs_action" for r in d["connections"]),
          "an engine that stops answering: its drives stay listed as needing action")
    check(c.get("/api/folders?connection_id=drive_local-admin").status_code == 503, "…and an op on them is a 503, never another drive")
    r = c.get("/file/d/lf1/view")
    check(r.status_code == 503, "…a share link is a 503 «try again» while its engine restarts, never a 404 «never existed»")
    check(engines.engine_of("drive_local") is None and engines.private_engine() is None,
          "…and a linked office's engine that claims our storage's protocol does not get it while ours restarts")
    r = c.delete("/connections/drive_other-x")
    check(r.status_code == 503 and any(i["id"] == "drive_other-x" for i in VAULT),
          "…and an account is not disconnected around an engine that does not answer (its refusal may be the one)")
    DOWN.discard("drive-local:8988")
    engines.invalidate()

    # ── one protocol: the engine side is the same file in every engine ──
    same = lambda a, b: open(os.path.join(APPS, a), "rb").read() == open(os.path.join(APPS, b), "rb").read()  # noqa: E731
    check(same("drive-local/engine_rpc.py", "drive-google/engine_rpc.py"), "engine_rpc.py is the same in every engine")
    check(same("drive-local/status.py", "drive-google/status.py"), "status.py too")
    check(same("drive/media.py", "drive-local/media.py") and same("drive/media.py", "drive-google/media.py"),
          "media.py (how a user's file may be served) is the same in «קבצים» and in every engine")
    check(same("drive-local/opsupport.py", "drive-google/opsupport.py"), "opsupport.py is the same in every engine")

    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
