"""Engine profiles — the identities on the PRIVATE mail engine, and the reconciler that makes each
declared one a real, working mail account.

Architecture: ai/context/app-engine-pattern.md. This module is mail's implementation of §5–§7 of it.

── the whole idea in one line ────────────────────────────────────────────────────────────────────
A mail profile's credential IS its mailbox password, so `{username, password}` — byte-identical in
shape to the Gmail app-password profile. That single fact is what collapses the private engine's
special case: `LocalBackend(user, pw)` becomes the same kind of object as `GmailBackend(user, pw)`,
the profile becomes a REAL vault instance instead of a synthesised row, and N profiles cost nothing.

What was here before: exactly one synthetic instance, `mail_imap_local-local`, with no vault row and
no secret, whose credentials came from the LOCALMAIL_* env — i.e. from the PROCESS, not from the
profile. Because the credentials were ambient, every `mail_imap_local` instance an operator created
resolved to the SAME mailbox: `POST /connections` accepted it, listed it, let you select it, and then
served somebody else's mail with no error anywhere. That path is gone (adapters._build now REQUIRES
the secret, and connections_api refuses to mint a credential-less local instance).

── the three planes and who owns what ────────────────────────────────────────────────────────────
  catalogue    apps/mail/app.json `engine.profiles`, compiled by reconcile.py into
               MAIL_ENGINE_PROFILES. The ONLY place a profile is declared.
  credential   the connections vault: one instance per profile, holding {username, password}.
  ledger       THIS module, on the app's own volume (/data/engine-profiles.json): which profiles the
               reconciler created, which instance each maps to, and whether we made the mailbox.

The ledger holds no password. That is not an omission — the vault is the credential plane, and a
second copy is a second thing to leak and a second thing to drift. The consequence is deliberate and
is the rule below: if an instance is lost, the password is genuinely unrecoverable, so the only way
back to a working profile is to rotate it and say so.

── the reconcile table (idempotent; the same on a fresh and on an existing machine) ──────────────
  declared, no mailbox, no instance      create the mailbox with a minted password, create the
                                         instance carrying it, record the ledger entry
  declared, mailbox + instance both live LEAVE ALONE. **Never re-mint.** Re-minting on boot would
                                         invalidate every stored client credential on every restart
  declared, mailbox live, instance gone  adopt (the primary mailbox, using LOCALMAIL_PW, verified by
                                         an actual IMAP login) — otherwise ROTATE, and log that we did
  declared, instance live, mailbox gone  recreate the mailbox and write the new password back to the
                                         existing instance (the id an operator selected survives)
  ours + declared, no longer declared    remove the instance, and the mailbox only if WE created it
  never ours (created from the UI)       LEAVE ALONE, always. A redeploy must never delete an
                                         operator's mailbox — hence `source` in the ledger.

That is the rule `mailserver-init` already proves in this same app; it is reused, not reinvented.

── failure is a retry, never a boot failure ──────────────────────────────────────────────────────
mailapi has no depends_on for mailboxd or connections, so at container start either may be absent.
`start()` runs one pass inline and then retries in the background. A pass that cannot reach the
vault still does its mailbox half and leaves the instance for a later pass — where the password is
by then unrecoverable and gets rotated. Nothing here raises into a request, and nothing mints twice.
"""
import json
import logging
import os
import secrets
import threading
import time

import connections_client as cc
import local_app
import mailboxes

log = logging.getLogger(__name__)

PROTOCOL = "mail_imap_local"

# The app's own volume (gmail_imap_data), beside active.json and the per-profile labels/ directory.
# App-local ON PURPOSE: a connections outage must degrade a LIST, not erase this deployment's
# knowledge of who exists.
LEDGER_PATH = os.environ.get("MAIL_PROFILE_LEDGER_PATH", "/data/engine-profiles.json")

# Rendered by platform/manager/reconcile.py from apps/mail/app.json `engine.profiles`.
DECLARED_ENV = "MAIL_ENGINE_PROFILES"

