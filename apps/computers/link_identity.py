"""link_identity — did this request really come in through a LINK's door? (DGO-553)

Why this exists
---------------
`computers` shares machines with a linked office, and the only thing that says which office is asking
is a header (`x-dgo-office`). Any container on this office's network can write that header, so on its
own it is a CLAIM, not a fact — and a claim that is believed turns "a peer was given three machines"
into "anything that can reach this port was given the fleet". Measured 2026-11-01: a plain
`curl -H 'x-dgo-office: nosuchoffice' http://computers:8977/api/computers` answered this office's
whole fleet, for an office that is not even linked.

The platform already has the answer, and it is one contract, not a second one: the door SIGNS what it
carries (`apps/dgo-extend/link-proxy.py`, `x-dgo-identity`), with the secret the two offices share
(`dgo_link` in the credential plane). `apps/project-pln/office_identity.py` verifies that signature to
know who is looking at it; this module is the same verification for this app. Two facts come out of
it, and they are the only two anything here needs: WHICH office, and that the door said so.

The contract
------------
    x-dgo-office:   <office id>
    x-dgo-identity: v1 <office> <user> <unix-seconds> <hex hmac-sha256 of "v1\n<office>\n<user>\n<ts>">

Anything that does not verify — a signature signed with another secret, a tampered field, one older
than `SIG_WINDOW`, a missing signature — is not an identity: the caller is refused, by name, and told
which of the cases it is. Self-contained and importable without a web server, a vault or a machine:
`tests/test_link_identity.py` proves the arithmetic, the window and every refusal.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time

#: The two headers the door writes. Both are removed from a request the door carries in, before it
#: writes its own (`link-proxy.py::Door.rewrite`), so a peer cannot smuggle a claim of its own.
OFFICE_HEADER = "x-dgo-office"
IDENTITY_HEADER = "x-dgo-identity"
#: …and the door's word that the office asking is the HERD's, by key (DGO-1800): `1`, written beside the office only
#: for a rule the delivery plan marked (dgo-extend give.herd_peer → linkproxy.build_multi), removed from every request
#: a peer sends (link-proxy.py HERD_HEADER). Not signed: believed only from the door's own address (`from_the_door`).
HERD_HEADER = "x-dgo-herd"

#: What is signed, and the whole of it — the same two functions as the door's, so the halves cannot
#: drift. Version first: a future format is a new version, never a reinterpretation of this one.
SIG_VERSION = "v1"
SIG_WINDOW = 300

#: An office id: the rule the compiler and the link's own declaration apply (`serve.OFFICE_RE`).
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}\Z")


def signed_text(office: str, user: str, ts: int) -> str:
    return f"{SIG_VERSION}\n{office}\n{user}\n{int(ts)}"


def signature(secret: str, office: str, user: str, ts: int) -> str:
    """The hex HMAC a door would have written — pure, so a test can build a real one."""
    return hmac.new(str(secret).encode("utf-8"), signed_text(office, user, ts).encode("utf-8"),
                    hashlib.sha256).hexdigest()


def parse(claim: str) -> tuple[str, str, int, str] | None:
    """`v1 office user ts mac` → its fields, or None when the header is not that shape at all."""
    parts = str(claim or "").strip().split()
    if len(parts) != 5 or parts[0] != SIG_VERSION:
        return None
    _, office, user, ts, mac = parts
    office = office.strip().lower()
    if not OFFICE_RE.match(office) or not user or not mac:
        return None
    try:
        when = int(ts)
    except (TypeError, ValueError):
        return None
    return office, user, when, mac


def verify(claim: str, office: str, secret: str, now: float | None = None) -> tuple[bool, str, str]:
    """Is `claim` a door's signature of `office`, made with `secret`, inside the window?

    Returns `(ok, kind, why)`. `kind` is the case, for the caller's own sentence: `ok`, `unsigned`
    (no signature at all — a caller can be a door older than this op, which is worth saying
    differently from a lie), `mismatch` (a signature naming another office), `no-secret`, `stale`,
    `bad-mac`, `malformed`. `why` is the reason in this app's words, already ready to show a person.
    """
    if not str(claim or "").strip():
        return False, "unsigned", "לבקשה אין חתימה של דלת הלשכה"
    fields = parse(claim)
    if fields is None:
        return False, "malformed", ("החתימה של הדלת שעל הבקשה אינה במבנה המוכר, ולכן הבקשה אינה "
                                    "מגיעה מלשכה מקושרת")
    got_office, user, when, mac = fields
    named = str(office or "").strip().lower()
    if not named or got_office != named:
        return False, "mismatch", ("הבקשה מצהירה על לשכה אחת וחתומה על אחרת — היא נדחתה")
    if not secret:
        return False, "no-secret", ("אין ללשכה הזו מפתח לקישור עם " + named +
                                    ", ולכן אי אפשר לאמת את הבקשה שלה")
    moment = time.time() if now is None else now
    if abs(moment - when) > SIG_WINDOW:
        return False, "stale", ("החתימה של " + named + " אינה עדכנית (היא נחתמה לפני יותר מ־"
                                f"{SIG_WINDOW} שניות) — בקשו ממנה לפתוח את המסך מחדש")
    want = signature(secret, got_office, user, when)
    if not hmac.compare_digest(want, mac):
        return False, "bad-mac", ("החתימה של " + named + " אינה נכונה — הבקשה לא עברה בדלת שלה, "
                                  "או שהמפתח של הקישור השתנה")
    return True, "ok", ""


def from_the_door(client: str, addresses) -> bool:
    """Did this request come from the LINK'S DOOR — the one container that carries peers' requests?

    The strongest proof is the signature (`verify`), and it is the one every office writes from the
    release that added it. A door older than that writes the office and no signature, and the office it
    serves is real: refusing it would break a shared machine that worked a moment ago (measured
    2026-11-01 — the MacBook's console reaching this office's «מחשבים» answered 403 after the signature
    became mandatory). So the second proof is WHERE it came from: `dgo-link` runs in the link network's
    own namespace, so its requests arrive from that one address, which any OTHER container in the office
    network does not have.

    What this keeps out is exactly what the header alone let in: a container that types an office name.
    It is not a claim that an old door is as good as a new one — the two are told apart in the log, and
    the update closes the difference.
    """
    addr = str(client or "").strip()
    if not addr:
        return False
    return addr in {str(a).strip() for a in (addresses or ()) if a}


class Secrets:
    """`office -> the pair's secret`, read from the credential plane and remembered for a while.

    The vault is a service; this is on the request path of every shared machine, so it is read once
    per office per `ttl`. `fetch` is injected (it does the HTTP) so this class can be proved without
    a network — and so this app names the vault in exactly one place.
    """

    def __init__(self, fetch, ttl: float = 60.0):
        self._fetch = fetch
        self._ttl = float(ttl)
        self._cache: dict[str, tuple[float, str]] = {}

    def get(self, office: str) -> str:
        office = str(office or "").strip().lower()
        if not OFFICE_RE.match(office):
            return ""
        now = time.time()
        hit = self._cache.get(office)
        if hit and now - hit[0] < self._ttl:
            return hit[1]
        try:
            token = str(self._fetch(office) or "")
        except Exception:                        # noqa: BLE001 — a vault that is down is "no secret"
            token = ""
        self._cache[office] = (now, token)
        return token

    def forget(self, office: str = "") -> None:
        """Drop one office's (or every) remembered secret — a pairing changed its key."""
        if office:
            self._cache.pop(str(office).strip().lower(), None)
        else:
            self._cache.clear()
