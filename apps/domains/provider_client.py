"""provider_client — the generic domains app's door to its PROVIDER APPS (ai/context/provider-apps.md).

The owner, 2026-11-08 (DGO-1473): «every implementation of a specific provider becomes an application
solving interaction with that provider», and the generic app «organising and serving all». So this app
holds no provider's code any more: a provider whose only door is a website (InterNIC) is its own app,
`domain-<provider>`, and this module is how the generic app finds it and asks it.

FINDING THEM — by name, in what the compiler already writes (no list of providers lives here):
  - an app of THIS office: `.generated/registry/office.apps.json`, an entry whose `app` is `domain-*`,
    reached at http://<service>:<port>;
  - an app a LINKED office gives this one (the provider runs where the browser signed in to it runs):
    `.generated/registry/remote.<office>.<alias>.json` with `app: domain-*`, reached at
    http://<module.host>:<link_port> — the door project-pln reaches the HP's Plane by.
  Ours first. Two linked offices giving the same provider is NOT guessed between (a client's office we
  installed may run its own, with its own account): it is reported, unless
  DOMAIN_PROVIDER_<ID>_OFFICE names the office. DOMAIN_PROVIDER_<ID>_URL overrides the whole lookup.

ASKING THEM — domain-provider.v1 (apps/domain-internic/app.py lists the ops). The functions below keep
the names and shapes the generic app called on the provider's code before it moved, so the screens,
the consent door and the history did not change: only where the answer comes from.
"""
from __future__ import annotations

import glob
import json
import os
import time

import requests

REGISTRY = os.environ.get("DOMAINS_REGISTRY_DIR", "/registry")
PREFIX = "domain-"
# A read answers in seconds or the link is down: it must not hold a worker thread for minutes. A panel
# write reads, saves and reads back through a browser, and gets the long one.
READ_TIMEOUT = float(os.environ.get("DOMAIN_PROVIDER_READ_TIMEOUT", "45"))
# a read that drives the browser through the panel (the zone editor's own budget is 150 s, browser_ops)
PANEL_TIMEOUT = float(os.environ.get("DOMAIN_PROVIDER_PANEL_TIMEOUT", "180"))
WRITE_TIMEOUT = float(os.environ.get("DOMAIN_PROVIDER_WRITE_TIMEOUT", "330"))
_cache: dict = {"at": 0.0, "found": {}}


class ProviderUnavailable(Exception):
    def __init__(self, provider: str, reason: str):
        super().__init__(reason)
        self.provider, self.reason = provider, reason


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def providers(force: bool = False) -> dict:
    """{provider id: {"url", "app", "office" (None = this office), "candidates"}} — every domain-* app."""
    if not force and time.time() - _cache["at"] < 30:
        return _cache["found"]
    found: dict = {}
    for entry in (_read(os.path.join(REGISTRY, "office.apps.json")).get("apps") or []):
        app = entry.get("app") or ""
        if app.startswith(PREFIX) and entry.get("port"):
            pid = app[len(PREFIX):]
            found[pid] = {"app": app, "office": None, "candidates": [None],
                          "url": f"http://{entry.get('service') or app}:{entry['port']}"}
    remote: dict = {}
    for path in sorted(glob.glob(os.path.join(REGISTRY, "remote.*.json"))):
        entry = _read(path)
        app = entry.get("app") or ""
        host = (entry.get("module") or {}).get("host")
        port = entry.get("link_port") or entry.get("port")      # as the compiler reads it (remote_records)
        if app.startswith(PREFIX) and host and port:
            office = (entry.get("remote") or {}).get("office")
            remote.setdefault(app[len(PREFIX):], []).append(
                {"app": app, "office": office, "url": f"http://{host}:{port}"})
    for pid, rows in remote.items():
        if pid in found:
            found[pid]["candidates"] += [r["office"] for r in rows]
            continue
        chosen = os.environ.get(f"DOMAIN_PROVIDER_{pid.upper().replace('-', '_')}_OFFICE", "").strip()
        pick = [r for r in rows if r["office"] == chosen] if chosen else rows
        if len(pick) == 1:
            found[pid] = {**pick[0], "candidates": [r["office"] for r in rows]}
        else:
            offices = ", ".join(str(r["office"]) for r in rows)
            why = (f"DOMAIN_PROVIDER_{pid.upper().replace('-', '_')}_OFFICE names {chosen}, and no linked office by "
                   f"that name gives {rows[0]['app']} (given by: {offices})") if chosen else (
                   f"{len(rows)} linked offices give {rows[0]['app']} ({offices}) — set "
                   f"DOMAIN_PROVIDER_{pid.upper().replace('-', '_')}_OFFICE to choose")
            found[pid] = {"app": rows[0]["app"], "office": None, "url": None,
                          "candidates": [r["office"] for r in rows], "ambiguous": why}
    for pid in list(found):
        override = os.environ.get(f"DOMAIN_PROVIDER_{pid.upper().replace('-', '_')}_URL", "").strip()
        if override:
            found[pid] = {**found[pid], "url": override.rstrip("/")}
    _cache.update(at=time.time(), found=found)
    return found


