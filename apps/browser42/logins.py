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
    run-queued           what start-browser.sh calls at boot; same as sync
"""

from __future__ import annotations

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


def main() -> None:
    verb = sys.argv[1] if len(sys.argv) > 1 else ""
    arg = sys.argv[2] if len(sys.argv) > 2 else ""
    if verb == "list":
        cmd_list()
    elif verb == "sources":
        cmd_sources()
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
        fail("usage", "verbs: list | sources | sync | materialize | harvest | export <site> | run-queued")


if __name__ == "__main__":
    main()
