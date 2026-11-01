#!/usr/bin/env python3
"""mailboxd — the ONLY process allowed to write the mail server's account file.

Adding a mailbox is one line in `postfix-accounts.cf`:

    person114@example.com|{SHA512-CRYPT}$6$…

and that is the whole of "a new person in this company gets an address" — no DNS, no certificate,
no restart, because the company's domain records already exist (ai/context/mail-multi-tenant.md).
The question this service exists to answer is not *how* to write that line. It is **who** may.

── why this is a separate container and not four routes in mailapi ───────────────────────────────
`mailapi` mounts the same volume READ-ONLY today (`mail_config:/mailconfig:ro`) so the setup
checker can read the PUBLIC half of the DKIM key. Making that mount read-write would have been one
character of diff, and it is the wrong character. That volume is not "the accounts file"; it is the
mail server's entire configuration:

    opendkim/keys/<domain>/<selector>.private   the signing key — the one secret that, leaked,
                                                lets anyone send mail AS this company
    postfix-main.cf / postfix-master.cf         arbitrary Postfix configuration, i.e. arbitrary
                                                commands via a transport definition
    dovecot.cf, postfix-virtual.cf, aliases     where every incoming message is routed

`mailapi` is the wrong process to hold that. It is browser-facing (an authentik-gated host of its
own), it parses untrusted input from three directions — RFC822 from the internet, IMAP from remote
providers, OAuth callbacks — and it renders a UI. A path-traversal or SSRF bug anywhere in those
thousands of lines becomes "read the DKIM private key" or "append a Postfix transport" the moment
it can write here.

So the privilege is separated by MOUNT, not by discipline:

    mailapi    mail_config:/mailconfig:ro     reads exactly one file (<selector>.txt, public)
    mailboxd   mail_config:/cfg               writes exactly one file, and cannot be reached
                                              from outside the compose network at all

This process has no traefik labels, no published port, no authentication of its own and needs
none: nothing outside the docker network can address it. It never accepts a path, a filename or a
shell fragment from its caller — the only file it will ever open is `$MAILBOXD_CFG/postfix-accounts.cf`,
composed here from a constant. Its whole vocabulary is list / create / delete, and every mutation
is validated against the ONE domain this deployment serves before it touches disk.

── why it runs the mailserver image ──────────────────────────────────────────────────────────────
The password hash must come from the very Dovecot that will verify it — `mailserver-init` already
learned this, and generating the hash with anything else is how you get an account that exists and
cannot log in. So this runs `mailserver/docker-mailserver:15.0.2` (already pulled for the MTA — no
extra image, no extra build) and shells out to its own `doveadm pw -s SHA512-CRYPT`. That image
ships python 3.11, so the server itself is stdlib-only: no pip install, no requirements file, and
nothing to keep in step with mailapi's dependency set.

The alternative was python's `crypt.crypt(pw, mksalt(METHOD_SHA512))`, which produces a
byte-compatible `$6$` string today and was removed from the standard library in python 3.13 — a
dependency on a deleted module, to reimplement a binary sitting in the same image.

── why no restart is needed ──────────────────────────────────────────────────────────────────────
docker-mailserver watches its config directory (`check-for-changes.sh`) and regenerates the Postfix
and Dovecot maps when a file changes. Appending a line is therefore live within seconds. That is
what makes step 3 of onboarding — "add users from the UI" — true rather than "add users and then
redeploy".
"""
import json
import os
import re
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

CFG = os.environ.get("MAILBOXD_CFG", "/cfg")
# Composed from a constant, never from the request. There is no code path in this file that can be
# made to open a different file, which is the property that makes the read-write mount acceptable.
ACCOUNTS = os.path.join(CFG, "postfix-accounts.cf")
MAILDIR_ROOT = os.environ.get("MAILBOXD_MAILDIR_ROOT", "/var/mail")
PORT = int(os.environ.get("MAILBOXD_PORT", "8971"))