# Never hardcoded, and never re-derived: the SAME variable the MTA, mailboxd and the local backend
# read (BUSINESS_NAME -> COMPANY_SLUG -> DEPLOYMENT_DOMAIN -> MAIL_DOMAIN). The one time these two
# sides derived an address separately, mailserver-init provisioned indox@<company>.digital-office…
# while the backend logged in as indox@local.test — both halves correct in isolation.
MAIL_DOMAIN = (os.environ.get("MAIL_DOMAIN") or "local.test").strip().lower() or "local.test"

_lock = threading.Lock()
_state = {"runs": 0, "last_run": 0, "ok": False, "error": "", "actions": []}


# ── what is DECLARED ───────────────────────────────────────────────────────────
def _fallback_declared():
    """One admin profile at the primary mailbox, for a deployment whose .generated/ predates
    MAIL_ENGINE_PROFILES. Without this, upgrading the image would leave a running company with zero
    profiles and therefore zero connections — the synthetic instance it used to fall back on is gone.
    Derived from the SAME LOCALMAIL_USER the MTA provisions from, so it adopts rather than duplicates.
    """
    local = local_app.USER.split("@")[0]
    return [{"id": local, "display_name": local, "admin": True}]


def declared():
    """[{id, display_name, admin}] — the profiles app.json declares, normalised.

    Malformed entries are DROPPED with a log line rather than failing the boot: this value arrives on
    an env var, and a service that will not start because a display name was mistyped is a worse
    failure than one that starts with the profiles it could understand."""
    raw = (os.environ.get(DECLARED_ENV) or "").strip()
    if not raw:
        return _fallback_declared()
    try:
        items = json.loads(raw)
    except Exception as e:
        log.warning("profiles: %s is not valid JSON (%s) — falling back to the primary mailbox",
                    DECLARED_ENV, e)
        return _fallback_declared()
    if not isinstance(items, list):
        log.warning("profiles: %s is not a list — falling back to the primary mailbox", DECLARED_ENV)
        return _fallback_declared()
    out, seen = [], set()
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("id") or "").strip().lower()
        if not pid or pid in seen:
            continue
        seen.add(pid)
        out.append({"id": pid,
                    "display_name": str(it.get("display_name") or pid),
                    "admin": bool(it.get("admin"))})
    if not out:
        return _fallback_declared()
    # "The first declared profile with admin:true is the one a fresh deployment comes up with." If
    # nobody is declared admin there is no way to manage anyone, so the first profile becomes one —
    # stated here rather than left to the operator to discover by finding the screen unreachable.
    if not any(p["admin"] for p in out):
        out[0]["admin"] = True
    return out


def address_of(pid):
    """<id>@<MAIL_DOMAIN>. The address is DERIVED, never declared — a profile declared with a domain
    of its own would be an address the MX does not point here for, i.e. live on screen and a black
    hole in the world."""
    return "%s@%s" % (str(pid).strip().lower(), MAIL_DOMAIN)


# ── the ledger ─────────────────────────────────────────────────────────────────
def _empty_ledger():
    return {"version": 1, "domain": MAIL_DOMAIN, "profiles": {}}


def ledger():
    try:
        with open(LEDGER_PATH, encoding="utf-8") as fh:
            d = json.load(fh)
        if isinstance(d, dict) and isinstance(d.get("profiles"), dict):
            return d
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("profiles: ledger at %s is unreadable (%s) — starting a new one. Nothing is "
                    "deleted on the strength of a ledger we could not read.", LEDGER_PATH, e)
    return _empty_ledger()


def _write_ledger(led):
    """write-then-rename: a truncated ledger reads as 'we own nothing', and the reconciler acts on
    ownership — a half-written file must never be able to orphan a profile."""
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    tmp = LEDGER_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(led, fh, ensure_ascii=False, indent=1, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, LEDGER_PATH)


# ── lookups the rest of the service asks for ───────────────────────────────────
def entries():
    """[(profile_id, record)] in declaration order first, then anything else we know about."""
    led = ledger()["profiles"]
    order = [p["id"] for p in declared()]
    out = [(pid, led[pid]) for pid in order if pid in led]
    out += [(pid, rec) for pid, rec in sorted(led.items()) if pid not in order]
    return out


