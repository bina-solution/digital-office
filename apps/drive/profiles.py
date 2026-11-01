"""profiles — identities on the PRIVATE drive engine (`drive_local`), and the rings that guard them.

The shape is the cross-app contract in ai/context/app-engine-pattern.md, implemented identically in
mail and chat:

    id · display_name · is_admin · key_hash · status(active|suspended) · instance_id · created_at

Two facts about one credential, deliberately kept in two different places:

  * the KEY itself lives in the connections vault, as the instance's secret — that is what makes a
    private profile an ordinary instance, so `resolve()` can stop special-casing private engines;
  * only its SHA-256 HASH lives here, so this service can authenticate an inbound call without ever
    being able to hand the key back out.

Never both in one place. A profile row is not a credential store.

THE RINGS (checked here, applied by app.py):
    data   any active profile — every drive op, scoped to its own rows BY THE QUERIES
    self   any active profile — read/update itself, rotate its own key
    admin  is_admin only      — create/edit/suspend/delete OTHER profiles

`is_admin` is not "the default profile". Nothing in this file, or any caller of it, may branch on
which profile was created first — the admin flag is the only thing that confers the admin ring.
"""
import hashlib
import re
import secrets

from db import q

# `drive_local-<8hex>` instances are minted by the vault; a profile id is ours and is a slug, because
# it lands in a WHERE clause, in an `account_hint`, and in a URL path segment.
_SLUG = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

STATUS_ACTIVE = "active"
STATUS_SUSPENDED = "suspended"

_SCHEMA_READY = False


def valid_id(pid):
    return bool(pid and _SLUG.match(str(pid)))


def ensure_schema():
    """Declare the profile table. Idempotent, and the ONLY declaration of `drive_profiles`.

    It used to be mirrored in blueprint/fixtures/schema.sql under a "must stay type-for-type
    identical" warning that nothing enforced and that had already stopped being true —
    `display_name` and `key_hash` are NOT NULL here and were nullable there. That mirror is deleted;
    see adapters/local.py's ensure_schema for the full reasoning."""
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return True
    try:
        q("""CREATE TABLE IF NOT EXISTS drive_profiles (
                id           text PRIMARY KEY,
                display_name text NOT NULL,
                is_admin     boolean NOT NULL DEFAULT false,
                key_hash     text NOT NULL,
                status       text NOT NULL DEFAULT 'active',
                instance_id  text UNIQUE,
                created_at   timestamptz NOT NULL DEFAULT now())""")
        # authentication is a lookup BY HASH on every authenticated call — index it
        q("CREATE INDEX IF NOT EXISTS drive_profiles_key_hash_idx ON drive_profiles (key_hash)")
    except Exception as e:
        print("[drive] profiles ensure_schema deferred (will retry):", e, flush=True)
        return False
    _SCHEMA_READY = True
    return True


# ── credentials ──────────────────────────────────────────────────────────────────
def mint_key():
    """A fresh profile credential. 256 bits from `secrets` — this is the only thing standing between
    a caller and another profile's files."""
    return "dk_" + secrets.token_urlsafe(32)


def key_hash(key):
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()


def fingerprint(key):
    """A short, non-reversible tag for a credential — the adapter cache is keyed on it, so a rotated
    key rebuilds the adapter without a restart and without the cache ever holding the key."""
    return key_hash(key)[:16]


def fingerprint_of_hash(h):
    """The same tag, computed from the STORED hash rather than the key, so a listing can show it
    without the service ever having seen the credential again."""
    if not h:
        return None
    return hashlib.sha256(f"fp:{h}".encode("utf-8")).hexdigest()[:16]


# ── rows ─────────────────────────────────────────────────────────────────────────
_COLS = "id, display_name, is_admin, key_hash, status, instance_id, created_at"


def _row(r):
    return {"id": r[0], "display_name": r[1], "is_admin": bool(r[2]), "key_hash": r[3],
            "status": r[4], "instance_id": r[5], "created_at": str(r[6])[:19] if r[6] else None}


def public(p):
    """What a profile looks like over HTTP: never the hash. Built field-by-field rather than by
    popping `key_hash` off, so a field added later cannot leak by omission.

    `key_fp` is a hash OF the hash — the adapter cache is keyed on it, so a rotation must change it
    or a cached adapter keeps serving with the old credential. A digest of a digest tells a caller
    nothing about the key and still changes the instant it rotates. Same field, same meaning, in
    chat and mail.
    """
    if not p:
        return None
    return {"id": p["id"], "display_name": p["display_name"], "is_admin": p["is_admin"],
            "status": p["status"], "instance_id": p.get("instance_id"),
            "key_fp": fingerprint_of_hash(p.get("key_hash")), "created_at": p["created_at"]}


