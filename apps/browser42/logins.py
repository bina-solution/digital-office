#!/usr/bin/env python3
"""browser42 logins — one login, two stores, always the same in both.

THE PROBLEM THIS SOLVES
    The office browser is where the owner signs in to things, so Chrome's password manager is where
    credentials actually land — and the credential plane (חיבורים ומפתחות) is where the office's
    secrets live, where they are backed up, where the agent can use one without seeing it, and where
    they survive a profile wipe. Until 2026-09-28 those two stores knew nothing about each other: a
    password saved in Chrome reached nothing, and a password stored in the plane never appeared in the
    browser's autofill. Both are wrong from the owner's seat, and "which store is this one in" is not
    a question he should ever have to ask.

THE MODEL (decided, not implied — the design is this paragraph)
    * The credential plane is the SOURCE OF TRUTH. Chrome's manager is a MIRROR kept for the human:
      it is what gives native autofill in /view, and it is disposable — it can be wiped, rebuilt or
      moved without the office losing a password.
    * Every login is `{origin, username, password}`. The ORIGIN is the key that ties the two sides
      together: Chrome stores rows by origin (`https://www.facebook.com/`), and a plane credential
      declares its URL either through the `app: {url}` block the connections screen already renders
      (`n8n-owner` → `N8N_BASE_URL`) or through a `*_URL` companion field. No per-site table exists
      anywhere: a new site is a new credential, not a code change.
    * Both directions run on every sync:
        - MATERIALIZE  plane → Chrome, so Chrome autofills the login.
        - HARVEST      Chrome → plane, so what he saves in the browser becomes a credential of its
                       own (a multi-field custom one) without anyone typing it twice.
    * CONFLICTS are resolved by "which side moved since the last sync", not by guessing. Both values
      are fingerprinted (HMAC, never the value) in /data/browser-logins.json:
         plane changed only   → Chrome is updated
         Chrome changed only  → the plane is updated (he typed it in the browser — that is intent)
         both / unclear       → Chrome wins, and the entry is reported so a surprise is visible
         equal                → nothing happens (the common case, silent on purpose)
      Without that state file "sync" means "last writer wins", which quietly reverts whichever side
      the human edited second — the failure mode that makes people stop trusting a sync.
    * DELETION is asymmetric on purpose. Removing a credential from the plane removes its row from
      Chrome — but only rows this bridge wrote, tracked in the state file. Removing a row from Chrome
      never deletes an office credential: a browser-side spring-clean must not be able to destroy the
      copy the office depends on.

CRYPTO (why this is short)
    The container has no keyring, so Chromium falls back to its **basic** store: the key is DERIVED
    rather than stored — PBKDF2-HMAC-SHA1(password=b"peanuts", salt=b"saltysalt", 1 iteration,
    16 bytes) — and each value is `v10` + AES-128-CBC with a 16-space IV. `os_crypt.encrypted_key` in
    `Local State` is what a keyring-backed profile has, and its ABSENCE is the signal that this scheme
    applies; when it is present this script refuses rather than writing something Chrome cannot read.
    The AES itself is `openssl enc`, already in the image.

    ⚠ Stated plainly, because it is a property of this design: with the basic store, anything running
    in this container can read the saved passwords, and so can a copy of the profile. That is why the
    profile volume is treated as a credential store (snapshot + backup coverage) and why
    `bbox b42 state dump` encrypts whatever leaves the machine. A real keyring (gnome-keyring + a
    session bus + `--password-store=gnome-libsecret`) is possible and is the next hardening step; it
    trades this simplicity for a daemon to supervise and a new way for passwords to look "missing".

WHAT IS NEVER PRINTED
    A password. Not on success, not on failure, not in a diff, and not in the state file. Output
    carries sites, origins, username LENGTHS and decisions.

USAGE (host wrapper: ./bbox b42 logins <verb> [args])
    list                 what Chrome holds (origins + username lengths; passwords never read)
    sources              what the plane offers, and how each entry maps to an origin
    sync                 both directions, with the conflict rules above
    materialize          plane → Chrome only
    harvest              Chrome → plane only
    export <site>        force one named site's Chrome login into its declared catalog row
    sessions [--json]    which services this browser is SIGNED IN TO right now (cookie names and
                         expiries only — never a value), including the sessions that have no password
    await <service|host> [seconds]
                         the human handoff, measured: wait until a live session for that service
                         exists and say what proved it. Exit 0 = connected, 2 = it did not happen
                         inside the budget. This is what makes "I signed in on the phone" a
                         measurement instead of an assumption.
    run-queued           what start-browser.sh calls at boot; same as sync
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROFILE = os.environ.get("BROWSER42_PROFILE", "/profile/__default__")
LOGIN_DB = os.path.join(PROFILE, "Default", "Login Data")
LOCAL_STATE = os.path.join(PROFILE, "Local State")
DATA = os.environ.get("BROWSER42_DATA", "/data")
STATE_FILE = os.path.join(DATA, "browser-logins.json")
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
CREDENTIAL_PREFIX = "browser42-login-"
CUSTOM_PREFIX = "browser-login-"
#: How long `await` waits for a person before it reports that it did not happen, and how often it
#: looks. Five minutes of polling every two seconds is a sign-in with a 2FA code on a phone; the
#: caller can say otherwise as the second argument.
DEFAULT_AWAIT_SECONDS = 300
POLL_SECONDS = 2
# Named sites get a DECLARED catalog row (visible in the app store's own catalog, with a probe and a
# wizard). Anything else lands as a custom credential — same screen, same labelled fields, no edit to
# any app.json. The named path exists for the site the office ships support for out of the box.
SITES = {"facebook": {"origin": "https://www.facebook.com/"}}
_WEBKIT_EPOCH_OFFSET_US = 11644473600 * 1_000_000
_SECRET_FIELD = re.compile(r"(PASSWORD|_PW$|_PASS$)")
_USER_FIELD = re.compile(r"(USER|USERNAME|EMAIL)")
_URL_FIELD = re.compile(r"(URL|HOST)$")


# ── output ──────────────────────────────────────────────────────────────────────────────────────

def fail(code: str, message: str) -> None:
    print(json.dumps({"ok": False, "error": {"code": code, "message": message}}, ensure_ascii=False))
    sys.exit(2)


def out(**fields) -> None:
    print(json.dumps({"ok": True, **fields}, ensure_ascii=False, sort_keys=True))


def note(message: str) -> None:
    print(f"[logins] {message}", file=sys.stderr)


# ── Chrome's store ──────────────────────────────────────────────────────────────────────────────

def basic_store_key() -> bytes:
    """The derived key, or a refusal naming what is actually there — see the module docstring."""
    try:
        with open(LOCAL_STATE, encoding="utf-8", errors="replace") as handle:
            state = json.load(handle)
    except OSError:
        fail("profile_not_found",
             f"no Local State at {LOCAL_STATE} — is this the office browser's profile?")
    except json.JSONDecodeError as error:
        fail("profile_unreadable", f"Local State is not valid JSON ({error})")
    if (state.get("os_crypt") or {}).get("encrypted_key"):
        fail("keyring_backed_store",
             "this profile keeps its password key in a keyring (os_crypt.encrypted_key is present), "
             "which this bridge deliberately does not decrypt — it handles the container's "
             "keyring-less 'basic' store only")
    return hashlib.pbkdf2_hmac("sha1", b"peanuts", b"saltysalt", 1, 16)


def _openssl(args: list, blob: bytes) -> bytes:
    done = subprocess.run(["openssl", "enc", *args, "-aes-128-cbc", "-K", basic_store_key().hex(),
                           "-iv", (" " * 16).encode().hex()], input=blob, capture_output=True)
    if done.returncode != 0:
        fail("crypto_failed", done.stderr.decode(errors="replace").strip()[:300])
    return done.stdout


def _login_db_copy() -> str:
    if not os.path.exists(LOGIN_DB):
        fail("no_login_db", f"{LOGIN_DB} does not exist — this profile has never saved a password")
    tmp = tempfile.mkdtemp(prefix="b42logins-")
    target = os.path.join(tmp, "Login Data")
    shutil.copy(LOGIN_DB, target)
    for suffix in ("-journal", "-wal", "-shm"):
        if os.path.exists(LOGIN_DB + suffix):
            shutil.copy(LOGIN_DB + suffix, target + suffix)
    return target


def normalize_origin(url: str) -> str:
    """`https://host/path?x=1` -> `https://host` — scheme + host, as typed."""
    match = re.match(r"^(https?://[^/]+)", (url or "").strip())
    return (match.group(1) if match else (url or "").strip()).rstrip("/")


def browser_origin(url: str) -> str:
    """The origin THE OFFICE BROWSER uses — which is not always the URL the plane stores.

    Measured 2026-09-29, and it is the whole reason a saved n8n password was not offered: the plane
    holds the OWNER's door, `http://n8n.localhost:8080` (that is what `N8N_BASE_URL` is for — his Mac
    reaches the edge on 8080), while inside this container the same app is reached through
    `localhost-forward.py`, which serves loopback :80 and proxies to traefik. Chrome addressed the
    page as `http://n8n.localhost/signin`, and Chromium matches saved logins by ORIGIN — scheme, host
    and PORT — so a row filed under `:8080` is a row for a different site and is never offered.

    So every `*.localhost` URL is reduced to its portless form: that is the only shape this browser
    can navigate to, and therefore the only shape its password manager will ever match. Everything
    else (the public internet, `https://www.facebook.com`) is left exactly as it is.
    """
    match = re.match(r"^(https?)://([^/:]+)(?::(\d+))?(?:/|$)", (url or "").strip())
    if not match:
        return normalize_origin(url)
    scheme, host, port = match.group(1), match.group(2), match.group(3)
    if host == "localhost" or host.endswith(".localhost"):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}" + (f":{port}" if port else "")


def chrome_rows() -> dict:
    """{origin: {username, password, modified}} — every saved login, decrypted."""
    db = sqlite3.connect(_login_db_copy())
    rows = db.execute("select origin_url, username_value, password_value, date_password_modified "
                      "from logins where blacklisted_by_user = 0").fetchall()
    out_rows = {}
    for origin_url, username, blob, modified in rows:
        blob = blob or b""
        if not blob or blob[:3] != b"v10":
            continue                        # never guess at an encoding we do not recognise
        origin = browser_origin(origin_url)
        password = _openssl(["-d"], blob[3:]).decode("utf-8", errors="replace")
        previous = out_rows.get(origin)
        if previous is None or (modified or 0) >= (previous["modified"] or 0):
            out_rows[origin] = {"username": username or "", "password": password,
                                "modified": modified or 0, "raw": normalize_origin(origin_url)}
    return out_rows


def chrome_raw_origins() -> list:
    """Every origin_url Chrome holds, as written — the input to the stale-variant cleanup."""
    db = sqlite3.connect(_login_db_copy())
    return [row[0] for row in db.execute("select origin_url from logins").fetchall()]


def chrome_put(origin: str, username: str, password: str) -> str:
    """Write/replace Chrome's saved login for `origin`, in Chrome's own encoding and schema.

    ⚠ `signon_realm` carries the TRAILING SLASH (`http://n8n.localhost/`), because that is what
    Chromium itself writes: it is the serialised origin (`GURL::Serialize()` of a URL with an empty
    path always ends in `/`), and password lookup matches on it. Rows written without it were stored,
    listed, and never offered — measured 2026-09-29, and it is the second half of the same bug as the
    `:8080` mismatch: the row has to be filed under the exact identity Chrome will look it up by.
    """
    blob = b"v10" + _openssl([], password.encode())
    now = int(time.time() * 1_000_000) + _WEBKIT_EPOCH_OFFSET_US
    url = origin if origin.endswith("/") else origin + "/"
    try:
        db = sqlite3.connect(LOGIN_DB, timeout=8)
        db.execute("delete from logins where origin_url = ? or signon_realm = ?", (url, origin))
        db.execute(
            "insert into logins (origin_url, action_url, username_element, username_value, "
            "password_element, password_value, submit_element, signon_realm, date_created, "
            "blacklisted_by_user, scheme, password_type, times_used, date_last_used, "
            "date_password_modified) "
            "values (?, '', '', ?, '', ?, '', ?, ?, 0, 0, 0, 0, ?, ?)",
            (url, username, blob, url, now, now, now))
        db.commit()
        db.close()
    except sqlite3.OperationalError as error:
        print(json.dumps({"ok": False, "error": {
            "code": "db_locked",
            "message": f"Chrome holds {LOGIN_DB} open ({error}) — a sync needs the browser stopped "
                       f"for a moment; the host wrapper does that automatically"}},
            ensure_ascii=False))
        sys.exit(3)
    return origin


def chrome_delete(origin: str) -> None:
    try:
        db = sqlite3.connect(LOGIN_DB, timeout=8)
        db.execute("delete from logins where origin_url = ? or signon_realm = ?",
                   (origin, origin.rstrip("/")))
        db.commit()
        db.close()
    except sqlite3.OperationalError:
        pass


# ── the credential plane ────────────────────────────────────────────────────────────────────────

def _call(path: str, data: dict | None = None):
    body = json.dumps(data).encode() if data is not None else None
    request = Request(CONNECTIONS_URL + path, data=body,
                      headers={"Content-Type": "application/json"},
                      method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode())
    except HTTPError as error:
        fail("credentials_refused",
             f"{path} -> {error.code} {error.read().decode(errors='replace')[:300]}")
    except URLError as error:
        fail("credentials_unreachable", f"cannot reach {CONNECTIONS_URL}: {error.reason}")


def plane_entries() -> dict:
    """{origin: {cid, username, password, url}} — every login the plane can describe.

    Discovery is by METADATA, not by a list of known sites: a credential qualifies when it declares a
    URL (its `app.url`, resolved live from the deployment's own environment, or a `*_URL` companion
    field) and carries a password field. That is what lets `n8n-owner` and the facebook row be
    handled by the same code as the site he adds next month.
    """
    entries: dict = {}
    listing = _call("/api/connections")
    rows = listing if isinstance(listing, list) else (listing.get("connections") or [])
    for row in rows:
        cid = str(row.get("id") or row.get("credential") or "")
        if not cid:
            continue
        detail = _call(f"/api/cred/{cid}")
        fields = {f["key"]: f for f in (detail.get("fields") or [])}
        app = detail.get("app") or {}
        url = (app.get("url") or "").strip()
        if not url:
            for key, field in fields.items():
                if _URL_FIELD.search(key) and field.get("clear"):
                    candidate = str(field["clear"]).strip()
                    if candidate.lower().startswith(("http://", "https://")):
                        url = candidate
                        break
        origin = browser_origin(url)
        if not origin.startswith(("http://", "https://")) or origin.count("://") != 1:
            continue
        password_field = next((k for k, f in fields.items()
                               if f.get("secret") and _SECRET_FIELD.search(k)), None)
        if not password_field:
            continue
        username = (app.get("user") or "").strip()
        if not username:
            for key, field in fields.items():
                if not field.get("secret") and _USER_FIELD.search(key) and field.get("clear"):
                    username = str(field["clear"]).strip()
                    break
        password = (_call(f"/api/reveal/{cid}", {"field": password_field}) or {}).get("value")
        if not password:
            continue
        entries[origin] = {"cid": cid, "username": username, "password": password, "url": url}
    return entries


def plane_write(cid: str, field: str | None, value: str) -> None:
    _call(f"/api/set/{cid}", {"value": value, **({"field": field} if field else {})})


def plane_create_custom(origin: str, username: str, password: str) -> str:
    """Give a Chrome-only login a home in the plane: a multi-field custom credential.

    The id is derived from the origin, so two syncs cannot create two rows for one site, and the env
    names are derived from the id, so the connections screen labels the three fields in Hebrew like
    any other credential (שם משתמש / סיסמה / כתובת) and edits them through the ordinary routes.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", origin.split("://", 1)[-1].lower()).strip("-")
    cid = CUSTOM_PREFIX + slug
    prefix = "BROWSER_LOGIN_" + slug.replace("-", "_").upper()
    url = origin + "/"
    _call("/api/add", {
        "id": cid, "value": password, "kind": "password",
        "title": f"כניסה ל-{origin.split('://')[-1]}",
        "env": prefix + "_PASSWORD", "envs_extra": [prefix + "_USER", prefix + "_URL"],
        "wizard": "נשמר אוטומטית מהדפדפן של הלשכה; אפשר לערוך כאן בכל רגע",
        "now": f"נוסף אוטומטית מהסיסמאות השמורות בכרום של הלשכה ({origin})",
    })
    plane_write(cid, prefix + "_USER", username)
    plane_write(cid, prefix + "_URL", url)
    return cid


