"""adapters — one interface, one adapter per protocol; ops run as the BOUND PROFILE.

The service holds a BINDING (connections_client.binding) and nothing else. `resolve()` turns that
binding — or a per-call `profile_id`/`connection_id` override — into the adapter that will actually
do the work, so "which account is this working on?" has exactly one answer and it is the same one
/readyz reports.

THE TWO-TIER CAPABILITY CONTRACT (taken from chat's adapters/index.js, deliberately rather than by
coincidence):

    CANONICAL_OPS   every adapter must answer these. They are the §3 automation surface.
    PROTOCOL_OPS    only some engines have them. Advertised separately so a caller can tell
                    "this service cannot do that" from "this connection cannot do that" BEFORE
                    trying.

Capability is derived by ASKING THE LIVE OBJECT (`ops_for`), never from a hand-kept list, so an
adapter that loses a method stops advertising it instead of advertising a 500. This replaces the
`hasattr(...)` + `except TypeError` sniffing that used to be scattered through app.py — sniffing
tells the SERVER what happened after the fact; the UI needed to know beforehand.

The interface every adapter implements (canonical, provider-agnostic):
    probe()                          -> None when usable, else a human reason
    folders()                        -> [{id, name, parent, count, last}]
    create_folder(name, parent='')   -> {id, name, parent}
    files(folder, trashed=False)     -> [item]
    search(term)                     -> [item]
    upload(folder, name, mime, data) -> {id, name}
    rename(id, name) · move(ids, to) -> int · trash(ids, restore=False) -> int · delete(ids) -> int
    content(id, range_header)        -> (status, headers, byte-iterator)
    item = {id, name, folder, size, mime, created, link, owner, owner_id}
"""
import time

import connections_client as cx
import profiles

from .google import GoogleAuthError, GoogleDriveAdapter
from .google_sa import GoogleServiceAccountAdapter
from .local import LocalAdapter
from .opsupport import AdapterError

BY_PROTOCOL = {
    LocalAdapter.protocol: LocalAdapter,
    GoogleDriveAdapter.protocol: GoogleDriveAdapter,
    GoogleServiceAccountAdapter.protocol: GoogleServiceAccountAdapter,
}

PRIVATE_PROTOCOLS = {LocalAdapter.protocol}

__all__ = ["AdapterError", "GoogleAuthError", "GoogleDriveAdapter", "GoogleServiceAccountAdapter",
           "LocalAdapter", "BY_PROTOCOL", "CANONICAL_OPS", "PROTOCOL_OPS", "PRIVATE_PROTOCOLS",
           "for_instance", "ops_for", "resolve", "resolve_active", "invalidate"]

# The §3 op names, mapped to the adapter method that answers each. This dict IS the automation op
# surface: /manifest advertises its keys and the op routes dispatch through it, so the two cannot
# drift (before this, /manifest listed seven ops the service did not implement at all).
CANONICAL_OPS = {
    "list": "op_list",
    "download": "op_download",
    "upload": "op_upload",
    "move": "op_move",
    "update": "op_update",
    "delete": "op_delete",
    "createFromText": "op_create_from_text",
}

#: Ops only SOME engines implement. Absence of the method IS the answer "unsupported" — never a stub
#: that fails at call time, which is a lie the UI cannot see.
PROTOCOL_OPS = {
    "star": "star",          # a flag on the index; Google has its own starred bit but not this one
    "storage": "storage",    # bytes used. Supabase has no per-bucket quota; Google reports its own
    "touch": "touch",        # stamp "opened" — what makes Recent mean recently LOOKED AT
    "views": "views",        # the system views this engine can answer (recent/starred/shared)
}


def ops_for(adapter):
    """The ops this adapter actually answers, by introspection. Two lists, because "the service
    cannot" and "this account cannot" are different sentences to put in front of a user."""
    has = lambda m: callable(getattr(adapter, m, None))  # noqa: E731
    return {
        "ops": [k for k, m in CANONICAL_OPS.items() if has(m)],
        "optional_ops": [k for k, m in PROTOCOL_OPS.items() if has(m)],
    }


def views_for(adapter):
    """Which system views this adapter can answer. `views` is itself a PROTOCOL op, so an adapter
    that does not have it answers none — and the UI hides the rail entries rather than offering
    tabs that silently fall back to the folder listing."""
    fn = getattr(adapter, "views", None)
    return list(fn()) if callable(fn) else []


