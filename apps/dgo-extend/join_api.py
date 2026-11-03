"""dgo-extend.join_api — an office that can only DIAL joins another one by DECLARING it (`DGO_JOIN`).

THE CASE. An office in a Claude cloud sandbox (measured 2026-10-15, ai/context/fresh-office-cloud-
sandbox-2026-10-15.md), in CI, on a laptop behind a hotel network, is a black box until it is linked:
nothing reaches it, it has no screen anybody watches, and the two-code pairing (pair_api.py) needs a
person at both screens within ten minutes. The owner, 2026-10-19: «fully declarative connection …
the vm is black box until we connect it to our vps». So the office links ITSELF, from one line of its
`.env` (or of the environment it runs in), over the one path every such network leaves open: HTTPS to
the other office's edge.

WHAT IS CARRIED IS THE PAIRING THAT EXISTS. The joiner's offer (DGOPAIR1:), the host's sealed and
signed reply (DGOPAIRR1:), the same records, link tokens, slots and render — nothing new on the wire
of the tunnel. Only the one human step of a pairing, comparing six digits on two screens, is replaced
by one of two things, each the industry's answer for a machine with no person in front of it:

* an INVITE (`DGOJOIN1:`, Tailscale's auth key, kubeadm's bootstrap token). The host mints it: the
  host's link address, the host's identity key (the joiner PINS it — a reply signed by any other key
  is refused, whoever is in the middle, an intercepting proxy included), an invite id, and an Ed25519
  PRIVATE key that is the access key. The host keeps only the public half, so the host's disk holds no
  secret that admits anybody. The joiner signs its offer with the invite key; the host verifies it and
  answers at once. Scoped like a key should be: one office id (or any), one direction, an expiry,
  single-use or reusable (a sandbox is reborn with new keys under the same id, and replaces its own
  last record — never anybody else's), revocable, listed with its uses.
* an APPROVAL (the device-code pattern of every TV and CLI). The joiner declares only the host's
  address — and its fingerprint, which is public, to pin it — and asks. The request waits on the
  host's screen (and in its notifications) with the joiner's fingerprint, which the joiner prints too,
  until a person approves it or refuses it. No secret exists anywhere.

WHAT MAKES IT SAFE WITH SOMEBODY IN THE MIDDLE (an intercepting proxy reads and can rewrite every
byte of the HTTPS here — a sandbox's does). Three bindings, each held by a test (`selftest`), found
missing by the second reader of 2026-10-19 and closed before this ran anywhere:
  · the OFFER is signed by the identity it names (`prove_offer`): its ephemeral key — the one the
    link token is sealed to — and its WireGuard key cannot be swapped under a real office's name;
  · the REPLY binds the host's WireGuard key inside what the host signed (pairing.accept/open_reply,
    `require_wg`): the pin on the identity key covers the tunnel key too;
  · an offer is answered ONCE (`granted`), and a join replaces only a record that a join through
    this same door wrote (its door URL and the pair id it recorded) — never a record a person paired.

WHAT IS NEVER ACCEPTED: a password. The owner asked for «.env username and password» on 2026-10-15
(dgo-dev p3-8): whoever holds them can do everything on the other office anyway. The research answer
(reports/DGO Extend Go mesh redesign.md; research_notes/…/implemented_decision.md) is that it is the
widest credential there is, put in the one place it must never be — the `.env` of a machine that is
a black box — where it cannot be scoped to one office or one direction, cannot be revoked for one
machine without changing it for everyone, breaks the day the account gets a second factor, and makes
a sandbox's permission classifier refuse the run (measured 2026-10-15). The invite gives the same one
line in `.env` with none of that, and the approval gives "just tell it where" with no secret at all.

THE TRANSPORT. A joined pair rides the carriers' TCP path through the host's DOOR: the joiner's
`dgo-carry` opens `wss://<link host>/carry` through whatever proxy its network has, the host's edge
hands it to the host's carrier (carrier/door.go), and the pair is proved by its WireGuard keys before
a datagram moves. One public port carries every office that joins, where UDP would need one published
port per pair — and an office can publish only one (hooks/prepare 2b).

WHO OWNS WHAT. This module decides who may join and runs both halves of the pairing for them; the
records, tokens and render stay the Pairing engine's (`pair_api.Pairing`), and the door's HTTP surface
is the carrier's (it passes only `POST /join` and `GET /join/<id>` here, and 404s everything else).
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import declaration
import pairing
import pair_api
from pair_api import PairError

log = logging.getLogger("dgo-extend.join")

INVITE_PREFIX = "DGOJOIN1:"
#: What the invite key signs, before the invite id and the offer: a signature made for anything else
#: (a pairing reply, another protocol) can never be replayed as a join.
SIG_CONTEXT = b"dgo-join/1\n"
#: How long a request waits for a person: the life of the offer it carries (the joiner asks again,
#: with a fresh offer, when it runs out — the screen shows one request per office all along).
REQUEST_TTL = pairing.OFFER_TTL
MAX_PENDING = 20
#: …and from one address: anybody can reach the door, so asking is bounded where it comes from too.
MAX_PENDING_PER_SOURCE = 3
#: The owner is told about a new request at most this often (seconds), whatever arrives.
NOTIFY_EVERY = 60
#: How long a granted offer id is remembered — longer than any offer lives, so none is answered twice.
GRANTED_KEEP = 3600
#: What the joining office's IDENTITY key signs: the offer whole (its ephemeral and WireGuard keys).
PROOF_CONTEXT = b"dgo-join/1 offer\n"
#: The joiner's clock: how often it asks how its request stands, and how long it rests after a
#: failure or a refusal.
POLL_EVERY = 5
RETRY_EVERY = 30
REFUSED_REST = 900
DEFAULT_INVITE_TTL = 7 * 86400

HOST_RE = re.compile(r"^[a-z0-9]([a-z0-9.\-]{0,251}[a-z0-9])?\Z")
ID_RE = re.compile(r"^[0-9a-f]{16}\Z")
RID_RE = re.compile(r"^[0-9a-f]{16}\Z")
KEY_RE = re.compile(r"^[A-Za-z0-9+/]{43}=\Z")
FP_RE = re.compile(r"^[0-9A-F]{4}(-[0-9A-F]{4}){3}\Z")


def link_host(env: dict | None = None) -> str:
    """This office's public link host (`DGO_LINK_HOST`, e.g. `link.staging.digital-office.co.il`): the
    name the edge routes to the door. Empty = this office has no door, and takes no joins."""
    host = str((env if env is not None else os.environ).get("DGO_LINK_HOST") or "").strip().lower()
    return host if HOST_RE.match(host) and "." in host else ""


def door_url(host: str) -> str:
    return f"wss://{host}/carry"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def _unb64(text: str, size: int | None = None) -> bytes:
    raw = base64.b64decode(str(text or ""), validate=True)
    if size is not None and len(raw) != size:
        raise ValueError(f"expected {size} bytes")
    return raw


def _hash(secret: str) -> str:
    return hashlib.sha256(str(secret).encode()).hexdigest()


def fingerprint_of(identity: dict) -> str:
    """The fingerprint two screens compare — identity.py's rule, from a PUBLIC identity."""
    material = str(identity.get("ed25519") or "") + str(identity.get("wg") or "")
    digest = hashlib.sha256(material.encode()).hexdigest().upper()
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


# ── the invite, as text ──────────────────────────────────────────────────────────────────────────
def invite_text(doc: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode())
    return INVITE_PREFIX + body.decode().rstrip("=")


