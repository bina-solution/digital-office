"""sites.indexnow — a site the office serves tells the search engines which of its pages changed (DGO-1765).

Why
---
Bing (the index DuckDuckGo and others read) did not hold digital-office.co.il at all on 2026-11-10, and a crawler
finds a changed page only when it comes back by itself. IndexNow (https://www.indexnow.org) is the open protocol
for saying it: one POST of the changed addresses to `api.indexnow.org`, which passes them on to every engine that
takes part (Bing, Yandex, Naver, Seznam, Yep; Google does not). The engine believes the site because the site
serves a key file it chose: `https://<host>/<key>.txt`, whose body is the key.

What it does, and when
----------------------
* **the key** — one per site, made the first time the site is announced, kept in the app's state beside the site's
  public cache (`<public>/.meta/<id>.indexnow.json`). It is public by design (the engine reads it from the site).
* **the key file** — `serve()` answers `/<key>.txt` with the key, before any file of the site.
* **which addresses** — the site's own sitemaps: the ones its robots.txt names (`Sitemap:`), else `sitemap.xml`,
  else `sitemap-index.xml` (Astro's name; a sitemap index is followed into its sitemaps in the cache): the site
  says which pages it has, and their canonical addresses. Only an `https://` address on one of the site's
  own serving domains, under that domain's entry path, is sent.
* **which of them** — the ones whose cached file changed since the last answer the engine accepted (a fingerprint
  of the file the address resolves to, the way `serve()` resolves it), the new ones, and the ones that left the
  sitemap or whose file is gone (an engine must hear about a page that went too). Nothing changed → nothing sent.
  The fingerprint is of the CACHED file: a change that reaches a page only at serving time (an asset bundle of
  `digital-assets`) is announced with the next sync of the site, not before.
* **when** — the scheduler's public pass (`scheduler.public_pass`, every five minutes) after the edge is published,
  and `POST /api/sites/<id>/indexnow` (`{"all": true}` sends every address). A pass that finds the cache as it was
  at the last look does no work. The pass sends at most once per site every `MIN_SECONDS` (`all` sends now); after
  a refusal or an error, the next try waits `RETRY_SECONDS`.
* **only where it is true** — the office serves the site (`mode: office`) on a server office whose edge answers
  https (`public._state["https"]`, set by `publish()` from the live edge: a laptop office never announces), the
  site has a sitemap, its own robots.txt does not close it to every crawler, its record does not say
  `public.indexnow: false`, and — before anything is sent — the key file answers the key at the address the engine
  will read (each office makes its own key). That last one keeps a copy of a site whose DNS points at another
  server from being announced: the engine could not believe it either. A clone reached on a host of its own (a
  staging alias) is announced only if its sitemap names that host and its robots.txt leaves it open — close it
  there. `SITES_INDEXNOW=0` turns it off for the office.

The outside calls of this module: the POST to `INDEXNOW_URL`, and a GET of the site's own key file at its public
address just before it. Nothing else leaves the office.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import posixpath
import re
import secrets
import threading
import time
import xml.etree.ElementTree as ET
from urllib.parse import unquote, urlsplit

import requests

import public
import store

log = logging.getLogger("sites.indexnow")

ENABLED = os.environ.get("SITES_INDEXNOW", "1") != "0"
INDEXNOW_URL = os.environ.get("SITES_INDEXNOW_URL", "https://api.indexnow.org/indexnow").strip()
MIN_SECONDS = int(os.environ.get("SITES_INDEXNOW_MIN_SECONDS", "600"))
RETRY_SECONDS = int(os.environ.get("SITES_INDEXNOW_RETRY_SECONDS", "3600"))
BATCH = 10_000                         # the protocol's limit of addresses in one POST
SITEMAP_FILES = 50                     # sitemap files read for one site, at most (named, and followed from an index)
KEY_RE = re.compile(r"^[0-9a-f]{32}$")
KEY_FILE_RE = re.compile(r"^[0-9a-f]{32}\.txt$")
_lock = threading.Lock()               # the scheduler's pass and the API's «send now» share one state file


# ── the state: the key, and what the engine last accepted ───────────────────────────────────────
def _state_path(sid: str):
    return public.PUBLIC_DIR / ".meta" / f"{sid}.indexnow.json"


def state(sid: str) -> dict:
    try:
        data = json.loads(_state_path(sid).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(sid: str, data: dict) -> None:
    p = _state_path(sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def key_of(sid: str) -> str:
    """The site's key, or "" when it has none yet. Reading never makes one."""
    key = str(state(sid).get("key") or "")
    return key if KEY_RE.match(key) else ""


