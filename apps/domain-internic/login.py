"""login — signing the office browser in to the InterNIC portal, by itself, once per call.

The owner, 2026-11-08 (DGO-1473): the provider app «depends on browser and mail and secrets so it can
complete the full flow of login and mail validation if needed». So:

  1. Is the browser signed in already? (`portal.state`) — then nothing is touched at all.
  2. Is the credential there? The row `domain-internic-login` in חיבורים ומפתחות (its STATUS only).
  3. The secret never passes through this app. The row declares the portal's address (`app.url`), so the
     office browser's own bridge (apps/browser42/logins.py) mirrors it into Chrome's password store, keyed
     by that origin — at every browser start and on `bbox b42 logins sync`. Here the user-name field is
     CLICKED (a real gesture) and Chrome's saved login is picked from its own list; what this app reads
     back is the fields' LENGTHS. Typing it here instead would need the browser's DevTools port, which the
     browser keeps to itself (DGO-983), or the MCP's type tool, whose reply echoes the text it typed.
  4. Submit, and read what the portal answers: signed in, a code sent by e-mail, a refusal, a captcha.
  5. A code: read it from the office's mail (mail.v1 `search` + `get` on the mailbox the setting
     DOMAIN_INTERNIC_MAIL_CONNECTION names), type it (a one-time code, its reply dropped), submit, check.

ONE attempt per call and ONE call at a time (a lock), no retry anywhere: a registrar locks an account that
guesses. A captcha, an unknown form, a refused password or a missing code stops with its own state and the
live view, and the fields are emptied on every stop, so no filled password is left on a shared screen.
"""
from __future__ import annotations

import os
import re
import threading
import time

import requests

import browser_session as bs
import portal

PORTAL = "internic"
CONNECTION = "domain-internic-login"
CONNECTIONS_URL = os.environ.get("CONNECTIONS_URL", "http://connections:8990").rstrip("/")
MAIL_URL = os.environ.get("MAIL_URL", "http://mailapi:8970").rstrip("/")
MAIL_CONNECTION = os.environ.get("DOMAIN_INTERNIC_MAIL_CONNECTION", "").strip()
LIVE_VIEW = "/a/browser42/"
_BUSY = threading.Lock()

# ── the form, found by what its fields MEAN (the portal renders its password as a plain textbox with a
# Hebrew placeholder: browser_session.state's docstring). These expressions hold no secret. ─────────────
_VISIBLE = "(el) => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length) && !el.disabled"
_WORDS = "(el) => [el.name, el.id, el.placeholder, el.getAttribute('aria-label'), el.autocomplete].join(' ')"
PASS_JS = ("(() => { const vis = %s, words = %s;"
           " const ins = [...document.querySelectorAll('input')].filter(vis);"
           " return ins.find(i => i.type === 'password')"
           " || ins.find(i => /pass|סיסמ/i.test(words(i))) || null; })()" % (_VISIBLE, _WORDS))
USER_JS = ("(() => { const vis = %s, words = %s, pw = %s;"
           " const ins = [...document.querySelectorAll('input')].filter(vis)"
           "   .filter(i => i !== pw && !['hidden','checkbox','radio','submit','button'].includes(i.type));"
           " return ins.find(i => i.type === 'email')"
           " || ins.find(i => /user|mail|login|שם משתמש|משתמש|דוא|אימייל|מייל/i.test(words(i)))"
           " || ins[0] || null; })()" % (_VISIBLE, _WORDS, PASS_JS))
CODE_JS = ("(() => { const vis = %s, words = %s;"
           " const ins = [...document.querySelectorAll('input')].filter(vis)"
           "   .filter(i => !['hidden','checkbox','radio','submit','button','password','email'].includes(i.type));"
           " return ins.find(i => i.autocomplete === 'one-time-code')"
           " || ins.find(i => /otp|code|token|verif|קוד|אימות/i.test(words(i)))"
           " || null; })()" % (_VISIBLE, _WORDS))
