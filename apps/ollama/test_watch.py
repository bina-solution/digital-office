#!/usr/bin/env python3
"""test_watch.py — ollama-watch (watch/watch.py): the models in memory and the turns, as «כל מקביל» draws them.

    python3 apps/ollama/test_watch.py        (G72 runs it; standard library only)

Against a stand-in for flowpub that records what would be published, and — for the turn — the timeline's own
reader (apps/any-concurrency/flow_source.py), so the bar is checked where the owner sees it, not only as an event.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


watch = _load("ollama_watch", HERE / "watch" / "watch.py")
flowpub = _load("flowpub_for_watch", REPO / "platform-base" / "redis" / "flowpub.py")
flow_source = _load("flow_source_for_watch", REPO / "apps" / "any-concurrency" / "flow_source.py")


class Pub:
    """flowpub's span halves, recorded: what the watcher would publish."""

    def __init__(self):
        self.events, self.n = [], 0

    def span_start(self, app, kind, title, data=None, link=""):
        self.n += 1
        sid, t0 = f"s{self.n}", 1000 * self.n
        self.events.append(("start", app, kind, title, dict(data or {}), sid))
        return sid, t0, True

    def span_end(self, app, kind, title, sid, t0, failed=False, data=None, link=""):
        self.events.append(("end", app, kind, title, dict(data or {}), sid))
        return True


def _iso(delta):
    return (datetime.now(timezone(timedelta(hours=2))) + delta).isoformat(timespec="microseconds")[:-6] + "123+02:00"


def model(name, size=1_900_000_000, left=timedelta(minutes=10)):
    return {"name": name, "model": name, "size": size, "size_vram": 0, "expires_at": _iso(left)}


class ModelsInMemory(unittest.TestCase):
    def test_a_model_is_a_bar_from_when_it_appears_to_when_it_leaves(self):
        pub = Pub()
        m = watch.Models(pub)
        m.see([model("qwen3:1.7b")])
        m.see([model("qwen3:1.7b")])                    # still there: nothing new
        self.assertEqual([e[0] for e in pub.events], ["start"])
        kind, title, data, sid = pub.events[0][2:]
        self.assertEqual((pub.events[0][1], kind), ("ollama", "model"))
        self.assertEqual(title, "qwen3:1.7b · 1.9 GB · בזיכרון")
        self.assertEqual((data["model"], data["size_mb"], data["pinned"]), ("qwen3:1.7b", 1900, False))
        m.see([])
        self.assertEqual(pub.events[-1][0], "end")
        self.assertEqual(pub.events[-1][5], sid)          # the same bar closed
        self.assertEqual(m.open, {})

    def test_keep_alive_minus_one_is_said(self):
        pub = Pub()
        watch.Models(pub).see([model("llama3:8b", left=timedelta(days=365 * 290))])
        title, data = pub.events[0][3], pub.events[0][4]
        self.assertTrue(title.endswith("נשאר בזיכרון"), title)
        self.assertIs(data["pinned"], True)

    def test_an_engine_that_stops_answering_closes_its_bars_after_three_polls(self):
        pub = Pub()
        m = watch.Models(pub)
        m.see([model("a"), model("b")])
        m.see(None)
        m.see(None)
        self.assertEqual(len(m.open), 2)                  # two silent polls: still believed loaded
        m.see(None)
        ends = [e for e in pub.events if e[0] == "end"]
        self.assertEqual(len(ends), 2)
        self.assertTrue(all(e[4].get("why") == "המנוע לא עונה" for e in ends))
        m.see([model("a")])                                # back: a new bar
        self.assertEqual(pub.events[-1][0], "start")

    def test_the_expiry_as_ollama_writes_it(self):
        self.assertAlmostEqual(watch._expiry_s(_iso(timedelta(minutes=5))), 300, delta=5)
        self.assertIsNone(watch._expiry_s("not a date"))
        self.assertIsNone(watch._expiry_s(None))


def access(uri="/api/chat", method="POST", status=200, ts=1_800_000_000.5, duration=12.4, office=None):
    req = {"method": method, "uri": uri, "headers": {"User-Agent": ["x"]}}
    if office:
        req["headers"]["X-Dgo-Office"] = [office]
    return json.dumps({"level": "info", "ts": ts, "logger": "http.log.access", "msg": "handled request",
                       "request": req, "duration": duration, "status": status})


