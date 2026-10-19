"""connections_client — the drive service's view of the credential plane (secret-base :8990).

Per the platform service contract (§1/§2): connection instances live in secret-base's vault, and
this service only ever holds a BINDING to the one it acts as (/data/active.json). Secrets are
fetched in-network, per-call, and never persisted here — that is the §5 invariant.

WHAT CHANGED, AND WHY IT MATTERS
The local drive used to be a SYNTHETIC instance (`drive_local-local`) with no secret and no vault
row, prepended to every listing. That fake row is gone. Every profile on the private engine — the
one declared `admin` in app.json included — is now a REAL vault instance holding a real credential,
which is what lets resolve() treat private and remote engines identically instead of special-casing
the private one in half a dozen places.

The zero-config guarantee survives unchanged in MEANING: a deployment that has selected nothing acts
as the first admin profile, which the bootstrap reconciler created before the first request. What is
gone is the pretence that this was a connection nobody had to create.
"""
import json
import logging
import os
import tempfile

import requests

import profiles

log = logging.getLogger(__name__)

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990")
PROTOCOL_GLOB = "drive_*"          # this service owns the drive_* protocols only
ACTIVE_PATH = os.environ.get("ACTIVE_PATH", "/data/active.json")
LOCAL_PROTOCOL = "drive_local"

#: The binding is a {scope -> instance id} MAP with exactly one scope today. Stored as a map from
#: day one on purpose (app-engine-pattern §10): when per-user selection arrives, the scope key
#: becomes the user id and nothing else moves. A scalar would need a second migration to get there.
DEFAULT_SCOPE = "deployment"

_TIMEOUT = 10


def vault_instances():
    """(instances, error) for drive_* — the vault's rows.

    Returns the REASON when secret-base could not answer instead of swallowing it. That distinction
    is the whole point: "the vault is down" and "that connection was deleted" both look like an
    empty list, but only the second one is a dangling binding. resolve_active() must be able to say
    which it is, and neither may ever be answered with somebody else's drive (see resolve_active).
    """
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances",
                         params={"protocol": PROTOCOL_GLOB}, timeout=_TIMEOUT)
        r.raise_for_status()
        return list((r.json() or {}).get("instances", [])), None
    except (requests.RequestException, ValueError) as e:
        log.warning("vault_instances: %r", e)
        return [], "שירות החשבונות אינו זמין"


def list_instances():
    """Vault instances for drive_*, annotated with what this service knows about each.

    A secret-base that is down degrades to an EMPTY list rather than failing: the drive must keep
    LISTING when the credential plane is unavailable. Note what this does NOT license — running an
    op somewhere else because the bound account is missing from this list. Listing degrades;
    resolution does not.
    """
    insts, _err = vault_instances()
    return [annotate(i) for i in insts]


def annotate(inst):
    """Add the explicit fields the console and the UI used to derive by parsing the id
    (`/-local$/`, `cid.rsplit("-",1)[0]`). An id is not a data structure."""
    proto = (inst or {}).get("protocol") or ""
    out = dict(inst or {})
    out["engine"] = proto
    out["is_private"] = proto == LOCAL_PROTOCOL
    out["app"] = "drive"
    if proto == LOCAL_PROTOCOL:
        pid = inst.get("account_hint")
        out["profile_id"] = pid
        p = None
        try:
            p = profiles.get(pid) if pid else None
        except Exception:            # the DB is not a dependency of LISTING connections
            p = None
        if p:
            out["is_admin"] = p["is_admin"]
            out["profile_status"] = p["status"]
            out["label"] = p["display_name"] or out.get("label")
        else:
            # an instance whose profile row is gone is unusable — say so in the row rather than
            # letting it look healthy in the bar (instance `status` is written once at creation)
            out["profile_status"] = "missing"
            out["status"] = "needs_action"
            out["reason"] = "הפרופיל שהחיבור הזה מייצג אינו קיים יותר"
    return out


def dangling_instance(cid, reason):
    """A display-only record for a binding that resolves to nothing (§2/§4b state propagation).

    /connections must never report an `active` id that is absent from its own list — the console
    then renders "no account selected" while /readyz says ready, and the two disagree about the
    same fact. So the broken selection is surfaced AS a row, carrying its own reason and a chip
    the UI already knows how to render (`needs_action`), and stays selectable-away-from.
    """
    proto = cid.rsplit("-", 1)[0] if "-" in cid else ""
    return {"id": cid, "protocol": proto if proto in (LOCAL_PROTOCOL, "drive_google_oauth") else "",
            "label": "חיבור שאינו זמין", "account_hint": None, "engine": proto,
            "is_private": proto == LOCAL_PROTOCOL, "app": "drive",
            "status": "needs_action", "reason": reason, "created_at": None}


def get_instance(cid):
    return next((i for i in list_instances() if i.get("id") == cid), None)


def get_secret(cid):
    """{protocol, secret} for a vault instance, or None when secret-base can't answer.

    There is no longer a synthetic id to special-case: EVERY drive connection, private engine
    included, has a secret here. That is what makes `Backend(credential)` uniform.
    """
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/instances/{cid}/secret", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError):
        return None