# what the page holds, as facts and lengths only — never a value
PAGE_JS = ("() => { const t = (document.body && document.body.innerText || '').slice(0, 4000);"
           " const pw = %s, us = %s, code = %s;"
           " const vis = %s;"
           " const cap = [...document.querySelectorAll('iframe[src*=captcha], iframe[title*=captcha i], #px-captcha, .h-captcha')]"
           "   .some(vis);"
           " return JSON.stringify({url: location.href, origin: location.origin, ready: document.readyState,"
           "  password: !!pw, password_len: pw ? (pw.value || '').length : 0, user_len: us ? (us.value || '').length : 0,"
           "  code: !!code, captcha: cap || /אני לא רובוט|I.m not a robot/i.test(t),"
           "  refused: /שגוי|לא נכונ|incorrect|invalid|wrong|נכשל/i.test(t)}); }"
           % (PASS_JS, USER_JS, CODE_JS, _VISIBLE))
_SUBMIT = (" const form = f && f.form; const vis = %s;"
           " const btn = [...(form || document).querySelectorAll('button, input[type=submit]')].filter(vis)"
           "   .find(b => b.type === 'submit' || /כניס|התחבר|login|sign in|שלח|אישור|המשך|submit|verify/i"
           "   .test(b.innerText || b.value || ''));"
           " if (btn) { btn.click(); return 'clicked'; }"
           " if (form) { form.requestSubmit ? form.requestSubmit() : form.submit(); return 'submitted'; }"
           " return 'none'; }" % _VISIBLE)
# The submit CHECKS THE FORM ITSELF, in the same evaluate that clicks: the right site, and every field it sends
# filled. Between a length read and a click the shared tab can reload (another screen asking the portal's
# state), and a click on an empty form is a failed attempt on the registrar's account (the second reader).
SUBMIT_LOGIN_JS = ("() => { if (location.origin !== '%%ORIGIN%%') return 'wrong_page';"
                   " const us = %s, pw = %s; if (!us || !pw || !(us.value || '').length || !(pw.value || '').length)"
                   " return 'empty'; const f = pw;" % (USER_JS, PASS_JS)) + _SUBMIT
SUBMIT_CODE_JS = ("() => { if (location.origin !== '%%ORIGIN%%') return 'wrong_page';"
                  " const code = %s; if (!code || !(code.value || '').length) return 'empty'; const f = code;"
                  % CODE_JS) + _SUBMIT
MARK_USER_JS = ("() => { const el = %s; if (!el) return 'none'; el.setAttribute('data-dgo-login', 'user');"
                " return 'marked'; }" % USER_JS)
MARK_CODE_JS = ("() => { const el = %s; if (!el) return 'none'; el.setAttribute('data-dgo-login', 'code');"
                " return 'marked'; }" % CODE_JS)
CLEAR_JS = ("() => { for (const el of [%s, %s, %s]) { if (el && 'value' in el) { el.value = '';"
            " el.dispatchEvent(new Event('input', {bubbles: true})); } } return 'cleared'; }"
            % (USER_JS, PASS_JS, CODE_JS))


class LoginStop(Exception):
    def __init__(self, state: str, reason: str, **more):
        super().__init__(reason)
        self.state, self.reason, self.more = state, reason, more

    def answer(self) -> dict:
        return {"ok": False, "state": self.state, "reason": self.reason, "live_view": LIVE_VIEW, **self.more}


def configured() -> dict:
    """Whether the row this app contributes (`domain-internic-login`) is filled — BOTH its fields. The
    password: the row's STATUS in the plane's catalog (`GET /api/connections`: `healthy` once typed,
    `unset`/`missing` before or for a placeholder); it reflects the primary field only. The user name: its
    field in `GET /api/cred/<id>` has a value (it is not a secret; its value is tested, never kept). A
    contributed row is a catalog row, not an instance: the instances listing never shows it."""
    try:
        r = requests.get(f"{CONNECTIONS_URL}/api/connections", timeout=10)
        rows = r.json().get("connections") or []
        row = next((x for x in rows if isinstance(x, dict) and x.get("id") == CONNECTION), None)
        user = False
        if row is not None:
            c = requests.get(f"{CONNECTIONS_URL}/api/cred/{CONNECTION}", timeout=10).json()
            user = any(isinstance(f, dict) and f.get("key") == "DOMAIN_INTERNIC_USER" and bool(f.get("clear"))
                       for f in (c.get("fields") or []))
    except (requests.RequestException, ValueError, AttributeError):
        return {"known": False}
    status = (row or {}).get("status")
    return {"known": True, "declared": row is not None, "status": status, "user": user,
            "rows": [CONNECTION] if status == "healthy" and user else []}


