"""sites.public — the PUBLIC PATH: the office serving the website itself.

Why this module exists
----------------------
A site's content can be served by a container the office rendered on a machine (`runtime.py`'s
pattern), or by the OFFICE ITSELF at a public path — a domain (chosen from the `domains` app) plus a
path on it, with no SSO in front of it. The second is what makes the office the serving runtime: the
content lives in the office, the edge routers for it are written by the office, and a site is one
record instead of a stack of files on somebody's server.

Three facts, one owner each
---------------------------
* **the record** — `site["public"] = {"mode": "container" | "office", "entries": [{domain, path}]}`.
  `mode: container` is what every site the office rendered so far is, and it stays the default: this
  module changes nothing until an entry says `office`.
* **the content** — pulled off the machine into a cache here (`sync`), because the office must serve
  a request without an SSH round trip in the path. `<root>/<web_root>` on the machine stays the
  source of truth; the cache is a copy with a fingerprint, never a place anyone edits.
* **the edge** — one file in the edge's own file-provider directory on the machine that runs THIS
  office (`publish`). Discovered from the edge container's own mounts, never assumed: the office on
  a laptop has traefik at `:8080` and the VPS has `traefik-staging` with ACME, and a hardcoded path
  would write a perfect config nothing ever reads.

Public means public
-------------------
A router this module writes carries NO authentik middleware — that is the point of a public path,
and it is also the one way this file could publish something private by accident. So the routers
only ever point at `/public/<id>/…`, which serves files from a site's cache and nothing else: no
directory listing, no dotfiles, no path escaping the cache root, and no access to the office's own
surface (`/api/…` is a different prefix and a different router).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import posixpath
import re
import shutil
import tarfile
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote

import requests

import machines
import runtime
import store
import indexnow  # it imports this module back, and reads nothing of it at import time

log = logging.getLogger("sites.public")

PUBLIC_DIR = Path(os.environ.get("SITES_PUBLIC_DIR", "/data/public"))
MAX_SYNC_BYTES = int(os.environ.get("SITES_PUBLIC_MAX_BYTES", str(256 * 1024 * 1024)))
EDGE_FILE = "sites-public.yaml"
SELF_URL = os.environ.get("SITES_SELF_URL", "http://sites:8979").rstrip("/")
#: The `digital-assets` service, wherever it runs. Same office by default; a peer office reaches it
#: through the link's door, which routes by Host — hence the second variable, which is empty when
#: the app is a plain local service.
ASSETS_URL = os.environ.get("DIGITAL_ASSETS_URL", "http://digital-assets:8985").rstrip("/")
ASSETS_HOST = os.environ.get("DIGITAL_ASSETS_HOST", "").strip()
BUNDLE_TTL = int(os.environ.get("SITES_PUBLIC_BUNDLE_TTL", "60"))
SYNC_SECONDS = int(os.environ.get("SITES_PUBLIC_SYNC_SECONDS", "300"))

DOMAIN_RE = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)+$")
#: named here, not guessed, where the image's Python (3.12) does not know the type — .webp, every image Astro writes
#: — or leaves out a charset: text/markdown requires one (RFC 7763), and the docs' Markdown twins are Hebrew (DGO-1793)
MIME = {".html": "text/html; charset=utf-8", ".htm": "text/html; charset=utf-8",
        ".css": "text/css; charset=utf-8", ".js": "application/javascript; charset=utf-8",
        ".mjs": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml", ".xml": "application/xml; charset=utf-8",
        ".txt": "text/plain; charset=utf-8", ".webmanifest": "application/manifest+json",
        ".woff2": "font/woff2", ".woff": "font/woff", ".ico": "image/x-icon",
        ".webp": "image/webp", ".md": "text/markdown; charset=utf-8"}


# ── the record ───────────────────────────────────────────────────────────────────────────────────
def mode_of(site: dict) -> str:
    """`office` = this app serves it at its public path; `container` = the machine's stack does.

    Anything unrecognised reads as `container`: a typo must never quietly move a live site onto a
    code path that has not been published for it yet.
    """
    return "office" if (site.get("public") or {}).get("mode") == "office" else "container"


def entries_of(site: dict) -> list[dict]:
    """The public path of a site, normalised — one entry per `{domain, path, redirect}`.

    With nothing declared, the site's own `hosts` ARE its public path (path `/`), and the `www`
    twin becomes a redirect when `edge.canonical_redirect` is on — exactly what the rendered nginx
    config did, so switching `mode` does not change what the world resolves.
    """
    pub = site.get("public") or {}
    raw = pub.get("entries")
    out: list[dict] = []
    if raw:
        for e in raw:
            if not isinstance(e, dict):
                continue
            domain = str(e.get("domain") or "").strip().lower()
            path = normal_path(e.get("path"))
            if not domain:
                continue
            out.append({"domain": domain, "path": path, "redirect": bool(e.get("redirect"))})
        return out
    hosts = runtime.hosts_of(site)
    if not hosts:
        return []
    edge = {**runtime.DEFAULT_EDGE, **(site.get("edge") or {})}
    apex = hosts[0]
    twin = f"www.{apex}" if not apex.startswith("www.") else apex[4:]
    for i, h in enumerate(hosts):
        redirect = bool(edge.get("canonical_redirect")) and i > 0 and h == twin
        out.append({"domain": h, "path": "/", "redirect": redirect})
    return out


def normal_path(path) -> str:
    """A path that starts with `/`, has no `..`, and no trailing slash (except the root)."""
    p = "/" + str(path or "/").strip().lstrip("/")
    p = re.sub(r"/{2,}", "/", p)
    if ".." in p:
        p = "/"
    return p if p == "/" else p.rstrip("/")


def clean_entries(entries, hosts: list[str]) -> tuple[list[dict], str | None]:
    """Validate what the UI sent. A domain is a hostname; a path is a path. Nothing else is
    accepted — these values are written into an edge config and into a router rule."""
    out: list[dict] = []
    for e in entries if isinstance(entries, list) else []:
        if not isinstance(e, dict):
            return [], "רשומת נתיב ציבורי חייבת להיות אובייקט {domain, path}"
        domain = str(e.get("domain") or "").strip().lower()
        if not DOMAIN_RE.match(domain):
            return [], f"דומיין לא תקין: {domain!r}"
        path = normal_path(e.get("path"))
        if not re.fullmatch(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*", path):
            return [], f"נתיב לא תקין: {path!r}"
        if not out and not any(h == domain for h in hosts):
            out.append({"domain": domain, "path": path, "redirect": False})   # canonical: first
            continue
        out.append({"domain": domain, "path": path, "redirect": bool(e.get("redirect"))})
    seen: set[tuple[str, str]] = set()
    for e in out:
        key = (e["domain"], e["path"])
        if key in seen:
            return [], f"אותו נתיב ציבורי פעמיים: {e['domain']}{e['path']}"
        seen.add(key)
    return out, None


def canonical_domain(site: dict) -> str:
    """Where a redirect entry points: the first SERVING entry's domain."""
    for e in entries_of(site):
        if not e["redirect"]:
            return e["domain"]
    return runtime.canonical_host(site)


# ── the domains the owner can pick from ──────────────────────────────────────────────────────────
DOMAINS_URL = os.environ.get("DOMAINS_URL", "http://domains:8980").rstrip("/")
_domains_cache: dict = {"at": 0.0, "rows": [], "error": ""}


