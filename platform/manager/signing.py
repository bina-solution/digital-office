#!/usr/bin/env python3
"""signing — detached Ed25519 signatures for the catalog index. STDLIB ONLY.

WHY NOT HMAC. The obvious stdlib answer is `hmac.new(key, blob, sha256)`. It is rejected here for
one reason: an HMAC key that can VERIFY can also FORGE. Anyone the platform hands a verification
key to can mint an index that verifies. That gives integrity against corruption and nothing at all
against a hostile publisher, which is the entire threat model of an app store.

Ed25519 splits those powers: the SECRET key signs, the PUBLIC key only verifies. Publishing the
public key next to the index is safe by construction, so a stranger can host a catalog and the
platform can check that the bytes it downloaded came from the holder of that secret key.

The implementation is RFC 8032 §5.1 in pure Python (the reference implementation from the RFC's own
appendix, expressed in extended homogeneous coordinates). No `cryptography`, no `pynacl`, no
`libsodium` — this must run in the app-management container, in Git-Bash on Windows and in a bare
CI image without a wheel build. `selftest()` checks the RFC 8032 §7.1 test vectors; the CLI runs it
under `bbox catalog selftest` and the install path refuses to verify anything if it fails.

WHAT A SIGNATURE HERE DOES AND DOES NOT PROVE — read this before trusting it.

  It PROVES: these index bytes were produced by whoever holds the secret key matching the public
  key stored under `key_id` in this deployment's keyring, and have not been altered since. Combined
  with the index's per-entry sha256 it extends to every artifact the index names.

  It DOES NOT PROVE: that the key belongs to anyone in particular. There is no CA, no web of trust
  and no revocation. `key_id` is `sha256(public_key)[:16]`, so the id is self-certifying — it binds
  to the key, not to a person. Trust enters the system exactly once, when an operator runs
  `bbox catalog trust <key-id> <public-key>` and thereby says "I accept this key". Everything after
  that is mechanical. If the operator pins a key they got from the same place as the index, they
  have proved integrity, not provenance. If they got it out of band, they have proved provenance
  relative to that channel.

  It also does not prove the app is SAFE. A signature says who, never what. That is what the
  pre-install disclosure is for.
"""
import hashlib
import json
import os
import pathlib
import time

# ── RFC 8032 Ed25519 (reference implementation, pure Python) ──────────────────
P = 2 ** 255 - 19
L = 2 ** 252 + 27742317777372353535851937790883648493


def _inv(x):
    return pow(x, P - 2, P)


