"""test_oauth_return — «התחברות עם Google» comes back to the window that asked, and only to it (DGO-1418).

    python3 apps/drive/test_oauth_return.py        (flask + requests: the drive's image has them)

What is asked: start makes a secret, gives connections only its sha256 and the screen the secret — in the body,
never in an address; a start with no return page is refused (it would be the broker's own, unbound consent), and so
is a Google address that is not https; without the screen, a page keeps the secret in the consent's own slot and
goes to Google; the return page (GET) asks connections nothing — it resolves `finish` against its own address (the
console injects a base at the app's mount), hands over the secret of ITS consent, removes it only on the app's own
answer (X-Dgo-Oauth), and when none came keeps it for a reload and leaves the screen's poller to decide; a consent
connections did not relay is never handed out; finish forwards code, state and the secret, says in words what
connections answered, and takes no body that is not an object; a cancelled consent asks nothing; nothing from
outside can end a script. Connections is replaced.
"""
import hashlib
import importlib
import os
import re
import sys
import tempfile
import types
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.environ.setdefault("DRIVE_DATA", tempfile.mkdtemp(prefix="drive-oauth-"))


def _have(name, **attrs):
    try:
        importlib.import_module(name)
    except Exception:                               # noqa: BLE001 — a driver nothing here calls
        mod = types.ModuleType(name)
        mod.__dict__.update(attrs)
        sys.modules[name] = mod


_have("psycopg2", OperationalError=Exception, InterfaceError=Exception, connect=None)
_have("psycopg2.pool", ThreadedConnectionPool=None)
sys.modules["psycopg2"].pool = sys.modules["psycopg2.pool"]

import requests  # noqa: E402 — the real package: the routes call requests.get / requests.post


def _refuse(*a, **kw):
    raise requests.ConnectionError("no connections in this test")


requests.get = requests.post = _refuse            # what the app asks while it loads fails at once
import app  # noqa: E402

FAILS = []
RET = "http://console.localhost:8080/a/drive.hp-laptop/oauth/google/return"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth?state=r1.x"
CALLS = []
ANSWER = {}


class Resp:
    def __init__(self, code, doc):
        self.status_code, self._doc = code, doc

    def json(self):
        return self._doc


def fake_get(url, params=None, timeout=None, **kw):
    CALLS.append(("GET", url, dict(params or {})))
    return Resp(200, {"authorize_url": ANSWER.get("authorize_url", AUTH), "relayed": ANSWER.get("relayed_flag", True)})


def fake_post(url, json=None, timeout=None, **kw):
    CALLS.append(("POST", url, dict(json or {})))
    return Resp(*ANSWER.get("relayed", (200, {"ok": True, "made": [{"id": "drive_google_oauth-1",
                                                                    "account_hint": "owner@example.com"}]})))


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def start(check_=True, ret=RET):
    q = ("check=1&" if check_ else "") + (("ret=" + urllib.parse.quote(ret, safe="")) if ret else "")
    return c.get("/oauth/google/start?" + q)


c = app.app.test_client()