def by_instance(cid):
    """(profile_id, record) for the profile that owns this connection id, or (None, None)."""
    if not cid:
        return None, None
    for pid, rec in ledger()["profiles"].items():
        if rec.get("instance_id") == cid:
            return pid, rec
    return None, None


def by_address(address):
    a = (address or "").strip().lower()
    for pid, rec in ledger()["profiles"].items():
        if (rec.get("address") or "").lower() == a:
            return pid, rec
    return None, None


def admin_ids():
    return [pid for pid, rec in ledger()["profiles"].items() if rec.get("admin")]


def default_instance_id():
    """The instance a deployment with nothing selected acts as: the FIRST DECLARED admin profile.

    Note what this is not — there is no "default profile" concept and nothing branches on one. This
    is only the answer to "nothing is selected yet"; §9 law 1 still holds, an unset pointer means
    "use the default" and a BROKEN pointer means "not ready", never a fallback."""
    led = ledger()["profiles"]
    for p in declared():
        rec = led.get(p["id"])
        if p["admin"] and rec and rec.get("instance_id"):
            return rec["instance_id"]
    for p in declared():
        rec = led.get(p["id"])
        if rec and rec.get("instance_id"):
            return rec["instance_id"]
    for _pid, rec in sorted(led.items()):
        if rec.get("instance_id"):
            return rec["instance_id"]
    return None


def known_instances():
    """The profile instances as connection rows, from the LEDGER — what /connections can still show
    when the vault is unreachable. Same shape the vault returns, so the console cannot tell which
    half answered, and a connections outage degrades a list rather than emptying the account bar."""
    out = []
    for pid, rec in entries():
        iid = rec.get("instance_id")
        if not iid:
            continue
        out.append({"id": iid, "protocol": PROTOCOL,
                    "label": rec.get("display_name") or pid,
                    "account_hint": rec.get("address") or "",
                    "status": "ok"})
    return out


# ── primitives ─────────────────────────────────────────────────────────────────
def mint_password():
    """A credential nobody types. It is minted here and put straight into the vault; the only way to
    read it is the service-only secret endpoint, and the only way to change it is a rotation."""
    return secrets.token_urlsafe(18)


def _imap_ok(user, password):
    """Can this credential actually log in? The one question that separates 'adopt the existing
    mailbox' from 'rotate it'. Asked against the very Dovecot the ops use, so a yes here means the
    profile works, not that a variable was set."""
    if not user or not password:
        return False
    try:
        from imapclient import IMAPClient
        c = IMAPClient(local_app.IMAP_HOST, port=local_app.IMAP_PORT,
                       ssl=local_app.IMAP_SSL, timeout=15)
        try:
            c.login(user, password)
            return True
        finally:
            try:
                c.logout()
            except Exception:
                pass
    except Exception:
        return False


def _mint_instance(address, label, password):
    r = cc.create_instance(PROTOCOL, label, {"username": address, "password": password}, address)
    iid = r.get("id") if isinstance(r, dict) else None
    if not iid:
        raise cc.ConnectionsError("connections did not return an instance id for %s" % address)
    return iid


# ── the reconciler ─────────────────────────────────────────────────────────────
def _mailbox_index():
    """{address: row} for every mailbox the MTA has, or None when mailboxd is unreachable.

    None and {} are NOT the same answer and must never be conflated: an empty domain means "create
    everything", an unreachable writer means "we do not know" — and acting on the second as if it
    were the first would recreate mailboxes that already exist."""
    payload, code = mailboxes.listing()
    if code != 200 or not payload.get("available"):
        return None
    return {(m.get("address") or "").lower(): m for m in (payload.get("mailboxes") or [])}


def _vault_index():
    """{instance_id: instance} for our protocol, or None when the vault is unreachable."""
    try:
        return {i["id"]: i for i in cc.list_instances(from_vault_only=True)
                if i.get("protocol") == PROTOCOL and i.get("id")}
    except cc.ConnectionsError:
        return None


