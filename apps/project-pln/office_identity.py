# office_identity.py — the office's own sign-in IS Plane's sign-in (DGO-371, DGO-545).
#
# Installed by ./Dockerfile (`COPY` + patches/sso-identity.py), which is also where it is wired into
# `settings.MIDDLEWARE`. It exists because Plane Community Edition has no OIDC, no SAML and no
# reverse-proxy header authentication (measured against v1.4.2: `plane.authentication.provider.oauth`
# ships google/github/gitlab/gitea and `ENABLE_*` flags for those only), so «sign in once to the
# office» cannot be configured into Plane — it has to be given to it.
#
# WHAT IT DOES, and the two doors it answers.
#
# (1) A browser that reaches Plane through the office edge is already authenticated: it carries the
# identity provider's cookie for this host (`authentik_proxy_…`). This middleware asks the PROVIDER —
# the same endpoint, with the same request the edge's `authentik@file` forwardAuth makes — who that
# cookie is, and if the answer is a user the office declared, it signs that person into Plane
# (`django.contrib.auth.login`), so Plane's own form is never shown inside the office.
#
# (2) A browser on a LINKED office's console has no such cookie — it was authenticated by the OTHER
# office. Its request arrives through the link's door, which replaces the peer's claims with this
# office's mapped user and SIGNS what it writes (`apps/dgo-extend/link-proxy.py`, `x-dgo-identity`,
# with the pair's own secret from the credential plane). This middleware checks that signature — with
# its own copy of the same secret, read from the vault — and signs the mapped person in the same way.
# A signature that does not verify, or is older than SIG_WINDOW, is not an identity: the request goes
# on exactly as it would have without this file, which is Plane's own sign-in page.
#
# WHAT IT TRUSTS, and what it deliberately does not. `X-authentik-username` / `-email` / `-jwt` on the
# incoming request are IGNORED — every container on the office network can write them, and the JWT is
# HS256 (the provider's own session secret, measured 2026-10-12), so it cannot be verified from
# outside either. The cookie path trusts only what the PROVIDER answers for THIS BROWSER'S OWN COOKIE;
# the link path trusts only a signature made with a secret no container here can guess, and only for
# the office that secret belongs to. A forged header with no cookie and no signature gets the 302 a
# stranger gets, and Plane's own sign-in page.
#
# WHO the answer is, is DECLARED — apps/project-pln/bootstrap.yaml (`sso:`), applied by
# `hooks/onboard` into /app/data/office-identity.json. An office user nobody declared is not
# guessed at: Plane's own form stands (and the reason is logged).
#
# Nothing here is fatal: if the provider is unreachable, or the file is absent, or the user has no
# Plane account, the request goes on exactly as it would have without this file.
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from django.contrib.auth import get_user_model, login

# The edge's own call, verbatim (platform-base/traefik/config/authentik-forwardauth.yaml): the
# provider decides who may pass, and answers the identity in headers — which only means anything
# because they come from the provider, in answer to a request carrying the browser's own cookie.
# WHICH provider is the office's one switch, `DGO_IDENTITY` (.env) — the same value the edge's
# middleware reads — so the app asks whoever the edge asks (r030-002). `PLANE_SSO_OUTPOST`, when
# set, still wins; an unknown value is authentik's, as it is for the edge.
PROVIDERS = {
    "forward-auth": "http://forward-auth:9078/auth/traefik",
    "authentik": "http://authentik-server:9000/outpost.goauthentik.io/auth/traefik",
}
OUTPOST = os.environ.get("PLANE_SSO_OUTPOST") or PROVIDERS.get(
    os.environ.get("DGO_IDENTITY", ""), PROVIDERS["authentik"])
