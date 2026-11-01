"""The adapter layer: which backend answers THIS request.

Contract §2: "the active pointer persists in the service (/data/active.json); `connection_id` on any
op overrides it for that call". This module is the one place that turns that pointer into a live
backend, so every op — and /readyz — routes identically and there is a single answer to "which
account is this?".

What it replaces: entry.py used to pick app.py vs local_app.py from GMAIL_IMAP_MODE at process start.
That made the protocol a BUILD-TIME property of the container, so selecting a connection could not
change what an op did (hence capabilities.ops_use_active_connection:false). Now ONE process holds a
backend per connection and dispatches per request; GMAIL_IMAP_MODE survives only as the bootstrap
default for "nothing selected" (CI sets it to local).

Protocols → backend:
  mail_imap_local          LocalBackend       our Postfix/Dovecot; secret {username, password} — the
                                              mailbox password IS the profile's credential, so this
                                              is the SAME shape as the row below it
  mail_imap_app_password   GmailBackend       secret {username, password}
  mail_gmail_oauth         GmailOAuthBackend  secret = the Google token dict; IMAP/SMTP XOAUTH2

stdlib only (urllib) for the token refresh: the image is flask + imapclient, and one POST an hour is
not worth a dependency.
"""
import os
import json
import time
import hashlib
import logging
import threading
import urllib.request
import urllib.error

import connections_client as cc

log = logging.getLogger(__name__)
from app import GmailBackend, GmailOAuthBackend
from local_app import LocalBackend

GOOGLE_TOKEN_URL = os.environ.get("GOOGLE_TOKEN_URL", "https://oauth2.googleapis.com/token")

# A secret lookup is an HTTP call to secret-base, and ops run hundreds of times a minute. Cache the
# resolution briefly: short enough that a rotated password takes effect on its own, long enough that
# the vault is not in the hot path of every label add.
SECRET_TTL_S = float(os.environ.get("MAIL_SECRET_TTL_S", "30"))

_lock = threading.Lock()
_backends = {}     # connection id -> (fingerprint, backend)
_secrets = {}      # connection id -> (fetched_at, protocol, secret)


# ── the op surface (§3) ────────────────────────────────────────────────────────
# op name -> the backend method that answers it. THIS DICT IS THE OP SURFACE: /manifest
# (connections_api.py) advertises its keys, `test_abstraction.py` holds every backend to it, and
# service.py's route table is one route per key — so the advertisement, the implementation and the
# uniformity across protocols cannot drift. Drive fixed the same class of bug the same way — its
# manifest had listed seven ops that had no routes at all.
#
# What was wrong here: the manifest hand-listed eight names ("exactly today's gmailApiImap01 op
# names") while the service had grown `thread` and `stats`. Nothing broke, because nothing
# dispatches off the manifest — it is read by humans and by n8n authors deciding what this service
# can do. So the cost was invisible and entirely real: `getThread` is the op the Mail Label Engine
# needed and could not discover.
#
# `deleteLabel` (/labels/delete) and the protocol-specific `rebuildLabels` (/labels/rebuild) were
# retired 2026-09-02 (RELEASE-DECISIONS N12): both had zero callers in the whole tree, and with
# them went the PROTOCOL_OPS split — every remaining op is answered by every protocol.
CANONICAL_OPS = {
    "search": "search",
    "get": "message",
    "getThread": "thread",
    "addLabels": "labels_add",
    "removeLabels": "labels_remove",
    "listLabels": "labels_list",
    "createLabel": "labels_create",
    "append": "append",
    "send": "send",
    "stats": "stats",
}

# Ops that USED to exist. Advertised nowhere; listed so a backend cannot quietly grow one back
# without the abstraction test noticing (a method with no route is dead code, not an op).
RETIRED_OPS = {
    "deleteLabel": "labels_delete",
    "rebuildLabels": "labels_rebuild",
}


def ops_for(backend):
    """The ops a given backend actually answers. Derived by asking the object, so a backend that
    loses a method stops advertising it rather than advertising a 500."""
    return [k for k, m in CANONICAL_OPS.items() if callable(getattr(backend, m, None))]