def endpoint(provider: str) -> str:
    p = providers().get(provider)
    if not p:
        raise ProviderUnavailable(provider, f"no {PREFIX}{provider} app runs on this office or is given to it")
    if not p.get("url"):
        raise ProviderUnavailable(provider, p.get("ambiguous") or f"{PREFIX}{provider} has no address")
    return p["url"]


MUTATING = ("/api/records", "/api/run", "/api/selftest")


def _call(provider: str, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> dict:
    """One provider op. For an op that CHANGES something, every answer short of "never reached" is a write
    nobody can vouch for (`unverified`): a read timeout, a dropped connection after sending, a gateway's
    non-JSON page. Only a refused connection, or the link door's empty no-app answer, means it did not act."""
    mutating = method == "POST" and path.startswith(MUTATING)
    unknown = {"ok": False, "state": "unverified", "saved": None, "provider": provider,
               "error": f"the {PREFIX}{provider} app did not give an answer — whether it acted is unknown"}
    try:
        # a door that drops packets is found out in 5 s; the answer then gets its own budget
        r = requests.request(method, endpoint(provider) + path, json=body,
                             timeout=(5, timeout or READ_TIMEOUT))
    except ProviderUnavailable as e:
        return {"ok": False, "state": "provider_unavailable", "error": e.reason, "provider": provider}
    except requests.ConnectionError as e:
        if mutating and not isinstance(e, requests.ConnectTimeout) and "Connection refused" not in str(e):
            return unknown
        return {"ok": False, "state": "provider_unavailable", "provider": provider,
                "error": f"the {PREFIX}{provider} app could not be reached ({type(e).__name__})"}
    except requests.ReadTimeout:
        return unknown if mutating else {"ok": False, "state": "timeout", "provider": provider,
                                         "error": f"the {PREFIX}{provider} app did not answer in time"}
    except requests.RequestException as e:
        return unknown if mutating else {"ok": False, "state": "provider_unavailable", "provider": provider,
                                         "error": f"the {PREFIX}{provider} app did not answer ({type(e).__name__})"}
    try:
        doc = r.json()
    except ValueError:
        # an EMPTY 404/502 from a linked office is its door saying the app is not served (door-empty-404)
        if r.status_code in (404, 502) and not (r.content or b"").strip():
            return {"ok": False, "state": "provider_unavailable", "provider": provider,
                    "error": f"the {PREFIX}{provider} app is not served here (HTTP {r.status_code}, no body)"}
        return unknown if mutating else {"ok": False, "state": "provider_unavailable", "provider": provider,
                                         "error": f"the {PREFIX}{provider} app answered HTTP {r.status_code} "
                                                  f"with no JSON"}
    return doc if isinstance(doc, dict) else {"ok": False, "state": "invalid", "error": "not an object"}


# ── the surface the generic app calls (the names the provider's code had) ─────────────────────────
def describe(provider: str) -> dict:
    return _call(provider, "GET", "/ops")


def origin(provider: str) -> str:
    return describe(provider).get("origin") or ""


def available() -> dict:
    """What used to be «is the office browser here»: which provider apps answer, and where they run."""
    out = {}
    for pid, p in providers().items():
        out[pid] = {"app": p["app"], "office": p.get("office"), "url": p.get("url"),
                    "ambiguous": p.get("ambiguous")}
    return {"available": any(p.get("url") for p in out.values()), "providers": out}


def state(provider: str) -> dict:
    st = _call(provider, "GET", "/api/state", timeout=PANEL_TIMEOUT)
    sess = st.get("session") or {}
    return {**sess, "state": sess.get("state") or st.get("state"), "provider_app": st.get("ok", False)}


def connect_check(provider: str) -> dict:
    return _call(provider, "POST", "/api/connect", timeout=PANEL_TIMEOUT)


def read_domains(provider: str) -> dict:
    return _call(provider, "GET", "/api/domains", timeout=PANEL_TIMEOUT)


def read_zone(provider: str, domain: str) -> dict:
    return _call(provider, "GET", f"/api/zones/{domain}", timeout=PANEL_TIMEOUT)


def write_state(provider: str) -> dict:
    res = _call(provider, "GET", "/api/write-state")
    if res.get("state") == "provider_unavailable":
        return {"enabled": False, "state": "provider_unavailable", "actions": {}, "title": res.get("error"),
                "why": "", "how": "", "portal_url": ""}
    return res


def write(provider: str, action: str, params: dict, consented_by: str | None) -> dict:
    """One record write. The consent is passed to the provider, which gates on it and, after a write it
    read back, marks the action the office's own (that mark is the provider's: the write is its)."""
    body = {"action": action, **(params or {})}
    if consented_by:
        body["consented_by"] = consented_by
    return _call(provider, "POST", "/api/records", body, timeout=WRITE_TIMEOUT)


def verified(provider: str, action: str) -> bool:
    return bool(_call(provider, "GET", f"/api/verified?action={action}").get("verified"))


def run(provider: str, operation: str, params: dict | None = None) -> dict:
    return _call(provider, "POST", "/api/run", {"operation": operation, "params": params or {}},
                 timeout=WRITE_TIMEOUT)
