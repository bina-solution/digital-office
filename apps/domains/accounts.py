"""domains.accounts — every provider account is an INSTANCE in the credential plane.

Same shape as drive, mail, git and computers (ai/context/platform-service-contract.md §1): the vault
is the one copy of an account, this app holds no token in its config, its environment or its volume,
and the console's account bar is rendered from the service contract rather than from a list here.

One difference from `git`, and it is a real one: the office's OWN registrar needs no credential at
all. `domain_registry_whois` exists so that the domains this business actually runs can be watched
(expiry, lock status, nameservers) with nothing to paste — the registry publishes that to anyone.
The consequence is that this app is useful the moment it starts, before the owner connects anything.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import requests

import providers
from providers import DomainError, PROVIDER_OF, adapter_for

log = logging.getLogger("domains.accounts")

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
STATE_DIR = Path(os.environ.get("DOMAINS_STATE_DIR", "/data"))
ACTIVE_PATH = STATE_DIR / "active.json"
PROBE_TTL = float(os.environ.get("DOMAINS_PROBE_TTL", "120"))
VT = 10

#: provider → its default protocol. DERIVED from the catalogue rather than hand-maintained: the
#: first version of this map was a literal, and the moment four more providers were added to
#: `providers.PROVIDERS` the API answered "ספק לא מוכר: 'porkbun'" for a provider it had just
#: advertised. A catalogue that can disagree with itself is worse than a small one.
def _protocols_from_catalog() -> dict:
    out = {}
    for p in providers.PROVIDERS:
        for m in p.get("auth_methods") or []:
            if m.get("protocol"):
                out.setdefault(p["id"], m["protocol"])
    return out


PROTOCOLS = _protocols_from_catalog()
PROVIDERS_CATALOG = providers.PROVIDERS

#: every protocol the catalogue can produce — what /connections and /manifest report
ALL_PROTOCOLS = sorted({m.get("protocol") for p in PROVIDERS_CATALOG
                        for m in (p.get("auth_methods") or []) if m.get("protocol")})

_active_lock = threading.Lock()


def active_id() -> str | None:
    try:
        return (json.loads(ACTIVE_PATH.read_text(encoding="utf-8")) or {}).get("active")
    except (OSError, ValueError):
        return None


def set_active(cid: str | None) -> None:
    with _active_lock:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        ACTIVE_PATH.write_text(json.dumps({"active": cid}), encoding="utf-8")


def protocol_for(provider: str) -> str | None:
    return PROTOCOLS.get(provider)


def auth_method(provider: str, method_id: str) -> dict | None:
    for p in PROVIDERS_CATALOG:
        if p["id"] != provider:
            continue
        for m in p["auth_methods"]:
            if m["id"] == method_id:
                return m
    return None


# ── the vault ────────────────────────────────────────────────────────────────────────────────────
def vault_list(protocol: str | None = None) -> tuple[list[dict], str | None]:
    try:
        params = {"protocol": protocol} if protocol else None
        r = requests.get(f"{CONNECTIONS_URL}/api/instances", params=params, timeout=VT)
        r.raise_for_status()
        insts = list((r.json() or {}).get("instances", []))
        if not protocol:
            insts = [i for i in insts if (i.get("protocol") or "") in PROVIDER_OF]
        return insts, None
    except requests.RequestException as e:
        log.warning("vault_list: %r", e)
        return [], "שירות החיבורים אינו זמין"
    except ValueError:
        return [], "שירות החיבורים החזיר תשובה שאינה JSON"


def vault_secret(cid: str) -> dict | None:
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", timeout=VT)
        r.raise_for_status()
        return (r.json() or {}).get("secret") or {}
    except (requests.RequestException, ValueError) as e:
        log.warning("vault secret for %s unavailable: %s", cid, type(e).__name__)
        return None


def vault_add(protocol: str, label: str, secret: dict, account_hint: str = "") -> tuple[dict, int]:
    body = {"protocol": protocol, "label": label, "secret": secret}
    if account_hint:
        body["account_hint"] = account_hint
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances", json=body, timeout=VT)
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": f"שירות החיבורים אינו זמין: {e}"}, 502


def vault_delete(cid: str) -> tuple[dict, int]:
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{cid}", timeout=VT)
        return (r.json() if r.content else {"ok": r.ok}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": f"שירות החיבורים אינו זמין: {e}"}, 502


def resolve(cid: str | None) -> tuple[dict, dict | None, str | None]:
    """(instance, secret, error). With no id, the ACTIVE account; with no accounts at all, the
    synthetic registry account — which needs nothing and is what makes a fresh install work."""
    insts, err = vault_list()
    if err:
        return {}, None, err
    if not insts:
        synthetic = {"id": "domain_registry-local", "protocol": "domain_registry_whois",
                     "label": "רישום (WHOIS)", "status": "ok"}
        return synthetic, {}, None
    if not cid:
        cid = active_id() or insts[0].get("id")
    inst = next((i for i in insts if i.get("id") == cid), None)
    if not inst:
        return {}, None, "לא נמצא חשבון כזה"
    return inst, vault_secret(inst["id"]) or {}, None


# ── probing ──────────────────────────────────────────────────────────────────────────────────────
_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[float, dict]] = {}


def probe_instance(inst: dict, secret: dict, max_age: float = PROBE_TTL) -> dict:
    cid = inst.get("id") or ""
    now = time.time()
    if max_age:
        with _probe_lock:
            hit = _probe_cache.get(cid)
        if hit and now - hit[0] < max_age:
            return {**hit[1], "cached": True}
    provider = PROVIDER_OF.get(inst.get("protocol") or "", "")
    try:
        who = adapter_for(provider, secret).whoami()
        out = {"ok": True, "state": "ok", "provider": provider,
               "login": who.get("login"), "scopes": who.get("scopes"),
               "capabilities": who.get("capabilities") or {},
               "sample": who.get("zones_sample") or who.get("domains_sample") or [],
               "checked_at": int(now)}
    except DomainError as e:
        out = {"ok": False, "state": "needs_action" if e.status in (400, 401, 403) else "error",
               "provider": provider, "reason": e.he_message, "detail": e.detail,
               "checked_at": int(now)}
    except Exception as e:                                   # noqa: BLE001
        log.warning("probe_instance: %r", e)
        out = {"ok": False, "state": "error", "provider": provider,
               "reason": "הבדיקה נכשלה", "checked_at": int(now)}
    with _probe_lock:
        _probe_cache[cid] = (now, out)
    return out


def forget_probe(cid: str | None = None) -> None:
    with _probe_lock:
        _probe_cache.pop(cid, None) if cid else _probe_cache.clear()


def account_row(inst: dict) -> dict:
    provider = PROVIDER_OF.get(inst.get("protocol") or "", "")
    probe = probe_instance(inst, vault_secret(inst["id"]) or {})
    return {"id": inst.get("id"), "label": inst.get("label") or provider,
            "provider": provider, "protocol": inst.get("protocol"),
            "account_hint": inst.get("account_hint") or "", "created_at": inst.get("created_at"),
            **{k: probe.get(k) for k in ("ok", "state", "reason", "detail", "login", "scopes",
                                         "capabilities", "sample", "checked_at", "cached")}}