def listing():
    return [_row(r) for r in q(f"SELECT {_COLS} FROM drive_profiles ORDER BY is_admin DESC, id")]


def get(pid):
    rows = q(f"SELECT {_COLS} FROM drive_profiles WHERE id=%s", (pid,))
    return _row(rows[0]) if rows else None


def by_key(key):
    """credential -> profile. The only way an inbound caller acquires an identity.

    Suspended profiles resolve to None: a suspended key must stop working everywhere at once, and
    letting it resolve here would mean every call site had to remember to check.
    """
    if not key:
        return None
    rows = q(f"SELECT {_COLS} FROM drive_profiles WHERE key_hash=%s AND status=%s",
             (key_hash(key), STATUS_ACTIVE))
    return _row(rows[0]) if rows else None


def by_instance(iid):
    """connection id -> profile. The profile row is the authoritative half of the map; the vault's
    `account_hint` is the recovery half (see bootstrap.instance_for)."""
    if not iid:
        return None
    rows = q(f"SELECT {_COLS} FROM drive_profiles WHERE instance_id=%s", (iid,))
    return _row(rows[0]) if rows else None


def set_instance(pid, iid):
    """Record which vault instance carries this profile's credential."""
    q("UPDATE drive_profiles SET instance_id=%s WHERE id=%s", (iid, pid))
    return get(pid)


def admins(active_only=True):
    sql = f"SELECT {_COLS} FROM drive_profiles WHERE is_admin"
    args = ()
    if active_only:
        sql += " AND status=%s"
        args = (STATUS_ACTIVE,)
    return [_row(r) for r in q(sql, args)]


def first_admin():
    """The profile a fresh deployment binds to. Ordered by creation so it is stable, NOT because
    "first" means anything — it is simply the one admin that exists on a new machine."""
    rows = q(f"SELECT {_COLS} FROM drive_profiles WHERE is_admin AND status=%s "
             "ORDER BY created_at, id LIMIT 1", (STATUS_ACTIVE,))
    return _row(rows[0]) if rows else None


# ── mutations ────────────────────────────────────────────────────────────────────
def create(pid, display_name, is_admin=False, key=None):
    """Insert a profile and return (profile, key). The key is returned ONCE, here — it is never
    readable from this service again, because only its hash is stored."""
    key = key or mint_key()
    q("INSERT INTO drive_profiles (id, display_name, is_admin, key_hash, status) "
      "VALUES (%s,%s,%s,%s,%s)",
      (pid, display_name or pid, bool(is_admin), key_hash(key), STATUS_ACTIVE))
    return get(pid), key


def update(pid, display_name=None, is_admin=None, status=None):
    sets, args = [], []
    if display_name is not None:
        sets.append("display_name=%s")
        args.append(display_name)
    if is_admin is not None:
        sets.append("is_admin=%s")
        args.append(bool(is_admin))
    if status is not None:
        sets.append("status=%s")
        args.append(status)
    if sets:
        q(f"UPDATE drive_profiles SET {', '.join(sets)} WHERE id=%s", tuple(args + [pid]))
    return get(pid)


def rotate(pid):
    """Mint a replacement credential for an EXISTING profile. Returns (profile, key).

    Called on an explicit rotate, and by the reconciler when a profile has no vault instance to hold
    its key. NEVER called merely because the service restarted — that is rule 10, and it is what
    makes `bbox run` safe to re-run on a live company.
    """
    key = mint_key()
    q("UPDATE drive_profiles SET key_hash=%s WHERE id=%s", (key_hash(key), pid))
    return get(pid), key


def delete(pid):
    """Remove ACCESS. Deliberately does not touch drive_files: rule 8 — deleting a profile removes
    access, never data. The rows keep their `profile` value, so re-creating the profile under the
    same id restores the view of them rather than resurrecting nothing."""
    q("DELETE FROM drive_profiles WHERE id=%s", (pid,))


# ── ring guards ──────────────────────────────────────────────────────────────────
class ProfileError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


def require_last_admin_survives(pid, *, removing=False, demoting=False, suspending=False):
    """The last admin cannot be removed, demoted or suspended.

    Without this, profile management becomes unreachable: no admin means no one may create an admin,
    and the only way back is a hand-edited database. Checked against ACTIVE admins, because a
    suspended admin cannot administer anything either — treating suspension as harmless is how this
    guard gets bypassed while looking intact.
    """
    if not (removing or demoting or suspending):
        return
    others = [a for a in admins(active_only=True) if a["id"] != pid]
    if others:
        return
    cur = get(pid)
    if not cur or not cur["is_admin"] or cur["status"] != STATUS_ACTIVE:
        return          # it was not the last active admin to begin with
    raise ProfileError("זהו המנהל האחרון — לא ניתן להסיר, לשנות או להשעות אותו", 409)