def parse_invite(text: str) -> dict:
    """An invite, checked field by field — it arrives from `.env`, a paste box or a chat."""
    t = re.sub(r"\s+", "", str(text or ""))
    if not t.startswith(INVITE_PREFIX):
        raise PairError(f"זו אינה הזמנה — היא מתחילה ב-{INVITE_PREFIX}", 400)
    body = t[len(INVITE_PREFIX):]
    try:
        doc = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (ValueError, TypeError) as e:
        raise PairError("ההזמנה אינה קריאה (או שנחתכה בדרך)", 400) from e
    if not isinstance(doc, dict) or doc.get("v") != 1:
        raise PairError("גרסת ההזמנה אינה מוכרת", 400)
    hub = urlparse(str(doc.get("hub") or ""))
    if hub.scheme != "https" or not HOST_RE.match(hub.hostname or "") or hub.path not in ("", "/"):
        raise PairError("כתובת הלשכה שבהזמנה אינה https://<host>", 400)
    if not ID_RE.match(str(doc.get("id") or "")):
        raise PairError("מזהה ההזמנה אינו תקין", 400)
    for key in ("key", "pin"):
        if not KEY_RE.match(str(doc.get(key) or "")):
            raise PairError(f"השדה {key} של ההזמנה אינו מפתח (base64 של 32 בתים)", 400)
    office = str(doc.get("office") or "")
    if office and not pairing.OFFICE_RE.match(office):
        raise PairError("מזהה הלשכה שבהזמנה אינו תקין", 400)
    return {"hub": f"https://{hub.hostname}{':' + str(hub.port) if hub.port else ''}",
            "id": doc["id"], "key": doc["key"], "pin": doc["pin"], "office": office,
            "label": str(doc.get("label") or "")[:60], "direction": str(doc.get("direction") or "")}


def sign_offer(seed_b64: str, iid: str, offer_text: str) -> str:
    message = SIG_CONTEXT + iid.encode() + b"\n" + offer_text.encode()
    return _b64(pairing.ed25519_sign(pairing.ed25519_private_der(seed_b64), message))


def verify_offer(pub_b64: str, iid: str, offer_text: str, sig_b64: str) -> bool:
    try:
        sig = _unb64(sig_b64)
    except ValueError:
        return False
    message = SIG_CONTEXT + iid.encode() + b"\n" + offer_text.encode()
    return pairing.ed25519_verify(pairing.ed25519_public_der(pub_b64), message, sig)


def prove_offer(identity_private_b64: str, offer_text: str) -> str:
    """The joining office signs its own offer with its identity key (the key the offer names)."""
    der = pairing.ed25519_private_der(identity_private_b64)
    return _b64(pairing.ed25519_sign(der, PROOF_CONTEXT + offer_text.encode()))


def offer_proved(offer: dict, offer_text: str, proof_b64: str) -> bool:
    """Was this offer signed by the identity it names? Anything malformed is a no."""
    try:
        sig = _unb64(proof_b64)
        pub = pairing.ed25519_public_der(str((offer.get("identity") or {}).get("ed25519") or ""))
    except (ValueError, pairing.PairingError):
        return False
    return pairing.ed25519_verify(pub, PROOF_CONTEXT + offer_text.encode(), sig)


def _new_invite_key() -> tuple[str, str]:
    """(seed, public) of a fresh Ed25519 key, base64 of the raw 32 bytes each."""
    priv_der, pub_der = pairing._ed25519_keypair()
    return _b64(priv_der[-32:]), _b64(pub_der[-32:])


