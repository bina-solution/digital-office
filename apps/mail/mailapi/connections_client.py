"""Connection (account) management for the mail service — shared by app.py and local_app.py.

Contract: ai/context/platform-service-contract.md §1-§2. This module owns the two things a
platform service must know about connections and NOTHING else:

  * the ACTIVE pointer  — which connection ops should use; persisted in /data/active.json so a
    restart keeps the operator's choice (the container is the owner of this state, not n8n).
  * secret-base lookups — instances live in the vault at connections:8990; this service asks for
    them by protocol and fetches a secret only when it actually needs to open a connection.

Invariant (§5): credentials never cross into n8n. They travel connections -> this service only,
over the internal network, and are never echoed back out of /connections (the list endpoint is
secret-free by construction — secret-base does not return secrets there).

stdlib only (urllib): the image has flask + imapclient and nothing else, and a fat HTTP client
is not worth a new dependency for four small in-network calls.
"""
import os
import json
import logging
import urllib.request
import urllib.error
import threading

log = logging.getLogger(__name__)

# Where secret-base lives. Env-overridable so the same image runs in compose (service DNS) and in
# a local/CI harness that port-forwards it.
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")

# The active pointer is a file, not an env var: it changes at RUNTIME (the console selects an
# account) and must survive a restart. /data is the service's volume — same one local mode already
# uses for its per-profile label registries (/data/labels/<connection_id>.json).
ACTIVE_PATH = os.environ.get("ACTIVE_CONNECTION_PATH", "/data/active.json")

# This service handles every mail_* protocol; the list endpoint filters secret-base by this glob so
# drive instances never show up in the mail console.
PROTOCOL_GLOB = "mail_*"
PROTOCOLS = ["mail_imap_local", "mail_imap_app_password", "mail_gmail_oauth"]

# The private engine. A profile ON it is an ORDINARY instance now — `mail_imap_local-<8hex>`, minted
# by profiles.py, carrying {username, password} in the vault exactly like a Gmail app-password
# account. There is no synthetic row any more.
#
# What used to be here, and why it had to go: `LOCAL_ID = "mail_imap_local-local"` was a fabricated
# instance with no vault row and no secret, whose credentials were the LOCALMAIL_* env — i.e. a
# property of the PROCESS rather than of the profile. It forced a special case in every function in
# this module (list, get_secret, put_secret, default_id, delete) and in the UI, and it made a second
# `mail_imap_local` instance meaningless: the vault held the operator's credentials, `_build`
# discarded them, and the SAME mailbox answered. Listed, selectable, and silently wrong.
LOCAL_PROTOCOL = "mail_imap_local"

# The ONE synthetic instance that remains: the account configured the old way, in env
# (GMAIL_IMAP_USER/APP_PW).
# It exists because GMAIL_IMAP_MODE=gmail must keep working with no connection selected (back-compat),
# and the effective active id must always be an id the console can SEE and re-select. Like the local
# one it has no vault row — its "secret" is the process env.
ENV_PROTOCOL = "mail_imap_app_password"
ENV_ID = "mail_imap_app_password-env"


# .env.ex SHIPS this file's Gmail block filled in with an example password, and an example is not a
# configuration. Same markers, same lesson as the placeholder guard in
# platform-base/connections/app.py: a string is not a secret.
_PLACEHOLDER_MARKERS = ("your-", "your_", "change_me", "changeme", "replace-me",
                        "example", "xxxx", "todo", "<", "placeholder")


def _env_user():
    return os.environ.get("GMAIL_IMAP_USER", "").strip()


def _env_pw():
    return os.environ.get("GMAIL_IMAP_APP_PW", "").strip()


def env_configured():
    """Does this deployment REALLY have an env-configured Gmail account?

    A username with no password is not an account, and neither is `your-gmail-app-password` — the
    literal value `.env.ex` ships. Both used to synthesize a connection reporting `status: "ok"`,
    which is a claim about something nobody ever set up. The cost was not cosmetic: the pointer
    could select it, every IMAP login answered AUTHENTICATIONFAILED, and /healthz + /readyz failed
    forever — mailapi AND mailview red on a deployment whose own mailbox worked perfectly. That is
    the DEFAULT state of every company that does not use Gmail, which is most of them.

    So an unconfigured Gmail does not exist here. Not "exists and is unhealthy" — a connection the
    operator never made must not be listed, must not be selectable, and must not be what health is
    judged against."""
    u, p = _env_user(), _env_pw()
    if not u or not p:
        return False
    low = p.lower()
    return not any(m in low for m in _PLACEHOLDER_MARKERS)


