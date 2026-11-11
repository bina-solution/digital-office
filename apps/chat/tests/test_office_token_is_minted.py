"""Every office mints its own CHAT_API_TOKEN, and chat is handed it (DGO-1792, the chat caller check's stage two).

    python3 apps/chat/tests/test_office_token_is_minted.py

Under edge trust chat believes an office service by `X-Chat-Office-Token: <CHAT_API_TOKEN>`
(src/api/middleware/edge_caller.js, the `token` caller). Nothing minted that token, so no service could prove
itself that way and enforce would have refused every one of them that is not a browser behind the edge. What
holds: scripts/env-secrets.py mints it per office (TABLE, 32 random bytes as hex — and a fresh office gets
every TABLE key, scripts/test_env_secrets.py), the template declares it empty, and chat's compose passes it.
"""
import importlib.util
import os
import pathlib
import unittest

# CHAT_TOKEN_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one)
ROOT = pathlib.Path(os.environ.get("CHAT_TOKEN_ROOT") or pathlib.Path(__file__).resolve().parents[3])


def env_secrets():
    spec = importlib.util.spec_from_file_location("env_secrets", ROOT / "scripts/env-secrets.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class OfficeTokenIsMinted(unittest.TestCase):
    # both of chat's office tokens: the one that opens every route, and the READ one (GET /api/accounts, /api/readyz)
    TOKENS = ("CHAT_API_TOKEN", "CHAT_READ_TOKEN")

    def test_env_secrets_mints_it(self):
        for name in self.TOKENS:
            kind, size = env_secrets().TABLE[name]
            self.assertEqual(kind, "hex", name)
            self.assertGreaterEqual(size, 32, name)

    def test_the_template_declares_it_empty(self):
        lines = (ROOT / ".env.ex").read_text(encoding="utf-8").splitlines()
        for name in self.TOKENS:
            self.assertIn(name + "=", lines)

    def test_chat_is_handed_it(self):
        compose = (ROOT / "apps/chat/docker-compose.yml").read_text(encoding="utf-8")
        for name in self.TOKENS:
            self.assertRegex(compose, r"(?m)^\s+- %s=\$\{%s:-\}$" % (name, name))

    def test_the_caller_check_reads_that_header_and_that_variable(self):
        js = (ROOT / "apps/chat/src/api/middleware/edge_caller.js").read_text(encoding="utf-8")
        self.assertIn("x-chat-office-token", js.lower())
        self.assertIn("CHAT_API_TOKEN", js)
        self.assertNotRegex(js, r"Nothing mints CHAT_API_TOKEN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