# ── sync state: fingerprints only, never values ─────────────────────────────────────────────────

def load_state() -> dict:
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            state = json.load(handle)
        if isinstance(state, dict) and state.get("key"):
            return state
    except (OSError, json.JSONDecodeError):
        pass
    return {"key": hashlib.sha256(os.urandom(32)).hexdigest(), "entries": {}}


def save_state(state: dict) -> None:
    directory = os.path.dirname(STATE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=1, sort_keys=True)


def fingerprint(state: dict, value: str) -> str:
    """HMAC, so the state file holds no value and no bare hash of one."""
    return hmac.new(bytes.fromhex(state["key"]), (value or "").encode(),
                    hashlib.sha256).hexdigest()[:32]


# ── signed in, not just "a password exists" ─────────────────────────────────────────────────────
#
# Chrome's password store answers "is there a PASSWORD for this site", and that is not the question
# this browser is ever asked. It is the office's SHARED browser: what matters is which services it
# is SIGned IN TO — and the two facts disagree in both directions. A saved password outlives the
# session it was saved for (a logged-out browser still holds it), and a live session often has no
# password at all: an SSO sign-in, a QR pairing, a device token. Measured 2026-10-14 (DGO-575/
# DGO-567): the profile held 6 saved logins, all of them `.localhost`, while the only real sessions
# in it were claude.ai, GitHub's `logged_in` flag (no session) and the office's own SSO.
#
# So the answer is read from the cookie jar — NAME-ONLY. A cookie's name and expiry say "there is a
# live session for this host" while none of its value leaves the container, which is the same rule
# the rest of this module keeps for passwords.
#
# A service whose session is NOT a cookie says so instead of claiming "not connected": WhatsApp Web
# keeps its session in IndexedDB (DGO-573), and a wrong "no" is worse than a "not a cookie" — it
# sends the owner to redo a sign-in that already worked.
COOKIE_DB = os.path.join(PROFILE, "Default", "Cookies")
# In UTC, explicitly: a naive 1601-01-01 is read in the container's LOCAL time, and bbox hands every
# container the host's zone — in Israel 1601 is local mean time, +2:25:12, so every "is this cookie
# still live" was off by 8,712 seconds (test_now_is_in_this_century, red on any machine not in UTC).
_WEBKIT_EPOCH = datetime.datetime(1601, 1, 1, tzinfo=datetime.timezone.utc)