def reconcile():
    """One idempotent pass. Returns (acts, vault_deferred).

    `acts` is a list of human-readable actions taken (empty = nothing to do, which is what every
    run after the first must produce). `vault_deferred` is True when this pass skipped work
    because the vault was unreachable — a profile's instance could not be created, verified, or
    torn down. THIS is the signal the boot loop must retry on.

    It used to be conflated with "did reconcile() raise?", and that was the bug: a cold `bbox run`
    starts mailapi before `connections` is guaranteed healthy (deliberately — see start()'s
    docstring), the first pass's vault calls came back unreachable, every deferral was logged and
    swallowed rather than raised, and the boot loop read "no exception" as "done" and stopped
    retrying FOREVER. The mailbox existed; its only credential lived in the vault call that never
    happened, so `/healthz`'s IMAP login had nothing to authenticate with — indefinitely, until an
    operator manually restarted the container (which is what actually fixes it today, and is the
    reproduction that found this). Reported: mailapi and its consumer mailview stayed unhealthy
    long after `connections` itself came up."""
    acts = []
    vault_deferred = False
    boxes = _mailbox_index()
    if boxes is None:
        raise RuntimeError("mailboxd is unreachable — nothing reconciled, will retry")
    vault = _vault_index()          # may be None: the mailbox half still runs
    led = ledger()
    profs = led.setdefault("profiles", {})
    led["domain"] = MAIL_DOMAIN
    want = declared()
    want_ids = {p["id"] for p in want}

    def has_instance(rec):
        iid = rec.get("instance_id")
        if not iid:
            return False
        return True if vault is None else iid in vault

    for p in want:
        pid, addr = p["id"], address_of(p["id"])
        rec = profs.get(pid)
        # An entry whose recorded address no longer matches the deployment's domain is a PREVIOUS
        # tenant's, not ours: the volume outlives .env. Drop the pointer and re-provision at the
        # address this deployment actually serves.
        if rec and (rec.get("address") or "").lower() != addr:
            acts.append("profile %s: recorded address %s is not at %s — re-provisioning"
                        % (pid, rec.get("address"), MAIL_DOMAIN))
            rec = None
            profs.pop(pid, None)

        box_ok = addr in boxes
        inst_ok = bool(rec) and has_instance(rec)

        if box_ok and inst_ok:
            # THE IDEMPOTENT PATH. Cosmetics may move; the credential never does.
            changed = []
            if rec.get("display_name") != p["display_name"]:
                rec["display_name"] = p["display_name"]
                changed.append("display_name")
            if bool(rec.get("admin")) != p["admin"]:
                rec["admin"] = p["admin"]
                changed.append("admin")
            if rec.get("source") != "declared":
                rec["source"] = "declared"      # a UI-created profile that is now declared
                changed.append("source")
            if changed:
                acts.append("profile %s: updated %s (credential untouched)" % (pid, ",".join(changed)))
            continue

        base = {"address": addr, "display_name": p["display_name"], "admin": p["admin"],
                "source": "declared", "protocol": PROTOCOL}

        if not box_ok and not inst_ok:
            pw = mint_password()
            payload, code = mailboxes.create({"local": pid, "password": pw})
            if code == 409:
                # Raced with something else creating it. Fall through to the "mailbox exists,
                # instance missing" branch on the NEXT pass rather than guessing a password.
                acts.append("profile %s: mailbox %s appeared during the pass — deferring" % (pid, addr))
                continue
            if code not in (200, 201):
                acts.append("profile %s: could not create mailbox %s: %s"
                            % (pid, addr, payload.get("error") or code))
                continue
            rec = dict(base, mailbox_created=True, created_at=int(time.time()))
            profs[pid] = rec
            acts.append("profile %s: created mailbox %s" % (pid, addr))
            _write_ledger(led)      # persist BEFORE the vault call: a crash here must leave a
                                    # mailbox we KNOW is ours, not an orphan we would later adopt
            if vault is None:
                vault_deferred = True
                acts.append("profile %s: connections unreachable — the instance will be created on a "
                            "later pass (the password is not kept outside the vault, so that pass "
                            "will rotate it)" % pid)
                continue
            try:
                rec["instance_id"] = _mint_instance(addr, p["display_name"], pw)
            except cc.ConnectionsError as e:
                acts.append("profile %s: mailbox created, instance deferred (%s)" % (pid, e))
                continue
            acts.append("profile %s: created instance %s" % (pid, rec["instance_id"]))
            continue

        if box_ok and not inst_ok:
            if vault is None:
                vault_deferred = True
                acts.append("profile %s: connections unreachable — instance deferred" % pid)
                continue
            # ADOPT if we can prove a credential works; otherwise the password is unrecoverable and
            # the only honest move is to rotate it. The seed is LOCALMAIL_PW, which is what
            # mailserver-init provisioned the primary mailbox with — so an existing deployment
            # migrates in silence instead of growing a duplicate account.
            seed = local_app.PW if addr == local_app.USER.lower() else None
            adopted = bool(seed) and _imap_ok(addr, seed)
            if adopted:
                pw = seed
                acts.append("profile %s: adopted the existing mailbox %s (LOCALMAIL_PW verified by "
                            "IMAP login — password NOT rotated)" % (pid, addr))
            else:
                pw = mint_password()
                payload, code = mailboxes.set_password(addr, pw)
                if code != 200:
                    acts.append("profile %s: could not rotate %s: %s"
                                % (pid, addr, payload.get("error") or code))
                    continue
                acts.append("profile %s: mailbox %s exists but its credential is not recoverable "
                            "(no vault instance holds it) — ROTATED to a freshly minted password"
                            % (pid, addr))
            keep_mailbox_flag = bool(rec and rec.get("mailbox_created"))
            rec = dict(base, mailbox_created=keep_mailbox_flag,
                       created_at=(rec or {}).get("created_at") or int(time.time()))
            profs[pid] = rec
            try:
                rec["instance_id"] = _mint_instance(addr, p["display_name"], pw)
            except cc.ConnectionsError as e:
                acts.append("profile %s: instance creation failed (%s)" % (pid, e))
                _write_ledger(led)
                continue
            acts.append("profile %s: created instance %s" % (pid, rec["instance_id"]))
            continue

        # instance live, mailbox gone — somebody removed the account under us. Recreate it and write
        # the new password into the SAME instance, so the id the operator selected still works.
        pw = mint_password()
        payload, code = mailboxes.create({"local": pid, "password": pw})
        if code not in (200, 201):
            acts.append("profile %s: instance %s exists but mailbox %s is gone and could not be "
                        "recreated: %s" % (pid, rec.get("instance_id"), addr,
                                           payload.get("error") or code))
            continue
        if not cc.put_secret(rec["instance_id"], {"username": addr, "password": pw}):
            acts.append("profile %s: recreated mailbox %s but could not update instance %s — the "
                        "instance holds a dead password until the next pass"
                        % (pid, addr, rec.get("instance_id")))
            continue
        rec.update(base)
        rec["mailbox_created"] = True
        acts.append("profile %s: mailbox %s was missing — recreated and rotated instance %s onto it"
                    % (pid, addr, rec["instance_id"]))

    # ── ours, no longer declared ────────────────────────────────────────────────
    # ONLY entries we recorded as `declared`. A profile created from the UI is `source: "ui"` and is
    # never touched here: it is declared nowhere, and a redeploy that deleted it would destroy an
    # address a company already hands out. Same rule mailserver-init applies to the accounts file.
    for pid in [k for k in list(profs) if k not in want_ids]:
        rec = profs[pid]
        if rec.get("source") != "declared":
            continue
        iid = rec.get("instance_id")
        if iid and vault is not None and iid in vault:
            try:
                cc.delete_instance(iid)
                acts.append("profile %s: removed instance %s (no longer declared)" % (pid, iid))
            except cc.ConnectionsError as e:
                acts.append("profile %s: could not remove instance %s (%s)" % (pid, iid, e))
                continue
            if cc.active() == iid:
                cc.select(None)
        elif iid and vault is None:
            vault_deferred = True
            continue                       # cannot verify — try again on a later pass
        if rec.get("mailbox_created") and (rec.get("address") or "").lower() in boxes:
            payload, code = mailboxes.delete(rec["address"])
            if code == 200:
                acts.append("profile %s: removed mailbox %s (no longer declared; mail kept at %s)"
                            % (pid, rec["address"], payload.get("maildir", "/var/mail")))
            else:
                acts.append("profile %s: could not remove mailbox %s: %s"
                            % (pid, rec["address"], payload.get("error") or code))
        profs.pop(pid, None)

    _write_ledger(led)
    _migrate_pointer()
    return acts, vault_deferred


