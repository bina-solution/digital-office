#!/usr/bin/env python3
"""test_oauth_relay — a Google consent that comes back through the herd's one door (DGO-1390).

    python3 platform-base/connections/test_oauth_relay.py

Google returns a person only to an address registered on the OAuth client, and an office at home has none.
So one address is registered — `OAUTH_RELAY_URL/oauth/relay` — and every office's apps come back through it.
What must hold:

    · a consent an app starts with `ret` is asked with the relay's address and a SIGNED state
    · the relay sends the browser to `ret` with Google's answer — and only for a state one of our offices signed
    · the relay exchanges nothing and writes nothing
    · `/oauth/relayed` completes only a consent THIS office started (its nonce), once, and only for a direct call
    · …and only with the secret of the browser that started it (`bind`, DGO-1418): a consent link somebody else
      opens and approves comes back to a page that cannot finish it, and the attempt spends the consent
    · the code is exchanged with the address it was asked with, and one consent is Drive AND Gmail
    · the same account connected again is the same instances with a fresh token, never a second row
    · the consent that does not come back here (no `ret`) is the broker's own, unchanged

Hermetic: the vault lives in a temporary directory and the token exchange is replaced.
"""
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ["CONN_DATA_DIR"] = tempfile.mkdtemp(prefix="oauthrelay-")
os.environ["N8N_GOOGLE_OAUTH_CLIENT_ID"] = "client-for-test.apps.googleusercontent.com"
os.environ["N8N_GOOGLE_OAUTH_CLIENT_SECRET"] = "relay-test-not-a-google-secret"   # not shaped like one (G92)
os.environ["OAUTH_RELAY_URL"] = "https://connections.relay.example"
import app  # noqa: E402

FAILS = []
RET = "http://console.localhost:8080/a/drive.hp-laptop/oauth/google/return"
SECRET = "the-secret-kept-in-the-window-that-asked"
BIND = hashlib.sha256(SECRET.encode()).hexdigest()


def start_url(ret=RET, bind=BIND, as_instance=True):
    return ("/oauth/google-workspace-grant/start?" + ("as_instance=1&" if as_instance else "")
            + "ret=" + urllib.parse.quote(ret, safe="") + (f"&bind={bind}" if bind else ""))


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def id_token(email):
    seg = lambda d: app._b64u(json.dumps(d).encode())   # noqa: E731
    return seg({"alg": "none"}) + "." + seg({"email": email}) + ".sig"