#: The cookie that exists only AFTER a real sign-in, per service. `spot` is the negative marker —
#: the one a service sets when it is showing you the sign-in/account chooser instead.
SERVICES = {
    "claude":    {"title": "Claude", "host": "claude.ai", "proof": ["sessionKey", "sessionKeyV3"]},
    "google":    {"title": "Google", "host": "google.com", "proof": ["SID", "__Secure-1PSID"],
                  "spot": ["__Host-GAPS", "ACCOUNT_CHOOSER"]},
    "github":    {"title": "GitHub", "host": "github.com", "proof": ["user_session"]},
    "facebook":  {"title": "Facebook", "host": "facebook.com", "proof": ["c_user"]},
    "instagram": {"title": "Instagram", "host": "instagram.com", "proof": ["sessionid"]},
    "x":         {"title": "X", "host": "x.com", "proof": ["auth_token"]},
    "linkedin":  {"title": "LinkedIn", "host": "linkedin.com", "proof": ["li_at"]},
    "slack":     {"title": "Slack", "host": "slack.com", "proof": ["d"]},
    "whatsapp":  {"title": "WhatsApp", "host": "web.whatsapp.com", "proof": [],
                  # Paired 2026-10-14, and this jar still cannot see it: the session is IndexedDB.
                  # The answer lives on the page — `bbox b42 await <slug> 'storage:last-wid-md'`
                  # (or `selector:#pane-side`) — which is what DGO-573 added and what `task await`
                  # /`bbox b42 await` are for.
                  "note": "session is IndexedDB, not a cookie — measure it on the page: "
                          "bbox b42 await <slug> 'storage:last-wid-md' (DGO-573)"},
}