# The id the synthetic instance used to have. It is not a constant this module uses for anything —
# it exists only so a pointer left behind by the previous design can be recognised and moved.
_LEGACY_SYNTHETIC_ID = "mail_imap_local-local"


def _migrate_pointer():
    """Move a pointer that names the deleted synthetic instance onto the admin profile.

    This is NOT the dangling-pointer fallback the architecture forbids: that rule protects an
    operator's OWN selection of an account that later vanished. This is our own id changing under a
    selection nobody made — the pointer says "the built-in mailbox", which is precisely what the
    admin profile now is. Left alone it would resolve to nothing and answer 503 forever."""
    try:
        cur = cc.active()
    except Exception:
        return
    if cur != _LEGACY_SYNTHETIC_ID:
        return
    iid = default_instance_id()
    if not iid:
        return
    cc.select(iid)
    log.warning("profiles: active pointer %s no longer exists (the synthetic local instance is "
                "gone) — moved to the admin profile's real instance %s", _LEGACY_SYNTHETIC_ID, iid)


# ── profile management (the UI's create/delete, and the admin ring) ────────────
class ProfileError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def acting(connection_id=None):
    """(profile_id, record) for the profile this request acts as: the explicit connection_id, else
    the active pointer, else the default. (None, None) when the caller is not acting as a profile on
    this engine at all — a Gmail account is selected, say."""
    cid = connection_id or cc.active() or cc.default_id()
    return by_instance(cid)


