"""dgo-cloud.accounts — DGO net's own accounts: e-mail + password, or Google; sessions; one-time links; view-as.

Examplex's way (apps/examplex/accounts.py), for the same reason: the buyers of DGO cloud are not the office's users.
  - a password is scrypt (PBKDF2 where hashlib has no scrypt); a wrong e-mail costs the same time as a wrong password
  - a session is a random token in an httpOnly cookie; only its SHA-256 is kept, so a copy of the database signs no one
    in. 30 days, renewed while used; ended by sign-out, a disabled account or a new password
  - a one-time link (verify the e-mail: 3 days; a new password: 2 hours) is kept as a hash and used once
  - Google: the authorization-code flow, server side; only a VERIFIED Google e-mail is believed, and it joins the
    account that already has that e-mail (Google proved the mailbox, which a sign-up never did)
  - VIEW AS: an admin sees the client's screens exactly as the client does; every write is refused meanwhile; 60
    minutes; audited
Nothing here knows HTTP: server.py asks, this answers or raises Refused.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import smtplib
import socket
import threading
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr

from store import Refused, NotFound, now, later, parse

SESSION_DAYS = 30
VERIFY_HOURS = 72
RESET_HOURS = 2
VIEW_MINUTES = 60
EMAIL_RX = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s]{2,24}$")
COMMON = {"12345678", "123456789", "1234567890", "password", "password1", "qwerty123", "11111111", "00000000",
          "abcd1234", "1q2w3e4r", "iloveyou", "admin123", "shalom123", "israel123", "dgo12345", "dgocloud"}
_HASHING = threading.BoundedSemaphore(int(os.environ.get("DGOCLOUD_HASH_SLOTS", "2")))


def sha(token):
    return hashlib.sha256(token.encode()).hexdigest()


def line(v, n=200):
    return re.sub(r"[\r\n\t\x00]+", " ", str(v or "")).strip()[:n]


def hash_password(pw):
    salt = secrets.token_bytes(16)
    with _HASHING:
        if hasattr(hashlib, "scrypt"):
            h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
            return f"scrypt$16384$8$1${salt.hex()}${h.hex()}"
        h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, 310000)
        return f"pbkdf2$310000${salt.hex()}${h.hex()}"


def check_password(pw, stored):
    try:
        parts = (stored or "").split("$")
        with _HASHING:
            if parts[0] == "scrypt" and hasattr(hashlib, "scrypt"):
                _, n, r, p, salt, want = parts
                if (n, r, p) != ("16384", "8", "1"):
                    return False
                got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1,
                                     maxmem=64 * 1024 * 1024, dklen=32)
            elif parts[0] == "pbkdf2":
                _, it, salt, want = parts
                if it != "310000":
                    return False
                got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), 310000)
            else:
                return False
        return hmac.compare_digest(got.hex(), want)
    except (ValueError, TypeError):
        return False


_DUMMY = hash_password(secrets.token_urlsafe(12))


def check_new_password(pw):
    if not isinstance(pw, str) or len(pw) < 8:
        raise Refused("הסיסמה צריכה להיות לפחות 8 תווים.")
    if len(pw) > 200:
        raise Refused("הסיסמה ארוכה מדי.")
    if pw.lower() in COMMON or len(set(pw)) < 4:
        raise Refused("הסיסמה הזאת נפוצה מדי — בחרו אחרת.")


def norm_email(e):
    e = line(e, 254).lower()
    if not EMAIL_RX.match(e):
        raise Refused("כתובת המייל לא תקינה.")
    return e


#: sign-in throttle — per e-mail and per address, in memory (a restart forgets, which is fine for a throttle)
_TRIES = {}
_TRIES_LOCK = threading.Lock()


def throttle(key, limit=8, window=900):
    import time
    t = time.time()
    with _TRIES_LOCK:
        lst = [x for x in _TRIES.get(key, []) if t - x < window]
        if len(lst) >= limit:
            raise Refused("יותר מדי ניסיונות — נסו שוב בעוד כמה דקות.")
        lst.append(t)
        _TRIES[key] = lst


class Accounts:
    def __init__(self, store):
        self.s = store

    # ── people ───────────────────────────────────────────────────────────────────────────────────────
    def get(self, aid):
        a = self.s.one("SELECT * FROM accounts WHERE id=?", aid)
        if not a:
            raise NotFound("אין חשבון כזה")
        return a

    def public(self, a):
        return {"id": a["id"], "email": a["email"], "name": a["name"], "phone": a.get("phone", ""),
                "company": a.get("company", ""), "tax_id": a.get("tax_id", ""), "admin": bool(a["admin"]),
                "proven": bool(a["proven"]), "google": bool(a.get("google_sub")), "status": a["status"],
                "created_at": a["created_at"], "has_password": bool(a.get("pw"))}

    def signup(self, email, name, pw, ip=""):
        email = norm_email(email)
        name = line(name, 120)
        if not name:
            raise Refused("איך לקרוא לך? חסר שם.")
        check_new_password(pw)
        throttle("signup:" + ip, limit=10, window=3600)
        if self.s.one("SELECT id FROM accounts WHERE email=?", email):
            raise Refused("כבר יש חשבון עם המייל הזה — היכנסו, או «שכחתי סיסמה».")
        h = hash_password(pw)
        with self.s.tx() as c:
            # never admin at sign-up, whatever the address: a sign-up proves nothing about who reads the mail, and
            # whoever signed an admin's address up first would hold the whole service (the second reader's #3).
            # Admin comes with PROOF: the verify link, a reset link, or Google (grant_admin_if_named).
            aid = c.execute("INSERT INTO accounts(email,name,pw,status,admin,created_at,last_ip) VALUES (?,?,?,?,?,?,?)",
                            (email, name, h, "active", 0, now(), ip)).lastrowid
            self.s.audit(f"a:{aid}", "account.signup", f"a:{aid}", {"email": email}, ip, c)
        return self.get(aid)

    def login(self, email, pw, ip=""):
        email = line(email, 254).lower()
        throttle("login:" + email)
        throttle("login-ip:" + ip, limit=30)
        a = self.s.one("SELECT * FROM accounts WHERE email=?", email)
        ok = check_password(pw or "", a["pw"] if a and a.get("pw") else _DUMMY)
        if not a or not ok:
            raise Refused("המייל או הסיסמה לא נכונים.")
        if a["status"] != "active":
            raise Refused("החשבון הזה מושבת. פנו אלינו: person11@example.com")
        return a

    def google_account(self, info, ip=""):
        """Google answered with a verified e-mail: the account that has it, or a new one (proven)."""
        email = norm_email(info.get("email"))
        if not info.get("email_verified"):
            raise Refused("Google לא אישר את כתובת המייל הזאת.")
        sub = line(info.get("sub"), 64)
        a = self.s.one("SELECT * FROM accounts WHERE google_sub=?", sub) or \
            self.s.one("SELECT * FROM accounts WHERE email=?", email)
        with self.s.tx() as c:
            if a:
                if a["status"] != "active":
                    raise Refused("החשבון הזה מושבת. פנו אלינו: person11@example.com")
                if not a["proven"]:
                    # Google proves THIS person owns the mailbox; whoever signed the address up with a password before
                    # never did — their password and every session they opened end here (pre-account takeover)
                    c.execute("UPDATE accounts SET pw='' WHERE id=?", (a["id"],))
                    c.execute("DELETE FROM sessions WHERE account_id=?", (a["id"],))
                c.execute("UPDATE accounts SET google_sub=?, proven=1, name=CASE WHEN name='' THEN ? ELSE name END "
                          "WHERE id=?", (sub, line(info.get("name"), 120), a["id"]))
                self.s.audit(f"a:{a['id']}", "account.google", f"a:{a['id']}", {"was_proven": bool(a["proven"])}, ip, c)
                aid = a["id"]
            else:
                aid = c.execute("INSERT INTO accounts(email,name,google_sub,status,admin,proven,created_at,last_ip) "
                                "VALUES (?,?,?,?,?,?,?,?)", (email, line(info.get("name"), 120) or email.split("@")[0],
                                                             sub, "active", 0, 1, now(), ip)).lastrowid
                self.s.audit(f"a:{aid}", "account.signup", f"a:{aid}", {"email": email, "via": "google"}, ip, c)
            grant_admin_if_named(self.s, aid, c)
        return self.get(aid)

    def update(self, aid, fields):
        allowed = {"name": 120, "phone": 40, "company": 120, "tax_id": 20}
        sets = {k: line(v, allowed[k]) for k, v in (fields or {}).items() if k in allowed}
        if "name" in sets and not sets["name"]:
            raise Refused("השם לא יכול להיות ריק.")
        if "tax_id" in sets and sets["tax_id"] and not re.fullmatch(r"\d{5,9}", sets["tax_id"]):
            raise Refused("מספר עוסק / ח.פ. הוא 5 עד 9 ספרות.")
        if sets:
            with self.s.tx() as c:
                c.execute(f"UPDATE accounts SET {', '.join(k + '=?' for k in sets)} WHERE id=?", (*sets.values(), aid))
                self.s.audit(f"a:{aid}", "account.update", f"a:{aid}", sets, "", c)
        return self.get(aid)

    def set_password(self, aid, pw, keep_session=None):
        check_new_password(pw)
        h = hash_password(pw)
        with self.s.tx() as c:
            c.execute("UPDATE accounts SET pw=? WHERE id=?", (h, aid))
            c.execute("DELETE FROM sessions WHERE account_id=? AND hash<>?", (aid, keep_session or ""))
            self.s.audit(f"a:{aid}", "account.password", f"a:{aid}", {}, "", c)

    # ── sessions ─────────────────────────────────────────────────────────────────────────────────────
    def open_session(self, aid, ip="", ua=""):
        tok = secrets.token_urlsafe(32)
        with self.s.tx() as c:
            c.execute("INSERT INTO sessions(hash,account_id,created_at,expires_at,seen_at,ip,ua) VALUES (?,?,?,?,?,?,?)",
                      (sha(tok), aid, now(), later(days=SESSION_DAYS), now(), ip, line(ua, 200)))
            c.execute("UPDATE accounts SET last_seen=?, last_ip=? WHERE id=?", (now(), ip, aid))
        return tok

    def by_session(self, tok):
        if not tok:
            return None
        h = sha(tok)
        r = self.s.one("SELECT s.*, a.status FROM sessions s JOIN accounts a ON a.id=s.account_id WHERE s.hash=?", h)
        if not r or r["status"] != "active":
            return None
        exp = parse(r["expires_at"])
        from store import dt as _dt
        n = _dt.datetime.now(_dt.timezone.utc)
        if not exp or exp <= n:
            self.s.run("DELETE FROM sessions WHERE hash=?", h)
            return None
        seen = parse(r["seen_at"])
        if not seen or (n - seen).total_seconds() > 3600:      # renewed while used, written at most once an hour
            self.s.run("UPDATE sessions SET seen_at=?, expires_at=? WHERE hash=?", now(), later(days=SESSION_DAYS), h)
        return {"account_id": r["account_id"], "hash": h}

    def close_session(self, tok):
        if tok:
            self.s.run("DELETE FROM sessions WHERE hash=?", sha(tok))
        self.s.run("DELETE FROM viewing WHERE until < ?", now())

    # ── one-time links ───────────────────────────────────────────────────────────────────────────────
    def link(self, aid, purpose):
        hours = VERIFY_HOURS if purpose == "verify" else RESET_HOURS
        tok = secrets.token_urlsafe(32)
        with self.s.tx() as c:
            c.execute("UPDATE tokens SET used_at=? WHERE account_id=? AND purpose=? AND used_at IS NULL",
                      (now(), aid, purpose))
            c.execute("INSERT INTO tokens(hash,account_id,purpose,created_at,expires_at) VALUES (?,?,?,?,?)",
                      (sha(tok), aid, purpose, now(), later(hours=hours)))
        return tok

    def use_link(self, tok, purpose):
        r = self.s.one("SELECT * FROM tokens WHERE hash=? AND purpose=?", sha(tok or ""), purpose)
        if not r or r["used_at"]:
            raise Refused("הקישור כבר שומש או לא קיים. אפשר לבקש חדש.")
        exp = parse(r["expires_at"])
        from store import dt as _dt
        if not exp or exp <= _dt.datetime.now(_dt.timezone.utc):
            raise Refused("פג תוקף הקישור. אפשר לבקש חדש.")
        with self.s.tx() as c:
            c.execute("UPDATE tokens SET used_at=? WHERE hash=?", (now(), r["hash"]))
            c.execute("UPDATE accounts SET proven=1 WHERE id=?", (r["account_id"],))
            grant_admin_if_named(self.s, r["account_id"], c)
        return self.get(r["account_id"])

    # ── view as ──────────────────────────────────────────────────────────────────────────────────────
    def view(self, admin_id, target_id):
        if admin_id == target_id:
            raise Refused("זה כבר החשבון שלך.")
        self.get(target_id)
        self.s.run("INSERT INTO viewing(actor,target,since,until) VALUES (?,?,?,?) ON CONFLICT(actor) DO UPDATE SET "
                   "target=excluded.target, since=excluded.since, until=excluded.until",
                   admin_id, target_id, now(), later(minutes=VIEW_MINUTES))
        self.s.audit(f"a:{admin_id}", "admin.view_as", f"a:{target_id}")

    def viewing(self, admin_id):
        r = self.s.one("SELECT * FROM viewing WHERE actor=? AND until > ?", admin_id, now())
        return r["target"] if r else None

    def stop_view(self, admin_id):
        r = self.s.one("SELECT * FROM viewing WHERE actor=?", admin_id)
        self.s.run("DELETE FROM viewing WHERE actor=?", admin_id)
        if r:
            self.s.audit(f"a:{admin_id}", "admin.view_as.end", f"a:{r['target']}")


def admin_emails():
    return {e.strip().lower() for e in os.environ.get("DGOCLOUD_ADMINS", "").split(",") if e.strip()}


def grant_admin_if_named(store, aid, c):
    """A PROVEN account whose address DGOCLOUD_ADMINS names becomes an admin (inside the caller's transaction)."""
    r = c.execute("SELECT email, proven, admin FROM accounts WHERE id=?", (aid,)).fetchone()
    if r and r["proven"] and not r["admin"] and r["email"].lower() in admin_emails():
        c.execute("UPDATE accounts SET admin=1 WHERE id=?", (aid,))
        store.audit("config", "account.admin.granted", f"a:{aid}", {"by": "DGOCLOUD_ADMINS"}, "", c)


# ── Google sign-in (the authorization-code flow; the secret never leaves this server) ────────────────────
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO = "https://openidconnect.googleapis.com/v1/userinfo"


def google_configured():
    return bool(os.environ.get("GOOGLE_OAUTH_CLIENT_ID") and os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET"))


def google_url(redirect_uri, state):
    q = {"client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""), "redirect_uri": redirect_uri,
         "response_type": "code", "scope": "openid email profile", "state": state, "prompt": "select_account",
         "access_type": "online"}
    return GOOGLE_AUTH + "?" + urllib.parse.urlencode(q)


def google_exchange(code, redirect_uri):
    body = urllib.parse.urlencode({"code": code, "client_id": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
                                   "client_secret": os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
                                   "redirect_uri": redirect_uri, "grant_type": "authorization_code"}).encode()
    try:
        r = urllib.request.urlopen(urllib.request.Request(GOOGLE_TOKEN, data=body, method="POST"), timeout=15)
        tok = json.load(r)
        u = urllib.request.urlopen(urllib.request.Request(
            GOOGLE_USERINFO, headers={"Authorization": "Bearer " + tok["access_token"]}), timeout=15)
        return json.load(u)
    except (OSError, ValueError, KeyError) as e:
        raise Refused("הכניסה עם Google לא הצליחה. נסו שוב, או היכנסו עם מייל וסיסמה.") from e


# ── mail ─────────────────────────────────────────────────────────────────────────────────────────────────
def esc(s):
    return (str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def send_mail(to, subject, lead, link="", cta="", foot=""):
    """True when the office's mail server took it. Never raises: a link the page can show is shown there too."""
    host = os.environ.get("DGOCLOUD_SMTP_HOST", "mailserver")
    if not host or host == "off":
        return False
    sender = os.environ.get("DGOCLOUD_MAIL_FROM", "person12@example.com")
    plain = f"{lead}\n\n" + (f"{cta}: {link}\n\n" if link else "") + (f"{foot}\n\n" if foot else "") + \
        "DGO Cloud — הלשכה הדיגיטלית"
    html = (f'<div dir="rtl" style="font-family:Arial,sans-serif;font-size:15px;line-height:1.6">'
            f"<p>{esc(lead)}</p>" + (f'<p><a href="{esc(link)}" style="font-weight:bold">{esc(cta)}</a></p>'
                                     if link else "") +
            (f'<p style="font-size:13px">{esc(foot)}</p>' if foot else "") +
            '<p style="font-size:13px">DGO Cloud — הלשכה הדיגיטלית</p></div>')
    try:
        msg = EmailMessage()
        msg["From"] = formataddr(("DGO Cloud", sender))
        msg["To"] = line(to, 254)
        msg["Subject"] = line(subject, 200)
        msg.set_content(plain)
        msg.add_alternative(html, subtype="html")
        with smtplib.SMTP(host, int(os.environ.get("DGOCLOUD_SMTP_PORT", "25")), timeout=10) as s:
            s.send_message(msg)
        return True
    except (OSError, ValueError, TypeError, smtplib.SMTPException, socket.timeout):
        return False
