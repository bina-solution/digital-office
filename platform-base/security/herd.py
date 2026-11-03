"""herd — the other offices this one is linked to, and one call to an app of theirs through the link.

The compiled registry (`.generated/registry/remote.<office>.<alias>.json`, one file per app a linked
office gives this one) is the whole truth about who is linked and where: its `link_port` is this
office's door to that office, and `<alias>.<office>` is a name on the office network (the link proxy
carries it). A call goes `http://<alias>.<office>:<link_port><path>`; the serving office's door
answers only for apps it gives, writes its own identity for the caller, and adds `X-Dgo-Office` —
the caller cannot choose who it is there.
"""
from __future__ import annotations

import json
import os
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor


class Herd:
    def __init__(self, registry_dir: str):
        self.dir = registry_dir
        self.cache: dict = {}
        self.lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=6)

    def offices(self) -> dict:
        """{office: {label, address, commit, apps: {alias: {port, link_port, name}}}}"""
        out: dict = {}
        try:
            files = os.listdir(self.dir)
        except OSError:
            return out
        for f in files:
            if not (f.startswith("remote.") and f.endswith(".json")):
                continue
            try:
                d = json.load(open(os.path.join(self.dir, f), encoding="utf-8"))
            except (OSError, ValueError):
                continue
            rem = d.get("remote") or {}
            office = rem.get("office")
            if not office:
                continue
            lab = rem.get("label") or {}
            o = out.setdefault(office, {"office": office, "label": (lab.get("he") if isinstance(lab, dict) else lab) or office,
                                        "address": rem.get("address"), "commit": rem.get("commit"), "apps": {}})
            o["apps"][d.get("alias") or d.get("app")] = {"app": d.get("app"), "port": d.get("port"),
                                                         "link_port": d.get("link_port"), "name": d.get("name")}
        return out

    def call(self, office: str, alias: str, path: str, timeout: float = 6.0):
        """(status, json|None, error) — one GET to an app of a linked office, through this office's door."""
        o = self.offices().get(office) or {}
        a = (o.get("apps") or {}).get(alias)
        if not a:
            return 0, None, "האפליקציה לא ניתנת לנו על ידי הלשכה הזאת"
        port = a.get("link_port") or a.get("port")
        url = f"http://{alias}.{office}:{port}{path}"
        req = urllib.request.Request(url, headers={"Host": f"{alias}.{office}", "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:   # noqa: S310 — an office-network name
                return r.status, json.loads(r.read(4 * 1024 * 1024) or b"null"), ""
        except urllib.error.HTTPError as e:
            door = e.headers.get("X-Dgo-Door", "")
            return e.code, None, f"HTTP {e.code}" + (f" ({door})" if door else "")
        except Exception as e:                                        # noqa: BLE001
            return 0, None, f"{type(e).__name__}"

    def cached(self, office: str, alias: str, path: str, ttl: float = 20.0):
        key = (office, alias, path)
        with self.lock:
            hit = self.cache.get(key)
        if hit and time.time() - hit[0] < ttl:
            return hit[1]
        res = self.call(office, alias, path)
        with self.lock:
            self.cache[key] = (time.time(), res)
        return res

    def each(self, alias: str, path: str) -> list:
        """The same call to every linked office that gives `alias`, in parallel; offices that do not
        give it are listed with why."""
        offs = self.offices()
        rows = []
        futs = {}
        for office, o in offs.items():
            if alias in (o.get("apps") or {}):
                futs[office] = self.pool.submit(self.cached, office, alias, path)
            else:
                rows.append({"office": office, "label": o["label"], "ok": False, "installed": False,
                             "error": "האפליקציה לא מותקנת שם, או לא ניתנת ללשכה הזאת"})
        for office, fut in futs.items():
            status, body, err = fut.result()
            rows.append({"office": office, "label": offs[office]["label"], "ok": status == 200 and body is not None,
                         "installed": True, "status": status, "error": err, "data": body})
        return sorted(rows, key=lambda r: (not r["ok"], r["office"]))
