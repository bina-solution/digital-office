"""The LLM router over real HTTP (DGO-1893): the real server in-process, a mock provider behind it (OpenAI's shape
for DeepSeek/OpenAI, Anthropic's for Claude; streamed and not). What a client office's agent sees, and what its
wallet pays.

    python3 -m unittest apps/dgo-cloud/tests/test_router_http.py
"""
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
SEEN = []


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        SEEN.append((self.path, dict(self.headers), body))
        stream = body.get("stream")
        if self.path.endswith("/messages"):
            if not stream:
                return self._json({"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                   "content": [{"type": "text", "text": "שלום"}], "stop_reason": "end_turn",
                                   "usage": {"input_tokens": 1000, "output_tokens": 100,
                                             "cache_read_input_tokens": 500}})
            ev = [{"type": "message_start", "message": {"id": "msg_2", "usage": {"input_tokens": 1000,
                                                                                 "output_tokens": 1}}},
                  {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "של"}},
                  {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ום"}},
                  {"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "tu1",
                                                                                "name": "lookup", "input": {}}},
                  {"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta",
                                                                        "partial_json": "{\"q\":1}"}},
                  {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 200}},
                  {"type": "message_stop"}]
            return self._sse([f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in ev])
        if not stream:
            return self._json({"id": "c1", "object": "chat.completion", "choices": [
                {"index": 0, "message": {"role": "assistant", "content": "hi"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 2000, "completion_tokens": 300, "prompt_cache_hit_tokens": 1000}})
        assert body.get("stream_options", {}).get("include_usage") is True
        chunks = [{"choices": [{"index": 0, "delta": {"content": "h"}}]},
                  {"choices": [{"index": 0, "delta": {"content": "i"}, "finish_reason": "stop"}]},
                  {"choices": [], "usage": {"prompt_tokens": 50, "completion_tokens": 7}}]
        slow = 0.4 if body.get("model") == "gpt-5-nano" else 0      # long enough for a client to hang up mid-way
        return self._sse([f"data: {json.dumps(c)}\n\n" for c in chunks] + ["data: [DONE]\n\n"], slow)

    def _json(self, d):
        b = json.dumps(d).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _sse(self, parts, slow=0):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        for p in parts:
            self.wfile.write(p.encode())
            self.wfile.flush()
            time.sleep(slow)


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class TestRouterHTTP(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.up, up_url = serve(Upstream)
        os.environ.update({"DGOCLOUD_DATA": tempfile.mkdtemp(), "CARDCOM_SIMULATE": "1", "DGOCLOUD_PROVIDER": "off",
                           "DGOCLOUD_SMTP_HOST": "off", "ROUTER_DEEPSEEK_URL": up_url, "ROUTER_OPENAI_URL": up_url,
                           "ROUTER_ANTHROPIC_URL": up_url, "ROUTER_DEEPSEEK_KEY": "sk-up-deepseek",
                           "ROUTER_OPENAI_KEY": "sk-up-openai", "ROUTER_ANTHROPIC_KEY": "sk-up-anthropic"})
        import server
        cls.srv = server
        cls.front, cls.url = serve(server.H)
        a = server.accounts.signup("router@example.test", "בדיקה", "olive-grove-99", "9.9.9.9")
        r = server.billing.checkout(a, "basic")
        lp = server.store.one("SELECT lp_id FROM payments WHERE id=?", r["payment"])["lp_id"]
        server.cardcom.sim_pay(lp, True)
        server.billing.verify(r["payment"])
        cls.aid = a["id"]
        cls.key = "dk_" + "k" * 40
        server.store.run("INSERT INTO keys(prefix,hash,account_id,created_at) VALUES (?,?,?,?)", cls.key[:10],
                         server.sha(cls.key), a["id"], "t")

    def call(self, path, body, host="dgo-llm.example.test", key=None, header="Authorization"):
        h = {"Content-Type": "application/json", "Host": host}
        h[header] = ("Bearer " if header == "Authorization" else "") + (key or self.key)
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode(), method="POST", headers=h)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()

    def usage(self):
        return self.srv.store.one("SELECT * FROM usage ORDER BY id DESC LIMIT 1")

    def test_1_deepseek_plain_on_its_own_path(self):
        st, body = self.call("/chat/completions", {"model": "deepseek-chat", "messages": [{"role": "user",
                                                                                          "content": "hi"}]})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["choices"][0]["message"]["content"], "hi")
        path, headers, _ = SEEN[-1]
        self.assertEqual(path, "/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer sk-up-deepseek")      # the client's key never goes up
        u = self.usage()
        self.assertEqual((u["in_tokens"], u["out_tokens"], u["cached_tokens"]), (2000, 300, 1000))
        # 1000 × 0.28 + 1000 × 0.028 + 300 × 0.42 = $0.000434 → × 3.75 × 1.1 = ₪0.00179 → 1 agora (rounded up)
        self.assertEqual(u["cost"], 1)

    def test_2_openai_stream_through_the_front_path(self):
        st, body = self.call("/llm/v1/chat/completions", {"model": "gpt-5-mini", "stream": True,
                                                          "messages": [{"role": "user", "content": "hi"}]},
                             host="dgo-cloud.example.test")
        self.assertEqual(st, 200)
        self.assertIn('"content": "h"', body)
        self.assertTrue(body.rstrip().endswith("data: [DONE]"))
        self.assertEqual(SEEN[-1][0], "/v1/chat/completions")
        u = self.usage()
        self.assertEqual((u["model"], u["in_tokens"], u["out_tokens"]), ("gpt-5-mini", 50, 7))

    def test_3_claude_through_openai_format_streamed(self):
        st, body = self.call("/v1/chat/completions", {
            "model": "claude-sonnet-5-5", "stream": True, "stream_options": {"include_usage": True},
            "messages": [{"role": "system", "content": "קצר"}, {"role": "user", "content": "hi"}]})
        self.assertEqual(st, 200)
        sent = SEEN[-1][2]
        self.assertEqual((SEEN[-1][0], sent["system"]), ("/v1/messages", "קצר"))
        self.assertEqual(SEEN[-1][1]["X-Api-Key"], "sk-up-anthropic")
        chunks = [json.loads(l[6:]) for l in body.splitlines() if l.startswith("data: {")]
        text = "".join((c["choices"][0]["delta"].get("content") or "") for c in chunks if c.get("choices"))
        self.assertEqual(text, "שלום")
        calls = [c["choices"][0]["delta"]["tool_calls"][0] for c in chunks
                 if c.get("choices") and c["choices"][0]["delta"].get("tool_calls")]
        self.assertEqual(calls[0]["function"]["name"], "lookup")
        self.assertEqual("".join(c["function"].get("arguments", "") for c in calls), "{\"q\":1}")
        self.assertEqual([c["choices"][0]["finish_reason"] for c in chunks if c.get("choices") and
                          c["choices"][0]["finish_reason"]], ["tool_calls"])
        self.assertEqual(chunks[-1]["usage"]["completion_tokens"], 200)
        u = self.usage()
        self.assertEqual((u["in_tokens"], u["out_tokens"]), (1000, 200))
        # 1000 × $2 + 200 × $10 = $0.004 → ₪0.0165 → 2 agorot
        self.assertEqual(u["cost"], 2)

    def test_4_claude_native_messages_with_x_api_key(self):
        st, body = self.call("/v1/messages", {"model": "claude-opus-5-5", "max_tokens": 50,
                                              "messages": [{"role": "user", "content": "hi"}]},
                             header="x-api-key")
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(body)["content"][0]["text"], "שלום")
        u = self.usage()
        self.assertEqual((u["in_tokens"], u["cached_tokens"], u["out_tokens"]), (1500, 500, 100))

    def test_5_refusals(self):
        st, body = self.call("/v1/chat/completions", {"model": "no-such-model", "messages": []})
        self.assertEqual(st, 404)
        st, body = self.call("/v1/chat/completions", {"model": "deepseek-chat", "messages": []}, key="dk_wrong")
        self.assertEqual(st, 401)
        req = urllib.request.Request(self.url + "/v1/models", headers={"Host": "dgo-llm.example.test"})
        models = json.load(urllib.request.urlopen(req, timeout=5))
        self.assertIn("claude-opus-5-5", [m["id"] for m in models["data"]])

    def test_5b_a_client_that_hangs_up_mid_stream_is_still_metered(self):
        body = json.dumps({"model": "gpt-5-nano", "stream": True, "messages": [{"role": "user", "content": "hi"}]})
        port = self.front.server_address[1]
        s = socket.create_connection(("127.0.0.1", port), 5)
        s.sendall((f"POST /v1/chat/completions HTTP/1.1\r\nHost: dgo-llm.example.test\r\nAuthorization: Bearer "
                   f"{self.key}\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n{body}").encode())
        self.assertIn(b"200", s.recv(64))                    # the stream started…
        s.close()                                            # …and the client is gone
        t0 = time.time()
        while time.time() - t0 < 10:
            u = self.srv.store.one("SELECT * FROM usage WHERE model='gpt-5-nano'")
            if u:
                break
            time.sleep(0.2)
        self.assertIsNotNone(u, "a call whose client hung up was never metered")
        self.assertEqual((u["in_tokens"], u["out_tokens"]), (50, 7))   # the upstream's own final count

    def test_6_the_wallet_paid_for_all_of_it(self):
        total = self.srv.store.one("SELECT SUM(cost) c FROM usage WHERE account_id=?", self.aid)["c"]
        self.assertEqual(self.srv.store.balance(self.aid)["plan"], 2400 - total)


if __name__ == "__main__":
    unittest.main()
