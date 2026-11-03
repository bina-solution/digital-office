"""totp — RFC 6238 one-time codes, minted INSIDE the credential plane.

A `totp` connection holds the shared secret behind «אימות דו-שלבי → אפליקציית אימות»: what a human
would scan into an authenticator app. It is stored in the vault and NOWHERE else — not in `.env`, not
in a consumer's environment, not in the browser profile. What leaves the plane is the current code
(`GET /api/totp/<id>`), which is dead `period` seconds later; the secret never does.

Pure stdlib, so this runs in the same image as app.py with nothing added:
    RFC 4226 HOTP  — HMAC(key, counter) → dynamic truncation → `digits` decimal digits
    RFC 6238 TOTP  — counter = floor(now / period); SHA1 (the default), SHA256 or SHA512

Validated on WRITE (`parse`), so a mistyped secret is refused at the connections screen rather than
discovered as a rejected code at a login. A refusal names the fault and never echoes the value.

    python3 platform-base/connections/totp_test.py        # the RFC 6238 Appendix B vectors
"""
import base64
import hashlib
import hmac
import math
import struct
import time
import urllib.parse

ALGORITHMS = {"SHA1": hashlib.sha1, "SHA256": hashlib.sha256, "SHA512": hashlib.sha512}
DEFAULT_DIGITS, DEFAULT_PERIOD, DEFAULT_ALGORITHM = 6, 30, "SHA1"
_B32 = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def _secret_bytes(secret):
    """Decode a base32 secret as humans paste it: any case, spaces or dashes between the groups, with
    or without the `=` padding authenticator exports leave off. Returns (key bytes, normalised text);
    raises ValueError naming the fault, never the value."""
    raw = "".join(str(secret or "").split()).replace("-", "").rstrip("=").upper()
    if not raw:
        raise ValueError("secret is empty")
    if set(raw) - _B32:
        raise ValueError("secret is not base32 (A–Z and 2–7 only)")
    key = base64.b32decode(raw + "=" * (-len(raw) % 8))
    if len(key) < 10:
        raise ValueError(f"secret is too short ({len(key)} bytes; an authenticator secret is at least 10)")
    return key, raw


def parse(value, digits=None, period=None, algorithm=None):
    """Normalise a pasted TOTP secret — an `otpauth://totp/...` URI or a bare base32 key, plus optional
    digits/period/algorithm overrides — into {secret, digits, period, algorithm, label}.

    Refusals name the fault and never repeat the input: 'secret is not base32', 'digits must be 6–8',
    'algorithm must be SHA1, SHA256 or SHA512', 'only otpauth://totp is supported'."""
    label = ""
    text = str(value or "").strip()
    if text.lower().startswith("otpauth://"):
        parts = urllib.parse.urlsplit(text)
        if parts.netloc.lower() != "totp":
            raise ValueError("only otpauth://totp is supported (not hotp)")
        query = dict(urllib.parse.parse_qsl(parts.query, keep_blank_values=True))
        label = urllib.parse.unquote(parts.path.lstrip("/"))
        if query.get("issuer") and ":" not in label:
            label = f"{query['issuer']}:{label}" if label else query["issuer"]
        text = query.get("secret", "")
        digits = digits if digits is not None else query.get("digits")
        period = period if period is not None else query.get("period")
        algorithm = algorithm if algorithm is not None else query.get("algorithm")
    _, secret = _secret_bytes(text)
    try:
        digits = int(digits) if digits not in (None, "") else DEFAULT_DIGITS
        period = int(period) if period not in (None, "") else DEFAULT_PERIOD
    except (TypeError, ValueError):
        raise ValueError("digits and period must be whole numbers") from None
    if not 6 <= digits <= 8:
        raise ValueError("digits must be 6–8")
    if not 1 <= period <= 300:
        raise ValueError("period must be 1–300 seconds")
    algorithm = str(algorithm or DEFAULT_ALGORITHM).upper().replace("-", "")
    if algorithm not in ALGORITHMS:
        raise ValueError("algorithm must be SHA1, SHA256 or SHA512")
    return {"secret": secret, "digits": digits, "period": period, "algorithm": algorithm, "label": label}


def uri(params):
    """The canonical stored form: ONE otpauth:// URI carrying every parameter, which any authenticator
    imports back — so a secret moved off this plane is a scan, not a riddle."""
    query = urllib.parse.urlencode({"secret": params["secret"], "digits": params["digits"],
                                    "period": params["period"], "algorithm": params["algorithm"]})
    return f"otpauth://totp/{urllib.parse.quote(params.get('label') or '')}?{query}"


def canonical(value, **overrides):
    """parse → uri: what the vault stores for a `totp` connection."""
    return uri(parse(value, **overrides))


def hotp(key, counter, digits=DEFAULT_DIGITS, algorithm=DEFAULT_ALGORITHM):
    """RFC 4226 §5.3: HMAC over the 8-byte big-endian counter, dynamic truncation on the low nibble of
    the last byte, 31 bits, modulo 10^digits, zero-padded."""
    mac = hmac.new(key, struct.pack(">Q", counter), ALGORITHMS[algorithm]).digest()
    offset = mac[-1] & 0x0F
    binary = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def code(params, at=None):
    """The code valid at unix time `at` (default: now) for parsed `params`."""
    key, _ = _secret_bytes(params["secret"])
    counter = int((time.time() if at is None else at) // params["period"])
    return hotp(key, counter, params["digits"], params["algorithm"])


def mint(params, at=None):
    """{code, next, expires_in}: the current code, the one after it (for a caller that straddles the
    boundary) and the whole seconds the current one still has. Never the secret."""
    now = time.time() if at is None else at
    period = params["period"]
    return {"code": code(params, now), "next": code(params, now + period),
            "expires_in": max(1, math.ceil(period - now % period))}
