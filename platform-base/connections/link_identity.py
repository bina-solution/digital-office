"""link_identity — did this request really come in through a LINK's door, and from which office? (DGO-553, DGO-1797)

THE ONE SOURCE. An app that answers requests a linked office makes mounts this file read-only at
/opt/dgo/link_identity.py (the flowpub pattern) and never keeps a copy of its own: a second copy of a check like
this one is a second place for it to be wrong. An app that still carries a copy is a debt with its own task.

Why this exists
---------------
The only thing that says which office is asking is a header (`x-dgo-office`). Any container on this office's network
can write that header, so on its own it is a CLAIM, not a fact — and a claim that is believed turns "a peer was given
three machines" into "anything that can reach this port was given the fleet". Measured 2026-11-01: a plain request
with `x-dgo-office: nosuchoffice` answered an office's whole fleet, for an office that is not even linked.

The answer is one contract, not a second one: the link's door SIGNS what it carries (`x-dgo-identity`), with the
secret the two offices share (`dgo_link` in the credential plane). Two facts come out of it, and they are the only
two a caller needs: WHICH office, and that the door said so.

The contract
------------
    x-dgo-office:   <office id>
    x-dgo-identity: v1 <office> <user> <unix-seconds> <hex hmac-sha256 of "v1\\n<office>\\n<user>\\n<ts>">

Anything that does not verify — a signature signed with another secret, a tampered field, one older than
`SIG_WINDOW`, a missing signature — is not an identity: the caller is refused, by name, and told which of the cases
it is. `link_secret` finds this office's copy of the pair's secret in the credential plane, matched exactly as the
door matches it. Self-contained and importable without a web server, a vault or a machine (the HTTP is injected):
test_link_identity.py beside it proves the arithmetic, the window, every refusal and the vault's matching.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import time

#: The two headers the door writes. Both are removed from a request the door carries in, before it writes its own,
#: so a peer cannot smuggle a claim of its own.
OFFICE_HEADER = "x-dgo-office"
IDENTITY_HEADER = "x-dgo-identity"

#: What is signed, and the whole of it — the same two functions as the door's, so the halves cannot drift. Version
#: first: a future format is a new version, never a reinterpretation of this one.
SIG_VERSION = "v1"
SIG_WINDOW = 300

#: An office id: the rule the compiler and the link's own declaration apply.
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

    Returns `(ok, kind, why)`. `kind` is the case, for the caller's own sentence: `ok`, `unsigned` (no signature at
    all — a caller can be a door older than this op, which is worth saying differently from a lie), `mismatch` (a
    signature naming another office), `no-secret`, `stale`, `bad-mac`, `malformed`. `why` is the reason in the
    office's words, already ready to show a person.
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

    The strongest proof is the signature (`verify`). A door older than the signature writes the office and no
    signature, and the office it serves is real: an app that already served it may keep a second proof, WHERE it
    came from — the door runs in the link network's own namespace, so its requests arrive from that one address,
    which any OTHER container in the office network does not have. An app that RUNS something for a peer does not
    take this second proof: it asks for the signature.
    """
    addr = str(client or "").strip()
    if not addr:
        return False
    return addr in {str(a).strip() for a in (addresses or ()) if a}


def link_secret(get_json, office: str) -> str | None:
    """This office's copy of the secret it shares with ONE linked office (`dgo_link` in the credential plane) — what
    the door signs with. Matched EXACTLY as the door matches it: `dgo_link-<office>`, or `<a>-><b>` in the hint, and
    never an agent credential a linked office handed over (`dgo_link-serve-*-agent`). Never a split on `-`: office ids
    carry hyphens (hp-laptop, hos-005).

    `get_json(path, params) -> (status, body)` is the vault's HTTP, injected. "" means the vault ANSWERED and holds
    no secret for that pair; None means it did not answer — which the caller refuses. The two looked the same once,
    and for a minute after a vault hiccup an unsigned request passed as "a pair without a secret".
    """
    office = str(office or "").strip().lower()
    if not OFFICE_RE.match(office):
        return ""
    try:
        status, body = get_json("/api/instances", {"protocol": "dgo_link"})
        if status != 200:
            return None
        for row in (body or {}).get("instances") or []:
            iid = str(row.get("id") or "").lower()
            if iid.startswith("dgo_link-serve-") and iid.endswith("-agent"):
                continue
            hint = str(row.get("account_hint") or "").lower().split(" ", 1)[0]
            if iid == f"dgo_link-{office}" or ("->" in hint and office in hint.split("->")):
                status, body = get_json(f"/api/instances/{row.get('id')}/secret", None)
                if status != 200:
                    return None
                tok = str(((body or {}).get("secret") or {}).get("token") or "")
                if tok:
                    return tok
    except (OSError, ValueError):
        return None
    return ""


class Secrets:
    """`office -> the pair's secret`, read from the credential plane and remembered for a while.

    The vault is a service; this is on the request path, so it is read once per office per `ttl`. `fetch` is
    injected (it does the HTTP) so this class can be proved without a network — and so an app names the vault in
    exactly one place. A vault that did not answer (None) is not remembered: the next request asks again.
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
            token = self._fetch(office)
        except Exception:                        # noqa: BLE001 — a vault that is down is "no secret"
            token = None
        if token is None:
            return ""
        self._cache[office] = (now, str(token))
        return str(token)

    def forget(self, office: str = "") -> None:
        """Drop one office's (or every) remembered secret — a pairing changed its key."""
        if office:
            self._cache.pop(str(office).strip().lower(), None)
        else:
            self._cache.clear()
