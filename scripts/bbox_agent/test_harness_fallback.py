#!/usr/bin/env python3
"""test_harness_fallback — `bbox agent --office <x>` reaches a linked office whose agent door is not served,
through its harness on the link's app door, and never sends a message twice (r030-204, DGO-1228).

    python3 scripts/bbox_agent/test_harness_fallback.py

The shape it reproduces is the HP of 2026-11-02 (761 commits behind): the link answers the agent's door with
`502` + `X-Dgo-Door: app-down`, while its harness answers `POST /api/<ns>/<method>` on the app's own door, under
the app's Host and Origin. A fake harness plays that door — it refuses any other Host/Origin, and pages its log the
way the real one does (`throughSeq` must be a sequence the log holds; -1 is the empty cut). A fake agent door plays
the four ways it can fail: the link saying app-down, the agent itself answering an error, a connection dropped after
the request, and no listener at all. Python 3.9, standard library only; no engine, no network.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp()          # never the operator's cached tokens
os.environ.pop("BBOX_AGENT_URL", None)
os.environ.pop("BBOX_AGENT_TOKEN", None)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bbox_agent import cli, client  # noqa: E402

HOST = "bina.localhost"
SID = "session-11111111-2222-3333-4444-555555555555"


class Harness:
    """A harness's sessions and the RPC calls it received."""

    def __init__(self):
        self.lock = threading.Lock()
        self.calls: list = []
        self.sessions: dict = {}
        self.add(SID, "Update brief", [("user/message", {"content": [{"type": "text", "text": "take dgo-stable"}]}),
                                       ("turn/start", {}),
                                       ("assistant/message", {"message": {"content": [{"type": "text", "text": "merged and running"}]}}),
                                       ("turn/end", {"reason": "completed"})])
        self.add("session-99999999-2222-3333-4444-555555555555", "Other", [])
        self.reply_after_prompt = None      # (delay, text): an answer that lands a moment after a prompt
        self.reply_at_once = None           # text: an answer whose turn starts BEFORE the prompt call returns
        self.cursor_words = True            # a page past the end names the cursor («past cursor N»), as the harness does
        self.flaky_pages = 0                # this many page calls fail with a harness error first
        self.stuck_paging = False           # every page says hasMore with the same records
        self.empty_prompt_result = False    # session/prompt answers with no `ok` at all

    def add(self, sid, title, events):
        self.sessions[sid] = {"title": title, "events": [], "cwd": "/workspace/office"}
        for t, d in events:
            self.append(sid, t, d)

    def append(self, sid, t, d):
        ev = self.sessions[sid]["events"]
        ev.append({"seq": len(ev), "type": t, "data": d, "time": 1793600000000 + len(ev)})

    def answer(self, method, args):
        with self.lock:
            self.calls.append((method, args))
        req = args.get("request") or {}
        if method == "session/list":
            return {"items": [{"sessionId": k, "blank": not v["events"], "running": False, "cwd": v["cwd"], "updatedAt": 1793600000000,
                               "projections": {"asOfSeq": len(v["events"]) - 1, "values": {"title": v["title"], "turnOutline": [1]}}}
                              for k, v in self.sessions.items()]}
        if method == "session/page":
            s = self.sessions.get(req["address"]["sessionId"])
            if s is None:
                raise KeyError("session/not-found")
            if self.flaky_pages > 0:
                self.flaky_pages -= 1
                raise ValueError("harness/http-500")
            through = req["throughSeq"]
            if through == -1:
                return {"records": [], "hasMore": False}
            if not 0 <= through < len(s["events"]):
                raise ValueError("gateway/bad-request" + (f": throughSeq {through} is past cursor {len(s['events']) - 1}"
                                                          if self.cursor_words else ""))
            if self.stuck_paging:
                return {"records": [{"type": "event", "event": s["events"][through]}], "hasMore": True}
            end = min(through + 1, req.get("beforeSeq", through + 1))
            start = max(0, end - req.get("maxMessages", 20) * 3)
            return {"records": [{"type": "event", "event": e} for e in s["events"][start:end]], "hasMore": start > 0}
        if method == "session/create":
            sid = "session-%08x-0000-0000-0000-000000000000" % len(self.sessions)
            self.sessions[sid] = {"title": None, "events": [], "cwd": req.get("cwd")}
            return {"sessionId": sid}
        if method == "session/rename":
            self.sessions[req["sessionId"]]["title"] = req["title"]
            return {}
        if method == "session/prompt":
            if self.empty_prompt_result:
                return None
            sid = req["sessionId"]
            self.append(sid, "user/message", {"content": req["content"]})
            if self.reply_at_once:
                self.append(sid, "turn/start", {})
                self.append(sid, "assistant/message", {"message": {"content": [{"type": "text", "text": self.reply_at_once}]}})
                self.append(sid, "turn/end", {"reason": "completed"})
            if self.reply_after_prompt:
                delay, text = self.reply_after_prompt

                def later():
                    time.sleep(delay)
                    with self.lock:
                        self.append(sid, "turn/start", {})
                        self.append(sid, "assistant/message", {"message": {"content": [{"type": "text", "text": text}]}})
                        self.append(sid, "turn/end", {"reason": "completed"})
                threading.Thread(target=later, daemon=True).start()
            return {}
        if method == "session/cancel":
            return {}
        raise ValueError("gateway/not-found")