#: Name fragments that mark a cookie as a SESSION rather than a preference. Used only for the hosts
#: no service row covers, so a new site shows up as "something is signed in here" without a code
#: change — the same reason no per-site table governs the password side. The lookbehind is
#: load-bearing: without it "_uetsid" (a Bing tracker) matches `sid` and every ad cookie reads as a
#: session — measured on canva.com, 2026-10-14.
_SESSION_NAME = re.compile(r"(session|sessid|(?<![A-Za-z])sid|token|auth|login|jwt)", re.I)

#: …and what matches one of those fragments WITHOUT being a session. The words are deliberately
#: narrow and named: `authentik_csrf` is a protection token, not an identity, and it is what made a
#: logged-OUT office host read as signed in (the test file pins it). A CSRF/anti-bot name is never
#: an answer to "is this browser signed in".
_NOT_A_SESSION = re.compile(r"(csrf|xsrf|anti.?bot|recaptcha|_uetsid|g_state|__cf)", re.I)


def _looks_like_a_session(name: str) -> bool:
    return bool(_SESSION_NAME.search(name)) and not _NOT_A_SESSION.search(name)


def _cookie_rows() -> list:
    """Every cookie in the profile, as (host, name, expires, persistent) — copied first.

    Chrome holds this database open, so it is read through a copy (the same reason `_login_db_copy`
    exists for the password store); a -wal sidecar is copied with it or a cookie written seconds ago
    is invisible.
    """
    if not os.path.exists(COOKIE_DB):
        fail("no_cookie_store", f"no cookie store at {COOKIE_DB} — is the browser profile there?")
    tmp = _copy_sqlite(COOKIE_DB)
    try:
        con = sqlite3.connect(tmp)
        try:
            return list(con.execute("SELECT host_key, name, expires_utc, is_persistent,"
                                    " last_update_utc FROM cookies"))
        finally:
            con.close()
    except sqlite3.DatabaseError as err:
        fail("cookie_store_unreadable", f"{COOKIE_DB}: {err}")
    finally:
        _drop_sqlite_copy(tmp)


