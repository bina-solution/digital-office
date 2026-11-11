"""connections_client — «קבצים»'s view of the credential plane (secret-base :8990).

SINCE THE SPLIT (DGO-1500, apps/drive/ENGINES.md): the vault's `drive_*` rows are still the one list of
the office's drives, and the BINDING is still kept here; what a row MEANS (a profile's name, whether it
can work, which one is the office's default) is said by the engine that serves its protocol
(engines.accounts / engines.annotate). Nothing here reads the office storage's database any more.

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
import time

import requests

import engines

log = logging.getLogger(__name__)

CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990")
PROTOCOL_GLOB = "drive_*"          # every drive engine's protocols are drive_* (engines.py)
ACTIVE_PATH = os.environ.get("ACTIVE_PATH", "/data/active.json")

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
    return engines.accounts(insts)


def annotate(inst):
    """The explicit fields the console and the UI used to derive by parsing the id (`/-local$/`,
    `cid.rsplit("-",1)[0]`) — said from the engines' own word on their protocols (engines.annotate).
    The full account (a profile's name, a row that cannot work) is list_instances'."""
    return engines.annotate(inst)


def dangling_instance(cid, reason):
    """A display-only record for a binding that resolves to nothing (§2/§4b state propagation).

    /connections must never report an `active` id that is absent from its own list — the console
    then renders "no account selected" while /readyz says ready, and the two disagree about the
    same fact. So the broken selection is surfaced AS a row, carrying its own reason and a chip
    the UI already knows how to render (`needs_action`), and stays selectable-away-from.
    """
    proto = cid.rsplit("-", 1)[0] if "-" in cid else ""
    known = proto in engines.protocols()
    return {"id": cid, "protocol": proto if known else "",
            "label": "חיבור שאינו זמין", "account_hint": None, "engine": proto,
            "is_private": known and proto in engines.private_protocols(), "app": "drive",
            "status": "needs_action", "reason": reason, "created_at": None}


def get_instance(cid):
    """One vault row, annotated lightly — what every op resolves (no engine is asked here). None means
    the vault says there is no such drive; a vault that cannot answer is a 503 that says so."""
    insts, err = vault_instances()
    if err:
        raise engines.AdapterError(f"{err} — לא ניתן לאמת את הכונן {cid}", 503)
    hit = next((i for i in insts if i.get("id") == cid), None)
    return annotate(hit) if hit else None


# No secret is read here: an account's credential is read by its own engine, per call (DGO-1500).
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
    not a fallback for a broken binding — see resolve_active. Which profile is the first admin is the
    office storage's engine's word: it marks that row `default` (engines.accounts). Asked at most every
    30 seconds — an office that never chose is asked this on every request.
    """
    now = time.time()
    if _default["at"] > now - 30 and instances is None and _default["row"]:
        return _default["row"]
    if instances is None:
        instances, _err = vault_instances()
    private = set(engines.private_protocols())
    rows = engines.accounts([i for i in instances if i.get("protocol") in private]) if private else []
    hit = next((r for r in rows if r.get("default")), None)
    if hit:                       # «none» is never kept: an engine that comes back is believed at once
        _default.update(at=now, row=hit)
    return hit


_default = {"at": 0.0, "row": None}


def forget_default():
    _default.update(at=0.0, row=None)


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
        inst = default_instance()
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