def env_instance():
    """The synthetic env instance, or None when this deployment has no env-configured Gmail account
    (local-only installs, and any install after the console takes over account management)."""
    if not env_configured():
        return None
    return {"id": ENV_ID, "protocol": ENV_PROTOCOL, "label": "Gmail (env-configured)",
            "account_hint": _env_user(), "status": "ok"}


def _admin_profile_id():
    """The first declared admin profile's instance id, or None while the engine reconciler has not
    finished a pass. Imported lazily: profiles.py needs this module, and a module-level import here
    would close the cycle."""
    try:
        import profiles
        return profiles.default_instance_id()
    except Exception:                                     # noqa: BLE001
        return None


def default_id():
    """The connection to use when NOTHING is selected — GMAIL_IMAP_MODE as the bootstrap default
    (CI sets it to local). Selection wins over this; see adapters.resolve_active().

    `None` is now a possible answer, and it is the honest one: before the engine reconciler has
    created the admin profile there IS no local account, and the previous code's answer — the
    synthetic id — was a claim that one existed. resolve_active turns a None into a 503 naming the
    reason, which is what a deployment that has not finished provisioning should report."""
    if os.environ.get("GMAIL_IMAP_MODE", "gmail") == "local":
        return _admin_profile_id()
    return ENV_ID if env_configured() else _admin_profile_id()

_HTTP_TIMEOUT = float(os.environ.get("CONNECTIONS_TIMEOUT_S", "8"))

# Writes to the pointer file are serialized: gunicorn runs threaded (--threads 12), so two console
# clicks could otherwise interleave a read-modify-write.
_active_lock = threading.Lock()


class ConnectionsError(Exception):
    """secret-base was unreachable or returned a non-2xx. Callers that can degrade (list) swallow
    this; callers that cannot (add/remove/secret fetch) surface it as a 502."""

    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


def _http(method, path, body=None):
    """One in-network JSON call to secret-base. Returns the decoded body ({} when empty)."""
    url = CONNECTIONS_URL + path
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as r:
            raw = r.read()
        return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        # Pass secret-base's own status through (404 on an unknown id must not read as a 502).
        detail = ""
        try:
            detail = e.read().decode("utf-8", "replace")[:300]
        except Exception:
            pass
        raise ConnectionsError("secret-base %s %s -> %s %s" % (method, path, e.code, detail), status=e.code)
    except Exception as e:
        raise ConnectionsError("secret-base %s %s unreachable: %s: %s" % (method, path, type(e).__name__, e))


# ── active pointer ─────────────────────────────────────────────────────────────
def active():
    """Currently selected connection id, or None when unset. Never raises: a missing/corrupt
    pointer file means 'nothing selected', which resolve_active() reads as 'use local'."""
    try:
        with open(ACTIVE_PATH, encoding="utf-8") as f:
            v = json.load(f).get("id")
        v = v or None
    except Exception:
        return None
    # A pointer at the synthetic env account when there IS no env account is not a selection — it
    # is a pointer at something that never existed. resolve_active() deliberately answers 503 for a
    # DANGLING pointer (an account the operator connected and later removed must never be silently
    # replaced by another one), and that rule is right and stays. This is the other case: nobody
    # ever connected this. The pointer survives in the /data volume across re-stages and across a
    # change of company, so a value inherited from `.env.ex` pinned the whole service to a Gmail
    # login that could not succeed. Fall back to the default, and say so once in the log rather
    # than failing every health check in silence.
    if v == ENV_ID and not env_configured():
        log.warning("active pointer names %s but no Gmail account is configured in env "
                    "(GMAIL_IMAP_USER/GMAIL_IMAP_APP_PW unset or still the .env.ex placeholder) — "
                    "falling back to the built-in mailbox", ENV_ID)
        return None
    return v


def select(instance_id):
    """Persist the active pointer. `None` clears it (back to the implicit local default)."""
    with _active_lock:
        try:
            os.makedirs(os.path.dirname(ACTIVE_PATH), exist_ok=True)
        except Exception:
            pass
        # write-then-rename: a crash mid-write must not leave a truncated pointer that reads as
        # "nothing selected" and silently swaps the operator's account back to local.
        tmp = ACTIVE_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"id": instance_id}, f)
        os.replace(tmp, ACTIVE_PATH)
    return instance_id


