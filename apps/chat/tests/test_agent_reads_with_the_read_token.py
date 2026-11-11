"""The office agent reads chat's accounts with the READ token, and holds no token that sends (DGO-1812, DGO-1792).

    python3 apps/chat/tests/test_agent_reads_with_the_read_token.py

operatives/chat.accounts.md's two reads (GET /api/accounts, GET /api/readyz) carried no proof, so chat's caller check
(src/api/middleware/edge_caller.js) would refuse them under CHAT_CALLER_MODE=enforce. CHAT_READ_TOKEN (f74e1a7b7)
opens exactly those two. The agent's shell never sees a *TOKEN* variable — the harness scrubs those names from every
model shell call (@deepseek-ai/dsh-subprocess) — so the token reaches the curl as DSH_CHAT_READ_TOKEN, a declared
fact of the office's own shell-env contributor (apps/bina-ds/plugins/office-shell-env). What holds:
  a. bina-ds's container is handed CHAT_READ_TOKEN and NOT CHAT_API_TOKEN;
  b. the contributor forwards exactly CHAT_READ_TOKEN → DSH_CHAT_READ_TOKEN (and computers' token), never chat's
     full token, and the profile loads it;
  c. every «here» call the operative makes to chat sends `X-Chat-Office-Token: $DSH_CHAT_READ_TOKEN`, to a route the
     read token opens, with no write method; nothing in it or computers' brief reads a scrubbed *TOKEN* name.

AGENT_READ_ROOT=<a checkout> runs the same checks on another tree (the proof that they catch the old one).
"""
import os
import pathlib
import re
import unittest

ROOT = pathlib.Path(os.environ.get("AGENT_READ_ROOT") or pathlib.Path(__file__).resolve().parents[3])
OPERATIVE = ROOT / "apps/chat/operatives/chat.accounts.md"
PLUGIN = ROOT / "apps/bina-ds/plugins/office-shell-env/lib/index.js"
CALL = re.compile(r"`(curl [^`]*http://chat:3000(/[^'` ?]*)[^`]*)`")
SCRUBBED = re.compile(r"\$\{?(?!DSH_)[A-Z0-9_]*(KEY|PASSWORD|SECRET|TOKEN)[A-Z0-9_]*")   # what the harness drops


class AgentReadsWithTheReadToken(unittest.TestCase):
    def test_bina_ds_is_handed_the_read_token_and_not_the_office_token(self):
        compose = (ROOT / "apps/bina-ds/docker-compose.yml").read_text(encoding="utf-8")
        self.assertRegex(compose, r"(?m)^\s+- CHAT_READ_TOKEN=\$\{CHAT_READ_TOKEN:-\}$")
        self.assertNotIn("CHAT_API_TOKEN", compose)

    def test_the_shell_env_contributor_forwards_the_read_token_and_is_loaded(self):
        js = PLUGIN.read_text(encoding="utf-8")
        self.assertRegex(js, r"DSH_CHAT_READ_TOKEN: Object\.freeze\(\{\s*from: 'CHAT_READ_TOKEN',")
        self.assertRegex(js, r"DSH_COMPUTERS_EXEC_TOKEN: Object\.freeze\(\{\s*from: 'COMPUTERS_EXEC_TOKEN',")
        self.assertNotIn("from: 'CHAT_API_TOKEN'", js)
        patch = (ROOT / "apps/bina-ds/harness/profile/cordis.patch.yml").read_text(encoding="utf-8")
        self.assertRegex(patch, r"- id: office-shell-env\n\s+name: '@bina/dsh-office-shell-env'")
        pkg = (ROOT / "apps/bina-ds/harness/profile/package.json").read_text(encoding="utf-8")
        self.assertIn('"@bina/dsh-office-shell-env": "file:../../plugins/office-shell-env"', pkg)

    def test_every_call_to_chat_sends_the_read_token_to_a_route_it_opens(self):
        text = OPERATIVE.read_text(encoding="utf-8")
        calls = CALL.findall(text)
        self.assertEqual(len(calls), 2, calls)
        js = (ROOT / "apps/chat/src/api/middleware/edge_caller.js").read_text(encoding="utf-8")
        opens = set(re.findall(r"'(/api/[a-z]+)'", re.search(r"READ_ROUTES = new Set\(\[([^\]]*)\]\)", js).group(1)))
        for line, path in calls:
            self.assertIn('-H "X-Chat-Office-Token: $DSH_CHAT_READ_TOKEN"', line, line)
            self.assertNotRegex(line, r"-X\s+(POST|PUT|PATCH|DELETE)", line)
            self.assertIn(path, opens, line)

    def test_no_brief_reads_a_name_the_harness_scrubs(self):
        for brief in (OPERATIVE, ROOT / "apps/computers/AGENT.md"):
            self.assertEqual(SCRUBBED.findall(brief.read_text(encoding="utf-8")), [], brief.name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