# ── a small JSON file, written whole ─────────────────────────────────────────────────────────────
class _Store:
    def __init__(self, path: Path):
        self.path = Path(path)

    def load(self) -> dict:
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
            return doc if isinstance(doc, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, doc: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=self.path.name + ".")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(doc, f, indent=2, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


# ══ the HOST: who may join, and the host half of their pairing ═══════════════════════════════════
class Hub:
    def __init__(self, engine: pair_api.Pairing, store: Path, notify=None, now=time.time,
                 host=link_host, requests_open=None):
        self.engine = engine
        self.store = _Store(store)
        self.notify = notify or (lambda *a, **k: False)
        self.now = now
        self.host = host
        self.requests_open = requests_open or (lambda: os.environ.get("DGO_JOIN_REQUESTS", "1").strip() != "0")
        self.lock = threading.RLock()
        #: live requests, in memory: each one carries an offer that dies in ten minutes anyway
        self.requests: dict[str, dict] = {}
        self._told: dict[str, float] = {}
        self._last_told = 0.0

    # ── invites ──────────────────────────────────────────────────────────────────────────────────
    def invite_create(self, office: str = "", direction: str = "both", ttl: int | None = None,
                      reusable: bool = False, label: str = "") -> dict:
        host = self.host()
        if not host:
            raise PairError("ללשכה הזאת אין דלת קישור ציבורית (DGO_LINK_HOST) — אין לאן להזמין", 409)
        office = str(office or "").strip().lower()
        if office and not pairing.OFFICE_RE.match(office):
            raise PairError("מזהה הלשכה המוזמנת אינו תקין (אותיות לטיניות קטנות, ספרות ומקף)", 400)
        if direction not in ("use", "serve", "both"):
            raise PairError("כיוון הקישור הוא use, serve או both", 400)
        if reusable and not office:
            # a reusable key for ANY name would let one leaked line become any number of offices
            raise PairError("הזמנה רב-פעמית נקשרת ללשכה אחת בשמה — ציינו office", 400)
        ttl = DEFAULT_INVITE_TTL if ttl is None else int(ttl)
        if ttl < 0:
            raise PairError("תוקף ההזמנה אינו יכול להיות שלילי", 400)
        home = self.engine._home()
        seed, pub = _new_invite_key()
        iid = secrets.token_hex(8)
        now = int(self.now())
        row = {"id": iid, "office": office, "direction": direction, "reusable": bool(reusable),
               "label": str(label or "")[:60], "pub": pub, "created_at": now,
               "expires_at": now + ttl if ttl else 0, "uses": 0}
        with self.lock:
            doc = self.store.load()
            doc.setdefault("invites", {})[iid] = row
            self.store.save(doc)
        text = invite_text({"v": 1, "hub": f"https://{host}", "id": iid, "key": seed,
                            "pin": home["identity"]["ed25519"], "office": office,
                            "label": pair_api.own_label(home), "direction": direction})
        log.info("invite %s minted for %s (%s, %s, expires %s)", iid, office or "any office",
                 direction, "reusable" if reusable else "single use", row["expires_at"] or "never")
        return {"text": text, "invite": self._public(row)}

    def _public(self, row: dict) -> dict:
        now = self.now()
        state = ("revoked" if row.get("revoked_at") else
                 "expired" if row.get("expires_at") and now > row["expires_at"] else
                 "used" if not row.get("reusable") and row.get("uses") else "live")
        return {k: row.get(k) for k in ("id", "office", "direction", "reusable", "label", "created_at",
                                        "expires_at", "uses", "last_used_at", "last_office", "revoked_at")} \
            | {"state": state}

    def invites(self) -> list[dict]:
        return [self._public(r) for r in sorted((self.store.load().get("invites") or {}).values(),
                                                 key=lambda r: -int(r.get("created_at") or 0))]

    def invite_revoke(self, iid: str) -> dict:
        with self.lock:
            doc = self.store.load()
            row = (doc.get("invites") or {}).get(iid)
            if not row:
                raise PairError("אין הזמנה כזאת", 404)
            row["revoked_at"] = int(self.now())
            self.store.save(doc)
        return {"ok": True, "invite": self._public(row)}

    # ── the door's two public calls ──────────────────────────────────────────────────────────────
    def join(self, body: dict, source: str = "") -> dict:
        """POST /join — an offer, signed by the identity it names, with an invite's signature too or
        without one."""
        if not self.host():
            raise PairError("ללשכה הזאת אין דלת קישור ציבורית", 404)
        body = body if isinstance(body, dict) else {}
        text = str(body.get("offer") or "")
        if len(text) > 16384:
            raise PairError("ההצעה ארוכה מדי", 413)
        try:
            offer = pairing.parse_offer(text)
        except pairing.PairingError as e:
            raise PairError(str(e), 400) from e
        now = self.now()
        if pairing.is_expired(offer, now):
            raise PairError("ההצעה פגה — הלשכה המצטרפת שולחת חדשה", 400)
        # An offer lives OFFER_TTL from the moment it was made. One that says it lives longer, or was
        # made in the future, is not one this code wrote — and would hold a request (and the screen's
        # attention) for as long as its sender likes.
        if int(offer.get("expires_at") or 0) > now + pairing.OFFER_TTL + 60 \
                or int(offer.get("created_at") or 0) > now + 60:
            raise PairError("תוקף ההצעה אינו התוקף שהלשכה הזאת מקבלת", 400)
        # THE OFFER IS PROVED BY THE IDENTITY IT NAMES. Its ephemeral key — the one the reply, and the
        # link token in it, is sealed to — and its WireGuard key are bound to that identity here, so a
        # party between the offices (an intercepting proxy) can neither put its own ephemeral key under
        # a real office's name nor its own WireGuard key: the person who approves a fingerprint, and
        # the invite that names an office, admit exactly the office that holds that key.
        if not offer_proved(offer, text, str(body.get("proof") or "")):
            raise PairError("ההצעה אינה חתומה בזהות שהיא נושאת", 403)
        iid = str(body.get("invite") or "")
        if iid:
            return self._join_invited(text, offer, iid, str(body.get("sig") or ""), source)
        return self._ask(text, offer, source)

    def _join_invited(self, text: str, offer: dict, iid: str, sig: str, source: str) -> dict:
        with self.lock:
            doc = self.store.load()
            row = (doc.get("invites") or {}).get(iid) if ID_RE.match(iid) else None
            # One answer for every invite that does not admit: which of them it was is the inviting
            # office's business, not the asker's.
            refused = PairError("ההזמנה אינה בתוקף בלשכה הזאת (לא קיימת, בוטלה, פגה או נוצלה)", 403)
            if not row or row.get("revoked_at"):
                raise refused
            if row.get("expires_at") and self.now() > row["expires_at"]:
                raise refused
            if not row.get("reusable") and row.get("uses"):
                raise refused
            if row.get("office") and offer["office"] != row["office"]:
                raise PairError(f"ההזמנה הזאת היא ללשכה {row['office']}, וההצעה היא של {offer['office']}", 403)
            if not verify_offer(row["pub"], iid, text, sig):
                raise PairError("מפתח ההזמנה לא חתם על הבקשה הזאת", 403)
            direction = row["direction"]
            # An invite for ANY office only creates: a name it does not carry is no claim on a record.
            reply = self._grant(text, offer, direction, via=f"invite:{iid}",
                                replace=False if not row.get("office") else None)
            # _grant wrote the store (who joined): the use is counted on what it wrote, not on the copy
            # read before it
            doc = self.store.load()
            used = (doc.get("invites") or {}).get(iid) or row
            used.update(uses=int(used.get("uses") or 0) + 1, last_used_at=int(self.now()),
                        last_office=offer["office"])
            doc.setdefault("invites", {})[iid] = used
            self.store.save(doc)
        label = str(offer.get("label") or offer["office"])[:60]
        self.notify(f"dgo-join-{offer['office']}-{offer['offer_id'][:8]}",
                    f"הלשכה {label} הצטרפה בהזמנה",
                    f"{offer['office']} ({fingerprint_of(offer['identity'])}) הצטרפה מ-{source or 'כתובת לא ידועה'} "
                    f"בהזמנה {iid}, כיוון {direction}.", "info")
        log.info("%s joined with invite %s from %s", offer["office"], iid, source or "?")
        return {"state": "approved", "reply": reply}

    def _ask(self, text: str, offer: dict, source: str) -> dict:
        if not self.requests_open():
            raise PairError("הלשכה הזאת אינה מקבלת בקשות הצטרפות בלי הזמנה", 403)
        fp = fingerprint_of(offer["identity"])
        label = str(offer.get("label") or offer["office"])[:60]
        # A request is ONE offer. A joiner that asks again (its offer ran out) replaces its own PENDING
        # request, so the screen shows one row and an approval meets the newest offer; a request that
        # was approved or refused is never overwritten by anybody.
        rid = hashlib.sha256(f"{offer['office']}\n{fp}\n{offer['offer_id']}".encode()).hexdigest()[:16]
        poll = secrets.token_hex(16)
        now = self.now()
        with self.lock:
            self._gc()
            if rid in self.requests:
                raise PairError("ההצעה הזאת כבר נשאלה — שואלים על הבקשה שלה", 409)
            mine = [q for q in self.requests.values() if q["office"] == offer["office"] and q["fingerprint"] == fp]
            if any(q["state"] == "refused" for q in mine):
                raise PairError("הבקשה של הלשכה הזאת נדחתה כאן", 403)
            for q in mine:
                if q["state"] == "pending":
                    self.requests.pop(q["rid"], None)
            pending = [q for q in self.requests.values() if q["state"] == "pending"]
            if source and sum(1 for q in pending if q["from"] == source) >= MAX_PENDING_PER_SOURCE:
                raise PairError("יותר מדי בקשות ממתינות מהכתובת הזאת — נסו שוב מאוחר יותר", 429)
            if len(pending) >= MAX_PENDING:
                raise PairError("יותר מדי בקשות ממתינות בלשכה הזאת — נסו שוב מאוחר יותר", 429)
            expires = min(int(offer["expires_at"]), int(now + REQUEST_TTL))
            self.requests[rid] = {"rid": rid, "office": offer["office"], "label": label,
                                  "fingerprint": fp, "offer": text, "offer_id": offer["offer_id"],
                                  "direction": str(offer.get("direction") or ""), "from": source,
                                  "at": int(now), "expires_at": expires,
                                  "state": "pending", "poll": _hash(poll)}
            # Told once an hour per office and key, and nothing more often than NOTIFY_EVERY in all:
            # whoever can reach the door can ask, and asking must not become a way to flood the owner.
            self._told = {k: t for k, t in self._told.items() if now - t < 3600}
            key = f"{offer['office']}\n{fp}"
            tell = key not in self._told and now - self._last_told >= NOTIFY_EVERY
            if tell:
                self._told[key] = self._last_told = now
        if tell:
            self.notify(f"dgo-join-request-{rid}", f"{label} מבקשת להצטרף",
                        f"הלשכה {offer['office']} (טביעת אצבע {fp}) מבקשת להצטרף ללשכה הזאת מ-{source or '?'}. "
                        "אשרו או דחו במסך „הרחבת הלשכה”, או: bbox dgo join approve " + offer["office"], "warning")
        log.info("join request %s from %s (%s) at %s", rid, offer["office"], fp, source or "?")
        return {"state": "pending", "request": rid, "poll": poll, "fingerprint": fp, "expires_at": expires}

    def poll(self, rid: str, poll: str) -> dict:
        """GET /join/<id> — the asker's own request, and only with its own poll secret."""
        with self.lock:
            self._gc()
            req = self.requests.get(rid) if RID_RE.match(str(rid or "")) else None
            if not req or not secrets.compare_digest(req["poll"], _hash(poll)):
                return {"state": "unknown"}
            out = {"state": req["state"]}
            if req["state"] == "approved":
                out["reply"] = req["reply"]
            return out

    def _gc(self) -> None:
        now = self.now()
        for rid in [r for r, q in self.requests.items() if now > q["expires_at"] + 60]:
            if self.requests[rid]["state"] != "refused" or now > self.requests[rid]["expires_at"] + REFUSED_REST:
                self.requests.pop(rid, None)

    # ── a person's two answers ───────────────────────────────────────────────────────────────────
    def pending(self) -> list[dict]:
        with self.lock:
            self._gc()
            return [{k: q[k] for k in ("rid", "office", "label", "fingerprint", "direction", "from",
                                       "at", "expires_at", "state")}
                    for q in sorted(self.requests.values(), key=lambda q: -q["at"])]

    def _find(self, ref: str) -> dict:
        self._gc()
        req = self.requests.get(ref)
        if not req:
            live = [q for q in self.requests.values() if q["office"] == ref and q["state"] == "pending"]
            req = live[0] if len(live) == 1 else None
        if not req:
            raise PairError("אין בקשה ממתינה כזאת (אולי פגה — הלשכה שואלת שוב בעצמה תוך דקה)", 404)
        return req

    def approve(self, ref: str, direction: str = "", replace: bool | None = None) -> dict:
        with self.lock:
            req = self._find(ref)
            if req["state"] != "pending":
                raise PairError(f"הבקשה כבר {req['state']}", 409)
            try:
                offer = pairing.parse_offer(req["offer"])
            except pairing.PairingError as e:
                raise PairError(str(e), 400) from e
            if pairing.is_expired(offer, self.now()):
                raise PairError("ההצעה שבבקשה פגה — הלשכה שולחת חדשה תוך דקה, ואז מאשרים אותה", 410)
            if direction not in ("use", "serve", "both"):
                direction = pair_api.mirror(req["direction"]) if req["direction"] in ("use", "serve", "both") else "both"
            req["reply"] = self._grant(req["offer"], offer, direction, via="approval", replace=replace)
            req["state"], req["approved_at"], req["granted"] = "approved", int(self.now()), direction
        log.info("join request %s (%s) approved, %s", req["rid"], req["office"], direction)
        return {"ok": True, "office": req["office"], "fingerprint": req["fingerprint"], "direction": direction}

    def refuse(self, ref: str) -> dict:
        with self.lock:
            req = self._find(ref)
            req["state"] = "refused"
            req["expires_at"] = int(self.now())
        log.info("join request %s (%s) refused", req["rid"], req["office"])
        return {"ok": True, "office": req["office"]}

    def joined(self) -> dict:
        return dict(self.store.load().get("joined") or {})

    # ── the host half of the pairing, with the comparison of six digits replaced ─────────────────
    def _grant(self, text: str, offer: dict, direction: str, via: str, replace: bool | None = None) -> str:
        """claim + confirm in one step. What the six digits prove in a pairing — that nobody in the
        middle swapped the offer — is proved here by the offer's own signature (`offer_proved`: its
        keys are its identity's) together with the invite's signature or a person's approval of THAT
        identity's fingerprint; the reply is sealed to the offer's key and signed by this office, and
        binds this office's WireGuard key, so the joiner checks all of it against the identity it
        pinned.

        `replace` None means the rule: a record is replaced only when a JOIN through this door wrote
        it — this office's door on it, and the pair id the join recorded. That is the same sandbox
        reborn with new keys. A record a person paired, an office this office installed, or a record
        under a name a join once used and a person has paired since, is never taken by a join."""
        office = offer["office"]
        now = self.now()
        door = door_url(self.host())
        with self.lock:
            doc = self.store.load()
            # AN OFFER IS ANSWERED ONCE. A replay of a granted offer (a proxy that saw it pass, within
            # its ten minutes) would mint a second link token the joiner never receives.
            granted = {k: t for k, t in (doc.get("granted") or {}).items() if now - int(t) < GRANTED_KEEP}
            if offer["offer_id"] in granted:
                raise PairError("ההצעה הזאת כבר נענתה — הצעה היא חד-פעמית", 409)
            if replace is None:
                existing = self.engine._existing(office)
                wrote = (doc.get("joined") or {}).get(office) or {}
                tun = (existing or {}).get("tunnel") or {}
                replace = bool(existing) and declaration.is_paired(existing) and tun.get("door") == door \
                    and bool(wrote.get("pair_id")) and wrote.get("pair_id") == existing.get("pair_id")
            claim = self.engine.claim(text, direction=direction, replace=replace, door=door)
            out = self.engine.claim_confirm(claim["rendezvous_id"], claim["code"], replace=replace)
            doc = self.store.load()
            doc["granted"] = {**granted, offer["offer_id"]: int(now)}
            doc.setdefault("joined", {})[office] = {"via": via, "at": int(now),
                                                    "pair_id": offer["offer_id"],
                                                    "fingerprint": fingerprint_of(offer["identity"]),
                                                    "slot": (out.get("link") or {}).get("slot")}
            self.store.save(doc)
        return claim["reply_text"]


# ══ the JOINER: the declaration, and the loop that carries it out ════════════════════════════════
def _ca_bundle() -> str | bool:
    """What a joiner trusts for the host's TLS: the usual roots, and the CA this office was told to
    accept (`DGO_EGRESS_CA` — a sandbox's intercepting proxy). `requests` reads only certifi's bundle,
    so the three are written into one file when there is a third."""
    extra = str(os.environ.get("DGO_EGRESS_CA") or "").strip()
    try:
        pem = Path(extra).read_text(encoding="utf-8") if extra else ""
    except OSError:
        pem = ""
    if "BEGIN CERTIFICATE" not in pem:
        return True
    parts = [pem]
    for path in (_certifi(), "/etc/ssl/certs/ca-certificates.crt"):
        try:
            parts.append(Path(path).read_text(encoding="utf-8"))
        except (OSError, TypeError):
            continue
    out = Path(tempfile.gettempdir()) / "dgo-join-ca.pem"
    text = "\n".join(parts)
    try:
        if not out.exists() or out.read_text(encoding="utf-8") != text:
            out.write_text(text, encoding="utf-8")
    except OSError:
        return True
    return str(out)


def _certifi() -> str | None:
    try:
        import certifi
        return certifi.where()
    except ImportError:
        return None


def _http(method: str, url: str, body: dict | None = None, headers: dict | None = None) -> tuple[int, dict]:
    import requests
    try:
        r = requests.request(method, url, json=body, headers=headers or {}, timeout=30, verify=_ca_bundle())
    except requests.RequestException as e:
        log.warning("join: %s %s: %s: %s", method, url, type(e).__name__, e)
        why = ("האישור (TLS) שלה לא אומת — רשת עם פרוקסי מיירט צריכה את ה-CA שלו (DGO_EGRESS_CA_FILE)"
               if isinstance(e, requests.exceptions.SSLError) else
               "הפרוקסי של הרשת הזאת סירב או אינו עונה (DGO_EGRESS_PROXY)"
               if isinstance(e, requests.exceptions.ProxyError) else
               "לא הגיעה תשובה בזמן" if isinstance(e, requests.exceptions.Timeout) else
               "אי אפשר להתחבר אליה מכאן")
        raise PairError(f"הלשכה אינה עונה ב-{url}: {why}", 502) from e
    try:
        doc = r.json()
    except ValueError:
        doc = {"error": (r.text or "")[:300]}
    return r.status_code, doc if isinstance(doc, dict) else {"error": str(doc)[:300]}


def declared(env: dict | None = None) -> bool:
    """Whether this office declared a join at all. The loop starts on that alone, so a declaration it
    cannot read is reported on the screen (`invalid`) instead of failing the app's start."""
    return bool(str((env if env is not None else os.environ).get("DGO_JOIN") or "").strip())


def parse_declaration(env: dict | None = None) -> dict | None:
    """`DGO_JOIN` (+ `DGO_JOIN_PIN`, `DGO_JOIN_DIRECTION`), as the joiner reads it. None = no join.

    DGO_JOIN=DGOJOIN1:…                 an invite: joins with no person, pinned by the invite itself
    DGO_JOIN=https://link.example.org   asks; a person approves it on that office's screen
    DGO_JOIN_PIN=CHANGE_ME     that office's fingerprint (or its Ed25519 key) — a reply from
                                         any other office is refused. Strongly recommended with a URL.
    DGO_JOIN_DIRECTION=both              what this office asks for (the host decides): use|serve|both
    """
    env = env if env is not None else os.environ
    raw = re.sub(r"\s+", "", str(env.get("DGO_JOIN") or ""))
    if not raw:
        return None
    direction = str(env.get("DGO_JOIN_DIRECTION") or "both").strip().lower()
    if direction not in ("use", "serve", "both"):
        raise PairError("DGO_JOIN_DIRECTION הוא use, serve או both", 400)
    pin = str(env.get("DGO_JOIN_PIN") or "").strip()
    if raw.startswith(INVITE_PREFIX):
        inv = parse_invite(raw)
        return {"hub": inv["hub"], "invite": inv, "pin": inv["pin"], "direction": direction}
    url = urlparse(raw if "://" in raw else f"https://{raw}")
    if url.scheme != "https" or not HOST_RE.match(url.hostname or ""):
        raise PairError("DGO_JOIN הוא הזמנה (DGOJOIN1:…) או כתובת https של דלת הקישור של הלשכה", 400)
    if pin and not (FP_RE.match(pin.upper()) or KEY_RE.match(pin)):
        raise PairError("DGO_JOIN_PIN הוא טביעת האצבע של הלשכה (XXXX-XXXX-XXXX-XXXX) או מפתח ה-Ed25519 שלה", 400)
    return {"hub": f"https://{url.hostname}{':' + str(url.port) if url.port else ''}", "invite": None,
            "pin": pin, "direction": direction}


def pin_holds(pin: str, identity: dict) -> bool:
    """Is this the office the declaration named? An Ed25519 key is compared whole, a fingerprint as
    identity.py computes it. No pin holds for any office — and is said on the screen."""
    if not pin:
        return True
    if KEY_RE.match(pin):
        return secrets.compare_digest(pin, str(identity.get("ed25519") or ""))
    return secrets.compare_digest(pin.upper(), fingerprint_of(identity))


class Joiner:
    def __init__(self, engine: pair_api.Pairing, store: Path, now=time.time, http=_http, env=None):
        self.engine = engine
        self.store = _Store(store)
        self.now = now
        self.http = http
        self.env = env
        self.lock = threading.RLock()
        self.live: dict = {}         # the request being waited on: {rid, poll, offer_rid, hub}
        self.last: dict = {"state": "off"}
        self.rest_until = 0.0
        self.force = False           # `again`: ask even though a record of the host is here

    def _cfg(self) -> dict | None:
        return parse_declaration(self.env)

    @staticmethod
    def _door_of(cfg: dict) -> str:
        """The door URL a join through this declaration writes into the pair's records."""
        return door_url(urlparse(cfg["hub"]).hostname or "")

    def status(self) -> dict:
        out = dict(self.last)
        try:
            home = self.engine.ports.home()
            out["fingerprint"] = (home.get("identity") or {}).get("fingerprint") or ""
            out["office"] = home.get("id")
        except Exception:  # noqa: BLE001 — a status never fails
            pass
        out["joined"] = self.store.load().get("joined") or {}
        return out

    def _say(self, state: str, **facts) -> dict:
        self.last = {"state": state, "at": int(self.now()), **facts}
        return self.last

    def forget(self) -> dict:
        """`bbox dgo join again`: ask again on the next pass even though a record of the host is here
        (a host that lost this office's record, a revoked invite replaced) — and forget a refusal.
        The record stays until the new grant replaces it: a link that works keeps working meanwhile."""
        with self.lock:
            self.live, self.rest_until, self.force = {}, 0.0, True
        return self._say("asking", note="ביקשתי להצטרף מחדש")

    def _holds_link(self, cfg: dict) -> str:
        """The office this declaration already joined — read from the RECORDS, which are the truth: a
        paired record that rides this declaration's door."""
        door = self._door_of(cfg)
        for d in self.engine.ports.declarations():
            if declaration.is_paired(d) and (d.get("tunnel") or {}).get("door") == door:
                return str(d.get("id") or "")
        return ""

    def step(self) -> dict:
        """ONE pass of the loop — what the thread runs, and what a test drives."""
        try:
            cfg = self._cfg()
        except PairError as e:
            return self._say("invalid", error=str(e))
        if not cfg:
            self.live = {}
            return self._say("off")
        with self.lock:
            joined = self._holds_link(cfg)
            if joined and not self.force:
                self.live = {}
                return self._say("joined", hub=cfg["hub"], peer=joined)
            if self.now() < self.rest_until:
                return self.last
            try:
                if self.live and self.live.get("hub") == cfg["hub"]:
                    return self._wait(cfg)
                return self._ask(cfg)
            except PairError as e:
                self.live = {}
                # a host that SAID no (an invite it does not hold, a refused request) is not asked
                # again every half minute
                self.rest_until = self.now() + (REFUSED_REST if e.status == 403 else RETRY_EVERY)
                return self._say("failed", hub=cfg["hub"], error=str(e))

    def _ask(self, cfg: dict) -> dict:
        home = self.engine._home()
        offer = self.engine.offer(direction=cfg["direction"])
        body = {"v": 1, "offer": offer["text"]}
        inv = cfg.get("invite")
        if inv:
            if inv.get("office") and inv["office"] != home["id"]:
                raise PairError(f"ההזמנה היא ללשכה {inv['office']}, והלשכה הזאת היא {home['id']} — "
                                f"הגדירו DGO_OFFICE_ID={inv['office']}", 409)
            body.update(invite=inv["id"], sig=sign_offer(inv["key"], inv["id"], offer["text"]))
        # the offer is proved by this office's own identity key — the key it names (offer_proved)
        body["proof"] = prove_offer(self.engine.ports.identity_private(), offer["text"])
        code, doc = self.http("POST", cfg["hub"] + "/join", body)
        if code != 200:
            raise PairError(f"{cfg['hub']} סירבה: {doc.get('error') or code}", code)
        if doc.get("state") == "approved":
            return self._complete(cfg, offer["rendezvous_id"], str(doc.get("reply") or ""))
        if doc.get("state") == "pending" and RID_RE.match(str(doc.get("request") or "")):
            self.live = {"hub": cfg["hub"], "rid": doc["request"], "poll": str(doc.get("poll") or ""),
                         "offer_rid": offer["rendezvous_id"], "expires_at": int(doc.get("expires_at") or 0)}
            note = "ממתין לאישור במסך של הלשכה — השוו את טביעת האצבע"
            if not cfg.get("pin"):
                note += (". אין DGO_JOIN_PIN: כל לשכה שעונה בכתובת הזאת תתקבל — הוסיפו את טביעת האצבע "
                         "שלה כדי שרק היא תתקבל")
            return self._say("waiting", hub=cfg["hub"], request=doc["request"],
                             fingerprint=home["identity"].get("fingerprint") or "", note=note)
        raise PairError(f"{cfg['hub']} ענתה תשובה לא מוכרת: {str(doc)[:200]}", 502)

    def _wait(self, cfg: dict) -> dict:
        live = self.live
        if self.now() > live.get("expires_at", 0):
            self.live = {}
            return self._ask(cfg)                  # the offer ran out: a fresh one, same request row
        try:
            code, doc = self.http("GET", f"{cfg['hub']}/join/{live['rid']}", None, {"X-Dgo-Poll": live["poll"]})
        except PairError:
            return self.last                       # the path blinked: the request still stands
        if code == 404:
            self.live = {}                         # the host no longer holds it (restarted): ask again
            return self._ask(cfg)
        if code != 200:
            return self.last                       # a 429, a 502: the approval is not lost over it
        state = doc.get("state")
        if state == "approved":
            return self._complete(cfg, live["offer_rid"], str(doc.get("reply") or ""))
        if state == "refused":
            self.live = {}
            self.rest_until = self.now() + REFUSED_REST
            return self._say("refused", hub=cfg["hub"], note="הלשכה דחתה את הבקשה")
        return self.last

    def _complete(self, cfg: dict, offer_rid: str, reply_text: str) -> dict:
        try:
            reply = pairing.parse_reply(reply_text)
        except pairing.PairingError as e:
            raise PairError(str(e), 502) from e
        identity = reply.get("identity") or {}
        if not pin_holds(cfg.get("pin") or "", identity):
            # The answer came from an office the declaration did not name — a proxy in the middle, a
            # host that changed its keys. Nothing is written.
            raise PairError(f"התשובה מ-{cfg['hub']} חתומה בזהות אחרת ({fingerprint_of(identity)}) מזו "
                            "שההצהרה נועצה בה — הצימוד לא נכתב", 403)
        # the reply must bind the host's WireGuard key inside what it signed: nobody compares six
        # digits here, so a key swapped on the way would otherwise become this tunnel's peer
        opened = self.engine.offer_reply(reply_text, offer_rid, require_wg=True)
        host = opened["peer"]["office_id"]
        # Replaced only when there is nothing, or a record a join through THIS door wrote — never a
        # record of that name that a person paired or this office installed.
        existing = self.engine._existing(host)
        replace = not existing or (declaration.is_paired(existing)
                                   and (existing.get("tunnel") or {}).get("door") == self._door_of(cfg))
        out = self.engine.offer_confirm(offer_rid, opened["code"], replace=replace)
        self.force = False
        with self.lock:
            doc = self.store.load()
            doc.setdefault("joined", {})[host] = {"hub": cfg["hub"], "at": int(self.now()),
                                                  "pair_id": (out.get("link") or {}).get("pair_id"),
                                                  "invite": (cfg.get("invite") or {}).get("id") or ""}
            self.store.save(doc)
        self.live = {}
        log.info("joined %s through %s (%s)", host, cfg["hub"], "invite" if cfg.get("invite") else "approval")
        return self._say("joined", hub=cfg["hub"], peer=host, link=out.get("link"))

    def run_forever(self, stop: threading.Event | None = None) -> None:
        stop = stop or threading.Event()
        while not stop.is_set():
            try:
                state = self.step().get("state")
            except Exception as e:  # noqa: BLE001 — the loop outlives any one pass
                log.warning("join pass failed: %s: %s", type(e).__name__, e)
                state = "failed"
            stop.wait(POLL_EVERY if state == "waiting" else RETRY_EVERY)


# ── HTTP ─────────────────────────────────────────────────────────────────────────────────────────
def _publish_request_type():
    """`from __future__ import annotations` makes `request: Request` the STRING "Request", which
    FastAPI resolves in this MODULE's globals — a function-local import is invisible there, and the
    parameter is read as a required query field: every call answered 422 (measured 2026-10-19 on the
    first live POST /join, the same trap pair_api.build_router names). Published once the web stack is
    known to exist, so importing this module still needs none."""
    from fastapi import Request
    globals()["Request"] = Request


def build_public_router(hub: Hub):
    """`POST /join` and `GET /join/<id>` — what the door passes here, and nothing else."""
    from fastapi import APIRouter, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse

    _publish_request_type()
    router = APIRouter()

    async def guarded(fn, *args):
        try:
            return await run_in_threadpool(fn, *args)
        except PairError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)

    @router.post("/join")
    async def join(request: Request):
        try:
            body = await request.json()
        except ValueError:
            body = {}
        return await guarded(hub.join, body if isinstance(body, dict) else {},
                             request.headers.get("x-real-ip") or "")

    @router.get("/join/{rid}")
    async def poll(rid: str, request: Request):
        out = await guarded(hub.poll, rid, request.headers.get("x-dgo-poll") or "")
        if isinstance(out, dict) and out.get("state") == "unknown":
            return JSONResponse(out, status_code=404)
        return out

    return router