def domains_list(ttl: int = 120) -> dict:
    """The business's domains, from the `domains` app — the list a public path chooses from.

    A missing domains app is not an error the owner has to fix to edit a site: the answer carries
    `error` and the UI falls back to free text plus the hosts the site already has.
    """
    now = time.time()
    if _domains_cache["rows"] and now - _domains_cache["at"] < ttl:
        return {"domains": _domains_cache["rows"], "error": _domains_cache["error"]}
    try:
        r = requests.get(f"{DOMAINS_URL}/api/domains", timeout=15)
        r.raise_for_status()
        rows = (r.json() or {}).get("domains") or []
        out = [{"name": d.get("name"), "days_left": d.get("days_left"),
                "zone": ((d.get("zone_holder") or {}) or {}).get("zone_holder")}
               for d in rows if d.get("name")]
        err = ""
    except (requests.RequestException, ValueError) as e:
        log.warning("domains_list: %r", e)
        out, err = _domains_cache["rows"], "אפליקציית הדומיינים אינה זמינה"
    _domains_cache.update({"at": now, "rows": out, "error": err})
    return {"domains": out, "error": err}


# ── the content cache ────────────────────────────────────────────────────────────────────────────
def cache_dir(sid: str) -> Path:
    return PUBLIC_DIR / sid


def _meta_path(sid: str) -> Path:
    return PUBLIC_DIR / ".meta" / f"{sid}.json"


def meta(sid: str) -> dict:
    try:
        return json.loads(_meta_path(sid).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(sid: str, data: dict) -> None:
    p = _meta_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _served_dir(site: dict) -> str | None:
    """Where the SERVED files are on the machine, or None when there is nothing to serve."""
    rel = runtime.web_root_dir(site)
    if not rel:
        return None
    return f"{str(site.get('root') or '').rstrip('/')}/{rel}"


#: One slice of a sync's archive per call through the `computers` door. The door holds a command's
#: whole output in memory (and so does this app, once more as JSON), and `computers` runs under a
#: 160 MB cap: a site's archive sent as ONE base64 blob — 4/3 of the site, in one answer — killed it
#: for any site of more than a few dozen MB (Exampleu's clone: 213 MB → ~284 MB of base64, DGO-1503).
SYNC_CHUNK = int(os.environ.get("SITES_PUBLIC_SYNC_CHUNK", str(8 * 1024 * 1024)))


def _fail(res: dict, what: str) -> dict:
    return {"ok": False, "reason": res.get("reason") or f"{what} נכשלה (קוד {res.get('code')})",
            "detail": (res.get("stderr") or "")[-300:]}


_sync_locks: dict[str, threading.Lock] = {}
_sync_locks_guard = threading.Lock()


def sync(site: dict, force: bool = False, wait: bool = False) -> dict:
    """Pull the served directory off the machine into this app's cache — one sync of a site at a time.

    A site is synced from several places (the switch to `office`, the public pass while its cache is
    empty, the sync button, an asset push), and a big one takes minutes: two at once would race on
    the cache's temporary directory. `wait=True` is for a caller whose next step NEEDS this copy — the
    switch to `office` (it then stops the container) and an asset push (it just rewrote the pages):
    it waits its turn, on its own thread. Without it (the button, the public pass) a second sync
    answers that one is running instead of holding its caller for minutes.
    """
    with _sync_locks_guard:
        lock = _sync_locks.setdefault(site["id"], threading.Lock())
    if not lock.acquire(blocking=wait):
        return {"ok": False, "busy": True, "reason": "סנכרון של האתר הזה כבר רץ — התוכן יגיע ממנו"}
    try:
        return _sync(site, force)
    finally:
        lock.release()


def _sync(site: dict, force: bool = False) -> dict:
    """The machine packs the directory into ONE tar in its /var/tmp (disk — /tmp is RAM on Debian 13),
    and the archive comes over the `computers` door in slices of SYNC_CHUNK (base64, so each survives a
    JSON hop) into a file here — so neither this app nor the door ever holds more than one slice,
    whatever the site weighs. The archive is checked against the machine's own size and sha256,
    extracted into a temporary directory and SWAPPED into place: a failed or partial sync leaves the
    previous copy serving, not a half-written one. The staging tar is the only thing written to the
    machine, under a name of its own, and it is removed whatever happens.
    """
    sid = site["id"]
    src = _served_dir(site)
    if not src:
        return {"ok": False, "reason": "לאתר הזה אין תיקיית תוכן מגוגשת (proxy?)"}
    mid = site["machine"]
    q = machines.q
    size_s = machines.stdout_of(mid, f"du -sb {q(src)} 2>/dev/null | cut -f1", timeout=60)
    try:
        size = int((size_s or "0").strip().splitlines()[-1] or 0)
    except (ValueError, IndexError):
        size = 0
    if size and size > MAX_SYNC_BYTES:
        return {"ok": False, "reason": f"התיקון גדול מהמותר ({size // 1048576}MB)"}
    # what a sync of this site that never reached its `finally` left (the app restarted in the middle):
    # no other sync of it runs now — this one holds its lock. The token follows a `.`, which a site id
    # cannot contain, so `exampleu.*` never matches `exampleu-clone.…` — another site's sync in flight.
    machines.exec_on(mid, f"rm -f /var/tmp/bina-site-sync-{q(sid)}.*.tar", timeout=60)
    PUBLIC_DIR.mkdir(parents=True, exist_ok=True)
    for stale in PUBLIC_DIR.glob(f".{sid}.*.tar"):
        stale.unlink(missing_ok=True)
    token = uuid.uuid4().hex[:12]
    stage = f"/var/tmp/bina-site-sync-{sid}.{token}.tar"
    local_tar = PUBLIC_DIR / f".{sid}.{token}.tar"
    received = False
    warning = ""
    try:
        # tar's own exit code is kept and judged here, not by `&&`: GNU tar answers 1 for "file changed
        # as we read it" and 2 for a file it could not read, and in both it still writes the archive of
        # everything else — the one-blob sync synced those sites (base64's code was the pipe's), so this
        # one does too, and says so. No archive at all is a failure.
        res = machines.exec_on(mid, f"tar -C {q(src)} -cf {q(stage)} . ; rc=$?; [ -s {q(stage)} ] || exit 3; "
                                    f"echo TAR_RC=$rc; wc -c < {q(stage)}; "
                                    f"(sha256sum {q(stage)} 2>/dev/null || shasum -a 256 {q(stage)}) | cut -d' ' -f1",
                               timeout=420)
        if res.get("code") != 0:
            return _fail(res, "האריזה")
        out = res.get("stdout") or ""
        rc = re.search(r"TAR_RC=(\d+)", out)
        if not rc or int(rc.group(1)) > 2:
            return _fail({**res, "code": rc.group(1) if rc else res.get("code")}, "האריזה")
        if int(rc.group(1)):
            warning = (res.get("stderr") or "").strip()[-300:] or f"tar exit {rc.group(1)}"
        try:
            total_s, remote_sha = out.split()[-2:]
            total = int(total_s)
        except ValueError:
            return {"ok": False, "reason": "המכונה לא החזירה את גודל הארכיון"}
        if total > MAX_SYNC_BYTES:                      # also where `du -sb` does not exist (busybox)
            return {"ok": False, "reason": f"התיקון גדול מהמותר ({total // 1048576}MB)"}
        digest = hashlib.sha256()
        got = 0
        with open(local_tar, "wb") as fh:
            while got < total:
                part = machines.exec_on(mid, f"tail -c +{got + 1} {q(stage)} | head -c {SYNC_CHUNK} | "
                                             f"base64 | tr -d '\\n'", timeout=300)
                if part.get("code") != 0:
                    return _fail(part, "הקריאה")
                try:
                    chunk = base64.b64decode((part.get("stdout") or "").strip())
                except Exception as e:                          # noqa: BLE001
                    log.warning("sync: %r", e)
                    return {"ok": False, "reason": "פענוח התוכן נכשל"}
                if not chunk:
                    return {"ok": False, "reason": "לא התקבל תוכן מהמכונה", "bytes": got, "total": total}
                fh.write(chunk)
                digest.update(chunk)
                got += len(chunk)
        if got != total or digest.hexdigest() != remote_sha:
            return {"ok": False, "reason": "הארכיון שהתקבל אינו זהה לזה שבמכונה", "bytes": got, "total": total}
        received = True
    finally:
        machines.exec_on(mid, f"rm -f {q(stage)}", timeout=60)
        if not received:
            local_tar.unlink(missing_ok=True)
    dest = cache_dir(sid)
    tmp = PUBLIC_DIR / f".{sid}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    files = 0
    try:
        with tarfile.open(local_tar, mode="r:") as tf:
            for m in tf.getmembers():
                name = posixpath.normpath(m.name.lstrip("./"))
                if name in (".", "") or name.startswith("..") or "/../" in name:
                    continue
                try:
                    tf.extract(m, tmp, filter="data")           # py>=3.12: refuse absolute/.. members
                except TypeError:                               # pragma: no cover — older python
                    tf.extract(m, tmp)
                if m.isfile():
                    files += 1
    except (tarfile.TarError, OSError) as e:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"ok": False, "reason": f"חילוץ הארכיון נכשל ({e})"}
    finally:
        local_tar.unlink(missing_ok=True)
    if warning and not files:
        # tar complained AND nothing readable came: an archive of bare directories, not the site
        shutil.rmtree(tmp, ignore_errors=True)
        return {"ok": False, "reason": "לא נקרא אף קובץ מתיקיית האתר", "detail": warning}
    dest.mkdir(parents=True, exist_ok=True)
    shutil.rmtree(dest, ignore_errors=True)
    tmp.rename(dest)
    info = {"ok": True, "site": sid, "machine": mid, "from": src, "files": files,
            "bytes": total, "source_bytes": size, "at": int(time.time())}
    if warning:
        info["warning"] = warning
    _write_meta(sid, info)
    log.info("public sync %s: %s files, %s bytes from %s", sid, files, total, src)
    return info