def update_secret(cid, secret):
    """Write a refreshed secret back to the vault (§1 `PUT /api/instances/<id>/secret`), so a token
    this service renewed is the token the whole estate uses. Returns True when secret-base accepted it.

    MERGE is the endpoint's default and we rely on it: we send the full merged grant anyway, but a
    partial write must never be able to drop the refresh_token. `replace` is deliberately not passed —
    a re-consent creates an instance, it does not patch one.

    Best-effort ON PURPOSE: the refresh already succeeded and the caller holds the fresh token in
    _CACHE, so a vault that is down/older-than-this-route costs us a re-refresh after a restart —
    never a failed op. Hence: log the reason and return False, never raise into the op path.
    """
    if not cid:
        return False
    try:
        r = requests.put(f"{CONNECTIONS_URL}/api/instances/{cid}/secret",
                         json={"secret": secret}, timeout=_TIMEOUT)
        if not r.ok:
            log.warning("connections: token write-back for %s rejected: %s %s",
                        cid, r.status_code, (r.text or "")[:200])
        return r.ok
    except requests.RequestException as e:
        log.warning("connections: token write-back for %s failed: %s: %s", cid, type(e).__name__, e)
        return False


def add_instance(protocol, label, secret, account_hint=None):
    """Proxy an add to secret-base. Returns (payload, status) so the route can pass the
    credential plane's own verdict through untouched."""
    body = {"protocol": protocol, "label": label, "secret": secret}
    if account_hint:
        body["account_hint"] = account_hint
    try:
        r = requests.post(f"{CONNECTIONS_URL}/api/instances", json=body, timeout=_TIMEOUT)
        return (r.json() if r.content else {}), r.status_code
    except ValueError:
        return {"error": "credential plane returned a non-JSON response"}, 502
    except requests.RequestException as e:
        return {"error": f"credential plane unreachable: {e}"}, 502


def delete_instance(cid):
    try:
        r = requests.delete(f"{CONNECTIONS_URL}/api/instances/{cid}", timeout=_TIMEOUT)
        return (r.json() if r.content else {"ok": r.ok}), r.status_code
    except ValueError:
        return {"error": "credential plane returned a non-JSON response"}, 502
    except requests.RequestException as e:
        return {"error": f"credential plane unreachable: {e}"}, 502


# ── the binding: {scope -> instance id} ──────────────────────────────────────────
def _bindings():
    """Read from disk every call: gunicorn runs several workers, so a select() in one worker must be
    visible to the next request in another."""
    try:
        with open(ACTIVE_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (OSError, ValueError):
        return {}
    if not isinstance(d, dict):
        return {}
    b = d.get("bindings")
    return b if isinstance(b, dict) else {}


def binding(scope=DEFAULT_SCOPE):
    return _bindings().get(scope) or None


def active():
    """The bound instance id for the only scope that exists today. Kept as its own name because
    "which account is this drive acting as" is the question every caller is really asking."""
    return binding(DEFAULT_SCOPE)


def select(cid, scope=DEFAULT_SCOPE):
    """Bind a scope to a connection. Written atomically (tmp + replace) so a crashed/raced write can
    never leave a half-written map that would strand the service."""
    d = os.path.dirname(ACTIVE_PATH) or "."
    os.makedirs(d, exist_ok=True)
    b = _bindings()
    b[scope] = cid
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"bindings": b}, f)
        os.replace(tmp, ACTIVE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return cid


def unbind(scope=DEFAULT_SCOPE):
    b = _bindings()
    if b.pop(scope, None) is None:
        return False
    d = os.path.dirname(ACTIVE_PATH) or "."
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"bindings": b}, f)
        os.replace(tmp, ACTIVE_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


def default_instance(instances=None):
    """The instance a deployment that has selected NOTHING acts as: the first admin profile's.

    This is the zero-config guarantee, and it is the ONLY substitution left in this module. It is
    not a fallback for a broken binding — see resolve_active.
    """
    try:
        admin = profiles.first_admin()
    except Exception:
        return None
    if not admin:
        return None
    if instances is None:
        instances, _err = vault_instances()
    return next((i for i in instances
                 if i.get("protocol") == LOCAL_PROTOCOL
                 and i.get("account_hint") == admin["id"]), None)


def resolve_active():
    """(instance, reason) for the next op. `reason` non-None => the binding does not resolve and
    NOTHING may run; the caller must fail, not substitute.

    ⚠ This function used to fall back to the local drive when the pointer named an instance that no
    longer existed, on the theory that a stale pointer should "degrade, not break the drive". That
    was the worst defect in the estate (2026-07-17): the pointer said Google, /readyz answered
    `200 {"ready":true,"connection_id":"drive_local-local"}`, n8n gates on /readyz alone — and so
    every drive op wrote the owner's real business documents to a local disk he was never looking
    at, green the whole way. A selection that cannot be honoured must FAIL LOUDLY; the built-in
    drive is a legitimate answer to "nothing is selected", never to "the selected account is
    missing".

    An UNSET binding still means the default profile — that is the zero-config guarantee (§2), and
    it is the only substitution left here. The one thing that changed is what "the default" IS: a
    real instance carrying a real credential, not a synthesised row.
    """
    cid = active()
    insts, err = vault_instances()
    if not cid:
        if err:
            return None, f"לא ניתן לקבוע את חשבון ברירת המחדל: {err}"
        inst = default_instance(insts)
        if inst:
            return annotate(inst), None
        return None, "הדרייב עדיין מאתחל — לא נוצר עדיין אף פרופיל. נסה שוב בעוד רגע."
    inst = next((i for i in insts if i.get("id") == cid), None)
    if inst:
        return annotate(inst), None
    if err:
        # Unreachable vault: we cannot prove the selection is gone, and we may not assume it is
        # fine either. Both roads lead to "not ready" — only the wording differs.
        return None, f"לא ניתן לאמת את החשבון שנבחר ({cid}): {err}"
    return None, (f"החשבון שנבחר ({cid}) אינו קיים יותר. בחר חשבון אחר או חבר אותו מחדש.")
