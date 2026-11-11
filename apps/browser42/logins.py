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
                       own (a multi-field custom one) without anyone typing it twice. A row with no
                       user name or no password is skipped and said in `skipped` as {origin, reason};
                       the rest are harvested (DGO-1490).
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
        - "the row this bridge wrote" is exact: origin + "/" and the user name it wrote (`wrote` in the
          state), as it wrote it; his own rows for the site are never deleted. Only sync and
          materialize delete; harvest never does.
        - a deleted credential does not come back: what Chrome still holds for that origin is kept out
          of harvest until it changes in Chrome after the deletion.
        - a plane answer that lists no credential while the state holds some decides nothing (no
          deletion, no harvest of those origins), and says so.
      Chrome-only changes are taken only from the entry's own account, never from another account
      Chrome holds for the same site, and never an empty password.

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

import atexit
import datetime
import fcntl
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
#: A credential deleted in the plane also deletes the Chrome row the bridge wrote for it — ONLY when an office opts in
#: (BROWSER42_LOGINS_DELETE=1). By default nothing in Chrome is ever deleted by the bridge: a credential also leaves
#: the plane's listing when its value stops resolving or the plane is restored from an older backup, and the Chrome
#: row was then the last copy (the bridge's fourth reader). The cost is a stale row in Chrome, said on every sync.
DELETE_IN_CHROME = os.environ.get("BROWSER42_LOGINS_DELETE") == "1"
#: …and even then a credential absent from two listings in a row is deleted only when its first absence is this old: a
#: wrapper that runs the sync twice in one command (offline, then at the browser's start) is not two looks (the fifth
#: reader).
MISSING_MIN_SECONDS = 3600
#: The id of a password kept aside (plane_keep_aside): `<custom id>-kept-<UTC second>[-n]` — exactly, so a real site
#: whose name has a `kept` in it (www.kept.co.il) is never taken for one (the sixth reader).
KEPT_ID = re.compile(r"^" + re.escape(CUSTOM_PREFIX) + r".+-kept-\d{14}(-\d)?$")
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


_COPIES: list = []                       # the copies of the password store this process made, removed when it ends


@atexit.register
def _drop_copies() -> None:
    for directory in _COPIES:
        shutil.rmtree(directory, ignore_errors=True)


def _login_db_copy() -> str:
    if not os.path.exists(LOGIN_DB):
        fail("no_login_db", f"{LOGIN_DB} does not exist — this profile has never saved a password")
    tmp = tempfile.mkdtemp(prefix="b42logins-")
    _COPIES.append(tmp)                    # a copy of every password: never left in /tmp (the fifth reader)
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


def chrome_account_rows() -> dict:
    """{(origin, username): {username, password, modified, raw}} — the newest row of EACH ACCOUNT per origin.

    chrome_rows answers «the newest row per origin», across accounts: a person who saves his personal account
    after the owner's made the owner's look gone, and a change he typed for the owner's account was then
    overwritten by the plane (the bridge's second reader). What the sync decides for a credential, it decides on
    that credential's own account."""
    db = sqlite3.connect(_login_db_copy())
    rows = db.execute("select origin_url, username_value, password_value, date_password_modified "
                      "from logins where blacklisted_by_user = 0").fetchall()
    out_rows = {}
    for origin_url, username, blob, modified in rows:
        blob = blob or b""
        if not blob or blob[:3] != b"v10":
            continue
        key = (browser_origin(origin_url), username or "")
        previous = out_rows.get(key)
        if previous is None or (modified or 0) >= (previous["modified"] or 0):
            out_rows[key] = {"username": username or "", "modified": modified or 0,
                             "password": _openssl(["-d"], blob[3:]).decode("utf-8", errors="replace"),
                             "raw": normalize_origin(origin_url)}
    return out_rows