def forget(sid: str) -> dict:
    """Drop a site's cache and metadata — called when the site itself is deleted.

    The CACHE is not the site (the machine's directory is), so this is safe by construction: a site
    that comes back re-syncs from its machine. What it prevents is a deleted site's content sitting
    on the office's disk for ever, and a stale `synced_at` for a name that now means something else.
    """
    d = cache_dir(sid)
    had = sum(1 for _ in d.rglob("*")) if d.exists() else 0
    shutil.rmtree(d, ignore_errors=True)
    _meta_path(sid).unlink(missing_ok=True)
    with indexnow._lock:                              # its key and what the engines were told, never mid-submission
        indexnow._state_path(sid).unlink(missing_ok=True)
    return {"removed": str(d), "entries": had}


def cached_file_count(sid: str) -> int:
    d = cache_dir(sid)
    if not d.exists():
        return 0
    return sum(1 for p in d.rglob("*") if p.is_file())


# ── what a browser gets ──────────────────────────────────────────────────────────────────────────
def _safe_path(root: Path, rel: str) -> Path | None:
    """The file this request names, or None when it names something outside the cache."""
    clean = posixpath.normpath("/" + (rel or "")).lstrip("/")
    if clean.startswith("..") or "/../" in clean or clean.startswith("."):
        return None
    p = (root / clean).resolve()
    try:
        p.relative_to(root.resolve())
    except ValueError:
        return None
    return p


def resolve(root: Path, rel: str) -> Path | None:
    """nginx's own resolution order, small: the file, `<rel>.html`, `<rel>/index.html`."""
    p = _safe_path(root, rel)
    if p is None:
        return None
    if p.is_dir():
        idx = p / "index.html"
        return idx if idx.is_file() else None
    if p.is_file():
        return p
    alt = _safe_path(root, (rel or "").rstrip("/") + ".html")
    if alt is not None and alt.is_file():
        return alt
    idx = _safe_path(root, posixpath.join(rel or "", "index.html"))
    return idx if idx is not None and idx.is_file() else None


def content_type(p: Path) -> str:
    ext = p.suffix.lower()
    if ext in MIME:
        return MIME[ext]
    guess, _ = mimetypes.guess_type(p.name)
    return guess or "application/octet-stream"


def https_address(site: dict, host: str, scheme: str, asked: str) -> str:
    """Where a PLAIN-http request for a public site is sent on to, or "" when it is served as it is.

    A PUBLIC SITE HAS ONE ADDRESS (DGO-1765). `http://digital-office.co.il/` and
    `http://bina-solutions.co.il/about/` answered 200 with the page beside the https address (measured
    2026-11-10): every page of both sites existed twice and a search engine was left to choose, while the
    office's own names answer 308 on port 80. The answer is given HERE, by the app that serves the site:
      * not by traefik's `redirectScheme` — v3 answers 301 there, which turns a POST into a GET;
      * not by the office's `port80-https` middleware — its server answers 400 to any host outside the
        office's own domain (platform-base/https-redirect/server.py), which is every public site, and
        traefik drops a router whole when it names a middleware it cannot resolve.
    It is sent on only when ALL of these hold, and served as before otherwise:
      * the edge says the request came over plain http (`X-Forwarded-Proto`, which traefik writes itself);
      * it came on one of the site's own public domains — never the console's mount or this app's host,
        and never a host a stranger put in the header (the Location names only a declared domain);
      * the office's edge answers https for it: `_state["https"]`, which `publish()` sets from the
        machine's live edge — a resolver, and the office's own port-80 rule, which exists only on a server
        office where certificates do. A laptop office, or this process before its first publish, serves.
    `asked` is the path the visitor asked for (traefik's `X-Replaced-Path`, with its query), so an entry
    under a path prefix goes back to that prefix.
    """
    host = (host or "").split(":")[0].strip().lower()
    if (scheme or "").strip().lower() != "http" or not _state.get("https") or not on_public_domain(site, host):
        return ""
    asked = asked if (asked or "").startswith("/") else "/" + (asked or "")
    return f"https://{host}{asked}"


def asked_address(site: dict, host: str, path: str, replaced: str = "", query: str = "") -> str:
    """The path (and query) a visitor asked the public domain for. The edge rewrote `<prefix>/<rest>` onto
    this app's `/public/<id>/<rest>` and says so in `X-Replaced-Path` (`replaced`); without that header the
    entry's own prefix is put back in front of what reached us."""
    if not (replaced or "").startswith("/"):
        host = (host or "").split(":")[0].strip().lower()
        prefix = next((e["path"] for e in entries_of(site) if e["domain"] == host), "/").rstrip("/")
        replaced = f"{prefix}/{(path or '').lstrip('/')}"
    return replaced + (f"?{query}" if query else "")


def edge_answers_https(edge: dict) -> bool:
    """Does this machine's edge answer https for a public site — a certificate resolver, and the office's own
    port-80 rule among the middlewares the LIVE edge lists (`runtime.probe_edge`): that rule is written only
    on a server office that redirects its own names (reconcile.py, `render_https_redirect`), which is where
    certificates exist. `publish()` keeps the answer in `_state["https"]` for `https_address`."""
    return bool(edge.get("tls") and edge.get("certresolver")
                and len(list(edge.get("entrypoints") or [])) > 1
                and PORT80 in (edge.get("middlewares_available") or []))


