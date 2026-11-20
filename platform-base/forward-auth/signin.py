"""signin.py — WHO a request's person is, asked of the office's own sign-in: the ONE copy every Python app's door uses.

    sys.path.insert(0, "/opt/dgo")                          # built into the app's image (below)
    import signin
    SIGNIN = signin.SignIn(os.environ.get("ASSETS_WHOAMI_URL", signin.WHOAMI_URL))
    app.middleware("http")(signin.door(SIGNIN, token=lambda: TOKEN, loopback_env="ASSETS_TRUST_LOOPBACK",
                                       person_reads=PERSON_READS, words=signin.Words(...)))

WHY ONE FILE. Two apps (assets, examplem-io) each carried these hundred lines, word for word, and a door written
twice drifts (the coordinator's review, 2026-11-10). A change to how a person is recognised is a change here.

HOW AN APP HAS IT: built into its image, never mounted and never copied into the app's directory — its compose
names this folder as a second build context (`build.additional_contexts: {dgo: ../../platform-base/forward-auth}`)
and its Dockerfile copies it (`COPY --from=dgo signin.py /opt/dgo/signin.py`). So a change here rebuilds the image
on the next `dc up --build` (a bind of one file could stay on the old one), and the app's tests run in its image
(gate G72's `--in-images`) find it where the app does — the image's copy, so a change here alone is judged there
only after that rebuild. A test run from the tree finds the tree's copy instead. Every builder passes the context:
compose, `ccr_build_serial` (scripts/lib.sh) and packaging/build-images.sh (`--build-context`).

WHAT IS TRUSTED. Never a header: the console's door forwards every header a caller sends, and anything on the office
network can call the door, so an `X-authentik-*` pair proves nothing (the assets app's second reader, 2026-11-10).
What the sign-in itself vouches for is the signed session cookie it gave a browser (`dgo_session`, forward-auth's HMAC
over the name and the expiry), which the door forwards too: the app hands that cookie — and only it (and authentik's,
which /whoami still reads during a migration) — to forward-auth's /whoami, and believes its answer.
What this does NOT close: the door hands that cookie to EVERY local app, and it is not bound to a host, so an app that
records its callers' cookies could replay one for its 14 days — a door-level fix with its own item (DGO-1763). An
office with no forward-auth answers nothing there: no person, the CLI and the token only.

Who passes `door()`, in order: /healthz; a service with the app's token (`Authorization: Bearer`); the app's own CLI
on loopback (unless `<APP>_TRUST_LOOPBACK=0`); then a PERSON an admin of the office, for a GET or HEAD of one of the
app's `person_reads` only — or, for an app that names `person_writes`, any method on those paths, sent from the app's
own page (a browser's `Sec-Fetch-Site` that is present says `same-origin`). Anyone else is refused in words: the page
for the screen, a JSON detail for the API. A person who passes is named to the app in `request.scope["dgo.person"]`,
so a change it records says WHO made it.

Standard library only, but `door()` builds FastAPI responses, so it imports FastAPI when it is called.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import http.client
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

WHOAMI_URL = "http://forward-auth:9078/whoami"
SESSION_COOKIES = ("dgo_session", "authentik_session")   # the sign-in's own, and authentik's it reads in a migration
ADMIN_GROUPS = frozenset({"admins", "authentik Admins"})  # forward-auth's, and authentik's own name for the same group
LOOPBACK = ("127.0.0.1", "::1")
SEEN_TTL = 10.0                                           # a sign-out or a removed admin holds at most this long
_GO_SPACE = " \t\r\n"                                     # textproto.TrimString's set — not str.strip()'s Unicode one


class SignIn:
    """The office's sign-in as one app asks it: its /whoami address and the answers held for SEEN_TTL seconds."""

    def __init__(self, url: str = WHOAMI_URL, admin_groups=ADMIN_GROUPS, ttl: float = SEEN_TTL):
        self.url = url
        self.admin_groups = frozenset(admin_groups)
        self.ttl = ttl
        self.seen: dict = {}                              # sha256(cookies) → (when asked, (name, groups) | None)

    def who_is(self, cookie: str, now=None):
        """(name, groups) of the session these cookies are, as forward-auth says, held `ttl` s; None when they are no
        session. Only an ANSWER is held (a session, or the sign-in's 401): a sign-in that did not answer is asked
        again next time, so a moment's outage of forward-auth does not shut the owner out for the hold. The hold runs
        on the monotonic clock, so a clock stepped back cannot stretch it."""
        now = time.monotonic() if now is None else now
        key = hashlib.sha256(cookie.encode()).hexdigest()
        hit = self.seen.get(key)
        if hit and 0 <= now - hit[0] < self.ttl:
            return hit[1]
        got = None
        try:
            req = urllib.request.Request(self.url, headers={"Cookie": cookie})
            with urllib.request.urlopen(req, timeout=4) as r:
                me = json.loads(r.read() or b"{}")
            if not isinstance(me, dict):                  # an answer that is not an object: not an answer
                return None
            groups = me.get("groups") if isinstance(me.get("groups"), list) else []
            if me.get("signed_in") and me.get("username"):
                got = (str(me["username"]), frozenset(str(g) for g in groups))
        except urllib.error.HTTPError as e:               # the sign-in answered: 401 = no such session
            if e.code != 401:
                return None
        except (OSError, ValueError, http.client.HTTPException):   # no sign-in service, a broken or non-JSON body
            return None
        if len(self.seen) > 512:
            self.seen.clear()
        self.seen[key] = (now, got)
        return got

    @staticmethod
    def session_cookie(cookie_lines) -> str:
        """The sign-in's own cookies among a request's Cookie lines, as one Cookie header — never its other cookies.
        Read as forward-auth (Go's net/http) reads them: every line in order, split on `;`, trimmed of Go's spaces
        only, each part kept whose name is one of the two — a bare or empty one too, since Go reads that one first
        and stops. So /whoami judges the very cookie the edge judged, and no value is unquoted into a `;` or a line
        break."""
        raw = "; ".join(cookie_lines)
        return "; ".join(p.strip(_GO_SPACE) for p in raw.split(";")
                         if p.strip(_GO_SPACE).split("=", 1)[0].strip(_GO_SPACE) in SESSION_COOKIES)

    def person(self, cookie_lines):
        """(name, an admin of the office) for the session the lines carry, or None when they carry none."""
        cookie = self.session_cookie(cookie_lines)
        who = self.who_is(cookie) if cookie else None
        return (who[0], bool(who[1] & self.admin_groups)) if who else None


