"""geo — where an address is: country, city, coordinates and network (ASN), from DB-IP's free "lite"
databases (CC BY 4.0 — the screen credits "IP geolocation by DB-IP").

The files are fetched by the office itself on first start and refreshed when a new month's edition is
out (DB-IP publishes on the 1st). The fetch is an ordinary outbound connection, so it appears on the
office's own outbound map like any other. Nothing is sent: these are static downloads.

  SECURITY_GEO=city      country + city coordinates + ASN (≈ 145 MB on disk)  — the default
  SECURITY_GEO=country   country + ASN (≈ 18 MB): a map by country only
  SECURITY_GEO=off       no lookups, no download
"""
from __future__ import annotations

import gzip
import os
import shutil
import threading
import time
import urllib.error
import urllib.request

import mmdb

SOURCE = os.environ.get("SECURITY_GEO_URL", "https://download.db-ip.com/free/").rstrip("/") + "/"
KINDS = {"city": ("city", "asn"), "country": ("country", "asn"), "off": ()}


def _read(path: str) -> str:
    try:
        with open(path, encoding="ascii") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def _write(path: str, text: str) -> None:
    try:
        with open(path + ".tmp", "w", encoding="ascii") as fh:
            fh.write(text + "\n")
        os.replace(path + ".tmp", path)
    except OSError:
        pass


class Geo:
    def __init__(self, directory: str, want: str = "city"):
        self.dir = directory
        self.want = want if want in KINDS else "city"
        self.readers: dict = {}
        self.status: dict = {"want": self.want, "files": {}, "error": "", "checked": 0}
        self.lock = threading.Lock()
        self.busy = threading.Lock()          # one refresh at a time: two wrote one `.part` and both downloaded
        os.makedirs(self.dir, exist_ok=True)
        self._open_existing()

    def _path(self, kind: str) -> str:
        return os.path.join(self.dir, f"dbip-{kind}-lite.mmdb")

    def _open_existing(self) -> None:
        for kind in KINDS[self.want]:
            p = self._path(kind)
            if os.path.exists(p):
                try:
                    r = mmdb.Reader(p)
                    with self.lock:
                        old = self.readers.get(kind)
                        self.readers[kind] = r
                    if old:
                        old.close()
                    self.status["files"][kind] = {"built": r.metadata.get("build_epoch"),
                                                  "type": r.metadata.get("database_type"),
                                                  "bytes": os.path.getsize(p)}
                except Exception as e:                        # noqa: BLE001 — a corrupt file is re-fetched
                    self.status["error"] = f"{kind}: {e}"
                    os.unlink(p)

    def refresh(self) -> None:
        """Fetch any database that is missing or older than this month's edition. Safe to call often:
        it does nothing until a file is missing or a month has turned — and nothing at all while another
        refresh is running."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            self._refresh()
        finally:
            self.busy.release()

    def _refresh(self) -> None:
        self.status["checked"] = time.time()
        if not KINDS[self.want]:
            return
        now = time.gmtime()
        months = [(now.tm_year, now.tm_mon)]
        months.append((now.tm_year - 1, 12) if now.tm_mon == 1 else (now.tm_year, now.tm_mon - 1))
        for kind in KINDS[self.want]:
            p = self._path(kind)
            # WHICH EDITION is on disk is the month in the name it was fetched under, kept beside it. Not
            # the file's build date: DB-IP stamps October's edition «built September 1st», so a freshness
            # rule on that date fetched the same 60 MB again on every restart and every six hours —
            # 424 MB in one day, measured by this app's own volume counter (2026-10-21).
            have = _read(p + ".edition") if os.path.exists(p) else ""
            for y, m in months:
                edition = f"{y:04d}-{m:02d}"
                if have == edition:
                    break                                   # the newest one published is the one we hold
                url = f"{SOURCE}dbip-{kind}-lite-{edition}.mmdb.gz"
                if self._fetch(url, p):
                    _write(p + ".edition", edition)
                    break
        self._open_existing()

    def _fetch(self, url: str, dest: str) -> bool:
        tmp = dest + ".part"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "dgo-security/1 (+https://digital-office.co.il)"})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as out:   # noqa: S310 — a fixed https source
                with gzip.GzipFile(fileobj=r) as gz:
                    shutil.copyfileobj(gz, out, 1 << 20)
            mmdb.Reader(tmp).close()                           # refuse a file that does not open
            os.replace(tmp, dest)
            self.status["error"] = ""
            return True
        except urllib.error.HTTPError as e:
            # the source's own answer: 404 is an edition not published yet, anything else is its words
            words = (e.read() or b"")[:160].decode("utf-8", "replace").strip()
            self.status["error"] = (f"{url.rsplit('/', 1)[-1]}: " + ("המהדורה עוד לא פורסמה" if e.code == 404
                                    else f"מקור המיקום ענה בשגיאה {e.code}" + (f" — {words}" if words else "")))[:300]
        except (urllib.error.URLError, OSError, EOFError, ValueError, IndexError) as e:
            # the download broke, or the file did not open as a location database (mmdb raises ValueError)
            self.status["error"] = f"{url.rsplit('/', 1)[-1]}: ההורדה לא הושלמה — {e}"[:300]
        try:
            os.unlink(tmp)
        except OSError:
            pass
        return False

    def lookup(self, ip: str) -> dict | None:
        """{cc, city, lat, lon, asn, org} — an empty dict for an address no database knows (private,
        reserved), None when no database is loaded yet (the caller fills the row later)."""
        with self.lock:
            readers = dict(self.readers)
        if not readers:
            return None
        out: dict = {}
        place = readers.get("city") or readers.get("country")
        if place:
            rec = place.get(ip) or {}
            country = rec.get("country") or {}
            out["cc"] = country.get("iso_code") or ""
            city = rec.get("city") or {}
            out["city"] = ((city.get("names") or {}).get("en")) or ""
            loc = rec.get("location") or {}
            out["lat"], out["lon"] = loc.get("latitude"), loc.get("longitude")
        a = readers.get("asn")
        if a:
            rec = a.get(ip) or {}
            out["asn"] = rec.get("autonomous_system_number")
            out["org"] = rec.get("autonomous_system_organization") or ""
        return out