def _eval(sess, fn: str):
    """Run code that holds no secret in the page; its JSON value back."""
    return bs._json_from_text(sess.call("browser_evaluate", {"function": fn}).get("text"))


def _result(sess, fn: str) -> str:
    """The value a string-returning evaluate gave, read from its `### Result` section ONLY: the MCP's reply
    also carries the code it ran (`### Ran Playwright code`), and that code contains every word it can
    return — a search of the whole reply always finds 'marked' (measured 2026-11-08)."""
    text = sess.call("browser_evaluate", {"function": fn}).get("text") or ""
    m = re.search(r"### Result\s*\n\s*\"([^\"]*)\"", text)
    return m.group(1) if m else ""


def _submit(sess, fn: str, origin: str) -> str:
    return _result(sess, fn.replace("%ORIGIN%", origin))     # the %-formatting above left one % each side


def _page(sess, origin: str) -> dict:
    page = _eval(sess, PAGE_JS) or {}
    if page.get("origin") and page["origin"] != origin:
        # the tab is somewhere else than the portal: nothing is ever filled there
        raise LoginStop("wrong_page", f"the browser's tab is on {page['origin']}, not the portal")
    return page


def _settle(sess, origin: str, seconds: int = 25) -> dict:
    """What the portal shows once the submit has been answered: poll until a LOADED page has no password
    field, asks a code, refused, or shows a captcha — never longer than `seconds`."""
    deadline, seen = time.time() + seconds, {}
    time.sleep(2)
    while time.time() < deadline:
        try:
            seen = _eval(sess, PAGE_JS) or {}
        except bs.SessionError:
            seen = {}
        loaded = seen.get("ready") == "complete" and (seen.get("url") or "").startswith(origin)
        if loaded and (not seen.get("password") or seen.get("code") or seen.get("refused") or seen.get("captcha")):
            return seen
        time.sleep(2)
    return seen


def _clear(sess) -> None:
    try:
        sess.call("browser_evaluate", {"function": CLEAR_JS})
    except bs.SessionError:
        pass


def mail_code(since: float, wait: int = 120) -> str | None:
    """The newest code InterNIC sent since `since`, from the office's mail: mail.v1 search, then the
    message itself — a 4–8 digit number right after a word that says it is a code. A mail service that
    does not answer is a stop of its own (`mail_unreachable`), never two minutes of «no code came»."""
    if not MAIL_CONNECTION:
        return None
    deadline = time.time() + wait
    pattern = re.compile(r"(?:קוד|code|סיסמה חד|אימות|verification)[^0-9]{0,40}(\d{4,8})", re.I)
    while time.time() < deadline:
        try:
            r = requests.post(f"{MAIL_URL}/search", timeout=30, json={
                "connection_id": MAIL_CONNECTION, "query": "internic OR interspace OR אינטרניק",
                # from the SUBMIT on: a code a stopped earlier run asked for is never the one typed now
                "since_ts": int(since), "limit": 5})
        except requests.RequestException as e:   # MissingSchema/InvalidURL too: raised before `r` exists
            raise LoginStop("mail_unreachable", f"the office's mail did not answer at {MAIL_URL} ({type(e).__name__})")
        # A decode of its own: requests' JSONDecodeError is BOTH a RequestException and a ValueError, so in the try
        # above an answer that was not JSON (a 502 page) was reported as no answer at all (the second reader).
        try:
            doc = r.json()
        except ValueError:
            raise LoginStop("mail_unreachable", f"the office's mail answered HTTP {r.status_code} with no JSON")
        data = doc.get("data") if isinstance(doc, dict) and isinstance(doc.get("data"), dict) else doc
        msgs = [m for m in ((data or {}).get("messages") or []) if isinstance(m, dict)] if isinstance(data, dict) else []

        def uid(m):
            try:
                return int(m.get("uid") or 0)
            except (TypeError, ValueError):
                return 0
        for m in sorted(msgs, key=lambda x: -uid(x)):
            try:
                g = requests.get(f"{MAIL_URL}/message/{uid(m)}", timeout=30,
                                 params={"connection_id": MAIL_CONNECTION})
                body = g.json()
            except (requests.RequestException, ValueError):
                continue
            body = body.get("data") if isinstance(body, dict) and isinstance(body.get("data"), dict) else body
            if not isinstance(body, dict):
                continue
            text = " ".join(str(body.get(k) or "") for k in ("subject", "text", "snippet", "body"))
            found = pattern.search(text)
            if found:
                return found.group(1)
        time.sleep(8)
    return None


