"""bootstrap — turn the profiles DECLARED in app.json into profiles that actually exist.

Runs at app start, IN-PROCESS, with direct database access. That is not an implementation detail:
it is the one path exempt from profile authentication, and the exemption is what resolves the
chicken-and-egg the rest of the design would otherwise have — you need an admin key to manage
profiles, and you need this to get one.

Idempotent and ledger-backed. Per declared profile:

    missing                       create row, mint credential, store hash, create vault instance
    profile + instance exist      leave alone — NEVER re-mint (rule 10). Re-minting on boot would
                                  invalidate every stored client key on every `bbox run`
    profile exists, no instance   rotate and log it: the old key was never handed to anyone (the
                                  instance that would have carried it does not exist)
    ours, no longer declared      remove the profile and its instance. The FILES stay (rule 8)
    exists but never ours         leave alone — a redeploy must never delete an operator's profile
    connections unreachable       keep the profile, retry the instance on a later pass, never fail
                                  the boot, never mint twice

The ledger (`/data/profile-ledger.json`, on the app's own volume) answers exactly one question:
"did the app.json reconciler create this profile?" It is deliberately NOT a credential store and
deliberately NOT the profile→instance map — `drive_profiles.instance_id` is that map, the same field
chat and mail keep on their profile rows.
"""
import json
import os
import tempfile
import time

import connections_client as cx
import profiles
from db import advisory_lock

APP_JSON = os.environ.get("DRIVE_APP_JSON", os.path.join(os.path.dirname(__file__), "app.json"))
LEDGER_PATH = os.environ.get("DRIVE_LEDGER_PATH", "/data/profile-ledger.json")
LOCAL_PROTOCOL = "drive_local"

# one arbitrary-but-fixed advisory-lock key for "the drive profile reconciler"
_LOCK_KEY = 0x4452_5645          # 'DRVE'

_DONE = False                    # reconciled successfully at least once in this worker


# ── the declaration ──────────────────────────────────────────────────────────────
def declared_profiles():
    """`engine.profiles[]` from app.json — the ONLY place profiles are declared.

    DRIVE_ENGINE_PROFILES overrides it with the same JSON array, which exists so a test can declare
    a third profile without rebuilding the image. It is an override of the declaration, never a
    second source of truth: when it is unset (always, in a real deployment) app.json is read.
    """
    raw = os.environ.get("DRIVE_ENGINE_PROFILES", "").strip()
    if raw:
        try:
            decl = json.loads(raw)
        except ValueError as e:
            print("[drive] DRIVE_ENGINE_PROFILES is not valid JSON, ignoring:", e, flush=True)
            decl = []
    else:
        try:
            with open(APP_JSON, encoding="utf-8") as f:
                decl = ((json.load(f).get("engine") or {}).get("profiles")) or []
        except (OSError, ValueError) as e:
            print("[drive] could not read the engine declaration from", APP_JSON, "-", e, flush=True)
            return []
    out = []
    for p in decl if isinstance(decl, list) else []:
        pid = str((p or {}).get("id") or "").strip()
        if not profiles.valid_id(pid):
            print(f"[drive] skipping declared profile with invalid id {pid!r}", flush=True)
            continue
        out.append({"id": pid,
                    "display_name": str(p.get("display_name") or pid),
                    "is_admin": bool(p.get("admin") or p.get("is_admin"))})
    return out