def chrome_written_rows() -> dict:
    """{(origin_url, username): password} for every row filed as chrome_put files its own (origin_url ending in "/").

    chrome_rows answers «the newest row per origin», across accounts. The DELETION rule needs a different
    question: the password of the ONE row the bridge wrote (origin + "/", the user name it wrote), whichever
    account is newest there. A row is the bridge's only in chrome_put's own shape — its form's fields empty: a login
    he saved from a site's HOME page is filed under origin + "/" too, with the form's field names, and taking it for
    the bridge's made a vault deletion delete his only copy (the bridge's third reader)."""
    db = sqlite3.connect(_login_db_copy())
    found = {}
    for origin_url, username, blob in db.execute("select origin_url, username_value, password_value from logins "
                                                 "where blacklisted_by_user = 0 and origin_url like '%/' "
                                                 "and ifnull(action_url, '') = '' and ifnull(username_element, '') = '' "
                                                 "and ifnull(password_element, '') = ''"):
        blob = blob or b""
        if blob[:3] == b"v10":
            found[(origin_url, username or "")] = _openssl(["-d"], blob[3:]).decode("utf-8", errors="replace")
    return found


def chrome_raw_rows() -> list:
    """(origin_url, username) of every saved row (not a «never save» one), as written — the input to the
    stale-variant cleanup, which moves one account and never another."""
    db = sqlite3.connect(_login_db_copy())
    return [(row[0], row[1] or "") for row in db.execute("select origin_url, username_value from logins "
                                                         "where blacklisted_by_user = 0").fetchall()]


def chrome_delete_variant(raw: str, username: str) -> int:
    """Delete the rows of ONE account filed under an address variant this browser cannot use — that origin_url,
    that user name, never a «never save» row. Returns how many went (0: Chrome held the store, said by the caller)."""
    try:
        db = sqlite3.connect(LOGIN_DB, timeout=8)
        gone = db.execute("delete from logins where origin_url = ? and username_value = ? and blacklisted_by_user = 0",
                          (raw, username)).rowcount
        db.commit()
        db.close()
        return gone
    except sqlite3.OperationalError:
        return 0


def chrome_put(origin: str, username: str, password: str, same_account: tuple = ()) -> str:
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
        # the bridge's own row, AND a row Chrome saved itself for the SAME ACCOUNT (filed under the slashed
        # realm with the login page as origin_url): the plane's user name, or the one of the harvested row a
        # declared row now shadows (`same_account`). Another account Chrome holds for the origin exists
        # nowhere else and is never touched, nor a «never save» row (DGO-1488 and its second reader).
        # Only these accounts, wherever they are filed for the origin — the site's root included: Chromium files a
        # login whose form is on the home page under `origin/` too, and «every row at origin/» was his other
        # account with it (the bridge's second reader, on its rewrite).
        accounts = sorted({username, *same_account})
        db.execute("delete from logins where (origin_url = ? or signon_realm in (?, ?)) and blacklisted_by_user = 0"
                   " and username_value in (%s)" % ",".join("?" * len(accounts)),
                   (url, url.rstrip("/"), url, *accounts))
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