def require_admin(connection_id=None, target_pid=None):
    """The two rings, checked HERE — in the engine — and not in the UI (§4).

    Bootstrap exemption: while the ledger is empty there is no admin to be authorised by, and
    refusing would make the first profile uncreatable. It closes the moment one profile exists."""
    if not ledger()["profiles"]:
        return None, None
    pid, rec = acting(connection_id)
    if not pid:
        raise ProfileError(
            "ניהול תיבות דואר מחייב לפעול כפרופיל של שרת הדואר המקומי. בחר חשבון מקומי בסרגל "
            "החשבונות ונסה שוב.", 403)
    if rec.get("admin"):
        return pid, rec
    if target_pid and target_pid == pid:
        return pid, rec                     # the `self` ring: a profile may manage itself
    raise ProfileError("הפרופיל %s אינו מנהל ואינו רשאי לנהל פרופילים אחרים." % pid, 403)


def _assert_not_last_admin(pid, demoting=False):
    admins = admin_ids()
    if pid in admins and len(admins) <= 1:
        raise ProfileError(
            "%s הוא המנהל האחרון — %s יהפוך את ניהול הפרופילים לבלתי נגיש."
            % (pid, "הורדתו" if demoting else "מחיקתו"), 409)


def create_profile(local, password, display_name=None, admin=False, source="ui"):
    """Create the mailbox AND its connection in ONE operation (§7).

    Create-then-separately-connect is a step with no decision in it, and it is exactly what made
    "add a mail user" undiscoverable: mailboxd minted addresses, connections held profiles, and
    nothing joined them — so a mailbox created from the UI was not reachable as a profile at all."""
    pid = (local or "").strip().lower().split("@")[0]
    if not pid:
        raise ProfileError("שם תיבה נדרש", 400)
    addr = address_of(pid)
    pw = password or mint_password()
    payload, code = mailboxes.create({"local": pid, "password": pw})
    if code not in (200, 201):
        # mailboxd's own refusals are answers, not failures (409: the address exists) — forward verbatim.
        return payload, code
    led = ledger()
    rec = {"address": addr, "display_name": display_name or pid, "admin": bool(admin),
           "source": source, "protocol": PROTOCOL, "mailbox_created": True,
           "created_at": int(time.time())}
    led["profiles"][pid] = rec
    _write_ledger(led)
    try:
        rec["instance_id"] = _mint_instance(addr, rec["display_name"], pw)
        _write_ledger(led)
    except cc.ConnectionsError as e:
        # The mailbox is real and receives mail; only its APPEARANCE as a connection is missing, and
        # the reconciler picks that up (rotating, because the password is not kept here). Say so.
        log.warning("profiles: created mailbox %s but the connection could not be minted: %s", addr, e)
        payload = dict(payload)
        payload["connection_pending"] = True
        payload["connection_error"] = str(e)
        return payload, code
    out = dict(payload)
    out["profile"] = pid
    out["connection_id"] = rec["instance_id"]
    return out, code