def _copy_sqlite(path: str) -> str:
    handle, tmp = tempfile.mkstemp(suffix=".sqlite")
    os.close(handle)
    shutil.copy2(path, tmp)
    for sidecar in ("-wal", "-journal"):
        if os.path.exists(path + sidecar):
            shutil.copy2(path + sidecar, tmp + sidecar[1:])
    return tmp


def _drop_sqlite_copy(tmp: str) -> None:
    for leftover in (tmp, tmp + "wal", tmp + "journal"):
        try:
            os.unlink(leftover)
        except OSError:
            pass


def _when(webkit_utc: int) -> str:
    if not webkit_utc:
        return ""
    try:
        return (_WEBKIT_EPOCH + datetime.timedelta(microseconds=int(webkit_utc))).strftime("%Y-%m-%d %H:%M")
    except (ValueError, OverflowError):
        return ""


def _host_cookies(rows: list, host: str) -> list:
    """Cookies that apply to a host: its own, plus those set on a parent domain.

    `.claude.ai` and `claude.ai` are two rows for the same site, and a sign-in may put its cookie on
    either — asking for the exact host is how a session that IS there gets reported as missing.
    """
    return [r for r in rows if r[0].lstrip(".") == host or r[0].lstrip(".").endswith("." + host)]


def _now_us() -> int:
    """WebKit epoch (1601) microseconds — the unit both Chrome stores stamp rows in.

    The sign is load-bearing and was wrong on the first run: `_WEBKIT_EPOCH.timestamp()` is the
    UNIX timestamp OF 1601, i.e. a NEGATIVE number, so "now" is `time.time()` MINUS it. Adding it
    produced a "now" in the year 1657 and every expired cookie read as live — which is how a
    logged-out console row would have been reported as a live session.
    """
    return int((time.time() - _WEBKIT_EPOCH.timestamp()) * 1_000_000)


