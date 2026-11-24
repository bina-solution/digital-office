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
…and the one other thing it believes: a person a LINKED office sent through the link's door, whose request carries
that office's cookie, not ours (DGO-2135). Never by a header alone either — see `Link`: the door's own address AND
its signature, verified by the platform's one verifier (platform-base/connections/link_identity.py, built into the
image beside this file the same way: `additional_contexts: {dgolink: ../../platform-base/connections}`,
`COPY --from=dgolink link_identity.py /opt/dgo/link_identity.py`; an image without it has no such person).

Who passes `door()`, in order: /healthz; a service with the app's token (`Authorization: Bearer`); the app's own CLI
on loopback (unless `<APP>_TRUST_LOOPBACK=0`); then a PERSON — a request from the link's door is the person the door
signed and nothing else (`Link`), any other the session its cookie is — an admin of the office, for a GET or HEAD of one of the
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
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

try:
    import link_identity as linkid                        # the platform's ONE verifier of the link door's signature
except ImportError:                                       # an image built without it: no linked office's person
    linkid = None
    print("signin: link_identity.py is not beside this file — a person a linked office sends through the link's "
          "door is refused here (the image's Dockerfile copies it: DGO-2135)", file=sys.stderr, flush=True)

WHOAMI_URL = "http://forward-auth:9078/whoami"
SESSION_COOKIES = ("dgo_session", "authentik_session")   # the sign-in's own, and authentik's it reads in a migration
# forward-auth's two names for its admins (users.go `adminGroups`: `authentik-admins` is a migrated office's — the HP's
# owner's line names it), and authentik's own name for the same group; the console's ADMIN_GROUPS are the same three
ADMIN_GROUPS = frozenset({"admins", "authentik-admins", "authentik Admins"})
LOOPBACK = ("127.0.0.1", "::1")
SEEN_TTL = 10.0                                           # a sign-out or a removed admin holds at most this long
_GO_SPACE = " \t\r\n"                                     # textproto.TrimString's set — not str.strip()'s Unicode one
CONNECTIONS_URL = "http://connections:8990"               # the vault: where this office's copy of a pair's secret is
#: the link's door, by CONTAINER name of this deployment (`dgo-net-<DEPLOYMENT_NAME>`): the door itself (dgo-link) and
#: the carrier run in dgo-net's namespace (`network_mode: service:dgo-net`, apps/dgo-extend/docker-compose.yml), so
#: their requests arrive from its address and they have no name of their own — a second name would only be one more
#: that another container could declare as its alias
DOOR_HOPS = ("dgo-net",)
HERD_HEADER = "x-dgo-herd"                                # the door's `1` for an office of the herd (link-proxy.py)


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


