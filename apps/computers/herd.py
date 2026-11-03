"""herd — every office's computer, and one READ of a service on it.

The owner, 2026-10-21 (DGO-890): "machine app and computers app should merge so every dgo shows his
computer in computers and you can see open there the resource view … and network view (inbound and
outbound) … all accessible from the vps so i can see all computer resource view of all 4 … machines live".

So a computer of the herd is not a row in a table of ours. It is what two services ON THAT COMPUTER say
about it — `machine` (the resource view: processor, memory, disk, network, the apps running) and
`security` (the network view: who came in, where it went out) — read here, through this office's door
when the computer belongs to a linked office:

    this office          http://machine:8080/<path>               (the service's own address)
    a linked office      http://machine.<office>:<link_port>/<path>   (the door; the link proxy carries it)

The compiled registry (`.generated/registry/remote.<office>.<alias>.json`, one file per app a linked
office gives this one) is the whole truth about who is linked and what they give: an office that does
not give `security` shows its resources and says so about its network, rather than this app guessing.

EVERY call is a GET to a path on `ALLOW`. This screen shows another office's machine; it does not
drive it — the one write it makes (a cleanup on THIS computer) is a separate, local-only door in app.py.
"""
from __future__ import annotations

import ipaddress
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

#: what the screen may read, per service — nothing else crosses this door
ALLOW = {
    "machine": ("api/overview", "api/storage", "api/power", "api/cleanup/options"),
    # `api/host/overview` is the security service's own reading of the machine, in machine's shape: the
    # resource view falls back to it on a computer that runs security without machine (the Mac does)
    "security": ("api/summary", "api/network", "api/inbound", "api/outbound", "api/map", "api/bans", "api/host/overview"),
}
#: ONE record of a list, by the address that names it: `<prefix>/<ip>` — the network view's detail of one
#: address that came in and one destination that was called (security's `api/inbound/{ip}`, `api/outbound/{ip}`).
#: The last part must BE an address (it is parsed and written back), so nothing else rides on the prefix.
ALLOW_ONE = {"security": ("api/inbound", "api/outbound")}
#: the query parameters a read may carry (a window, a filter) — the rest are dropped
QUERY_KEYS = ("hours", "kind", "q", "limit")


def allowed(svc: str, path: str) -> str:
    """The path as it is sent, or "" when the screen may not read it."""
    if path in ALLOW.get(svc, ()):
        return path
    prefix, _, last = path.rpartition("/")
    # an IPv6 zone (`fe80::1%…`) parses and is written back with whatever follows the `%`: refused
    if prefix in ALLOW_ONE.get(svc, ()) and "%" not in last:
        try:
            return f"{prefix}/{ipaddress.ip_address(last)}"
        except ValueError:
            return ""
    return ""


class Herd:
    def __init__(self, registry_dir: str, local: dict, office: str = ""):
        self.dir = registry_dir
        self.local = {k: (v or "").rstrip("/") for k, v in (local or {}).items()}
        self.office = office or "local"
        self.cache: dict = {}
        self.lock = threading.Lock()

    # ── who is linked ────────────────────────────────────────────────────────────────────────────
    def offices(self) -> dict:
        """{office: {office, label, address, commit, apps: {alias: {app, port, link_port}}}}"""
        out: dict = {}
        try:
            files = os.listdir(self.dir)
        except OSError:
            return out
        for f in sorted(files):
            if not (f.startswith("remote.") and f.endswith(".json")):
                continue
            try:
                with open(os.path.join(self.dir, f), encoding="utf-8") as fh:
                    d = json.load(fh)
            except (OSError, ValueError):
                continue
            rem = d.get("remote") or {}
            office = rem.get("office")
            if not office:
                continue
            lab = rem.get("label") or {}
            o = out.setdefault(office, {
                "office": office,
                "label": (lab.get("he") if isinstance(lab, dict) else lab) or office,
                "address": rem.get("address") or "", "commit": rem.get("commit") or "", "apps": {}})
            alias = d.get("alias") or d.get("app")
            o["apps"][alias] = {"app": d.get("app"), "port": d.get("port"), "link_port": d.get("link_port")}
        return out

    def computers(self) -> list:
        """This office's computer first, then one per linked office, each with what it gives."""
        rows = [{"where": "local", "office": self.office, "label": "המחשב הזה", "local": True,
                 "gives": {svc: bool(self.local.get(svc)) for svc in ALLOW}}]
        for o in self.offices().values():
            rows.append({"where": o["office"], "office": o["office"], "label": o["label"], "local": False,
                         "address": o["address"], "commit": o["commit"],
                         "gives": {svc: svc in o["apps"] for svc in ALLOW}})
        return rows

    # ── one read ─────────────────────────────────────────────────────────────────────────────────
    def url(self, where: str, svc: str, path: str) -> str:
        if where == "local":
            base = self.local.get(svc)
            return f"{base}/{path}" if base else ""
        a = ((self.offices().get(where) or {}).get("apps") or {}).get(svc)
        if not a:
            return ""
        port = a.get("link_port") or a.get("port")
        return f"http://{svc}.{where}:{port}/{path}" if port else ""

    def get(self, where: str, svc: str, path: str, query: dict | None = None,
            ttl: float = 4.0, timeout: float = 10.0) -> tuple[int, object, str]:
        """(status, json-or-None, Hebrew reason). A read nobody allowed is refused before any network."""
        path = allowed(svc, path.strip("/"))
        if not path:
            return 403, None, "הקריאה הזאת אינה מותרת דרך המחשבים"
        url = self.url(where, svc, path)
        if not url:
            return 404, None, ("השירות לא מותקן במחשב הזה" if where == "local"
                               else "הלשכה הזאת לא נותנת את השירות הזה דרך הקישור")
        q = {k: str(v) for k, v in (query or {}).items() if k in QUERY_KEYS and v not in (None, "")}
        if q:
            url += "?" + urllib.parse.urlencode(q)
        now = time.time()
        with self.lock:
            hit = self.cache.get(url)
            if hit and now - hit[0] < ttl:
                return hit[1], hit[2], hit[3]
        status, body, why = self._fetch(url, timeout, local=where == "local")
        with self.lock:
            self.cache[url] = (time.time(), status, body, why)
            if len(self.cache) > 400:                      # an hour of a busy screen, never more
                for k in sorted(self.cache, key=lambda k: self.cache[k][0])[:200]:
                    self.cache.pop(k, None)
        return status, body, why

    @staticmethod
    def _fetch(url: str, timeout: float, local: bool = False) -> tuple[int, object, str]:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"null"), ""
        except urllib.error.HTTPError as e:
            return e.code, None, "השירות במחשב ענה בשגיאה"
        except (urllib.error.URLError, OSError, ValueError) as e:
            reason = getattr(e, "reason", e)
            if isinstance(reason, TimeoutError) or "timed out" in str(reason):
                return 504, None, "המחשב לא ענה בזמן"
            # THIS office's service is reached by its compose name, and the engine resolves a name only
            # while that container runs: a name nobody answers to is a service that does not run here.
            # vps1 had no `security` at all, and the screen said «no way to this computer» (2026-11-01).
            if local and isinstance(reason, socket.gaierror):
                return 404, None, "השירות לא פועל במחשב הזה"
            return 502, None, "אין דרך למחשב הזה כרגע"