def _ensure_key(sid: str) -> str:
    key = key_of(sid)
    if not key:
        key = secrets.token_hex(16)
        _write_state(sid, {**state(sid), "key": key})
    return key


def key_file(site: dict, path: str) -> dict | None:
    """The answer to `/<key>.txt` for this site, or None when `path` is not its key file. The state is read only
    for a path shaped like a key file, never for every request of the site."""
    name = (path or "").strip("/")
    if not KEY_FILE_RE.match(name):
        return None
    key = key_of(site["id"])
    if not key or name != f"{key}.txt":
        return None
    return {"status": 200, "headers": {"Content-Type": "text/plain; charset=utf-8",
                                       "Cache-Control": "public, max-age=300", "X-Served-By": "sites-app"},
            "body": key.encode("ascii")}


# ── the addresses: the sitemap, on the site's own serving domains ───────────────────────────────
def _serving(site: dict) -> list[dict]:
    """The entries that serve the site (not a redirect twin), the longest path first."""
    rows = [e for e in public.entries_of(site) if not e.get("redirect")]
    return sorted(rows, key=lambda e: -len(e["path"]))


def _rel_of(site: dict, url: str) -> tuple[str, str, str] | None:
    """(host, the entry's path prefix — "" at the root, the path inside the site's cache) for an address the site
    serves, else None. Under a prefix only an address BELOW it counts (`/blog/…`, not `/blog`): a key file under
    `/blog/` vouches for nothing else. The cache path is decoded, as `serve()` gets it; the address is sent as is."""
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return None
    host = (u.hostname or "").lower()
    if u.scheme != "https" or not host:
        return None
    path = u.path or "/"
    for e in _serving(site):
        if e["domain"] != host:
            continue
        prefix = e["path"].rstrip("/")
        if prefix and not path.startswith(prefix + "/"):
            continue
        return host, prefix, unquote(path[len(prefix):]).lstrip("/")
    return None


def _local(tag) -> str:
    return str(tag).rsplit("}", 1)[-1]


def _locs(site: dict, root, rel: str, seen: set) -> list[str]:
    """The `<loc>`s of a sitemap file in the cache, following a sitemap index into the sitemaps the site serves
    (each child named by its address, which is mapped into the cache the way a request for it would be). Matched
    by local name: a sitemap that forgot its namespace is still read."""
    if rel in seen or len(seen) >= SITEMAP_FILES:
        return []
    seen.add(rel)
    p = public._safe_path(root, rel)
    if p is None or not p.is_file():
        return []
    try:
        doc = ET.fromstring(p.read_bytes())
    except (ET.ParseError, ValueError, LookupError):      # LookupError: an encoding Python does not know
        log.warning("indexnow: %s of %s is not a sitemap XML can read", rel, site["id"])
        return []
    locs = [(e.text or "").strip() for e in doc.iter() if _local(e.tag) == "loc" and (e.text or "").strip()]
    if _local(doc.tag) == "sitemapindex":
        out: list[str] = []
        for loc in locs:
            where = _rel_of(site, loc)
            if where:
                out.extend(_locs(site, root, where[2], seen))
        return out
    return locs


def fingerprints(site: dict) -> dict:
    """{address: fingerprint of the file it serves} for every address of the site's sitemap it may send."""
    root = public.cache_dir(site["id"])
    out: dict = {}
    seen: set = set()
    for url in [u for rel in sitemaps_of(site, root) for u in _locs(site, root, rel, seen)]:
        where = _rel_of(site, url)
        if not where or url in out:
            continue
        p = public.resolve(root, where[2])
        try:
            out[url] = hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p is not None else ""
        except OSError:
            out[url] = ""
    return out


def changed(now: dict, sent: dict) -> list[str]:
    """New, changed, gone (left the sitemap) and missing-file addresses — the ones an engine must re-read. A page
    whose file went missing differs from what was accepted (its fingerprint becomes ""), and once that "" is
    accepted it is not sent again on every look."""
    out = [u for u, fp in now.items() if sent.get(u) != fp]
    out += [u for u in sent if u not in now]
    return out


def _robots(root) -> list[tuple[str, str]]:
    """The `(field, value)` lines of the site's own robots.txt, the field lower-cased and comments dropped."""
    p = public._safe_path(root, "robots.txt")
    if p is None or not p.is_file():
        return []
    try:
        lines = p.read_text(encoding="utf-8-sig", errors="replace").splitlines()     # -sig: a BOM is not a field
    except OSError:
        return []
    out = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if line and ":" in line:
            field, value = (s.strip() for s in line.split(":", 1))
            out.append((field.lower(), value))
    return out