def delete_profile(address):
    """Remove ACCESS: the connection instance and the account. Never the mail — mailboxd leaves the
    maildir on disk and says where it is (§9 law 8)."""
    pid, rec = by_address(address)
    if pid:
        _assert_not_last_admin(pid)
    payload, code = mailboxes.delete(address)
    if code != 200:
        return payload, code
    if pid:
        led = ledger()
        led_rec = led["profiles"].pop(pid, None) or {}
        _write_ledger(led)
        iid = led_rec.get("instance_id")
        if iid:
            try:
                cc.delete_instance(iid)
            except cc.ConnectionsError as e:
                log.warning("profiles: removed mailbox %s but its instance %s survives: %s",
                            address, iid, e)
            if cc.active() == iid:
                cc.select(None)
            import adapters
            adapters.forget(iid)
            payload = dict(payload)
            payload["connection_id"] = iid
        payload = dict(payload)
        payload["profile"] = pid
    return payload, code


def rotate_password(pid, new_password=None):
    """Rotate one profile's credential: the mailbox hash and the vault instance move together, or
    neither does. The backend cache is keyed on the credential's fingerprint, so the new password is
    in effect on the next op with no restart."""
    led = ledger()
    rec = led["profiles"].get(pid)
    if not rec:
        raise ProfileError("no such profile %r" % pid, 404)
    addr = rec.get("address") or address_of(pid)
    pw = new_password or mint_password()
    payload, code = mailboxes.set_password(addr, pw)
    if code != 200:
        return payload, code
    iid = rec.get("instance_id")
    if iid:
        if not cc.put_secret(iid, {"username": addr, "password": pw}):
            # The mailbox now has a password the vault does not know. Refusing to hide that is the
            # point: the reconciler's next pass sees an instance that cannot log in and rotates both.
            return {"error": "המייל עודכן אך לא ניתן היה לעדכן את הכספת — הפרופיל ייתוקן בריצה הבאה",
                    "address": addr, "connection_id": iid}, 502
        import adapters
        adapters.forget(iid)
    else:
        try:
            rec["instance_id"] = _mint_instance(addr, rec.get("display_name") or pid, pw)
            _write_ledger(led)
        except cc.ConnectionsError as e:
            return {"error": str(e), "address": addr}, 502
    return {"ok": True, "profile": pid, "address": addr,
            "connection_id": rec.get("instance_id")}, 200


def update_profile(pid, display_name=None, admin=None):
    """Rename, promote, demote. The same act as chat's and drive's PATCH /engine/profiles/<id>, and
    it carries the same rule: the LAST admin cannot demote itself, or profile management becomes
    unreachable with no way back in.

    Mail has no `status` — there is no suspend on a dovecot mailbox short of rotating its password
    out from under it, which is a different act with a different route. The route says so rather than
    accepting `status` and silently doing nothing, which is the failure this whole change is about."""
    led = ledger()
    rec = led["profiles"].get(pid)
    if not rec:
        raise ProfileError("no such profile %r" % pid, 404)
    if admin is not None and not bool(admin) and rec.get("admin"):
        _assert_not_last_admin(pid, demoting=True)
    if display_name is not None:
        name = str(display_name).strip()
        if not name:
            raise ProfileError("שם תצוגה ריק", 400)
        rec["display_name"] = name
    if admin is not None:
        rec["admin"] = bool(admin)
    _write_ledger(led)
    iid = rec.get("instance_id")
    if iid:
        # The admin flag is read on every guarded request through the cached backend's record, so a
        # demotion that only lands in the ledger would keep answering as an admin until the cache
        # aged out. Chat forgets its adapter for the same reason.
        import adapters
        adapters.forget(iid)
    return {"ok": True, "profile": _public(pid, rec)}, 200