MAIL_DOMAIN = (os.environ.get("MAIL_DOMAIN") or "local.test").strip().lower()
# The account mailapi itself authenticates as. It is not a mailbox like the others: deleting it
# does not remove a person, it disconnects the mail application from its own server.
#
# H6 (2026-08-05): this used to fall back to a hardcoded "admin" when LOCALMAIL_USER was unset or
# empty. mailapi's own read of the SAME variable (apps/mail/mailapi/local_app.py) falls back to
# "indox" instead — so on a deployment that left LOCALMAIL_USER unset, this guard silently
# protected an address ("admin@…") that was never provisioned, while the account mailapi actually
# logs in as ("indox@…") had NO guard at all. Guessing a fallback here is exactly the wrong
# instinct for a guard whose only job is "never delete the live mailbox" — a wrong guess is worse
# than no guess, because it looks like protection while providing none. So: no guess. If the
# deployment did not say who the primary is, PRIMARY is unknown and every delete is refused until
# it does — see `delete_mailbox` below.
_primary_raw = (os.environ.get("LOCALMAIL_USER") or "").strip().lower()
PRIMARY = (_primary_raw if "@" in _primary_raw else "%s@%s" % (_primary_raw, MAIL_DOMAIN)) \
    if _primary_raw else None

# RFC 5321 allows far more than this in a local part. We allow far less, deliberately: these
# addresses are typed by a person into a web form and then read back by another person off a
# business card, and `"weird\ name"@…` is a support call rather than a feature. Lowercase because
# Dovecot's lookup is case-sensitive on the stored form while humans are not — accepting `User2`
# would create a mailbox that never receives the mail addressed to `user2`.
LOCAL_RE = re.compile(r"^[a-z0-9](?:[a-z0-9._-]{0,61}[a-z0-9])?$")
MIN_PW = 8
# What a refusal SAYS is read by a person: mailapi and mailview forward `error` word for word, and
# the mail's screen shows it. So it is a sentence in the office's language — an address, a domain
# and a setting's name stand in it as they are — and each is written once (test_refusals.py).
SHORT_PW = "הסיסמה קצרה מדי — לפחות %d תווים" % MIN_PW
NO_SUCH = "אין תיבה כזאת"
HASH_FAILED = "הצפנת הסיסמה נכשלה"

_lock = threading.Lock()


# ── the accounts file ─────────────────────────────────────────────────────────
def _read_lines():
    try:
        with open(ACCOUNTS, encoding="utf-8", errors="replace") as fh:
            return fh.read().splitlines()
    except FileNotFoundError:
        return []


def _entries():
    """[(address, hash)] in file order. Malformed lines are skipped, never rewritten — this file is
    also written by mailserver-init and, historically, by hand, and silently dropping a line we did
    not understand would delete somebody's mailbox."""
    out = []
    for ln in _read_lines():
        s = ln.strip()
        if not s or s.startswith("#") or "|" not in s:
            continue
        addr, _, h = s.partition("|")
        out.append((addr.strip().lower(), h))
    return out