def main() -> int:
    app.VAULT_PATH = os.path.join(tempfile.mkdtemp(prefix="oauthrelay-vault-"), "vault.enc")
    exchanged = []
    app._exchange = lambda prov, code, redirect: (exchanged.append((code, redirect)) or
                                                  ({"access_token": "a-" + code, "refresh_token": "r-" + code,
                                                    "id_token": id_token("owner@example.com")}, None))
    c = app.app.test_client()

    # ── the provider asked first: a dead client is said here, not on Google's page ──
    real_refusal = app._provider_refusal
    app._provider_refusal = lambda url: "invalid_client"
    r = c.get(start_url())
    d = r.get_json() or {}
    check(r.status_code == 409 and d.get("provider_error") == "invalid_client" and "authorize_url" not in d,
          "a client Google no longer has is refused before anyone is sent to Google")
    check("https://connections.relay.example/oauth/relay" in d.get("error", "") and "Google" in d.get("error", ""),
          "…in a Hebrew sentence that names the address to register")
    app._provider_refusal = lambda url: ""

    # ── start ──
    r = c.get(start_url())
    d = r.get_json() or {}
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(d.get("authorize_url", "")).query)
    state = (q.get("state") or [""])[0]
    check(r.status_code == 200 and d.get("relayed") is True, "a consent with `ret` is a relayed one")
    check(q.get("redirect_uri") == ["https://connections.relay.example/oauth/relay"],
          "it is asked with the relay's one address")
    check(state.startswith("r1.") and app.open_state(state)[0] is not None, "its state is signed and opens")
    check(app.open_state(state)[0]["r"] == RET, "the state names the app's return page")
    bad = c.get(start_url("javascript:alert(1)"))
    check(bad.status_code == 400, "a return that is not an absolute http(s) page is refused")
    for foreign in ("https://evil.example/oauth/google/return", "https://digital-office.co.il.evil.example/oauth/google/return",
                    "http://console.localhost:8080/a/drive/somewhere-else", RET + "?next=https://evil.example"):
        bad = c.get(start_url(foreign))
        check(bad.status_code == 400, f"a return that is not one of our apps' return pages is refused: {foreign}")
    ok_public = c.get(start_url("https://console.staging.digital-office.co.il/a/mailview/oauth/google/return"))
    check(ok_public.status_code == 200, "an app's return page on the herd's public name is taken")
    bad = c.get(start_url(as_instance=False))
    check(bad.status_code == 400, "a relayed consent that connects no account (no as_instance) is refused")
    bad = c.get(start_url(bind=""))
    check(bad.status_code == 400 and "bind" in (bad.get_json() or {}).get("error", ""),
          "a relayed consent that names no browser (no bind) is refused")
    bad = c.get(start_url(bind="not-a-sha256"))
    check(bad.status_code == 400, "…and so is one whose bind is not a sha256")

    # ── the relay ──
    vault_before = os.path.getmtime(app.VAULT_PATH) if os.path.exists(app.VAULT_PATH) else None
    r = c.get("/oauth/relay?" + urllib.parse.urlencode({"code": "C1", "state": state}))
    loc = r.headers.get("Location", "")
    back = urllib.parse.parse_qs(urllib.parse.urlsplit(loc).query)
    check(r.status_code == 302 and loc.startswith(RET + "?"), "the relay sends the browser to the return page")
    check(back.get("code") == ["C1"] and back.get("state") == [state], "…with Google's code and the same state")
    check(not exchanged, "the relay exchanged nothing")
    vault_after = os.path.getmtime(app.VAULT_PATH) if os.path.exists(app.VAULT_PATH) else None
    check(vault_before == vault_after, "the relay wrote nothing to the vault")
    head, body, mac = state.split(".")
    forged = head + "." + body + "." + ("A" if mac[0] != "A" else "B") + mac[1:]
    r = c.get("/oauth/relay?" + urllib.parse.urlencode({"code": "C1", "state": forged}))
    check(r.status_code == 400 and not r.headers.get("Location"), "a state with another signature is not relayed")
    other = json.loads(app.base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    other["r"] = "https://evil.example/steal"
    tampered = "r1." + app._b64u(json.dumps(other, separators=(",", ":")).encode()) + "." + mac
    r = c.get("/oauth/relay?" + urllib.parse.urlencode({"code": "C1", "state": tampered}))
    check(r.status_code == 400 and "evil" not in r.headers.get("Location", ""), "a state pointed elsewhere is not relayed")
    r = c.get("/oauth/relay?" + urllib.parse.urlencode({"code": "C1", "state": "google-workspace-grant|as_instance"}))
    check(r.status_code == 400, "the broker's own unsigned state is not relayed")
    # a state signed with the secret (any office that holds it could) but pointed outside: the relay holds the line too
    evil = app.sign_state(app.catalog()["google-workspace-grant"],
                          {"c": "google-workspace-grant", "i": 1, "n": "x", "r": "https://evil.example/oauth/google/return",
                           "u": "https://connections.relay.example/oauth/relay", "t": int(time.time()) + 600})
    r = c.get("/oauth/relay?" + urllib.parse.urlencode({"code": "C1", "state": evil}))
    check(r.status_code == 400 and not r.headers.get("Location"), "a signed state pointed outside is not relayed")

    # ── completing it here ──
    r = c.post("/oauth/relayed", json={"code": "C1", "state": state, "bind": SECRET},
               headers={"X-Forwarded-For": "192.168.16.50"})
    check(r.status_code == 403 and not exchanged, "a completion relayed through the edge is refused")
    r = c.post("/oauth/relayed", json={"code": "C1", "state": state, "bind": SECRET})
    d = r.get_json() or {}
    protos = sorted(m["protocol"] for m in d.get("made", []))
    check(r.status_code == 200 and d.get("ok"), "a direct completion of this office's consent is taken")
    check(protos == ["drive_google_oauth", "mail_gmail_oauth"], "one consent is Drive and Gmail")
    check(exchanged == [("C1", "https://connections.relay.example/oauth/relay")],
          "the code was exchanged once, with the address it was asked with")
    check(d.get("account_hint") == "owner@example.com", "the account is named by its address")
    r = c.post("/oauth/relayed", json={"code": "C1", "state": state, "bind": SECRET})
    check(r.status_code == 409 and len(exchanged) == 1, "the same consent is not taken twice")

    # ── bound to the browser that asked (DGO-1418) ──
    for other in ("", "the-secret-of-another-browser"):
        r = c.get(start_url())
        st = urllib.parse.parse_qs(urllib.parse.urlsplit(r.get_json()["authorize_url"]).query)["state"][0]
        r = c.post("/oauth/relayed", json={"code": "C3", "state": st, **({"bind": other} if other else {})})
        check(r.status_code == 403 and len(exchanged) == 1,
              "a completion " + ("without the browser's secret" if not other else "with another browser's secret")
              + " is refused, and nothing is exchanged")
        r = c.post("/oauth/relayed", json={"code": "C3", "state": st, "bind": SECRET})
        check(r.status_code == 409 and len(exchanged) == 1, "…and the attempt spent the consent: the right secret comes too late")
    r = c.get(start_url())
    st = urllib.parse.parse_qs(urllib.parse.urlsplit(r.get_json()["authorize_url"]).query)["state"][0]
    r = c.post("/oauth/relayed", data='{"code": "C4", "state": "%s", "bind": "\\ud800"}' % st, content_type="application/json")
    check(r.status_code == 403 and len(exchanged) == 1, "a secret that is not even text is refused, not a server error")
    r = c.post("/oauth/relayed", data='["not", "an", "object"]', content_type="application/json")
    check(r.status_code == 400, "a body that is not an object is refused, not a server error")

    # a consent another office started (a valid signature, a nonce this office never issued)
    foreign = app.sign_state(app.catalog()["google-workspace-grant"],
                             {"c": "google-workspace-grant", "i": 1, "n": "not-issued-here", "r": RET,
                              "u": "https://connections.relay.example/oauth/relay", "t": int(time.time()) + 600})
    r = c.post("/oauth/relayed", json={"code": "C9", "state": foreign, "bind": SECRET})
    check(r.status_code == 409 and len(exchanged) == 1, "a consent another office started is not planted here")
    late = app.sign_state(app.catalog()["google-workspace-grant"],
                          {"c": "google-workspace-grant", "i": 1, "n": "x", "r": RET, "u": "u", "t": int(time.time()) - 1})
    check(app.open_state(late)[0] is None, "an expired consent does not open")

    # the same account again: the same rows, a fresh token
    r = c.get(start_url())
    state2 = urllib.parse.parse_qs(urllib.parse.urlsplit(r.get_json()["authorize_url"]).query)["state"][0]
    r = c.post("/oauth/relayed", json={"code": "C2", "state": state2, "bind": SECRET})
    d2 = r.get_json() or {}
    rows = [rec for rec in app._instances(app.vault_read()).values() if rec.get("account_hint") == "owner@example.com"]
    check(r.status_code == 200 and all(m["again"] for m in d2.get("made", [])), "the same account again is the same instances")
    check(len(rows) == 2 and all(rec["secret"]["access_token"] == "a-C2" for rec in rows),
          "…two rows, each with the fresh token")
    r = c.post("/oauth/relayed", json={"error": "access_denied", "state": app.sign_state(
        app.catalog()["google-workspace-grant"], {"c": "google-workspace-grant", "i": 1, "n": "nope", "r": RET,
                                                  "u": "u", "t": int(time.time()) + 60})})
    check(r.status_code in (400, 409), "a refused consent is said, not taken")

    # ── DGO-1634: every refusal is said in plain words with WHERE it is fixed — the console's own start too ──
    help_page = "https://console.cloud.google.com/apis/credentials"
    app._provider_refusal = lambda url: "invalid_client"
    r = c.get(start_url())
    check((r.get_json() or {}).get("help_url") == help_page, "a relayed refusal carries Google Cloud's credentials page")
    r = c.get("/oauth/google-workspace-grant/start?as_instance=1")
    d = r.get_json() or {}
    check(r.status_code == 409 and d.get("provider_error") == "invalid_client" and "authorize_url" not in d,
          "the broker's own start (the console's «חיבור חשבון חדש») asks Google first too, and opens nothing")
    check(d.get("error", "").startswith("ההתחברות עם Google עוד לא פתוחה בלשכה הזו") and d.get("help_url") == help_page
          and d.get("redirect_uri", "").endswith("/oauth/callback"),
          "…said in plain words, with the page where it is fixed and the address it would need")
    r = c.get("/oauth/google-workspace-grant/start?as_instance=1&go=1")
    page = r.get_data(as_text=True)
    check(r.status_code == 409 and "Location" not in r.headers and help_page in page and "נמחק אצל Google" in page,
          "a browser sent there (go=1) gets a page of the same words and the link, never Google's")
    app._provider_refusal = lambda url: "redirect_uri_mismatch"
    d = c.get("/oauth/google-workspace-grant/start?as_instance=1").get_json() or {}
    check("Google לא מכיר את כתובת החזרה" in d.get("error", "") and d["redirect_uri"] in d.get("error", ""),
          "a live client that does not know this address: said, with the address to add")
    asked = []
    app._provider_refusal = lambda url: asked.append(url) or ""
    saved = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_ID")
    for none in ("", "your-client-id.apps.googleusercontent.com"):
        os.environ["N8N_GOOGLE_OAUTH_CLIENT_ID"] = none
        d = c.get("/oauth/google-workspace-grant/start?as_instance=1").get_json() or {}
        check(d.get("provider_error") == "no_client" and "אין לה עדיין מזהה התחברות" in d.get("error", "")
              and d.get("help_url") == help_page and not asked,
              f"no client (or a template's placeholder {none!r}): «not yet» in plain words, Google not even asked")
    os.environ["N8N_GOOGLE_OAUTH_CLIENT_ID"] = saved
    saved_secret = os.environ.get("N8N_GOOGLE_OAUTH_CLIENT_SECRET")
    os.environ["N8N_GOOGLE_OAUTH_CLIENT_SECRET"] = ""
    d = c.get(start_url()).get_json() or {}
    check(d.get("provider_error") == "no_secret" and "client secret" in d.get("error", "") and d.get("client_id_present") is True,
          "an id without its secret: «the secret is missing», not «make a new client» — its fix is another")
    os.environ["N8N_GOOGLE_OAUTH_CLIENT_SECRET"] = saved_secret
    check(app._real_client("123456789012-abxxxtodo0123456789abcdefghijklm.apps.googleusercontent.com")
          and not app._real_client("your-client-id.apps.googleusercontent.com") and not app._real_client(""),
          "a client id in Google's own shape is real whatever its random part spells (xxx, todo)")
    app._provider_refusal = real_refusal
    opened = []

    class Down:
        def open(self, *a, **kw):
            opened.append(1)
            raise OSError("no route to Google")
    real_opener = app.urllib.request.build_opener
    app.urllib.request.build_opener = lambda *a: Down()
    url = "https://accounts.google.com/o/oauth2/v2/auth?client_id=cid-for-test&redirect_uri=https%3A%2F%2Fx%2Fcb"
    first, second = app._provider_refusal(url), app._provider_refusal(url)
    app.urllib.request.build_opener = real_opener
    check(first == second == "" and len(opened) == 1,
          "Google that cannot be asked is asked once a minute, not on every start (each would wait its timeout)")
    app._provider_refusal = lambda url: ""

    # ── the broker's own consent is unchanged ──
    r = c.get("/oauth/google-workspace-grant/start?as_instance=1")
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(r.get_json()["authorize_url"]).query)
    check(q.get("state") == ["google-workspace-grant|as_instance"], "a consent without `ret` keeps the broker's state")
    check(q.get("redirect_uri", [""])[0].endswith("/oauth/callback"), "…and the broker's own callback")
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
