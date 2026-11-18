#!/usr/bin/env python3
"""test_oauth_readonly — an office that connects a protocol READ-ONLY (EXU-24, ported from Exampleu's 9810127).

    python3 platform-base/connections/test_oauth_readonly.py

Exampleu's office reads its client's Google Drive and must never be able to write to it. It declares
`OAUTH_READONLY_PROTOCOLS=drive_google_oauth`. What must hold:

    · an office that declares nothing is untouched: «קבצים»'s and mailview's consent is the provider-wide grant
      (Drive AND Gmail, full), the protocol hint ignored; the broker's own callback keeps the full grant
    · where it is declared, «קבצים»'s consent asks Google for drive.readonly alone (no include_granted_scopes) and
      mints the Drive account only — said read-only; mailview's asks for Gmail alone, never Drive
    · a protocol consent's token that carries any scope beyond what that protocol asks for is refused, and nothing
      is kept — a read-only Drive one, and a Gmail one widened to Drive alike
    · a provider-wide consent that would cover the read-only protocol is refused — at the start (a page for a
      browser), at the broker's callback and at a relayed completion, also one started before the declaration
    · what came before the declaration is held to it too: the vault hands out no wider Drive account, takes no
      wider renewal back, adds no wider account by hand, and re-pushes no provider-wide grant into n8n
    · a read-only declaration for a protocol with no read-only scopes is refused, never widened, never a 500

Hermetic: the vault lives in a temporary directory and the token exchange is replaced.
"""
import hashlib
import json
import os
import sys
import tempfile
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CONN_DATA_DIR"] = tempfile.mkdtemp(prefix="oauthro-")
os.environ["N8N_GOOGLE_OAUTH_CLIENT_ID"] = "client-for-test.apps.googleusercontent.com"
os.environ["N8N_GOOGLE_OAUTH_CLIENT_SECRET"] = "readonly-test-not-a-google-secret"   # not shaped like one (G92)
os.environ["OAUTH_RELAY_URL"] = "https://connections.relay.example"
os.environ.pop("OAUTH_READONLY_PROTOCOLS", None)
import app  # noqa: E402

FAILS = []
GRANT = "google-workspace-grant"
RET = "http://console.localhost:8080/a/drive.exampleu/oauth/google/return"
SECRET = "the-secret-kept-in-the-window-that-asked"
BIND = hashlib.sha256(SECRET.encode()).hexdigest()
RO = "https://www.googleapis.com/auth/drive.readonly"
FULL = "https://www.googleapis.com/auth/drive"
MAIL = "https://mail.google.com/"
MODIFY = "https://www.googleapis.com/auth/gmail.modify"
EMAIL = "https://www.googleapis.com/auth/userinfo.email"


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def id_token(email):
    seg = lambda d: app._b64u(json.dumps(d).encode())   # noqa: E731
    return seg({"alg": "none"}) + "." + seg({"email": email}) + ".sig"


def door_start(c, protocol="drive_google_oauth", cid=GRANT):
    """What «קבצים»'s door (protocol drive_google_oauth) or mailview's (mail_gmail_oauth) asks connections."""
    q = {"as_instance": "1", "ret": RET, "bind": BIND}
    if protocol is not None:
        q["protocol"] = protocol
    return c.get(f"/oauth/{cid}/start?" + urllib.parse.urlencode(q))


def asked(r):
    return urllib.parse.parse_qs(urllib.parse.urlsplit((r.get_json() or {}).get("authorize_url", "")).query)


def scope_of(r):
    return (asked(r).get("scope") or [""])[0].split()


def accounts():
    return sorted(rec.get("protocol") for rec in app._instances(app.vault_read()).values())


def fresh_vault():
    app.VAULT_PATH = os.path.join(tempfile.mkdtemp(prefix="oauthro-vault-"), "vault.enc")


