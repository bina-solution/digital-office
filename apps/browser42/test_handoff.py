"""The human hand-off (DGO-571): one address, the right tab in front — unit tests, no browser, no network."""
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).parent


def load(name: str, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def stub_websockets() -> None:
    """group-manager.py and broker.py import websockets at the top; the native tests carry none."""
    for name, attr in (("websockets.sync.client", "connect"), ("websockets.asyncio.client", "connect"),
                       ("websockets.asyncio.server", "serve")):
        try:
            __import__(name)
        except ImportError:
            parts = name.split(".")
            for depth in range(1, len(parts) + 1):
                sys.modules.setdefault(".".join(parts[:depth]), types.ModuleType(".".join(parts[:depth])))
            setattr(sys.modules[name], attr, getattr(sys.modules[name], attr, None))


stub_websockets()
MODULE = load("handoff.py", "browser42_handoff")
TOKEN = "test-token"


def write_json(root: Path, relative: str, payload: dict) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class RouteShapeTests(unittest.TestCase):
    def test_slug_is_read_from_the_route_and_nothing_else(self):
        self.assertEqual(MODULE.slug_from_path("/handoff/whatsapp-pair"), "whatsapp-pair")
        self.assertEqual(MODULE.slug_from_path("/handoff/whatsapp-pair/"), "whatsapp-pair")
        self.assertEqual(MODULE.slug_from_path("/handoff/task-7?x=1"), "task-7")
        for bad in ("/handoff/", "/handoff/../etc", "/handoff/Upper", "/handoff/a b", "/handoff/a--b",
                    "/handoff/-a", "/handoff/a/b", "/view/", "/handoffs/a"):
            self.assertIsNone(MODULE.slug_from_path(bad), bad)

    def test_redirect_is_pinned_to_the_view_or_the_mount_and_says_what_was_lost(self):
        self.assertEqual(MODULE.redirect_target(False), "/view/")
        # The console mounts /view/ AT /a/browser42/ (app.json module.url): behind it the view IS the
        # mount — and the mount is this app's constant, whatever the forwarded header said.
        self.assertEqual(MODULE.redirect_target(True), "/a/browser42/")
        self.assertEqual(MODULE.redirect_target(False, "pair"), "/view/?lost=pair")
        self.assertEqual(MODULE.redirect_target(True, "pair"), "/a/browser42/?lost=pair")

    def test_links_are_console_deep_links_from_what_the_office_declares(self):
        self.assertEqual(MODULE.handoff_link("s", {}), "http://console.localhost:8080/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "console.example.example", "AUTH_PROTOCOL": "https"}),
                         "https://console.example.example/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "console.localhost:8080"}),
                         "http://console.localhost:8080/a/browser42/handoff/s")
        self.assertEqual(MODULE.handoff_link("s", {"CONSOLE_BASE_URL": "https://console.x/"}),
                         "https://console.x/a/browser42/handoff/s")
        self.assertEqual(MODULE.view_link({"CONSOLE_BASE_URL": "console.localhost:8080"}), "http://console.localhost:8080/a/browser42/")


class RecordTests(unittest.TestCase):
    def test_a_session_group_or_a_task_names_the_window(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, "groups/pair/group.json", {"slug": "pair", "tab_id": 42, "group_id": 7, "color": "cyan", "url": "https://web.whatsapp.com"})
            write_json(root, "tasks/job/task.json", {"slug": "job", "tab_id": 43, "native_group": {"id": 8, "color": "pink"}})
            self.assertEqual(MODULE.group_record("pair", root)["tab_id"], 42)
            self.assertEqual((MODULE.group_id_of(MODULE.group_record("pair", root)), MODULE.group_color_of(MODULE.group_record("pair", root))), (7, "cyan"))
            self.assertEqual(MODULE.group_record("job", root)["tab_id"], 43)
            self.assertEqual((MODULE.group_id_of(MODULE.group_record("job", root)), MODULE.group_color_of(MODULE.group_record("job", root))), (8, "pink"))
            self.assertIsNone(MODULE.group_record("never", root))
            (root / "groups" / "broken").mkdir()
            (root / "groups" / "broken" / "group.json").write_text("{not json")
            self.assertIsNone(MODULE.group_record("broken", root))


class HandoffRecordTests(unittest.TestCase):
    """The record of a hand-off (DGO-1336): who asked, where it stands, a sentence — never an address."""

    def test_an_address_is_kept_bare(self):
        self.assertEqual(MODULE.bare_url("https://claude.com/cai/login/app-google-auth?open_in_browser=1&hop_nonce=x#f"),
                         "https://claude.com/cai/login/app-google-auth")
        self.assertEqual(MODULE.bare_url("https://claude.ai:8443/login/popup-google-auth?code=c&state=desktop:u.n"),
                         "https://claude.ai:8443/login/popup-google-auth")
        for nothing in ("", None, "not a url", "about:blank"):
            self.assertEqual(MODULE.bare_url(nothing), "")

    def test_needed_opens_an_episode_and_its_end_keeps_it(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opened = MODULE.write_record("claude-signin", "needed", app="bina-claude", sentence="בחרו חשבון", data=root, now=1000)
            self.assertEqual((opened["for"], opened["state"], opened["sentence"], opened["opened_at"]),
                             ("bina-claude", "needed", "בחרו חשבון", 1000))
            self.assertRegex(opened["id"], r"^[0-9a-f]{12}$")
            ended = MODULE.write_record("claude-signin", "done", data=root, now=1030)
            self.assertEqual((ended["id"], ended["for"], ended["opened_at"], ended["updated_at"]),
                             (opened["id"], "bina-claude", 1000, 1030), "the end is the end OF that episode")
            self.assertTrue(ended["sentence"], "an ended record always says something")
            again = MODULE.write_record("claude-signin", "needed", app="bina-claude", data=root, now=1100)
            self.assertNotEqual(again["id"], opened["id"], "a new attempt is a new episode")
            on_disk = json.loads((root / "handoffs" / "claude-signin.json").read_text(encoding="utf-8"))
            self.assertEqual(sorted(on_disk), sorted(MODULE.RECORD_KEYS))
            self.assertFalse(list((root / "handoffs").glob(".*.tmp")), "written whole, nothing left behind")

    def test_an_end_for_an_episode_a_newer_attempt_replaced_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = MODULE.write_record("claude-signin", "needed", app="bina-claude", data=root, now=1)
            new = MODULE.write_record("claude-signin", "needed", app="bina-claude", data=root, now=2)
            self.assertEqual(MODULE.current_episode("claude-signin", root), new["id"])
            with self.assertRaises(MODULE.Superseded):
                MODULE.write_record("claude-signin", "failed", sentence="Google לא ענה", data=root, now=3, episode=old["id"])
            self.assertEqual(json.loads((root / "handoffs" / "claude-signin.json").read_text())["state"], "needed",
                             "the newer attempt's record is untouched")
            ended = MODULE.write_record("claude-signin", "done", data=root, now=4, episode=new["id"])
            self.assertEqual((ended["state"], ended["id"]), ("done", new["id"]))
            self.assertEqual(MODULE.current_episode("never", root), "")

    def test_the_episode_a_caller_minted_is_the_records_id_and_a_malformed_one_is_refused(self):
        """The opener mints its press's episode, so it can end that hand-off even when the open never answers."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            opened = MODULE.write_record("claude-signin", "needed", app="bina-claude", data=root, now=1, episode="a1b2c3")
            self.assertEqual((opened["id"], MODULE.current_episode("claude-signin", root)), ("a1b2c3", "a1b2c3"))
            for malformed in ("A1", "../x", "a b", "", "a1b2c3\n"):
                with self.assertRaises(MODULE.RecordError, msg=repr(malformed)):
                    MODULE.write_record("claude-signin", "done", data=root, now=2, episode=malformed)
            self.assertEqual(json.loads((root / "handoffs" / "claude-signin.json").read_text())["state"], "needed")

    def test_a_person_is_waited_for_only_while_a_needed_record_is_news(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertFalse(MODULE.waiting("claude-signin", root, now=1), "no record, nobody waited for")
            MODULE.write_record("claude-signin", "needed", app="bina-claude", data=root, now=1000)
            self.assertTrue(MODULE.waiting("claude-signin", root, now=1000 + MODULE.NEEDED_TTL_S))
            self.assertFalse(MODULE.waiting("claude-signin", root, now=1001 + MODULE.NEEDED_TTL_S),
                             "a record its dead watcher left holds no bookmark in a reload loop")
            MODULE.write_record("claude-signin", "done", data=root, now=1010)
            self.assertFalse(MODULE.waiting("claude-signin", root, now=1011))
            (root / "handoffs" / "claude-signin.json").write_text('{"state": "needed", "updated_at": "soon"}')
            self.assertFalse(MODULE.waiting("claude-signin", root, now=1011), "a record that cannot be read waits for nobody")

    def test_a_failed_record_without_a_sentence_still_says_why(self):
        with tempfile.TemporaryDirectory() as directory:
            MODULE.write_record("claude-signin", "needed", app="bina-claude", data=Path(directory), now=1)
            failed = MODULE.write_record("claude-signin", "failed", data=Path(directory), now=2)
            self.assertEqual(failed["sentence"], MODULE.ENDED_SENTENCE["failed"])

    def test_what_cannot_be_written_is_refused_by_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for slug, state, app, sentence, says in (
                    ("Bad Slug", "needed", "x", "", "slug"), ("../etc", "done", None, "", "slug"),
                    ("ok", "maybe", None, "", "state"), ("ok", "needed", None, "", "--for"),
                    ("ok", "needed", "Not An App", "", "app id"),
                    ("ok", "failed", None, "see https://claude.ai/login?code=abc&state=x", "query"),
                    ("ok", "failed", None, "hop_nonce=abc", "query")):
                with self.assertRaises(MODULE.RecordError) as caught:
                    MODULE.write_record(slug, state, app=app, sentence=sentence, data=root)
                self.assertIn(says, str(caught.exception))
            self.assertFalse((root / "handoffs").exists() and list((root / "handoffs").iterdir()))

    def test_the_list_is_the_news_and_only_the_allowed_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            write_json(root, "handoffs/fresh.json", {"slug": "fresh", "for": "bina-claude", "state": "needed", "sentence": "s",
                                                     "id": "a1", "opened_at": 990, "updated_at": 990,
                                                     "url": "https://claude.com/x?hop_nonce=leak"})
            write_json(root, "handoffs/stale.json", {"slug": "stale", "for": "x", "state": "needed", "id": "b",
                                                     "updated_at": 1000 - MODULE.NEEDED_TTL_S - 1})
            write_json(root, "handoffs/ended.json", {"slug": "ended", "for": "x", "state": "done", "id": "c", "updated_at": 995})
            write_json(root, "handoffs/old-end.json", {"slug": "old-end", "for": "x", "state": "failed", "id": "d",
                                                       "updated_at": 1000 - MODULE.ENDED_TTL_S - 1})
            write_json(root, "handoffs/odd.json", {"slug": "odd", "state": "weird", "updated_at": 999})
            (root / "handoffs" / "broken.json").write_text("{nope")
            listed = MODULE.read_records(root, now=1000)
            self.assertEqual([r["slug"] for r in listed], ["ended", "fresh"], "newest first; stale, odd and broken left out")
            self.assertEqual(sorted(listed[1]), sorted(MODULE.RECORD_KEYS))
            self.assertNotIn("leak", json.dumps(listed), "whatever else a file holds stays in it")
            self.assertEqual(MODULE.read_records(root / "nowhere", now=1000), [])


class GateTests(unittest.TestCase):
    """Caddy's question before the view and the hand-off (DGO-988), and the link's answer (DGO-1336)."""

    def test_the_link_is_known_by_address_and_asked_again_when_it_moves(self):
        clock = [100.0]
        answers = {"dgo-net": {"10.0.0.7", "::ffff:10.0.0.8"}}
        asked = []

        def resolve(name):
            asked.append(name)
            got = answers.get(name, set())
            return None if got is None else set(got)

        peers = MODULE.Peers(names=("dgo-net", "no-such-name"), resolve=resolve, clock=lambda: clock[0],
                             spawn=lambda look: look())     # a later look runs beside the request; here, at once
        self.assertTrue(peers.admits("10.0.0.7"))
        self.assertTrue(peers.admits("::ffff:10.0.0.8"), "an IPv4 peer on a dual-stack socket is the same address")
        self.assertTrue(peers.admits("10.0.0.8"))
        self.assertFalse(peers.admits(""))
        self.assertEqual(asked, ["dgo-net", "no-such-name"], "one look, while the answer is fresh")
        answers["dgo-net"] = {"10.0.0.9"}                     # the link proxy was recreated
        self.assertFalse(peers.admits("10.0.0.9"), "a miss right after a look is not a reason to ask again")
        clock[0] += MODULE.PEER_MISS_S + 0.5
        self.assertTrue(peers.admits("10.0.0.9"), "after the miss window, a miss asks again")
        self.assertFalse(peers.admits("10.0.0.7"), "the old address is gone with the old container")
        answers["dgo-net"] = None                             # the resolver did not answer this time
        clock[0] += MODULE.PEER_TTL_S + 1
        self.assertTrue(peers.admits("10.0.0.9"), "a look that learned nothing keeps the last good answer")
        answers["dgo-net"] = set()                            # the name is gone: no link here any more
        clock[0] += MODULE.PEER_TTL_S + 1
        self.assertFalse(peers.admits("10.0.0.9"), "a name that no longer exists admits nobody")

    def test_only_the_first_look_holds_a_request_and_a_later_one_runs_beside_it(self):
        spawned, clock = [], [100.0]
        peers = MODULE.Peers(names=("dgo-net",), resolve=lambda name: {"10.0.0.7"}, clock=lambda: clock[0],
                             spawn=spawned.append)
        self.assertTrue(peers.admits("10.0.0.7"), "the first look is made before the first answer")
        self.assertEqual(spawned, [])
        clock[0] += MODULE.PEER_MISS_S + 1
        self.assertFalse(peers.admits("10.0.0.5"), "a miss is answered from what is known now…")
        self.assertEqual(len(spawned), 1, "…while the look it asks for runs beside the request")
        self.assertFalse(peers.admits("10.0.0.6"), "one look at a time")
        self.assertEqual(len(spawned), 1)

    def test_the_resolver_tells_no_such_name_from_not_known_now(self):
        def failing(errno):
            def getaddrinfo(*_):
                raise MODULE.socket.gaierror(errno, "x")
            return getaddrinfo

        with patch.object(MODULE.socket, "getaddrinfo", failing(MODULE.socket.EAI_NONAME)):
            self.assertEqual(MODULE._resolve("dgo-net"), set())
        with patch.object(MODULE.socket, "getaddrinfo", failing(MODULE.socket.EAI_AGAIN)):
            self.assertIsNone(MODULE._resolve("dgo-net"))

    def test_the_link_is_admitted_and_everyone_else_is_the_providers_question(self):
        link = types.SimpleNamespace(admits=lambda address: address == "10.0.0.7")
        asked = []

        def ask(endpoint, headers):
            asked.append((endpoint, dict(headers)))
            return 302, [("Location", "https://auth.example/login?rd=x"), ("Set-Cookie", "dgo_state=s; Path=/")], b""

        status, _, _ = MODULE.gate_answer({MODULE.PEER_HEADER: "10.0.0.7", "Cookie": "c=1"}, peers=link, ask=ask,
                                          env={"DGO_IDENTITY": "forward-auth"})
        self.assertEqual((status, asked), (200, []), "the link is in without a question to the provider")
        status, headers, _ = MODULE.gate_answer({MODULE.PEER_HEADER: "10.0.0.5", "Cookie": "c=1"}, peers=link, ask=ask,
                                                env={"DGO_IDENTITY": "forward-auth"})
        self.assertEqual(status, 302)
        self.assertEqual(asked[0][0], MODULE.PROVIDERS["forward-auth"])
        self.assertIn(("Set-Cookie", "dgo_state=s; Path=/"), headers, "the provider's answer reaches the person whole")
        MODULE.gate_answer({MODULE.PEER_HEADER: "10.0.0.5"}, peers=link, ask=ask, env={})
        self.assertEqual(asked[1][0], MODULE.PROVIDERS["authentik"], "no switch is the platform's default")
        status, _, body = MODULE.gate_answer({MODULE.PEER_HEADER: "10.0.0.5"}, peers=link, ask=ask, env={"DGO_IDENTITY": "nobody"})
        self.assertEqual(status, 502)
        self.assertIn("nobody", body.decode("utf-8"))
        self.assertEqual(len(asked), 2, "an unknown provider is never guessed at")

    def test_a_browser_started_from_an_older_config_asks_the_provider_caddy_names(self):
        """hp-dgo before DGO-1336 set DGO_IDENTITY on Caddy only: a browser container RESTARTED (not recreated)
        with this file has none, and must not ask a provider the office does not run (all but the link refused)."""
        link = types.SimpleNamespace(admits=lambda address: False)
        asked = []

        def ask(endpoint, headers):
            asked.append(endpoint)
            return 200, [], b""

        said = {MODULE.PEER_HEADER: "10.0.0.5", MODULE.IDENTITY_HEADER: "forward-auth"}
        MODULE.gate_answer(said, peers=link, ask=ask, env={})
        MODULE.gate_answer(said, peers=link, ask=ask, env={"DGO_IDENTITY": "authentik"})
        self.assertEqual(asked, [MODULE.PROVIDERS["forward-auth"], MODULE.PROVIDERS["authentik"]],
                         "Caddy's word when the container has none; the container's own when it has one")
        status, _, _ = MODULE.gate_answer({MODULE.PEER_HEADER: "10.0.0.5", MODULE.IDENTITY_HEADER: "open-sesame"},
                                          peers=link, ask=ask, env={})
        self.assertEqual((status, len(asked)), (502, 2), "a header names one of the providers, or the door stays shut")

    def test_the_provider_is_asked_with_the_requests_own_headers_and_its_answer_is_returned_whole(self):
        seen = {}

        class Provider(MODULE.BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                seen.update(path=self.path, headers={k.lower(): v for k, v in self.headers.items()})
                self.send_response(302)
                self.send_header("Location", "https://auth.example/login?rd=https%3A%2F%2Fb42%2Fview%2F")
                self.send_header("Set-Cookie", "dgo_state=one; Path=/")
                self.send_header("Set-Cookie", "other=two; Path=/")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *_):
                return

        server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            endpoint = f"http://127.0.0.1:{server.server_address[1]}/auth/traefik"
            status, headers, _ = MODULE.provider_ask(endpoint, {
                "Cookie": "dgo_session=abc", "X-Forwarded-Host": "browser42.example", "X-Forwarded-Uri": "/view/vnc.html",
                "Connection": "Upgrade", "Upgrade": "websocket", MODULE.PEER_HEADER: "10.0.0.5",
                MODULE.TOKEN_HEADER: "secret", "Host": "browser42-browser-internal:8767"})
        finally:
            server.shutdown()
            server.server_close()
        self.assertEqual(status, 302)
        self.assertEqual(seen["path"], "/auth/traefik")
        self.assertEqual((seen["headers"]["cookie"], seen["headers"]["x-forwarded-host"], seen["headers"]["x-forwarded-uri"]),
                         ("dgo_session=abc", "browser42.example", "/view/vnc.html"))
        for gone in ("upgrade", MODULE.PEER_HEADER.lower(), MODULE.TOKEN_HEADER.lower()):
            self.assertNotIn(gone, seen["headers"], f"{gone} never reaches the provider")
        self.assertEqual(seen["headers"]["host"], "browser42-browser-internal:8767",
                         "the request's own Host goes through, as Caddy's forward_auth passed it")
        self.assertEqual([v for k, v in headers if k.lower() == "set-cookie"], ["dgo_state=one; Path=/", "other=two; Path=/"])

    def test_a_provider_that_does_not_answer_keeps_the_door_shut(self):
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, body = MODULE.provider_ask("http://127.0.0.1:9/auth", {"Cookie": "c"})
        self.assertEqual(status, 502)
        self.assertIn("stays shut", body.decode("utf-8"))


class FrontTests(unittest.TestCase):
    def test_the_command_carries_what_recovers_the_tab_after_a_sleep(self):
        sent = []
        MODULE.front("pair", {"url": "https://web.whatsapp.com/", "color": "cyan"}, budget=1,
                     send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        MODULE.front("job", {"url": "https://claude.ai/x", "native_group": {"color": "pink"}}, budget=1,
                     send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        MODULE.front("bare", None, budget=1, send=lambda command: sent.append(command) or {"ok": True}, clock=lambda: 0.0, sleep=lambda s: None)
        self.assertEqual(sent, [
            {"action": "front", "slug": "pair", "url": "https://web.whatsapp.com/", "label": "pair", "color": "cyan"},
            {"action": "front", "slug": "job", "url": "https://claude.ai/x", "label": "job", "color": "pink"},
            {"action": "front", "slug": "bare", "url": "", "label": "bare"},
        ])

    def test_front_waits_for_the_extension_then_returns_its_answer(self):
        answers = [ConnectionRefusedError("broker restarting"),
                   {"ok": False, "error": {"code": "extension_unavailable", "message": "extension is not connected"}},
                   {"ok": True, "tabId": 42, "groupId": 7, "recovered": True}]
        sent, slept, now = [], [], [0.0]

        def send(command):
            sent.append(command["slug"])
            answer = answers.pop(0)
            if isinstance(answer, Exception):
                raise answer
            return answer

        result = MODULE.front("pair", {}, budget=20, send=send, clock=lambda: now[0], sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
        self.assertEqual(result, {"ok": True, "tabId": 42, "groupId": 7, "recovered": True})
        self.assertEqual((sent, slept), (["pair"] * 3, [1, 1]))

    def test_a_lost_tab_is_a_definite_answer_returned_at_once(self):
        slept = []
        lost = {"ok": False, "error": {"code": "tab_lost", "message": "no live tab for gone, and none at its last address"}}
        result = MODULE.front("gone", {}, budget=20, send=lambda command: lost, clock=lambda: 0.0, sleep=slept.append)
        self.assertEqual((result["error"]["code"], slept), ("tab_lost", []))
        legacy = MODULE.front("gone", {}, budget=20, send=lambda command: {"ok": False, "error": "no live tab"}, clock=lambda: 0.0, sleep=slept.append)
        self.assertEqual((legacy["ok"], slept), (False, []))

    def test_the_budget_ends_the_wait(self):
        now = [0.0]
        result = MODULE.front("pair", {}, budget=3, send=lambda command: {"ok": False, "error": {"code": "extension_unavailable"}},
                              clock=lambda: now[0], sleep=lambda s: now.__setitem__(0, now[0] + s))
        self.assertEqual(result["error"]["code"], "extension_unavailable")
        self.assertGreaterEqual(now[0], 3)


class WakerTests(unittest.TestCase):
    def test_one_launch_is_shared_by_every_request_that_arrives_while_it_runs(self):
        release, calls = threading.Event(), []

        def slow_wake():
            calls.append(1)
            release.wait(5)
            return True

        waker = MODULE.Waker(wake=slow_wake)
        self.assertIsNone(waker.ensure(0.05))            # the first request: still waking
        self.assertIsNone(waker.ensure(0.05))            # a reload joins the same launch
        self.assertEqual(len(calls), 1, "cloakserve was asked ONCE")
        release.set()
        result = waker.ensure(5)
        self.assertTrue(result["awake"])
        self.assertGreaterEqual(result["took"], 0.0)
        self.assertEqual(len(calls), 1)

    def test_an_awake_browser_answers_at_once_and_a_failed_wake_is_reported(self):
        self.assertEqual(MODULE.Waker(wake=lambda: True).ensure(5)["awake"], True)
        self.assertEqual(MODULE.Waker(wake=lambda: False).ensure(5)["awake"], False)

    def test_after_a_finished_launch_the_next_request_asks_again(self):
        calls = []
        waker = MODULE.Waker(wake=lambda: calls.append(1) or True)
        waker.ensure(5)
        waker.ensure(5)
        self.assertEqual(len(calls), 2, "a later sleep must be woken by a later request")


class FakeWaker:
    def __init__(self, result):
        self.result = result

    def ensure(self, timeout):
        return self.result


class PresentationTests(unittest.TestCase):
    def test_only_a_fullscreen_chromium_window_gets_f11(self):
        calls = []

        def run(argv):
            calls.append(argv)
            if argv[0] == "wmctrl":
                return ("0x01 0 chromium.Chromium      host chromium\n"
                        "0x02 0 fluxbox.fluxbox        host toolbar\n"
                        "0x03 0 chromium.Chromium      host other\n")
            if argv[0] == "xprop":
                return "_NET_WM_STATE(ATOM) = _NET_WM_STATE_FULLSCREEN" if argv[2] == "0x01" else "_NET_WM_STATE(ATOM) = _NET_WM_STATE_MAXIMIZED_VERT"
            return ""

        self.assertEqual(MODULE.present_standard(run), 1)
        keys = [argv for argv in calls if argv[0] == "xdotool"]
        self.assertEqual(keys, [["xdotool", "windowactivate", "--sync", "0x01", "key", "--window", "0x01", "F11"]])

    def test_no_x_tools_means_nothing_switched(self):
        self.assertEqual(MODULE.present_standard(lambda argv: ""), 0)


class PerformTests(unittest.TestCase):
    def test_while_the_browser_is_still_waking_nothing_else_happens(self):
        touched = []
        result = MODULE.perform("pair", {"tab_id": 1}, waker=FakeWaker(None),
                                front=lambda slug, record: touched.append("front"), present=lambda: touched.append("present"),
                                touch=lambda: touched.append("touch"), sleep=lambda s: touched.append("sleep"))
        self.assertEqual((result, touched), ({"slug": "pair", "waking": True}, []))

    def test_awake_order_is_wake_then_use_then_front_then_strip_and_a_failed_front_is_lost_not_fatal(self):
        order = []
        result = MODULE.perform(
            "pair", {"tab_id": 42, "group_id": 7, "state": "active"}, waker=FakeWaker({"awake": True, "took": 0.01}),
            front=lambda slug, record: order.append(f"front:{slug}:{record['tab_id']}") or {"ok": False, "error": {"code": "tab_lost"}},
            present=lambda: order.append("present") or 1,
            touch=lambda: order.append("touch"),
            sleep=lambda s: order.append(f"sleep:{s}"))
        self.assertEqual(order, ["touch", "front:pair:42", "present"])
        self.assertEqual((result["waking"], result["awake"], result["cold"], result["front"], result["lost"]), (False, True, False, False, True))
        self.assertEqual((result["presentation_switched"], result["tab_id"], result["group_id"], result["state"]), (1, 42, 7, "active"))

    def test_after_a_cold_launch_the_compact_press_is_given_time_before_the_look(self):
        order = []
        result = MODULE.perform("pair", {"tab_id": 1}, waker=FakeWaker({"awake": True, "took": MODULE.COLD_LAUNCH_S + 1}),
                                front=lambda slug, record: {"ok": True}, present=lambda: order.append("present") or 0,
                                touch=lambda: order.append("touch"), sleep=lambda s: order.append(f"sleep:{s}"))
        self.assertEqual(order, ["touch", f"sleep:{MODULE.COMPACT_SETTLE_S}", "present"])
        self.assertEqual((result["cold"], result["front"], result["lost"]), (True, True, False))


class NoticeTests(unittest.TestCase):
    def post(self, **kwargs):
        posts = []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        def fake_urlopen(request, timeout=None):
            posts.append((request.full_url, json.loads(request.data.decode("utf-8")), timeout))
            return Response()

        with patch.object(MODULE, "urlopen", side_effect=fake_urlopen):
            ok = MODULE.notify_human(**kwargs)
        return ok, posts

    def test_the_notice_is_one_per_slug_in_hebrew_with_the_link(self):
        link = "http://console.localhost:8080/a/browser42/handoff/pair"
        ok, posts = self.post(slug="pair", body="נדרש אדם", link=link, url="http://notifications:8977/")
        self.assertTrue(ok)
        url, body, timeout = posts[0]
        self.assertEqual(url, "http://notifications:8977/api/notifications")
        self.assertEqual((body["source"], body["source_id"], body["level"], body["link"]), ("browser42", "handoff:pair", "warning", link))
        self.assertIn("pair", body["title"])
        self.assertTrue(any("֐" <= ch <= "׿" for ch in body["title"]), "the title is Hebrew")
        self.assertIn(link, body["body"])
        self.assertEqual(body["meta"], {"app": "browser42", "slug": "pair"})
        self.assertLessEqual(timeout, 5)

    def test_an_episode_is_the_same_last_seen_so_a_repeat_is_not_new_again(self):
        _, first = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_000)
        _, again = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_000)
        _, later = self.post(slug="pair", body="x", link="y", url="http://n", since=1_790_000_060)
        self.assertEqual(first[0][1]["meta"]["lastSeen"], "2026-09-21T14:13:20+00:00")   # the centre's own isoformat, UTC
        self.assertEqual(first[0][1]["meta"]["lastSeen"], again[0][1]["meta"]["lastSeen"])
        self.assertGreater(later[0][1]["meta"]["lastSeen"], first[0][1]["meta"]["lastSeen"])

    def test_no_address_means_no_notice_and_a_failure_is_swallowed(self):
        with patch.object(MODULE, "urlopen", side_effect=AssertionError("must not be called")):
            self.assertFalse(MODULE.notify_human("pair", "x", "y", url=""))
        with patch.object(MODULE, "urlopen", side_effect=urllib.error.URLError("down")):
            self.assertFalse(MODULE.notify_human("pair", "x", "y", url="http://notifications:8977"))


class ServerTests(unittest.TestCase):
    """The route itself, over HTTP on a loopback port — the browser work replaced by fakes."""

    @classmethod
    def setUpClass(cls):
        cls.server = MODULE.ThreadingHTTPServer(("127.0.0.1", 0), MODULE.Handler)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self._token = MODULE.TOKEN
        MODULE.TOKEN = TOKEN

    def tearDown(self):
        MODULE.TOKEN = self._token

    def get(self, path, headers=None, token=TOKEN):
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(NoRedirect)
        sent = dict(headers or {})
        if token is not None:
            sent[MODULE.TOKEN_HEADER] = token
        request = urllib.request.Request(self.base + path, headers=sent)
        try:
            with opener.open(request, timeout=5) as response:
                return response.status, dict(response.headers), response.read()
        except urllib.error.HTTPError as error:
            return error.code, dict(error.headers), error.read()

    def test_a_known_slug_is_performed_and_sent_to_the_view_or_the_pinned_mount(self):
        performed = []
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42, "group_id": 7}), \
                patch.object(MODULE, "perform", side_effect=lambda slug, record: performed.append((slug, record)) or {"slug": slug, "waking": False, "lost": False}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, _ = self.get("/handoff/pair")
            self.assertEqual((status, headers["Location"]), (302, "/view/"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "/a/browser42"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "//evil.example/x"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/"), "the header is a hint, never the address")
        self.assertEqual(performed, [("pair", {"tab_id": 42, "group_id": 7})] * 3)

    def test_a_tab_that_could_not_be_fronted_is_said_not_pretended(self):
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42}), \
                patch.object(MODULE, "perform", return_value={"slug": "pair", "waking": False, "lost": True}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, _ = self.get("/handoff/pair")
            self.assertEqual((status, headers["Location"]), (302, "/view/?lost=pair"))
            status, headers, _ = self.get("/handoff/pair", {"X-Forwarded-Prefix": "/a/browser42"})
            self.assertEqual((status, headers["Location"]), (302, "/a/browser42/?lost=pair"))

    def test_while_waking_the_page_says_so_and_reloads_itself(self):
        with patch.object(MODULE, "group_record", return_value={"tab_id": 42}), \
                patch.object(MODULE, "perform", return_value={"slug": "pair", "waking": True}), \
                contextlib.redirect_stdout(io.StringIO()):
            status, headers, body = self.get("/handoff/pair")
        self.assertEqual((status, headers["Refresh"]), (200, "5"))
        self.assertIn("text/html", headers["Content-Type"])
        text = body.decode("utf-8")
        self.assertIn('http-equiv="refresh" content="5"', text)
        self.assertIn("«pair»", text)
        self.assertIn('dir="rtl"', text)
        self.assertNotIn("#", text.split("<body>", 1)[1], "no colour of its own")

    def test_without_the_edge_token_the_hand_off_is_refused(self):
        with patch.object(MODULE, "perform", side_effect=AssertionError("must not perform")), \
                patch.object(MODULE, "group_record", return_value={"tab_id": 42}):
            status, _, body = self.get("/handoff/pair", token=None)
            self.assertEqual((status, json.loads(body)["error"]["code"]), (403, "forbidden"))
            status, _, _ = self.get("/handoff/pair", token="wrong")
            self.assertEqual(status, 403)
            with patch.object(MODULE, "TOKEN", ""):
                status, _, _ = self.get("/handoff/pair", token="")
                self.assertEqual(status, 403, "an empty token refuses everything")
        status, _, body = self.get("/healthz", token=None)
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))

    def test_a_hand_off_whose_tab_is_still_being_opened_waits_and_wakes_nothing(self):
        """`bbox b42 open` records the hand-off before it wakes the browser: the person arrives first."""
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "DATA", Path(directory)), \
                patch.object(MODULE, "perform", side_effect=AssertionError("nothing to front yet")), \
                patch.object(MODULE.WAKER, "ensure", side_effect=AssertionError("the opener wakes it, not the route")):
            MODULE.write_record("claude-signin", "needed", app="bina-claude")
            status, headers, body = self.get("/handoff/claude-signin")
            self.assertEqual((status, headers["Refresh"]), (200, "5"))
            self.assertIn("«claude-signin»", body.decode("utf-8"))
            MODULE.write_record("claude-signin", "done")
            status, _, body = self.get("/handoff/claude-signin")
            self.assertEqual((status, json.loads(body)["error"]["code"]), (404, "no_such_group"), "an ended one is not waited for")

    def test_the_list_and_the_gate_are_behind_the_same_token(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "DATA", Path(directory)):
            MODULE.write_record("claude-signin", "needed", app="bina-claude", sentence="בחרו חשבון")
            status, _, body = self.get("/handoff/")
            listed = json.loads(body)
            self.assertEqual((status, [r["slug"] for r in listed["handoffs"]]), (200, ["claude-signin"]))
            self.assertEqual(self.get("/handoff", token=None)[0], 403)
        with patch.object(MODULE, "gate_answer", return_value=(200, [("Cache-Control", "no-store")], b"")) as gate:
            status, headers, _ = self.get("/gate", {MODULE.PEER_HEADER: "10.0.0.7"})
            self.assertEqual((status, headers["Cache-Control"]), (200, "no-store"))
            self.assertEqual(gate.call_args[0][0][MODULE.PEER_HEADER], "10.0.0.7")
            self.assertEqual(self.get("/gate", token="wrong")[0], 403)
        with patch.object(MODULE, "gate_answer", return_value=(302, [("Location", "https://auth.example/login")], b"")):
            status, headers, _ = self.get("/gate")
            self.assertEqual((status, headers["Location"]), (302, "https://auth.example/login"))

    def test_an_unknown_slug_and_a_wrong_path_are_404_by_name(self):
        with patch.object(MODULE, "group_record", return_value=None), \
                patch.object(MODULE, "perform", side_effect=AssertionError("nothing to perform")):
            status, _, body = self.get("/handoff/never")
            error = json.loads(body)["error"]
            self.assertEqual((status, error["code"]), (404, "no_such_group"))
            self.assertIn("was ever opened", error["message"])
            self.assertNotIn("or it was closed", error["message"])
            status, _, body = self.get("/handoff/../etc")
            self.assertEqual(status, 404)
            status, _, body = self.get("/view/")
            self.assertEqual((status, json.loads(body)["error"]["code"]), (404, "not_found"))


class CliTests(unittest.TestCase):
    def test_link_prints_the_address_and_what_it_brings_to_the_front(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "DATA", Path(directory)), \
                patch.dict("os.environ", {"CONSOLE_BASE_URL": "console.localhost:8080", "AUTH_PROTOCOL": "http"}):
            write_json(Path(directory), "groups/pair/group.json", {"slug": "pair", "tab_id": 42, "group_id": 7, "url": "https://web.whatsapp.com"})
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "pair"]), 0)
            answer = json.loads(out.getvalue())
            self.assertEqual((answer["ok"], answer["url"], answer["tab_id"], answer["group_id"], answer["page"]),
                             (True, "http://console.localhost:8080/a/browser42/handoff/pair", 42, 7, "https://web.whatsapp.com"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "never"]), 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "no_such_group")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(MODULE.main(["handoff.py", "link", "Not A Slug"]), 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "usage")

    def test_record_and_list_are_the_hands_of_whoever_ends_the_errand(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(MODULE, "DATA", Path(directory)):
            def run(*args):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = MODULE.main(["handoff.py", *args])
                return code, json.loads(out.getvalue())

            code, answer = run("record", "claude-signin", "needed", "--for", "bina-claude", "--sentence", "בחרו חשבון")
            self.assertEqual((code, answer["handoff"]["state"], answer["handoff"]["for"]), (0, "needed", "bina-claude"))
            code, answer = run("record", "claude-signin", "failed", "--sentence", "Google לא ענה")
            self.assertEqual((code, answer["handoff"]["state"], answer["handoff"]["sentence"]), (0, "failed", "Google לא ענה"))
            code, answer = run("list")
            self.assertEqual((code, [r["state"] for r in answer["handoffs"]]), (0, ["failed"]))
            code, answer = run("record", "claude-signin", "done", "--bogus")
            self.assertEqual((code, answer["error"]["code"]), (2, "usage"))
            code, answer = run("record", "claude-signin", "failed", "--sentence", "state=leak")
            self.assertEqual((code, answer["error"]["code"]), (2, "usage"))
            code, answer = run("record", "claude-signin", "done", "--episode", "not-the-open-one")
            self.assertEqual((code, answer["error"]["code"]), (3, "superseded"))


class WiringTests(unittest.TestCase):
    """The pieces the route depends on, read where they live."""

    def test_the_broker_accepts_front(self):
        broker = load("broker.py", "browser42_broker_for_handoff")
        self.assertIn("front", broker.SUPPORTED_ACTIONS)

    def test_the_extension_fronts_in_the_same_window_and_recovers_a_tab_by_its_last_address(self):
        source = (HERE / "extension" / "worker-1.2.js").read_text(encoding="utf-8")
        self.assertIn("? frontSession(command)", source)
        body = source[source.index("async function frontSession"):source.index("async function listSessions")]
        self.assertIn("recoverSession(slug, stored, command)", body)
        self.assertIn("chrome.tabs.update(existing.tab.id, { active: true })", body)
        self.assertIn("code: 'tab_lost'", body)
        for never in ("tabs.create", "windows.create"):
            self.assertNotIn(never, body)
        recover = source[source.index("async function recoverSession"):source.index("async function frontSession")]
        self.assertIn("stored?.lastUrl, command.url", recover)
        self.assertIn("entry.title === slug", recover, "the restored group's NAME decides first")
        self.assertIn("others.has(title)", recover, "another session's restored tab is never a candidate")
        self.assertIn("if (exact.length > 1) return null", recover, "ambiguity is lost, not a guess")
        self.assertIn("await claimTab(id, slug)", recover, "the recovered tab is re-tagged")
        # DGO-1336: the last address is kept current — BARE (origin and path), never a sign-in's query
        self.assertIn("session.lastUrl = bareUrl(changeInfo.url)", source.replace("current.lastUrl", "session.lastUrl"), "the last address is kept current")
        self.assertIn("lastUrl: bareUrl(command.url)", source)
        self.assertEqual(re.findall(r"lastUrl\s*(?::|=(?!=))(?!\s*bareUrl\()[^,;\n]*", source.split("async function ownerForTab", 1)[1]), [],
                         "every address the extension keeps goes through bareUrl")
        self.assertIn("bareStoredAddresses().catch", source, "what an older build kept is made bare at start")

    def test_the_gate_asks_the_handoff_server_which_knows_the_link_and_the_provider(self):
        caddyfile = (HERE / "caddy" / "Caddyfile").read_text(encoding="utf-8")
        gate = caddyfile[caddyfile.index("(gate) {"):caddyfile.index("(gate-headers) {")]
        self.assertIn("forward_auth {$BROWSER42_UPSTREAM}:8767", gate)
        self.assertIn("uri /gate", gate)
        self.assertIn("header_up X-Browser42-Peer {http.request.remote.host}", gate, "Caddy writes the peer, a client cannot")
        self.assertIn("header_up X-Browser42-Handoff {$MCP_TOKEN}", gate)
        self.assertIn("header_up X-Browser42-Identity {$DGO_IDENTITY:authentik}", gate,
                      "Caddy names the provider (with a default: an empty value would not parse)")
        self.assertNotIn("gate-authentik", caddyfile, "the provider's endpoints live in handoff.PROVIDERS now")
        for door in ("handle_path /view/*", "handle /websockify", "handle /handoff/*"):
            block = caddyfile[caddyfile.index(door):]
            self.assertIn("import gate", block[:block.index("}")], f"{door} is gated")
        agent = caddyfile[caddyfile.index(":8766, :8931 {"):]
        self.assertIn("handle /v1/handoffs", agent)
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        browser = compose[compose.index("  browser42-browser:"):compose.index("  browser42-mcp:")]
        self.assertIn("DGO_IDENTITY: ${DGO_IDENTITY:-authentik}", browser, "the gate's provider is read where it is asked")
        caddy = compose[compose.index("  browser42-caddy:"):]
        self.assertIn("DGO_IDENTITY: ${DGO_IDENTITY:-authentik}", caddy[:caddy.index("volumes:")], "…and said by Caddy")
        self.assertIn("BROWSER42_LINK_PEERS: ${BROWSER42_LINK_PEERS:-dgo-net}", browser)
        self.assertIn("- ./extension:/extension:ro", browser, "the extension lands without an image rebuild")
        self.assertEqual(set(MODULE.PROVIDERS), {"authentik", "forward-auth"})

    def test_the_hooks_open_and_end_a_hand_off(self):
        opener = (HERE / "hooks" / "open").read_text(encoding="utf-8")
        self.assertIn("python3 /group-manager.py handoff-open", opener)
        self.assertTrue(os.access(HERE / "hooks" / "open", os.X_OK), "a hook is executable (G31)")
        ender = (HERE / "hooks" / "handoff").read_text(encoding="utf-8")
        for spelled in ('record "${slug}" done "$@"', 'record "${slug}" failed --sentence "${sentence}" "$@"',
                        "/handoff.py list"):
            self.assertIn(spelled, ender)
        waiter = (HERE / "hooks" / "await").read_text(encoding="utf-8")
        self.assertNotIn("bbox b42 open whatsapp-pair", waiter, "a tab to await on is a group, never a hand-off")
        runner = (HERE / "task-runner.py").read_text(encoding="utf-8")
        self.assertIn('== "/v1/handoffs"', runner)

    def test_the_ending_hook_hands_on_what_it_was_given_and_never_takes_a_flag_for_the_sentence(self):
        """`handoff <slug> --failed --episode <id>` with no sentence: `--episode` is not the sentence, and the
        record says the default one (the second reader of DGO-1336). Run with a docker that prints its argv."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            hooks = root / "apps" / "browser42" / "hooks"
            hooks.mkdir(parents=True)
            shutil.copy2(HERE / "hooks" / "handoff", hooks / "handoff")
            (root / "scripts").mkdir()
            (root / "scripts" / "lib.sh").write_text('die() { echo "$*" >&2; exit 1; }\n')
            (root / "bin").mkdir()
            docker = root / "bin" / "docker"
            docker.write_text('#!/bin/sh\n[ "$1" = ps ] && { echo browser42-browser-1; exit 0; }\n'
                              'shift 4\nfor a in "$@"; do printf "<%s>" "$a"; done\n')
            docker.chmod(0o755)
            env = {**os.environ, "PATH": f"{root / 'bin'}{os.pathsep}{os.environ.get('PATH', '')}"}

            def ran(*args):
                return subprocess.run([str(hooks / "handoff"), *args], env=env, capture_output=True,
                                      text=True, check=True, timeout=20).stdout

            for args, handed in (
                    (("claude-signin", "--failed", "--episode", "e1"),
                     "</handoff.py><record><claude-signin><failed><--sentence><><--episode><e1>"),
                    (("claude-signin", "--failed", "Google לא ענה", "--episode", "e1"),
                     "</handoff.py><record><claude-signin><failed><--sentence><Google לא ענה><--episode><e1>"),
                    (("claude-signin", "--failed"), "</handoff.py><record><claude-signin><failed><--sentence><>"),
                    (("claude-signin", "--done", "--episode", "e1"), "</handoff.py><record><claude-signin><done><--episode><e1>"),
                    (("--list",), "</handoff.py><list>"),
                    (("claude-signin",), "</handoff.py><link><claude-signin>")):
                self.assertEqual(ran(*args), handed, args)

    def test_caddy_routes_the_handoff_with_the_token_and_carries_the_lost_marker(self):
        caddyfile = (HERE / "caddy" / "Caddyfile").read_text(encoding="utf-8")
        self.assertIn("handle /handoff/*", caddyfile)
        handle = caddyfile[caddyfile.index("handle /handoff/*"):caddyfile.index("redir / /view/")]
        # The internal-only alias: the browser's hand-off listens on browser42's network alone, and
        # caddy sits on both networks, where the bare service name may resolve to the other (DGO-983).
        # Caddy takes it from its compose environment, so a change of it recreates Caddy.
        self.assertIn("reverse_proxy {$BROWSER42_UPSTREAM}:8767", handle)
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("BROWSER42_UPSTREAM: browser42-browser-internal", compose)
        self.assertIn("header_up X-Browser42-Handoff {$MCP_TOKEN}", handle)
        self.assertIn("path=websockify&{query}", caddyfile, "the /view/ redir keeps ?lost=")

    def test_the_viewer_says_what_was_lost(self):
        navigation = (HERE / "browser-navigation.js").read_text(encoding="utf-8")
        self.assertIn('get("lost")', navigation)
        self.assertIn("UI.showStatus", navigation)

    def test_the_console_passthrough_strips_the_mount_for_the_handoff_prefix(self):
        manifest = json.loads((HERE / "app.json").read_text(encoding="utf-8"))
        passthroughs = manifest["routing"][0]["module"]["passthrough"]
        handoff = [spec for spec in passthroughs if spec["path"] == "/handoff"]
        self.assertEqual(handoff, [{"path": "/handoff", "transport": "http", "match": "prefix", "strip_mount_prefix": True}])

    def test_every_browser42_container_that_speaks_of_the_handoff_mounts_the_file(self):
        compose = (HERE / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertEqual(compose.count("- ./handoff.py:/handoff.py:ro"), 3, "browser, task runner, watchdog")
        self.assertIn("- '8767'", compose)
        self.assertIn("BROWSER42_MCP_TOKEN: ${BROWSER42_MCP_TOKEN:-}", compose, "the browser holds the token Caddy sends")
        # Kept alive since DGO-1336: the live view's gate asks it, so a crash would close the whole screen.
        self.assertRegex((HERE / "start-browser.sh").read_text(encoding="utf-8"),
                         r"\( while :; do\s+python3 /handoff\.py serve \|\| true\n(?:[^\n]*\n){1,3}?\s*done \) &")


class ExtensionLogicTests(unittest.TestCase):
    """The worker's own functions, run in node against a fake `chrome` (test_worker.mjs)."""

    @unittest.skipUnless(shutil.which("node"), "node is not on this machine — the rule is stated in recoverSession's comment")
    def test_two_groups_on_one_address_never_swap_tabs(self):
        run = subprocess.run([shutil.which("node"), str(HERE / "test_worker.mjs")], capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("7 cases ok", run.stdout)


class CaptchaHandoffTests(unittest.TestCase):
    def test_exhausted_rounds_hand_the_owner_the_link_and_tell_him_once_per_task(self):
        gm = load("group-manager.py", "browser42_group_manager_for_handoff")
        notices = []
        task = {"slug": "whatsapp-pair", "state": "active", "created_at": 1_790_000_000,
                "captcha": {"attempts": gm.CAPTCHA_MAX_ATTEMPTS, "history": []}}
        with patch.object(gm, "read_task", return_value=task), \
                patch.object(gm, "task_connection", return_value=(None, None, None)), \
                patch.object(gm.handoff, "notify_human", side_effect=lambda slug, body, link, **kw: notices.append((slug, body, link, kw.get("since"))) or True), \
                patch.dict("os.environ", {"CONSOLE_BASE_URL": "console.localhost:8080", "AUTH_PROTOCOL": "http"}):
            with self.assertRaises(gm.BrowserTaskError) as caught:
                gm.task_captcha("whatsapp-pair", "click", "0")
        link = "http://console.localhost:8080/a/browser42/handoff/whatsapp-pair"
        self.assertEqual(caught.exception.code, "captcha_attempts_exhausted")
        self.assertIn(link, str(caught.exception))
        self.assertNotIn("browser42.localhost:8080/view/", str(caught.exception))
        self.assertEqual([(slug, found, since) for slug, _, found, since in notices], [("whatsapp-pair", link, 1_790_000_000)])
        self.assertIn("captcha", notices[0][1])


if __name__ == "__main__":
    unittest.main()
