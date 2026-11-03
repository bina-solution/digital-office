"""media_jobs — the pictures and facts that make a file list look like the file: a thumbnail
(an image, a PDF's first page, a video's frame, an album's cover), a large preview for what a
browser cannot draw (HEIC, TIFF, PSD), an audio file's waveform, and the facts the photo, music and
video views sort and lay out by (size in pixels, duration, title, artist, when a photo was taken).

Made on demand and KEPT: a file's bytes never change under its id, so its picture never goes
stale. The cache is the drive's own volume (/data/cache/<id>/…), and a file that cannot be pictured
says so once (a `.none` marker for a day) instead of being tried again on every view.

ONE JOB AT A TIME, across every worker: the office's server has two cores and also records and
transcribes meetings. Jobs take a file lock, run ffmpeg at the lowest priority with a time limit,
and read the bytes straight from storage — ffmpeg over HTTP with Range, so a two-hour recording is
probed or framed without being downloaded.
"""
import array
import fcntl
import io
import json
import os
import subprocess
import threading
import time

import requests

from adapters.local import BUCKET, STORAGE, SERVICE_KEY, _object
from db import q

CACHE = os.environ.get("DRIVE_CACHE_DIR", "/data/cache")
SIZES = (128, 256, 512, 1024, 2048)
MAX_BYTES = 80 * 1024 * 1024          # what is pulled into memory to picture (an image, a PDF)
NONE_TTL = 24 * 3600

try:
    from PIL import Image, ImageOps
    Image.MAX_IMAGE_PIXELS = 160_000_000      # a picture claiming more pixels than this is refused, not decoded
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:                  # HEIC / AVIF pictured only where the codec is there
        pass
except Exception:                      # a developer's box without Pillow: every thumbnail is "none"
    Image = None


def _dir(fid):
    d = os.path.join(CACHE, fid.replace("/", "_"))
    os.makedirs(d, exist_ok=True)
    return d


class _one_at_a_time:
    """A lock every worker process sees (flock on the cache's own file)."""

    def __enter__(self):
        os.makedirs(CACHE, exist_ok=True)
        self.f = open(os.path.join(CACHE, ".lock"), "w")
        fcntl.flock(self.f, fcntl.LOCK_EX)
        return self

    def __exit__(self, *_):
        fcntl.flock(self.f, fcntl.LOCK_UN)
        self.f.close()
        return False


def _src_url(fid):
    return f"{STORAGE}/object/authenticated/{BUCKET}/{fid}"


def _ff(args, timeout, stdin=None):
    """ffmpeg/ffprobe at the lowest priority, reading storage with the service key."""
    hdr = ["-headers", f"Authorization: Bearer {SERVICE_KEY}\r\n"]
    i = args.index("-i")
    cmd = ["nice", "-n", "19"] + args[:i] + hdr + args[i:]
    return subprocess.run(cmd, capture_output=True, timeout=timeout, stdin=stdin)


def _bytes(fid, limit=MAX_BYTES):
    rs = _object(fid)
    if rs.status_code >= 400:
        rs.close()
        return None
    out = io.BytesIO()
    for chunk in rs.iter_content(1 << 20):
        out.write(chunk)
        if out.tell() > limit:
            rs.close()
            return None
    return out.getvalue()


def _webp(im, size):
    im = ImageOps.exif_transpose(im)
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.mode or im.mode == "P" else "RGB")
    im.thumbnail((size, size))
    buf = io.BytesIO()
    im.save(buf, "WEBP", quality=80, method=4)
    return buf.getvalue()


def _kind(item):
    mime, name = (item.get("mime") or ""), (item.get("name") or "").lower()
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if mime == "application/pdf" or ext == "pdf":
        return "pdf"
    if mime.startswith("audio/"):           # a container holding sound only (a recorded .webm): the type decides
        return "audio"
    if mime.startswith("video/") or ext in ("mp4", "m4v", "mov", "webm", "mkv", "avi", "wmv", "flv", "3gp"):
        return "video"
    if mime.startswith("audio/") or ext in ("mp3", "m4a", "aac", "flac", "ogg", "opus", "wav", "wma"):
        return "audio"
    if mime.startswith("image/") or ext in ("heic", "heif", "tif", "tiff", "psd", "bmp", "webp", "avif", "ico", "gif", "png", "jpg", "jpeg"):
        return "svg" if ext == "svg" or mime == "image/svg+xml" else "image"
    return ""


