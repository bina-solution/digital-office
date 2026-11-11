#!/usr/bin/env python3
"""test_runner_token — newsflow presents browser42's task-runner token, read from the office vault (DGO-1152).

    python3 apps/newsflow/test_runner_token.py      (G72 runs it; standard library only)

A fake vault (GET /api/agent-token/browser42-task-runner) and a fake runner (POST /v1/task) on local ports: the
token reaches the runner as a Bearer, the vault is asked once and again after a 401, and a vault that hands
nothing over leaves the call without a token (the runner then answers as its BROWSER42_TASK_AUTH says).
"""
import http.server
import importlib.util
import json
import os
import threading
import unittest
import urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("newsflow_main_token", os.path.join(HERE, "main.py"))
nf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(nf)


class Fake(http.server.ThreadingHTTPServer):
    def __init__(self):
        self.vault_tokens = ["tok-1"]        # what the vault hands over, one per ask (the last repeats)
        self.vault_asks = []                 # the X-Conn-Container of each ask
        self.runner_wants = "tok-1"          # the token the runner accepts; None = it serves anyone
        self.runner_seen = []                # the Authorization of each call
        super().__init__(("127.0.0.1", 0), Handler)


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def answer(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        s = self.server
        if self.path == "/api/agent-token/browser42-task-runner":
            s.vault_asks.append(self.headers.get("X-Conn-Container"))
            tok = s.vault_tokens[min(len(s.vault_asks), len(s.vault_tokens)) - 1]
            return self.answer(200, {"service": "browser42-task-runner", "token": tok}) if tok else \
                self.answer(403, {"error": "only this office's dgo-extend …", "decision": "refuse"})
        self.answer(404, {})

    def do_POST(self):
        s = self.server
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        auth = self.headers.get("Authorization")
        s.runner_seen.append(auth)
        if s.runner_wants is not None and auth != f"Bearer {s.runner_wants}":
            return self.answer(401, {"ok": False, "error": {"code": "unauthorized"}})
        self.answer(200, {"ok": True, "argv": "x"})


class RunnerToken(unittest.TestCase):
    def setUp(self):
        self.srv = Fake()
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        self.saved = nf.VAULT, nf.BROWSER
        nf.VAULT, nf.BROWSER = url, url
        nf._RUNNER_TOKEN.update(value="", missed_at=0.0)

    def tearDown(self):
        nf.VAULT, nf.BROWSER = self.saved
        self.srv.shutdown()

    def test_the_token_reaches_the_runner_and_the_vault_is_asked_once(self):
        self.assertEqual(nf.b42("list", timeout=5), {"ok": True, "argv": "x"})
        self.assertEqual(nf.b42("list", timeout=5)["ok"], True)
        self.assertEqual(self.srv.runner_seen, ["Bearer tok-1", "Bearer tok-1"])
        self.assertEqual(len(self.srv.vault_asks), 1)                      # kept in memory
        self.assertIsNotNone(self.srv.vault_asks[0])                       # the second factor is sent (maybe "")

    def test_a_401_asks_the_vault_again_once(self):
        self.srv.vault_tokens = ["old", "tok-1"]
        self.assertEqual(nf.b42("list", timeout=5)["ok"], True)
        self.assertEqual(self.srv.runner_seen, ["Bearer old", "Bearer tok-1"])
        self.assertEqual(len(self.srv.vault_asks), 2)

    def test_a_401_after_the_second_ask_stands(self):
        self.srv.vault_tokens = ["old"]
        with self.assertRaises(urllib.error.HTTPError) as e:
            nf.b42("list", timeout=5)
        self.assertEqual(e.exception.code, 401)
        self.assertEqual(len(self.srv.runner_seen), 2)

    def test_a_vault_that_hands_nothing_over_leaves_the_call_without_a_token(self):
        self.srv.vault_tokens = [""]
        self.srv.runner_wants = None                                       # a runner that still warns
        self.assertEqual(nf.b42("list", timeout=5)["ok"], True)
        self.assertEqual(self.srv.runner_seen, [None])
        nf.b42("list", timeout=5)                                          # within a minute: not asked again
        self.assertEqual(len(self.srv.vault_asks), 1)
        nf._RUNNER_TOKEN["missed_at"] -= nf.TOKEN_MISS_S                   # a minute later: asked again
        nf.b42("list", timeout=5)
        self.assertEqual(len(self.srv.vault_asks), 2)


if __name__ == "__main__":
    unittest.main()