# ── the ledger ───────────────────────────────────────────────────────────────────
def _ledger_read():
    try:
        with open(LEDGER_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ledger_write(d):
    p = os.path.dirname(LEDGER_PATH) or "."
    os.makedirs(p, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=p, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        os.replace(tmp, LEDGER_PATH)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def ours(pid):
    return pid in (_ledger_read().get("declared") or {})


def _mark_ours(pid):
    d = _ledger_read()
    d.setdefault("declared", {})[pid] = {"created_at": int(time.time())}
    _ledger_write(d)


def unmark(pid):
    d = _ledger_read()
    if (d.get("declared") or {}).pop(pid, None) is not None:
        _ledger_write(d)


# ── profile ↔ instance ───────────────────────────────────────────────────────────
def instance_for(pid, instances=None):
    """The vault instance that carries this profile's credential.

    Two halves, in this order, and the order is the point:

      1. `drive_profiles.instance_id` — the authoritative map, the same field chat and mail keep on
         their profile rows. One lookup, no vault round-trip, and it survives a connections outage.
      2. the vault's `account_hint` — the RECOVERY path, used only when the row has no id or names
         an instance that no longer exists. This is what lets a profile find its instance again
         after the row was restored from a fixture, or the id was lost mid-provision.

    A row whose `instance_id` points at nothing is repaired here rather than believed: an id that
    resolves to no instance is not a map, it is a memory of one.
    """
    if instances is None:
        instances, _err = cx.vault_instances()
    row = profiles.get(pid)
    if row and row.get("instance_id"):
        hit = next((i for i in instances if i.get("id") == row["instance_id"]), None)
        if hit:
            return hit
    hint = next((i for i in instances
                 if i.get("protocol") == LOCAL_PROTOCOL and i.get("account_hint") == pid), None)
    if hint and row and row.get("instance_id") != hint["id"]:
        profiles.set_instance(pid, hint["id"])
    return hint


def provision_profile(pid, display_name, is_admin=False):
    """Create a profile AND its vault instance in ONE operation (rule 7).

    Used by the reconciler and by `POST /engine/profiles` alike, so a profile born from app.json and
    a profile born in the UI are the same kind of thing afterwards — including appearing in the
    connection bar without a second, decision-free "now connect it" step.

    Returns (profile, key, instance_id, error). `error` non-None with a profile means the identity
    exists but the vault could not be told: a later reconcile pass completes it.
    """
    profile, key = profiles.create(pid, display_name, is_admin)
    iid, err = mint_instance(pid, display_name, key)
    return profile, key, iid, err


def mint_instance(pid, display_name, key):
    """Create the vault instance that carries this profile's key, and record the id on the row.

    The secret is `{api_key, profile_id}` — the same two fields chat stores — so a client that holds
    a credential also knows which identity it is, without asking.
    """
    body, status = cx.add_instance(LOCAL_PROTOCOL, display_name or pid,
                                   {"api_key": key, "profile_id": pid}, account_hint=pid)
    if 200 <= status < 300 and (body or {}).get("id"):
        profiles.set_instance(pid, body["id"])
        return body["id"], None
    return None, (body or {}).get("error") or f"connections returned HTTP {status}"


# ── the reconciler ───────────────────────────────────────────────────────────────
def reconcile(force=False, report=False):
    """One idempotent pass. Returns True when the declaration is fully realised.

    With `report=True` it returns the pass REPORT instead — `{created, repaired, removed, errors,
    complete}`. That is what `POST /engine/profiles/reconcile` answers with, and it exists for the
    same reason chat's and mail's do: idempotence is a claim, and a claim you cannot exercise on a
    running deployment is a claim nobody checks. Run it twice and the second report's `created`,
    `repaired` and `removed` are empty — that emptiness IS the property that makes `bbox run` safe
    to point at a live company.

    Never raises into the boot path: a vault outage must cost a retry, not the service.
    """
    global _DONE
    rep = {"created": [], "repaired": [], "removed": [], "errors": [], "complete": False}
    if _DONE and not force:
        rep["complete"] = True
        return rep if report else True
    if not profiles.ensure_schema():
        rep["errors"].append("the profile table is not available yet")
        return rep if report else False
    declared = declared_profiles()
    if not declared:
        # nothing declared is a legitimate state (an app.json without an engine block); there is
        # simply nothing to reconcile. Do NOT invent a profile here — app.json is the only source.
        _DONE = True
        rep["complete"] = True
        return rep if report else True

    with advisory_lock(_LOCK_KEY) as got:
        if not got:
            # another worker is doing it; this one re-arms on the next pass
            rep["errors"].append("another worker holds the reconcile lock")
            return rep if report else False
        try:
            _pass(declared, rep)
        except Exception as e:      # a reconciler that crashes a worker is worse than a late profile
            print("[drive] profile reconcile failed (will retry):", e, flush=True)
            rep["errors"].append(str(e))
            return rep if report else False
    if rep["complete"]:
        _DONE = True
    return rep if report else rep["complete"]


def _pass(declared, rep):
    instances, vault_err = cx.vault_instances()
    if vault_err:
        instances = []
        rep["errors"].append(f"connections unreachable: {vault_err}")
    complete = True

    declared_ids = {d["id"] for d in declared}
    existing = {p["id"]: p for p in profiles.listing()}

    for d in declared:
        pid, name, is_admin = d["id"], d["display_name"], d["is_admin"]
        row = existing.get(pid)
        inst = None if vault_err else instance_for(pid, instances)

        if row and inst:
            # THE COMMON CASE, and the one rule 10 is about: both halves exist, so nothing is
            # minted. Only the declarative, non-credential fields are kept in step.
            if row["display_name"] != name or row["is_admin"] != is_admin:
                profiles.update(pid, display_name=name, is_admin=is_admin)
            continue

        if row and vault_err:
            # We cannot see the vault, so we cannot know whether the instance is missing. Assuming
            # it is would rotate a perfectly good key on every restart during an outage.
            complete = False
            continue

        if row and not inst:
            if not ours(pid):
                print(f"[drive] profile {pid!r} has no vault instance but was not created by the "
                      "reconciler — leaving it alone", flush=True)
                complete = False
                continue
            # Ours, and its credential has nowhere to live. Rotate and SAY SO: the previous key was
            # never handed to a client (the instance that would have carried it does not exist).
            _profile, key = profiles.rotate(pid)
            iid, err = mint_instance(pid, name, key)
            if err:
                print(f"[drive] profile {pid!r}: instance not created ({err}); retrying later",
                      flush=True)
                rep["errors"].append(f"{pid}: {err}")
                complete = False
            else:
                print(f"[drive] profile {pid!r}: credential rotated into a new instance {iid}",
                      flush=True)
                rep["repaired"].append(pid)
            continue

        # No row at all → create both halves.
        _profile, key, iid, err = provision_profile(pid, name, is_admin)
        _mark_ours(pid)
        rep["created"].append(pid)
        if err:
            print(f"[drive] profile {pid!r} created; instance deferred ({err})", flush=True)
            rep["errors"].append(f"{pid}: {err}")
            complete = False
        else:
            print(f"[drive] profile {pid!r} created with instance {iid}", flush=True)

    # ours, no longer declared → remove ACCESS. The files keep their `profile` value (rule 8).
    if not vault_err:
        for pid in list(existing):
            if pid in declared_ids or not ours(pid):
                continue
            inst = instance_for(pid, instances)
            if inst:
                cx.delete_instance(inst["id"])
            profiles.delete(pid)
            unmark(pid)
            rep["removed"].append(pid)
            print(f"[drive] profile {pid!r} is no longer declared — access removed, files kept",
                  flush=True)

    _ensure_binding()
    rep["complete"] = complete
    return complete


def _ensure_binding():
    """A fresh deployment must come up bound to something real.

    Only ever sets an UNSET binding. An operator who switched the connection bar to another profile
    (or to a Google account) must not find it switched back by a restart — that would be the same
    class of defect as the 2026-07-17 silent substitution, only slower.
    """
    if cx.binding():
        return
    admin = profiles.first_admin()
    if not admin:
        return
    inst = instance_for(admin["id"])
    if inst:
        cx.select(inst["id"])
        print(f"[drive] bound to {inst['id']} (profile {admin['id']!r})", flush=True)