#: where a site whose robots.txt names no sitemap keeps it: the protocol's name, then Astro's (the docs, DGO-1788)
SITEMAP_NAMES = ("sitemap.xml", "sitemap-index.xml")


def sitemaps_of(site: dict, root) -> list[str]:
    """The cache paths of the site's sitemaps, [] when it has none: the ones its own robots.txt names (`Sitemap:`, the
    protocol's way to name a sitemap that is not /sitemap.xml — a WordPress copy's wp-sitemap.xml) on the site's own
    serving domains, else the first of SITEMAP_NAMES it has."""
    def there(rel: str) -> bool:
        p = public._safe_path(root, rel)
        return p is not None and p.is_file()
    named = [w[2] for field, value in _robots(root)
             if field == "sitemap" and (w := _rel_of(site, value)) and there(w[2])]
    return list(dict.fromkeys(named)) or [n for n in SITEMAP_NAMES if there(n)][:1]


def _robots_closed(root) -> bool:
    """The site's own robots.txt closes it to every crawler (`User-agent: *` with `Disallow: /`): a staging alias
    or a clone that says so is not announced, whatever host it is reached on."""
    agents, closed, group_open = [], False, False
    for field, value in _robots(root):
        if field == "user-agent":
            agents = agents if group_open else []
            agents.append(value)
            group_open = True
            continue
        group_open = False
        if field == "disallow" and "*" in agents and value == "/":
            closed = True
    return closed


# ── the submission ──────────────────────────────────────────────────────────────────────────────
def why_not(site: dict) -> str:
    """Why this site is not announced now, or "" when it is."""
    if not ENABLED or not INDEXNOW_URL:
        return "IndexNow כבוי בלשכה הזו (SITES_INDEXNOW=0)"
    if (site.get("public") or {}).get("indexnow") is False:
        return "הרשומה של האתר אומרת public.indexnow: false"
    if public.mode_of(site) != "office" or not _serving(site):
        return "הלשכה לא מגישה את האתר בכתובת ציבורית"
    if not public._state.get("https"):
        return "הקצה של המחשב הזה לא עונה https (מחשב נייד, או לפני הפרסום הראשון)"
    if not sitemaps_of(site, public.cache_dir(site["id"])):
        return "אין לאתר sitemap (לא ב-robots.txt, לא sitemap.xml ולא sitemap-index.xml)"
    if _robots_closed(public.cache_dir(site["id"])):
        return "ה-robots.txt של האתר סוגר אותו לכל סורק (Disallow: /)"
    return ""


#: the office's own requests say so: `checks.visits.OWN_UA` («BinaOfficeSites/») is the prefix the visit count leaves
#: out (DGO-1591) — spelled here, not imported, because `checks` imports every check and public.py imports it lazily
HEADERS = {"User-Agent": "BinaOfficeSites/1.0 (+digital office IndexNow)"}


def _key_answers(location: str, key: str) -> bool:
    """Does the world reach this office for that address: the key file, asked for at its public address."""
    try:
        r = requests.get(location, timeout=15, allow_redirects=False, headers=HEADERS)
        return r.status_code == 200 and (r.text or "").strip() == key
    except Exception as e:                                          # noqa: BLE001
        log.info("indexnow: key file %s: %s", location, type(e).__name__)
        return False


def submit(site: dict, force: bool = False, now: float | None = None) -> dict:
    """Send the site's changed addresses (every address with `force`) — or say why nothing was sent."""
    with _lock:
        return _submit(site, force, time.time() if now is None else now)