D = -121665 * _inv(121666) % P
SQRT_M1 = pow(2, (P - 1) // 4, P)


def _recover_x(y, sign):
    if y >= P:
        return None
    x2 = (y * y - 1) * _inv(D * y * y + 1) % P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_M1 % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


_G_Y = 4 * _inv(5) % P
_G_X = _recover_x(_G_Y, 0)
G = (_G_X, _G_Y, 1, _G_X * _G_Y % P)
ZERO = (0, 1, 1, 0)


def _add(Pt, Q):
    """Extended homogeneous coordinates (x, y, z, t); t = xy/z."""
    A = (Pt[1] - Pt[0]) * (Q[1] - Q[0]) % P
    B = (Pt[1] + Pt[0]) * (Q[1] + Q[0]) % P
    C = 2 * Pt[3] * Q[3] * D % P
    E = 2 * Pt[2] * Q[2] % P
    f, g, h, i = B - A, E - C, E + C, B + A
    return (f * g % P, h * i % P, g * h % P, f * i % P)


def _mul(s, Pt):
    Q = ZERO
    while s > 0:
        if s & 1:
            Q = _add(Q, Pt)
        Pt = _add(Pt, Pt)
        s >>= 1
    return Q


def _eq(Pt, Q):
    return (Pt[0] * Q[2] - Q[0] * Pt[2]) % P == 0 and (Pt[1] * Q[2] - Q[1] * Pt[2]) % P == 0


def _sha512_int(b):
    return int.from_bytes(hashlib.sha512(b).digest(), "little")


def _compress(Pt):
    zi = _inv(Pt[2])
    x, y = Pt[0] * zi % P, Pt[1] * zi % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _decompress(b):
    if len(b) != 32:
        return None
    y = int.from_bytes(b, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = _recover_x(y, sign)
    return None if x is None else (x, y, 1, x * y % P)


def _expand(secret):
    h = hashlib.sha512(secret).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8          # clamp: clear low 3 bits, clear bit 255, set bit 254
    a |= 1 << 254
    return a, h[32:]


def public_key(secret):
    """32-byte seed -> 32-byte public key."""
    a, _ = _expand(secret)
    return _compress(_mul(a, G))


def sign(secret, msg):
    """Detached 64-byte Ed25519 signature over `msg`."""
    a, prefix = _expand(secret)
    A = _compress(_mul(a, G))
    r = _sha512_int(prefix + msg) % L
    R = _compress(_mul(r, G))
    k = _sha512_int(R + A + msg) % L
    return R + int.to_bytes((r + k * a) % L, 32, "little")


def verify(pub, msg, sig):
    """True only if `sig` is a valid Ed25519 signature of `msg` under `pub`."""
    if len(sig) != 64 or len(pub) != 32:
        return False
    A = _decompress(pub)
    if A is None:
        return False
    R = _decompress(sig[:32])
    if R is None:
        return False
    s = int.from_bytes(sig[32:], "little")
    if s >= L:
        return False
    k = _sha512_int(sig[:32] + pub + msg) % L
    return _eq(_mul(s, G), _add(R, _mul(k, A)))


# RFC 8032 §7.1 — if these do not pass, nothing here may be trusted.
_VECTORS = [
    ("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60",
     "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a", "",
     "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bacc61e397"
     "01cf9b46bd25bf5f0595bbe24655141438e7a100b"),
    ("4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb",
     "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c", "72",
     "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e458f3613"
     "d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"),
    ("c5aa8df43f9f837bedb7442f31dcb7b166d38535076f094b85ce3a2e0b4458f7",
     "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025", "af82",
     "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290ae67f760"
     "984dc6594a7c15e9716ed28dc027beceea1ec40a"),
]


def selftest():
    """Run the RFC 8032 vectors. Returns (ok, detail)."""
    for i, (sk, pk, msg, sig) in enumerate(_VECTORS, 1):
        s, m = bytes.fromhex(sk), bytes.fromhex(msg)
        got_pk = public_key(s).hex()
        if got_pk != pk:
            return False, f"vector {i}: public key {got_pk} != {pk}"
        got_sig = sign(s, m).hex()
        if got_sig != sig:
            return False, f"vector {i}: signature mismatch"
        if not verify(bytes.fromhex(pk), m, bytes.fromhex(sig)):
            return False, f"vector {i}: verify rejected a valid signature"
        if verify(bytes.fromhex(pk), m + b"\x00", bytes.fromhex(sig)):
            return False, f"vector {i}: verify ACCEPTED a tampered message"
    return True, f"{len(_VECTORS)} RFC 8032 vectors OK (sign + verify + tamper-reject)"


# ── canonical bytes ───────────────────────────────────────────────────────────
def canonical(obj):
    """The exact bytes a signature covers. Deterministic across machines and Python builds:
    sorted keys, no insignificant whitespace, UTF-8. Anything ambiguous here is a forgery gap."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def key_id(pub):
    """Self-certifying id: the first 16 hex chars of sha256(public key). It names the KEY, never a
    person — which is precisely the guarantee, and the limit, of this scheme."""
    return hashlib.sha256(pub).hexdigest()[:16]


# ── keys on disk ──────────────────────────────────────────────────────────────
REPO = pathlib.Path(__file__).resolve().parents[2]
KEYRING = REPO / "platform" / "trust" / "keyring.json"
SECRET_KEY = REPO / ".catalog-signing-key.json"      # gitignored; never leaves this machine


def load_keyring(path=None):
    p = pathlib.Path(path or KEYRING)
    if not p.exists():
        return {"format": "bina.catalog.keyring/v1", "keys": {}}
    return json.loads(p.read_text(encoding="utf-8"))


def write_lf(path, text):
    """Always LF, on every OS. Python's text mode would translate to CRLF on Windows, and the
    index signature covers the BYTES ON DISK — a line ending that depends on who built the catalog
    is a hash that depends on who built the catalog."""
    pathlib.Path(path).write_text(text, encoding="utf-8", newline="\n")


def save_keyring(kr, path=None):
    p = pathlib.Path(path or KEYRING)
    p.parent.mkdir(parents=True, exist_ok=True)
    write_lf(p, json.dumps(kr, indent=2, ensure_ascii=False) + "\n")


def trust(pub_hex, label="", path=None):
    """Pin a public key. THIS is the trust decision — the only one in the whole scheme."""
    pub = bytes.fromhex(pub_hex)
    if len(pub) != 32:
        raise ValueError("an ed25519 public key is 32 bytes (64 hex chars)")
    kid = key_id(pub)
    kr = load_keyring(path)
    kr.setdefault("keys", {})[kid] = {
        "alg": "ed25519", "public_key": pub.hex(), "label": label,
        "added": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    save_keyring(kr, path)
    return kid


def keygen(label="", secret_path=None, keyring_path=None):
    """Generate a signing key. The SECRET stays in a gitignored file; the PUBLIC half is pinned in
    the committed keyring, so a fresh clone already trusts the catalog this deployment publishes."""
    sp = pathlib.Path(secret_path or SECRET_KEY)
    seed = os.urandom(32)
    pub = public_key(seed)
    kid = key_id(pub)
    write_lf(sp, json.dumps({
        "format": "bina.catalog.secretkey/v1", "alg": "ed25519", "key_id": kid,
        "label": label, "secret_key": seed.hex(), "public_key": pub.hex(),
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }, indent=2) + "\n")
    try:
        os.chmod(sp, 0o600)          # best effort; a no-op on Windows
    except OSError:
        pass
    trust(pub.hex(), label or f"local signing key ({kid})", keyring_path)
    return kid, pub.hex()


def load_secret(secret_path=None):
    sp = pathlib.Path(secret_path or SECRET_KEY)
    if not sp.exists():
        raise FileNotFoundError(
            f"no signing key at {sp.name} — run: bbox catalog keygen")
    d = json.loads(sp.read_text(encoding="utf-8"))
    seed = bytes.fromhex(d["secret_key"])
    if public_key(seed).hex() != d["public_key"]:
        raise ValueError(f"{sp.name}: public key does not match the secret — file is corrupt")
    return d["key_id"], seed, bytes.fromhex(d["public_key"])


# ── the signed envelope (F-Droid entry.jar, minus the JAR) ────────────────────
#
# F-Droid signs a tiny `entry.json` that carries the sha256 of the big `index-v2.json`, which in
# turn carries the sha256 of every APK. One signature covers the whole chain, and a client can
# check the index it downloaded without parsing it first. Same shape here, with a detached
# Ed25519 signature instead of a JAR signature.
SIG_FORMAT = "bina.catalog.sig/v1"


def sign_envelope(index_path, secret_path=None, keyring_path=None):
    index_path = pathlib.Path(index_path)
    kid, seed, pub = load_secret(secret_path)
    body = {
        "format": SIG_FORMAT,
        "index": {"name": index_path.name,
                  "size": index_path.stat().st_size,
                  "sha256": sha256_file(index_path)},
        "signed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "key_id": kid,
        "public_key": pub.hex(),      # convenience only — NEVER used to decide trust (see verify)
        "alg": "ed25519",
    }
    body["signature"] = sign(seed, canonical(body)).hex()
    return body


def verify_envelope(env, index_bytes, keyring_path=None):
    """(ok, reason). Refuses on: bad format, unknown key, bad signature, index hash/size mismatch.

    The `public_key` field inside the envelope is deliberately IGNORED for the trust decision — an
    envelope that carries its own key and is checked against it verifies every forgery ever made.
    The key must already be in the keyring, put there by an operator."""
    if not isinstance(env, dict) or env.get("format") != SIG_FORMAT:
        return False, f"not a {SIG_FORMAT} envelope"
    if env.get("alg") != "ed25519":
        return False, f"unsupported signature algorithm '{env.get('alg')}'"
    sig = env.get("signature")
    kid = env.get("key_id")
    if not sig or not kid:
        return False, "envelope has no signature/key_id"
    keys = (load_keyring(keyring_path).get("keys") or {})
    entry = keys.get(kid)
    if not entry:
        return False, (f"key '{kid}' is not trusted by this deployment — pin it deliberately with "
                       f"`bbox catalog trust {kid} <public-key-hex>` after obtaining the key from a "
                       f"channel you trust, or refuse the index")
    pub = bytes.fromhex(entry["public_key"])
    if key_id(pub) != kid:
        return False, f"keyring entry '{kid}' does not hash to its own id — keyring is corrupt"
    body = {k: v for k, v in env.items() if k != "signature"}
    try:
        okay = verify(pub, canonical(body), bytes.fromhex(sig))
    except ValueError:
        return False, "signature is not valid hex"
    if not okay:
        return False, f"SIGNATURE DOES NOT VERIFY under trusted key '{kid}' — the index was altered"
    idx = env.get("index") or {}
    if len(index_bytes) != idx.get("size"):
        return False, (f"index size {len(index_bytes)} != signed size {idx.get('size')}")
    got = sha256_bytes(index_bytes)
    if got != idx.get("sha256"):
        return False, f"index sha256 {got[:16]}… != signed {str(idx.get('sha256'))[:16]}…"
    return True, f"signature OK (ed25519, key {kid}) and index hash matches"