def _public(pid, rec, declared_ids=None):
    """One profile as every surface sees it. `admin` and `is_admin` are BOTH emitted: mail's own UI
    reads `admin`, chat and drive settled on `is_admin`, and a profile screen that works against all
    three should not have to know which app it is talking to."""
    if declared_ids is None:
        declared_ids = {p["id"] for p in declared()}
    return {"id": pid, "address": rec.get("address"),
            "display_name": rec.get("display_name") or pid,
            "admin": bool(rec.get("admin")),
            "is_admin": bool(rec.get("admin")),
            "declared": pid in declared_ids,
            "source": rec.get("source") or "ui",
            "connection_id": rec.get("instance_id"),
            "created_at": rec.get("created_at")}


def listing():
    """The profile plane as the UI sees it. No credential ever appears here."""
    led = ledger()["profiles"]
    declared_ids = {p["id"] for p in declared()}
    out = []
    for pid, rec in entries():
        out.append({"id": pid, "address": rec.get("address"),
                    "display_name": rec.get("display_name") or pid,
                    "admin": bool(rec.get("admin")),
                    "is_admin": bool(rec.get("admin")),
                    "declared": pid in declared_ids,
                    "source": rec.get("source") or "ui",
                    "connection_id": rec.get("instance_id"),
                    "created_at": rec.get("created_at")})
    return {"engine": PROTOCOL, "domain": MAIL_DOMAIN, "profiles": out,
            "declared": declared(), "count": len(led), "bootstrap": dict(_state)}


# ── bootstrap ──────────────────────────────────────────────────────────────────
_RETRY_FAST_S = float(os.environ.get("MAIL_PROFILE_RETRY_S", "10"))
_RETRY_SLOW_S = 300.0
_started = False


def _run_once():
    """Returns True only when the pass is TRULY complete — no exception AND nothing deferred to
    the vault being unreachable. Either failure mode must keep the boot loop retrying; conflating
    "ran without raising" with "done" was the bug (see reconcile()'s docstring)."""
    with _lock:
        _state["runs"] += 1
        _state["last_run"] = int(time.time())
        try:
            acts, vault_deferred = reconcile()
        except Exception as e:                              # noqa: BLE001 — never raise into a boot
            _state["ok"] = False
            _state["error"] = "%s: %s" % (type(e).__name__, e)
            log.warning("profiles: reconcile pass failed (%s) — will retry", _state["error"])
            return False
        _state["ok"] = not vault_deferred
        _state["error"] = "" if not vault_deferred else "connections unreachable — will retry"
        _state["actions"] = acts
        for a in acts:
            log.warning("profiles: %s", a)
        if not acts:
            log.info("profiles: nothing to do — every declared profile already has its mailbox "
                     "and its connection")
        elif vault_deferred:
            log.warning("profiles: pass ran without error but deferred %d item(s) to the vault — "
                        "retrying, not stopping", sum(1 for a in acts if "connections unreachable" in a
                                                       or "cannot verify" in a))
        return not vault_deferred


def start():
    """Run passes in the background until one succeeds. Called once, at import.

    OFF the request path and off the boot path on purpose. mailapi declares no depends_on for
    mailboxd or connections, so on a cold `bbox run` either may still be starting — and a mail
    service that will not come up because the vault is slow is a worse outage than one that has no
    accounts for twenty seconds. The first attempt is immediate (no initial sleep), so in the normal
    case profiles exist before anything asks."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def loop():
        started = time.time()
        while True:
            if _run_once():
                return
            time.sleep(_RETRY_FAST_S if time.time() - started < 600 else _RETRY_SLOW_S)

    t = threading.Thread(target=loop, name="mail-profile-reconcile", daemon=True)
    t.start()


def run_now():
    """Force a pass and return what it did — the operator's 'try again', and what makes idempotence
    provable: run it twice and the second answer is an empty action list."""
    ok = _run_once()
    return {"ok": ok, "actions": list(_state["actions"]) if ok else [],
            "error": _state["error"], "runs": _state["runs"]}