MAP_FILE = os.environ.get("PLANE_SSO_MAP", "/app/data/office-identity.json")
TIMEOUT = float(os.environ.get("PLANE_SSO_TIMEOUT", "4"))
# The office's cookies — authentik's, and forward-auth's own session, which also accepts authentik's
# while an office migrates. A request with neither has nothing to ask about, and pays nothing.
COOKIE_PREFIX = ("authentik", "dgo_session")
# Paths this never touches: static assets, the provider's own endpoints under this host, and the
# instance-admin API (`/api/instances/`, the god-mode's own session — a separate cookie and a
# separate door, which stays exactly as it was).
SKIP = ("/static/", "/assets-", "/icons/", "/favicon", "/manifest", "/site.webmanifest",
        "/outpost.goauthentik.io/", "/api/instances/")
BACKEND = "django.contrib.auth.backends.ModelBackend"

# ── the LINK's door (DGO-545) ────────────────────────────────────────────────────────────────────
#: The signature the door writes, and the secret it is checked against. The format is a contract
#: between two apps — it is written out beside its writer (`apps/dgo-extend/link-proxy.py`, and
#: README.md § "the door's signature" there); both halves are pinned by this app's `hooks/verify`.
DOOR_HEADER = "HTTP_X_DGO_IDENTITY"
SIG_VERSION = "v1"
#: How old a signature may be. The two offices are the owner's own machines, minutes apart at worst.
SIG_WINDOW = 300
#: The credential plane, and the protocol its link instances carry (`apps/dgo-extend/links.py`).
CONNECTIONS_URL = (os.environ.get("CONNECTIONS_URL", "http://connections:8990")).rstrip("/")
VAULT_PROTOCOL = "dgo_link"
#: An office id is a name the vault is asked for — never a path. Same rule as the vault's own. `\Z`,
#: never `$`: Python's `$` also matches just BEFORE a trailing newline, so `^…$` passed "vps1\n" (the
#: two readers here strip or split first; the rule must not depend on that — DGO-615).
OFFICE_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]{0,63}\Z")
#: `office -> (read_at, token)`. Read once per office per SIG_TTL: the vault is a service a page load
#: must not depend on, and a pair's secret does not rotate under a live link. An office the vault has
#: nothing for is remembered too (empty token), so a forged header cannot turn into a request storm.
SIG_TTL = 60.0
_SECRETS: dict[str, tuple[float, str]] = {}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A 302 from the provider IS the answer ("this browser is not signed in") — never follow it."""

    def redirect_request(self, *args, **kwargs):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def log(message: str) -> None:
    """One line, on the API's own stderr.

    `getLogger` is called here and not at import time: `plane.settings.production` configures logging
    with `disable_existing_loggers: True`, and a logger created while the module is imported — i.e.
    before that — is disabled for the life of the process (measured: a module-level logger printed
    nothing at all, in every worker).
    """
    try:
        logger = logging.getLogger("plane.office_identity")
        logger.disabled = False
        logger.warning(message)
    except Exception:                                          # noqa: BLE001 — never break a request
        pass


def _mapping() -> list[dict]:
    """The declared office-identity → Plane-account pairs, re-read when the file changes."""
    try:
        info = os.stat(MAP_FILE)
    except OSError:
        return []
    stamp = (info.st_mtime, info.st_size)
    cached = getattr(_mapping, "cache", None)
    if cached and cached[0] == stamp:
        return cached[1]
    try:
        with open(MAP_FILE, encoding="utf-8") as handle:
            users = (json.load(handle) or {}).get("users") or []
    except (OSError, ValueError):
        return []
    pairs = []
    for entry in users:
        if not isinstance(entry, dict):
            continue
        plane = str(entry.get("plane") or "").strip()
        names = entry.get("authentik") or []
        if isinstance(names, str):
            names = [names]
        names = [str(n).strip() for n in names if str(n).strip()]
        if plane and names:
            pairs.append({"plane": plane, "authentik": names})
    _mapping.cache = (stamp, pairs)
    return pairs


def _who_is_this(request, cookies: dict) -> dict | None:
    """Ask the office's own identity provider about this browser. None = not signed in."""
    headers = {
        "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
        "X-Forwarded-Host": request.get_host(),
        "X-Forwarded-Proto": "https" if request.is_secure() else "http",
        "X-Forwarded-Uri": request.get_full_path(),
    }
    try:
        answer = _OPENER.open(urllib.request.Request(OUTPOST, headers=headers), timeout=TIMEOUT)
    except urllib.error.HTTPError:
        return None                                # 302 → the provider's own "sign in first"
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # A provider that cannot be reached is not an error of this request: the person gets
        # Plane's own sign-in page, and the line below says why (DNS, refused, timed out).
        log(f"office identity: the provider could not be asked ({exc})")
        return None
    identity = {
        "username": answer.headers.get("X-Authentik-Username") or "",
        "email": answer.headers.get("X-Authentik-Email") or "",
        "uid": answer.headers.get("X-Authentik-Uid") or "",
    }
    return identity if (identity["username"] or identity["email"]) else None