def chrome_delete_written(origin: str, username: str) -> int:
    """Delete the ONE row chrome_put wrote for `origin` and `username` — its exact identity, origin_url with the
    trailing slash and that user name — and nothing else: not his other accounts under the same realm, not a
    «never save» row. Returns how many rows went (0 when it was not there, or Chrome held the store), so a
    deletion that did not happen is never reported as one (the second reader of the first attempt)."""
    url = origin if origin.endswith("/") else origin + "/"
    try:
        db = sqlite3.connect(LOGIN_DB, timeout=8)
        gone = db.execute("delete from logins where origin_url = ? and username_value = ? and blacklisted_by_user = 0",
                          (url, username)).rowcount
        db.commit()
        db.close()
        return gone
    except sqlite3.OperationalError:
        return 0


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
        if KEPT_ID.search(cid):
            continue          # a password kept aside (plane_keep_aside) is a record, never a site's login (fifth reader)
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
        # A row an app DECLARES for an origin wins over one harvested from Chrome (`browser-login-*`) for the
        # same origin, whichever the listing gives last: a password Chrome once saved by hand must not hide
        # the row the app tells its owner to keep up to date (DGO-1488, the second reader of DGO-1473). The
        # shadowed row's user name rides along, so its Chrome copy is replaced (chrome_put `same_account`);
        # it is decided BEFORE a password is revealed, so a shadowed row's secret is never read for nothing.
        held = entries.get(origin)
        if held and cid.startswith(CUSTOM_PREFIX) and not held["cid"].startswith(CUSTOM_PREFIX):
            if username:
                held.setdefault("shadowed", []).append(username)
                held.setdefault("shadowed_cid", {})[username] = cid   # where its newest password is kept first
            continue
        password = (_call(f"/api/reveal/{cid}", {"field": password_field}) or {}).get("value")
        if not password:
            continue
        shadowed = list((held or {}).get("shadowed") or [])
        shadowed_cid = dict((held or {}).get("shadowed_cid") or {})
        if held and held["cid"].startswith(CUSTOM_PREFIX) and held.get("username"):
            shadowed.append(held["username"])
            shadowed_cid[held["username"]] = held["cid"]
        # where a password from Chrome is written: the field it was read from — None when that is the primary value
        # (/api/set's default); a companion by its name. The primary was written always, and a credential whose
        # password is a companion had its main value (an API key) overwritten (the fifth reader).
        write_field = None if fields[password_field].get("primary") else password_field
        entries[origin] = {"cid": cid, "username": username, "password": password, "url": url,
                           "password_field": write_field,
                           **({"shadowed": shadowed, "shadowed_cid": shadowed_cid} if shadowed else {})}
    return entries


def plane_secret(cid: str) -> str | None:
    """The password field of one credential, or None when it cannot be read."""
    try:
        detail = _call(f"/api/cred/{cid}")
        field = next((f["key"] for f in (detail.get("fields") or [])
                      if f.get("secret") and _SECRET_FIELD.search(f.get("key") or "")), None)
        return (_call(f"/api/reveal/{cid}", {"field": field}) or {}).get("value") if field else None
    except SystemExit:                                       # _call's fail(): not a reason to end the sync here
        return None


def plane_write(cid: str, field: str | None, value: str) -> None:
    _call(f"/api/set/{cid}", {"value": value, **({"field": field} if field else {})})


class PlaneIdTaken(Exception):
    """The id a harvested login would take is already a credential of the plane's: nothing is written."""


def custom_id(origin: str) -> tuple[str, str]:
    """(credential id, env prefix) of a harvested login: the host, its port, and its scheme when that is not https —
    `http://shop.test` and `https://shop.test` are two sites, and one id for both overwrote one with the other (the
    bridge's fourth reader). An https site keeps the id it always had."""
    scheme, _, rest = origin.partition("://")
    slug = re.sub(r"[^a-z0-9]+", "-", rest.lower()).strip("-")
    if scheme.lower() != "https":
        slug = f"{scheme.lower()}-{slug}"
    return CUSTOM_PREFIX + slug, "BROWSER_LOGIN_" + slug.replace("-", "_").upper()


def plane_exists(cid: str) -> bool:
    """Is `cid` a credential of the plane already? An answer that is not a clear «no» counts as yes."""
    request = Request(CONNECTIONS_URL + f"/api/cred/{cid}", method="GET")
    try:
        with urlopen(request, timeout=20):
            return True
    except HTTPError as error:
        return error.code != 404
    except URLError:
        return True


