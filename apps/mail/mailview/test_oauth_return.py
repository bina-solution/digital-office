"""test_oauth_return — the mail screen's «התחברות עם Google» comes back to the window that asked, and only to it
(DGO-1418). The same rule as apps/drive/test_oauth_return.py, for the mail's own routes.

    python3 apps/mail/mailview/test_oauth_return.py        (flask + requests: the mail's image has them)

What is asked: start gives connections only the sha256 of a secret and the screen the secret, in the body; a start
with no return page, or a Google address that is not https, is refused; without the screen a page keeps the secret
in its consent's own slot and goes to Google; the return page (GET) asks connections nothing, resolves `finish`
against its own address, and removes the secret only once the app answered; finish forwards code, state and the
secret; a cancelled consent asks nothing. Connections is replaced (the app's `_HTTP`).
"""
import hashlib
import os
import re
import sys
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app  # noqa: E402

FAILS = []
RET = "https://console.staging.digital-office.co.il/a/mailview/oauth/google/return"
AUTH = "https://accounts.google.com/o/oauth2/v2/auth?state=r1.y"
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
    return Resp(*ANSWER.get("relayed", (200, {"ok": True, "made": [{"id": "mail_gmail_oauth-1",
                                                                    "account_hint": "owner@example.com"}]})))


def check(cond, what):
    print(("PASS  " if cond else "FAIL  ") + what)
    if not cond:
        FAILS.append(what)


def main() -> int:
    app._HTTP.get, app._HTTP.post = fake_get, fake_post
    c = app.app.test_client()
    start = lambda ck=True, ret=RET: c.get("/oauth/google/start?" + ("check=1&" if ck else "")  # noqa: E731
                                           + (("ret=" + urllib.parse.quote(ret, safe="")) if ret else ""))

    r = start()
    d = r.get_json() or {}
    sent = CALLS[-1][2] if CALLS else {}
    check(r.status_code == 200 and d.get("authorize_url") == AUTH and d.get("bind"), "the screen gets Google's address and a secret")
    check(sent.get("bind") == hashlib.sha256(d.get("bind", "").encode()).hexdigest() and sent.get("ret") == RET,
          "connections gets the return page and only the secret's sha256")
    check(sent.get("protocol") == "mail_gmail_oauth",
          "…and the protocol this screen connects (Gmail alone where the office reads Drive only, EXU-24)")
    check(d.get("bind", "") not in str(CALLS[-1]) and "no-store" in r.headers.get("Cache-Control", ""),
          "the secret never reaches connections, and its answer is not cached")
    n = len(CALLS)
    check(start(ret="").status_code == 400 and start(ret="  ").status_code == 400 and len(CALLS) == n,
          "a start with no return page (or one of blanks) is refused, connections not asked")
    ANSWER["authorize_url"] = "http://accounts.example/auth?state=r1.y"
    check(start().status_code == 502, "a Google address that is not https is not handed to a window")
    ANSWER.pop("authorize_url")
    ANSWER["relayed_flag"] = False
    check(start().status_code == 502, "a consent connections did not relay (the broker's own, unbound) is not handed out")
    ANSWER.pop("relayed_flag")

    page = start(ck=False).get_data(as_text=True)
    kept = re.search(r'setItem\("dgo-oauth-bind:r1\.y","([^"]+)"\)', page)
    check(kept and f'location.replace("{AUTH}")' in page
          and CALLS[-1][2].get("bind") == hashlib.sha256(kept.group(1).encode()).hexdigest(),
          "without the screen, a page keeps the secret in this consent's own slot and goes on to Google")

    n = len(CALLS)
    page = c.get("/oauth/google/return?code=C1&state=S1").get_data(as_text=True)
    check(len(CALLS) == n and 'fetch(new URL("finish",location.href)' in page and 'fetch("finish"' not in page,
          "the return page asks connections nothing and resolves finish against its own address")
    check('key="dgo-oauth-bind:"+(q.get("state")||"")' in page and page.index("removeItem(key)") > page.index(".then(function(h)")
          and 'r.headers.get("X-Dgo-Oauth")' in page and "ok:false" not in page,
          "it hands over its consent's secret, removes it only on the app's own answer, and leaves a failure to the screen's poller")

    r = c.post("/oauth/google/finish", json={"code": "C1", "state": "S1", "error": "", "bind": "the-secret"})
    check(CALLS[-1][1].endswith("/oauth/relayed") and CALLS[-1][2] == {"code": "C1", "state": "S1", "bind": "the-secret"}
          and "החשבון חובר" in r.get_data(as_text=True) and r.headers.get("X-Dgo-Oauth") == "1",
          "finish hands code, state and the secret to connections, and says so on a page marked as its answer")
    n = len(CALLS)
    r = c.post("/oauth/google/finish", json={"error": "access_denied", "state": "S1"})
    check(len(CALLS) == n and "ההתחברות בוטלה" in r.get_data(as_text=True), "a cancelled consent asks nothing")
    r = c.post("/oauth/google/finish", data='["a", "list"]', content_type="application/json")
    check(r.status_code in (200, 400) and CALLS[-1][2] == {}, "a body that is not an object is taken as empty, never a server error")
    ANSWER["relayed"] = (403, {"ok": False, "error": "this consent was started in another browser"})
    r = c.post("/oauth/google/finish", json={"code": "C2", "state": "S2"})
    check(r.status_code == 400 and "another browser" in r.get_data(as_text=True), "a refusal by connections is said")
    print(f"{'OK' if not FAILS else 'FAILED'}: {len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