def build_admin_router(hub: Hub, joiner: Joiner):
    """The person's side — behind this office's sign-in like every other `/api/*` of the app."""
    from fastapi import APIRouter, Request
    from fastapi.concurrency import run_in_threadpool
    from fastapi.responses import JSONResponse

    _publish_request_type()
    router = APIRouter()

    async def guarded(fn, *args, **kwargs):
        try:
            return await run_in_threadpool(fn, *args, **kwargs)
        except PairError as e:
            return JSONResponse({"error": str(e)}, status_code=e.status)

    async def body_of(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    @router.get("/api/join")
    async def overview():
        host = hub.host()
        return {"door": {"host": host, "url": f"https://{host}" if host else ""},
                "requests": hub.pending(), "invites": hub.invites(), "joined": hub.joined(),
                "joiner": joiner.status()}

    @router.post("/api/join/{ref}/approve")
    async def approve(ref: str, request: Request):
        b = await body_of(request)
        replace = b.get("replace")
        return await guarded(hub.approve, ref, str(b.get("direction") or ""),
                             None if replace is None else bool(replace))

    @router.post("/api/join/{ref}/refuse")
    async def refuse(ref: str):
        return await guarded(hub.refuse, ref)

    @router.post("/api/join/again")
    async def again():
        return await guarded(joiner.forget)

    @router.post("/api/invite")
    async def invite(request: Request):
        b = await body_of(request)
        ttl = b.get("ttl_seconds")
        return await guarded(hub.invite_create, str(b.get("office") or ""), str(b.get("direction") or "both"),
                             None if ttl is None else int(ttl), bool(b.get("reusable")), str(b.get("label") or ""))

    @router.get("/api/invite")
    async def invites():
        return {"invites": hub.invites()}

    @router.delete("/api/invite/{iid}")
    async def revoke(iid: str):
        return await guarded(hub.invite_revoke, iid)

    return router


# ── the gate's half: a host and a sandbox in memory, both ways of joining, every refusal ─────────
def selftest() -> list[str]:
    import tempfile as _tf
    problems: list[str] = []
    tmp = Path(_tf.mkdtemp(prefix="join-selftest-"))
    LINK = "link.example.org"

    def hub_of(ports, host=LINK):
        return Hub(pair_api.Pairing(ports), tmp / f"hub-{ports.home()['id']}-{secrets.token_hex(3)}.json",
                   host=lambda: host)

    def shim(hub, source="203.0.113.5"):
        def http(method, url, body=None, headers=None):
            try:
                if method == "POST" and url.endswith("/join"):
                    return 200, hub.join(body or {}, source)
                if method == "GET" and "/join/" in url:
                    out = hub.poll(url.rsplit("/", 1)[1], (headers or {}).get("X-Dgo-Poll", ""))
                    return (404 if out.get("state") == "unknown" else 200), out
            except PairError as e:
                return e.status, {"error": str(e)}
            return 404, {"error": "no such path"}
        return http

    def joiner_of(ports, hub, env):
        return Joiner(pair_api.Pairing(ports), tmp / f"joiner-{secrets.token_hex(3)}.json",
                      http=shim(hub), env=env)

    def refused(name, fn, *a, **k):
        try:
            fn(*a, **k)
            problems.append(f"must be refused: {name}")
        except PairError:
            pass

    vps1 = pair_api._MemoryPorts("vps1", "vps1", slot=1, listen={"endpoint": "console.example.org", "port": 51830})
    hub = hub_of(vps1)
    pin = vps1.home()["identity"]["ed25519"]

    # ── an invite: no person anywhere ────────────────────────────────────────────────────────────
    refused("a reusable invite for ANY office", hub.invite_create, "", "both", None, True)
    refused("an invite from an office with no door", hub_of(vps1, host="").invite_create, "claude-cloud")
    minted = hub.invite_create("claude-cloud", "both", reusable=True)
    if "key" in minted["invite"] or "pub" in minted["invite"]:
        problems.append("the invite's listing carries no key, public or private")
    if "seed" in json.dumps(hub.store.load()) or parse_invite(minted["text"])["key"] in json.dumps(hub.store.load()):
        problems.append("the host keeps only the invite's PUBLIC key — the access key is in the text alone")
    cloud = pair_api._MemoryPorts("claude-cloud", "Claude Cloud", slot=1)
    j = joiner_of(cloud, hub, {"DGO_JOIN": minted["text"]})
    got = j.step()
    if got.get("state") != "joined" or got.get("peer") != "vps1":
        problems.append(f"a sandbox with an invite in its .env joins with nobody looking: {got}")
    rh, rj = vps1.records.get("claude-cloud") or {}, cloud.records.get("vps1") or {}
    th, tj = rh.get("tunnel") or {}, rj.get("tunnel") or {}
    door = f"wss://{LINK}/carry"
    if th.get("door") != door or tj.get("door") != door or th.get("transport") != "tcp" or tj.get("transport") != "tcp":
        problems.append(f"a joined pair rides the host's door on the TCP path, on both ends: {th} / {tj}")
    if th.get("dial") != "joiner" or tj.get("dial") != "joiner" or th.get("port") != pair_api.DOOR_WG_BASE + th.get("slot", 0):
        problems.append(f"the sandbox dials; the host's port is local (DOOR_WG_BASE + slot): {th}")
    if not cloud.vault.get("dgo_link-vps1") or not vps1.vault.get("dgo_link-claude-cloud"):
        problems.append("both ends hold the link token, as after any pairing")
    if (hub.invites()[0].get("uses"), hub.invites()[0].get("state")) != (1, "live"):
        problems.append(f"a reusable invite counts its uses and stays live: {hub.invites()[0]}")
    if j.step().get("state") != "joined":
        problems.append("a joined office does not ask again while its record is here")

    # the sandbox is reborn (new keys, same name): the same line joins again, replacing ITS record
    reborn = pair_api._MemoryPorts("claude-cloud", "Claude Cloud", slot=1)
    if joiner_of(reborn, hub, {"DGO_JOIN": minted["text"]}).step().get("state") != "joined" \
            or vps1.records["claude-cloud"]["identity"]["ed25519"] != reborn.home()["identity"]["ed25519"]:
        problems.append("a reborn sandbox replaces its own last record with the same invite")

    # …and never a record a person paired: an office paired from the screens under that name
    vps1.records["hp-laptop"] = {"id": "hp-laptop", "kind": "paired", "tunnel": {"slot": 3}}
    hp_inv = hub.invite_create("hp-laptop", "both", reusable=True)
    impostor = pair_api._MemoryPorts("hp-laptop", "HP?", slot=1)
    if joiner_of(impostor, hub, {"DGO_JOIN": hp_inv["text"]}).step().get("state") == "joined" \
            or vps1.records["hp-laptop"].get("tunnel", {}).get("door"):
        problems.append("a join never replaces a record that a pairing (not a join) wrote")

    # refusals at the host: a forged signature, another office, revoked, expired, used up
    single = hub.invite_create("claude-cloud", "use")
    parsed = parse_invite(single["text"])
    other_seed, _pub = _new_invite_key()
    forged = invite_text({"v": 1, "hub": parsed["hub"], "id": parsed["id"], "key": other_seed,
                          "pin": parsed["pin"], "office": "claude-cloud"})
    fresh = pair_api._MemoryPorts("claude-cloud", "Claude Cloud", slot=1)
    if joiner_of(fresh, hub, {"DGO_JOIN": forged}).step().get("state") == "joined":
        problems.append("an invite whose key is not the one the host minted admits nobody")
    wrong_office = pair_api._MemoryPorts("someone", "X", slot=1)
    if joiner_of(wrong_office, hub, {"DGO_JOIN": single["text"]}).step().get("state") == "joined":
        problems.append("an invite for one office admits no other")
    hub.invite_revoke(parsed["id"])
    if joiner_of(fresh, hub, {"DGO_JOIN": single["text"]}).step().get("state") == "joined":
        problems.append("a revoked invite admits nobody")
    once = hub.invite_create("", "both")
    first = pair_api._MemoryPorts("lab-1", "Lab", slot=1)
    second = pair_api._MemoryPorts("lab-2", "Lab", slot=1)
    if joiner_of(first, hub, {"DGO_JOIN": once["text"]}).step().get("state") != "joined":
        problems.append("a single-use invite admits its first office")
    if joiner_of(second, hub, {"DGO_JOIN": once["text"]}).step().get("state") == "joined":
        problems.append("a single-use invite admits nobody the second time")
    expired_hub = Hub(pair_api.Pairing(vps1), tmp / "hub-expired.json", host=lambda: LINK,
                      now=lambda: time.time() + 8 * 86400)
    late = hub.invite_create("lab-3", "both")
    late_row = hub.store.load()["invites"][parse_invite(late["text"])["id"]]
    expired_hub.store.save({"invites": {late_row["id"]: late_row}})
    try:
        expired_hub._join_invited("x", {"office": "lab-3"}, late_row["id"], "", "")
        problems.append("an expired invite admits nobody")
    except PairError:
        pass

    # a reply signed by another office than the one the invite pinned: nothing written on the joiner
    other = pair_api._MemoryPorts("vps1", "fake vps1", slot=1)
    fake_hub = hub_of(other)
    fake_inv = fake_hub.invite_create("claude-cloud", "both", reusable=True)
    doc = parse_invite(fake_inv["text"])
    pinned_elsewhere = invite_text({"v": 1, "hub": doc["hub"], "id": doc["id"], "key": doc["key"],
                                    "pin": pin, "office": "claude-cloud"})
    victim = pair_api._MemoryPorts("claude-cloud", "Claude Cloud", slot=1)
    st = joiner_of(victim, fake_hub, {"DGO_JOIN": pinned_elsewhere}).step()
    if st.get("state") == "joined" or victim.records:
        problems.append(f"a reply from an office the invite did not pin is refused and writes nothing: {st}")

    # ── an approval: no secret anywhere ──────────────────────────────────────────────────────────
    asker = pair_api._MemoryPorts("claude-dev", "Claude Dev", slot=1)
    fp = fingerprint_of(vps1.home()["identity"])
    ja = joiner_of(asker, hub, {"DGO_JOIN": f"https://{LINK}", "DGO_JOIN_PIN": fp, "DGO_JOIN_DIRECTION": "both"})
    st = ja.step()
    if st.get("state") != "waiting" or not st.get("request"):
        problems.append(f"a URL alone asks, and waits: {st}")
    rows = [r for r in hub.pending() if r["office"] == "claude-dev"]
    if len(rows) != 1 or rows[0]["fingerprint"] != fingerprint_of(asker.home()["identity"]):
        problems.append(f"the host shows ONE request, with the asker's own fingerprint to compare: {rows}")
    if hub.poll(rows[0]["rid"], "not-the-secret").get("state") != "unknown":
        problems.append("a request's state is told only to whoever holds its poll secret")
    if ja.step().get("state") != "waiting" or asker.records:
        problems.append("nothing is written while the request waits")
    hub.approve("claude-dev")
    st = ja.step()
    if st.get("state") != "joined" or "vps1" not in asker.records or "claude-dev" not in vps1.records:
        problems.append(f"an approved request completes on the joiner's next pass: {st}")

    refusee = pair_api._MemoryPorts("stranger", "?", slot=1)
    jr = joiner_of(refusee, hub, {"DGO_JOIN": f"https://{LINK}"})
    jr.step()
    hub.refuse("stranger")
    if jr.step().get("state") != "refused" or refusee.records or "stranger" in vps1.records:
        problems.append("a refused request ends with nothing written, and the joiner says so")
    if jr.step().get("state") != "refused":
        problems.append("a refused office rests instead of asking again at once")

    wrong_pin = pair_api._MemoryPorts("claude-qa", "QA", slot=1)
    jw = joiner_of(wrong_pin, hub, {"DGO_JOIN": f"https://{LINK}", "DGO_JOIN_PIN": "0000-0000-0000-0000"})
    jw.step()
    hub.approve("claude-qa")
    if jw.step().get("state") == "joined" or wrong_pin.records:
        problems.append("an approval answered by an office the pin does not name writes nothing")

    # ── what the second reader found (2026-10-19), each held ────────────────────────────────────
    def posted(ports, extra=None, tamper=None):
        """An offer of `ports`, proved by its own identity unless `tamper` changes something after."""
        eng = pair_api.Pairing(ports)
        off = eng.offer(direction="both")
        body = {"v": 1, "offer": off["text"], "proof": prove_offer(ports.identity_private(), off["text"])}
        body.update(extra or {})
        if tamper:
            tamper(body)
        return eng, off, body

    # (1) a reply whose WireGuard key was swapped on the way: the joiner writes nothing
    swapper_hub = hub_of(vps1)
    swap_inv = swapper_hub.invite_create("swap-test", "both", reusable=True)
    base_http = shim(swapper_hub)

    def swapping(method, url, body=None, headers=None):
        code, doc = base_http(method, url, body, headers)
        if doc.get("reply"):
            r = pairing.parse_reply(doc["reply"])
            r["identity"] = dict(r["identity"], wg=_b64(b"P" * 32))
            doc = dict(doc, reply=pairing.reply_text(r))
        return code, doc
    target = pair_api._MemoryPorts("swap-test", "S", slot=1)
    js = Joiner(pair_api.Pairing(target), tmp / "j-swap.json", http=swapping, env={"DGO_JOIN": swap_inv["text"]})
    if js.step().get("state") == "joined" or target.records:
        problems.append("a reply whose WireGuard key was swapped on the way is refused and writes nothing")

    # (3) an offer must be proved by the identity it names: no proof, or another key's, is refused
    for why, tamper in (("no proof", lambda b: b.pop("proof")),
                        ("another key's proof", lambda b: b.update(proof=prove_offer(vps1.identity_private(), b["offer"])))):
        _eng, _off, body = posted(pair_api._MemoryPorts("prover", "P", slot=1), tamper=tamper)
        try:
            hub.join(body, "198.51.100.1")
            problems.append(f"an offer with {why} must be refused")
        except PairError as e:
            if e.status != 403:
                problems.append(f"an offer with {why}: 403, got {e.status}")

    # (4) a granted offer is answered once — its replay mints nothing
    replay_inv = hub.invite_create("replayed", "both", reusable=True)
    rinv = parse_invite(replay_inv["text"])
    _eng, _off, body = posted(pair_api._MemoryPorts("replayed", "R", slot=1),
                              extra={"invite": rinv["id"]})
    body["sig"] = sign_offer(rinv["key"], rinv["id"], body["offer"])
    hub.join(dict(body), "198.51.100.2")
    try:
        hub.join(dict(body), "198.51.100.2")
        problems.append("a granted offer replayed must be refused")
    except PairError as e:
        if e.status != 409:
            problems.append(f"a replayed offer: 409, got {e.status}")

    # (2) an invite for ANY office never replaces a record, even one a join wrote under that name
    anyone = hub.invite_create("", "both")
    again_cloud = pair_api._MemoryPorts("claude-cloud", "Claude Cloud", slot=1)
    before = vps1.records["claude-cloud"]["identity"]["ed25519"]
    if joiner_of(again_cloud, hub, {"DGO_JOIN": anyone["text"]}).step().get("state") == "joined" \
            or vps1.records["claude-cloud"]["identity"]["ed25519"] != before:
        problems.append("an invite for any office does not take a name another join holds")
    # …and a name a join once used, then paired by a person, is not taken by the join's reusable invite
    vps1.records["claude-cloud"] = dict(vps1.records["claude-cloud"], pair_id="ff" * 16,
                                        tunnel={k: v for k, v in vps1.records["claude-cloud"]["tunnel"].items()
                                                if k != "door"})
    person_paired = vps1.records["claude-cloud"]["identity"]["ed25519"]
    if joiner_of(pair_api._MemoryPorts("claude-cloud", "C", slot=1), hub, {"DGO_JOIN": minted["text"]}).step() \
            .get("state") == "joined" or vps1.records["claude-cloud"]["identity"]["ed25519"] != person_paired:
        problems.append("a record a person paired since is never replaced by a join")

    # (5) an offer that claims to live past OFFER_TTL is refused; one address holds at most a few requests
    def long_lived(b):
        o = pairing.parse_offer(b["offer"])
        o["expires_at"] = int(time.time()) + 30 * 86400
        b["offer"] = pairing.offer_text(o)
    p_long = pair_api._MemoryPorts("forever", "F", slot=1)
    _eng, _off, body = posted(p_long, tamper=long_lived)
    body["proof"] = prove_offer(p_long.identity_private(), body["offer"])
    try:
        hub.join(body, "198.51.100.3")
        problems.append("an offer that claims to live a month must be refused")
    except PairError:
        pass
    capped = 0
    for i in range(MAX_PENDING_PER_SOURCE + 2):
        _eng, _off, body = posted(pair_api._MemoryPorts(f"flood-{i}", "F", slot=1))
        try:
            hub.join(body, "203.0.113.99")
        except PairError as e:
            capped += e.status == 429
    if capped != 2:
        problems.append(f"one address holds at most {MAX_PENDING_PER_SOURCE} waiting requests ({capped} refused)")

    # (6) `again` asks again and replaces its OWN door record — once, with no loop
    again_inv = hub.invite_create("claude-again", "both", reusable=True)
    ag = pair_api._MemoryPorts("claude-again", "A", slot=1)
    jag = joiner_of(ag, hub, {"DGO_JOIN": again_inv["text"]})
    first = jag.step()
    jag.forget()
    second = jag.step()
    if first.get("state") != "joined" or second.get("state") != "joined" or jag.force \
            or jag.step().get("state") != "joined" or len(ag.records) != 1:
        problems.append(f"`again` re-joins once, replacing its own record, and then rests: {second}")

    # (8) a poll that fails for a moment does not cost the approval
    flaky = pair_api._MemoryPorts("claude-flaky", "F", slot=1)
    jf = joiner_of(flaky, hub, {"DGO_JOIN": f"https://{LINK}", "DGO_JOIN_PIN": fp})
    jf.step()
    real = jf.http
    jf.http = lambda m, u, b=None, h=None: (502, {"error": "bad gateway"}) if m == "GET" else real(m, u, b, h)
    if jf.step().get("state") != "waiting" or not jf.live:
        problems.append("a 502 while waiting keeps the request")
    jf.http = real
    hub.approve("claude-flaky")
    if jf.step().get("state") != "joined":
        problems.append("…and the approval given meanwhile completes on the next pass")

    # ── the declaration, read ────────────────────────────────────────────────────────────────────
    for bad in ({"DGO_JOIN": "http://link.example.org"}, {"DGO_JOIN": "https://"},
                {"DGO_JOIN": f"https://{LINK}", "DGO_JOIN_DIRECTION": "all"},
                {"DGO_JOIN": f"https://{LINK}", "DGO_JOIN_PIN": "not-a-pin"},
                {"DGO_JOIN": "DGOJOIN1:garbage"}):
        try:
            parse_declaration(bad)
            problems.append(f"a declaration that is not one must be refused: {bad}")
        except PairError:
            pass
    if parse_declaration({}) is not None or parse_declaration({"DGO_JOIN": " "}) is not None:
        problems.append("no DGO_JOIN is no join")
    if parse_declaration({"DGO_JOIN": LINK})["hub"] != f"https://{LINK}":
        problems.append("a bare host is read as its https address")
    if not pin_holds("", {"ed25519": pin}) or pin_holds("0000-0000-0000-0000", vps1.home()["identity"]) \
            or not pin_holds(fp.lower(), vps1.home()["identity"]) or not pin_holds(pin, vps1.home()["identity"]):
        problems.append("a pin is a fingerprint (any case) or the Ed25519 key itself")
    if link_host({"DGO_LINK_HOST": "Link.Example.org"}) != "link.example.org" or link_host({"DGO_LINK_HOST": "x"}):
        problems.append("the link host is a dotted host name, lower-cased, or nothing")

    # ── the HTTP routes, as FastAPI reads them (where the web stack exists) ─────────────────────
    # The first live POST /join answered 422: `request` was read as a QUERY field (the
    # postponed-annotation trap, `_publish_request_type`). No route may take a query field of that name.
    try:
        import fastapi  # noqa: F401
    except ImportError:
        return problems
    for router in (build_public_router(hub), build_admin_router(hub, ja)):
        for route in router.routes:
            names = [p.name for p in getattr(getattr(route, "dependant", None), "query_params", [])]
            if "request" in names:
                problems.append(f"{route.path} reads `request` as a query field — the Request is not resolved")
    return problems


if __name__ == "__main__":
    logging.basicConfig(level=logging.WARNING)
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("join_api.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