def _picture(item, size):
    """The picture of one file at `size`, or None. Never raises: a file that cannot be pictured is
    simply a file without a picture."""
    fid, kind = item["id"], _kind(item)
    if Image is None or kind in ("", "svg"):
        return None
    try:
        if kind == "image":
            data = _bytes(fid)
            if not data:
                return None
            im = Image.open(io.BytesIO(data))
            if im.format == "JPEG":
                im.draft("RGB", (size * 2, size * 2))     # decode a JPEG at a fraction of its size: fast, small
            return _webp(im, size)
        if kind == "pdf":
            import pypdfium2 as pdfium
            data = _bytes(fid)
            if not data:
                return None
            doc = pdfium.PdfDocument(data)
            page = doc[0]
            w, h = page.get_size()
            im = page.render(scale=max(0.2, min(4.0, size / max(w, h)))).to_pil()
            doc.close()
            return _webp(im, size)
        if kind == "video":
            dur = (probe(item) or {}).get("duration") or 0
            at = min(max(dur * 0.1, 0.5), 30) if dur else 1
            r = _ff(["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", _src_url(fid), "-frames:v", "1",
                     "-vf", f"scale='min(iw,{size * 2})':-2", "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], 45)
            return _webp(Image.open(io.BytesIO(r.stdout)), size) if r.returncode == 0 and r.stdout else None
        if kind == "audio":                       # the cover the file carries, when it carries one
            r = _ff(["ffmpeg", "-v", "error", "-i", _src_url(fid), "-an", "-frames:v", "1",
                     "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"], 30)
            return _webp(Image.open(io.BytesIO(r.stdout)), size) if r.returncode == 0 and r.stdout else None
    except Exception as e:
        print(f"[drive] no picture of {fid} ({kind}): {e}", flush=True)
    return None


def thumb(item, size):
    """(bytes, 'image/webp') of a file's picture at the nearest size this service makes, or None."""
    size = min(SIZES, key=lambda s: abs(s - int(size or 256)))
    d = _dir(item["id"])
    path, none = os.path.join(d, f"t{size}.webp"), os.path.join(d, "t.none")
    if os.path.exists(path):
        with open(path, "rb") as f:
            return f.read()
    if os.path.exists(none) and time.time() - os.path.getmtime(none) < NONE_TTL:
        return None
    with _one_at_a_time():
        if os.path.exists(path):          # made by another worker while this one waited
            with open(path, "rb") as f:
                return f.read()
        data = _picture(item, size)
    if not data:
        open(none, "w").close()
        return None
    tmp = path + f".{os.getpid()}.tmp"
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    return data


def peaks(item, buckets=600):
    """An audio file's waveform: `buckets` loudness values 0..1, decoded at 2 kHz straight from
    storage. A long recording takes a few seconds once; after that it is a file read."""
    d = _dir(item["id"])
    path = os.path.join(d, f"peaks{buckets}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    if _kind(item) not in ("audio", "video"):
        return None
    with _one_at_a_time():
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        dur = (probe(item) or {}).get("duration") or 0
        rate = 2000
        per = max(1, int(dur * rate / buckets)) if dur else rate
        hdr = ["-headers", f"Authorization: Bearer {SERVICE_KEY}\r\n"]
        p = subprocess.Popen(["nice", "-n", "19", "ffmpeg", "-v", "error"] + hdr + ["-i", _src_url(item["id"]), "-vn", "-ac", "1",
                             "-ar", str(rate), "-f", "s16le", "pipe:1"], stdout=subprocess.PIPE)
        out, t0 = [], time.time()
        try:
            while time.time() - t0 < 180:
                raw = p.stdout.read(per * 2)
                if not raw:
                    break
                a = array.array("h", raw[: len(raw) // 2 * 2])
                out.append(max(max(a), -min(a)) if a else 0)
        finally:
            p.kill()
            p.wait()
    if not out:
        return None
    if len(out) > buckets:                  # an estimate of the duration that was short: fold the rest in
        k = len(out) / buckets
        out = [max(out[int(i * k):int((i + 1) * k)] or [0]) for i in range(buckets)]
    top = max(out) or 1
    vals = [round(v / top, 3) for v in out]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(vals, f)
    return vals


def probe(item):
    """What the media views need to know about a file, kept in `drive_media`: w, h, duration,
    title, artist, album, taken (when a photo was shot / a recording was made)."""
    rows = q("SELECT w,h,duration,title,artist,album,taken FROM drive_media WHERE id=%s", (item["id"],))
    if rows:
        w, h, dur, title, artist, album, taken = rows[0]
        return {"w": w, "h": h, "duration": dur, "title": title, "artist": artist, "album": album,
                "taken": taken.strftime("%Y-%m-%d %H:%M") if taken else None}
    kind, meta = _kind(item), {}
    try:
        if kind in ("video", "audio"):
            r = _ff(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", "-i", _src_url(item["id"])], 30)
            j = json.loads(r.stdout or b"{}")
            fmt, tags = j.get("format") or {}, {k.lower(): v for k, v in ((j.get("format") or {}).get("tags") or {}).items()}
            v = next((s for s in j.get("streams") or [] if s.get("codec_type") == "video" and not (s.get("disposition") or {}).get("attached_pic")), None)
            meta = {"duration": float(fmt.get("duration") or 0) or None, "w": v and v.get("width"), "h": v and v.get("height"),
                    "title": tags.get("title"), "artist": tags.get("artist") or tags.get("album_artist"), "album": tags.get("album"),
                    "taken": (tags.get("creation_time") or "")[:16].replace("T", " ") or None}
        elif kind == "image" and Image is not None:
            data = _bytes(item["id"], 40 * 1024 * 1024)
            if data:
                im = Image.open(io.BytesIO(data))
                w, h = im.size
                ex = im.getexif() if hasattr(im, "getexif") else {}
                if ex and ex.get(274) in (5, 6, 7, 8):        # EXIF orientation turns it a quarter
                    w, h = h, w
                shot = (ex.get_ifd(0x8769).get(36867) if ex else None) or (ex.get(306) if ex else None)
                meta = {"w": w, "h": h, "taken": (str(shot)[:16].replace(":", "-", 2) if shot else None)}
    except Exception as e:
        print(f"[drive] probe of {item['id']} failed: {e}", flush=True)
    q("INSERT INTO drive_media (id,w,h,duration,title,artist,album,taken) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
      "ON CONFLICT (id) DO NOTHING",
      (item["id"], meta.get("w"), meta.get("h"), meta.get("duration"), meta.get("title"), meta.get("artist"),
       meta.get("album"), meta.get("taken")))
    return meta


def has_peaks(fid, buckets=600):
    """Whether a file's waveform is already measured — what a list asks; it never starts the work."""
    return os.path.exists(os.path.join(CACHE, fid.replace("/", "_"), f"peaks{buckets}.json"))


def wants_probe(item):
    """Pictures, videos and audio have something the views show (size, duration, waveform)."""
    return _kind(item) in ("image", "raster", "video", "audio")


def ensure_table():
    q("""CREATE TABLE IF NOT EXISTS drive_media (
            id text PRIMARY KEY,
            w integer, h integer, duration double precision,
            title text, artist text, album text, taken timestamp,
            probed_at timestamptz NOT NULL DEFAULT now())""")


_queue, _queued = [], set()
_wake = threading.Event()


def probe_later(items):
    """Probe these in the background, one at a time — the views ask again on their next refresh."""
    for it in items:
        if it["id"] not in _queued:
            _queued.add(it["id"])
            _queue.append(it)
    _wake.set()


def _worker():
    while True:
        _wake.wait()
        while _queue:
            it = _queue.pop(0)
            try:
                with _one_at_a_time():
                    probe(it)
                if _kind(it) == "audio" and not has_peaks(it["id"]):
                    peaks(it)               # the waveform the lists draw — it takes its own turn at the lock
            except Exception as e:
                print(f"[drive] background probe of {it.get('id')} failed: {e}", flush=True)
            finally:
                _queued.discard(it["id"])
        _wake.clear()


threading.Thread(target=_worker, name="media-probe", daemon=True).start()


def forget(ids):
    """A file deleted for good takes its pictures and facts with it."""
    for fid in ids:
        d = os.path.join(CACHE, fid.replace("/", "_"))
        if os.path.isdir(d):
            for n in os.listdir(d):
                try:
                    os.unlink(os.path.join(d, n))
                except OSError:
                    pass
            try:
                os.rmdir(d)
            except OSError:
                pass
    if ids:
        q("DELETE FROM drive_media WHERE id = ANY(%s)", (list(ids),))
