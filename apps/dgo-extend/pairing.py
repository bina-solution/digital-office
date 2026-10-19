"""dgo-extend.pairing — three ways to pair two offices, ONE result (DGO-33, decision 7).

The three flows, and why they are one module
-------------------------------------------
A link needs both sides to agree on: two identities, two WireGuard keys, a slot, a direction and a
token. HOW the two sides meet is a transport question, and there are three honest answers:

  **through `computers`** — the zero-touch path. The host already holds an approved SSH key on the
  joiner's machine, so it writes the grant itself and nobody scans anything. This is the flow every
  test uses.
  **QR** — the joiner's screen shows public material, the host scans it in the office browser. For a
  machine the office has never touched (a laptop in someone's hand, a machine on another network).
  **paste** — the same offer as text, when there is no camera in the room.

They are one module because the OFFER is the same object in all three, and because the interesting
part — what an attacker who photographs the screen, replays the offer, or answers with the wrong code
can achieve — must be decided once, not three times.

What the offer contains, and what it must never contain
--------------------------------------------------------
Public material only: the joiner's office id, its Ed25519 and WireGuard PUBLIC keys, its candidate
endpoints, an ephemeral X25519 public key, a rendezvous id, and an expiry. No token, no private key,
no shared secret.

That is a real constraint, not a style choice: a QR is a photograph. It is displayed on a screen, it
ends up in camera rolls and in screenshots, and anyone who has it can read every byte of it forever.
So photographing the offer must be worth NOTHING — and it is, because the grant (which carries the
link token) is encrypted to a key the offer only names, the offer is single-use, and it expires in
ten minutes. The confirmation code that both screens display is derived from the ECDH secret, so a
photograph of the screen cannot produce it.

The confirmation code (SAS)
---------------------------
Six digits, derived by BOTH sides from the ECDH secret plus both identity keys. It is the one value
an attacker who sits between the two sides cannot compute, which is why the operator reads it out
loud and confirms it: "the code matches" is the sentence that turns a key exchange into a pairing.

Crypto, and why openssl again
-----------------------------
X25519 (keygen, derive) and Ed25519 (sign, verify) come from the `openssl` binary, exactly as in
`identity.py`: this image has no Python crypto library, and adding one would be a new supply chain for
two curves the platform already depends on. The symmetric part is built from the standard library:
HKDF-SHA256 for key separation, AES-256-CTR through `openssl enc` for confidentiality, and a separate
HMAC-SHA256 over the ciphertext (encrypt-then-MAC) so a modified grant is refused before it is
decrypted rather than after.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import tempfile
import time
from pathlib import Path

#: How long an offer stays valid. Ten minutes: long enough to walk a laptop to the host and scan,
#: short enough that a screenshot found later is worthless.
OFFER_TTL = 600
#: The offer's wire prefix, so a pasted string is recognisable and a QR payload is self-describing.
PREFIX = "DGOPAIR1:"
#: The REPLY's prefix (the host's signed, sealed grant travelling back to the joiner). A different
#: prefix on purpose: both texts are pasted into the same box, and a reply read as an offer (or the
#: reverse) must be refused by name instead of failing three fields later.
REPLY_PREFIX = "DGOPAIRR1:"
OFFICE_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")


class PairingError(RuntimeError):
    """A refusal with a sentence the operator can act on — always before any secret moves."""


# ── openssl-backed primitives (the same choice identity.py makes) ──────────────
def _run(cmd: list[str], data: bytes | None = None) -> bytes:
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise PairingError(f"openssl נכשל ({cmd[1] if len(cmd) > 1 else '?'}): {e}") from e
    return p.stdout


def x25519_keypair() -> tuple[bytes, bytes]:
    """(DER private, DER public) — the ephemeral pair of ONE offer."""
    priv = _run(["openssl", "genpkey", "-algorithm", "X25519", "-outform", "DER"])
    pub = _run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"], priv)
    return priv, pub


def x25519_public(priv_der: bytes) -> bytes:
    return _run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"], priv_der)


def x25519_derive(priv_der: bytes, peer_pub_der: bytes) -> bytes:
    """The ECDH shared secret. Both sides compute the SAME 32 bytes — that is the pairing."""
    with tempfile.TemporaryDirectory() as d:
        k, p = Path(d) / "k.pem", Path(d) / "p.pem"
        k.write_bytes(priv_der)
        p.write_bytes(peer_pub_der)
        # OpenSSL 3.0's option is `-peerform`; `-peerkeyform` is rejected as an unknown option, and
        # the failure names the option rather than the key, which is why this is written down here.
        out = _run(["openssl", "pkeyutl", "-derive", "-inkey", str(k), "-keyform", "DER",
                    "-peerkey", str(p), "-peerform", "DER"])
    if len(out) < 32:
        raise PairingError("openssl החזיר סוד משותף קצר מהצפוי")
    return out[:32]


def ed25519_sign(priv_der: bytes, message: bytes) -> bytes:
    with tempfile.TemporaryDirectory() as d:
        k, m = Path(d) / "k.pem", Path(d) / "m.bin"
        k.write_bytes(priv_der)
        m.write_bytes(message)
        # `-rawin` is what makes Ed25519 sign the MESSAGE rather than a pre-hashed digest, and it
        # insists on a real file: fed on stdin it fails with a bare non-zero exit, which is why the
        # message is written out rather than piped. `-keyform DER` is required because these keys are
        # raw DER blobs (the shape identity.py stores) — without it openssl expects PEM and refuses.
        return _run(["openssl", "pkeyutl", "-sign", "-inkey", str(k), "-keyform", "DER",
                     "-rawin", "-in", str(m)])


def ed25519_verify(pub_der: bytes, message: bytes, signature: bytes) -> bool:
    with tempfile.TemporaryDirectory() as d:
        k, m, sig = Path(d) / "k.pem", Path(d) / "m.bin", Path(d) / "sig.bin"
        k.write_bytes(pub_der)
        m.write_bytes(message)
        sig.write_bytes(signature)
        try:
            subprocess.run(["openssl", "pkeyutl", "-verify", "-pubin", "-inkey", str(k),
                            "-keyform", "DER", "-rawin", "-in", str(m), "-sigfile", str(sig)],
                           capture_output=True, check=True)
            return True
        except (OSError, subprocess.CalledProcessError):
            return False


def hkdf(ikm: bytes, salt: bytes, info: bytes, length: int = 32) -> bytes:
    """RFC 5869 with SHA-256 — the standard way to get two independent keys out of one ECDH secret."""
    prk = hmac.new(salt, ikm, hashlib.sha256).digest()
    out, block, counter = b"", b"", 1
    while len(out) < length:
        block = hmac.new(prk, block + info + bytes([counter]), hashlib.sha256).digest()
        out += block
        counter += 1
    return out[:length]


def _aes_ctr(key: bytes, iv: bytes, data: bytes) -> bytes:
    """AES-256-CTR through the openssl binary. CTR (not CBC) so the ciphertext is exactly as long as
    the plaintext — a grant has no padding to leak, and no block-alignment to explain."""
    return _run(["openssl", "enc", "-aes-256-ctr", "-K", key.hex(), "-iv", iv.hex()], data)


def seal(shared: bytes, salt: bytes, plaintext: bytes) -> dict:
    """Encrypt-then-MAC. Returns the four fields that travel; nothing here is a secret input."""
    key = hkdf(shared, salt, b"dgo-pairing-v1")
    enc_key, mac_key = key[:16] * 2, key          # 32-byte AES key = two 16-byte halves
    iv = secrets.token_bytes(16)
    ct = _aes_ctr(enc_key, iv, plaintext)
    tag = hmac.new(mac_key + b"mac", iv + ct, hashlib.sha256).digest()
    b64 = lambda b: base64.b64encode(b).decode()   # noqa: E731
    return {"iv": b64(iv), "ct": b64(ct), "tag": b64(tag), "v": 1}


def open_sealed(shared: bytes, salt: bytes, sealed: dict) -> bytes:
    """Refuse a modified grant BEFORE decrypting it: a CTR stream with no integrity check is a
    stream an attacker edits, and the edit would decrypt into something that looks like a grant."""
    key = hkdf(shared, salt, b"dgo-pairing-v1")
    enc_key, mac_key = key[:16] * 2, key
    try:
        iv = base64.b64decode(sealed["iv"]); ct = base64.b64decode(sealed["ct"])
        tag = base64.b64decode(sealed["tag"])
    except (KeyError, ValueError) as e:
        raise PairingError("ה-grant אינו קריא (שדות חסרים או פגומים)") from e
    want = hmac.new(mac_key + b"mac", iv + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(want, tag):
        raise PairingError("ה-grant שונה בדרך — החתימה אינה מתאימה, והצימוד מבוטל")
    return _aes_ctr(enc_key, iv, ct)


def sas(shared: bytes, joiner_identity: str, host_identity: str) -> str:
    """The six digits both screens show. Order-independent on purpose: the two sides may compute it
    in either order, and a code that depends on who typed first is a code that mismatches."""
    material = b"|".join(sorted([joiner_identity.encode(), host_identity.encode()]))
    digest = hashlib.sha256(shared + material).digest()
    return f"{int.from_bytes(digest[:8], 'big') % 1_000_000:06d}"


# ── the offer ─────────────────────────────────────────────────────────────────
def new_offer(office: str, identity_public: dict, endpoints: list[str], now: float | None = None,
              ttl: int = OFFER_TTL, extra: dict | None = None) -> tuple[dict, bytes]:
    """The JOINER mints an offer. Returns (offer, ephemeral_private_DER) — the private half never
    leaves this process, which is why it is returned separately from the offer dict.

    `extra` carries the PUBLIC facts the host needs to build the pair (`label`, `used_slots`, `listen`,
    `direction`); it can never overwrite one of the offer's own fields, and anything that looks like a
    secret is refused here rather than trusted to the caller."""
    if not OFFICE_RE.match(str(office or "")):
        raise PairingError(f"מזהה לשכה לא תקין: {office!r}")
    if not (identity_public or {}).get("ed25519"):
        raise PairingError("אין זהות (Ed25519) ללשכה הזאת — הרץ `bbox dgo identity`")
    priv, pub = x25519_keypair()
    now = time.time() if now is None else now
    offer = {
        "v": 1,
        "offer_id": secrets.token_hex(16),
        "office": office,
        "identity": {"ed25519": identity_public["ed25519"], "wg": identity_public.get("wg", ""),
                     "fingerprint": identity_public.get("fingerprint", "")},
        "ephemeral": base64.b64encode(pub).decode(),
        "endpoints": [e for e in (endpoints or []) if e],
        "created_at": int(now),
        "expires_at": int(now + ttl),
    }
    for key, value in (extra or {}).items():
        if key in offer:
            raise PairingError(f"השדה {key} שייך להצעה עצמה ואינו ניתן לדריסה")
        if re.search(r"token|private|secret", key, re.I):
            raise PairingError(f"הצעת צימוד נושאת חומר ציבורי בלבד — {key} אינו נכנס אליה")
        offer[key] = value
    return offer, priv


def _b64url(doc: dict) -> str:
    """base64url WITHOUT padding: the text is read aloud, typed and pasted, and a trailing `=` is the
    character people drop. The reader pads it back."""
    raw = json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64url(body: str) -> dict:
    body = re.sub(r"\s+", "", body or "")
    doc = json.loads(base64.urlsafe_b64decode((body + "=" * (-len(body) % 4)).encode()))
    if not isinstance(doc, dict):
        raise ValueError("not an object")
    return doc


def kind_of(text: str) -> str:
    """`offer`, `reply` or `` — by PREFIX, after dropping the spaces the display form adds. One
    function, because every door (camera, picture, pasted text) asks this before anything else."""
    t = re.sub(r"\s+", "", text or "")
    if t.startswith(REPLY_PREFIX):
        return "reply"
    if t.startswith(PREFIX):
        return "offer"
    return ""


def offer_text(offer: dict) -> str:
    """The offer as one line: what goes into the QR, and what gets pasted when there is no camera."""
    return PREFIX + _b64url(offer)


def parse_offer(text: str) -> dict:
    """Read an offer back. Refuses anything that is not one — a scanned QR is untrusted input.

    Whitespace anywhere is dropped first: the screen shows the text in groups so a person can carry
    it across a room, and a code typed back with different spacing is the same code."""
    t = re.sub(r"\s+", "", text or "")
    if t.startswith(REPLY_PREFIX):
        raise PairingError("זה קוד תשובה (של הלשכה המארחת), לא הצעת הצטרפות — הדביקו אותו בלשכה שהציגה את ההצעה")
    body = t[len(PREFIX):] if t.startswith(PREFIX) else t
    try:
        doc = _unb64url(body)
    except (ValueError, TypeError) as e:
        raise PairingError("הקוד שהודבק אינו הצעת צימוד (או שנחתך בדרך)") from e
    for field in ("offer_id", "office", "identity", "ephemeral", "expires_at"):
        if field not in doc:
            raise PairingError(f"בהצעת הצימוד חסר השדה {field}")
    if not OFFICE_RE.match(str(doc.get("office") or "")):
        raise PairingError(f"מזהה הלשכה שבהצעה אינו תקין: {doc.get('office')!r}")
    if not isinstance(doc.get("identity"), dict) or not doc["identity"].get("ed25519"):
        raise PairingError("בהצעת הצימוד אין זהות (Ed25519) של הלשכה המצטרפת")
    return doc


def reply_text(reply: dict) -> str:
    """The host's reply as one line — the SECOND code of a pairing, shown by the host and read by the
    joiner. Everything secret in it is inside `sealed`; the rest is the host's public identity, its
    ephemeral public key and a signature, so a photograph of this one is worth nothing either."""
    return REPLY_PREFIX + _b64url(reply)


def parse_reply(text: str) -> dict:
    t = re.sub(r"\s+", "", text or "")
    if t.startswith(PREFIX):
        raise PairingError("זו הצעת הצטרפות, לא קוד תשובה — הדביקו אותה בלשכה המארחת")
    if not t.startswith(REPLY_PREFIX):
        raise PairingError(f"זה לא קוד תשובה — הוא אמור להתחיל ב-{REPLY_PREFIX}")
    try:
        doc = _unb64url(t[len(REPLY_PREFIX):])
    except (ValueError, TypeError) as e:
        raise PairingError("קוד התשובה אינו קריא (או שנחתך בדרך)") from e
    for field in ("offer_id", "ephemeral", "identity", "sealed", "sig"):
        if field not in doc:
            raise PairingError(f"בקוד התשובה חסר השדה {field}")
    return doc


# ── keys as they are STORED (identity.py: base64 of the raw 32 bytes) → the DER openssl wants ──────
_ED25519_PRIV_DER = bytes.fromhex("302e020100300506032b657004220420")
_ED25519_PUB_DER = bytes.fromhex("302a300506032b6570032100")


def ed25519_private_der(raw_b64: str) -> bytes:
    raw = base64.b64decode(raw_b64 or "")
    if len(raw) != 32:
        raise PairingError("המפתח הפרטי של הלשכה אינו במבנה הצפוי (32 בתים)")
    return _ED25519_PRIV_DER + raw


def ed25519_public_der(raw_b64: str) -> bytes:
    try:
        raw = base64.b64decode(raw_b64 or "")
    except ValueError as e:
        raise PairingError("מפתח הזהות הציבורי אינו base64 תקין") from e
    if len(raw) != 32:
        raise PairingError("מפתח הזהות הציבורי אינו במבנה הצפוי (32 בתים)")
    return _ED25519_PUB_DER + raw


def is_expired(offer: dict, now: float | None = None) -> bool:
    return (time.time() if now is None else now) > int(offer.get("expires_at") or 0)


# ── the grant, and the handshake around it ────────────────────────────────────
def accept(offer: dict, host_office: str, host_identity_private: bytes, host_identity_public: dict,
           token: str, direction: str, tunnel: dict, now: float | None = None,
           extra: dict | None = None) -> dict:
    """The HOST side: build the grant, encrypt it to the offer's ephemeral key, sign it.

    Everything the joiner needs is inside the sealed blob and nowhere else — the token included. The
    reply's own fields (identity, ephemeral public key, signature) are the only cleartext, and none
    of them is a secret.
    """
    if is_expired(offer, now):
        raise PairingError("הצעת הצימוד פגה (10 דקות) — הצג הצעה חדשה במכונה המצטרפת")
    if direction not in ("use", "serve", "both"):
        raise PairingError("כיוון הקישור חייב להיות use, serve או both")
    if not token:
        raise PairingError("אין אסימון לקישור — הצימוד לא יעביר קישור בלי הרשאה")
    joiner_pub = base64.b64decode(offer["ephemeral"])
    host_priv, host_pub = x25519_keypair()
    shared = x25519_derive(host_priv, joiner_pub)

    # The grant repeats NEITHER identity in full: the joiner knows its own, and the host's travels in
    # the reply's cleartext. What it does carry is the host's identity KEY, inside the seal — so the
    # cleartext identity cannot be swapped for another one without the opened grant saying so. Kept
    # small on purpose: this text is a QR a laptop camera has to read off another screen.
    grant = {"v": 1, "offer_id": offer["offer_id"], "joiner": offer["office"],
             "host": host_office, "direction": direction, "token": token,
             "host_ed25519": host_identity_public.get("ed25519", ""),
             "tunnel": tunnel or {}}
    for key, value in (extra or {}).items():
        grant.setdefault(key, value)
    sealed = seal(shared, offer["offer_id"].encode(), json.dumps(grant, sort_keys=True).encode())
    signature = ed25519_sign(host_identity_private,
                             json.dumps(sealed, sort_keys=True).encode())
    return {
        "v": 1, "offer_id": offer["offer_id"],
        "ephemeral": base64.b64encode(host_pub).decode(),
        "identity": host_identity_public,
        "sealed": sealed,
        "sig": base64.b64encode(signature).decode(),
        "host_sas": sas(shared, offer["identity"]["ed25519"],
                        host_identity_public.get("ed25519", "")),
    }


def open_reply(offer: dict, ephemeral_private: bytes, reply: dict,
               now: float | None = None) -> tuple[dict, str]:
    """The JOINER reads the host's reply: (grant, six-digit code). Nothing is written by this.

    The order is the security property. The SIGNATURE is verified first, against the identity key
    the reply names — a reply whose sealed blob was not signed by that key is refused before any
    secret is derived. Then the ECDH secret opens the seal, which refuses a modified grant by its MAC.
    Then the grant must name THIS offer and the SAME identity key the cleartext showed. The code is
    computed here and only shown: comparing it with the host's screen is the operator's act, and it is
    what anchors the host's self-asserted identity (an attacker in the middle cannot produce it).
    """
    if is_expired(offer, now):
        raise PairingError("הצעת הצימוד פגה — אי אפשר להשלים צימוד ישן")
    if reply.get("offer_id") != offer["offer_id"]:
        raise PairingError("התשובה שייכת להצעה אחרת")
    host_identity = reply.get("identity") or {}
    sealed = reply.get("sealed") or {}
    try:
        signature = base64.b64decode(reply.get("sig") or "")
        host_eph = base64.b64decode(reply["ephemeral"])
    except (KeyError, ValueError) as e:
        raise PairingError("קוד התשובה פגום (חתימה או מפתח זמני אינם קריאים)") from e
    if not ed25519_verify(ed25519_public_der(host_identity.get("ed25519", "")),
                          json.dumps(sealed, sort_keys=True).encode(), signature):
        raise PairingError("החתימה על התשובה אינה של הלשכה שהציגה אותה — הצימוד בוטל")
    shared = x25519_derive(ephemeral_private, host_eph)
    code = sas(shared, offer["identity"]["ed25519"], host_identity.get("ed25519", ""))
    if reply.get("host_sas") and str(reply["host_sas"]) != code:
        raise PairingError("הלשכה המארחת הציגה קוד אחר — מישהו באמצע. הצימוד בוטל")
    grant = json.loads(open_sealed(shared, offer["offer_id"].encode(), sealed))
    if grant.get("offer_id") != offer["offer_id"]:
        raise PairingError("ה-grant שנפתח אינו של ההצעה הזאת")
    if grant.get("host_ed25519") and grant["host_ed25519"] != host_identity.get("ed25519"):
        raise PairingError("הזהות שבתשובה אינה הזהות שחתמה על ה-grant — הצימוד בוטל")
    return grant, code


def finish(offer: dict, ephemeral_private: bytes, reply: dict, code_shown: str,
           now: float | None = None) -> dict:
    """The JOINER side, completed: everything `open_reply` checks, and then the six-digit code the
    operator confirmed must be the one this side computed. A wrong code aborts, whatever else held."""
    grant, code = open_reply(offer, ephemeral_private, reply, now)
    if "".join(ch for ch in str(code_shown) if ch.isdigit()) != code:
        raise PairingError("קוד האישור אינו תואם — הצימוד בוטל")
    return grant


class Offers:
    """The joiner's live offers: single-use, expiring, and kept in memory (never on disk).

    In memory is the design decision from §9 ("Pairing offer | the remote's memory, 10 min | none"):
    an offer that survives a restart is an offer that can be redeemed after the room has emptied, and
    its whole value is that it is short-lived.
    """

    def __init__(self, now=None):
        self._live: dict[str, dict] = {}
        self._used: dict[str, float] = {}
        self._now = now or time.time

    def add(self, offer: dict, ephemeral_private: bytes) -> None:
        self._live[offer["offer_id"]] = {"offer": offer, "priv": ephemeral_private,
                                         "expires_at": offer["expires_at"]}

    def get(self, offer_id: str) -> dict:
        now = self._now()
        if offer_id in self._used:
            raise PairingError("ההצעה הזאת כבר נוצלה — הצעה היא חד-פעמית")
        row = self._live.get(offer_id)
        if not row:
            raise PairingError("אין הצעה חיה במזהה הזה (אולי היא פגה ואוחסנה מחדש)")
        if now > row["expires_at"]:
            self._live.pop(offer_id, None)
            raise PairingError("הצעת הצימוד פגה")
        return row

    def claim(self, offer_id: str, **facts) -> dict:
        """The reply arrived and opened: remember it NEXT TO the live offer. The offer stays live —
        an offer burned when the reply is read would leave nothing to confirm against (the lifecycle
        is live → claimed → confirmed, and only `use` ends it). A second, DIFFERENT reply to an offer
        that already holds one is refused: one offer pairs one host."""
        row = self.get(offer_id)
        held = row.get("claim")
        if held and held.get("reply_sig") != facts.get("reply_sig"):
            raise PairingError("ההצעה הזאת כבר קיבלה תשובה מלשכה אחרת — הציגו הצעה חדשה")
        row["claim"] = dict(facts)
        return row

    def state(self, offer_id: str) -> str:
        """waiting | claimed | confirmed | expired | unknown — what the screen polls."""
        if offer_id in self._used:
            return "confirmed"
        row = self._live.get(offer_id)
        if not row:
            return "unknown"
        if self._now() > row["expires_at"]:
            return "expired"
        return "claimed" if row.get("claim") else "waiting"

    def cancel(self, offer_id: str) -> None:
        self._live.pop(offer_id, None)

    def use(self, offer_id: str) -> None:
        """Mark it redeemed. Called ONLY after the code matched and the grant opened: an offer burned
        by a failed attempt would leave the operator with a dead screen and no explanation."""
        self._live.pop(offer_id, None)
        self._used[offer_id] = self._now()

    def gc(self) -> int:
        now = self._now()
        gone = [k for k, v in self._live.items() if now > v["expires_at"]]
        for k in gone:
            self._live.pop(k, None)
        self._used = {k: t for k, t in self._used.items() if now - t < 3600}
        return len(gone)

    def prune_used(self, keep_unique: bool = True) -> int:
        """What "photographed QR redeems nothing" is made of: the used list is what refuses the
        second attempt, and it is kept for an hour so a replayed offer is refused rather than
        reported as "unknown offer" (which reads like a bug, not like a refusal)."""
        return len(self._used) if keep_unique else 0


def selftest() -> list[str]:
    """The three acceptances of decision 7, without a network: a photographed offer redeems nothing,
    a wrong code aborts, an offer expires."""
    problems = []
    joiner_identity = {"ed25519": base64.b64encode(b"J" * 32).decode(), "wg": "W", "fingerprint": "AAAA-BBBB"}
    host_signing_priv, host_signing_pub = _ed25519_keypair()
    host_identity = {"ed25519": base64.b64encode(host_signing_pub[-32:]).decode(), "wg": "W2",
                     "fingerprint": "CCCC-DDDD"}

    offer, eph_priv = new_offer("portable", joiner_identity, ["192.168.16.103:51820"])
    text = offer_text(offer)
    if parse_offer(text)["offer_id"] != offer["offer_id"]:
        problems.append("an offer must survive its own text encoding (that IS the QR payload)")

    # the token must not be in the offer — a photograph of the screen is worth nothing
    if "token" in json.dumps(offer) or "private" in json.dumps(offer):
        problems.append("the offer carries a secret — a photographed QR would redeem a link")

    reply = accept(offer, "macbook", host_signing_priv, host_identity, token="t0ken",
                   direction="serve", tunnel={"slot": 3, "endpoint": "10.79.3.2"})
    if reply["host_sas"] != sas(x25519_derive(eph_priv, base64.b64decode(reply["ephemeral"])),
                                joiner_identity["ed25519"], host_identity["ed25519"]):
        problems.append("the host's displayed code must be the ECDH code the joiner computes")
    grant = finish(offer, eph_priv, reply, reply["host_sas"])
    if grant.get("token") != "t0ken" or grant.get("direction") != "serve":
        problems.append(f"the sealed grant must carry token and direction: {grant}")

    # a photographed offer, replayed by a third party, cannot open the grant: it does not have the
    # ephemeral PRIVATE key. Nor can it produce the code.
    other_priv, _ = x25519_keypair()
    try:
        finish(offer, other_priv, reply, reply["host_sas"])
        problems.append("a stranger holding the photographed QR could open the grant")
    except PairingError:
        pass

    wrong = "000000" if reply["host_sas"] != "000000" else "111111"
    try:
        finish(offer, eph_priv, reply, wrong)
        problems.append("a wrong confirmation code must abort the pairing")
    except PairingError:
        pass

    tampered = json.loads(json.dumps(reply))
    tampered["sealed"]["ct"] = base64.b64encode(b"\x00" * 16).decode()
    try:
        finish(offer, eph_priv, tampered, reply["host_sas"])
        problems.append("a modified grant must be refused by its MAC, before decryption")
    except PairingError:
        pass

    expired, epriv = new_offer("portable", joiner_identity, [], now=time.time() - 3600)
    try:
        accept(expired, "macbook", host_signing_priv, host_identity, token="t", direction="use",
               tunnel={})
        problems.append("an expired offer must not be acceptable")
    except PairingError:
        pass
    try:
        finish(expired, epriv, reply, reply["host_sas"])
        problems.append("an expired offer must not be finishable")
    except PairingError:
        pass

    store = Offers()
    store.add(offer, eph_priv)
    store.get(offer["offer_id"])
    store.use(offer["offer_id"])
    try:
        store.get(offer["offer_id"])
        problems.append("an offer is single-use: a second redemption must be refused")
    except PairingError:
        pass

    # the second code of a pairing: the reply travels as text too, under its own prefix
    rtext = reply_text(reply)
    if not rtext.startswith(REPLY_PREFIX) or parse_reply(rtext) != reply:
        problems.append("a reply must survive its own text encoding (that IS the second QR)")
    grouped = " ".join(rtext[i:i + 40] for i in range(0, len(rtext), 40))
    spaced = " " + text[:30] + "\n" + text[30:]
    if parse_reply(grouped) != reply or parse_offer(spaced)["offer_id"] != offer["offer_id"]:
        problems.append("a code typed back with different spacing is the same code")
    for wrong, reader in ((rtext, parse_offer), (text, parse_reply)):
        try:
            reader(wrong)
            problems.append("an offer and a reply must not be readable as each other")
        except PairingError:
            pass
    if kind_of(text) != "offer" or kind_of(grouped) != "reply" or kind_of("hello") != "":
        problems.append("kind_of must tell the two codes apart by prefix")
    # a reply signed by ANOTHER key than the identity it names is refused before anything is derived
    forged = json.loads(json.dumps(reply))
    forged["identity"] = dict(forged["identity"], ed25519=base64.b64encode(b"X" * 32).decode())
    try:
        open_reply(offer, eph_priv, forged)
        problems.append("a reply whose signature is not by the named identity must be refused")
    except PairingError:
        pass
    # stored keys are raw; openssl wants DER — the wrap must agree with what openssl itself emits
    if ed25519_private_der(base64.b64encode(host_signing_priv[-32:]).decode()) != host_signing_priv:
        problems.append("the raw-to-DER wrap of an Ed25519 private key must match openssl's own DER")
    if ed25519_public_der(host_identity["ed25519"]) != host_signing_pub:
        problems.append("the raw-to-DER wrap of an Ed25519 public key must match openssl's own DER")
    # the lifecycle: a claimed offer is still live, a second host is refused, only `use` ends it
    life = Offers()
    o2, p2 = new_offer("portable", joiner_identity, ["192.168.16.103:51820"],
                       extra={"used_slots": [1], "label": "נייד"})
    life.add(o2, p2)
    if life.state(o2["offer_id"]) != "waiting":
        problems.append("a fresh offer waits")
    life.claim(o2["offer_id"], reply_sig="a", code="123456")
    if life.state(o2["offer_id"]) != "claimed" or not life.get(o2["offer_id"]).get("claim"):
        problems.append("a claimed offer stays live until it is confirmed")
    try:
        life.claim(o2["offer_id"], reply_sig="b", code="654321")
        problems.append("one offer pairs one host: a second reply must be refused")
    except PairingError:
        pass
    life.use(o2["offer_id"])
    if life.state(o2["offer_id"]) != "confirmed":
        problems.append("a used offer reads as confirmed, not as unknown")
    try:
        new_offer("portable", joiner_identity, [], extra={"token": "x"})
        problems.append("an offer must refuse anything that looks like a secret")
    except PairingError:
        pass

    sig = ed25519_sign(host_signing_priv, b"hello")
    if not ed25519_verify(host_signing_pub, b"hello", sig):
        problems.append("a signature must verify against its own public key")
    if ed25519_verify(host_signing_pub, b"hello!", sig):
        problems.append("a signature must not verify another message")
    return problems


def _ed25519_keypair() -> tuple[bytes, bytes]:
    priv = _run(["openssl", "genpkey", "-algorithm", "ED25519", "-outform", "DER"])
    pub = _run(["openssl", "pkey", "-inform", "DER", "-pubout", "-outform", "DER"], priv)
    return priv, pub


if __name__ == "__main__":
    bad = selftest()
    for b in bad:
        print("FAIL", b)
    print("pairing.py selftest:", "PASS" if not bad else f"{len(bad)} problem(s)")
    raise SystemExit(1 if bad else 0)