def _live(row: tuple, now_us: int) -> bool:
    _host, _name, expires, persistent, _updated = row
    if not persistent:
        return True                      # a session cookie lives exactly as long as the browser does
    return bool(expires) and int(expires) > now_us


def service_sessions(rows: list) -> list:
    """One row per KNOWN service: is there a live session, and which cookie proves it."""
    now_us = _now_us()
    report = []
    for key, spec in SERVICES.items():
        all_of = _host_cookies(rows, spec["host"])
        live = [r for r in all_of if _live(r, now_us)]
        names = {r[1] for r in live}
        proof = [p for p in spec["proof"] if p in names]
        row = {
            "service": key, "title": spec["title"], "host": spec["host"],
            "state": ("connected" if proof else
                      "not_connected" if spec["proof"] else "not_a_cookie"),
            "proof": proof,
            "spot": [s for s in spec.get("spot", []) if s in {r[1] for r in all_of}],
            "cookies": len({r[1] for r in all_of}),
            "last_update": max([_when(r[4]) for r in all_of] or [""]),
            "expires": max([_when(r[2]) for r in all_of if r[2]] or [""]),
        }
        if spec.get("note"):
            row["note"] = spec["note"]
        report.append(row)
    return report


def other_sessions(rows: list) -> list:
    """Hosts no service row covers that are holding something that looks like a session."""
    known = {s["host"] for s in SERVICES.values()}
    now_us = _now_us()
    hosts: dict = {}
    for row in rows:
        host, name = row[0].lstrip("."), row[1]
        if any(host == k or host.endswith("." + k) for k in known):
            continue
        if not _looks_like_a_session(name) or not _live(row, now_us):
            continue
        entry = hosts.setdefault(host, {"host": host, "cookies": [], "last_update": ""})
        entry["cookies"].append(name)
        entry["last_update"] = max(entry["last_update"], _when(row[4]))
    for entry in hosts.values():
        entry["cookies"] = sorted(set(entry["cookies"]))
    return sorted(hosts.values(), key=lambda e: e["last_update"], reverse=True)