# ── secret + adapter caches ──────────────────────────────────────────────────────
# A secret lookup is an HTTP call to the vault and ops run often, so resolution is cached briefly.
# The adapter cache is keyed by (connection id, CREDENTIAL FINGERPRINT), never by id alone: a
# rotated key keeps its connection id, so an id-keyed cache would keep serving an adapter built on
# the dead credential until the process restarted. Rotation invalidates by construction here.
_SECRET_TTL = 30
_secret_cache = {}      # cid -> (expires_at, secret dict)
_adapter_cache = {}     # (cid, fingerprint) -> (expires_at, adapter)


def invalidate(cid=None):
    """Drop cached credentials/adapters. Called after a rotate so the next request rebuilds."""
    if cid is None:
        _secret_cache.clear()
        _adapter_cache.clear()
        return
    _secret_cache.pop(cid, None)
    for k in [k for k in _adapter_cache if k[0] == cid]:
        _adapter_cache.pop(k, None)


def _secret(cid):
    now = time.time()
    hit = _secret_cache.get(cid)
    if hit and hit[0] > now:
        return hit[1]
    got = cx.get_secret(cid)
    if got is None:
        # Unreachable vault with nothing cached. NOT an empty secret — an adapter built on "{}"
        # would be an adapter with no identity, and this file's whole contract is that there is no
        # such thing.
        raise AdapterError("שירות החשבונות אינו זמין — לא ניתן לקרוא את מפתח הפרופיל", 503)
    sec = got.get("secret") or {}
    _secret_cache[cid] = (now + _SECRET_TTL, sec)
    return sec


def for_instance(inst):
    """Build (or reuse) the adapter for one instance. Private engines are constructed FROM THEIR
    CREDENTIAL, exactly like remote ones — that symmetry is the whole point of giving a private
    profile a key."""
    inst = inst or {}
    proto = inst.get("protocol")
    cls = BY_PROTOCOL.get(proto)
    if not cls:
        raise AdapterError(f"no adapter for protocol {proto!r}", 501)
    if proto not in PRIVATE_PROTOCOLS:
        # remote adapters fetch their own grant lazily and keep their own token cache
        return cls(inst)
    cid = inst.get("id")
    sec = _secret(cid)
    fp = profiles.fingerprint(sec.get("api_key"))
    now = time.time()
    hit = _adapter_cache.get((cid, fp))
    if hit and hit[0] > now:
        return hit[1]
    ad = cls(inst, secret=sec)
    _adapter_cache[(cid, fp)] = (now + _SECRET_TTL, ad)
    return ad


def resolve(profile_id=None, connection_id=None):
    """(instance, adapter) — THE single choke point. /readyz uses it too, so health and ops agree
    by construction rather than by convention.

    Precedence: explicit argument > binding > (the default profile, only when NOTHING is bound).

    A binding that names a missing instance RAISES: an op must fail rather than run against a
    different account than the one selected (see connections_client.resolve_active, and the
    2026-07-17 incident it is named after). That rule is not weakened by profiles — it is the
    reason profiles could be added at all.
    """
    if profile_id and not connection_id:
        inst = _instance_for_profile(profile_id)
        if not inst:
            raise AdapterError(f"unknown profile {profile_id!r}", 404)
    elif connection_id:
        inst = cx.get_instance(connection_id)
        if not inst:
            raise AdapterError(f"unknown connection {connection_id!r}", 404)
    else:
        inst, reason = cx.resolve_active()
        if reason:
            raise AdapterError(reason, 503)
    return inst, for_instance(inst)


def _instance_for_profile(pid):
    """The instance carrying this profile's credential. The profile row is the authoritative map
    (`drive_profiles.instance_id`); `account_hint` is the recovery path when the row has no id yet.
    Both are checked against the LIVE instance list, so a stale id resolves to nothing rather than
    to a connection that no longer exists."""
    live = cx.list_instances()
    row = profiles.get(pid) or {}
    if row.get("instance_id"):
        hit = next((i for i in live if i.get("id") == row["instance_id"]), None)
        if hit:
            return hit
    return next((i for i in live
                 if i.get("protocol") in PRIVATE_PROTOCOLS and i.get("account_hint") == pid), None)


def resolve_active(connection_id=None):
    """Back-compatible name for `resolve`. Kept because every op route and /readyz calls it, and
    because "the active connection" is still the question being asked."""
    return resolve(connection_id=connection_id)