def main() -> int:
    requests.get, requests.post = fake_get, fake_post
    # since the split (DGO-1500) the door is the one an engine names in its /ops: drive-google's
    app.engines.invalidate = lambda *a, **kw: None
    app.engines.oauth = lambda name: ({"grant": "google-workspace-grant", "protocol": "drive_google_oauth",
                                       "provider": "Google", "engine": "google",
                                       "connected": "Google Drive ו־Gmail של החשבון זמינים עכשיו בלשכה.",
                                       "connected_read_only": "Google Drive של החשבון זמין עכשיו בלשכה, לקריאה בלבד."}
                                      if name == "google" else None)

    # ── start, from the screen ──
    r = start()
    d = r.get_json() or {}
    sent = CALLS[-1][2] if CALLS else {}
    check(r.status_code == 200 and d.get("authorize_url") == AUTH and d.get("bind"), "the screen gets Google's address and a secret")
    check(sent.get("bind") == hashlib.sha256(d.get("bind", "").encode()).hexdigest(), "connections gets only the secret's sha256")
    check(sent.get("ret") == RET and sent.get("as_instance") == "1", "…with the return page, for an account")
    check(sent.get("protocol") == "drive_google_oauth",
          "…and the protocol the door serves (connections narrows the consent to it where the office reads it only, EXU-24)")
    check(d.get("bind", "") not in str(CALLS[-1]), "the secret itself never reaches connections")
    check("no-store" in r.headers.get("Cache-Control", ""), "the answer that carries the secret is not cached")
    check((start().get_json() or {}).get("bind") not in (None, d.get("bind")), "every consent has a secret of its own")
    n = len(CALLS)
    r = start(ret="")
    check(r.status_code == 400 and len(CALLS) == n and "כתובת החזרה" in (r.get_json() or {}).get("error", ""),
          "a start with no return page is refused, and connections is not asked")
    check(start(check_=False, ret="").status_code == 400, "…from a link too")
    n = len(CALLS)
    check(start(ret="   ").status_code == 400 and len(CALLS) == n, "…and a return page of blanks is no return page")
    # DGO-1634: connections' refusal reaches the screen whole — its sentence, what Google said, and where it is fixed
    said = "ההתחברות עם Google עוד לא פתוחה בלשכה הזו: מזהה ההתחברות שלה (OAuth client) נמחק אצל Google."
    real_get = requests.get
    for page, passed in (("https://console.cloud.google.com/apis/credentials", "https://console.cloud.google.com/apis/credentials"),
                         ("javascript:alert(1)", None)):
        requests.get = lambda url, params=None, timeout=None, p=page, **kw: Resp(409, {
            "error": said, "provider_error": "invalid_client", "help_url": p})
        r = start()
        d = r.get_json() or {}
        check(r.status_code == 409 and d.get("error") == said and d.get("provider_error") == "invalid_client"
              and d.get("help_url") == passed and "bind" not in d,
              "a refused consent: the screen gets the sentence and " + ("the page where it is fixed" if passed
                                                                         else "no link that is not https"))
    requests.get = real_get
    ANSWER["authorize_url"] = "http://accounts.example/auth?state=r1.x"
    r = start()
    check(r.status_code == 502 and "bind" not in (r.get_json() or {}), "a Google address that is not https is not handed to a window")
    ANSWER.pop("authorize_url")
    ANSWER["relayed_flag"] = False
    r = start()
    check(r.status_code == 502 and "bind" not in (r.get_json() or {}),
          "a consent connections did not relay (the broker's own, unbound) is not handed to a window")
    ANSWER.pop("relayed_flag")

    # ── start, without the screen ──
    r = start(check_=False)
    page = r.get_data(as_text=True)
    kept = re.search(r'setItem\("dgo-oauth-bind:r1\.x","([^"]+)"\)', page)
    check(r.status_code == 200 and kept and f'location.replace("{AUTH}")' in page,
          "without the screen, a page keeps the secret in this consent's own slot and goes on to Google")
    check(kept and CALLS[-1][2].get("bind") == hashlib.sha256(kept.group(1).encode()).hexdigest(),
          "…the secret whose sha256 connections keeps")
    ANSWER["authorize_url"] = "https://accounts.google.com/auth?state=r1.z&x=</script><script>alert(1)//"
    page = start(check_=False).get_data(as_text=True)
    check("</script><script>alert" not in page and "\\u003c/script>" in page, "nothing in Google's address can end the script")
    ANSWER.pop("authorize_url")

    # ── the return page ──
    n = len(CALLS)
    r = c.get("/oauth/google/return?code=C1&state=S1")
    page = r.get_data(as_text=True)
    check(r.status_code == 200 and len(CALLS) == n, "the return page asks connections nothing")
    check('fetch(new URL("finish",location.href)' in page and 'fetch("finish"' not in page,
          "it resolves finish against its own address, not the base the console injects at the app's mount")
    check('key="dgo-oauth-bind:"+(q.get("state")||"")' in page and "getItem(key)" in page,
          "it hands over the secret of ITS consent (the slot of its state)")
    check(page.index("removeItem(key)") > page.index(".then(function(h)") and 'r.headers.get("X-Dgo-Oauth")' in page,
          "it removes the secret only on the app's own answer (X-Dgo-Oauth), never on another HTML page")
    check("ok:false" not in page,
          "when no answer of the app's came, it keeps the secret for a reload and leaves the screen's poller to decide")

    # ── finish ──
    r = c.post("/oauth/google/finish", json={"code": "C1", "state": "S1", "error": "", "bind": "the-secret"})
    page = r.get_data(as_text=True)
    check(CALLS[-1][0] == "POST" and CALLS[-1][1].endswith("/oauth/relayed")
          and CALLS[-1][2] == {"code": "C1", "state": "S1", "bind": "the-secret"}, "finish hands code, state and the secret to connections")
    check(r.status_code == 200 and "החשבון חובר" in page and "owner@example.com" in page
          and r.headers.get("X-Dgo-Oauth") == "1", "…and says which account was connected, on a page marked as the app's answer")
    check("Gmail" in page and "לקריאה בלבד" not in page, "…a full consent says Drive and Gmail")
    ANSWER["relayed"] = (200, {"ok": True, "read_only": True, "made": [{"id": "drive_google_oauth-1",
                                                                         "protocol": "drive_google_oauth",
                                                                         "account_hint": "reader@example.com"}]})
    page = c.post("/oauth/google/finish", json={"code": "C9", "state": "S9", "bind": "the-secret"}).get_data(as_text=True)
    check("לקריאה בלבד" in page and "Gmail" not in page, "a read-only consent (EXU-24) says Drive alone, read-only")
    ANSWER.pop("relayed", None)
    n = len(CALLS)
    r = c.post("/oauth/google/finish", json={"error": "access_denied", "state": "S1", "bind": "the-secret"})
    check(len(CALLS) == n and "ההתחברות בוטלה" in r.get_data(as_text=True), "a cancelled consent asks nothing")
    r = c.post("/oauth/google/finish", data='["a", "list"]', content_type="application/json")
    check(r.status_code in (200, 400) and CALLS[-1][2] == {}, "a body that is not an object is taken as empty, never a server error")
    ANSWER["relayed"] = (403, {"ok": False, "error": "this consent was started in another browser"})
    r = c.post("/oauth/google/finish", json={"code": "C2", "state": "S2"})
    check(r.status_code == 400 and "another browser" in r.get_data(as_text=True) and "bind" not in CALLS[-1][2],
          "a completion without the secret is refused by connections, and said")
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
