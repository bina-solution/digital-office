"""uploads — resumable uploads (the tus 1.0 protocol: core + creation + termination).

WHY. A file used to arrive as one multipart request that the console proxy buffers whole (40 s) and
the drive read into memory (`f.read()`, 384 MB container): an hour-long recording either timed out or
took the container down, and a dropped connection meant starting over. Now a file is a SESSION that
takes pieces of a few MB in order, so memory stays flat, no request is long, and a session survives
a dropped network, a reload or a restart: the client asks how much arrived and sends the rest.

A session is two files in /data/uploads — `<id>.json` (who, what, where to) and `<id>.part` (the
bytes so far; its size IS the offset). The volume is shared by every worker; `flock` on the part file
serialises appends across them. When the last byte lands, the session is FINISHED in a background
thread (md5 over the part, streamed to storage, indexed) and the client polls the session until it
says `done` — finishing a large file takes longer than the console proxy waits for one answer.

Sessions nobody touched for SESSION_TTL are removed by `sweep()`.
"""
import base64
import hashlib
import json
import os
import secrets
import shutil
import threading
import time

try:
    import fcntl
except ImportError:                 # a developer's Windows box running the tests; the image is Linux
    fcntl = None

ROOT = os.environ.get("DRIVE_UPLOAD_DIR", "/data/uploads")
MAX_SIZE = int(os.environ.get("DRIVE_MAX_UPLOAD") or 2 * 1024 ** 3)
MAX_CHUNK = 64 * 1024 ** 2          # one PATCH body; the client sends 8 MB
SESSION_TTL = 72 * 3600
STALE_FINISH = 180                  # a `finishing` session older than this lost its thread
DISK_MARGIN = 512 * 1024 ** 2
BLOCK = 1024 * 1024


class UploadError(Exception):
    def __init__(self, message, status=400, offset=None):
        super().__init__(message)
        self.message, self.status, self.offset = message, status, offset


def _paths(uid):
    if not uid or not all(c.isalnum() or c in "-_" for c in uid):
        raise UploadError("מזהה העלאה לא תקין", 404)
    return os.path.join(ROOT, uid + ".json"), os.path.join(ROOT, uid + ".part")


def _load(uid, profile):
    meta_p, part_p = _paths(uid)
    try:
        with open(meta_p, encoding="utf-8") as f:
            meta = json.load(f)
    except (OSError, ValueError):
        raise UploadError("ההעלאה אינה קיימת (אולי פג תוקפה)", 404)
    if meta.get("profile") != profile:
        raise UploadError("ההעלאה אינה קיימת (אולי פג תוקפה)", 404)
    # Read, not checked and then read: a finishing thread unlinks the part right after it records done,
    # and a poll between the two answered 500 (FileNotFoundError) where it now answers the session.
    try:
        meta["offset"] = os.path.getsize(part_p)
    except FileNotFoundError:
        meta["offset"] = 0
    return meta


def _save(meta):
    meta_p, _ = _paths(meta["id"])
    keep = {k: v for k, v in meta.items() if k != "offset"}
    keep["updated"] = time.time()
    tmp = f"{meta_p}.{threading.get_ident()}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(keep, f, ensure_ascii=False)
    for attempt in range(20):
        try:
            os.replace(tmp, meta_p)
            return
        except PermissionError:     # Windows only: the target is open in a reader this instant
            time.sleep(0.02 * (attempt + 1))
    os.replace(tmp, meta_p)


def parse_metadata(header):
    """tus `Upload-Metadata: name <b64>,folder <b64>` → {name: 'x', folder: 'y'}."""
    out = {}
    for pair in (header or "").split(","):
        key, _, val = pair.strip().partition(" ")
        if key:
            try:
                out[key] = base64.b64decode(val).decode("utf-8") if val else ""
            except (ValueError, UnicodeDecodeError):
                raise UploadError(f"Upload-Metadata: {key} is not base64 UTF-8", 400)
    return out


def create(profile, size, meta):
    """A new session for `size` bytes. `meta` carries name, mime, folder or path, mode — and, from an
    app, the folder it keeps (`system`) and what to make of a browser recording (`remux`)."""
    if size < 0 or size > MAX_SIZE:
        raise UploadError(f"הקובץ גדול מהמותר ({MAX_SIZE // 1024 ** 2} MB)", 413)
    os.makedirs(ROOT, exist_ok=True)
    free = shutil.disk_usage(ROOT).free
    if size + DISK_MARGIN > free:
        raise UploadError("אין מספיק מקום פנוי בשרת לקובץ הזה", 507)
    sweep()
    uid = secrets.token_urlsafe(18)
    session = {"id": uid, "profile": profile, "size": int(size), "state": "receiving",
               "name": meta.get("name") or meta.get("filename") or "file",
               "mime": meta.get("mime") or meta.get("filetype") or "",
               "folder": meta.get("folder") or "", "path": meta.get("path") or "",
               "mode": meta.get("mode") or "", "system": meta.get("system") or "",
               "remux": meta.get("remux") or "", "created": time.time()}
    open(_paths(uid)[1], "wb").close()
    _save(session)
    session["offset"] = 0
    return session


