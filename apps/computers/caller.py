"""caller — WHO is asking this app to change something, and WHAT that caller may change (DGO-1304 / DGO-1305).

Why this exists
---------------
`POST /api/computers/<id>/exec` runs a command as root on a machine of the fleet. Until this module the
app asked nobody anything: any container on the office network could run root on every machine the office
holds a key for (measured 2026-11-03 from the HP's desktop-app container: the request was accepted, and it
failed only because the HP's host has no sshd). A write is now answered only for a caller that can say who
it is, in one of four ways — and each way is a FACT the network gives, not a header a caller types:

  door      a LINKED OFFICE: the request came from the link's door (`dgo-net-<deployment>` /
            `dgo-link-<deployment>`, the one container the link network answers from), it names its office
            in `x-dgo-office`, this office gives its computer to that office (`COMPUTERS_SHARE_TO`), and the
            door's signature (`x-dgo-identity`, link_identity.py) verifies whenever the pair has a secret.
            A door may only RUN on the shared computer (`door_allows`): never manage the fleet, never reach
            another machine — sharing "my computer" is not sharing the office's keys to vps1.
  sso       a PERSON on the screen: forward-auth's `X-authentik-username`, believed only from the two hops
            that write it — traefik (the app's own host) and the console (its proxy of /a/computers/; it
            drops the header from any request that did not come through traefik).
  token     an office SERVICE: `Authorization: Bearer <COMPUTERS_EXEC_TOKEN>` — minted once into the vault
            and .env (app.json `contributes.connection_providers`), held only by the apps whose own app.json
            declares the connection.
  loopback  this container itself: the bbox hooks run here (`docker exec computers …`).

The address is the TCP peer's: the app runs uvicorn with `--no-proxy-headers`, so `X-Forwarded-For` cannot
make a container "loopback" or "the console" (the second reader, 2026-11-03).

Anything else is refused BY NAME — the sentence says what was missing. While the office is in `warn`
(non-negotiable 8: warn, count, then refuse) a refusal is let through and counted, EXCEPT where `enforced`
says it already holds: everything that manages the fleet once any machine is enforced, and that machine.

Pure: the request is reduced to `Facts` by the app, so every case is provable without a server
(tests/test_caller.py).
"""
from __future__ import annotations

import hmac
import ipaddress
import re
from dataclasses import dataclass, field

import link_identity as linkid

#: the hops that write forward-auth's identity header, by CONTAINER name (`<name>-<deployment>`): a network
#: alias any compose file could also declare is not a hop
SSO_HOPS = ("traefik", "console")
#: the link's door (link_identity.from_the_door)
DOOR_HOPS = ("dgo-net", "dgo-link")
#: the computer a linked office is given: this office's own
SHARED_MACHINE = "computer_local-local"
#: the per-machine writes that RUN something, as opposed to managing the fleet — an interactive shell included:
#: opening it, typing into it, resizing and closing it (DGO-1800: the terminal app's routes)
RUN_RE = re.compile(r"^/api/computers/([^/]+)/(exec|probe|shell(?:/[0-9a-f]+(?:/(?:input|resize))?)?)$")


@dataclass
class Facts:
    """What the request says, and where it came from — no more."""
    client: str = ""
    office: str = ""                 # x-dgo-office
    claim: str = ""                  # x-dgo-identity
    user: str = ""                   # x-authentik-username
    bearer: str = ""                 # Authorization: Bearer …


@dataclass
class Policy:
    """This office's side: the addresses of the hops, what it gives, and the token."""
    door_addrs: set = field(default_factory=set)
    sso_addrs: set = field(default_factory=set)
    share_to: set = field(default_factory=set)
    token: str = ""
    secret_of: object = None         # office -> the pair's secret ("" when none, None when the vault did not answer)


@dataclass
class Caller:
    ok: bool
    way: str                         # door | sso | token | loopback | none
    who: str                         # office:<id>/<user> · user:<name> · service · local · the address
    why: str = ""                    # the refusal, in the app's words (Hebrew), when not ok
    note: str = ""                   # for the log: an unsigned door, a header that was ignored


def is_loopback(addr: str) -> bool:
    try:
        return ipaddress.ip_address(str(addr).split("%")[0]).is_loopback
    except ValueError:
        return False


