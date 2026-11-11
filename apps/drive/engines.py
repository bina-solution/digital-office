"""engines — «קבצים»'s door to its ENGINES (apps/drive/ENGINES.md, DGO-1500).

The owner, 2026-11-09: the drive app is split into a private engine, Google Drive as an external engine,
and a generic drive app that unites them and gives every account of every engine in one protocol. This
module is how the generic app finds the engines and asks them; it holds no engine's code.

FINDING THEM — by name, in what the compiler already writes (no list of engines lives here; the rule of
apps/domains/provider_client.py):
  - an app of THIS office whose id is `drive-<engine>`: `.generated/registry/office.apps.json`, a row of
    `apps` (a tile) or of `services` (a door with no tile, `link: true` on its capability), reached at
    http://<service>:<port>;
  - one a LINKED office gives this one: `remote.<office>.<alias>.json` with `app: drive-*`.
  Ours first. Two linked offices giving the same engine is reported, never guessed between
  (DRIVE_ENGINE_<ID>_OFFICE chooses); DRIVE_ENGINE_<ID>_URL overrides the lookup.

ASKING THEM — drive-engine.v1. Each answers /ops with the vault protocols it serves (every engine's
protocols are `drive_*`), so an account's engine is found from its protocol. `RemoteAdapter` gives app.py
the same surface the in-process adapters had (the same method names, arguments and results; a method the
engine lacks is absent, so `callable(getattr(ad, m, None))` still says what a drive can do), and raises
the same three errors the routes already answer.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import tempfile
import time
import urllib.parse

import requests

log = logging.getLogger(__name__)

REGISTRY = os.environ.get("DRIVE_REGISTRY_DIR", "/registry")
PREFIX = "drive-"
TIMEOUT = float(os.environ.get("DRIVE_ENGINE_TIMEOUT", "60"))
STREAM_TIMEOUT = (10, float(os.environ.get("DRIVE_ENGINE_STREAM_TIMEOUT", "600")))
ERROR_HEADER = "X-Drive-Engine-Error"
PROFILE_KEY_HEADER = "X-Drive-Profile-Key"
_TTL = 30

#: the §3 op names → the method that answers each (this dict IS the automation op surface: /manifest
#: advertises its keys and the op routes dispatch through it)
CANONICAL_OPS = {"list": "op_list", "download": "op_download", "upload": "op_upload", "move": "op_move",
                 "update": "op_update", "delete": "op_delete", "createFromText": "op_create_from_text"}
#: ops only SOME engines have; absence IS the answer "unsupported"
PROTOCOL_OPS = {"star": "star", "storage": "storage", "touch": "touch", "views": "views"}


class AdapterError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.message, self.status = message, int(status or 503)


class AuthError(Exception):
    """An account that cannot authenticate (Google's grant expired, a service account key refused). Its
    STATUS passes through: 404/410 describe the object, 503 the connection (gdrive.GoogleAuthError)."""

    def __init__(self, message, status=503):
        super().__init__(message)
        self.message, self.status = message, int(status or 503)


class ProfileError(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.message, self.status = message, int(status or 403)


_KINDS = {"auth": AuthError, "profile": ProfileError}


def _raise(doc, status, eid):
    doc = doc if isinstance(doc, dict) else {}
    cls = _KINDS.get(doc.get("kind"), AdapterError)
    raise cls(doc.get("error") or f"מנוע הקבצים {PREFIX}{eid} ענה HTTP {status}", doc.get("status") or status)


# ── finding the engines ───────────────────────────────────────────────────────────
_found = {"at": 0.0, "rows": {}}
_ops = {}                # eid -> (expires_at, ops)


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def found(force=False):
    """{engine id: {"app", "url", "office" (None = this office), "candidates"[, "ambiguous"]}}."""
    if not force and time.time() - _found["at"] < _TTL:
        return _found["rows"]
    rows = {}
    reg = _read(os.path.join(REGISTRY, "office.apps.json"))
    for entry in list(reg.get("apps") or []) + list(reg.get("services") or []):
        app = entry.get("app") or ""
        if app.startswith(PREFIX) and entry.get("port"):
            rows.setdefault(app[len(PREFIX):], {"app": app, "office": None, "candidates": [None],
                                                "url": f"http://{entry.get('service') or app}:{entry['port']}"})
    remote = {}
    for path in sorted(glob.glob(os.path.join(REGISTRY, "remote.*.json"))):
        entry = _read(path)
        app = entry.get("app") or ""
        host = (entry.get("module") or {}).get("host")
        port = entry.get("link_port") or entry.get("port")
        if app.startswith(PREFIX) and host and port:
            remote.setdefault(app[len(PREFIX):], []).append(
                {"app": app, "office": (entry.get("remote") or {}).get("office"), "url": f"http://{host}:{port}"})
    for eid, cands in remote.items():
        var = f"DRIVE_ENGINE_{eid.upper().replace('-', '_')}_OFFICE"
        if eid in rows:
            rows[eid]["candidates"] += [r["office"] for r in cands]
            continue
        chosen = os.environ.get(var, "").strip()
        pick = [r for r in cands if r["office"] == chosen] if chosen else cands
        if len(pick) == 1:
            rows[eid] = {**pick[0], "candidates": [r["office"] for r in cands]}
        else:
            offices = ", ".join(str(r["office"]) for r in cands)
            rows[eid] = {"app": cands[0]["app"], "office": None, "url": None,
                         "candidates": [r["office"] for r in cands],
                         "ambiguous": f"{len(cands)} linked offices give {cands[0]['app']} ({offices}) — set {var}"}
    for eid in list(rows):
        url = os.environ.get(f"DRIVE_ENGINE_{eid.upper().replace('-', '_')}_URL", "").strip()
        if url:
            rows[eid] = {**rows[eid], "url": url.rstrip("/")}
    for k, v in os.environ.items():                  # an engine named only by its address (a test, a laptop)
        if k.startswith("DRIVE_ENGINE_") and k.endswith("_URL") and v.strip():
            eid = k[len("DRIVE_ENGINE_"):-len("_URL")].lower().replace("_", "-")
            rows.setdefault(eid, {"app": PREFIX + eid, "office": None, "candidates": [None], "url": v.strip().rstrip("/")})
    _found.update(at=time.time(), rows=rows)
    return rows


def ops(eid):
    """The engine's /ops (cached), or None when it does not answer."""
    hit = _ops.get(eid)
    now = time.time()
    if hit and hit[0] > now:
        return hit[1]
    row = found().get(eid) or {}
    if not row.get("url"):
        return None
    try:
        r = requests.get(row["url"] + "/ops", timeout=(5, 15))
        doc = r.json()
    except (requests.RequestException, ValueError):
        _ops[eid] = (now + 5, None)                  # a down engine is asked again in a few seconds
        return None
    good = doc if isinstance(doc, dict) and doc.get("ok") else None
    _ops[eid] = (now + (_TTL if good else 5), good)
    return good


def _is_local(eid):
    return eid in found() and found().get(eid, {}).get("office") is None


def _sorted(pairs):
    return sorted(pairs, key=lambda eo: (not _is_local(eo[0]), eo[1].get("kind") != "engine", eo[0]))


def local_ops():
    """Only this office's engines — asked without asking a linked office anything. What an engine may claim
    beyond its own accounts — the path prefixes «קבצים» hands it, being the office's PRIVATE storage (the
    engine a profile key is sent to), a consent door — is trusted from an app of this office alone."""
    out = [(eid, ops(eid)) for eid in sorted(found()) if _is_local(eid)]
    return _sorted([(e, o) for e, o in out if o])


def all_ops():
    """[(engine id, its /ops)] of every engine that answers — this office's before a linked office's, the
    office's own storage first."""
    out = [(eid, ops(eid)) for eid in sorted(found())]
    return _sorted([(e, o) for e, o in out if o])


def unanswered():
    """Engines of THIS office found in the registry that do not answer right now — their accounts cannot be
    judged. A linked office's door that is down is not this office's to wait for."""
    return [eid for eid in sorted(found()) if _is_local(eid) and found().get(eid, {}).get("url") and not ops(eid)]


def engine_of(protocol):
    """The engine of an account's protocol: this office's first. A protocol an engine of THIS office serves —
    now, or when it last answered (kept, `_kept()`) — is never given to a linked office's engine, not even
    while ours restarts; nor is a private one, ever."""
    kept = _kept()["protocols"]
    for eid, o in all_ops():
        d = (o.get("protocols") or {}).get(protocol)
        if d is None:
            continue
        if not _is_local(eid) and ((d or {}).get("private") or protocol in kept):
            continue
        return eid
    return None


def protocols():
    """Every protocol some engine serves here, once — a linked office's claim to a private one is not one."""
    out = []
    for _e, o in all_ops():
        for p in (o.get("protocols") or {}):
            if p not in out and engine_of(p):
                out.append(p)
    return out


def private_protocols():
    return sorted(p for _e, o in local_ops() for p, d in (o.get("protocols") or {}).items() if (d or {}).get("private"))


def private_engine():
    """The engine that runs the office's own storage (the one whose profiles a key belongs to)."""
    for eid, o in local_ops():
        if any((d or {}).get("private") for d in (o.get("protocols") or {}).values()):
            return eid
    return None


def oauth(name):
    """The consent door an engine of this office names (`/ops` `oauth`): {"engine", "grant", "provider",
    "connected"} or None."""
    for eid, o in local_ops():
        hit = (o.get("oauth") or {}).get(name)
        if hit:
            return {**hit, "engine": eid}
    return None


ROUTES_PATH = os.environ.get("DRIVE_ENGINE_ROUTES", "/data/engine-routes.json")


def _kept():
    """What this office's engines said when they last answered, kept on this app's volume:
    {"routes": [[prefix, engine]], "protocols": {protocol: engine}} — refreshed from the engines that answer,
    kept for those that are restarting, dropped for an engine no longer in the registry."""
    try:
        with open(ROUTES_PATH, encoding="utf-8") as f:
            doc = json.load(f)
        doc = doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        doc = {}
    live = local_ops()
    answered = {eid for eid, _o in live}
    routes_ = sorted({(p, eid) for eid, o in live for p in (o.get("routes") or [])}
                     | {(p, e) for p, e in (tuple(x) for x in doc.get("routes") or [] if len(x) == 2)
                        if e not in answered and _is_local(e)})
    protos = {p: eid for eid, o in live for p in (o.get("protocols") or {})}
    protos.update({p: e for p, e in (doc.get("protocols") or {}).items()
                   if e not in answered and _is_local(e) and p not in protos})
    want = {"routes": [list(x) for x in routes_], "protocols": dict(sorted(protos.items()))}
    if want != {"routes": doc.get("routes") or [], "protocols": doc.get("protocols") or {}}:
        try:                                  # atomically, by every worker and thread alike
            d = os.path.dirname(ROUTES_PATH) or "."
            os.makedirs(d, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(want, f)
            os.replace(tmp, ROUTES_PATH)
        except OSError:
            pass
    return {"routes": [tuple(x) for x in want["routes"]], "protocols": want["protocols"]}


def routes():
    """[(path prefix, engine id)] — what «קבצים» hands to an engine of this office verbatim (its profile
    plane, its share links). The last answer is KEPT: an engine that is restarting still owns its prefixes,
    so a share link is a 503 «try again», never a 404 «this never existed»."""
    return _kept()["routes"]


def url(eid):
    row = found().get(eid) or {}
    if not row.get("url"):
        raise AdapterError(row.get("ambiguous") or f"מנוע הקבצים {PREFIX}{eid} אינו פועל בלשכה הזו", 503)
    return row["url"]


# ── one call ──────────────────────────────────────────────────────────────────────
def _headers(key=None, extra=None):
    h = dict(extra or {})
    if key:
        h[PROFILE_KEY_HEADER] = key
    return h


def _unreachable(eid, e, said="אינו עונה"):
    """A sentence for a person; the transport's own name for what failed goes to the log (G76)."""
    log.warning("drive engine %s: %s %s", eid, type(e).__name__, e)
    return AdapterError(f"מנוע הקבצים {PREFIX}{eid} {said} — נסו שוב בעוד רגע", 503)


def post(eid, path, body, key=None, timeout=None):
    """One JSON op → its answer (a dict with ok), raising the errors the routes answer."""
    try:
        r = requests.post(url(eid) + path, json=body, headers=_headers(key), timeout=(5, timeout or TIMEOUT))
    except requests.RequestException as e:
        raise _unreachable(eid, e)
    try:
        doc = r.json()
    except ValueError:
        raise AdapterError(f"מנוע הקבצים {PREFIX}{eid} ענה HTTP {r.status_code} בלי תשובה", 502 if r.status_code < 500 else r.status_code)
    if not isinstance(doc, dict) or doc.get("ok") is False or r.status_code >= 400:
        _raise(doc, r.status_code, eid)
    return doc


def _stream(eid, method, path, key=None, **kw):
    """A byte answer: (status, headers, chunks). An error is the engine's JSON, marked by its header."""
    try:
        r = requests.request(method, url(eid) + path, headers=_headers(key, kw.pop("headers", None)),
                             stream=True, timeout=STREAM_TIMEOUT, **kw)
    except requests.RequestException as e:
        raise _unreachable(eid, e)
    if r.headers.get(ERROR_HEADER):
        try:
            doc = r.json()
        except ValueError:
            doc = {}
        finally:
            r.close()
        _raise(doc, r.status_code, eid)
    hdrs = {k: v for k, v in r.headers.items() if k.lower() not in HOP_RESPONSE}
    return r.status_code, hdrs, _raw(r)


class Sized:
    """A file object of known size from its current position — sent with its own Content-Length."""

    def __init__(self, src, size):
        self.src, self.size = src, int(size)

    def __len__(self):
        return self.size

    def read(self, n=-1):
        return self.src.read(n)


# ── a drive, as app.py knows one ──────────────────────────────────────────────────
_desc = {}               # cid -> (expires_at, describe)


class RemoteAdapter:
    """One account of one engine. The attributes app.py reads (`protocol`, `profile_id`, `_SA_NO_CREATE`)
    and exactly the methods the engine says this account has."""

    STREAMING = ("content", "op_download", "store_file", "upload", "op_upload", "thumb")

    def __init__(self, eid, inst, desc, key=None):
        self.engine, self.instance, self.cid, self.key = eid, inst, inst.get("id"), key
        self.protocol = desc.get("protocol") or inst.get("protocol") or ""
        self.private = bool(desc.get("private"))
        self.profile_id = desc.get("profile_id")
        self._methods = set(desc.get("methods") or [])
        self._streams = set(desc.get("streams") or [])
        self._views = list(desc.get("views") or [])
        if not desc.get("creates", True):
            self._SA_NO_CREATE = True

    def __getattr__(self, name):
        method = "file" if name == "_file" else name
        if method in self.__dict__.get("_methods", ()):
            if method == "views":
                return lambda: list(self._views)
            return lambda *a, **kw: self._call(method, a, kw)
        if name in self.STREAMING and name in self.__dict__.get("_streams", ()):
            return getattr(self, "_s_" + name)
        raise AttributeError(name)

    def _call(self, method, args, kwargs):
        return post(self.engine, "/v1/call/" + method,
                    {"connection_id": self.cid, "args": list(args), "kwargs": kwargs}, self.key).get("result")

    # the byte doors, each on its own route
    def _s_content(self, fid, range_header=None, want="inline"):
        return _stream(self.engine, "GET", "/v1/content", self.key,
                       params={"connection_id": self.cid, "id": fid, "want": want},
                       headers={"Range": range_header} if range_header else None)

    def _s_op_download(self, file_id, file_id_mode="id"):
        return _stream(self.engine, "GET", "/v1/download", self.key,
                       params={"connection_id": self.cid, "file_id": file_id, "file_id_mode": file_id_mode})

    def _put(self, route, src, size, md5, name, mime, folder):
        try:
            r = requests.put(url(self.engine) + route, data=Sized(src, size),
                             params={"connection_id": self.cid, "size": int(size), "md5": md5 or "", "name": name,
                                     "mime": mime or "", "folder": folder or ""},
                             headers=_headers(self.key, {"Content-Type": "application/octet-stream",
                                                         "Content-Length": str(int(size))}),
                             timeout=STREAM_TIMEOUT)
        except requests.RequestException as e:
            raise _unreachable(self.engine, e, "לא קיבל את הקובץ")
        try:
            doc = r.json()
        except ValueError:                                 # a proxy's 413 with no JSON is still «too big», not an outage
            raise AdapterError(f"מנוע הקבצים {PREFIX}{self.engine} ענה HTTP {r.status_code}",
                               413 if r.status_code == 413 else 502)
        if not isinstance(doc, dict) or doc.get("ok") is False or r.status_code >= 400:
            _raise(doc, r.status_code, self.engine)
        return doc.get("result")

    def _s_store_file(self, src, size, md5, name, mime, folder="", oid=None):
        return self._put("/v1/store", src, size, md5, name, mime, folder)

    def _s_upload(self, folder, filename, mime, data):
        import hashlib
        import io
        data = data or b""
        return self._put("/v1/store", io.BytesIO(data), len(data), hashlib.md5(data).hexdigest(), filename, mime, folder)

    def _s_op_upload(self, folder_id, name, mime, data):
        import hashlib
        import io
        data = data or b""
        return self._put("/v1/op_upload", io.BytesIO(data), len(data), hashlib.md5(data).hexdigest(), name, mime, folder_id)

    def op_store_stream(self, src, size, md5, name, mime, folder=""):
        """The §3 `upload` op, streamed from a spooled part (the engine answers its own file resource)."""
        return self._put("/v1/op_upload", src, size, md5, name, mime, folder)

    def _s_thumb(self, item, size):
        try:
            r = requests.post(url(self.engine) + "/v1/thumb", json={"connection_id": self.cid, "item": item, "size": size},
                              headers=_headers(self.key), timeout=(5, TIMEOUT))
        except requests.RequestException:
            return None
        if r.status_code >= 400 or r.headers.get(ERROR_HEADER) or not r.content:
            return None
        return r.content, (r.headers.get("Content-Type") or "image/webp").split(";")[0]


def describe(eid, cid, key=None):
    hit = _desc.get(cid)
    now = time.time()
    if hit and hit[0] > now and not key:
        return hit[1]
    d = post(eid, "/v1/describe", {"connection_id": cid}, key)
    if not key:
        _desc[cid] = (now + _TTL, d)
    return d


def invalidate(cid=None):
    if cid is None:
        _desc.clear()
        _ops.clear()
        _found.update(at=0.0)
    else:
        _desc.pop(cid, None)


def for_instance(inst, key=None):
    inst = inst or {}
    proto = inst.get("protocol") or ""
    eid = engine_of(proto)
    if not eid:
        raise AdapterError(f"אין מנוע קבצים פעיל לחשבון מסוג {proto!r} — המנוע אינו מותקן או אינו עונה", 503)
    return RemoteAdapter(eid, inst, describe(eid, inst.get("id"), key), key)


def ops_for(adapter):
    has = lambda m: callable(getattr(adapter, m, None))  # noqa: E731
    return {"ops": [k for k, m in CANONICAL_OPS.items() if has(m)],
            "optional_ops": [k for k, m in PROTOCOL_OPS.items() if has(m)]}


def views_for(adapter):
    fn = getattr(adapter, "views", None)
    return list(fn()) if callable(fn) else []


# ── every account of every engine, one list ───────────────────────────────────────
def annotate(inst):
    """The fields a caller used to derive by parsing the id — from the engines' own word on their protocols."""
    out = dict(inst or {})
    proto = out.get("protocol") or ""
    out["engine"] = proto
    out["is_private"] = proto in private_protocols()
    out["app"] = "drive"
    if out["is_private"]:
        out.setdefault("profile_id", out.get("account_hint"))
    return out


def accounts(instances):
    """The vault rows, each annotated by its own engine (/v1/accounts). The rows of an engine that does
    not run or does not answer stay in the list, saying so — never dropped, never another drive's."""
    by = {}
    for inst in instances:
        by.setdefault(engine_of(inst.get("protocol") or ""), []).append(inst)
    out = []
    for eid, rows in by.items():
        got = None
        if eid:
            try:
                got = post(eid, "/v1/accounts", {"instances": rows}, timeout=20).get("accounts")
            except (AdapterError, AuthError, ProfileError):
                got = None
        if got is None:
            why = (f"מנוע הקבצים {PREFIX}{eid} אינו עונה כרגע" if eid
                   else "מנוע הקבצים של החשבון הזה אינו פועל בלשכה")
            got = [dict(annotate(i), status="needs_action", reason=why) for i in rows]
        out += got
    order = {i.get("id"): n for n, i in enumerate(instances)}
    return sorted(out, key=lambda r: order.get(r.get("id"), 1 << 30))


# ── what an engine keeps for itself, handed over verbatim ─────────────────────────
#: what a request handed to an engine carries — never the person's session (Cookie, the SSO headers):
#: an engine needs the range, the conditions, the body's type and the profile key, nothing else
PASS_REQUEST = ("range", "if-range", "if-none-match", "if-modified-since", "accept", "accept-language",
                "content-type", "authorization", PROFILE_KEY_HEADER.lower())
#: what an answer does not carry on to the browser (hop-by-hop); its length and encoding DO pass
HOP_RESPONSE = ("connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
                "proxy-authenticate", "server", "date")


class _raw:
    """The answer's bytes exactly as sent (not decoded), so its Content-Length and Content-Encoding stay true.
    An iterable with close(): the server closes it when the answer is done — also when it never reads it
    (HEAD, 204, 304), so the connection to the engine is never left to the garbage collector."""

    def __init__(self, r):
        self.r = r

    def __iter__(self):
        return iter(self.r.raw.stream(65536, decode_content=False))

    def close(self):
        self.r.close()


def proxy(eid, path, method, query, headers, body):
    """(status, headers, chunks) of the engine's own answer to this request (its profile plane, its share
    links). `body` is (stream, length) — streamed with its length — or bytes (a chunked request, read
    whole: these are small JSON bodies). The path is quoted again: a decoded `?`, `#` or `%` in it stays
    a part of the path. The answer streams back as sent."""
    fwd = {k: v for k, v in headers.items() if k.lower() in PASS_REQUEST}
    if isinstance(body, tuple):
        stream, length = body
        data = Sized(stream, length) if length else None
        if length:
            fwd["Content-Length"] = str(length)
    else:
        data = body or None
    try:
        r = requests.request(method, url(eid) + urllib.parse.quote(path, safe="/"), params=query, headers=fwd,
                             data=data, stream=True, timeout=STREAM_TIMEOUT, allow_redirects=False)
    except requests.RequestException as e:
        raise _unreachable(eid, e)
    hdrs = [(k, v) for k, v in r.headers.items() if k.lower() not in HOP_RESPONSE]
    return r.status_code, hdrs, _raw(r)