def status(uid, profile):
    meta = _load(uid, profile)
    if meta.get("state") == "finishing" and time.time() - meta.get("updated", 0) > STALE_FINISH:
        meta["state"] = "complete"          # the thread that was finishing it is gone; finish again
    return meta


def append(uid, profile, offset, stream, length):
    """Write the next piece. `offset` must be exactly what has arrived (409 otherwise, with the
    real offset so the client can resume); a piece may not run past the declared size."""
    meta = _load(uid, profile)
    if meta.get("state") != "receiving":
        raise UploadError("ההעלאה כבר הושלמה", 409, meta["offset"])
    if length is None or length < 0:
        raise UploadError("Content-Length חסר", 411)
    if length > MAX_CHUNK:
        raise UploadError("חתיכה גדולה מדי", 413)
    _, part_p = _paths(uid)
    with open(part_p, "ab") as part:
        if fcntl:
            fcntl.flock(part, fcntl.LOCK_EX)
        try:
            have = os.fstat(part.fileno()).st_size
            if offset != have:
                raise UploadError("ההיסט אינו תואם", 409, have)
            if have + length > meta["size"]:
                raise UploadError("החתיכה חורגת מגודל הקובץ שהוצהר", 413, have)
            left = length
            while left:
                buf = stream.read(min(BLOCK, left))
                if not buf:
                    break                   # the client went away mid-piece; what arrived stays
                part.write(buf)
                left -= len(buf)
            part.flush()
            have = os.fstat(part.fileno()).st_size
        finally:
            if fcntl:
                fcntl.flock(part, fcntl.LOCK_UN)
    meta["offset"] = have
    if have == meta["size"]:
        meta["state"] = "complete"
    _save(meta)
    return meta


# (part path, session meta) -> the path to store instead, e.g. a browser recording copied into a fresh
# container; app.py fills it. A step that fails returns the part itself: the bytes are stored as they came.
PREPARE = []


def finish_async(uid, profile, store):
    """Once every byte is in: hash it and hand it to `store(fileobj, size, md5, meta) -> item` in a
    thread; the session records `done` + the item, or `failed` + the reason (and can be retried)."""
    meta = status(uid, profile)
    if meta["offset"] != meta["size"]:
        raise UploadError("ההעלאה עוד לא הסתיימה", 409, meta["offset"])
    if meta.get("state") in ("finishing", "done"):
        return meta
    meta["state"] = "finishing"
    meta.pop("error", None)
    _save(meta)

    def run():
        _, part_p = _paths(uid)
        src_p = part_p
        try:
            for prep in PREPARE:
                src_p = prep(src_p, meta) or src_p
            h = hashlib.md5()
            with open(src_p, "rb") as f:
                for buf in iter(lambda: f.read(BLOCK), b""):
                    h.update(buf)
                f.seek(0)
                item = store(f, os.path.getsize(src_p), h.hexdigest(), meta)
            meta.update(state="done", file=item)
            _save(meta)
            os.unlink(part_p)
            if src_p != part_p:
                os.unlink(src_p)
        except Exception as e:      # the session stays; the client may retry the finish
            if src_p != part_p:     # …from the part itself: a prepared copy is made again then
                try:
                    os.unlink(src_p)
                except OSError:
                    pass
            print(f"[drive] finishing upload {uid} failed: {e}", flush=True)
            meta.update(state="failed", error=str(getattr(e, "message", "") or e)[:300])
            _save(meta)

    threading.Thread(target=run, name=f"finish-{uid}", daemon=True).start()
    return meta


def remove(uid, profile):
    _load(uid, profile)
    for p in _paths(uid):
        try:
            os.unlink(p)
        except FileNotFoundError:
            pass


def open_sessions(profile):
    """This profile's sessions that are not done — what a page offers to resume."""
    out = []
    for name in os.listdir(ROOT) if os.path.isdir(ROOT) else []:
        if name.endswith(".json"):
            try:
                meta = _load(name[:-5], profile)
            except UploadError:
                continue
            if meta.get("state") != "done":
                out.append({k: meta.get(k) for k in ("id", "name", "size", "offset", "state", "folder", "path",
                                                       "created", "error")})
    return sorted(out, key=lambda m: m.get("created") or 0, reverse=True)


def sweep():
    """Remove sessions untouched for SESSION_TTL, and finished ones after an hour."""
    if not os.path.isdir(ROOT):
        return
    now = time.time()
    for name in os.listdir(ROOT):
        if not name.endswith(".json"):
            continue
        p = os.path.join(ROOT, name)
        try:
            with open(p, encoding="utf-8") as f:
                meta = json.load(f)
        except (OSError, ValueError):
            meta = {}
        age = now - (meta.get("updated") or os.path.getmtime(p))
        if age > SESSION_TTL or (meta.get("state") == "done" and age > 3600):
            for q in (p, p[:-5] + ".part"):
                try:
                    os.unlink(q)
                except FileNotFoundError:
                    pass