def main() -> int:
    fresh_vault()
    app._provider_refusal = lambda url: ""
    granted = {"scope": ""}
    exchanged = []
    app._exchange = lambda prov, code, redirect: (exchanged.append(code) or
                                                  ({"access_token": "a-" + code, "refresh_token": "r-" + code,
                                                    "id_token": id_token("reader@example.com"),
                                                    **({"scope": granted["scope"]} if granted["scope"] else {})}, None))
    injected = []
    app.inject_into_n8n = lambda prov, tok: (injected.append(tok) or 1)
    c = app.app.test_client()

    # ── an office that declares nothing: as it always was ──
    r = door_start(c)
    q = asked(r)
    check(r.status_code == 200 and FULL in scope_of(r) and MAIL in scope_of(r),
          "no declaration: «קבצים»'s consent is the provider-wide grant (Drive and Gmail, full), the hint ignored")
    check(q.get("include_granted_scopes") == ["true"] and (r.get_json() or {}).get("read_only") is False,
          "…with include_granted_scopes, as before, and not said read-only")
    r = door_start(c, protocol="mail_gmail_oauth")
    check(r.status_code == 200 and FULL in scope_of(r) and MAIL in scope_of(r), "…mailview's hint is ignored too")
    state = q["state"][0]
    check(app.open_state(state)[0].get("p") == "", "…its signed state names no protocol")
    granted["scope"] = f"openid {EMAIL} {FULL} {MAIL}"
    d = c.post("/oauth/relayed", json={"code": "N1", "state": state, "bind": SECRET}).get_json() or {}
    check(d.get("ok") and sorted(m["protocol"] for m in d.get("made", [])) == ["drive_google_oauth", "mail_gmail_oauth"]
          and d.get("read_only") is False, "…and one consent is still Drive and Gmail")
    r = c.get("/oauth/callback?" + urllib.parse.urlencode({"code": "N2", "state": f"{GRANT}|as_instance"}))
    check(r.status_code == 200 and GRANT in app.vault_read() and accounts().count("mail_gmail_oauth") == 2,
          "…the broker's own callback keeps the provider's full grant and mints both accounts, as before")
    r = c.get("/oauth/drive_google_oauth/start?as_instance=1")
    check(r.status_code == 200 and scope_of(r) == ["openid", "email", FULL] and "include_granted_scopes" not in asked(r),
          "…a start by a protocol's own id is a consent for that protocol alone (its `full` scopes)")
    granted["scope"] = f"openid {EMAIL} {FULL} {MAIL}"
    n = len(accounts())
    r = c.get("/oauth/callback?" + urllib.parse.urlencode({"code": "N3", "state": "drive_google_oauth|as_instance"}))
    check(r.status_code == 409 and len(accounts()) == n, "…and its token may carry no more than that protocol asks for")

    # a provider-wide relayed consent started BEFORE the declaration (the provider-wide grant is kept from N2)
    pending = asked(door_start(c))["state"][0]

    # ── the office declares Drive read-only ──
    os.environ["OAUTH_READONLY_PROTOCOLS"] = "drive_google_oauth"
    n = len(exchanged)
    granted["scope"] = f"openid {EMAIL} {FULL} {MAIL}"
    r = c.post("/oauth/relayed", json={"code": "P1", "state": pending, "bind": SECRET})
    check(r.status_code == 409 and len(exchanged) == n,
          "declared: a provider-wide consent started before the declaration is refused when it completes, nothing exchanged")
    r = door_start(c, protocol=None)
    check(r.status_code == 409 and "קריאה בלבד" in (r.get_json() or {}).get("error", ""),
          "…a provider-wide consent (no protocol) is refused, in words")
    r = c.get(f"/oauth/{GRANT}/start?go=1")
    page = r.get_data(as_text=True)
    check(r.status_code == 409 and not r.headers.get("Location") and r.mimetype == "text/html" and "קריאה בלבד" in page,
          "…the broker's own, for a browser (the console's «חבר»), as a page in words, never raw JSON")
    r = c.get(f"/oauth/{GRANT}/reinject")
    check(r.status_code == 409 and not injected, "…and the provider-wide grant kept from before is not re-pushed into n8n")

    r = door_start(c)
    q = asked(r)
    d = r.get_json() or {}
    check(r.status_code == 200 and scope_of(r) == ["openid", "email", RO], "«קבצים»'s consent asks Google for drive.readonly alone")
    check("include_granted_scopes" not in q, "…without include_granted_scopes (no earlier full grant folded in)")
    check(d.get("read_only") is True and d.get("platform_protocols") == ["drive_google_oauth"],
          "…said read-only, for the Drive protocol only")
    payload = app.open_state(q["state"][0])[0]
    check(payload.get("c") == GRANT and payload.get("p") == "drive_google_oauth",
          "…its signed state names the provider and the protocol")
    r = door_start(c, protocol="mail_gmail_oauth")
    check(r.status_code == 200 and scope_of(r) == ["openid", "email", MAIL, MODIFY] and (r.get_json() or {}).get("read_only") is False,
          "mailview's consent asks for Gmail alone — no Drive scope at all")

    fresh_vault()
    granted["scope"] = f"openid {EMAIL} {RO}"
    d = c.post("/oauth/relayed", json={"code": "R1", "state": q["state"][0], "bind": SECRET}).get_json() or {}
    check(d.get("ok") and [m["protocol"] for m in d.get("made", [])] == ["drive_google_oauth"] and d.get("read_only") is True,
          "a read-only token: the Drive account alone is made, said read-only")
    check(accounts() == ["drive_google_oauth"], "…no Gmail account was minted")
    ro_drive = next(iter(app._instances(app.vault_read())))

    def kept():
        return app._instances(app.vault_read())[ro_drive]["secret"].get("access_token")

    for extra, what in ((f"openid {EMAIL} {RO} {FULL}", "a token carrying drive (write) besides"),
                        (f"openid {EMAIL} {RO} {MAIL}", "a token carrying Gmail besides"),
                        ("", "a token that states no scope")):
        st = asked(door_start(c))["state"][0]
        granted["scope"] = extra
        r = c.post("/oauth/relayed", json={"code": "X", "state": st, "bind": SECRET})
        check(r.status_code == 409 and accounts() == ["drive_google_oauth"] and kept() == "a-R1",
              f"{what} is refused, and nothing is kept")
    st = asked(door_start(c, protocol="mail_gmail_oauth"))["state"][0]
    granted["scope"] = f"openid {EMAIL} {MAIL} {MODIFY} {FULL}"
    r = c.post("/oauth/relayed", json={"code": "G1", "state": st, "bind": SECRET})
    check(r.status_code == 409 and accounts() == ["drive_google_oauth"],
          "a Gmail consent whose token carries Drive (its address widened) is refused, and no account is made")
    st = asked(door_start(c, protocol="mail_gmail_oauth"))["state"][0]
    granted["scope"] = f"openid {EMAIL} {MAIL} {MODIFY}"
    d = c.post("/oauth/relayed", json={"code": "G2", "state": st, "bind": SECRET}).get_json() or {}
    check(d.get("ok") and [m["protocol"] for m in d.get("made", [])] == ["mail_gmail_oauth"],
          "…a Gmail token of Gmail alone makes the Gmail account alone")

    # ── the vault holds what came before to the declaration too ──
    fresh_vault()
    wide = app.create_instance("drive_google_oauth", "old", {"access_token": "old", "refresh_token": "old-r",
                                                               "scope": f"openid {EMAIL} {FULL}"}, "reader@example.com")
    narrow = app.create_instance("drive_google_oauth", "new", {"access_token": "new", "refresh_token": "new-r",
                                                                 "scope": f"openid {EMAIL} {RO}"}, "reader@example.com")
    r = c.get(f"/api/instances/{wide}/secret")
    check(r.status_code == 409 and "secret" not in (r.get_json() or {}) and (r.get_json() or {}).get("read_only") is True,
          "an account from before the declaration (full Drive) is not handed out: it must be connected again")
    r = c.get(f"/api/instances/{narrow}/secret")
    check(r.status_code == 200 and (r.get_json() or {}).get("secret", {}).get("access_token") == "new",
          "…a read-only one is")
    r = c.put(f"/api/instances/{narrow}/secret", json={"secret": {"access_token": "revived", "scope": f"openid {EMAIL} {FULL}"}})
    check(r.status_code == 409 and app._instances(app.vault_read())[narrow]["secret"]["access_token"] == "new",
          "a renewal from the old full grant (an engine that still held it) is not written back")
    r = c.put(f"/api/instances/{narrow}/secret", json={"secret": {"access_token": "renewed", "expires_in": 3599}})
    check(r.status_code == 200 and app._instances(app.vault_read())[narrow]["secret"]["access_token"] == "renewed",
          "…a routine renewal of the read-only grant is")
    r = c.put(f"/api/instances/{narrow}/secret", json={"secret": {"access_token": "other", "refresh_token": "other-r"}})
    check(r.status_code == 409 and app._instances(app.vault_read())[narrow]["secret"]["refresh_token"] == "new-r",
          "a write that brings another refresh token without its own scope is refused (the record's would only label it)")
    old_mail = app.create_instance("mail_gmail_oauth", "old", {"access_token": "m", "refresh_token": "m-r",
                                                                "scope": f"openid {EMAIL} {MAIL} {MODIFY} {FULL}"}, "x")
    r = c.get(f"/api/instances/{old_mail}/secret")
    check(r.status_code == 409 and "secret" not in (r.get_json() or {}),
          "a Gmail account from a provider-wide consent before the declaration (it carries Drive write) is not handed out")
    new_mail = app.create_instance("mail_gmail_oauth", "new", {"access_token": "m2", "refresh_token": "m2-r",
                                                                "scope": f"openid {EMAIL} {MAIL} {MODIFY}"}, "x")
    r = c.get(f"/api/instances/{new_mail}/secret")
    check(r.status_code == 200, "…a Gmail account of Gmail alone is")
    r = c.post("/api/instances", json={"protocol": "drive_google_oauth", "label": "by hand",
                                       "secret": {"access_token": "h", "scope": f"openid {FULL}"}})
    check(r.status_code == 409, "an account added by hand with a wider scope is refused")
    r = c.post("/api/instances", json={"protocol": "drive_google_oauth", "label": "by hand",
                                       "secret": {"access_token": "h", "scope": f"openid {RO}"}})
    check(r.status_code == 200, "…a read-only one is taken")

    # ── the broker's own (unsigned) callback holds the line too ──
    n = len(exchanged)
    r = c.get("/oauth/callback?" + urllib.parse.urlencode({"code": "B1", "state": f"{GRANT}|as_instance"}))
    check(r.status_code == 409 and len(exchanged) == n, "a provider-wide callback is refused before any exchange")
    fresh_vault()
    r = c.get("/oauth/drive_google_oauth/start?as_instance=1")
    q = asked(r)
    check(r.status_code == 200 and scope_of(r) == ["openid", "email", RO]
          and q.get("state") == ["drive_google_oauth|as_instance"], "a start by the protocol's own id is the same narrow consent")
    r = c.get("/oauth/drive_google_oauth/start")
    check(r.status_code == 400, "…and without as_instance it is refused (a protocol grant is never injected)")
    r = c.get("/oauth/drive_google_oauth/start?go=1")
    check(r.status_code == 400 and r.mimetype == "text/html", "…for a browser, as a page")
    granted["scope"] = f"openid {EMAIL} {RO}"
    r = c.get("/oauth/callback?" + urllib.parse.urlencode({"code": "B2", "state": "drive_google_oauth|as_instance"}))
    check(r.status_code == 200 and accounts() == ["drive_google_oauth"] and GRANT not in app.vault_read(),
          "its callback makes a Drive account only, and keeps no provider-wide grant")
    granted["scope"] = f"openid {EMAIL} {FULL}"
    r = c.get("/oauth/callback?" + urllib.parse.urlencode({"code": "B3", "state": "drive_google_oauth|as_instance"}))
    check(r.status_code == 409 and accounts() == ["drive_google_oauth"], "…and a wider token there is refused too")

    # ── a declaration with no read-only list is refused, never widened, never a 500 ──
    st = asked(door_start(c, protocol="mail_gmail_oauth"))["state"][0]
    os.environ["OAUTH_READONLY_PROTOCOLS"] = "drive_google_oauth,mail_gmail_oauth"
    r = c.get("/oauth/mail_gmail_oauth/start?as_instance=1")
    check(r.status_code == 409 and "mail_gmail_oauth" in (r.get_json() or {}).get("error", ""),
          "a read-only declaration for a protocol with no read-only scopes is refused")
    granted["scope"] = f"openid {EMAIL} {MAIL} {MODIFY}"
    r = c.post("/oauth/relayed", json={"code": "M1", "state": st, "bind": SECRET})
    check(r.status_code == 409 and "mail_gmail_oauth" not in accounts(),
          "…a consent in flight when that declaration was made is refused as such, not a server error")
    os.environ.pop("OAUTH_READONLY_PROTOCOLS", None)

    print()
    print("test_oauth_readonly: " + ("all passed" if not FAILS else f"{len(FAILS)} FAILED"))
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