def plane_keep_aside(origin: str, username: str, password: str, source: str = "chrome") -> str | None:
    """A password the bridge is about to replace, kept in the plane first as a credential of its own
    (`…-kept-<when>`): Chrome's (`source="chrome"`, a row that was the only copy — a credential that came back after a
    deletion, an account Chrome saved by hand, a newer password a restored vault would overwrite) or the plane's own
    (`source="plane"`, when Chrome's newer one goes over it). The id carries the second, and an id that exists is
    never written over. Returns the id, or None when nothing could be kept (then nothing is replaced). Once the
    credential exists the password IS kept: its user name and address are written after it, best effort — an empty
    user name is not written at all (the plane refuses one, and the kept copy was said to fail and made again on every
    sync — the fifth reader)."""
    base, env_base = custom_id(origin)
    stamp = time.strftime("%Y%m%d%H%M%S", time.gmtime())
    where = "מהכרום" if source == "chrome" else "מהכספת"
    instead = "בסיסמה מהכספת" if source == "chrome" else "בסיסמה מהכרום"
    # two kept in one second (two syncs back to back, the real-Chromium run) take the next free id — never one taken
    for n in range(1, 10):
        tail = stamp if n == 1 else f"{stamp}-{n}"
        cid, prefix = f"{base}-kept-{tail}", f"{env_base}_KEPT_{tail.replace('-', '_')}"
        try:
            if not plane_exists(cid):
                break
        except SystemExit:
            return None
    else:
        return None
    try:
        _call("/api/add", {
            "id": cid, "value": password, "kind": "password",
            "title": f"כניסה ל-{origin.split('://')[-1]} — נשמרה {where} לפני החלפה",
            "env": prefix + "_PASSWORD", "envs_extra": [prefix + "_USER", prefix + "_URL"],
            "wizard": f"הסיסמה שהייתה {where.replace('מה', 'ב', 1)} לפני שהגשר החליף אותה; אפשר למחוק אחרי שבדקת",
            "now": f"נשמרה {where} ({origin}) לפני שהוחלפה {instead}",
        })
    except SystemExit:                                    # _call's fail(): not kept, so nothing is replaced
        return None
    for field, value in ((prefix + "_USER", username), (prefix + "_URL", origin + "/")):
        if not value:
            continue
        try:
            plane_write(cid, field, value)
        except SystemExit:
            note(f"kept {cid}, but its {field.rsplit('_', 1)[-1].lower()} field could not be written")
    return cid


ALREADY_KEPT = "already kept"


def keep_once(state: dict, origin: str, username: str, password: str, source: str = "chrome") -> str | None:
    """plane_keep_aside, once per password: what was kept is remembered by its fingerprint (the state's `kept`, per
    origin, the last 20) and the state is saved AT ONCE — a sync that stops after the copy (the store held by Chrome)
    and the offline sync the wrapper runs next keep a password once, not twice (the sixth reader). ALREADY_KEPT when it
    was kept before; the id; or None when it could not be kept (then nothing is replaced)."""
    fp = fingerprint(state, password)
    held = state.setdefault("kept", {}).setdefault(origin, [])
    if fp in held:
        return ALREADY_KEPT
    cid = plane_keep_aside(origin, username, password, source=source)
    if cid:
        held.append(fp)
        del held[:-20]
        save_state(state)
    return cid


def plane_create_custom(origin: str, username: str, password: str) -> str:
    """Give a Chrome-only login a home in the plane: a multi-field custom credential.

    The id is derived from the origin, so two syncs cannot create two rows for one site, and the env
    names are derived from the id, so the connections screen labels the three fields in Hebrew like
    any other credential (שם משתמש / סיסמה / כתובת) and edits them through the ordinary routes.
    """
    cid, prefix = custom_id(origin)
    url = origin + "/"
    if plane_exists(cid):
        # /api/add has no check of its own: it would overwrite whatever holds this id — another site's password
        # (http and https of one host had one id; the bridge's fourth reader). Never: the row stays in Chrome.
        raise PlaneIdTaken(cid)
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
    """The sync's memory. No file is a first run. A file that cannot be read is NOT a first run: starting fresh would
    take every credential for new (the plane overwriting what he typed in Chrome) and forget every deletion marker (a
    deleted credential harvested back) — the bridge's third reader. The sync stops instead, and says so."""
    try:
        with open(STATE_FILE, encoding="utf-8") as handle:
            state = json.load(handle)
    except FileNotFoundError:
        return {"key": hashlib.sha256(os.urandom(32)).hexdigest(), "entries": {}}
    except (OSError, json.JSONDecodeError) as error:
        fail("state_unreadable", f"{STATE_FILE} cannot be read ({error}); nothing is synced until it is fixed or "
                                 f"removed by a person — a fresh state would take every login for new")
    if not (isinstance(state, dict) and state.get("key") and isinstance(state.get("entries"), dict)):
        fail("state_unreadable", f"{STATE_FILE} is not the sync's state; nothing is synced until a person looks")
    return state