# ── secret-base ────────────────────────────────────────────────────────────────
def list_instances(from_vault_only=False):
    """Every mail connection the console can offer.

    Degrades on purpose. The local profiles are REAL vault rows now, so a vault outage would empty
    the account bar of a deployment whose mailboxes are working perfectly — the degradation the old
    synthetic row accidentally provided, minus its lie. The ledger on this service's own volume is
    the honest replacement: it knows which instance ids belong to this deployment's profiles, holds
    no secret, and is exactly the app-local state the architecture says must survive a connections
    outage. `from_vault_only` is for the reconciler, which must be able to tell "the vault does not
    have this instance" from "we remember it".
    """
    try:
        r = _http("GET", "/api/instances?protocol=" + PROTOCOL_GLOB)
        vault = [i for i in (r.get("instances") or []) if i.get("id") != ENV_ID]
        reachable = True
    except ConnectionsError:
        if from_vault_only:
            raise
        vault, reachable = [], False
    if from_vault_only:
        return vault
    out = list(vault)
    if not reachable:
        try:
            import profiles
            out = profiles.known_instances()
        except Exception:                                 # noqa: BLE001
            out = []
    envi = env_instance()
    if envi:
        out.append(envi)
    return out


def get_secret(instance_id):
    """{protocol, secret:{...}} for one instance. Service-only endpoint — in-network, never proxied
    out to the console or n8n."""
    if instance_id == ENV_ID:
        # Synthetic: the credentials are this process's env, not a vault row. When there are none,
        # 404 — the same answer the vault gives for an id that does not exist, because that is
        # exactly what this is. Handing back {username, ""} instead is what produced an adapter that
        # authenticated with a blank password on every single request.
        if not env_configured():
            raise ConnectionsError(
                "no Gmail account is configured in env (GMAIL_IMAP_USER/GMAIL_IMAP_APP_PW)",
                status=404)
        return {"protocol": ENV_PROTOCOL, "secret": {"username": _env_user(),
                                                     "password": _env_pw()}}
    return _http("GET", "/api/instances/%s/secret" % instance_id)


def put_secret(instance_id, secret):
    """Write a rotated secret back to the vault (§1 `PUT /api/instances/<id>/secret`). The ONLY
    caller is the OAuth adapter persisting a refreshed access token — without this the renewal lives
    in one process's memory, dies with the container, and (if Google ever rotates refresh tokens)
    leaves drive holding a token this service already invalidated.

    Merge is the endpoint's default, which is what we want: the adapter sends its merged grant, and
    even a partial write cannot drop the refresh_token. We never send `replace` — re-consent mints a
    new instance, it does not patch one.

    The env account's "vault" is the process env, so writing to it is a no-op by construction, not a
    failure.

    Best-effort BY DESIGN: the token in hand is already good and the adapter caches it, so a vault
    outage must cost a re-refresh after restart — never a failed mail op. Every failure is logged
    with its reason and swallowed; nothing here may raise into an op."""
    if instance_id == ENV_ID:
        return False
    try:
        _http("PUT", "/api/instances/%s/secret" % instance_id, {"secret": secret})
        return True
    except ConnectionsError as e:
        log.warning("connections: token write-back for %s failed: %s", instance_id, e)
        return False
    except Exception as e:      # json-encoding etc: _http only wraps what happens on the wire
        log.warning("connections: token write-back for %s failed: %s: %s",
                    instance_id, type(e).__name__, e)
        return False


def create_instance(protocol, label, secret, account_hint=None):
    body = {"protocol": protocol, "label": label, "secret": secret or {}}
    if account_hint:
        body["account_hint"] = account_hint
    return _http("POST", "/api/instances", body)


def delete_instance(instance_id):
    return _http("DELETE", "/api/instances/%s" % instance_id)


def dangling_instance(cid, reason):
    """A display-only record for a pointer that resolves to nothing (§2/§4b state propagation).

    /connections must never report an `active` id that is absent from its own list: the console then
    renders "no account selected" while /readyz reports on some other account, and the two disagree
    about the same fact. Surface the broken selection AS a row instead — with the `needs_action`
    chip the UI already knows and the service's own reason — so it can be seen and selected away
    from."""
    proto = cid.rsplit("-", 1)[0] if "-" in cid else ""
    return {"id": cid, "protocol": proto if proto in PROTOCOLS else "",
            "label": "חיבור שאינו זמין", "account_hint": "",
            "status": "needs_action", "reason": reason}


# NOTE: there is deliberately NO resolve_active() here. Resolution lives in exactly one place —
# adapters.resolve_active — because a second copy of "which account is this?" is a second answer,
# and the two drift. (The copy that used to live here fell through to the local default on a
# dangling pointer, which is the defect this module now exists to make impossible.)