class Turns(unittest.TestCase):
    def test_a_chat_is_one_end_with_its_start_and_duration(self):
        typ, title, data = watch.turn(access(office="hp-laptop"), "qwen3:1.7b")
        self.assertEqual(typ, "turn.ended")
        self.assertEqual(title, "chat · qwen3:1.7b · hp-laptop · 12.4 שניות")
        self.assertEqual((data["t0"], data["ms"]), (int((1_800_000_000.5 - 12.4) * 1000), 12400))
        self.assertEqual((data["path"], data["status"], data["model"], data["office"]),
                         ("/api/chat", 200, "qwen3:1.7b", "hp-laptop"))

    def test_the_timeline_draws_it_from_its_start(self):
        """The END alone, through flowpub's own fields and the timeline's own reader: the bar starts at t0."""
        typ, title, data = watch.turn(access(ts=time.time() - 1, duration=20.0), None)
        fields = dict(zip(*[iter(flowpub.fields_of("ollama", typ, title, data))] * 2))
        row = flow_source.span_of("dgo:flow:ollama", "1-0", fields, {})
        self.assertEqual(row["s"], data["t0"])
        self.assertGreaterEqual(row["d"], 20_000)          # its duration (and at most a poll of lag)
        self.assertEqual((row["svc"], row["status"]), ("ollama", "success"))

    def test_what_is_not_a_turn(self):
        self.assertIsNone(watch.turn(access(uri="/api/tags", method="GET"), None))
        self.assertIsNone(watch.turn(access(uri="/api/pull"), None))
        self.assertIsNone(watch.turn(access(uri="/", method="GET"), None))
        self.assertIsNone(watch.turn("{not json", None))
        self.assertIsNone(watch.turn("[1, 2]", None))

    def test_a_refused_turn_is_a_failed_bar_and_a_query_is_not_the_path(self):
        typ, title, data = watch.turn(access(uri="/api/generate?x=1", status=500), None)
        self.assertEqual((typ, data["path"]), ("turn.failed", "/api/generate"))
        self.assertNotIn("model", data)
        self.assertEqual(title, "generate · 12.4 שניות")

    def test_a_line_as_caddy_writes_it(self):
        """Captured from caddy:2-alpine running front/Caddyfile (vps1, 2026-11-10): a POST /api/chat with no engine
        behind it (502) and the screen's GET / — Authorization written REDACTED, the office header a list."""
        chat = ('{"level":"error","ts":1794351133.0033607,"logger":"http.log.access.log0","msg":"handled request",'
                '"request":{"remote_ip":"127.0.0.1","remote_port":"55494","client_ip":"127.0.0.1","proto":"HTTP/1.1",'
                '"method":"POST","host":"127.0.0.1:11434","uri":"/api/chat?x=1","headers":{"User-Agent":["Wget"],'
                '"Accept":["*/*"],"Connection":["close"],"X-Dgo-Office":["hp-laptop"],"Authorization":["REDACTED"],'
                '"Content-Type":["application/x-www-form-urlencoded"],"Content-Length":["2"]}},"bytes_read":0,'
                '"user_id":"","duration":0.002274778,"size":0,"status":502,"resp_headers":{"Server":["Caddy"]}}')
        screen = ('{"level":"info","ts":1794351133.1062887,"logger":"http.log.access.log0","msg":"handled request",'
                  '"request":{"method":"GET","host":"127.0.0.1:11434","uri":"/","headers":{"Accept":["text/html"]}},'
                  '"duration":0.007821376,"size":18566,"status":200}')
        typ, title, data = watch.turn(chat, None)
        self.assertEqual((typ, data["path"], data["status"], data["office"]), ("turn.failed", "/api/chat", 502, "hp-laptop"))
        self.assertEqual(title, "chat · hp-laptop · 0.0 שניות")
        self.assertNotIn("REDACTED", json.dumps(data, ensure_ascii=False))
        self.assertIsNone(watch.turn(screen, None))

    def test_an_office_header_that_is_no_office_id_is_not_repeated(self):
        for bad in ("Hp Laptop", "x" * 80, "a\nb", "<script>"):
            typ, title, data = watch.turn(access(office=bad), None)
            self.assertNotIn("office", data, bad)
            self.assertEqual(title, "chat · 12.4 שניות", bad)

    def test_an_answer_with_no_models_list_is_no_answer(self):
        import http.server
        import threading

        class H(http.server.BaseHTTPRequestHandler):
            body = b'{"models": []}'

            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(H.body)

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}"
        try:
            self.assertEqual(watch.ps(url), [])                 # nothing loaded: an answer
            H.body = b'{"error": "busy"}'
            self.assertIsNone(watch.ps(url))                     # not an answer about the models
            H.body = b"not json"
            self.assertIsNone(watch.ps(url))
        finally:
            srv.shutdown()
        self.assertIsNone(watch.ps("http://127.0.0.1:9", timeout=1))   # nothing listening

    def test_two_turns_ending_together_are_two_bars(self):
        a, b = watch.turn(access(), None), watch.turn(access(), None)
        self.assertNotEqual(a[2]["span"], b[2]["span"])


class AccessLogTail(unittest.TestCase):
    def test_a_log_there_at_start_is_read_from_its_end_and_a_roll_loses_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "access.json")
            with open(p, "w") as f:
                f.write("old 1\nold 2\n")
            t = watch.Tail(p)
            self.assertEqual(t.lines(), [])
            with open(p, "a") as f:
                f.write("new 1\nhalf")
            self.assertEqual(t.lines(), ["new 1"])
            with open(p, "a") as f:
                f.write(" done\nlast before the roll\n")
            os.rename(p, os.path.join(d, "access-1.json"))     # Caddy rolls: rename, then a new file
            with open(p, "w") as f:
                f.write("after the roll\n")
            self.assertEqual(t.lines(), ["half done", "last before the roll", "after the roll"])

    def test_a_log_that_appears_later_is_read_from_its_start(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "access.json")
            t = watch.Tail(p)
            self.assertEqual(t.lines(), [])
            with open(p, "w") as f:
                f.write("first\n")
            self.assertEqual(t.lines(), ["first"])


if __name__ == "__main__":
    unittest.main()