def identify(f: Facts, p: Policy) -> Caller:
    """The one decision. A request that names an office is judged as a door and nothing else, so a peer can
    never pass as the screen or as a service."""
    addr = f.client or "?"
    office = (f.office or "").strip().lower()
    if office or f.claim:
        if not linkid.from_the_door(f.client, p.door_addrs):
            return Caller(False, "none", addr, f"הבקשה מצהירה על הלשכה {office or '?'} אבל לא הגיעה מהדלת של "
                          "הקישור — רק הדלת כותבת את הכותרת הזו")
        if not office:
            return Caller(False, "none", addr, "הבקשה נושאת חתימת קישור בלי לומר מאיזו לשכה היא")
        if office not in p.share_to:
            return Caller(False, "none", f"office:{office}",
                          f"הלשכה הזו אינה משתפת את המחשב שלה עם {office} (COMPUTERS_SHARE_TO)")
        secret = p.secret_of(office) if callable(p.secret_of) else ""
        if secret is None:
            # the vault did not answer: "no secret" cannot be told from "could not read it", so nothing passes
            return Caller(False, "none", f"office:{office}", "שירות החשבונות אינו זמין, ולכן אי אפשר לאמת את "
                          f"החתימה של {office} — נסו שוב בעוד רגע")
        if f.claim or secret:
            # a pair that HAS a secret must sign: "verified when present" would let anything at the door's
            # address leave the signature out (the second reader)
            ok, kind, why = linkid.verify(f.claim, office=office, secret=secret)
            if not ok:
                return Caller(False, "none", f"office:{office}", why)
            return Caller(True, "door", f"office:{office}/{(linkid.parse(f.claim) or ('', '?'))[1]}")
        return Caller(True, "door", f"office:{office}/{f.user or '?'}",
                      note="unsigned door: the pair has no secret in this office's vault")
    ignored = ""
    if f.user:
        if f.client in p.sso_addrs:
            return Caller(True, "sso", f"user:{f.user}")
        # not a refusal of its own: the header is simply not believed from here
        ignored = f"the sign-in header from {addr} ignored (not traefik or the console)"
    if f.bearer:
        if p.token and hmac.compare_digest(f.bearer.encode(), p.token.encode()):
            return Caller(True, "token", "service", note=ignored)
        return Caller(False, "none", addr, "הטוקן של השירות שגוי (COMPUTERS_EXEC_TOKEN)", note=ignored)
    if is_loopback(f.client):
        return Caller(True, "loopback", "local", note=ignored)
    return Caller(False, "none", addr,
                  "לא ידוע מי מבקש: אין כניסה דרך המסך, אין טוקן של שירות (Authorization: Bearer "
                  "COMPUTERS_EXEC_TOKEN), והבקשה לא הגיעה מהדלת של הקישור", note=ignored)


def door_allows(method: str, path: str) -> bool:
    """A linked office runs commands on the computer it was given — and does nothing else here."""
    m = RUN_RE.match(path)
    if not m or m.group(1) != SHARED_MACHINE:
        return False
    # POST runs, types into, resizes; DELETE only closes its own shell session (a session id, nothing wider)
    return method == "POST" or (method == "DELETE" and re.fullmatch(r"shell/[0-9a-f]+", m.group(2)) is not None)


def is_shell(path: str) -> bool:
    """One of the terminal's routes (open, type, poll, resize, close) — by its prefix, so a malformed session id
    is still a shell route."""
    return re.match(r"^/api/computers/[^/]+/shell(?:/|$)", path) is not None


def enforced(method: str, path: str, mode: str, machines: set) -> bool:
    """Is a refusal REAL for this write (not only counted)?

    `enforce`: always. `warn` with no enforced machine: never. `warn` with enforced machines: everything except
    running something on a machine that is NOT enforced — adding a second record for the same host, deleting
    one, streaming INTO a volume of it, a share, a connection, a cleanup are all ways to the enforced machine
    that do not carry its id where a per-machine check would look (the second reader, 2026-11-03)."""
    if mode == "enforce":
        return True
    if not machines:
        return False
    m = RUN_RE.match(path)
    return not (m and m.group(1) not in machines)


def bearer_of(header: str) -> str:
    h = str(header or "").strip()
    return h[7:].strip() if h[:7].lower() == "bearer " else ""


def route_shape(path: str) -> str:
    """`/api/computers/computer_ssh-1a2b/exec` → `/api/computers/{id}/exec`; an unknown path is one bucket, so a
    caller cannot grow the count's table with paths of its own making."""
    for pat, shape in ((r"^/api/computers/[^/]+/(exec|probe|stream|transfer|shares|authorize-command|shell)$",
                        r"/api/computers/{id}/\1"),
                       (r"^/api/computers/[^/]+/shell/[^/]+(/input|/resize)?$", r"/api/computers/{id}/shell/{sid}\1"),
                       (r"^/api/computers/[^/]+$", "/api/computers/{id}"),
                       (r"^/api/computers$", "/api/computers"),
                       (r"^/api/shares/[^/]+$", "/api/shares/{id}"),
                       (r"^/api/transfers/[^/]+/cancel$", "/api/transfers/{id}/cancel"),
                       (r"^/api/hosts/local/machine/cleanup/[^/]+$", "/api/hosts/local/machine/cleanup/{id}"),
                       (r"^/connections(/select|/[^/]+)?$", "/connections…")):
        if re.match(pat, path):
            return re.sub(pat, shape, path)
    return "(other)"
