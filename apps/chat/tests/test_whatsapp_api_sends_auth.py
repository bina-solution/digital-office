"""n8n's «whatsapp api» workflow SENDS the chat credential it attaches (DGO-1792).

    python3 apps/chat/tests/test_whatsapp_api_sends_auth.py

Its nine HTTP nodes to chat attached `Chat Auth [env-managed]` (an httpBasicAuth credential holding
CHAT_AUTH_USER/CHAT_AUTH_PASS, chat's own Basic login) without `authentication: 'genericCredentialType'` — and n8n
uses a node's credential only when that parameter says so. So they sent no auth at all: with edge trust off chat
answered 401, and under edge trust chat's caller check (src/api/middleware/edge_caller.js) names them as unproved
callers. What holds: every node URL to chat in the blueprint is preceded by the two parameters that make n8n send
the attached Basic credential, and the credential is the env-managed Chat Auth.
"""
import pathlib
import re
import unittest

WF = pathlib.Path(__file__).resolve().parents[1] / "blueprint" / "n8n" / "whatsappApi01.workflow.ts"


class WhatsappApiSendsAuth(unittest.TestCase):
    def test_every_chat_url_sends_the_basic_credential(self):
        lines = WF.read_text(encoding="utf-8").splitlines()
        urls = [i for i, l in enumerate(lines) if re.search(r"url: 'http://chat:3000/", l)]
        self.assertGreaterEqual(len(urls), 9, "scan found %d chat URLs" % len(urls))
        for i in urls:
            before = " ".join(lines[max(0, i - 3):i])
            self.assertIn("authentication: 'genericCredentialType'", before, lines[i].strip())
            self.assertIn("genericAuthType: 'httpBasicAuth'", before, lines[i].strip())
            # per node, not per file: the node definition just above its parameters attaches Chat Auth
            node = " ".join(lines[max(0, i - 16):i])
            self.assertIn("httpBasicAuth: { id: 'BmKlKWiEeZAxNWyi'", node, lines[i].strip())

    def test_every_call_is_a_route_chat_serves_with_that_method(self):
        # the group-participants node sent GET and chat serves only POST: 404 whatever the auth
        text = WF.read_text(encoding="utf-8")
        calls = []
        for block in re.findall(r"(?ms)^    W\w+ = \{\n(.*?)^    \};", text):
            url = re.search(r"url: 'http://chat:3000(/[^']+)'", block)
            if url:
                m = re.search(r"method: '([A-Z]+)'", block)
                calls.append(((m.group(1) if m else "GET").lower(), url.group(1)))
        self.assertEqual(len(calls), text.count("url: 'http://chat:3000"), "a node's block escaped the scan")
        # (only /api/bot/* is read: every node of this workflow calls the legacy bot routes in src/api/api.js)
        api = (WF.parents[2] / "src" / "api" / "api.js").read_text(encoding="utf-8")
        served = set(re.findall(r"app\.(get|post|put|delete)\('(/api/bot/[^']+)'", api))
        missing = sorted(c for c in calls if c not in served)
        self.assertEqual(missing, [], "called by the workflow, not served by chat with that method")

    def test_the_attached_credential_is_chats_own_basic_login(self):
        text = WF.read_text(encoding="utf-8")
        creds = set(re.findall(r"httpBasicAuth: \{ id: '([^']+)', name: '([^']+)' \}", text))
        self.assertEqual(creds, {("BmKlKWiEeZAxNWyi", "Chat Auth [env-managed]")})
        blueprint = (WF.parents[4] / "apps" / "n8n" / "blueprint.yml").read_text(encoding="utf-8")
        self.assertRegex(blueprint, r'BmKlKWiEeZAxNWyi: \{"name":"Chat Auth \[env-managed\]","type":"httpBasicAuth",'
                                    r'"data":\{"user":"\$\{CHAT_AUTH_USER\}","password":"\$\{CHAT_AUTH_PASS\}"\}\}')


if __name__ == "__main__":
    unittest.main(verbosity=2)
