"""social-list.accounts — every social account is an INSTANCE in the credential plane.

The same shape as drive, mail, domains and computers (ai/context/platform-service-contract.md §1):
the vault (`connections`) is the one copy of an account; this app keeps no token in its config, its
environment or its volume. An account's PROTOCOL says which platform it is on and which kind of
implementation speaks for it (platforms.by_protocol), so choosing the adapter is a lookup, not a
decision anybody makes twice.

Two kinds of secret, and the difference is the whole security story:

  * `api`     — the platform's own token (a page token, a bot token, a PAT). It is read at call time
                and never leaves this process except toward the platform.
  * `browser` — a POINTER, never a cookie and never a password (browser-session-connection.md §2):
                `{endpoint, token_connection, origin, group, handle}`. The owner logged in once in the
                office's own Chromium; the session lives there.

What this app DOES own (in its volume): which account is the primary one per platform, and the log
of every action it performed on the owner's behalf.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import requests

import platforms
from adapters import adapter_for
from adapters.base import SocialError

log = logging.getLogger("social-list.accounts")

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
STATE_DIR = Path(os.environ.get("APP_STATE_DIR", "/data"))
PRIMARY_PATH = STATE_DIR / "primary.json"
PROBE_TTL = float(os.environ.get("SOCIAL_PROBE_TTL", "300"))
VT = 10

_lock = threading.Lock()


class VaultError(Exception):
    pass


# ── the vault ────────────────────────────────────────────────────────────────────────────────────
def vault_list() -> list[dict]:
    """Every social instance. Raises VaultError when the vault is unreachable: "no accounts" and
    "the vault did not answer" are different states and the screen must be able to say which."""
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances", timeout=VT)
        r.raise_for_status()
        insts = list((r.json() or {}).get("instances", []))
    except requests.RequestException as e:
        raise VaultError("שירות החיבורים אינו זמין") from e
    except ValueError as e:
        raise VaultError("שירות החיבורים החזיר תשובה שאינה JSON") from e
    known = set(platforms.all_protocols())
    return [i for i in insts if (i.get("protocol") or "") in known]


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
        return {"error": "שירות החיבורים אינו זמין"}, 502


def vault_delete(cid: str) -> tuple[dict, int]:
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{cid}", timeout=VT)
        return (r.json() if r.content else {"ok": r.ok}), r.status_code
    except ValueError:
        return {"error": "הוולט החזיר תשובה שאינה JSON"}, 502
    except requests.RequestException as e:
        return {"error": "שירות החיבורים אינו זמין"}, 502


# ── primary account per platform ─────────────────────────────────────────────────────────────────
def primaries() -> dict:
    try:
        return json.loads(PRIMARY_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, ValueError):
        return {}


def set_primary(platform_id: str, cid: str | None) -> dict:
    with _lock:
        cur = primaries()
        if cid:
            cur[platform_id] = cid
        else:
            cur.pop(platform_id, None)
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        PRIMARY_PATH.write_text(json.dumps(cur), encoding="utf-8")
        return cur


# ── resolution ───────────────────────────────────────────────────────────────────────────────────
def resolve(ref: str) -> tuple[dict, dict, dict, str]:
    """An account id — or a platform id, meaning that platform's primary account — to
    (instance, secret, platform, kind). Raises SocialError naming what is missing."""
    insts = vault_list()
    inst = next((i for i in insts if i.get("id") == ref), None)
    if inst is None and platforms.get(ref):
        pid = ref
        cid = primaries().get(pid)
        mine = [i for i in insts if (platforms.by_protocol(i.get("protocol") or "")[0] or {}).get("id") == pid]
        inst = next((i for i in mine if i.get("id") == cid), None) or (mine[0] if mine else None)
        if inst is None:
            name = (platforms.get(pid).get("name") or {}).get("he", pid)
            raise SocialError(f"אין חשבון {name} מחובר", status=404, kind="not_connected",
                              title=f"{name} אינו מחובר", how="חברו חשבון במסך „רשתות חברתיות”.")
    if inst is None:
        raise SocialError("לא נמצא חשבון כזה", status=404, kind="not_found")
    platform, kind = platforms.by_protocol(inst.get("protocol") or "")
    secret = vault_secret(inst["id"])
    if secret is None:
        raise SocialError("לא ניתן לקרוא את פרטי החשבון מהוולט", status=502, kind="vault")
    return inst, secret, platform, kind


def adapter(ref: str, **kw):
    inst, secret, platform, kind = resolve(ref)
    return adapter_for(platform, kind, secret, inst, **kw), inst


# ── probing: is this account actually usable right now? ─────────────────────────────────────────
_probe_lock = threading.Lock()
_probe_cache: dict[str, tuple[float, dict]] = {}


def probe(inst: dict, secret: dict, max_age: float = PROBE_TTL) -> dict:
    cid = inst.get("id") or ""
    now = time.time()
    if max_age:
        with _probe_lock:
            hit = _probe_cache.get(cid)
        if hit and now - hit[0] < max_age:
            return {**hit[1], "cached": True}
    platform, kind = platforms.by_protocol(inst.get("protocol") or "")
    try:
        who = adapter_for(platform, kind, secret, inst).whoami()
        out = {"ok": True, "state": "ok", "handle": who.get("handle"), "name": who.get("name"),
               "url": who.get("url"), "checked_at": int(now)}
    except SocialError as e:
        state = "needs_action" if e.kind in ("needs_owner", "unauthorized", "needs_verification") \
            else ("unsupported" if e.kind == "unsupported" else "error")
        out = {"ok": False, "state": state, "reason": e.he_message, "how": e.how, "url": e.url,
               "checked_at": int(now)}
    except Exception as e:                                   # noqa: BLE001
        log.warning("probe: %r", e)
        out = {"ok": False, "state": "error", "reason": "הבדיקה נכשלה",
               "checked_at": int(now)}
    with _probe_lock:
        _probe_cache[cid] = (now, out)
    return out


def forget_probe(cid: str | None = None) -> None:
    with _probe_lock:
        if cid:
            _probe_cache.pop(cid, None)
        else:
            _probe_cache.clear()


def cached_probe(cid: str) -> dict | None:
    with _probe_lock:
        hit = _probe_cache.get(cid)
    return hit[1] if hit else None


def row(inst: dict, with_probe: bool = False) -> dict:
    platform, kind = platforms.by_protocol(inst.get("protocol") or "")
    p = platform or {}
    out = {"id": inst.get("id"), "label": inst.get("label") or "", "platform": p.get("id"),
           "platform_name": (p.get("name") or {}).get("he"), "kind": kind,
           "account_hint": inst.get("account_hint") or "", "created_at": inst.get("created_at"),
           "primary": primaries().get(p.get("id")) == inst.get("id"), "test": bool(p.get("test"))}
    pr = None
    if with_probe:
        secret = vault_secret(inst["id"]) or {}
        pr = probe(inst, secret)
    else:
        pr = cached_probe(inst.get("id") or "")
    out["probe"] = pr
    return out