def save_state(state: dict) -> None:
    """Whole or not at all: a temporary file, flushed to the disk, then renamed over the old one."""
    directory = os.path.dirname(STATE_FILE) or "."
    os.makedirs(directory, exist_ok=True)
    # a name of its own (two writers never share one temporary file — the fifth reader), beside the state, renamed
    fd, tmp = tempfile.mkstemp(prefix=".logins-state-", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, indent=1, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, STATE_FILE)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def sync_lock() -> None:
    """One sync at a time: the boot sync, a `bbox b42 logins sync` and a retried one never read and write the state
    and the two stores together (the fifth reader). Held until the process ends; a second asks and is refused."""
    if _LOCKS:
        return                             # this process holds it already (a verb that syncs twice)
    try:
        os.makedirs(os.path.dirname(STATE_FILE) or ".", exist_ok=True)
        handle = open(STATE_FILE + ".lock", "a")
    except OSError as error:               # no place for the lock: the state cannot be written either, and says so
        note(f"no lock beside the sync's state ({error.strerror})")
        return
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        handle.close()
        fail("sync_running", "another sync of the logins is running now; nothing was done — ask again in a moment")
    except OSError as error:               # a mount that takes no locks (ENOLCK): said, and the sync goes on unlocked
        handle.close()
        note(f"the sync's lock cannot be taken here ({error.strerror}): it runs unlocked")
        return
    _LOCKS.append(handle)


_LOCKS: list = []


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


def _shadowed_safe(origin: str, entry: dict, own: dict, report: dict) -> tuple:
    """The shadowed accounts (DGO-1488) whose Chrome rows chrome_put may replace: those whose Chrome password the
    plane already holds, so replacing the row loses nothing. When the two differ, neither side is known to be the
    newer one — he may have changed it in Chrome since the harvest (the second reader: the row's replacement lost
    it), or in the plane's screen (the third reader: writing Chrome's over it lost the plane's) — so nothing is
    overwritten anywhere: the row stays in Chrome beside the declared one, and the sync says so. One whose credential
    cannot be read is left in Chrome too."""
    safe = []
    for username in entry.get("shadowed") or ():
        row = own.get((origin, username))
        cid = (entry.get("shadowed_cid") or {}).get(username)
        if row is None or not row["password"]:
            safe.append(username)                             # nothing of it in Chrome to lose
            continue
        held = plane_secret(cid) if cid else None
        # the account by its credential's id, never its user name: a report is printed (the fifth reader)
        if held is None:
            report["skipped"].append({"origin": origin, "reason": f"a harvested account (credential {cid}) is kept in "
                                      "Chrome: its credential could not be read"})
            continue
        if held != row["password"]:
            report["skipped"].append({"origin": origin, "reason": f"a harvested account (credential {cid}) differs "
                                      "between Chrome and its credential: kept in both, nothing overwritten — a person "
                                      "picks"})
            continue
        safe.append(username)
    return tuple(safe)


