#!/usr/bin/env python3
"""Is this .env internally consistent with the artifacts committed alongside it?

Most variables only have to be *set*. A few have to AGREE with something else, and when they stop
agreeing nothing says so — the stack comes up healthy and then fails much later, in a way that
looks like a dozen unrelated problems.

Both checks here are from incidents on this repo:

  N8N_ENCRYPTION_KEY vs the blueprint fingerprint
      The committed credential blobs are AES-encrypted under one key. Push with a different one and
      n8n throws `bad decrypt` on the first credential update, which takes the whole push down —
      workflows included. What the operator sees is four red n8n checks, the indox suites red
      behind them, and no ui-map, an hour into a baseline. The key had been silently rotated by a
      generator; nothing compared it to the blueprint it has to match.

  SUPABASE_ANON_KEY / SUPABASE_SERVICE_KEY vs SUPABASE_JWT_SECRET
      Those two are JWTs SIGNED by the secret. Regenerate the secret without reminting them and
      storage answers `Invalid Compact JWS` to every request. That is what took out all six indox
      document/sync suites once.

Exit 1 on any mismatch. Reports every problem rather than the first — this runs at preflight
precisely so nobody discovers the second one an hour later.
"""
import base64
import hashlib
import hmac
import json
import pathlib
import re
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]


def load_env(path):
    out = {}
    if not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#") and "=" in ln:
            k, v = ln.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def fingerprint(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def check_n8n_key(env, problems):
    bp = REPO / "apps/n8n/blueprint.yml"
    if not bp.exists():
        return
    m = re.search(r'^encryption_key_fingerprint:\s*"?([0-9a-f]+)"?',
                  bp.read_text(encoding="utf-8"), re.M)
    if not m:
        return                              # blueprint predates the fingerprint; nothing to compare
    want = m.group(1)
    key = env.get("N8N_ENCRYPTION_KEY", "")
    if not key:
        problems.append("N8N_ENCRYPTION_KEY is unset, but the blueprint carries encrypted "
                        "credentials that need it.")
        return
    have = fingerprint(key)
    if have == want:
        return

    # Only a FIXABLE drift is a failure. If `.env.ex` carries the key the blueprint was captured
    # against and `.env` does not, someone's .env was rotated away from the canonical one and a
    # copy puts it right — that is the case worth stopping for, and it is the one that cost a
    # baseline. If .env.ex does not match either, this is a freshly generated environment (CI mints
    # throwaway secrets with ci-env.sh); the credentials will simply be created under this key
    # instead of decrypted, which works. Saying "FAIL" there would block a legitimate setup.
    ex = load_env(REPO / ".env.ex")
    ex_key = ex.get("N8N_ENCRYPTION_KEY", "")
    if ex_key and fingerprint(ex_key) == want:
        problems.append(
            f"N8N_ENCRYPTION_KEY does not match the blueprint, and .env.ex has the one that does.\n"
            f"      blueprint expects fingerprint : {want}\n"
            f"      .env currently has            : {have}\n"
            f"      The committed credentials are encrypted under the blueprint's key, so once this\n"
            f"      instance holds any, `bbox n8n push` fails on the first credential update and\n"
            f"      nothing after it runs — workflows included.\n"
            f"      Fix: copy N8N_ENCRYPTION_KEY from .env.ex into .env, then\n"
            f"           ./bbox reset --force && ./bbox run\n"
            f"      (or, if the rotation was deliberate, re-capture with ./bbox n8n pull)")
    else:
        print(f"env-consistency NOTE: N8N_ENCRYPTION_KEY ({have}) differs from the blueprint "
              f"({want}), and .env.ex does not carry the blueprint's key either — this looks like a "
              f"generated environment. Credentials will be created under this key rather than "
              f"decrypted; committed OAuth secrets will need re-authorising.")


def check_supabase_jwts(env, problems):
    secret = env.get("SUPABASE_JWT_SECRET", "")
    if not secret:
        return
    for name, want_role in (("SUPABASE_ANON_KEY", "anon"),
                            ("SUPABASE_SERVICE_KEY", "service_role")):
        tok = env.get(name, "")
        if not tok:
            continue
        parts = tok.split(".")
        if len(parts) != 3:
            problems.append(f"{name} is not a JWT.")
            continue
        head, payload, sig = parts
        expect = base64.urlsafe_b64encode(
            hmac.new(secret.encode(), f"{head}.{payload}".encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if expect != sig:
            problems.append(
                f"{name} is not signed by SUPABASE_JWT_SECRET.\n"
                f"      Storage will answer `Invalid Compact JWS` to every request and every indox\n"
                f"      document/sync suite will go red. Re-mint both keys from the current secret,\n"
                f"      or restore the secret they were minted against.")
            continue
        try:
            body = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        except Exception:
            continue
        if body.get("role") != want_role:
            problems.append(f"{name} carries role '{body.get('role')}', expected '{want_role}'.")


def main():
    env_path = REPO / ".env"
    if not env_path.exists():
        print("env-consistency: no .env — nothing to check.")
        return 0
    env = load_env(env_path)
    problems = []
    check_n8n_key(env, problems)
    check_supabase_jwts(env, problems)

    if problems:
        print("ENV CONSISTENCY — values that must agree, and do not")
        print("-" * 74)
        for p in problems:
            print(f"  ✗ {p}")
        print("-" * 74)
        print(f"\nFAIL — {len(problems)} inconsistenc(y/ies). These do not surface as startup errors;\n"
              f"they surface as unrelated-looking test failures much later.")
        return 1

    print("env-consistency OK — n8n key matches the blueprint; supabase JWTs match their secret.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
