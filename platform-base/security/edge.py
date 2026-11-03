"""edge — who reached this office: the edge's access log and the identity provider's sign-ins, read from
the engine's own log stream (the same stream any-concurrency reads), and every request classified.

A request is one of:
  public    a public website or an app with no sign-in of the office's (its own login, or none)
  private   an app behind the office's sign-in (the console and everything gated by it)
  remote    an app of ANOTHER office, opened here through the link (this office's edge serves the tile)
  auth      the sign-in pages themselves
  door      the link door (offices joining and carrying their tunnel over 443)
  none      a request no router took: a scan of the bare address, a host nobody declared

What decides it is the router traefik picked, and what the router carries: an `authentik` middleware
means private. The routers are read from the containers' own labels (the compiled truth, not a list
kept here) and refreshed every minute; file-provider routers are recognised by the names the compiler
gives them (`dgo-remote-<office>-<alias>-…`, `sites-public-<site>-…`).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time

import netparse as np
from dockerapi import Docker, DockerError

_SUFFIX = re.compile(r"-(https|http|local|frame|own-origin|signed-in|enter|websocket(-\d+)?|http-\d+|https-\d+)$")
#: The office's sign-in services: authentik, and forward-auth, which replaces it (r030-002). A router
#: of theirs is the sign-in page itself, never an app behind it.
_AUTH_APPS = ("forward-auth", "authentik")


def _auth_app(name: str) -> str:
    return next((a for a in _AUTH_APPS if name.startswith(a)), "")


class Routers:
    """router name → {app, kind, office, title}."""

    def __init__(self, docker: Docker, registry_dir: str):
        self.docker = docker
        self.registry_dir = registry_dir
        self.meta: dict = {}
        self.offices: dict = {}       # office id → label
        self.titles: dict = {}        # app / alias / service → Hebrew name
        self.sso_mw: set = set()
        self.at = 0.0
        self.lock = threading.Lock()

    def refresh(self) -> None:
        meta, titles, offices = {}, {}, {}
        try:
            containers = self.docker.containers()
        except DockerError:
            containers = []
        for c in containers:
            labels = c.get("Labels") or {}
            svc = labels.get("com.docker.compose.service") or (c.get("Names") or ["?"])[0].lstrip("/")
            for k, v in labels.items():
                m = re.match(r"^traefik\.http\.routers\.([^.]+)\.(middlewares|service|rule)$", k)
                if not m:
                    continue
                r = meta.setdefault(m.group(1), {"service": svc, "middlewares": "", "rule": ""})
                r[m.group(2)] = v
        reg = self.registry_dir
        try:
            for f in os.listdir(reg):
                if f.startswith("remote.") and f.endswith(".json"):
                    try:
                        d = json.load(open(os.path.join(reg, f), encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    rem = d.get("remote") or {}
                    office = rem.get("office")
                    if office:
                        lab = rem.get("label") or {}
                        offices[office] = (lab.get("he") if isinstance(lab, dict) else lab) or office
                        titles[f"{office}/{d.get('alias')}"] = d.get("name") or d.get("alias")
                elif f == "office.apps.json":
                    try:
                        d = json.load(open(os.path.join(reg, f), encoding="utf-8"))
                    except (OSError, ValueError):
                        continue
                    for a in d.get("apps") or []:
                        for key in (a.get("app"), a.get("alias"), a.get("service")):
                            if key:
                                titles[key] = a.get("name") or key
        except OSError:
            pass
        try:
            import yaml  # optional: console.modules.yaml names every tile, local ones included
            mods = yaml.safe_load(open(os.path.join(reg, "console.modules.yaml"), encoding="utf-8")) or {}
            for m in (mods.get("modules") if isinstance(mods, dict) else mods) or []:
                if isinstance(m, dict) and m.get("id") and "." not in str(m.get("id")):
                    titles.setdefault(str(m.get("id")), m.get("name") or m.get("id"))
                    if m.get("alias"):
                        titles.setdefault(str(m.get("alias")), m.get("name") or m.get("alias"))
        except Exception:                                      # noqa: BLE001 — names are a nicety
            pass
        with self.lock:
            self.meta, self.titles, self.offices, self.at = meta, titles, offices, time.time()

    def classify(self, router: str) -> dict:
        """→ {kind, app, office}."""
        name = (router or "").split("@", 1)[0]
        if not name:
            return {"kind": "none", "app": "", "office": ""}
        if name.startswith("dgo-remote-"):
            rest = name[len("dgo-remote-"):]
            with self.lock:
                offices = sorted(self.offices, key=len, reverse=True)
            for office in offices:
                if rest.startswith(office + "-"):
                    alias = rest[len(office) + 1:]
                    alias = re.sub(r"-console(-.*)?$", "", alias)
                    return {"kind": "remote", "app": alias, "office": office}
            parts = rest.split("-")
            return {"kind": "remote", "app": parts[-2] if len(parts) > 2 else rest, "office": parts[0]}
        if name.startswith("sites-public-"):
            site = re.sub(r"-\d+(-https?)?$", "", name[len("sites-public-"):])
            return {"kind": "public", "app": f"site:{site}", "office": ""}
        with self.lock:
            m = self.meta.get(name)
        base = _SUFFIX.sub("", name)
        if m:
            app = m.get("service") or base
            mws = m.get("middlewares") or ""
            who = _auth_app(app) or _auth_app(base)
            if who:
                return {"kind": "auth", "app": who, "office": ""}
            if name.endswith("link-door"):
                return {"kind": "door", "app": app, "office": ""}
            return {"kind": "private" if "authentik" in mws else "public", "app": app, "office": ""}
        who = _auth_app(base)
        if who:
            return {"kind": "auth", "app": who, "office": ""}
        return {"kind": "private", "app": base, "office": ""}

    def title(self, app: str, office: str = "") -> str:
        with self.lock:
            if office:
                return self.titles.get(f"{office}/{app}") or app
            return self.titles.get(app) or app


class Tail(threading.Thread):
    """Follow one container's log stream from a remembered point, hand each line to `on_line`, and come
    back from wherever it stopped: a restarted edge, a recreated container, an engine that blinked."""

    def __init__(self, docker: Docker, container: str, cursor_get, cursor_put, on_line, name: str, backfill_s: int = 6 * 3600):
        super().__init__(daemon=True, name=f"tail-{name}")
        self.docker = docker
        self.container = container
        self.cursor_get, self.cursor_put = cursor_get, cursor_put
        self.on_line = on_line
        self.backfill_s = backfill_s
        self.health = {"ok": None, "error": "", "lines": 0, "parsed": 0, "container": container, "last": 0}
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            cur = self.cursor_get()
            # docker's `since` is inclusive: resume one microsecond after the last line already read
            since = (cur + 1e-6) if cur else (time.time() - self.backfill_s)
            try:
                tty = bool(((self.docker.inspect(self.container) or {}).get("Config") or {}).get("Tty"))
                self.health.update(ok=True, error="")
                last_save = time.time()
                for ts_text, line in self.docker.logs(self.container, since=since, follow=True, tty=tty):
                    if self.stop.is_set():
                        return
                    ts = np.docker_ts(ts_text) or time.time()
                    self.health["lines"] += 1
                    if self.on_line(ts, line):
                        self.health["parsed"] += 1
                        self.health["last"] = ts
                    since = ts
                    if time.time() - last_save > 5:
                        self.cursor_put(since)
                        last_save = time.time()
                self.cursor_put(since)
                self.health.update(ok=False, error="the stream ended (container restarted?)")
            except DockerError as e:
                self.health.update(ok=False, error=str(e)[:300])
            except Exception as e:                             # noqa: BLE001 — keep following
                self.health.update(ok=False, error=f"{type(e).__name__}: {e}"[:300])
            self.stop.wait(5)