def _submit(site: dict, force: bool, now: float) -> dict:
    sid = site["id"]
    reason = why_not(site)
    if reason:
        return {"ok": True, "sent": 0, "skipped": reason}
    st = state(sid)
    synced = float(public.meta(sid).get("at") or 0)
    if not force:
        if st.get("retry_at") and now < float(st["retry_at"]):
            return {"ok": True, "sent": 0, "skipped": "ממתין לניסיון חוזר"}
        if not st.get("retry_at") and st.get("synced") == synced:
            return {"ok": True, "sent": 0, "skipped": "התוכן לא השתנה מאז הבדיקה האחרונה"}
        if st.get("at") and now - float(st["at"]) < MIN_SECONDS:
            return {"ok": True, "sent": 0, "skipped": f"הודעה אחרונה נשלחה לפני פחות מ-{MIN_SECONDS // 60} דקות"}
    prints = fingerprints(site)
    sent = dict(st.get("sent") or {})
    if not prints and sent:
        # a sitemap that is there but reads as nothing (broken, an encoding Python does not know, swapped in the
        # middle of a sync) is not «every page went»: nothing is sent, and it is looked at again with the next sync
        return {"ok": True, "sent": 0, "skipped": "ה-sitemap לא נקרא כרגע — לא נשלח דבר"}
    urls = list(prints) + [u for u in sent if u not in prints] if force else changed(prints, sent)
    if not urls:
        _write_state(sid, {**st, "synced": synced, "sent": prints, "retry_at": 0})
        return {"ok": True, "sent": 0, "skipped": "אין כתובת שהשתנתה" if prints or sent
                else "ה-sitemap לא מונה אף כתובת https בדומיין שהאתר מוגש בו"}
    key = _ensure_key(sid)
    # One POST per (host, entry path): a key file under `/blog/` vouches only for addresses under `/blog/`.
    groups: dict = {}
    for u in urls:
        where = _rel_of(site, u)
        if where:
            groups.setdefault(where[:2], []).append(u)
    results = []
    for (host, prefix), rows in groups.items():
        location = f"https://{host}{prefix}/{key}.txt"
        if not _key_answers(location, key):
            # the world does not reach this office at that address: nothing is sent, and nothing is said on the
            # site's events — a copy or a clone is not a failure; it is looked at again after RETRY_SECONDS
            results.append({"host": host, "count": 0, "status": "key-unreachable", "rows": []})
            continue
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i + BATCH]
            body = {"host": host, "key": key, "keyLocation": location, "urlList": batch}
            try:
                r = requests.post(INDEXNOW_URL, json=body, timeout=30,
                                  headers={**HEADERS, "Content-Type": "application/json; charset=utf-8"})
                code = r.status_code
            except Exception as e:                                  # noqa: BLE001
                code = 0
                log.warning("indexnow %s: %s", sid, type(e).__name__)
            # 200 and 202 are both «received» (202: the key is still being checked)
            results.append({"host": host, "count": len(batch), "status": code, "rows": batch})
    ok = all(r["status"] in (200, 202) for r in results)
    # what the engine accepted is recorded per batch: a refusal of one host does not re-send another's
    for r in results:
        if r["status"] in (200, 202):
            for u in r["rows"]:
                if u in prints:
                    sent[u] = prints[u]
                else:
                    sent.pop(u, None)
    last = {"at": now, "count": sum(r["count"] for r in results if r["status"] in (200, 202)), "ok": ok,
            "results": [{k: v for k, v in r.items() if k != "rows"} for r in results]}
    unreachable = any(r["status"] == "key-unreachable" for r in results)
    if ok:
        _write_state(sid, {**state(sid), "at": now, "synced": synced, "sent": prints, "retry_at": 0, "last": last})
    else:
        _write_state(sid, {**state(sid), "at": now, "sent": sent, "retry_at": now + RETRY_SECONDS, "last": last})
    return {"ok": ok, "sent": last["count"], "results": last["results"],
            **({"skipped": "קובץ המפתח לא נענה בכתובת הציבורית — האתר לא מוגש מכאן לעולם"} if unreachable else {})}


def record(site: dict, res: dict) -> None:
    """One line on the site's events for an announcement that sent something, or one the engine refused."""
    refused = [r for r in (res.get("results") or []) if r.get("status") not in (200, 202, "key-unreachable")]
    if res.get("sent"):
        store.event(site["id"], "indexnow", f"נשלחו {res['sent']} כתובות למנועי החיפוש (IndexNow)",
                    {"sent": res["sent"], "ok": bool(res.get("ok"))})
    if refused:
        store.event(site["id"], "indexnow_failed",
                    f"מנועי החיפוש לא קיבלו את הכתובות (IndexNow, קוד {refused[0].get('status')}) — "
                    f"ניסיון חוזר בעוד {RETRY_SECONDS // 60} דקות", {"status": str(refused[0].get("status"))})


def status(site: dict) -> dict:
    """What the office says about this site to the engines: the key file, the last answer, what is waiting."""
    st = state(site["id"])
    key = key_of(site["id"])
    reason = why_not(site)
    out = {"enabled": not reason, "reason": reason, "endpoint": INDEXNOW_URL,
           "key_files": [f"https://{e['domain']}{posixpath.join(e['path'], key + '.txt')}"
                         for e in _serving(site)] if key else [],
           "last": st.get("last") or {}, "retry_at": st.get("retry_at") or 0}
    if not reason:
        out["waiting"] = len(changed(fingerprints(site), st.get("sent") or {}))
    return out


def pass_site(site: dict) -> dict:
    """The scheduler's call: announce what changed, and say so on the site's events."""
    res = submit(site)
    record(site, res)
    return res