def session_of(which: str, rows: list) -> dict:
    """One service by its short name, or any host typed as a host — the waiter takes both.

    A host the caller named has no declared proof cookie, so what comes back is what was MEASURED —
    a live session-looking cookie, or none — and the "none" is named `no_live_cookie`. Calling it
    `not_connected` would be a claim this module cannot make: measured 2026-10-14, Canva was signed
    in (through Google, and being edited in that browser) while holding no session cookie at all.
    """
    if which in SERVICES:
        return next(r for r in service_sessions(rows) if r["service"] == which)
    host = which.lstrip(".").lower()
    live = [r for r in _host_cookies(rows, host)
            if _looks_like_a_session(r[1]) and _live(r, _now_us())]
    return {"service": which, "title": which, "host": host,
            "state": "connected" if live else "no_live_cookie",
            "proof": sorted({r[1] for r in live}),
            "last_update": max([_when(r[4]) for r in _host_cookies(rows, host)] or [""])}


# ── verbs ───────────────────────────────────────────────────────────────────────────────────────

def cmd_list() -> None:
    rows = chrome_rows()
    out(verb="list", count=len(rows),
        logins=[{"origin": origin, "username_len": len(row["username"])}
                for origin, row in sorted(rows.items())])


def cmd_sources() -> None:
    entries = plane_entries()
    out(verb="sources", count=len(entries),
        logins=[{"origin": origin, "credential": entry["cid"], "username_len": len(entry["username"])}
                for origin, entry in sorted(entries.items())])


def cmd_export(site: str) -> None:
    """Force one named site's Chrome login into its DECLARED catalog row (the pre-sync path)."""
    entry = SITES.get(site) or fail("unknown_site",
                                    f"'{site}' is not a named site (known: {', '.join(sorted(SITES))})")
    # `chrome_rows` is keyed by NORMALISED origin (no trailing slash); the SITES table is written the
    # way a URL is typed. Comparing them raw missed every site — the first run of this verb reported
    # "Chrome holds no saved login for https://www.facebook.com/" against a store that was holding
    # exactly that, which is how the harvest went on to create a second credential for the same site.
    origin = browser_origin(entry["origin"])
    rows = chrome_rows()
    if origin not in rows:
        fail("site_not_in_chrome", f"Chrome holds no saved login for {origin}")
    row = rows[origin]
    cid = CREDENTIAL_PREFIX + site
    prefix = "BROWSER42_LOGIN_" + site.upper()
    plane_write(cid, None, row["password"])
    if row["username"]:
        plane_write(cid, prefix + "_USER", row["username"])
    plane_write(cid, prefix + "_URL", origin + "/")
    out(verb="export", site=site, origin=origin, connection=cid, username_len=len(row["username"]),
        password_len=len(row["password"]))


def cmd_sync(materialize: bool = True, harvest: bool = True) -> None:
    """Both directions, with the conflict rules from the module docstring."""
    state = load_state()
    report = {"to_chrome": [], "to_plane": [], "created": [], "deleted": [], "skipped": []}
    rows = chrome_rows()
    entries = plane_entries()

    if materialize:
        for origin, entry in entries.items():
            row = rows.get(origin)
            known = state["entries"].get(origin) or {}
            plane_fp = fingerprint(state, entry["password"])
            chrome_fp = fingerprint(state, row["password"]) if row else None
            # "Already identical" has to mean identical INCLUDING the stored URL, otherwise a row
            # filed under `:8080` is left in place forever while Chromium refuses to match it.
            if row and row["password"] == entry["password"] and row["username"] == entry["username"] \
                    and row.get("raw") == origin + "/":
                state["entries"][origin] = {"plane": plane_fp, "chrome": plane_fp}
                continue
            if row and known.get("chrome") and chrome_fp != known["chrome"] \
                    and plane_fp == known.get("plane"):
                # Only Chrome moved since the last sync — harvest owns this one.
                report["skipped"].append(origin)
                continue
            if row and known.get("chrome") and known.get("plane") \
                    and chrome_fp != known["chrome"] and plane_fp != known["plane"]:
                report["to_plane"].append(origin)      # both moved: Chrome wins, and we say so
                plane_write(entry["cid"], None, row["password"])
                state["entries"][origin] = {"plane": fingerprint(state, row["password"]),
                                            "chrome": fingerprint(state, row["password"])}
                continue
            chrome_put(origin, entry["username"], entry["password"])
            report["to_chrome"].append(origin)
            state["entries"][origin] = {"plane": plane_fp, "chrome": plane_fp}
        # Rows filed under a variant this browser cannot address (the old `:8080` rows) are dead
        # weight: Chromium will never match them, and leaving them means two rows per site forever.
        # Compare NORMALISED forms: a plain trailing slash (`https://www.facebook.com/`) is the same
        # origin, not a variant — only a dropped PORT makes a row unreachable by this browser.
        for raw in chrome_raw_origins():
            if normalize_origin(raw) != browser_origin(raw) and browser_origin(raw) in entries:
                chrome_delete(raw)
                report.setdefault("migrated", []).append(raw)

    if harvest:
        for origin, row in rows.items():
            if origin in entries:
                continue
            cid = plane_create_custom(origin, row["username"], row["password"])
            report["created"].append({"origin": origin, "credential": cid})
            state["entries"][origin] = {"plane": fingerprint(state, row["password"]),
                                        "chrome": fingerprint(state, row["password"])}

    # A credential deleted in the plane must not linger in Chrome — but only rows this bridge wrote.
    for origin in list(state["entries"]):
        if origin in entries or origin in rows:
            continue
        chrome_delete(origin)
        report["deleted"].append(origin)
        del state["entries"][origin]

    save_state(state)
    out(verb="sync", plane_logins=len(entries), chrome_logins=len(rows), **report)