def sign_in(endpoint: str | None = None) -> dict:
    """One sign-in at a time (`_BUSY`), and while it runs nothing else of this app drives the shared tab
    (`bs.driving()`, the lock every panel read and write already takes): a state read between the fill and
    the submit reloads the page (the second reader)."""
    if not _BUSY.acquire(blocking=False):
        return {"ok": False, "state": "busy", "reason": "a sign-in is already running — one at a time"}
    try:
        with bs.driving():
            return _sign_in(endpoint)
    except bs.SessionError as e:
        return {"ok": False, "state": e.state, "reason": e.message}
    finally:
        _BUSY.release()


def busy() -> bool:
    return _BUSY.locked()


def _sign_in(endpoint: str | None) -> dict:
    s = portal.SCRIPTS[PORTAL]
    origin = s["origin"]
    started = time.time()
    sess = portal.session_for(PORTAL, endpoint)
    st = sess.state(origin)
    if st.get("authenticated"):
        return {"ok": True, "state": "ok", "already_signed_in": True, "url": st.get("url")}
    if st.get("state") not in ("needs_human_login", "session_expired"):
        # blocked by the WAF, the browser away, a page that did not load: nothing to fill
        return {"ok": False, **st, "live_view": LIVE_VIEW}
    cred = configured()
    if not cred.get("known"):
        return LoginStop("credential_plane_unreachable", "the credential plane did not answer — nothing was tried"
                         ).answer()
    if not cred.get("rows"):
        missing = "user name" if cred.get("status") == "healthy" else "user name and password"
        return LoginStop("credential_not_configured",
                         f"the credential plane holds no InterNIC {missing}. Open חיבורים ומפתחות "
                         f"(/a/connections/), fill '{CONNECTION}' once — then the office signs in by itself",
                         screen="/a/connections/", status=cred.get("status")).answer()
    filled = False
    try:
        sess.open(origin + (s.get("login_path") or "/"), snapshot=False)
        filled = True        # Chrome may fill a saved login on load: from here every stop empties the form
        before = _page(sess, origin)
        if before.get("captcha"):
            raise LoginStop("captcha", "the portal shows a captcha: a person passes it in the live view")
        if not before.get("password"):
            st = sess.state()
            if st.get("authenticated"):
                filled = False
                return {"ok": True, "state": "ok", "already_signed_in": True, "url": st.get("url")}
            raise LoginStop("login_selector_missing", "the sign-in page has no password field the app recognises",
                            url=before.get("url"))
        # Chrome's own saved login: a real click on the user field, then its list's first entry
        if _result(sess, MARK_USER_JS) != "marked":
            raise LoginStop("login_selector_missing", "the sign-in page has no user-name field the app recognises")
        clicked = sess.call("browser_click", sess.element_args("browser_click", _marked("user")))
        if clicked.get("is_error"):
            raise LoginStop("login_selector_missing", "the user-name field could not be clicked")
        time.sleep(1)
        now = _page(sess, origin)
        if not (now.get("user_len") and now.get("password_len")):
            # Chrome's list is open under the field: ArrowDown highlights its first login, Tab accepts it.
            # Never Enter: with no list open, Enter submits an EMPTY form — a failed attempt on the account.
            sess.call("browser_press_key", {"key": "ArrowDown"})
            sess.call("browser_press_key", {"key": "Tab"})
            time.sleep(1)
            now = _page(sess, origin)
        if not (now.get("user_len") and now.get("password_len")):
            raise LoginStop("not_in_browser_store",
                            "the office browser's password store has no login for the portal yet — the row is "
                            "mirrored into it at every browser start and by `./bbox b42 logins sync`",
                            how="./bbox b42 logins sync")
        submitted_at = time.time()
        sent = _submit(sess, SUBMIT_LOGIN_JS, origin)
        if sent not in ("clicked", "submitted"):
            raise LoginStop("login_selector_missing" if sent != "wrong_page" else "wrong_page",
                            f"the form was not sent ({sent or 'no answer'}): nothing reached the portal")
        after = _settle(sess, origin)
        if after.get("captcha"):
            raise LoginStop("captcha", "the portal answered with a captcha")
        if after.get("code"):
            # read the page where it IS: a state check with the origin would navigate off the code page
            res = _finish_with_code(sess, origin, submitted_at, started)
            filled = not res.get("ok")
            return res
        st = sess.state()
        if st.get("authenticated"):
            filled = False
            return {"ok": True, "state": "ok", "signed_in": True, "url": st.get("url"),
                    "seconds": round(time.time() - started, 1)}
        if after.get("refused") and after.get("password"):
            raise LoginStop("login_failed", "the portal refused the user name or password — not retried; "
                                            "check the row in חיבורים ומפתחות", screen="/a/connections/")
        return {"ok": False, **st, "live_view": LIVE_VIEW,
                "after_submit": {k: after.get(k) for k in ("url", "password", "code", "refused")}}
    except LoginStop as stop:
        if stop.state == "wrong_page":
            filled = False       # never run the page's own code on someone else's site
        return stop.answer()
    except bs.SessionError as e:
        return {"ok": False, "state": e.state, "reason": e.message, "live_view": LIVE_VIEW}
    finally:
        if filled:
            _clear(sess)


