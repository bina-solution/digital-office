#!/usr/bin/env python3
"""totp_test — the RFC 6238 Appendix B (and RFC 4226 Appendix D) vectors against totp.py, what the
parser refuses, and that a refusal never echoes the secret.

    python3 platform-base/connections/totp_test.py
"""
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import totp  # noqa: E402

# RFC 6238 Appendix B: the seed is the ASCII string "1234567890…" cut to the digest length.
SEED = b"12345678901234567890"
SEEDS = {"SHA1": SEED, "SHA256": (SEED * 2)[:32], "SHA512": (SEED * 4)[:64]}
VECTORS = [  # (unix time, SHA1, SHA256, SHA512) — 8 digits, period 30
    (59, "94287082", "46119246", "90693936"),
    (1111111109, "07081804", "68084774", "25091201"),
    (1111111111, "14050471", "67062674", "99943326"),
    (1234567890, "89005924", "91819424", "93441116"),
    (2000000000, "69279037", "90698825", "38618901"),
    (20000000000, "65353130", "77737706", "47863826"),
]
# RFC 4226 Appendix D: HOTP for counters 0–9 with the 20-byte seed, 6 digits.
HOTP = ["755224", "287082", "359152", "969429", "338314", "254676", "287922", "162583", "399871", "520489"]
KEY = "JBSWY3DPEHPK3PXP"


def _params(algorithm, digits=8):
    return {"secret": base64.b32encode(SEEDS[algorithm]).decode(), "digits": digits, "period": 30,
            "algorithm": algorithm, "label": ""}


def test_rfc6238_appendix_b_vectors():
    for at, *expected in VECTORS:
        for algorithm, want in zip(("SHA1", "SHA256", "SHA512"), expected):
            assert totp.code(_params(algorithm), at) == want, (at, algorithm)


def test_rfc4226_appendix_d_hotp_vectors():
    for counter, want in enumerate(HOTP):
        assert totp.hotp(SEED, counter) == want, counter


def test_a_uri_and_a_bare_key_parse_to_the_same_secret():
    uri = ("otpauth://totp/Facebook:owner%40example.com?secret=jbsw%20y3dp%20ehpk%203pxp"
           "&issuer=Facebook&digits=6&period=30")
    a, b = totp.parse(uri), totp.parse("jbsw y3dp-ehpk 3pxp")
    assert a["secret"] == b["secret"] == KEY
    assert a["label"] == "Facebook:owner@example.com"
    assert (a["digits"], a["period"], a["algorithm"]) == (6, 30, "SHA1")
    assert totp.parse(totp.canonical(uri)) == a                     # the canonical form round-trips


def test_overrides_and_uri_parameters_are_honoured():
    p = totp.parse(f"otpauth://totp/x?secret={KEY}&digits=8&period=60&algorithm=sha256")
    assert (p["digits"], p["period"], p["algorithm"]) == (8, 60, "SHA256")
    p = totp.parse(KEY, digits="7", algorithm="sha-512")
    assert (p["digits"], p["algorithm"]) == (7, "SHA512")


def test_what_is_refused_and_that_the_refusal_never_echoes_the_value():
    for value in ("not base32 !!", f"otpauth://hotp/x?secret={KEY}", "", "JBSWY3DP"):
        try:
            totp.parse(value)
        except ValueError as e:
            assert not value.strip() or value not in str(e), str(e)
        else:
            raise AssertionError(f"accepted {value!r}")
    for kwargs in ({"digits": 5}, {"digits": 9}, {"period": 0}, {"algorithm": "MD5"}, {"digits": "six"}):
        try:
            totp.parse(KEY, **kwargs)
        except ValueError:
            pass
        else:
            raise AssertionError(f"accepted {kwargs}")


def test_mint_returns_the_current_and_the_next_code_and_the_seconds_left():
    p = totp.parse(KEY)
    m = totp.mint(p, at=1111111109)                                   # 1111111109 % 30 == 29
    assert set(m) == {"code", "next", "expires_in"}
    assert m["code"] == totp.code(p, 1111111109) and m["next"] == totp.code(p, 1111111109 + 30)
    assert m["expires_in"] == 1
    assert totp.mint(p, at=1111111110)["expires_in"] == 30            # on the boundary: a full period
    assert KEY not in str(m)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print("  ok  ", t.__name__)
    print(f"totp: {len(tests)}/{len(tests)} ok")