def serve(site: dict, path: str, host: str = "", count: bool = True, prefix: str = "",
          ua: str = "", ip: str = "", scheme: str = "", asked: str = "") -> dict:
    """The answer for one public request: `{status, headers, body}` (body is bytes).

    The Host decides nothing except redirects: the edge already routed `<domain><path>` here, and
    this app's only job is to hand back the file — or the site's own `404.html`. `prefix` is the
    request's `X-Forwarded-Prefix`: it changes a page only when it names a console mount
    (`under_mount`). `ua` and `ip` (the client's User-Agent and address) only count the visit.
    `scheme` and `asked` are the request's `X-Forwarded-Proto` and the address it asked for: a plain-http
    request on a public domain is sent on to https where the office answers it (`https_address`).
    """
    sid = site["id"]
    onward = https_address(site, host, scheme, asked or asked_address(site, host, path))
    if onward:
        # An hour, not for ever: a browser keeps a 308 with no lifetime indefinitely, and an office whose
        # https later breaks (or whose owner closes the redirect) must not have left visitors stuck on it.
        return {"status": 308, "headers": {"Location": onward, "Content-Type": "text/plain; charset=utf-8",
                                           "Cache-Control": "max-age=3600"},
                "body": b"", "redirect": onward}
    key = indexnow.key_file(site, path)     # `/<key>.txt`: how a search engine knows the site announced itself
    if key:
        return key
    if (path or "").lstrip("/").startswith(".assets/"):
        out = _serve_asset(site, (path or "").lstrip("/"))
        # counted here, as a page is: a request on the site's own domain, never a HEAD (`count`), never the office
        # looking at itself — the asset path used to count every fetch, from any host and any agent
        if count and out.get("status") == 200 and on_public_domain(site, host):
            _count_visit(sid, "/" + (path or "").lstrip("/"), 200, len(out.get("body") or b""), ua, ip)
        return out
    root = cache_dir(sid)
    host = (host or "").split(":")[0].strip().lower()
    target = _redirect_for(site, host, path)
    if target:
        return {"status": 301, "headers": {"Location": target, "Content-Type": "text/plain; charset=utf-8"},
                "body": b"", "redirect": target}
    if not root.exists() or not any(root.iterdir()):
        return {"status": 503, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                "body": "האתר עוד לא סונכרן ללשכה — נסה שוב בעוד רגע".encode("utf-8"),
                "reason": "cache empty"}
    p = resolve(root, path)
    status = 200
    if p is None:
        # nginx's own answer for a directory it has no index for (and autoindex is off): 403, not
        # 404. The difference is visible to anyone comparing the two serving modes, and "exactly
        # the same site" was the whole point of moving it here.
        d = _safe_path(root, path)
        if d is not None and d.is_dir():
            return {"status": 403, "headers": {"Content-Type": "text/html; charset=utf-8"},
                    "body": b"<html>\r\n<head><title>403 Forbidden</title></head>\r\n"
                            b"<body>\r\n<center><h1>403 Forbidden</h1></center>\r\n</body>\r\n</html>\r\n"}
        p = root / "404.html"
        status = 404
        if not p.is_file():
            return {"status": 404, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                    "body": b"Not Found"}
    ctype = content_type(p)
    try:
        body = p.read_bytes()
    except OSError as e:
        log.warning("serve: %r", e)
        return {"status": 500, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                "body": "קריאת הקובץ נכשלה".encode("utf-8")}
    headers = {"Content-Type": ctype, "Cache-Control": "public, max-age=300",
               "X-Served-By": "sites-app"}
    if ctype.startswith("text/html"):
        applied, report = apply_assets(body.decode("utf-8", "replace"), path or "")
        if under_mount(site, prefix, host):
            applied = with_base(applied)
            headers.update({"Cache-Control": "private, no-cache", "Vary": "X-Forwarded-Prefix"})
        body = applied.encode("utf-8")
        if report.get("assets"):
            headers["X-Assets"] = str(report["assets"])
    if count and on_public_domain(site, host):
        _count_visit(sid, "/" + (path or "").lstrip("/"), status, len(body), ua, ip)
    return {"status": status, "headers": headers, "body": body}