class Link:
    """A person a LINKED office sent through the link's door (DGO-2135) — the one other way a person is known here.

    A browser that opens this app from a linked office's console carries THAT office's session cookie, which this
    office's sign-in cannot vouch for (/whoami says «no session»: the owner, signed in on vps1, read «הכניסה שלך
    ללשכה לא אומתה» on the HP). The request reaches the app through the link's door (apps/dgo-extend/link-proxy.py),
    which removes what the peer claimed and writes the user it becomes here, the office it came from and the door's
    signature of both (`x-dgo-identity`, with the pair's secret) — and `x-dgo-herd: 1` for an office of the herd
    (apps/computers/herd.yaml, matched by WireGuard key). It is believed only when BOTH hold: it came from the door's
    own address (the TCP peer — every app behind this door runs uvicorn `--no-proxy-headers`), and the signature
    verifies (link_identity.verify). Either alone is not enough: any container can write the headers, and any can
    still read a pair's secret from the vault (issues/the-vault-hands-a-link-s-pair-token-…); none has the door's
    address. A request from that address is the door's and nothing else — the cookies on it are another office's.

    An ADMIN of this office is a person of the herd's offices: the owner's own, each of which lets only its own admins
    open a linked office's app (DGO-1755, serve.py's REMOTE_SIGN_IN and the console's `_is_admin`). A person of any
    other linked office is a person here, not an admin: the catalog gives `*` to a client's office too, and maps
    every office to the same user, so neither the route nor the name can tell them apart. The name the app is told
    is `<user>@<office>`, so a change it records says it came over the link.

    THE TRUST, said plainly (the second reader, DGO-2135): the door signs what ARRIVES on a pair, so this believes
    a herd office at office granularity — anything on that office's network that reaches its door to this one is
    its person here, as Plane (office_identity.py) and the computers app already believe it. Two limits are the
    door's, not this file's (issues/the-link-door-…-herd-mark-…): a peer the door lets in from outside its pair's
    address while DGO_LINK_CLIENTS is `warn` is stamped as that pair, herd mark included; and a raw splice (an agent
    port, linkproxy's Forwarder) carries a peer's own headers from the door's address — so an app behind this door is
    never also served by a splice. On the HP every pair is the herd's (2026-11-20), so neither reaches anyone today.

    `addresses` (a test's): the door's addresses instead of asking the network; `vault` the credential plane."""

    RETRY = 10.0                                          # a re-keyed pair: the secret re-read at most this often
    SAY = 60.0                                            # one log line per office and case per this long

    def __init__(self, deployment: str | None = None, vault: str | None = None, addresses=None):
        self.deployment = (os.environ.get("DEPLOYMENT_NAME", "") if deployment is None else deployment).strip()
        self.vault = (vault or os.environ.get("CONNECTIONS_URL") or CONNECTIONS_URL).rstrip("/")
        self._fixed = None if addresses is None else frozenset(addresses)
        self._door = (0.0, frozenset())                   # (when resolved, the door's addresses)
        self._resolving = threading.Lock()                # one lookup at a time; the others keep the last answer
        self._secrets = linkid.Secrets(lambda office: linkid.link_secret(self._vault_json, office)) if linkid else None
        self._reread: dict = {}                           # office → when its secret was last re-read on a refusal
        self._said: dict = {}                             # (office, case) → when it was last logged

    def _vault_json(self, path: str, params):
        """The vault's HTTP for link_identity.link_secret — (status, body); an error status is an answer."""
        url = self.vault + path + (("?" + urllib.parse.urlencode(params)) if params else "")
        try:
            with urllib.request.urlopen(url, timeout=4) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, {}

    def addresses(self) -> frozenset:
        """The door's addresses, re-read once a minute (15 s while none resolves: an office linked a moment ago is
        noticed soon, and a miss is never a permission). One lookup at a time — a request that finds one running keeps
        the last answer, so a slow resolver costs one request, not all of them. A name that answers with two addresses
        of one family is not one container (another declared the door's name as its alias): no door at all."""
        if self._fixed is not None:
            return self._fixed
        at, found = self._door
        if at and 0 <= time.monotonic() - at < (60 if found else 15):
            return found
        if not self._resolving.acquire(blocking=False):
            return found
        try:
            addrs = set()
            for name in (f"{hop}-{self.deployment}" for hop in DOOR_HOPS) if self.deployment else ():
                try:
                    got = {str(i[4][0]) for i in socket.getaddrinfo(name, None, proto=socket.IPPROTO_TCP)}
                except (OSError, ValueError):             # no such name; a label DNS cannot carry (UnicodeError)
                    continue
                if len({a for a in got if ":" not in a}) > 1 or len({a for a in got if ":" in a}) > 1:
                    print(f"signin: {name} answers with {', '.join(sorted(got))} — another container declares the "
                          f"door's name, so no request is taken as the door's", file=sys.stderr, flush=True)
                    continue
                addrs |= got
            self._door = (time.monotonic(), frozenset(addrs))
            return self._door[1]
        finally:
            self._resolving.release()

    def from_door(self, client: str) -> bool:
        """Did this request come from the link's door? Never, with no verifier in the image."""
        return linkid is not None and linkid.from_the_door(client, self.addresses())

    def person(self, headers):
        """((`<user>@<office>`, an admin of the office), "") for the person the door signed — or (None, (why, kind)):
        the link's own sentence, and which case it is. Asked only of a request that came from the door
        (`from_door`)."""
        office = str(headers.get(linkid.OFFICE_HEADER) or "").strip().lower()
        claim = str(headers.get(linkid.IDENTITY_HEADER) or "")
        fields = linkid.parse(claim)
        if fields is None or fields[0] != office:         # unsigned, malformed or another office's: no vault call
            ok, kind, why = linkid.verify(claim, office=office, secret="")
        else:
            ok, kind, why = linkid.verify(claim, office=office, secret=self._secrets.get(office))
            now = time.monotonic()
            if not ok and kind in ("bad-mac", "no-secret") and now - self._reread.get(office, now - self.RETRY) \
                    >= self.RETRY:
                # the pair may have been re-keyed, or linked a moment ago, since the vault was last asked: once more
                self._reread[office] = now
                self._secrets.forget(office)
                ok, kind, why = linkid.verify(claim, office=office, secret=self._secrets.get(office))
        if not ok:
            self._say(office, kind, why)
            return None, (why, kind)
        return (f"{fields[1]}@{office}", (headers.get(HERD_HEADER) or "").strip() == "1"), ""

    def _say(self, office: str, kind: str, why: str) -> None:
        """One log line per office and case per SAY seconds: refused requests in a loop cannot fill the app's log."""
        now, key = time.monotonic(), (office[:64], kind)
        if key in self._said and now - self._said[key] < self.SAY:
            return
        if len(self._said) > 256:
            self._said.clear()
        self._said[key] = now
        print(f"signin: a request through the link's door refused ({kind}, {office[:64] or 'no office'}): {why}",
              flush=True)


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
         person_writes=(), link: Link | None = None):
    """The app's HTTP middleware: `app.middleware("http")(door(...))`. `token` is the app's token, or a function
    returning it now (a test may change it); `person_reads` the paths a person's GET may read — the screen and its
    reads; `screen` the path whose refusal is a page, not JSON. `person_writes` (empty by default, so an app that
    does not name it is exactly as before): the paths an ADMIN may also change from the screen — any method — for
    an app whose screen is where its records are kept («ישויות», DGO-2101). Either may be a set of paths or any
    object answering `path in it` (a prefix rule). Such a change is taken only from the app's own page: a browser
    names where a request comes from (`Sec-Fetch-Site`), and one that names anything but `same-origin` — a sibling
    host of the office's domain shares the session cookie (SameSite=Lax) — is refused; the app takes a change only
    as JSON, exactly (its `_body`), which no page of another site can send unasked. The person let in is named to
    the app in `request.scope["dgo.person"]`. `link`: who the link's door is (`Link`, from the office's own
    `DEPLOYMENT_NAME` unless a test names it); a request it carried in and could not prove is refused with its
    reason."""
    token_now = token if callable(token) else (lambda: token)
    link = Link() if link is None else link
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
        refused = ()
        if await run_in_threadpool(link.from_door, request.client.host if request.client else ""):
            person, refused = await run_in_threadpool(link.person, request.headers)
        else:
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
        if refused:                                       # the link's door carried it, and it proved nobody: why
            why, kind = refused
            if path == screen:
                return HTMLResponse(page(words.title, why), status_code=401)
            return JSONResponse({"detail": f"{why} ({kind})"}, status_code=401)
        if path == screen:                                # the tile with no session the sign-in vouches for
            return HTMLResponse(no_session, status_code=401)
        return JSONResponse({"detail": words.api_no_session}, status_code=401)

    return _door