@dataclass(frozen=True)
class Words:
    """What a refused caller reads, in the app's own words."""
    title: str              # the page's <title>, the app's name («הלוואות»)
    no_grant: str           # the page for a signed-in person who may not read it
    no_session: str         # the page for a browser with no session the sign-in vouches for
    api_no_grant: str       # the API's detail for that person
    api_no_session: str     # the API's detail for a caller with neither a token nor a session


def page(title: str, text: str) -> str:
    """A refusal as a page a person reads: the app's name and one sentence, right to left."""
    return (f"<!doctype html><html lang='he' dir='rtl'><meta charset='utf-8'><title>{html.escape(title)}</title>"
            f"<body style='font-family:system-ui,sans-serif;padding:24px'><p>{html.escape(text)}</p></body></html>")


def bearer_ok(authorization: str | None, token: str) -> bool:
    """The request carries the app's token — compared in constant time; an app with no token admits no service."""
    auth = authorization or ""
    return bool(token) and auth.startswith("Bearer ") and hmac.compare_digest(auth[7:].strip().encode(), token.encode())


def door(sign_in: SignIn, *, token, loopback_env: str, person_reads, words: Words, screen: str = "/",
         person_writes=()):
    """The app's HTTP middleware: `app.middleware("http")(door(...))`. `token` is the app's token, or a function
    returning it now (a test may change it); `person_reads` the paths a person's GET may read — the screen and its
    reads; `screen` the path whose refusal is a page, not JSON. `person_writes` (empty by default, so an app that
    does not name it is exactly as before): the paths an ADMIN may also change from the screen — any method — for
    an app whose screen is where its records are kept («ישויות», DGO-2101). Either may be a set of paths or any
    object answering `path in it` (a prefix rule). Such a change is taken only from the app's own page: a browser
    names where a request comes from (`Sec-Fetch-Site`), and one that names anything but `same-origin` — a sibling
    host of the office's domain shares the session cookie (SameSite=Lax) — is refused; the app takes a change only
    as JSON, exactly (its `_body`), which no page of another site can send unasked. The person let in is named to
    the app in `request.scope["dgo.person"]`."""
    token_now = token if callable(token) else (lambda: token)
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import HTMLResponse, JSONResponse

    no_grant, no_session = page(words.title, words.no_grant), page(words.title, words.no_session)

    async def _door(request, call_next):
        if request.url.path == "/healthz":
            return await call_next(request)
        if bearer_ok(request.headers.get("authorization"), token_now()):
            return await call_next(request)
        if (request.client.host if request.client else "") in LOOPBACK and os.environ.get(loopback_env, "1") == "1":
            return await call_next(request)
        # a person, after the CLI and the token: the path as the request names it (the scope's), not `request.url`,
        # which is rebuilt from the Host header; the session asked of the sign-in off the event loop
        path = request.scope.get("path")
        lines = request.headers.getlist("cookie")
        person = await run_in_threadpool(sign_in.person, lines) if sign_in.session_cookie(lines) else None
        if person and person[1] and request.method in ("GET", "HEAD") and path in person_reads:
            request.scope["dgo.person"] = person[0]
            return await call_next(request)
        if person and person[1] and path in person_writes:
            site = (request.headers.get("sec-fetch-site") or "").strip().lower()
            if site and site != "same-origin":            # another page — of a sibling host too — not the app's own
                return JSONResponse({"detail": "a change is made from the app's own page"}, status_code=403)
            request.scope["dgo.person"] = person[0]
            return await call_next(request)
        if person:                                        # signed in, but not one who reads this (or not a read)
            if path == screen:
                return HTMLResponse(no_grant, status_code=403)
            return JSONResponse({"detail": words.api_no_grant}, status_code=403)
        if path == screen:                                # the tile with no session the sign-in vouches for
            return HTMLResponse(no_session, status_code=401)
        return JSONResponse({"detail": words.api_no_session}, status_code=401)

    return _door