def _write_lines(lines):
    """Replace the file atomically, preserving its mode.

    Not `open(...,'a')`: a partial write here is not a lost feature, it is a mail server that
    cannot parse its own account list, i.e. every mailbox on this deployment stops resolving at
    once. Same-directory temp + os.replace so the rename is atomic on the volume, and fsync before
    it so the content is on disk before the name points at it."""
    tmp = ACCOUNTS + ".mailboxd.tmp"
    mode = None
    try:
        mode = os.stat(ACCOUNTS).st_mode & 0o777
    except OSError:
        pass
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + ("\n" if lines else ""))
        fh.flush()
        os.fsync(fh.fileno())
    if mode is not None:
        os.chmod(tmp, mode)
    os.replace(tmp, ACCOUNTS)
    # fsync the DIRECTORY too, so the rename itself survives a hard power loss.
    fd = os.open(CFG, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _maildir(address):
    """Where docker-mailserver keeps this mailbox's mail: /var/mail/<domain>/<local>/."""
    local, _, dom = address.partition("@")
    return os.path.join(MAILDIR_ROOT, dom, local)


def _dir_bytes(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


def _hash(password):
    """The hash, from the Dovecot that will verify it. See the module docstring."""
    p = subprocess.run(["doveadm", "pw", "-s", "SHA512-CRYPT", "-p", password],
                       capture_output=True, text=True, timeout=30)
    if p.returncode != 0 or not p.stdout.strip():
        raise RuntimeError("doveadm pw failed: %s" % (p.stderr or "").strip()[:200])
    return p.stdout.strip()


# ── operations ────────────────────────────────────────────────────────────────
def list_mailboxes():
    out = []
    for addr, _h in _entries():
        md = _maildir(addr)
        exists = os.path.isdir(md)
        out.append({
            "address": addr,
            "local": addr.split("@")[0],
            "domain": addr.split("@")[-1],
            "primary": addr == PRIMARY,
            # Whether mail has ever been delivered here. A brand-new mailbox has no maildir until
            # its first message, which is normal and must not read as "broken".
            "maildir": md,
            "maildir_exists": exists,
            "size_bytes": _dir_bytes(md) if exists else 0,
        })
    return {"domain": MAIL_DOMAIN, "primary": PRIMARY, "mailboxes": out, "count": len(out)}


def create_mailbox(body):
    local = (body.get("local") or "").strip().lower()
    address = (body.get("address") or "").strip().lower()
    if address and not local:
        local, _, dom = address.partition("@")
        # A mailbox on another domain would be accepted here and then never receive anything: MX
        # points at this machine for exactly one domain. Refusing is the honest answer; creating it
        # would produce an address that looks live on the screen and is a black hole in the world.
        if dom and dom != MAIL_DOMAIN:
            return {"error": "הדומיין %s אינו של השרת הזה — תיבות נוצרות כאן רק ב-%s" % (dom, MAIL_DOMAIN)}, 400
    if not LOCAL_RE.match(local):
        return {"error": "שם תיבה לא תקין — אותיות לטיניות קטנות, ספרות, נקודה, מקף וקו תחתון; "
                         "בקצוות אות או ספרה"}, 400
    pw = body.get("password") or ""
    if len(pw) < MIN_PW:
        return {"error": SHORT_PW, "min": MIN_PW}, 400
    addr = "%s@%s" % (local, MAIL_DOMAIN)
    with _lock:
        lines = _read_lines()
        if any(a == addr for a, _h in _entries()):
            # Not an overwrite. Re-creating an existing address is indistinguishable, from here,
            # from "reset that person's password", and a create endpoint must not be a password
            # reset that anyone who can guess an address can call.
            return {"error": "התיבה כבר קיימת", "address": addr}, 409
        try:
            h = _hash(pw)
        except Exception as e:
            return {"error": HASH_FAILED, "detail": str(e)}, 500
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append("%s|%s" % (addr, h))
        _write_lines(lines)
    return {"ok": True, "address": addr, "maildir": _maildir(addr)}, 201


def set_password(address, body):
    """Replace ONE account's hash. The rotate primitive the engine reconciler needs.

    `create` deliberately refuses an address that already exists (a create endpoint that doubles as a
    password reset is a password reset anyone who can guess an address can call), so rotation needs a
    door of its own — and it needs one for a reason that is not convenience: the mailbox password IS
    the profile's credential, and the vault is the only place it is kept. If an instance is lost, the
    password is genuinely unrecoverable and the only way back to a working profile is to set a new
    one. Without this the answer would be "delete the mailbox and make another", i.e. break the
    address people already write to.

    Only the line for this address is rewritten; every other line is copied through byte-for-byte,
    including ones this service did not write and does not understand."""
    addr = (address or "").strip().lower()
    if "@" not in addr:
        addr = "%s@%s" % (addr, MAIL_DOMAIN)
    pw = (body or {}).get("password") or ""
    if len(pw) < MIN_PW:
        return {"error": SHORT_PW, "min": MIN_PW}, 400
    with _lock:
        if not any(a == addr for a, _h in _entries()):
            return {"error": NO_SUCH, "address": addr}, 404
        try:
            h = _hash(pw)
        except Exception as e:
            return {"error": HASH_FAILED, "detail": str(e)}, 500
        out, changed = [], False
        for ln in _read_lines():
            s = ln.strip()
            if s and "|" in s and s.partition("|")[0].strip().lower() == addr:
                out.append("%s|%s" % (addr, h))
                changed = True
                continue
            out.append(ln)
        if not changed:                      # cannot happen (checked above), but never write a
            return {"error": NO_SUCH, "address": addr}, 404             # file we did not change
        _write_lines(out)
    return {"ok": True, "address": addr}, 200


def delete_mailbox(address):
    addr = (address or "").strip().lower()
    if "@" not in addr:
        addr = "%s@%s" % (addr, MAIL_DOMAIN)
    if PRIMARY is None:
        # FAIL CLOSED: LOCALMAIL_USER is unset, so there is no reliable way to tell whether `addr`
        # IS the account mailapi authenticates as. Guessing (the old behaviour) meant the guard
        # protected whatever address it guessed — right or wrong — while looking like it was
        # working either way. Refusing every delete until the deployment says who the primary is
        # is the only version of this guard that cannot silently protect the wrong mailbox.
        return {"error": "לא נמחק — לא הוגדר מי התיבה הראשית (LOCALMAIL_USER), ולכן אי אפשר לוודא "
                         "שהמחיקה בטוחה",
                "address": addr,
                "hint": "מגדירים את LOCALMAIL_USER ב-.env ומנסים שוב"}, 409
    if addr == PRIMARY:
        return {"error": "התיבה הראשית אינה נמחקת",
                "address": addr,
                "hint": "זה החשבון שבו יישום הדואר מתחבר לשרת; כדי להעבירו משנים את "
                        "LOCALMAIL_USER ב-.env"}, 409
    with _lock:
        kept, removed = [], False
        for ln in _read_lines():
            s = ln.strip()
            if s and "|" in s and s.partition("|")[0].strip().lower() == addr:
                removed = True
                continue
            kept.append(ln)
        if not removed:
            return {"error": NO_SUCH, "address": addr}, 404
        _write_lines(kept)
    md = _maildir(addr)
    # THE MAIL IS NOT DELETED, and that is a decision, not an omission. Removing the account stops
    # delivery and stops login — which is what "remove this person" means — while the messages they
    # received stay on disk. A UI button that destroys years of a company's correspondence with no
    # way back is not a feature anyone asked for, and the operator can still remove the directory
    # deliberately. The response says exactly where it is so that choice is informed.
    return {"ok": True, "address": addr, "maildir": md,
            "maildir_kept": os.path.isdir(md),
            "size_bytes": _dir_bytes(md) if os.path.isdir(md) else 0}, 200


# ── HTTP ──────────────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return {}
        if n <= 0 or n > 1 << 16:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode("utf-8")) or {}
        except Exception:
            return {}

    def do_GET(self):
        p = urlparse(self.path).path.rstrip("/") or "/"
        if p in ("/healthz", "/"):
            return self._send({"status": "ok", "domain": MAIL_DOMAIN, "primary": PRIMARY,
                               "accounts_file": ACCOUNTS,
                               "accounts_present": os.path.isfile(ACCOUNTS)})
        if p == "/mailboxes":
            return self._send(list_mailboxes())
        self._send({"error": "not found"}, 404)

    def do_POST(self):
        p = urlparse(self.path).path.rstrip("/") or "/"
        if p == "/mailboxes":
            payload, code = create_mailbox(self._body())
            return self._send(payload, code)
        self._send({"error": "not found"}, 404)

    def do_PUT(self):
        p = urlparse(self.path).path.rstrip("/") or "/"
        # /mailboxes/<address>/password — the rotate primitive (see set_password).
        if p.startswith("/mailboxes/") and p.endswith("/password"):
            addr = unquote(p[len("/mailboxes/"):-len("/password")])
            payload, code = set_password(addr, self._body())
            return self._send(payload, code)
        self._send({"error": "not found"}, 404)

    def do_DELETE(self):
        p = urlparse(self.path).path
        if p.startswith("/mailboxes/"):
            payload, code = delete_mailbox(unquote(p[len("/mailboxes/"):]))
            return self._send(payload, code)
        self._send({"error": "not found"}, 404)

    def log_message(self, fmt, *args):
        # One line per request on stdout, so `docker logs` shows who asked for what. The default
        # implementation writes to stderr, which the compose json-file driver interleaves oddly.
        print("mailboxd %s - %s" % (self.address_string(), fmt % args), flush=True)


def main():
    os.makedirs(CFG, exist_ok=True)
    if not shutil.which("doveadm"):
        # Fail at START, not at the first create. A mailboxd that answers /healthz and cannot hash
        # a password is the exact shape of failure this whole file is written to avoid.
        raise SystemExit("mailboxd: doveadm not found — this must run the mailserver image")
    print("mailboxd: serving %s on :%d (domain %s, primary %s)"
          % (ACCOUNTS, PORT, MAIL_DOMAIN, PRIMARY), flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
