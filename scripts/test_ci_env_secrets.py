"""test_ci_env_secrets.py — a fresh .env from scripts/ci-env.sh carries no secret of the template's (DGO-1220).

    python3 scripts/test_ci_env_secrets.py

The template (.env.ex) held real values, and ci-env.sh copied every key it did not mint itself: each office it
made shared those secrets with every other office and with whoever holds the template (measured 2026-11-03: 10
of them in each fresh .env; vps1 runs on them). Asked here, in a scratch copy of the files ci-env.sh reads (it
never writes a real .env), for the CI form and for a real office (OFFICE_DOMAIN):
  - no secret-named key keeps a template value that looks generated (hex, a JWT, a long random string);
  - no key is written twice; n8n's API key is left for n8n to issue;
  - the Supabase JWTs verify against this office's own secret, not the template's;
  - a real office's local mailbox password is its own (CI keeps its known one).
No value is ever printed: a failure names the key.
"""
import base64
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SECRET_NAME = re.compile(r"(PASS|SECRET|TOKEN|KEY|SALT|PRIVATE|CREDENTIAL|_PW$)")
PLACEHOLDER = re.compile(r"^(|your[-_].*|change.*|CHANGE.*|<.*>|x+|sk-(your|x).*|fc-(your|x).*)$", re.I)


def values(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"^([A-Z][A-Z0-9_]*)=(.*)$", line.rstrip("\n"))
            if m:
                out.setdefault(m.group(1), []).append(m.group(2).split(" #", 1)[0].strip().strip('"').strip("'"))
    return out


def generated_looking(v):
    """A value someone minted: hex of 32+, a JWT, or 24+ characters of mixed random-looking text."""
    if PLACEHOLDER.match(v):
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{32,}", v) or v.startswith("eyJ")
                or (len(v) >= 24 and re.search(r"\d", v) and re.search(r"[a-zA-Z]", v)))


def make_env(**env):
    d = tempfile.mkdtemp()
    os.makedirs(os.path.join(d, "scripts"))
    os.makedirs(os.path.join(d, "platform-base", "postgres", "hooks"))
    shutil.copy(os.path.join(REPO, "scripts", "ci-env.sh"), os.path.join(d, "scripts"))
    for f in (".env.ex", "platform.state.default.yaml"):
        shutil.copy(os.path.join(REPO, f), d)
    shutil.copy(os.path.join(REPO, "platform-base", "postgres", "hooks", "keygen.py"),
                os.path.join(d, "platform-base", "postgres", "hooks"))
    open(os.path.join(d, "bbox"), "w").close()        # keygen.py finds the root by this file
    # the case's own environment only: a CI step exports N8N_ENCRYPTION_KEY_SECRET (the blueprint's key, which
    # the template carries too) and may export the others, and each would be read by ci-env.sh as an answer
    base = {k: v for k, v in os.environ.items()
            if k not in ("N8N_ENCRYPTION_KEY_SECRET", "OFFICE_DOMAIN", "CI_EDGE_PORT", "CI_IDENTITY",
                         "CI_DEPLOYMENT_NAME", "CI_ENV_FORCE")}
    run = subprocess.run(["bash", "scripts/ci-env.sh"], cwd=d, capture_output=True, text=True, env={**base, **env})
    assert run.returncode == 0, run.stderr[-500:]
    return values(os.path.join(d, ".env")), values(os.path.join(d, ".env.ex")), run.stderr


def jwt_ok(token, secret):
    h, p, s = token.split(".")
    want = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest())
    return hmac.compare_digest(want.decode().rstrip("="), s), json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4)))


class Fresh(unittest.TestCase):
    def check(self, gen, tpl, stderr, office):
        twice = sorted(k for k, v in gen.items() if len(v) > 1)
        self.assertEqual(twice, [], "keys written twice")
        self.assertNotIn("twice", stderr)
        kept = sorted(k for k, v in gen.items()
                      if SECRET_NAME.search(k) and generated_looking(v[-1]) and v[-1] in tpl.get(k, []))
        self.assertEqual(kept, [], "secret-named keys still carrying the template's value")
        self.assertEqual(gen["N8N_API_KEY"], [""])
        secret = gen["SUPABASE_JWT_SECRET"][-1]
        self.assertNotEqual(secret, tpl["SUPABASE_JWT_SECRET"][-1])
        for k, role in (("SUPABASE_ANON_KEY", "anon"), ("SUPABASE_SERVICE_KEY", "service_role")):
            ok, claims = jwt_ok(gen[k][-1], secret)
            self.assertTrue(ok, f"{k} is not signed with this office's own secret")
            self.assertEqual(claims["role"], role)
        if office:
            self.assertNotEqual(gen["LOCALMAIL_PW"], ["indox"])
        else:
            self.assertEqual(gen["LOCALMAIL_PW"], ["indox"])

    def test_the_ci_form(self):
        self.check(*make_env(), office=False)

    def test_the_mac_engine_form(self):
        self.check(*make_env(CI_DEPLOYMENT_NAME="local", CI_EDGE_PORT="8080"), office=False)

    def test_a_real_office(self):
        self.check(*make_env(OFFICE_DOMAIN="example.test"), office=True)

    def test_two_offices_share_no_secret(self):
        a, _, _ = make_env(OFFICE_DOMAIN="a.test")
        b, _, _ = make_env(OFFICE_DOMAIN="b.test")
        shared = sorted(k for k in a if SECRET_NAME.search(k) and generated_looking(a[k][-1]) and a[k] == b.get(k))
        self.assertEqual(shared, [], "two fresh offices got the same value")


if __name__ == "__main__":
    unittest.main()