def serve(handler_cls) -> tuple:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


class Suite(unittest.TestCase):
    def setUp(self):
        self.h = h = Harness()

        class HarnessDoor(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
                if self.headers.get("Host") != HOST or self.headers.get("Origin") != f"http://{HOST}":
                    self.send_response(403); self.end_headers(); return          # the app's trusted-host fence
                method = self.path[len("/api/"):]
                try:
                    value = h.answer(method, body["payload"]["args"])
                    res = {} if value is None and method == "session/prompt" else {"ok": True, "value": value}
                except (KeyError, ValueError) as e:
                    words = str(e).strip("'")
                    res = {"ok": False, "error": {"code": words.split(":")[0], "message": words}}
                out = json.dumps({"type": "server-response", "rpcId": body.get("rpcId"), "result": res}).encode()
                self.send_response(200); self.send_header("content-length", str(len(out))); self.end_headers()
                self.wfile.write(out)

        self.door_mode = "app-down"
        suite = self

        class AgentDoor(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _any(self):
                suite.door_hits += 1
                n = int(self.headers.get("content-length") or 0)
                if n:
                    self.rfile.read(n)
                if suite.door_mode == "app-down":                   # the LINK answers: the office is there, the door is not
                    self.send_response(502); self.send_header("X-Dgo-Door", "app-down")
                    self.send_header("content-length", "0"); self.end_headers()
                elif suite.door_mode == "agent-error":              # the AGENT answers, with an error of its own
                    out = b'{"error":"the harness is not answering","code":"harness/unreachable"}'
                    self.send_response(502); self.send_header("content-length", str(len(out))); self.end_headers()
                    self.wfile.write(out)
                elif suite.door_mode == "drop":                     # took the request, then the connection died
                    self.connection.shutdown(socket.SHUT_RDWR)
                elif suite.door_mode == "unauthorized":             # the agent refuses this office's (stale) token
                    out = b'{"error":"missing or wrong Bearer token","code":"auth"}'
                    self.send_response(401); self.send_header("content-length", str(len(out))); self.end_headers()
                    self.wfile.write(out)
            do_GET = do_POST = _any

        self.door_hits = 0
        self.harness_srv, hport = serve(HarnessDoor)
        self.door_srv, dport = serve(AgentDoor)
        self.prov = {"app": "bina-ds", "alias": "bina", "port": dport, "service": "dgo-serve-hp-laptop-bina",
                     "url": f"http://127.0.0.1:{dport}", "served_by": "hp-laptop", "from": "state",
                     "instances": ["dgo_link-serve-hp-laptop-bina-ds-agent"], "instance": "dgo_link-serve-hp-laptop-bina-ds-agent",
                     "rpc": {"office": "hp-laptop", "alias": "bina", "address": "127.0.0.1", "port": hport, "host": HOST}}
        self.saved = (client.remote_provider, client._link_url, client.obtain_token, client.HarnessFallback.POLL)
        client.remote_provider = lambda office="": dict(self.prov)
        client._link_url = lambda alias, office, addr, port: f"http://127.0.0.1:{port}"
        client.HarnessFallback.POLL = 0.05

    def tearDown(self):
        client.remote_provider, client._link_url, client.obtain_token, client.HarnessFallback.POLL = self.saved
        os.environ.pop("BBOX_AGENT_NO_FALLBACK", None)
        self.harness_srv.shutdown(); self.door_srv.shutdown()

    def run_cli(self, *args, token=True, limit=15.0):
        argv = ["--office", "hp-laptop", "--timeout", "10"] + (["--token", "t" * 40] if token else []) + list(args)
        out, err, rc = io.StringIO(), io.StringIO(), [None]

        def go():
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc[0] = cli.main(argv)
        t = threading.Thread(target=go, daemon=True)
        t.start(); t.join(limit)
        self.assertFalse(t.is_alive(), f"`bbox agent {' '.join(args)}` did not return within {limit}s")
        return rc[0], out.getvalue(), err.getvalue()

    def methods(self):
        return [m for m, _ in self.h.calls]

    # ── the door is not served: every verb an operator needs, through the harness
    def test_list(self):
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)
        self.assertIn("agent door is not served", err)
        self.assertEqual(self.methods(), ["session/list"])

    def test_show_by_prefix(self):
        rc, out, err = self.run_cli("show", "11111111")
        self.assertEqual(rc, 0, err)
        self.assertIn(SID, out)
        self.assertIn("Update brief", out)

    def test_send_queues_once(self):
        rc, out, err = self.run_cli("send", SID, "take", "dgo-stable", "now")
        self.assertEqual(rc, 0, err)
        prompts = [a["request"] for m, a in self.h.calls if m == "session/prompt"]
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0]["mode"], "queue")
        self.assertEqual(prompts[0]["content"], [{"type": "text", "text": "take dgo-stable now"}])
        self.assertIn("queued for", out)

    def test_log_reads_the_newest_events(self):
        rc, out, err = self.run_cli("log", SID, "-n", "5")
        self.assertEqual(rc, 0, err)
        self.assertIn("merged and running", out)
        self.assertIn("take dgo-stable", out)

    def test_log_json_events(self):
        rc, out, err = self.run_cli("--json", "log", SID)
        self.assertEqual(rc, 0, err)
        types = [e["type"] for e in json.loads(out)["events"]]
        self.assertEqual(types, ["user", "turn.start", "assistant", "turn.end"])

    def test_new_names_and_prompts(self):
        rc, out, err = self.run_cli("new", "-t", "From the Mac", "hello")
        self.assertEqual(rc, 0, err)
        new = [k for k, v in self.h.sessions.items() if v["title"] == "From the Mac"]
        self.assertEqual(len(new), 1)
        self.assertEqual(self.h.sessions[new[0]]["cwd"], client.HARNESS_OFFICE_ROOT)
        self.assertEqual(self.h.sessions[new[0]]["events"][0]["data"]["content"][0]["text"], "hello")

    def test_wait_prints_the_answer(self):
        rc, out, err = self.run_cli("wait", SID)
        self.assertEqual(rc, 0, err)
        self.assertIn("merged and running", out)

    def test_send_follow_until_the_turn_ends(self):
        self.h.reply_after_prompt = (0.4, "pong from the HP")
        rc, out, err = self.run_cli("send", "-F", SID, "ping")
        self.assertEqual(rc, 0, err)
        self.assertIn("pong from the HP", out)

    def test_rename_and_cancel(self):
        self.assertEqual(self.run_cli("rename", SID, "New", "name")[0], 0)
        self.assertEqual(self.h.sessions[SID]["title"], "New name")
        self.assertEqual(self.run_cli("cancel", SID)[0], 0)
        self.assertIn("session/cancel", self.methods())

    def test_no_token_here_goes_to_the_harness(self):
        def no_token(prov):
            raise client.AgentError("no credential for the agent of hp-laptop in this office's vault", 3)
        client.obtain_token = no_token
        rc, out, err = self.run_cli("list", token=False)
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)
        self.assertEqual(self.door_hits, 0)

    def test_no_listener_goes_to_the_harness(self):
        self.door_srv.shutdown(); self.door_srv.server_close()
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)

    def test_send_follow_when_the_turn_starts_before_the_follow_looks(self):
        # through the relay every read is an engine hop: the turn has often begun before the follow opens
        self.h.reply_at_once = "answered at once"
        rc, out, err = self.run_cli("send", "-F", SID, "ping", limit=10)
        self.assertEqual(rc, 0, err)
        self.assertIn("answered at once", out)
        rc, out, err = self.run_cli("new", "-F", "-t", "fresh", "ping", limit=10)
        self.assertEqual(rc, 0, err)
        self.assertIn("answered at once", out)

    def test_log_zero_returns(self):
        rc, out, err = self.run_cli("log", SID, "-n", "0", limit=8)
        self.assertEqual(rc, 0, err)

    def test_health_is_the_agent_doors_own(self):
        rc, out, err = self.run_cli("health")
        self.assertEqual(rc, 0, err)
        self.assertFalse(json.loads(out)["ok"])
        self.assertNotIn("answering from its harness", err)
        self.assertEqual(self.methods(), [])

    def test_reads_without_the_cursor_words(self):
        # a harness that refuses a page past the end without naming the cursor: found by probing instead
        self.h.cursor_words = False
        rc, out, err = self.run_cli("log", SID, "-n", "5")
        self.assertEqual(rc, 0, err)
        self.assertIn("merged and running", out)

    def test_one_call_finds_the_newest_event(self):
        rc, out, err = self.run_cli("log", SID, "-n", "5")
        self.assertEqual(rc, 0, err)
        # resolve (full id: none) + one page past the end + the page itself — no probing
        self.assertEqual(self.methods(), ["session/page", "session/page"])

    def test_paging_that_makes_no_progress_ends(self):
        fb = client.HarnessFallback(f"http://127.0.0.1:{self.harness_srv.server_address[1]}", HOST, "hp-laptop", "test", 10)
        self.h.stuck_paging = True
        got = fb.events_after(SID, -1, 3)
        self.assertLessEqual(len(got), 4)

    def test_a_follow_survives_a_few_failed_reads(self):
        self.h.reply_after_prompt = (0.3, "after the hiccup")
        self.h.flaky_pages = 0

        def flaky_later():
            time.sleep(0.15)
            self.h.flaky_pages = 3
        threading.Thread(target=flaky_later, daemon=True).start()
        rc, out, err = self.run_cli("send", "-F", SID, "ping")
        self.assertEqual(rc, 0, err)
        self.assertIn("after the hiccup", out)

    def test_a_reply_without_ok_is_not_queued(self):
        self.h.empty_prompt_result = True
        rc, out, err = self.run_cli("send", SID, "lost?")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("queued for", out)

    def test_a_stale_cached_token_with_no_fresh_one(self):
        # the token cached here is stale, and the vault has none to replace it: the 401 still goes to the harness
        client.save_config({f"{client.repo_key()}::hp-laptop": {"token": "s" * 40}})

        def no_token(prov):
            raise client.AgentError("no credential for the agent of hp-laptop in this office's vault", 3)
        client.obtain_token = no_token
        self.door_mode = "unauthorized"
        try:
            rc, out, err = self.run_cli("list", token=False)
        finally:
            client.save_config({})
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)

    def test_a_send_to_a_closed_door(self):
        self.door_srv.shutdown(); self.door_srv.server_close()
        rc, out, err = self.run_cli("send", SID, "through the harness")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.methods().count("session/prompt"), 1)

    def test_an_app_agent_never_falls_back(self):
        saved = client._app_provider
        client._app_provider = lambda app: {"app": app, "service": "x", "port": self.door_srv.server_address[1],
                                            "url": f"http://127.0.0.1:{self.door_srv.server_address[1]}"}
        try:
            c = client.Client(token="t" * 40, app="bina-claude")
            with self.assertRaises(client.AgentError):
                c.sessions()
        finally:
            client._app_provider = saved
        self.assertEqual(self.methods(), [])

    def test_the_office_agent_before_another_agent_app(self):
        # the HP after its update serves bina-claude AND bina-ds; `--office hp-laptop` means its office agent
        saved = (client.remote_provider, client._remote_blocks)
        client.remote_provider = self.saved[0]
        client._remote_blocks = lambda: [{"office": "hp-laptop", "address": "10.79.5.1", "apps": [
            {"app": "bina-claude", "alias": "bina-claude", "agent_api_port": 3091, "link_port": 9005},
            {"app": "bina-ds", "alias": "bina", "agent_api_port": 10080, "link_port": 9005, "host": "bina.localhost"}]}]
        try:
            p = client.remote_provider("hp-laptop")
        finally:
            client.remote_provider, client._remote_blocks = saved
        self.assertEqual((p["app"], p["rpc"]["host"], p["rpc"]["port"]), ("bina-ds", "bina.localhost", 9005))

    def test_a_refused_token_goes_to_the_harness(self):
        # the HP of 2026-11-03: its door answers again, but this office's token for it is stale (401 even fresh)
        self.door_mode = "unauthorized"
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)
        rc, out, err = self.run_cli("send", SID, "once")
        self.assertEqual(rc, 0, err)
        self.assertEqual(self.methods().count("session/prompt"), 1)
        rc, out, err = self.run_cli("log", SID, "-n", "3")
        self.assertEqual(rc, 0, err)
        self.assertIn("once", out)

    def test_what_needs_the_agent_door_says_so(self):
        rc, out, err = self.run_cli("models")
        self.assertEqual(rc, 3)
        self.assertIn("needs hp-laptop's agent door", err)
        rc, out, err = self.run_cli("send", "-f", __file__, SID, "x")
        self.assertNotEqual(rc, 0)
        self.assertIn("agent door", err)
        self.assertNotIn("session/prompt", self.methods())

    def test_the_fence_is_kept(self):
        # the harness answers ONLY under the app's own Host and Origin — the same trust as the screen
        self.prov["rpc"]["host"] = "evil.localhost"
        rc, out, err = self.run_cli("list")
        self.assertNotEqual(rc, 0)
        self.assertIn("403", err)

    # ── the door answered, or may have: never a second way
    def test_the_agents_own_error_is_not_retried(self):
        self.door_mode = "agent-error"
        rc, out, err = self.run_cli("send", SID, "once")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.methods(), [])
        self.assertIn("the harness is not answering", err)

    def test_a_dropped_send_is_not_sent_again(self):
        self.door_mode = "drop"
        rc, out, err = self.run_cli("send", SID, "once")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("session/prompt", self.methods())

    def test_a_dropped_read_goes_to_the_harness(self):
        self.door_mode = "drop"
        rc, out, err = self.run_cli("list")
        self.assertEqual(rc, 0, err)
        self.assertIn("Update brief", out)

    def test_switched_off(self):
        os.environ["BBOX_AGENT_NO_FALLBACK"] = "1"
        rc, out, err = self.run_cli("list")
        self.assertNotEqual(rc, 0)
        self.assertEqual(self.methods(), [])

    def test_a_local_agent_never_falls_back(self):
        c = client.Client(url=f"http://127.0.0.1:{self.door_srv.server_address[1]}", token="t" * 40)
        with self.assertRaises(client.AgentError):
            c.sessions()
        self.assertEqual(self.methods(), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
