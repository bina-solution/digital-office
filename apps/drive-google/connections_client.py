"""connections_client — this engine's view of the credential plane (connections :8990).

Every account of this engine is a vault INSTANCE under one of its protocols (a Google account signed in
with Google, `drive_google_oauth`; a service account, `drive_google_service_account`). The
engine reads an instance's secret per call and never keeps it on disk; it adds and removes only its own
protocols' instances. Which instance the office's agents use by default (the BINDING) is the generic
«קבצים»'s, never an engine's (apps/drive/ENGINES.md).
"""
import logging
import os
import time

import requests

from opsupport import AdapterError

log = logging.getLogger(__name__)

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990")
#: the vault protocols this engine serves — every drive engine's protocols are `drive_*`
PROTOCOLS = ("drive_google_oauth", "drive_google_service_account")
_TIMEOUT = 10
_INSTANCE_TTL = 30
_inst_cache = {"at": 0.0, "rows": None}


def vault_instances():
    """(instances, error) of this engine's protocols. The REASON is returned when the vault could not
    answer: "the vault is down" and "that account was removed" both look like an empty list."""
    out = []
    try:
        for proto in PROTOCOLS:
            r = requests.get(f"{CONNECTIONS_URL}/api/instances", params={"protocol": proto}, timeout=_TIMEOUT)
            r.raise_for_status()
            out += [i for i in (r.json() or {}).get("instances", []) if i.get("protocol") == proto]
    except (requests.RequestException, ValueError) as e:
        log.warning("vault_instances: %r", e)
        return [], "שירות החשבונות אינו זמין"
    _inst_cache.update(at=time.time(), rows=out)
    return out, None


def get_instance(cid):
    """One of this engine's instances by id (a 30-second view of the vault: every op names one). None
    means the vault says there is no such account; a vault that cannot answer is a 503 that says so —
    never «unknown account», which a caller would take as gone for good."""
    rows = _inst_cache["rows"]
    if rows is None or time.time() - _inst_cache["at"] > _INSTANCE_TTL or not any(i.get("id") == cid for i in rows):
        fresh, err = vault_instances()
        if err:
            hit = next((i for i in (rows or []) if i.get("id") == cid), None)
            if hit:
                return hit                       # the last view of it, while the vault is away
            raise AdapterError(f"{err} — לא ניתן לאמת את החשבון {cid}", 503)
        rows = fresh
    return next((i for i in rows if i.get("id") == cid), None)


def forget():
    _inst_cache.update(at=0.0, rows=None)


def get_secret(cid):
    """{protocol, secret} for a vault instance, or None when the vault cannot answer."""
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def update_secret(cid, secret):
    """Write a renewed secret back (MERGE, the endpoint's default): best-effort, never raised into an op."""
    if not cid:
        return False
    try:
        r = requests.put(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", json={"secret": secret}, timeout=_TIMEOUT)
        if not r.ok:
            log.warning("connections: secret write-back for %s rejected: %s", cid, r.status_code)
        return r.ok
    except requests.RequestException as e:
        log.warning("connections: secret write-back for %s failed: %s", cid, type(e).__name__)
        return False


def add_instance(protocol, label, secret, account_hint=None):
    """(payload, status) — the credential plane's own verdict, passed through."""
    if protocol not in PROTOCOLS:
        return {"error": f"this engine does not serve {protocol!r}"}, 400
    body = {"protocol": protocol, "label": label, "secret": secret}
    if account_hint:
        body["account_hint"] = account_hint
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances", json=body, timeout=_TIMEOUT)
        forget()
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "credential plane returned a non-JSON response"}, 502
    except requests.RequestException as e:
        return {"error": f"credential plane unreachable: {type(e).__name__}"}, 502


def delete_instance(cid):
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{cid}", timeout=_TIMEOUT)
        forget()
        return (r.json() if r.content else {"ok": r.ok}), r.status_code
    except ValueError:
        return {"error": "credential plane returned a non-JSON response"}, 502
    except requests.RequestException as e:
        return {"error": f"credential plane unreachable: {type(e).__name__}"}, 502