def _declared_plane_email(pairs: list[dict], identity: dict) -> str:
    """The Plane account the office declared for this identity — by username, e-mail or uid."""
    claimed = {v.strip().lower() for v in identity.values() if v}
    for pair in pairs:
        if claimed & {n.lower() for n in pair["authentik"]}:
            return pair["plane"]
    return ""


def names_office(row: dict, office: str) -> bool:
    """Is this `dgo_link` row the link with `office`? The same rule as the signer (apps/dgo-extend/link-proxy.py
    `names_office`): `dgo_link-<office>` from a pairing, or `<a>-><b> <direction>` in a converged row's hint; never a
    split on `-`, which left hyphenated offices (hp-laptop) unverifiable (hos-005)."""
    iid = str((row or {}).get("id") or "").lower()
    if iid == f"dgo_link-{office}":
        return True
    hint = str((row or {}).get("account_hint") or "").lower().split(" ", 1)[0]
    return office in hint.split("->") if "->" in hint else False


def _link_secret(office: str) -> str:
    """This office's copy of the secret it shares with ONE linked office, from the credential plane.

    Found exactly the way `apps/dgo-extend/links.py` and the door that signs with it find it: every
    `dgo_link` instance whose NAME (or account hint) carries that office as a whole word — so a pair
    that holds `dgo_link-vps1` here and `dgo_link-hp-laptop` there agrees about the secret without
    agreeing about the file name. A vault that is down, or a link nobody minted a secret for, answers
    empty: an identity that cannot be proved is not an identity, and the request keeps Plane's own
    sign-in page.
    """
    office = (office or "").strip().lower()
    if not OFFICE_RE.match(office):
        return ""
    now = time.time()
    hit = _SECRETS.get(office)
    if hit and now - hit[0] < SIG_TTL:
        return hit[1]
    token = ""
    try:
        with urllib.request.urlopen(
                f"{CONNECTIONS_URL}/api/instances?protocol={VAULT_PROTOCOL}", timeout=TIMEOUT) as r:
            rows = (json.loads(r.read() or b"{}").get("instances") or [])
        for row in rows:
            iid0 = str((row or {}).get("id") or "")
            # an agent's credential handed over by a linked office is not the pair's secret (DGO-1127)
            if iid0.startswith("dgo_link-serve-") and iid0.endswith("-agent"):
                continue
            if not names_office(row, office):
                continue
            iid = urllib.parse.quote(str(row.get("id") or ""), safe="")
            with urllib.request.urlopen(
                    f"{CONNECTIONS_URL}/api/instances/{iid}/secret", timeout=TIMEOUT) as r:
                token = str((json.loads(r.read() or b"{}").get("secret") or {}).get("token") or "")
            if token:
                break
    except (urllib.error.URLError, OSError, ValueError, TypeError) as exc:
        log(f"office identity: the link secret for {office} could not be read ({exc})")
        token = ""
    _SECRETS[office] = (now, token)
    return token