def cmd_sync(materialize: bool = True, harvest: bool = True) -> None:
    """Both directions, with the conflict rules from the module docstring."""
    sync_lock()
    state = load_state()
    report = {"to_chrome": [], "to_plane": [], "created": [], "deleted": [], "skipped": []}
    rows = chrome_rows()
    entries = plane_entries()
    written = []                                              # chrome_written_rows(), read once and only if needed

    def bridge_row(origin: str, username: str):
        if not written:
            written.append(chrome_written_rows())
        return written[0].get((origin + "/", username))

    if materialize:
        own = chrome_account_rows()
        settled = set()                    # origins whose account this run left filed where this browser looks
        for origin, entry in entries.items():
            # the credential's OWN account: never the newest row of another one (the bridge's second reader)
            row = own.get((origin, entry["username"]))
            known = state["entries"].get(origin) or {}
            # The fingerprints are of ONE account (`account`). When the plane's credential now names another, they
            # say nothing of this one's Chrome row: comparing them read «Chrome moved», and Chrome's stale password
            # overwrote the one he had just set in the plane (the bridge's third reader). Nothing is taken from
            # Chrome then: the plane's account is written, as for a credential seen the first time.
            # An entry with fingerprints and NO account (a harvest before the field, or from an older bridge) says
            # nothing of which account they are: unclear the same way (the fifth reader).
            if (known.get("plane") or known.get("chrome")) and known.get("account") != entry["username"]:
                report["skipped"].append({"origin": origin, "reason": "its credential names another account than the "
                                          "sync's memory (or the memory names none): the plane's is written to "
                                          "Chrome, nothing is taken from Chrome"})
                known = {k: v for k, v in known.items() if k == "wrote"}
            account = {"account": entry["username"]}
            plane_fp = fingerprint(state, entry["password"])
            chrome_fp = fingerprint(state, row["password"]) if row else None
            # "Already identical" has to mean identical INCLUDING the stored URL, otherwise a row
            # filed under `:8080` is left in place forever while Chromium refuses to match it.
            # (`raw` is normalize_origin's, which never ends in "/": compared with `origin + "/"` this was
            # never true, so every sync rewrote every login — DGO-1488's second reader)
            # `wrote`: the user name THIS bridge wrote the Chrome row with (chrome_put) — the one row the DELETION
            # rule may remove. An entry from before the field has none, and nothing it names is ever deleted.
            keep = {"wrote": known["wrote"]} if known.get("wrote") else {}
            if row and row["password"] == entry["password"] and row.get("raw") == origin:
                # an entry from before `wrote`, whose Chrome row IS the one the bridge files: it is the bridge's,
                # so a deletion in the plane can take it (otherwise no such row would ever be deleted)
                # (never for a credential harvested from Chrome: its row is his, whatever its shape)
                if not keep and not entry["cid"].startswith(CUSTOM_PREFIX) \
                        and bridge_row(origin, entry["username"]) == entry["password"]:
                    keep = {"wrote": entry["username"]}
                state["entries"][origin] = {"plane": plane_fp, "chrome": plane_fp, **keep, **account}
                settled.add(origin)
                continue
            # The row is this credential's own account (chrome_account_rows): another account's password is never
            # taken for it — that wrote a personal account's password over the owner's, in the plane and then in
            # Chrome (the second reader of the first attempt). An empty one is never taken either: the plane
            # refuses it, and fail() ends the whole sync.
            takeable = bool(row) and bool(row["password"])
            if row and known.get("chrome") and chrome_fp != known["chrome"] \
                    and plane_fp == known.get("plane"):
                if not takeable:
                    report["skipped"].append({"origin": origin, "reason": "Chrome's row for this account is empty: "
                                              "not taken for this credential"})
                    continue
                # Only Chrome moved since the last sync: he typed it in the browser, and that is intent (the
                # CONFLICTS table). This was left to harvest, which skips every origin the plane already has, so a
                # password changed in Chrome never arrived.
                report["to_plane"].append(origin)
                plane_write(entry["cid"], entry.get("password_field"), row["password"])
                state["entries"][origin] = {"plane": chrome_fp, "chrome": chrome_fp, **keep, **account}
                continue
            if takeable and known.get("chrome") and known.get("plane") \
                    and chrome_fp != known["chrome"] and plane_fp != known["plane"]:
                # both moved: Chrome wins, and we say so — the plane's value kept aside first (the fifth reader)
                kept = keep_once(state, origin, entry["username"], entry["password"], source="plane")
                if kept is None:
                    report["skipped"].append({"origin": origin, "reason": "both sides changed, and the plane's "
                                              "password could not be kept first: nothing replaced"})
                    continue
                if kept != ALREADY_KEPT:
                    report.setdefault("kept", []).append({"origin": origin, "credential": kept})
                report["to_plane"].append(origin)
                plane_write(entry["cid"], entry.get("password_field"), row["password"])
                state["entries"][origin] = {"plane": chrome_fp, "chrome": chrome_fp, **keep, **account}
                continue
            if row and row["password"] and row["password"] != entry["password"]:
                # Chrome holds another password for this account — one the bridge never recorded, or the one it did
                # when it is the plane that moved (a vault restored from an older backup moves back: Chrome's is the
                # newer, the fifth reader). Replacing it would lose it: kept in the plane first.
                kept = keep_once(state, origin, entry["username"], row["password"])
                if kept is None:
                    report["skipped"].append({"origin": origin, "reason": "Chrome holds another password for this "
                                              "account, which could not be kept in the plane first: nothing replaced"})
                    continue
                if kept != ALREADY_KEPT:
                    report.setdefault("kept", []).append({"origin": origin, "credential": kept})
            chrome_put(origin, entry["username"], entry["password"], _shadowed_safe(origin, entry, own, report))
            report["to_chrome"].append(origin)
            state["entries"][origin] = {"plane": plane_fp, "chrome": plane_fp, "wrote": entry["username"], **account}
            settled.add(origin)
        # Rows filed under a variant this browser cannot address (the old `:8080` rows) are dead
        # weight: Chromium will never match them, and leaving them means two rows per site forever.
        # Compare NORMALISED forms: a plain trailing slash (`https://www.facebook.com/`) is the same
        # origin, not a variant — only a dropped PORT makes a row unreachable by this browser.
        # Only the account the plane holds is moved: its row was just filed under the address this browser uses.
        # Another account of his under the old address is the only copy of that password, and stays (a real Login
        # Data, the second reader: «migrated» deleted every row of the variant, his other n8n account with it).
        # And only when this run left that account filed at the browser's address (written now, or found there
        # identical): a credential skipped on this run has no other copy of its old row (the second reader).
        for raw, username in chrome_raw_rows():
            origin = browser_origin(raw)
            if normalize_origin(raw) != origin and origin in settled and username == entries[origin]["username"]:
                if chrome_delete_variant(raw, username):
                    report.setdefault("migrated", []).append(raw)
                else:
                    report["skipped"].append({"origin": raw, "reason": "its old-address row could not be removed "
                                              "now (the browser holds the store?): tried again on the next sync"})

    # DELETION — a credential that left the plane: in the state, no longer an entry. Decided BEFORE harvest, which
    # otherwise found its Chrome row on the same run and created the credential again (and the old loop skipped
    # every origin still in Chrome, which is every row it existed for). The rules:
    #   - the plane listed NOTHING while the state holds credentials: no decision at all on that answer — not a
    #     deletion (a wiped or half-restored plane would take every row the bridge wrote, the only copy left),
    #     and not a harvest of those origins either;
    #   - the row this bridge wrote (origin + "/", the user name in `wrote`), as it wrote it: deleted, exactly that
    #     row, and only by a verb that writes Chrome (sync, materialize) — harvest never deletes;
    #   - anything else there (his own rows, the bridge's row changed in Chrome since, an entry from before `wrote`)
    #     is never deleted by the bridge. What Chrome holds for the origin at that moment is fingerprinted
    #     (`deleted_in_plane`) and kept out of harvest until Chrome changes after the deletion: a credential
    #     deleted in the plane does not come back by itself.
    held = not entries and bool(state["entries"])
    if held:
        report["skipped"].append({"origin": "*", "reason": "the plane listed no credential while the state holds "
                                  f"{len(state['entries'])}: nothing is deleted or harvested back on that answer"})
    pending = set()                                           # origins harvest leaves alone on this run
    for origin, known in list(state["entries"].items()):
        if origin in entries:
            known.pop("missing", None)                        # listed again: a later absence starts over
            continue
        if held:
            pending.add(origin)
            continue
        row = rows.get(origin)
        if row is None:                                       # nothing saved for it in Chrome any more
            del state["entries"][origin]
            continue
        pending.add(origin)
        marker = known.get("deleted_in_plane")
        if marker is None and not known.get("missing"):
            # Missing from ONE listing decides nothing yet: a plane restored from an older backup lists the older
            # credentials only, and every row the bridge wrote for a newer one would go — perhaps the last copy (the
            # bridge's third reader). Still missing on a sync MISSING_MIN_SECONDS later, it is a deletion. `missing`
            # is when it was first missed (a state from before says 1: long ago).
            known["missing"] = int(time.time())
            report["skipped"].append({"origin": origin, "reason": "missing from the plane's listing: decided on a "
                                      "later sync, if it is still missing then"})
            continue
        if marker is None and time.time() - float(known.get("missing") or 0) < MISSING_MIN_SECONDS:
            report["skipped"].append({"origin": origin, "reason": "still missing from the plane's listing, but first "
                                      "missed less than an hour ago: decided on a later sync"})
            continue
        mine = bridge_row(origin, known["wrote"]) if known.get("wrote") and marker is None else None
        if mine is not None and fingerprint(state, mine) == known.get("chrome") and not DELETE_IN_CHROME:
            # The bridge never deletes a Chrome row by itself (the fourth reader: a credential leaves the plane's
            # listing for reasons that are not a deletion — a value that stopped resolving, a plane restored from an
            # older backup — and the row was the last copy). It is said, kept out of harvest, and stays in Chrome.
            report["skipped"].append({"origin": origin, "reason": "gone from the plane: its Chrome row is kept "
                                      "(the bridge deletes nothing by itself) and is not harvested back"})
            known["deleted_in_plane"] = fingerprint(state, row["username"] + "\n" + row["password"])
            continue
        if mine is not None and fingerprint(state, mine) == known.get("chrome"):
            if not materialize:
                continue                                      # harvest only: decided by the next sync
            if chrome_delete_written(origin, known["wrote"]):
                report["deleted"].append(origin)
                state["entries"][origin] = {"deleted_in_plane": "next"}   # fingerprinted on the next run
            else:                                             # 0 rows: never reported as deleted
                report["skipped"].append({"origin": origin, "reason": "its Chrome row could not be deleted now "
                                          "(the browser holds the store?): tried again on the next sync"})
            continue
        seen = fingerprint(state, row["username"] + "\n" + row["password"])
        if marker is None:
            if mine is not None:
                report["skipped"].append({"origin": origin, "reason": "deleted in the plane, and changed in Chrome "
                                          "since the last sync: left in Chrome, not brought back"})
            known["deleted_in_plane"] = seen
        elif marker == "next":
            known["deleted_in_plane"] = seen
        elif marker != seen:
            del state["entries"][origin]                      # Chrome changed after the deletion: harvest takes it
            pending.discard(origin)

    if harvest:
        for origin, row in rows.items():
            if origin in entries or origin in pending:
                continue
            # A row with no user name or no password cannot become a credential: the plane refuses an empty
            # field (/api/set → 400 «value required»), and that refusal ended the WHOLE harvest at the first
            # such row (the HP, 2026-11-08: an empty user name saved for the sign-in host, DGO-1490). It is
            # skipped and said, before anything is written for it, and the rest are harvested.
            missing = [what for what, empty in (("user name", not row["username"].strip()),
                                                ("password", not row["password"])) if empty]
            if missing:
                report["skipped"].append({"origin": origin, "reason": "no " + " and no ".join(missing)})
                continue
            try:
                cid = plane_create_custom(origin, row["username"], row["password"])
            except PlaneIdTaken as taken:
                report["skipped"].append({"origin": origin, "reason": f"its credential id {taken} is another "
                                          "credential's already: nothing written, the row stays in Chrome"})
                continue
            report["created"].append({"origin": origin, "credential": cid})
            # with its ACCOUNT: an entry without one had a later account change in the plane read as «both moved»,
            # and Chrome's old password went over the new one (the fifth reader)
            state["entries"][origin] = {"plane": fingerprint(state, row["password"]),
                                        "chrome": fingerprint(state, row["password"]), "account": row["username"]}

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