# ── seen inside the office: the console's frame ──────────────────────────────────────────────────
# The console reaches an app at `/a/<alias>/…` and writes `<base href="/a/<alias>/">` into every HTML
# page it proxies, unless the page carries a `<base>` of its own (platform-base/console/app.py
# `_inject_base`). Right for an app's own screen, wrong for a site's page, whose every URL is relative
# to the PAGE: `wp-content/x.css` on `/a/sites/public/exampleu/` became `/a/sites/wp-content/x.css`, and
# the site opened from the console with no styles, pictures or working links (measured on Exampleu
# 2026-11-09, DGO-1591). So a page asked for through a console mount — the request says so in
# `X-Forwarded-Prefix` — carries a `<base>` of its own WITHOUT an address (`target="_self"`, the
# default): the console sees a base and writes none, and the browser keeps the one it would have used
# anyway — the document's own address, spelled exactly as it asked for it, query included. Computing
# that address here could only approximate it (the second reader, two rounds: a directory sent `#top`
# to another document; a re-encoded path spelled `(`, `,` or a lowercase `%d7` differently, and the
# browser reloaded instead of scrolling). Anything else (the edge's public routers, the app's own host,
# a probe) gets the bytes unchanged.
_MOUNT_RE = re.compile(r"/a/[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
NO_BASE = '<base target="_self">'


def public_hosts(site: dict) -> list[str]:
    """The domains the site answers on in public: its own `hosts` — or, for a site the office serves
    with only a public path declared (`public.entries`, no `hosts`), that path's serving domains, a
    root entry first and redirect twins left out. The checks know only `hosts`, so a site published
    that way was «לא הוגדר דומיין לאתר» to every scan and never probed for uptime (the second reader,
    DGO-1591). A path entry (`ex.co.il/site`) is checked at its domain's root — a known limit."""
    hosts = [h for h in (site.get("hosts") or []) if h]
    if hosts or mode_of(site) != "office":
        return hosts
    out: list[str] = []
    for e in sorted(entries_of(site), key=lambda e: e["path"] != "/"):
        if not e.get("redirect") and e["domain"] not in out:
            out.append(e["domain"])
    return out


def on_public_domain(site: dict, host: str) -> bool:
    """The request arrived on one of the site's own public domains — a visitor, not the office."""
    host = (host or "").split(":")[0].strip().lower()
    return bool(host) and any(e["domain"] == host for e in entries_of(site))


def under_mount(site: dict, prefix: str, host: str = "") -> bool:
    """True when `prefix` is exactly a console mount (`/a/<alias>`) and the request did not arrive on
    one of the site's own public domains — a visitor's address is the site's, never a mount."""
    if not _MOUNT_RE.fullmatch((prefix or "").strip().rstrip("/")):
        return False
    return not on_public_domain(site, host)


def with_base(html: str, tag: str = NO_BASE) -> str:
    """`html` with `tag` first in its head — unchanged when it already has a base (the page's own
    decision, and the same test the console makes before writing one). A document with neither
    `<head>` nor `<html>` (valid HTML5) gets it after its doctype, a byte-order mark allowed before
    it: ahead of the doctype the browser would render the page in quirks mode."""
    if "<base " in html.lower():
        return html
    m = (re.search(r"<head(?:\s[^>]*)?>", html, re.I) or re.search(r"<html(?:\s[^>]*)?>", html, re.I)
         or re.match(r"[\s﻿]*<!doctype[^>]*>", html, re.I))
    return html[:m.end()] + tag + html[m.end():] if m else tag + html


def preview_path(site: dict) -> str:
    """Where the office shows a site it serves itself, RELATIVE to this app's root — so the same
    link is `/public/<id>/` on the app's own host and `/a/sites/public/<id>/` in the console; ""
    for a site its machine serves (that one opens at its own address)."""
    return f"public/{quote(site['id'], safe='')}/" if mode_of(site) == "office" else ""


def _redirect_for(site: dict, host: str, path: str) -> str:
    """The canonical-redirect answer for this request, or "". `www.` → apex, and only when the
    record says so (an entry marked `redirect`) — the staging alias is a serving entry on purpose."""
    if not host:
        return ""
    apex = canonical_domain(site)
    scheme = "https" if (site.get("edge") or {}).get("tls", True) else "http"
    for e in entries_of(site):
        if not e.get("redirect") or e["domain"] != host:
            continue
        rest = (path or "").lstrip("/")
        return f"{scheme}://{apex}/{rest}"
    return ""


_seen: dict = {}                      # (site, hour) → hashed client addresses already counted
_seen_lock = threading.Lock()
SEEN_CAP = 50_000                     # addresses told apart per site per hour; past it, no more uniques


def _count_visit(sid: str, path: str, status: int, nbytes: int, ua: str = "", ip: str = "") -> None:
    """Visits for a site the OFFICE serves have no nginx log to read, so they are counted here, with
    the meaning the log-based count has (checks/visits.py `aggregate`): a hit per request, a bot by
    its User-Agent, a unique per client address per hour.

    Only a request on one of the site's own public domains reaches here (`serve`): a look from inside
    the office (the console, this app's own host, the internal address) is not a visit — Exampleu's
    clone, which has no domain at all, showed 1011 «ביקורים» in 7 days, every one of them the office's
    own requests (DGO-1591). Nor is the office's own check that arrives through the domain (uptime
    every minute, the scans): `checks.visits.OWN_UA`, left out of the log-based count the same way.
    Uniques were 1 per request — every picture a new visitor; an address is now counted once an hour
    (hashed, held for this hour and the last, at most `SEEN_CAP` of them — past it a flood of fresh
    addresses adds hits, not visitors; a restart may count one twice within the hour)."""
    try:
        from checks.visits import BOT_UA, OWN_UA
        if (ua or "").startswith(OWN_UA):
            return
        bot = bool(BOT_UA.search(ua or ""))
        hour = int(time.time() // 3600) * 3600
        unique = 0
        if not bot:
            key = hashlib.sha256(f"{sid}\0{ip or ''}".encode()).hexdigest()[:16]
            with _seen_lock:
                for k in [k for k in _seen if k[1] < hour - 3600]:
                    _seen.pop(k, None)
                seen = _seen.setdefault((sid, hour), set())
                if key not in seen and len(seen) < SEEN_CAP:
                    seen.add(key)
                    unique = 1
        store.add_visit_hour(sid, hour, 1, unique, 1 if bot else 0, 1 if status >= 400 else 0, nbytes,
                             {} if bot else {path[:200]: 1}, {})
    except Exception as e:                                      # noqa: BLE001 — never fail a request
        log.debug("visit counting failed for %s: %s", sid, type(e).__name__)


# ── digital assets: every text and picture comes from the slot that owns it ──────────────────────
_bundle_cache: dict = {"at": 0.0, "bundle": None, "error": ""}
_bundle_lock = threading.Lock()


def bundle(force: bool = False) -> dict | None:
    """The ACTIVE values of every website slot, cached for `BUNDLE_TTL` seconds.

    None means "not reachable right now" and is a normal answer: the office keeps serving the last
    applied content (the files already carry the values — a push wrote them), because a website that
    goes down when an asset service naps is worse than a website one edit behind.
    """
    now = time.time()
    with _bundle_lock:
        if not force and _bundle_cache["bundle"] is not None and now - _bundle_cache["at"] < BUNDLE_TTL:
            return _bundle_cache["bundle"]
    headers = {"Host": ASSETS_HOST} if ASSETS_HOST else {}
    try:
        r = requests.get(f"{ASSETS_URL}/api/bundle", timeout=12, headers=headers)
        r.raise_for_status()
        data = r.json() or {}
    except (requests.RequestException, ValueError) as e:
        with _bundle_lock:
            _bundle_cache["error"] = f"{type(e).__name__}"
        return _bundle_cache["bundle"] if not force else None
    with _bundle_lock:
        _bundle_cache.update({"at": now, "bundle": data, "error": ""})
    return data


def apply_assets(html: str, page: str = "") -> tuple[str, dict]:
    """Rewrite every `data-da*` value in a page from the active bundle. Never raises: a page that
    cannot be rewritten is served as it is, and the report says the bundle was missing.

    `page` is where the document is inside the site, as the browser asked for it (`""` for the root,
    `projects/x/` for a page in a directory): a file slot's URL is written relative to it."""
    b = bundle()
    if not b:
        return html, {"assets": 0, "reason": "bundle unavailable"}
    try:
        import site_kit
        out, report = site_kit.apply(html, b, file_url=lambda entry: _asset_url(entry, page))
        edits = report.get("changed") or []
        return out, {"assets": len(edits), "missing": report.get("missing") or [],
                     "report": {k: v for k, v in (report or {}).items() if k != "changed"}}
    except Exception as e:                                      # noqa: BLE001
        log.warning("applying the asset bundle failed: %s", type(e).__name__)
        return html, {"assets": 0, "reason": type(e).__name__}


def _asset_url(entry: dict, page: str = "") -> str:
    """A file slot's URL as the PAGE must reference it: `.assets/<file>` in the site, RELATIVE to the page.

    Never the asset service's absolute origin: the site is served on whatever domain its public path
    names, so a page pointing at `http://digital-assets:8985/...` shows an internal name and breaks
    the moment the domain changes. The office serves the file under the site's own prefix instead.

    Relative, not `/.assets/…`: the browser resolves it against the document's own URL, so one page is
    right at a domain's root, under a path entry (`ex.co.il/site/`) and under this app's own prefix
    (`/public/<id>/`, which is how a site is seen inside the office before it has a public address). A
    root-absolute URL named the root of whatever host served the page — a root the site owns only in
    the first of the three, so its pictures broke in the other two. `page` is the document's path
    inside the site as the browser asked for it: one `../` per directory above it.
    """
    up = "../" * (page or "").lstrip("/").count("/")
    url = str((entry or {}).get("url") or "")
    m = re.search(r"/files/([A-Za-z0-9._-]+)$", url)
    if m:
        return f"{up}.assets/{m.group(1)}"
    sha = (entry or {}).get("sha")
    if sha:
        ext = str((entry or {}).get("ext") or "")
        return f"{up}.assets/{sha}" + (f".{ext}" if ext else "")
    return url if url.startswith("/") else ""


def _serve_asset(site: dict, rel: str) -> dict:
    """A file slot, proxied LIVE from `digital-assets` — the picture the slot holds now.

    The alternative (copying the files into the site's cache) makes every asset change a deploy, and
    the owner asked for the opposite: whatever is active in the assets screen is what the site shows.
    """
    name = rel.split("/", 1)[1].lstrip("/") if "/" in rel else ""
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", name or ""):
        return {"status": 404, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                "body": b"Not Found"}
    headers = {"Host": ASSETS_HOST} if ASSETS_HOST else {}
    try:
        r = requests.get(f"{ASSETS_URL}/files/{name}", timeout=20, headers=headers)
    except requests.RequestException as e:
        log.warning("asset fetch: %r", e)
        return {"status": 503, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                "body": "\u05e9\u05d9\u05e8\u05d5\u05ea \u05d4\u05e0\u05db\u05e1\u05d9\u05dd \u05d0\u05d9\u05e0\u05d5 \u05d6\u05de\u05d9\u05df".encode("utf-8")}
    if r.status_code >= 400:
        return {"status": 404, "headers": {"Content-Type": "text/plain; charset=utf-8"},
                "body": b"Not Found"}
    return {"status": 200, "body": r.content,
            "headers": {"Content-Type": r.headers.get("content-type") or "application/octet-stream",
                        "Cache-Control": "public, max-age=86400",
                        "X-Served-By": "sites-app/assets"}}


# ── the edge: the routers that make a site public ────────────────────────────────────────────────
def edge_dir(machine_id: str) -> dict:
    """The edge's own file-provider directory ON the machine, discovered from the container.

    `<dir>:/etc/traefik` in the edge's mounts is the host side of what `--providers.file.directory`
    reads inside the container; writing there is what makes traefik see a new router. A machine with
    no edge returns `{}` and the caller refuses — a public path published nowhere is worse than one
    that says it could not be published.
    """
    edge = runtime.default_edge(machine_id)
    container = edge.get("edge_container")
    if not container:
        return {}
    # `{{json .Mounts}}` and a real parser, NOT a Go template with a newline in it: `\n` inside a
    # single-quoted shell string reaches the template engine as two characters, so every mount came
    # back on ONE line and the "directory" this returned was the whole mount list (measured).
    raw = machines.stdout_of(machine_id,
                             f"docker inspect {machines.q(container)} --format '{{{{json .Mounts}}}}'",
                             timeout=45)
    try:
        mounts = json.loads((raw or "").strip().splitlines()[0])
    except (ValueError, IndexError):
        return {}
    host_dir = ""
    for m in mounts if isinstance(mounts, list) else []:
        dest = str(m.get("Destination") or "").rstrip("/")
        if dest == "/etc/traefik":
            host_dir = str(m.get("Source") or "").rstrip("/")
            break
    if not host_dir.startswith("/"):
        return {}
    return {"container": container, "dir": host_dir, "entrypoints":
            [edge.get("http_entrypoint") or "web", edge.get("https_entrypoint") or "websecure"],
            "certresolver": edge.get("certresolver") or "",
            "tls": bool(edge.get("tls", True)),
            "middlewares_available": edge.get("middlewares_available") or [],
            "middlewares": [m for m in (edge.get("middlewares") or [])
                            if m.split("@")[0] in (edge.get("middlewares_available") or [])
                            or "@" not in m]}


def site_middlewares(site: dict, edge: dict) -> list[str]:
    """The edge middlewares a site's public routers carry: the ones its own record names (`edge.middlewares`), else
    the machine's default — each only when the live edge defines it (`middlewares_available`: traefik drops a router
    that names a middleware it cannot resolve), only from the file provider, and never a sign-in one (a public path
    is public). The record's list used to be ignored here: digital-office.co.il and bina-solutions.co.il name
    `security-headers@file` and `ratelimit-default@file`, and served without them from the day the office took them
    over (no HSTS, nosniff, frame or referrer policy, no rate limit — the sites app's own scan, 2026-11-10)."""
    available = set(edge.get("middlewares_available") or [])

    def usable(names) -> list[str]:
        return [m for m in dict.fromkeys(names or [])
                if m.endswith("@file") and m.split("@")[0] in available and "auth" not in m.lower()]
    # a record whose every name is gone from the edge keeps the default, not an empty chain (it would lose compress)
    return usable((site.get("edge") or {}).get("middlewares")) or usable(edge.get("middlewares"))


def render_edge(sites: list[dict], edge: dict) -> str:
    """The file-provider config for every OFFICE-served site: one router per public entry.

    The router's rule is `<domain>` + the entry's path prefix; its middleware is what turns that
    public address into this app's own serving prefix (`/public/<id>/…`); its backend is this app.
    `priority` is set higher than a container-label router's, so a site mid-migration cannot be
    served twice — the office wins by construction, and taking the record back to `container`
    removes the router entirely.
    """
    routers: dict = {}
    middlewares: dict = {}
    services: dict = {}
    for site in sites:
        # Belt and braces: the filter is applied here too, not only in `office_sites()`. A caller
        # that hands over every site must not be able to publish one that its own record still
        # says the machine serves — two routers for one host is an outage nobody would diagnose.
        if mode_of(site) != "office":
            continue
        sid = site["id"]
        svc = f"sites-public-{sid}"
        services[svc] = {"loadBalancer": {"servers": [{"url": SELF_URL}]}}
        for i, e in enumerate(entries_of(site)):
            rid = f"{svc}-{i}"
            mw = f"{svc}-{i}-to-office"
            prefix = e["path"]
            regex = r"^/" if prefix == "/" else "^" + re.escape(prefix) + r"/?"
            middlewares[mw] = {"replacePathRegex": {"regex": regex, "replacement": f"/public/{sid}/"}}
            chain = [mw] + site_middlewares(site, edge)
            rule = f"Host(`{e['domain']}`) && PathPrefix(`{prefix}`)"
            common = {"rule": rule, "service": svc, "middlewares": chain, "priority": 100}
            eps = list(edge.get("entrypoints") or ["web", "websecure"])
            # TWO routers, one per entrypoint — the platform's own convention, and not a style
            # choice: a router that carries a `tls` block does NOT answer on the plain entrypoint
            # (measured 2026-10-02: `web` returned traefik's own 404 while `websecure` was fine), so
            # a single router with tls silently drops every http request — the exact shape of a site
            # that "is up" and answers nobody.
            if eps:
                routers[f"{rid}-http"] = {**common, "entryPoints": [eps[0]]}
            if edge.get("tls") and edge.get("certresolver") and len(eps) > 1:
                routers[f"{rid}-https"] = {**common, "entryPoints": [eps[-1]],
                                           "tls": {"certResolver": edge["certresolver"]}}
                if not eps[0]:
                    routers.pop(f"{rid}-http", None)
    if not routers:
        return ""
    body = ("# GENERATED by the office's sites app (apps/sites/public.py) — DO NOT EDIT.\n"
            "# One router per site whose PUBLIC PATH says the office serves it. NO forward-auth\n"
            "# middleware is attached here, on purpose: a public path is public by definition, and\n"
            "# this file is the one place that decides it.\n")
    return body + _dump_yaml({"http": {"routers": routers, "middlewares": middlewares,
                                       "services": services}})


def _dump_yaml(obj) -> str:
    try:
        import yaml
        return yaml.safe_dump(obj, allow_unicode=True, sort_keys=True, default_flow_style=False)
    except ImportError:                                          # pragma: no cover
        return json.dumps(obj, ensure_ascii=False, indent=2)


def office_sites(sites: list[dict] | None = None) -> list[dict]:
    rows = sites if sites is not None else store.list_sites()
    return [s for s in rows if mode_of(s) == "office" and entries_of(s)]


def office_machine(machine_id: str = "") -> str:
    """The machine that runs THIS office (`computers`' own builtin) — where the edge lives."""
    if machine_id:
        return machine_id
    rows, err = machines.list_machines(probe=False)
    if err:
        return ""
    for m in rows:
        if m.get("builtin") or m.get("id") == "computer_local-local":
            return m["id"]
    return ""


#: The office's own port-80 rule, by the name the live edge lists it under (`edge_answers_https`).
PORT80 = "port80-https"
_state = {"at": 0.0, "text": "", "machine": "", "error": "", "https": False}


def publish(machine_id: str = "", force: bool = False) -> dict:
    """Write (or remove) the edge file for every office-served site. Idempotent by content.

    The file is written only when its text changed — the edge watches the directory, and a rewrite
    on every tick is churn with no reader. Removing every entry removes the FILE, which is how a
    site goes back to being served by its own container.
    """
    mid = office_machine(machine_id)
    if not mid:
        return {"ok": False, "reason": "לא נמצא המחשב שמריץ את הלשכה"}
    sites = office_sites()
    edge = edge_dir(mid)
    if not edge:
        return {"ok": False, "reason": "לא נמצא קצה (traefik) במחשב הזה"}
    _state["https"] = edge_answers_https(edge)      # asked of the machine at every publish, never remembered
    text = render_edge(sites, edge)
    path = f"{edge['dir']}/{EDGE_FILE}"
    if not text:
        # Nothing to publish. Whether a file is there is asked of the MACHINE, not remembered:
        # after a restart this process has no memory of what it wrote, and a stale router for a
        # site that is back on its container is an outage caused by a cache.
        exists = machines.stdout_of(mid, f"test -f {machines.q(path)} && echo yes || echo no",
                                    timeout=45).strip()
        _state.update({"text": "", "at": time.time(), "machine": mid})
        if exists.endswith("yes"):
            machines.run(mid, f"rm -f {machines.q(path)}", timeout=60, what="הסרת קובץ הקצה")
            return {"ok": True, "removed": True, "file": path}
        return {"ok": True, "removed": False, "written": False, "file": path, "sites": 0}
    if not force and text == _state.get("text") and _state.get("machine") == mid:
        return {"ok": True, "written": False, "file": path, "sites": len(sites), "unchanged": True}
    machines.write_file(mid, path, text, mode=0o644, timeout=90)
    _state.update({"text": text, "at": time.time(), "machine": mid, "error": ""})
    return {"ok": True, "written": True, "file": path, "sites": len(sites),
            "domains": sorted({e["domain"] for s in sites for e in entries_of(s)})}


# ── the site's files on the machine: which texts are slots, and writing the bundle into them ─────
def _pages(site: dict, limit: int = 40) -> list[str]:
    """Every `.html` under the served directory, as paths relative to it."""
    root = cache_dir(site["id"])
    if not root.exists():
        return []
    out = []
    for p in sorted(root.rglob("*.html")):
        if p.name.startswith("."):
            continue
        out.append(str(p.relative_to(root)))
        if len(out) >= limit:
            break
    return out


def slots_scan(site: dict) -> dict:
    """What the site's pages already take from digital-assets, and what is still hand-written.

    Read-only, and it reads the CACHE (the office's own copy) — so the answer is about the content
    the office is serving, and a scan can never depend on a machine being reachable.
    """
    import site_kit
    sid = site["id"]
    if not cache_dir(sid).exists():
        sync(site)
    pages, keys, unmapped = [], set(), []
    for rel in _pages(site):
        try:
            html = (cache_dir(sid) / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        sc = site_kit.scan(html)
        pages.append({"page": rel, "mapped": sc.get("mapped") or [],
                      "unmapped": (sc.get("unmapped") or [])[:40]})
        keys |= set(sc.get("keys") or [])
        for u in (sc.get("unmapped") or [])[:10]:
            unmapped.append({"page": rel, **u})
    return {"site": sid, "pages": pages, "keys": sorted(keys),
            "unmapped": unmapped[:80], "synced_at": meta(sid).get("at")}


def slots_apply(site: dict, bundle: dict, actor: str = "", client: str = "") -> dict:
    """Write the bundle's values into the site's pages on the MACHINE, then re-sync the cache.

    This is the push half of the contract with `digital-assets` (its `website` channel calls here):
    the active value of a slot becomes the text or the picture of the element that declares it. The
    machine stays the source of truth — the office never edits its own cache.
    """
    import site_kit
    sid = site["id"]
    mid = site["machine"]
    src = _served_dir(site)
    if not src:
        return {"ok": False, "reason": "לאתר הזה אין תיקיית תוכן"}
    changed, skipped, errors = [], [], []
    for rel in _pages(site):
        remote = f"{src}/{rel}"
        cur = machines.stdout_of(mid, f"cat {machines.q(remote)}", timeout=60)
        if not cur:
            skipped.append({"page": rel, "reason": "הקובץ לא נקרא"})
            continue
        try:
            out, report = site_kit.apply(cur, bundle, file_url=lambda entry, page=rel: _asset_url(entry, page))
        except Exception as e:                                  # noqa: BLE001
            errors.append({"page": rel, "reason": f"{type(e).__name__}"})
            continue
        edits = report.get("changed") or []
        if not edits:
            continue
        if out == cur:
            continue
        machines.write_file(mid, remote, out, mode=0o644, timeout=120)
        changed.append({"page": rel, "edits": len(edits)})
    res = sync(site, force=True, wait=True)       # the pages just changed: this copy must land
    store.event(sid, "assets", f"הנכסים הופעלו באתר ({len(changed)} עמודים)",
                {"actor": actor, "client": client, "changed": changed, "sync": res.get("ok")})
    return {"ok": True, "site": sid, "changed": changed, "skipped": skipped, "errors": errors,
            "sync": res}


# ── lifecycle: moving a site between its container and the office ────────────────────────────────
def container_action(site: dict, action: str) -> dict:
    """Start/stop the site's own container on its machine (used when the serving mode changes).

    Deliberately `compose stop/start`, not `down`: the stack stays where it is, so going back to
    `container` is one record change and one start — nothing has to be rendered again.
    """
    if not runtime.is_managed(site):
        return {"ok": False, "reason": "אתר שאינו מנוהל (adopted) — אין להפעיל עליו פעולות מלשכה"}
    mid = site["machine"]
    root, project = site["root"], site["project"]
    res = machines.exec_on(mid, runtime._compose(site, f"{action} web"), timeout=180)
    return {"ok": res.get("code") == 0, "action": action, "root": root, "project": project,
            "output": ((res.get("stdout") or "") + (res.get("stderr") or ""))[-400:],
            "code": res.get("code")}


def selftest() -> None:
    """The pure parts, on fixtures. `python3 public.py` runs this."""
    site = {"id": "x", "hosts": ["ex.co.il", "www.ex.co.il", "site.staging.ex.co.il"],
            "edge": {"canonical_redirect": True}, "public": None}
    ents = entries_of(site)
    assert [e["domain"] for e in ents] == site["hosts"], ents
    assert [e["redirect"] for e in ents] == [False, True, False], ents
    assert entries_of({"id": "y", "public": {"entries": [{"domain": "a.co.il", "path": "docs/"}]}})[0] == \
        {"domain": "a.co.il", "path": "/docs", "redirect": False}
    assert mode_of({"public": {"mode": "weird"}}) == "container"
    ok, err = clean_entries([{"domain": "A.co.il", "path": "/x"}, {"domain": "b.co.il"}], [])
    assert err is None and ok[0]["domain"] == "a.co.il" and ok[1]["path"] == "/", (ok, err)
    _, err = clean_entries([{"domain": "not a domain"}], [])
    assert err, "a bad domain must be refused"
    _, err = clean_entries([{"domain": "a.co.il", "path": "/x"},
                            {"domain": "a.co.il", "path": "/x/"}], [])
    assert err and "פעמיים" in err, err
    text = render_edge([{"id": "d", "hosts": ["d.co.il"], "public": {"mode": "office"}}],
                       {"entrypoints": ["web", "websecure"], "certresolver": "myresolver",
                        "tls": True, "middlewares": ["compress@file"]})
    assert "Host(`d.co.il`)" in text and "/public/d/" in text, text
    assert "certResolver: myresolver" in text, text
    # No forward-auth is attached to a public router — asserted on the PARSED config, because the
    # file's own comment says the word and a substring test would fail on prose.
    import yaml as _yaml
    _cfg = _yaml.safe_load(text)["http"]
    for _r in _cfg["routers"].values():
        assert not any("authentik" in m for m in _r.get("middlewares") or []), _r
    # TWO routers, one per entrypoint: a router carrying `tls` does not answer on the plain one.
    assert "sites-public-d-0-http:" in text and "sites-public-d-0-https:" in text, text
    assert "- websecure" in text, text
    assert render_edge([], {}) == "" and render_edge([{"id": "d", "hosts": ["d.co.il"]}],
                                                     {"certresolver": "r", "tls": True}) == ""
    # a site's own middlewares reach its routers — only those the edge defines, from the file provider, never a
    # sign-in one; a site that names none keeps the machine's default
    _edge = {"entrypoints": ["web", "websecure"], "certresolver": "r", "tls": True, "middlewares": ["compress@file"],
             "middlewares_available": ["compress", "security-headers", "ratelimit-default", "authentik"]}
    _own = {"id": "s", "hosts": ["s.co.il"], "public": {"mode": "office"},
            "edge": {"middlewares": ["ratelimit-default@file", "security-headers@file", "compress@file", "gone@file",
                                     "authentik@file", "x@docker", "security-headers@file"]}}
    _want = ["ratelimit-default@file", "security-headers@file", "compress@file"]
    assert site_middlewares(_own, _edge) == _want, site_middlewares(_own, _edge)
    assert site_middlewares({"id": "t"}, _edge) == ["compress@file"]
    assert site_middlewares({"id": "u", "edge": {"middlewares": ["gone@file"]}}, _edge) == ["compress@file"]
    # the edge's catalogue is what a `middlewares:` MAPPING defines — not a router's list, a setting or a header name
    _text = ("http:\n  middlewares:\n    security-headers:\n      headers:\n        customFrameOptionsValue: SAMEORIGIN\n"
             "        customRequestHeaders:\n          Host: x\n    compress:\n      compress: {}\n  routers:\n"
             "    dgo-port80:\n      middlewares:\n      - port80-https\n      service: dgo-port80\n"
             "    other:\n      middlewares:\n        - compress\n      service: s\n"
             "http:\n    middlewares:\n        port80-https:\n            redirectScheme: {}\n"
             "http:\n  middlewares:   # the sign-in ones\n    authentik:\n{{- if .X }}\n      forwardAuth: {}\n"
             "{{- end }}\n    'ratelimit-default':\n      rateLimit: {}\n")
    assert runtime._middlewares_from(_text) == ["security-headers", "compress", "port80-https", "authentik",
                                                "ratelimit-default"], runtime._middlewares_from(_text)
    _routers = _yaml.safe_load(render_edge([_own], _edge))["http"]["routers"]
    assert _routers["sites-public-s-0-https"]["middlewares"] == ["sites-public-s-0-to-office"] + _want, _routers
    assert _routers["sites-public-s-0-http"]["middlewares"] == ["sites-public-s-0-to-office"] + _want, _routers
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        root = Path(d).resolve()        # macOS: /var links to /private/var, and resolve() answers the real path
        (root / "index.html").write_text("<h1>hi</h1>")
        (root / "about").mkdir()
        (root / "about" / "index.html").write_text("about")
        (root / "features.html").write_text("f")
        assert resolve(root, "") == root / "index.html"
        assert resolve(root, "about").name == "index.html"
        assert resolve(root, "features").name == "features.html"
        assert resolve(root, "../etc/passwd") is None
        assert resolve(root, ".hidden") is None
        assert resolve(root, "nope") is None
        (root / "noindex").mkdir()
        assert resolve(root, "noindex") is None and (root / "noindex").is_dir()
    # named, not guessed: Python 3.12 knows no .webp (octet-stream, measured live) and gives .md no charset
    assert content_type(Path("x/shot.light.he.webp")) == "image/webp"
    assert content_type(Path("he/start.md")) == "text/markdown; charset=utf-8"
    assert _asset_url({"url": "http://digital-assets:8985/files/ab12cd.png"}) == ".assets/ab12cd.png"
    assert _asset_url({"sha": "ff00", "ext": "svg"}) == ".assets/ff00.svg"
    assert _asset_url({"url": "/local.png"}) == "/local.png" and _asset_url({}) == ""
    # relative to the document: one `../` per directory above it, whatever prefix serves the site
    e = {"url": "http://digital-assets:8985/files/ab12cd.png"}
    assert _asset_url(e, "about/") == "../.assets/ab12cd.png"
    assert _asset_url(e, "/projects/x/index.html") == "../../.assets/ab12cd.png"
    assert _asset_url(e, "features") == ".assets/ab12cd.png"
    import posixpath as _pp
    for _prefix in ("/", "/public/s/", "/site/"):
        for _page in ("", "about/", "projects/x/"):
            _doc = _prefix + _page
            _abs = _pp.normpath(_pp.join(_pp.dirname(_doc), _asset_url(e, _page)))
            assert _abs == _prefix + ".assets/ab12cd.png", (_prefix, _page, _abs)
    # a page asked for through a console mount carries a base of its own, with no address
    _s = {"id": "s", "public": {"mode": "office", "entries": [{"domain": "ex.co.il", "path": "/"}]}}
    assert under_mount(_s, "/a/sites") and under_mount(_s, "/a/sites/") and under_mount(_s, "/a/sites.exampleu")
    assert not under_mount(_s, "") and not under_mount(_s, "/site") and not under_mount(_s, "/a/")
    assert not under_mount(_s, '/a/x"><script>') and not under_mount(_s, "/a/sites/public")
    assert not under_mount(_s, "/a/sites", host="ex.co.il:443")       # a visitor's address is the site's
    assert NO_BASE == '<base target="_self">' and "href" not in NO_BASE
    assert with_base("<html><head><title>t</title>") == '<html><head><base target="_self"><title>t</title>'
    assert with_base('<head lang="he">x') == '<head lang="he"><base target="_self">x'
    assert with_base("<head><base href='/own/'>") == "<head><base href='/own/'>"
    assert with_base("<header>x") == '<base target="_self"><header>x'     # <header> is not <head>
    assert (with_base("<!doctype html><meta charset=utf-8><title>x</title>")    # no head, no html
            == '<!doctype html><base target="_self"><meta charset=utf-8><title>x</title>')
    assert with_base("﻿<!DOCTYPE html><p>x") == '﻿<!DOCTYPE html><base target="_self"><p>x'
    assert preview_path(_s) == "public/s/" and preview_path({"id": "c", "hosts": ["c.co.il"]}) == ""
    print("public.py selftest: ok")


if __name__ == "__main__":
    selftest()