def _door_identity(request) -> tuple[str, str] | None:
    """(office, user) when this request crossed a link whose door PROVED it — else None.

    The door writes `x-dgo-identity: v1 <office> <user> <ts> <hmac>` and signs the first four fields
    with the pair's own secret (`apps/dgo-extend/link-proxy.py`, the same contract). Anything that
    does not verify — a wrong secret, a tampered field, a signature older than SIG_WINDOW — is not an
    identity at all: the caller gets what a stranger gets.
    """
    claim = str(request.META.get(DOOR_HEADER) or "").strip()
    if not claim:
        return None
    parts = claim.split()
    if len(parts) != 5 or parts[0] != SIG_VERSION:
        log("office identity: a malformed link signature was ignored")
        return None
    _, office, user, ts, mac = parts
    if not (OFFICE_RE.match(office.lower()) and user):
        return None
    try:
        if abs(time.time() - int(ts)) > SIG_WINDOW:
            log(f"office identity: a link signature from {office} was stale ({ts}) — ignored")
            return None
    except ValueError:
        return None
    secret = _link_secret(office)
    if not secret:
        log(f"office identity: no secret here for the office {office} — its signature cannot be "
            f"checked, and Plane's own sign-in stands")
        return None
    want = hmac.new(secret.encode("utf-8"), f"{SIG_VERSION}\n{office}\n{user}\n{int(ts)}".encode("utf-8"),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(want, mac):
        log(f"office identity: a link signature claiming {office}/{user} did not verify — refused")
        return None
    return office, user


class OfficeIdentityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        try:
            self.identify(request)
        except Exception as exc:                   # noqa: BLE001 — a sign-in helper must never 500 a screen
            log(f"office identity: skipped ({type(exc).__name__}: {exc})")
        return self.get_response(request)

    def identify(self, request) -> None:
        if request.user.is_authenticated:          # already signed in (or an API key) — nothing to do
            return
        if request.path.startswith(SKIP):
            return
        pairs = _mapping()
        if not pairs:                              # nothing declared: Plane's own sign-in is the door
            return
        door = _door_identity(request)
        if door:
            # A signed door request needs no CSRF token, and that is the same decision as the
            # signature itself: CSRF defends a COOKIE session from a foreign page, and no page can
            # produce this signature — it is an HMAC with a secret only the two offices hold. Set
            # only here, on a request whose identity was just verified (Django and DRF both read
            # this attribute), never on a cookie-authenticated one.
            request._dont_enforce_csrf_checks = True
            if self._enter(request, pairs, {"username": door[1], "email": "", "uid": ""},
                           f"the {door[0]} link's door"):
                # …and the ONE thing a token API may be opened to (patches/api-door-identity.py):
                # a request that arrived through a link and whose identity this office PROVED. A
                # browser's cookie is deliberately not enough there — a token API stays a token API
                # for everyone else, and this flag is set on no other request.
                request._dgo_link_identity = f"{door[0]}:{door[1]}"
            return
        cookies = {k: v for k, v in request.COOKIES.items() if k.lower().startswith(COOKIE_PREFIX)}
        if not cookies:
            return
        identity = _who_is_this(request, cookies)
        if identity is None:
            return
        self._enter(request, pairs, identity,
                    f"the office's own {identity['username'] or identity['email']}")

    @staticmethod
    def _enter(request, pairs: list[dict], identity: dict, source: str):
        """Sign in the Plane account the office declared for this identity — or say why not.

        Returns the user it signed in, so a caller can record WHY this request is authenticated.
        """
        email = _declared_plane_email(pairs, identity)
        if not email:
            log(f"office identity: {identity['username'] or identity['email']} is not declared as a "
                f"Plane account (apps/project-pln/bootstrap.yaml → sso:) — its own form stands")
            return None
        user = get_user_model().objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            log(f"office identity: the declared account {email} has no active Plane user")
            return None
        login(request, user, backend=BACKEND)
        log(f"office identity: signed in {user.email} ({source})")
        return user