def _marked(mark: str) -> dict:
    """The field the page's own code marked `data-dgo-login=<mark>`, as a node the MCP acts on BY THAT
    MARK (its `target`): an accessible-name lookup could land on another field whose name contains the same
    word (the second reader) — and on this portal the password's aria-label reads «כתובת דוא״ל» (measured)."""
    return {"name": f"the {mark} field", "css": f'[data-dgo-login="{mark}"]', "ref": None}


def _finish_with_code(sess, origin: str, submitted_at: float, started: float) -> dict:
    """`started` is the sign-in's own start (the answer reports the whole sign-in's seconds): read here while it
    lived only in _sign_in, a code sign-in that SUCCEEDED raised NameError on its way out (gate G80, DGO-1496)."""
    code = mail_code(submitted_at)
    if not code:
        why = ("no mailbox is named for InterNIC's codes (DOMAIN_INTERNIC_MAIL_CONNECTION)" if not MAIL_CONNECTION
               else "no code from InterNIC reached the mailbox in two minutes")
        raise LoginStop("needs_mail_code", f"the portal asked for a code sent by e-mail, and {why}")
    if _result(sess, MARK_CODE_JS) != "marked":
        raise LoginStop("login_selector_missing", "the code field is gone")
    # a one-time code, minutes from expiry: typed through the MCP, its reply (which echoes it) dropped here
    typed = sess.call("browser_type", {**sess.element_args("browser_type", _marked("code")), "text": code})
    del code
    if typed.get("is_error"):
        raise LoginStop("login_selector_missing", "the code could not be typed — nothing was sent")
    sent = _submit(sess, SUBMIT_CODE_JS, origin)
    if sent not in ("clicked", "submitted"):
        raise LoginStop("login_selector_missing" if sent != "wrong_page" else "wrong_page",
                        f"the code was not sent ({sent or 'no answer'})")
    _settle(sess, origin)
    st = sess.state()
    if st.get("authenticated"):
        return {"ok": True, "state": "ok", "signed_in": True, "mail_code": True, "url": st.get("url"),
                "seconds": round(time.time() - started, 1)}
    return {"ok": False, **st, "mail_code": True, "live_view": LIVE_VIEW}