def cmd_run_queued() -> None:
    """start-browser.sh calls this BEFORE Chrome starts — the only moment the store is unheld."""
    try:
        cmd_sync()
    except SystemExit as exit_code:                     # a refusal must never stop the browser
        note(f"sync skipped at boot ({exit_code.code})")


def cmd_sessions() -> None:
    rows = _cookie_rows()
    services = service_sessions(rows)
    out(verb="sessions", count=len(services), connected=[s["service"] for s in services
                                                         if s["state"] == "connected"],
        services=services, hosts=other_sessions(rows))


def cmd_await(which: str, seconds: str) -> None:
    """Wait for the owner to finish a sign-in, and report what PROVED it — never that it "should" be
    done. The profile's cookie jar is the source: it is written by Chrome itself, it survives the
    page moving on, and it is the same fact `sessions` reports before and after."""
    if not which:
        fail("usage", "await needs a service or a host, e.g. `bbox b42 logins await google`")
    try:
        budget = float(seconds) if seconds else DEFAULT_AWAIT_SECONDS
    except ValueError:
        fail("usage", f"'{seconds}' is not a number of seconds")
    started = time.time()
    deadline = started + max(1.0, budget)
    last = None
    while True:
        last = session_of(which, _cookie_rows())
        if last["state"] == "connected":
            out(verb="await", target=which, state="connected", proof=last.get("proof", []),
                waited_s=round(time.time() - started, 1), detail=last)
            return
        if last["state"] == "not_a_cookie":
            # Waiting would be waiting for something this check can never see. Say which, now.
            fail("not_a_cookie", f"{which}: {last.get('note') or 'its session is not a cookie'} — "
                                 f"a cookie jar cannot report it")
        if time.time() >= deadline:
            fail("not_connected", f"{which}: no live session after {round(time.time() - started)}s "
                                  f"({last['state']}; last cookie activity "
                                  f"{last.get('last_update') or 'never'})")
        note(f"{which}: {last['state']} — still waiting "
             f"({round(time.time() - started)}s of {round(budget)}s)")
        time.sleep(POLL_SECONDS)


def main() -> None:
    verb = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    arg2 = sys.argv[3] if len(sys.argv) > 3 else ""
    if verb == "list":
        cmd_list()
    elif verb == "sources":
        cmd_sources()
    elif verb == "sessions":
        cmd_sessions()
    elif verb == "await":
        cmd_await(arg, arg2)
    elif verb == "sync":
        cmd_sync()
    elif verb == "materialize":
        cmd_sync(materialize=True, harvest=False)
    elif verb == "harvest":
        cmd_sync(materialize=False, harvest=True)
    elif verb == "export":
        cmd_export(arg or fail("usage", "export needs a site, e.g. `bbox b42 logins export facebook`"))
    elif verb in ("run-queued", "sync-at-boot"):
        cmd_run_queued()
    else:
        fail("usage", "verbs: list | sources | sessions | await <service|host> [seconds] | sync | "
                      "materialize | harvest | export <site> | run-queued")


if __name__ == "__main__":
    main()