class AdapterError(Exception):
    """The connection cannot be turned into a working backend (unknown id/protocol, vault down with
    nothing cached, OAuth without a client). Carries the status the caller should return.

    It also carries WHICH connection failed, and that is not a detail. Any op accepts a per-call
    `connection_id` override, so the failing connection is frequently NOT the active one — and the
    error handler used to report `cc.active()` regardless. Asking mail to send through a broken Gmail
    account produced:

        {"connection_id": "mail_imap_local-local",
         "error": "connection mail_imap_app_password-env: secret needs {username, password}"}

    Two different accounts named in one response, the wrong one in the field a machine reads. An
    operator follows that field and goes to inspect a local mailbox that was never involved.
    """

    def __init__(self, message, status=502, connection_id=None):
        super().__init__(message)
        self.status = status
        self.connection_id = connection_id


# ── OAuth tokens ───────────────────────────────────────────────────────────────
class GoogleTokens:
    """Access-token supplier for one mail_gmail_oauth connection.

    The vault holds the grant exactly as Google's token endpoint returned it (connections' OAuth
    broker stores `tok` verbatim): {access_token, refresh_token, expires_in, scope, ...}. Note what is
    NOT in there — an absolute expiry. `expires_in` is relative to a mint time nobody recorded, so a
    stored access_token is of unknown age and we refresh once on first use rather than opening an IMAP
    connection with a token that may already be dead.
    """

    def __init__(self, connection_id, secret):
        self.cid = connection_id
        self.tok = dict(secret or {})
        self._access = self.tok.get("access_token") or ""
        # Unknown age (see above) -> assume expired when we can mint a new one; when we cannot
        # (no refresh_token), the stored token is all we have — use it and let the login error say so.
        self._exp = 0 if self.tok.get("refresh_token") else time.time() + 3600
        self._lock = threading.Lock()

    def access_token(self):
        with self._lock:
            if self._access and time.time() < self._exp:
                return self._access
            if not self.tok.get("refresh_token"):
                if self._access:
                    return self._access
                raise AdapterError("connection %s has neither access_token nor refresh_token" % self.cid, 502,
                                   connection_id=self.cid)
            self._refresh()
            return self._access

    def _refresh(self):
        cid_env = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID", "").strip()
        secret_env = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not cid_env or not secret_env:
            # The refresh_token is worthless without the client that minted it; say so plainly
            # instead of surfacing a Google 401 the operator cannot act on.
            raise AdapterError("cannot refresh %s: N8N_GOOGLE_OAUTH_CLIENT_ID/SECRET are not set" % self.cid,
                               502, connection_id=self.cid)
        from urllib.parse import urlencode
        body = urlencode({"client_id": cid_env, "client_secret": secret_env,
                          "refresh_token": self.tok["refresh_token"],
                          "grant_type": "refresh_token"}).encode()
        req = urllib.request.Request(GOOGLE_TOKEN_URL, data=body, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                fresh = json.load(r)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:
                pass
            raise AdapterError("token refresh for %s failed: %s %s" % (self.cid, e.code, detail), 502,
                               connection_id=self.cid)
        except Exception as e:
            raise AdapterError("token refresh for %s failed: %s: %s" % (self.cid, type(e).__name__, e), 502,
                               connection_id=self.cid)
        self._access = fresh.get("access_token") or ""
        if not self._access:
            raise AdapterError("token refresh for %s returned no access_token" % self.cid, 502,
                               connection_id=self.cid)
        # 60s skew: a token that expires while an IMAP op is in flight fails the whole op.
        self._exp = time.time() + max(60, int(fresh.get("expires_in") or 3600)) - 60
        # Google does not return the refresh_token on a refresh — keep ours.
        self.tok.update({k: v for k, v in fresh.items() if k != "refresh_token"})
        cc.put_secret(self.cid, self.tok)   # best-effort; see connections_client.put_secret


# ── resolution ─────────────────────────────────────────────────────────────────
def _fingerprint(protocol, secret):
    """Identity of the CREDENTIAL, not of the connection: when a password is rotated or an account
    re-consented, the id is unchanged but every socket the old backend holds is dead. Comparing this
    is what makes a rotation take effect without a restart."""
    blob = json.dumps({"p": protocol, "s": secret}, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _fetch(cid, explicit=False):
    """(protocol, secret) for a connection id, TTL-cached.

    Two failures that look alike and must not be treated alike:

    * the vault is UNREACHABLE — fall back to the last known values. An op must not fail because
      the vault blinked, and the credential we already hold is still the right one.
    * the vault says 404 — the instance is GONE. That is authoritative, so the cache is now a lie:
      drop it and fail. Serving a deleted account's cached grant would keep mail silently running
      on credentials the operator believes he removed (and the TTL would never expire it, because
      every miss would re-serve the same stale entry).

    `explicit` distinguishes a per-call connection_id (a caller naming an id that does not exist:
    404, their mistake) from the ACTIVE POINTER dangling (503: the service is not ready — this is
    what /readyz must report, and it must never be answered by substituting another account)."""
    now = time.time()
    hit = _secrets.get(cid)
    if hit and now - hit[0] < SECRET_TTL_S:
        return hit[1], hit[2]
    try:
        r = cc.get_secret(cid)
    except cc.ConnectionsError as e:
        if e.status == 404:
            _secrets.pop(cid, None)
            raise AdapterError(
                "החשבון שנבחר (%s) אינו קיים יותר. בחר חשבון אחר או חבר אותו מחדש." % cid,
                404 if explicit else 503, connection_id=cid)
        if hit:
            return hit[1], hit[2]
        raise AdapterError("לא ניתן לאמת את החשבון שנבחר (%s): %s" % (cid, e), 503, connection_id=cid)
    protocol, secret = (r.get("protocol") or ""), (r.get("secret") or {})
    _secrets[cid] = (now, protocol, secret)
    return protocol, secret


def _account_hint(cid):
    """The instance's display hint (the Google email, for an OAuth grant). Best-effort: it lives on
    the list endpoint, which is secret-free, so this leaks nothing and degrades to ''."""
    try:
        for inst in cc.list_instances():
            if inst.get("id") == cid:
                return (inst.get("account_hint") or "").strip()
    except Exception:
        pass
    return ""


def _build(cid, protocol, secret):
    if protocol == cc.LOCAL_PROTOCOL:
        # The private engine is no longer special: a profile on it carries {username, password} in
        # the vault, exactly like a Gmail app-password account, and THAT is what it logs in as.
        #
        # This used to be `return LocalBackend()` — the secret discarded, the credentials taken from
        # the LOCALMAIL_* env. Because the identity came from the process rather than the profile,
        # every mail_imap_local instance resolved to the SAME mailbox: an operator could add one,
        # see it listed, select it, and be served somebody else's mail with nothing reporting an
        # error. Refusing a credential-less instance is what closes that path; there is no ambient
        # identity left to fall back to.
        user = secret.get("username") or secret.get("user") or ""
        pw = secret.get("password") or ""
        if not user or not pw:
            raise AdapterError(
                "connection %s: a local mail profile must carry its own {username, password}. "
                "Local mailboxes are created on the mailbox screen (POST /mailboxes), which mints "
                "the connection with them." % cid, 502, connection_id=cid)
        return LocalBackend(user, password=pw,
                            imap_host=secret.get("imap_host"), imap_port=secret.get("imap_port"),
                            smtp_host=secret.get("smtp_host"), smtp_port=secret.get("smtp_port"),
                            connection_id=cid)
    if protocol == "mail_imap_app_password":
        user = secret.get("username") or secret.get("user") or ""
        pw = secret.get("password") or secret.get("app_password") or ""
        if not user or not pw:
            raise AdapterError("connection %s: secret needs {username, password}" % cid, 502, connection_id=cid)
        return GmailBackend(user, password=pw,
                            imap_host=secret.get("imap_host"), imap_port=secret.get("imap_port"),
                            smtp_host=secret.get("smtp_host"), smtp_port=secret.get("smtp_port"))
    if protocol == "mail_gmail_oauth":
        # XOAUTH2 needs the address as well as the token. The grant carries it only inside the
        # id_token JWT, which connections already decoded into the instance's account_hint — and the
        # secret endpoint does not return that field, so read it off the (secret-free) list.
        user = secret.get("username") or secret.get("email") or _account_hint(cid)
        if not user:
            raise AdapterError("connection %s: cannot tell which Gmail address the token is for "
                               "(no username in the secret, no account_hint on the instance)" % cid,
                               502, connection_id=cid)
        tokens = GoogleTokens(cid, secret)
        return GmailOAuthBackend(user, token_provider=tokens.access_token)
    raise AdapterError("connection %s: unsupported protocol %r" % (cid, protocol), 400, connection_id=cid)


def resolve_active(connection_id=None):
    """(connection_id, backend) for this request.

    Precedence: explicit per-op connection_id > the persisted active pointer > GMAIL_IMAP_MODE.
    Backends are cached per connection because they own IMAP sockets (Gmail caps ~15 per account) —
    rebuilding one per request would open and abandon a pool on every op. The cache is keyed by
    credential fingerprint, so a rotated secret builds a new backend and closes the stale one.

    A pointer that no longer resolves raises (503) instead of falling through to the bootstrap
    default: an UNSET pointer means "use the default", a BROKEN one means "not ready". Collapsing
    those two is how the drive service came to report ready:true on the local disk while the owner
    believed he had selected his Google account."""
    # The pre-refactor synthetic id for the local engine. Old configs still pin it (the sync
    # registry's mail pipe, platform.state.yaml) but the reconciler now mints
    # mail_imap_local-<8hex> instances and the pointer migrator moved the ACTIVE pointer off it.
    # A stale pin therefore degrades to "the account this deployment actually has" instead of a
    # hard 404 every fifteen minutes. Any REAL instance id is still honoured as given. If the
    # remap finds nothing either, cid stays None and the honest 503 bootstrap path below fires.
    if connection_id == "mail_imap_local-local":
        connection_id = cc.active() or cc.default_id()
    explicit = bool(connection_id)
    cid = connection_id or cc.active() or cc.default_id()
    if not cid:
        # There is no synthetic account to stand in any more, so "nothing is configured yet" is a
        # state that can be reported rather than papered over. It resolves itself: the engine
        # reconciler creates the declared profiles and retries until it can.
        raise AdapterError(
            "אין עדיין חשבון דואר מוגדר בפריסה הזו — פרופילי שרת הדואר המקומי נוצרים ברקע. "
            "(no mail profile exists yet: the engine bootstrap has not completed a pass)",
            503, connection_id=None)
    protocol, secret = _fetch(cid, explicit=explicit)
    fp = _fingerprint(protocol, secret)
    with _lock:
        hit = _backends.get(cid)
        if hit and hit[0] == fp:
            return cid, hit[1]
        backend = _build(cid, protocol, secret)
        _backends[cid] = (fp, backend)
    if hit:
        try:
            hit[1].close()   # the credential changed: drop the old account's sockets
        except Exception:
            pass
    return cid, backend


def forget(cid):
    """Drop a connection's cached backend + secret (it was deleted or re-selected away)."""
    with _lock:
        hit = _backends.pop(cid, None)
        _secrets.pop(cid, None)
    if hit:
        try:
            hit[1].close()
        except Exception:
            pass


def close_all():
    """LOGOUT every cached backend — registered as an atexit/SIGTERM hook (entry.py) so a container
    stop or redeploy sends a real IMAP LOGOUT instead of dropping the sockets silently. Without this,
    Gmail keeps each abandoned server-side session alive for ~30 min against the ~15/account cap, so
    a few quick recreates could lock the account out even though the new container holds one socket.
    Idempotent and never raises."""
    with _lock:
        hits = list(_backends.values())
        _backends.clear()
        _secrets.clear()
    for _fp, backend in hits:
        try:
            backend.close()
        except Exception:
            pass
